"""Batch collection runner for detached workers (0057 M1).

Batch jobs enumerate a platform exhaustively — creator full works first —
and write every item to ``results.jsonl`` inside the job directory.  The
public surface only ever returns the file path, the item count and a small
sample; agents page through the file with ``resource_batch_read`` instead
of pulling the whole list into the conversation.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .errors import DomainError
from .job_state import (
    CANCEL_FLAG_NAME,
    FileCancelEvent,
    read_job,
    read_request,
    write_job,
)

LOGGER = logging.getLogger(__name__)

RESULTS_NAME = "results.jsonl"
BATCH_MODES = frozenset({"creator_full"})
MAX_ITEMS_HARD_CAP = 1000
BATCH_READ_PAGE_CAP = 50


def public_item(resource: dict[str, Any]) -> dict[str, Any]:
    """Compact, conversation-safe record for one enumerated item."""

    metadata = resource.get("metadata") or {}
    item: dict[str, Any] = {
        "platform": resource.get("platform"),
        "title": resource.get("title"),
        "resource_type": resource.get("resource_type"),
        "url": resource.get("source_url"),
    }
    for key in ("author", "published_at", "language", "download_feasibility"):
        if isinstance(metadata, dict) and metadata.get(key) not in (None, ""):
            item[key] = metadata[key]
    return item


def run_batch_collect(directory: Path, service: Any = None) -> int:
    """Execute one batch_collect job; owns job.json while running."""

    request = read_request(directory)
    mode = str(request.get("mode") or "")
    if mode not in BATCH_MODES:
        write_job(
            directory,
            {
                **read_job(directory),
                "status": "failed",
                "failures": [
                    {
                        "code": "PARAM_INVALID",
                        "message": f"未知批量模式 {mode!r}；当前支持 {sorted(BATCH_MODES)}",
                        "retryable": False,
                    }
                ],
            },
        )
        return 1

    platform = str(request.get("platform") or "")
    creator_id = str(request.get("creator_id") or "")
    max_items = _safe_int(request.get("max_items"), 500)
    cancel = FileCancelEvent(directory / CANCEL_FLAG_NAME)

    write_job(
        directory,
        {**read_job(directory), "status": "running", "pid": os.getpid()},
    )

    if service is None:
        from .service import ResourceService

        service = ResourceService(recover_jobs=False)

    failures: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    try:
        search_creator = getattr(service.search_provider, "search_creator", None)
        if not callable(search_creator):
            raise DomainError(
                "FEATURE_NOT_SUPPORTED", f"平台 {platform} 不支持创作者枚举"
            )
        raw, platform_runs = search_creator(
            platform, creator_id, max_items, cancel_event=cancel
        )
        error = None
        for run in platform_runs or []:
            for query_run in run.get("query_runs") or []:
                if isinstance(query_run.get("error"), dict):
                    error = query_run["error"]
        if error and not raw:
            raise DomainError(
                str(error.get("code") or "PARTIAL_FAILURE"),
                str(error.get("message") or "批量枚举失败"),
                retryable=bool(error.get("retryable")),
            )
        items = [
            public_item(resource)
            for resource in raw
            if isinstance(resource, dict)
            and resource.get("source_url")
            and resource.get("title")
        ]
    except DomainError as exc:
        failures.append(
            {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
        )
    except Exception as exc:  # noqa: BLE001 - never leave a running status behind
        LOGGER.exception("batch collect crashed")
        failures.append(
            {
                "code": "WORKER_CRASHED",
                "message": f"{type(exc).__name__}: {exc}",
                "retryable": True,
            }
        )

    if cancel.is_set():
        final = "cancelled"
    elif failures and items:
        final = "partial"
    elif items:
        final = "succeeded"
    else:
        final = "failed"

    files: list[dict[str, Any]] = []
    if items:
        path = directory / RESULTS_NAME
        path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )
        files = [{"filename": RESULTS_NAME, "path": str(path), "lines": len(items)}]

    write_job(
        directory,
        {
            **read_job(directory),
            "status": final,
            "pid": os.getpid(),
            "total": len(items),
            "completed": len(items),
            "files": files,
            "failures": failures,
        },
    )
    LOGGER.info(
        "batch %s finished: %s (%d items)", request.get("job_id"), final, len(items)
    )
    return 0


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
