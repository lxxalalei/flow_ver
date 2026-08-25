"""SmartEdu textbook and course-file expansion."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
from typing import Any
import urllib.parse
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

from ..errors import DomainError
from .http_client import urlopen_with_fallback

_SMARTEDU_MATERIAL_PARTS_URL = (
    "https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/national_lesson/"
    "teachingmaterials/{textbook_id}/resources/part_{part_no}.json"
)


def _kind(target: Mapping[str, Any]) -> str:
    return str(target.get("resource_type") or "").strip().casefold()


def _url(target: Mapping[str, Any]) -> str:
    return str(target.get("source_url") or "").strip()

def expand(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    url = _url(target)
    kind = _kind(target)
    if kind == "textbook" or "/tchMaterial/" in url:
        yield from _iter_smartedu_textbook(
            adapter,
            target,
            cancel_event=cancel_event,
            summary=summary,
        )
        return
    if kind == "course":
        yield from _iter_smartedu_course_files(
            adapter,
            target,
            cancel_event=cancel_event,
            summary=summary,
        )
        return
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "SmartEdu 当前资源没有已实现的结构展开能力",
    )


def _smartedu_course_detail(
    adapter: Any,
    source_url: str,
) -> tuple[str, str, dict[str, Any]]:
    from .smartedu_download import (
        _DETAIL_MAX_BYTES,
        _SMARTEDU_DETAIL_HOSTS,
        _SmartEduHttpClient,
        _raise_for_http_status,
        _read_json_object,
        _smartedu_headers,
    )
    from .smartedu_resource import _COURSE_TYPES, _detail_api_url, _resolve_content

    content_id, content_type = _resolve_content(source_url)
    if content_type not in _COURSE_TYPES:
        raise DomainError("FEATURE_NOT_SUPPORTED", "SmartEdu 当前资源不是可展开课程")
    token = ""
    session_store = getattr(adapter, "session_store", None)
    if session_store is not None:
        session_data = session_store.get_session_data("smartedu") or {}
        tokens = session_data.get("tokens") or {}
        raw_token = str(tokens.get("accessToken") or "")
        token = raw_token[7:].strip() if raw_token.casefold().startswith("bearer ") else raw_token
    client = _SmartEduHttpClient(allowed_hosts=_SMARTEDU_DETAIL_HOSTS)
    request = Request(
        _detail_api_url(content_id, content_type, source_url),
        headers=_smartedu_headers(token),
    )
    try:
        with client.open(request, timeout=float(getattr(adapter, "timeout", 30.0))) as response:
            _raise_for_http_status(response)
            detail = _read_json_object(response, _DETAIL_MAX_BYTES, label="课程详情")
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "PARTIAL_FAILURE",
            "SmartEdu 课程文件详情读取失败",
            retryable=True,
        ) from exc
    return content_id, content_type, detail


def _iter_smartedu_course_files(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    from .smartedu_resource import (
        _ACTIVE_PRIMARY_FORMATS,
        _find_files,
        _primary_candidate,
        _role_for_candidate,
        _select_course_files,
        _smartedu_file_key,
    )

    source_url = _url(target)
    content_id, content_type, detail = _smartedu_course_detail(adapter, source_url)
    active = [
        candidate
        for candidate in _find_files(detail)
        if str(candidate.get("format") or "").casefold() in _ACTIVE_PRIMARY_FORMATS
    ]
    selected = _select_course_files(active)
    primary = _primary_candidate(
        selected,
        content_type,
        supported_formats=_ACTIVE_PRIMARY_FORMATS,
    )
    if primary is None:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "SmartEdu 课程详情未提供受支持的主文件",
        )
    primary_key = str(primary.get("item_key") or "")
    report = {
        "course_id": content_id,
        "files_seen": len(selected),
        "emitted": 0,
        "unstable_files": 0,
    }
    if summary is not None:
        summary["smartedu"] = report
    seen_keys: set[str] = set()
    role_labels = {
        "primary": "主文件",
        "attachment": "附件",
        "companion": "伴随资源",
        "subtitle": "字幕",
    }
    type_by_format = {
        "mp4": "video",
        "m3u8": "video",
        "mp3": "audio",
        "m4a": "audio",
        "pdf": "document",
    }
    for candidate in selected:
        if cancel_event is not None and cancel_event.is_set():
            return
        file_key = _smartedu_file_key(content_id, candidate)
        if not file_key:
            report["unstable_files"] += 1
            continue
        if file_key in seen_keys:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "SmartEdu 课程详情包含重复的平台文件身份",
            )
        seen_keys.add(file_key)
        fmt = str(candidate.get("format") or "").casefold()
        role = _role_for_candidate(
            candidate,
            primary_key=primary_key,
            content_type=content_type,
        )
        title = str(candidate.get("title") or "").strip() or f"课程文件 {len(seen_keys)}"
        size = int(candidate.get("size") or 0)
        summary_parts = [role_labels.get(role, role), fmt.upper()]
        if size > 0:
            summary_parts.append(f"{size} bytes")
        report["emitted"] += 1
        yield {
            "platform": "smartedu",
            "title": title,
            "source_url": source_url,
            "resource_type": type_by_format.get(fmt, "other"),
            "summary": " · ".join(summary_parts),
            "metadata": {
                "platform_signals": {
                    "course_id": content_id,
                    "file_key": file_key,
                    "relation_key": str(candidate.get("relation_key") or "root"),
                    "course_role": role,
                    "format": fmt,
                }
            },
        }


def _iter_smartedu_textbook(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    source_url = _url(target)
    textbook_id = str(
        (urllib.parse.parse_qs(urlsplit(source_url).query).get("contentId") or [""])[0]
    ).strip()
    if not textbook_id:
        raise DomainError("INVALID_ARGUMENT", "SmartEdu 教材 URL 缺少 contentId")

    headers = adapter._build_headers()  # noqa: SLF001 - same platform layer
    parent_metadata = target.get("metadata")
    parent_signals = (
        parent_metadata.get("platform_signals")
        if isinstance(parent_metadata, Mapping)
        and isinstance(parent_metadata.get("platform_signals"), Mapping)
        else {}
    )
    report: dict[str, Any] = {
        "textbook_id": textbook_id,
        "parts_read": 0,
        "resource_counts": {},
        "emitted": 0,
        "skipped_types": {},
        "invalid_items": 0,
        "termination": None,
    }
    if summary is not None:
        summary["smartedu"] = report

    part_no = 100
    while True:
        if cancel_event is not None and cancel_event.is_set():
            report["termination"] = "cancelled"
            return
        try:
            values = _smartedu_cdn_json(
                adapter,
                _SMARTEDU_MATERIAL_PARTS_URL.format(
                    textbook_id=urllib.parse.quote(textbook_id),
                    part_no=part_no,
                ),
                headers,
            )
        except HTTPError as exc:
            if exc.code == 404:
                report["termination"] = "not_found"
                break
            report["termination"] = "error"
            raise
        except Exception:
            report["termination"] = "error"
            raise
        if not isinstance(values, list):
            report["termination"] = "error"
            raise DomainError(
                "PARTIAL_FAILURE",
                "SmartEdu 教材资源分片格式异常",
                retryable=True,
            )
        report["parts_read"] += 1
        if not values:
            report["termination"] = "empty_page"
            break
        for entry in values:
            if not isinstance(entry, dict):
                report["invalid_items"] += 1
                continue
            resource_type = str(entry.get("resource_type_code") or "").strip()
            child_id = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not resource_type or not child_id or not title:
                report["invalid_items"] += 1
                continue
            counts = report["resource_counts"]
            counts[resource_type] = int(counts.get(resource_type) or 0) + 1
            if resource_type not in {"national_lesson", "elite_lesson"}:
                skipped = report["skipped_types"]
                skipped[resource_type] = int(skipped.get(resource_type) or 0) + 1
                continue
            child_url = (
                "https://basic.smartedu.cn/syncClassroom/classActivity?activityId="
                + urllib.parse.quote(child_id)
                if resource_type == "national_lesson"
                else "https://basic.smartedu.cn/qualityCourse?courseId="
                + urllib.parse.quote(child_id)
            )
            child_signals = {
                "textbook_id": textbook_id,
                "resource_type_code": resource_type,
            }
            for key in ("subject", "grade", "volume", "version", "edition", "stage"):
                if parent_signals.get(key) not in (None, ""):
                    child_signals[key] = parent_signals[key]
            report["emitted"] += 1
            yield {
                "platform": "smartedu",
                "title": title,
                "source_url": child_url,
                "resource_type": "course",
                "metadata": {
                    "platform_signals": child_signals
                },
            }
        part_no += 1


def _smartedu_cdn_json(
    adapter: Any,
    url: str,
    headers: Mapping[str, str],
) -> Any:
    request = Request(url, headers=dict(headers))
    with urlopen_with_fallback(
        request,
        timeout=float(getattr(adapter, "timeout", 30.0)),
    ) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


__all__ = ["expand"]
