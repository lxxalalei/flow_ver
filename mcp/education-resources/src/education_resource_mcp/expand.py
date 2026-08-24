"""Generic structural expansion Job lifecycle.

Platform URL recognition and platform-specific enumeration are owned by the
adapter layer. This module only manages Resource handles, persistent Expand
Jobs, JSONL result storage and paged reads.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from itertools import islice
import json
import os
from pathlib import Path
from typing import Any

from .adapters.expansion import expand_resource
from .adapters.resource_urls import identify_resource_url
from .errors import DomainError
from .job_state import (
    CANCEL_FLAG_NAME,
    FileCancelEvent,
    TERMINAL_STATUSES,
    job_dir,
    read_job,
    read_request,
    utc_now_iso,
    write_job,
    write_request,
)
from .jobs import spawn_worker


RESULTS_NAME = "results.jsonl"


def import_resource_url(service: Any, source_url: str) -> dict[str, Any]:
    """Register and inspect a known URL."""

    raw = identify_resource_url(source_url)
    registered = service._remember_resources([raw])  # noqa: SLF001
    if not registered:
        raise DomainError("RESOURCE_NOT_FOUND", "无法建立资源句柄")
    resource_id = str(registered[0]["resource_id"])
    inspected = service.inspect(resource_id)
    return {
        "resource_id": resource_id,
        **{k: v for k, v in inspected.items() if k != "resource_id"},
    }


def start_expand(
    service: Any,
    *,
    resource_id: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    """Start a persistent full structural expansion job."""

    resource_id = str(resource_id or "").strip()
    source_url = str(source_url or "").strip()
    if bool(resource_id) == bool(source_url):
        raise DomainError(
            "INVALID_ARGUMENT",
            "resource_id 与 source_url 必须且只能提供一种展开目标",
        )
    if resource_id:
        target = service._get_resource(resource_id)  # noqa: SLF001
    else:
        target = identify_resource_url(source_url)

    import secrets

    job_id = f"job_{secrets.token_hex(16)}"
    directory = job_dir(service.settings.jobs_dir, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    write_request(
        directory,
        {
            "kind": "resource_expand",
            "job_id": job_id,
            "target": target,
        },
    )
    write_job(
        directory,
        {
            "job_id": job_id,
            "kind": "resource_expand",
            "status": "queued",
            "total": 0,
            "completed": 0,
            "files": [],
            "failures": [],
            "pid": None,
            "created_at": utc_now_iso(),
        },
    )

    def _spawn() -> Any:
        if (directory / CANCEL_FLAG_NAME).exists():
            write_job(
                directory,
                {**read_job(directory), "status": "cancelled"},
            )
            return None
        return spawn_worker(directory)

    service.job_runner.submit(job_id, _spawn)
    return {"job_id": job_id, "status": "queued"}


def read_expand(
    service: Any,
    job_id: str,
    *,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """Read one page without truncating the persisted expansion result."""

    directory, job = service._load_job(job_id)  # noqa: SLF001
    job = service._reconcile(directory, job)  # noqa: SLF001
    if str(job.get("kind") or "") != "resource_expand":
        raise DomainError("INVALID_ARGUMENT", "该任务不是资源展开任务")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise DomainError("INVALID_ARGUMENT", "offset 必须 >= 0")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise DomainError("INVALID_ARGUMENT", "limit 必须 >= 1")
    limit = min(limit, 50)

    path = directory / RESULTS_NAME
    items: list[dict[str, Any]] = []
    line_count = 0
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            lines = list(islice(handle, offset, offset + limit))
        line_count = len(lines)
        for index, line in enumerate(lines, start=offset + 1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    "JOB_STATE_INVALID",
                    "资源展开结果文件损坏",
                    details={"job_id": job_id, "line": index},
                ) from exc
            if not isinstance(raw, dict):
                raise DomainError(
                    "JOB_STATE_INVALID",
                    "资源展开结果项格式无效",
                )
            registered = service._remember_resources([raw])  # noqa: SLF001
            if registered:
                items.append(registered[0])

    total = max(
        int(job.get("total") or 0),
        int(job.get("completed") or 0),
    )
    status = str(job.get("status") or "")
    return {
        "job_id": job_id,
        "kind": "resource_expand",
        "status": status,
        "total": total,
        "offset": offset,
        "items": items,
        "complete": (
            status in TERMINAL_STATUSES
            and offset + line_count >= total
        ),
        "failures": [dict(item) for item in job.get("failures") or []],
    }


def download_expanded(
    service: Any,
    expand_job_id: str,
    *,
    preferred_container: str = "original",
) -> dict[str, Any]:
    """Download every child after explicit whole-expansion selection."""

    directory, job = service._load_job(expand_job_id)  # noqa: SLF001
    job = service._reconcile(directory, job)  # noqa: SLF001
    if str(job.get("kind") or "") != "resource_expand":
        raise DomainError(
            "INVALID_ARGUMENT",
            "expand_job_id 不是资源展开任务",
        )
    if str(job.get("status") or "") != "succeeded":
        raise DomainError(
            "EXPAND_INCOMPLETE",
            "展开结果尚未完整成功，不能把部分结果当成用户选择的全部资源",
        )
    path = directory / RESULTS_NAME
    if not path.is_file():
        raise DomainError(
            "JOB_STATE_INVALID",
            "资源展开结果文件不存在",
        )

    raw_resources = _read_all_results(path)
    registered = service._remember_resources(raw_resources)  # noqa: SLF001
    resource_ids = [str(item["resource_id"]) for item in registered]
    if not resource_ids:
        raise DomainError(
            "RESOURCE_NOT_FOUND",
            "资源展开任务没有可下载子资源",
        )
    result = service.download(
        resource_ids,
        preferred_container=preferred_container,
    )
    result["source_expand_job_id"] = expand_job_id
    return result


def run_expand(directory: Path, service: Any = None) -> int:
    """Worker entry: enumerate structural children into ``results.jsonl``."""

    request = read_request(directory)
    target = request.get("target")
    if not isinstance(target, dict):
        write_job(
            directory,
            {
                **read_job(directory),
                "status": "failed",
                "failures": [
                    {
                        "code": "INVALID_ARGUMENT",
                        "message": "展开目标无效",
                        "retryable": False,
                    }
                ],
            },
        )
        return 1

    if service is None:
        from .service import ResourceService

        service = ResourceService(recover_jobs=False)

    cancel = FileCancelEvent(directory / CANCEL_FLAG_NAME)
    write_job(
        directory,
        {
            **read_job(directory),
            "status": "running",
            "pid": os.getpid(),
        },
    )
    results_path = directory / RESULTS_NAME
    results_path.unlink(missing_ok=True)
    failures: list[dict[str, Any]] = []
    count = 0

    try:
        iterator = iter_expand(
            service,
            target,
            cancel_event=cancel,
        )
        seen: set[tuple[str, str]] = set()
        with results_path.open("w", encoding="utf-8") as handle:
            for resource in iterator:
                if cancel.is_set():
                    break
                if not isinstance(resource, dict):
                    continue
                url = str(resource.get("source_url") or "").strip()
                platform = str(resource.get("platform") or "generic")
                title = str(resource.get("title") or "").strip()
                if not url or not title:
                    continue
                key = (platform, url)
                if key in seen:
                    continue
                seen.add(key)
                persisted = _persistable_resource(resource)
                handle.write(
                    json.dumps(persisted, ensure_ascii=False) + "\n"
                )
                handle.flush()
                count += 1
                if count % 20 == 0:
                    write_job(
                        directory,
                        {
                            **read_job(directory),
                            "status": "running",
                            "pid": os.getpid(),
                            "completed": count,
                            "total": count,
                        },
                    )
    except Exception as exc:
        failures.append(_failure_from_exception(exc))

    if cancel.is_set():
        final = "cancelled"
    elif failures and count:
        final = "partial"
    elif count:
        final = "succeeded"
    else:
        final = "failed"

    files: list[dict[str, Any]] = []
    if count and results_path.is_file():
        files = [
            {
                "filename": RESULTS_NAME,
                "path": str(results_path),
                "lines": count,
            }
        ]
    else:
        results_path.unlink(missing_ok=True)
    write_job(
        directory,
        {
            **read_job(directory),
            "status": final,
            "pid": os.getpid(),
            "total": count,
            "completed": count,
            "files": files,
            "failures": failures,
        },
    )
    return 0


def iter_expand(
    service: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    """Delegate structural enumeration to the adapter layer."""

    yield from expand_resource(
        service.search_provider,
        target,
        cancel_event=cancel_event,
    )


def _persistable_resource(
    resource: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "platform": str(resource.get("platform") or "generic"),
        "title": str(resource.get("title") or ""),
        "source_url": str(resource.get("source_url") or ""),
        "resource_type": resource.get("resource_type") or "其他",
        "summary": resource.get("summary"),
        "metadata": (
            dict(resource.get("metadata") or {})
            if isinstance(resource.get("metadata"), Mapping)
            else {}
        ),
    }


def _read_all_results(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    "JOB_STATE_INVALID",
                    "资源展开结果文件损坏",
                    details={"line": index},
                ) from exc
            if not isinstance(item, dict):
                raise DomainError(
                    "JOB_STATE_INVALID",
                    "资源展开结果项格式无效",
                )
            values.append(item)
    return values


def _failure_from_exception(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, DomainError):
        return {
            "code": exc.code,
            "message": exc.message,
            "retryable": exc.retryable,
        }
    code = str(getattr(exc, "code", "PARTIAL_FAILURE"))
    message = str(getattr(exc, "message", str(exc)))
    retryable = bool(getattr(exc, "retryable", True))
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
    }


__all__ = [
    "download_expanded",
    "import_resource_url",
    "iter_expand",
    "read_expand",
    "run_expand",
    "start_expand",
]
