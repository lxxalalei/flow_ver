"""Zjer course expansion."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from ..errors import DomainError


def _kind(target: Mapping[str, Any]) -> str:
    return str(target.get("resource_type") or "").strip().casefold()


def _url(target: Mapping[str, Any]) -> str:
    return str(target.get("source_url") or "").strip()

def expand(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    session_store: Any = None,
) -> Iterator[dict[str, Any]]:
    if _kind(target) not in {"course", "课程"}:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "Zjer video 是叶子资源，没有可展开子资源",
        )

    from .zjer import (
        _course_id_from_query,
        _detail_url,
        _safe_media_facts,
        best_mp4,
        fetch_course_detail,
        lessons,
    )

    cookie = ""
    if session_store is not None:
        session_data = session_store.get_session_data("zjer")
        cookie = session_store._cookie_header(session_data) if session_data else ""

    course_id = _course_id_from_query(_url(target))
    if course_id is None:
        raise DomainError("INVALID_ARGUMENT", "Zjer 课程 URL 缺少 courseCateId")
    data = fetch_course_detail(
        course_id,
        timeout=float(getattr(adapter, "timeout", 30.0)),
        transport=getattr(adapter, "detail_transport", None),
        cookie=cookie,
    )
    course_name = str(data.get("cateName") or "").strip()
    org_name = str(data.get("teacherOrgName") or data.get("orgName") or "").strip()
    course_uuid = str(data.get("uuid") or "").strip()

    for lesson in lessons(data):
        if cancel_event is not None and cancel_event.is_set():
            return
        try:
            video_id = int(lesson.get("videoId") or 0)
            course_info_id = int(lesson.get("id") or 0)
        except (TypeError, ValueError):
            continue
        lesson_name = str(lesson.get("courseName") or "").strip()
        media = best_mp4(lesson)
        if not video_id or not course_info_id or not lesson_name or media is None:
            continue
        signals: dict[str, Any] = {
            "course_cate_id": course_id,
            "course_info_id": course_info_id,
            "video_id": video_id,
            "course_cate_uuid": course_uuid or None,
            "course_info_uuid": str(lesson.get("uuid") or "").strip() or None,
        }
        signals.update(_safe_media_facts(media))
        yield {
            "platform": "zjer",
            "title": f"{course_name}｜{lesson_name}" if course_name else lesson_name,
            "source_url": _detail_url(course_id, video_id=video_id),
            "resource_type": "视频",
            "metadata": {
                "author": org_name or None,
                "platform_signals": signals,
            },
        }


__all__ = ["expand_resource"]


__all__ = ["expand"]
