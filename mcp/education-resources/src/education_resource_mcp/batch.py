"""Batch collection runner for detached workers.

Batch jobs enumerate large platform result sets into ``results.jsonl``.
The conversation only sees a job handle plus paged reads; enumeration itself
streams records to disk instead of accumulating the whole result set in memory.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator
import urllib.parse

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
    """Execute one batch_collect job and stream results to ``results.jsonl``."""

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

    max_items = _optional_positive_int(request.get("max_items"))
    cancel = FileCancelEvent(directory / CANCEL_FLAG_NAME)
    write_job(
        directory,
        {**read_job(directory), "status": "running", "pid": os.getpid()},
    )

    if service is None:
        from .service import ResourceService

        service = ResourceService(recover_jobs=False)

    failures: list[dict[str, Any]] = []
    count = 0
    results_path = directory / RESULTS_NAME
    try:
        results_path.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        iterator = _iterator_for_request(service, request, cancel, max_items)
        seen: set[str] = set()
        with results_path.open("w", encoding="utf-8") as handle:
            for item in iterator:
                if cancel.is_set():
                    break
                identity = _item_identity(item)
                if identity and identity in seen:
                    continue
                if identity:
                    seen.add(identity)
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
                count += 1
                if count % 20 == 0:
                    current = read_job(directory)
                    write_job(
                        directory,
                        {
                            **current,
                            "status": "running",
                            "pid": os.getpid(),
                            "completed": count,
                            "total": count,
                        },
                    )
                if max_items is not None and count >= max_items:
                    break
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
    elif failures and count:
        final = "partial"
    elif count:
        final = "succeeded"
    else:
        final = "failed"

    files: list[dict[str, Any]] = []
    if count and results_path.is_file():
        files = [{"filename": RESULTS_NAME, "path": str(results_path), "lines": count}]
    elif not count:
        try:
            results_path.unlink(missing_ok=True)
        except OSError:
            pass

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
    LOGGER.info(
        "batch %s finished: %s (%d items)", request.get("job_id"), final, count
    )
    return 0


def _iterator_for_request(
    service: Any,
    request: dict[str, Any],
    cancel: Any,
    max_items: int | None,
) -> Iterator[dict[str, Any]]:
    mode = str(request.get("mode") or "")
    platform = str(request.get("platform") or "")
    if mode == "creator_full":
        return _iter_creator_full(
            service,
            platform,
            str(request.get("creator_id") or ""),
            cancel,
            max_items,
        )
    if mode == "time_range_search":
        return _iter_time_range(
            service,
            platform,
            str(request.get("keyword") or ""),
            str(request.get("start_day") or ""),
            str(request.get("end_day") or ""),
            cancel,
            max_items,
        )
    if mode == "catalog_expand":
        return _iter_catalog_expand(
            service,
            platform,
            list(request.get("specs") or []),
            cancel,
        )
    raise DomainError("INVALID_ARGUMENT", f"未知批量模式 {mode!r}")


def _adapter_for(service: Any, platform: str) -> Any | None:
    adapters = getattr(service.search_provider, "_adapters", None) or {}
    return adapters.get(platform)


def _iter_creator_full(
    service: Any,
    platform: str,
    creator_id: str,
    cancel: Any,
    max_items: int | None,
) -> Iterator[dict[str, Any]]:
    adapter = _adapter_for(service, platform)
    iter_creator = getattr(adapter, "iter_creator", None) if adapter is not None else None
    if callable(iter_creator):
        try:
            for resource in iter_creator(creator_id, cancel_event=cancel):
                item = public_item(resource)
                if item.get("title") and item.get("url"):
                    yield item
            return
        except Exception as exc:
            converted = _adapter_error(exc)
            if converted is not None:
                raise converted from exc
            raise

    # Compatibility for providers/test doubles that only expose the older
    # list-returning search_creator API. It is allowed only when the caller
    # explicitly supplied a bound; unbounded "full" mode must be streamable.
    search_creator = getattr(service.search_provider, "search_creator", None)
    if max_items is None or not callable(search_creator):
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            f"平台 {platform} 暂不支持无截断的完整创作者枚举",
        )
    raw, platform_runs = search_creator(
        platform, creator_id, max_items, cancel_event=cancel
    )
    error = _first_error(platform_runs)
    if error and not raw:
        raise DomainError(
            str(error.get("code") or "PARTIAL_FAILURE"),
            str(error.get("message") or "批量枚举失败"),
            retryable=bool(error.get("retryable")),
        )
    for resource in raw:
        item = public_item(resource)
        if item.get("title") and item.get("url"):
            yield item


def _iter_time_range(
    service: Any,
    platform: str,
    keyword: str,
    start_day: str,
    end_day: str,
    cancel: Any,
    max_items: int | None,
) -> Iterator[dict[str, Any]]:
    if platform != "bilibili":
        raise DomainError(
            "FEATURE_NOT_SUPPORTED", "time_range_search 当前仅支持 bilibili"
        )
    if not keyword:
        raise DomainError("INVALID_ARGUMENT", "time_range_search 需要 keyword")
    if not start_day or not end_day:
        raise DomainError(
            "INVALID_ARGUMENT", "time_range_search 需要 start_day/end_day (YYYY-MM-DD)"
        )
    try:
        start = date.fromisoformat(start_day)
        end = date.fromisoformat(end_day)
    except ValueError as exc:
        raise DomainError("INVALID_ARGUMENT", f"日期格式应为 YYYY-MM-DD: {exc}") from None
    if start > end:
        raise DomainError("INVALID_ARGUMENT", "start_day 不能晚于 end_day")

    adapter = _adapter_for(service, "bilibili")
    if adapter is None:
        raise DomainError("FEATURE_NOT_SUPPORTED", "bilibili adapter 不可用")
    iter_search = getattr(adapter, "iter_search", None)
    search = getattr(adapter, "search", None)
    if not callable(iter_search) and (max_items is None or not callable(search)):
        raise DomainError(
            "FEATURE_NOT_SUPPORTED", "bilibili adapter 不支持无截断的时间范围枚举"
        )

    current = start
    try:
        while current <= end:
            if cancel.is_set():
                break
            begin = int(datetime.combine(current, datetime.min.time()).timestamp())
            end_ts = begin + 86399
            if callable(iter_search):
                resources = iter_search(
                    keyword,
                    pubtime_begin_s=begin,
                    pubtime_end_s=end_ts,
                    cancel_event=cancel,
                )
                for resource in resources:
                    item = public_item(resource)
                    if item.get("title") and item.get("url"):
                        yield item
            else:
                raw, error = search(
                    keyword,
                    max_items,
                    pubtime_begin_s=begin,
                    pubtime_end_s=end_ts,
                )
                if error and not raw:
                    raise DomainError(
                        str(error.get("code") or "PARTIAL_FAILURE"),
                        str(error.get("message") or "时间范围搜索失败"),
                        retryable=bool(error.get("retryable")),
                    )
                for resource in raw:
                    item = public_item(resource)
                    if item.get("title") and item.get("url"):
                        yield item
            current += timedelta(days=1)
    except Exception as exc:
        if isinstance(exc, DomainError):
            raise
        converted = _adapter_error(exc)
        if converted is not None:
            raise converted from exc
        raise


def _iter_catalog_expand(
    service: Any, platform: str, specs: list[str], cancel: Any
) -> Iterator[dict[str, Any]]:
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
        return
    adapter = _adapter_for(service, "smartedu")
    discover = getattr(adapter, "discover_textbook_courses", None) if adapter else None
    if not callable(discover):
        raise DomainError("FEATURE_NOT_SUPPORTED", "smartedu 适配器不支持教材发现")
    try:
        for course in discover(specs):
            if cancel.is_set():
                break
            aid = str(course.get("id") or "")
            title = str(course.get("title") or "").strip()
            if not aid or not title:
                continue
            yield public_item(
                {
                    "platform": "smartedu",
                    "title": title,
                    "resource_type": "course",
                    "source_url": (
                        "https://basic.smartedu.cn/syncClassroom/classActivity"
                        f"?activityId={urllib.parse.quote(aid)}"
                    ),
                    "activity_id": aid,
                    "textbook": course.get("textbook"),
                    "metadata": {},
                }
            )
    except Exception as exc:
        converted = _adapter_error(exc)
        if converted is not None:
            raise converted from exc
        raise


def _item_identity(item: dict[str, Any]) -> str:
    """Deduplicate by stable resource identity, never by title."""

    url = str(item.get("url") or "").strip()
    if url:
        return url
    platform = str(item.get("platform") or "").strip()
    activity_id = str(item.get("activity_id") or "").strip()
    return f"{platform}:{activity_id}" if activity_id else ""


def _first_error(platform_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for run in platform_runs or []:
        for query_run in run.get("query_runs") or []:
            error = query_run.get("error")
            if isinstance(error, dict):
                return error
    return None


def _adapter_error(exc: Exception) -> DomainError | None:
    code = getattr(exc, "code", None)
    if not code:
        return None
    return DomainError(
        str(code),
        str(getattr(exc, "message", str(exc))),
        retryable=bool(getattr(exc, "retryable", False)),
    )


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise DomainError("INVALID_ARGUMENT", "max_items 必须是正整数或留空") from None
    if parsed <= 0:
        raise DomainError("INVALID_ARGUMENT", "max_items 必须大于 0 或留空")
    return parsed
