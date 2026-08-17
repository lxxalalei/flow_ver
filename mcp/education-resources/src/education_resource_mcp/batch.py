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
import urllib.parse
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
BATCH_MODES = frozenset({"creator_full", "time_range_search", "catalog_expand"})
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
    for key in ("activity_id", "textbook"):
        if resource.get(key) not in (None, ""):
            item[key] = resource[key]
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
        if mode == "creator_full":
            items = _collect_creator_full(
                service, platform, creator_id, max_items, cancel
            )
        elif mode == "time_range_search":
            items = _collect_time_range(
                service,
                platform,
                str(request.get("keyword") or ""),
                str(request.get("start_day") or ""),
                str(request.get("end_day") or ""),
                max_items,
                cancel,
            )
        elif mode == "catalog_expand":
            items = _collect_catalog_expand(
                service, platform, list(request.get("specs") or []), cancel
            )
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


def _collect_creator_full(
    service: Any, platform: str, creator_id: str, max_items: int, cancel: Any
) -> list[dict[str, Any]]:
    search_creator = getattr(service.search_provider, "search_creator", None)
    if not callable(search_creator):
        raise DomainError(
            "FEATURE_NOT_SUPPORTED", f"平台 {platform} 不支持创作者枚举"
        )
    raw, platform_runs = search_creator(platform, creator_id, max_items, cancel_event=cancel)
    error = _first_error(platform_runs)
    if error and not raw:
        raise DomainError(
            str(error.get("code") or "PARTIAL_FAILURE"),
            str(error.get("message") or "批量枚举失败"),
            retryable=bool(error.get("retryable")),
        )
    return _public_items(raw)


def _collect_time_range(
    service: Any,
    platform: str,
    keyword: str,
    start_day: str,
    end_day: str,
    max_items: int,
    cancel: Any,
) -> list[dict[str, Any]]:
    """Enumerate a keyword's results day by day over [start_day, end_day]."""

    if platform != "bilibili":
        raise DomainError(
            "FEATURE_NOT_SUPPORTED", "time_range_search 当前仅支持 bilibili"
        )
    if not keyword:
        raise DomainError("INVALID_ARGUMENT", "time_range_search 需要 keyword")
    if not start_day or not end_day:
        raise DomainError("INVALID_ARGUMENT", "time_range_search 需要 start_day/end_day (YYYY-MM-DD)")

    from datetime import date, datetime, timedelta

    try:
        start = date.fromisoformat(start_day)
        end = date.fromisoformat(end_day)
    except ValueError as exc:
        raise DomainError("INVALID_ARGUMENT", f"日期格式应为 YYYY-MM-DD: {exc}") from None
    if start > end:
        raise DomainError("INVALID_ARGUMENT", "start_day 不能晚于 end_day")
    if (end - start).days > 90:
        raise DomainError("INVALID_ARGUMENT", "单次时间范围最多 90 天")

    adapters = getattr(service.search_provider, "_adapters", None) or {}
    search = adapters.get("bilibili")
    if search is None:
        raise DomainError("FEATURE_NOT_SUPPORTED", "bilibili 适配器不可用")

    collected: list[dict[str, Any]] = []
    errors: list[str] = []
    current = start
    while current <= end and len(collected) < max_items:
        if cancel.is_set():
            break
        begin = int(datetime.combine(current, datetime.min.time()).timestamp())
        # whole day inclusive: [begin, begin + 1 day - 1 second]
        end_ts = begin + 86399
        per_day = max_items - len(collected)
        try:
            raw, error = search.search(
                keyword,
                per_day,
                pubtime_begin_s=begin,
                pubtime_end_s=end_ts,
            )
            if error:
                errors.append(f"{current}: {error.get('code')} {error.get('message')}")
            collected.extend(
                item for item in _public_items(raw)
                if item.get("title") not in {x.get("title") for x in collected}
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{current}: {type(exc).__name__}: {exc}")
        current += timedelta(days=1)

    if not collected and errors:
        raise DomainError(
            "PARTIAL_FAILURE",
            "; ".join(errors[:5]),
            retryable=True,
        )
    return collected


def _collect_catalog_expand(
    service: Any, platform: str, specs: list[str], cancel: Any
) -> list[dict[str, Any]]:
    """Enumerate a SmartEdu textbook's national-lesson courses via CDN JSON."""

    if platform != "smartedu":
        raise DomainError(
            "FEATURE_NOT_SUPPORTED", "catalog_expand 当前仅支持 smartedu"
        )
    specs = [s for s in specs if str(s).strip()]
    if not specs:
        raise DomainError(
            "INVALID_ARGUMENT",
            "catalog_expand 需要 specs，如 语文/一年级/上册/统编版",
        )
    if cancel.is_set():
        return []
    adapters = getattr(service.search_provider, "_adapters", None) or {}
    adapter = adapters.get("smartedu")
    discover = getattr(adapter, "discover_textbook_courses", None)
    if not callable(discover):
        raise DomainError("FEATURE_NOT_SUPPORTED", "smartedu 适配器不支持教材发现")
    courses = discover(specs)
    items: list[dict[str, Any]] = []
    for course in courses:
        aid = str(course.get("id") or "")
        title = str(course.get("title") or "").strip()
        if not aid or not title:
            continue
        items.append(
            public_item(
                {
                    "platform": "smartedu",
                    "title": title,
                    "resource_type": "course",
                    "source_url": (
                        f"https://basic.smartedu.cn/syncClassroom/classActivity"
                        f"?activityId={urllib.parse.quote(aid)}"
                    ),
                    "activity_id": aid,
                    "textbook": course.get("textbook"),
                    "metadata": {},
                }
            )
        )
    return items


def _first_error(platform_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for run in platform_runs or []:
        for query_run in run.get("query_runs") or []:
            if isinstance(query_run.get("error"), dict):
                return query_run["error"]
    return None


def _public_items(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        public_item(resource)
        for resource in raw
        if isinstance(resource, dict)
        and resource.get("source_url")
        and resource.get("title")
    ]


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
