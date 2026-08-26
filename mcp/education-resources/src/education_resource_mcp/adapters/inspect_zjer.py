"""Zjer (之江汇) course-video inspection.

Inspection re-reads the stable course detail API and confirms that the selected
lesson still exposes a materializable MP4. The short-lived signed media URL is
never included in the public Resolution.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any, Callable

from ..errors import DomainError
from ..inspection import (
    INSPECTOR_VERSION,
    InspectionResult,
    build_default_inspection,
)
from ..sessions import session_cookie
from .zjer import best_mp4, fetch_course_detail, find_lesson, resource_video_identity


class ZjerInspector:
    platform_id = "zjer"
    inspector_id = "zjer"
    version = INSPECTOR_VERSION

    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        detail_fetcher: Callable[..., dict[str, Any]] = fetch_course_detail,
        session_store: Any = None,
    ) -> None:
        self.timeout = float(timeout_seconds)
        self.detail_fetcher = detail_fetcher
        self.session_store = session_store

    def _cookie(self) -> str:
        return session_cookie(self.session_store, "zjer")

    @staticmethod
    def _metadata(
        resource: Mapping[str, Any],
        *,
        course_cate_id: int | None = None,
        course_info_id: int | None = None,
        video_id: int | None = None,
        media: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in (
            ("course_cate_id", course_cate_id),
            ("course_info_id", course_info_id),
            ("video_id", video_id),
        ):
            if value is not None:
                result[key] = value
        raw_metadata = resource.get("metadata")
        raw_signals = raw_metadata.get("platform_signals") if isinstance(raw_metadata, Mapping) else None
        if isinstance(raw_signals, Mapping):
            for source, target in (
                ("course_cate_uuid", "course_cate_uuid"),
                ("course_info_uuid", "course_info_uuid"),
            ):
                value = raw_signals.get(source)
                if isinstance(value, str) and value:
                    result[target] = value[:128]
        if isinstance(media, Mapping):
            for source, target in (
                ("definition", "definition"),
                ("height", "height"),
                ("width", "width"),
                ("bitrate", "bitrate_kbps"),
                ("videoSize", "video_size_bytes"),
                ("videoSecond", "video_duration_seconds"),
                ("uuid", "video_uuid"),
            ):
                value = media.get(source)
                if isinstance(value, (str, int, float, bool)) and value not in ("", None):
                    result[target] = value
        return result

    def _failure(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        *,
        retryable: bool,
        availability: str = "unknown",
    ) -> InspectionResult:
        identity = resource_video_identity(resource)
        course_cate_id = course_info_id = video_id = None
        if identity is not None:
            course_cate_id, course_info_id, video_id = identity
        return InspectionResult(
            resolution_status="unresolved",
            resolved_resource={
                "title": str(resource.get("title") or "之江汇课程视频")[:512],
                "resource_type": "video",
                "availability": {"status": availability},
                "representations": [],
                "metadata": self._metadata(
                    resource,
                    course_cate_id=course_cate_id,
                    course_info_id=course_info_id,
                    video_id=video_id,
                ),
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="platform_detail_api",
                version=self.version,
            ),
            failures=(
                {
                    "platform": "zjer",
                    "code": code,
                    "message": message,
                    "retriable": retryable,
                },
            ),
        )

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if not isinstance(resource, Mapping) or resource.get("platform") != "zjer":
            return self._failure(
                resource if isinstance(resource, Mapping) else {},
                "PLATFORM_VALIDATION_BLOCKED",
                "之江汇检查需要有效的 zjer Resource",
                retryable=False,
            )
        identity = resource_video_identity(resource)
        if identity is None:
            return self._failure(
                resource,
                "PLATFORM_VALIDATION_BLOCKED",
                "之江汇检查需要服务端 courseCateId、courseInfoId 和 videoId",
                retryable=False,
            )
        course_cate_id, course_info_id, video_id = identity
        try:
            data = self.detail_fetcher(
                course_cate_id,
                timeout=self.timeout,
                cookie=self._cookie(),
            )
        except DomainError as exc:
            availability = (
                "auth_required"
                if exc.code == "AUTH_REQUIRED"
                else "unavailable"
                if exc.code == "RESOURCE_NOT_FOUND"
                else "unknown"
            )
            return self._failure(
                resource,
                exc.code,
                exc.message,
                retryable=exc.retryable,
                availability=availability,
            )
        except Exception:
            return self._failure(
                resource,
                "PLATFORM_UNAVAILABLE",
                "之江汇课程详情检查失败",
                retryable=True,
            )

        lesson = find_lesson(
            data,
            video_id=video_id,
            course_info_id=course_info_id,
        )
        if lesson is None:
            return self._failure(
                resource,
                "RESOURCE_NOT_FOUND",
                "之江汇课时已经不存在",
                retryable=False,
                availability="unavailable",
            )
        media = best_mp4(lesson)
        if media is None:
            return self._failure(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "之江汇课时当前未提供可获取的 MP4",
                retryable=False,
            )

        title = str(resource.get("title") or lesson.get("courseName") or "之江汇课程视频")[:512]
        representation_id = "repr_" + hashlib.sha256(
            f"zjer|{course_cate_id}|{course_info_id}|{video_id}|mp4".encode("utf-8")
        ).hexdigest()[:32]
        inspected = build_default_inspection(
            self.inspector_id,
            method="platform_detail_api",
            version=self.version,
        )
        representation: dict[str, Any] = {
            "representation_id": representation_id,
            "kind": "video",
            "container": "mp4",
            "mime_type": "video/mp4",
            "role": "primary",
            "materializable": True,
        }
        size = media.get("videoSize")
        if isinstance(size, int) and not isinstance(size, bool) and size > 0:
            representation["size_bytes"] = size
        representation["scope"] = "primary_resource"
        representation["technical_availability"] = "available"
        metadata = self._metadata(
            resource,
            course_cate_id=course_cate_id,
            course_info_id=course_info_id,
            video_id=video_id,
            media=media,
        )
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": title,
                "resource_type": "video",
                "availability": {"status": "available"},
                "representations": [representation],
                "metadata": metadata,
            },
            inspection=inspected,
            failures=(),
        )


__all__ = ["ZjerInspector"]
