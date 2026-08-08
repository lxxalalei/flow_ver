"""Public SmartEdu inspection with resource-type representations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..inspection import INSPECTOR_VERSION
from .inspect_bilibili import _PlatformWebInspector


_FORMAT_DETAILS: dict[str, tuple[str, str]] = {
    "mp4": ("video", "video/mp4"),
    "webm": ("video", "video/webm"),
    "mov": ("video", "video/quicktime"),
    "mp3": ("audio", "audio/mpeg"),
    "m4a": ("audio", "audio/mp4"),
    "wav": ("audio", "audio/wav"),
    "ogg": ("audio", "audio/ogg"),
    "pdf": ("document", "application/pdf"),
    "doc": ("document", "application/msword"),
    "docx": (
        "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "ppt": ("document", "application/vnd.ms-powerpoint"),
    "pptx": (
        "document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "txt": ("document", "text/plain"),
}


class SmartEduInspector(_PlatformWebInspector):
    """Inspect a public National Smart Education Platform detail page."""

    platform_id = "smartedu"
    inspector_id = "smartedu"
    version = INSPECTOR_VERSION
    host_suffixes = ("smartedu.cn", "eduyun.cn")
    metadata_allowlist = (
        "content_id",
        "course_id",
        "resource_id",
        "grade",
        "subject",
        "resource_format",
        "provider",
    )

    def _representation_shape(
        self, payload: Mapping[str, Any]
    ) -> tuple[str, str, str | None]:
        resolved_type = payload["resolved_resource"].get("resource_type")
        metadata = payload["resolved_resource"].get("metadata", {})
        raw_format = metadata.get("resource_format")
        resource_format = raw_format.casefold() if isinstance(raw_format, str) else ""

        if resolved_type == "course":
            return "webpage", "course", None
        if resolved_type == "video":
            default_kind = "video"
        elif resolved_type == "audio":
            default_kind = "audio"
        elif resolved_type in {"document", "book"}:
            default_kind = "document"
        elif resolved_type == "article":
            return "webpage", "article", None
        else:
            default_kind = "other"

        format_detail = _FORMAT_DETAILS.get(resource_format)
        if format_detail and (resolved_type == "other" or default_kind == "other"):
            default_kind = format_detail[0]
        mime_type = format_detail[1] if format_detail and format_detail[0] == default_kind else None
        container = resource_format or default_kind
        return default_kind, container, mime_type

    def _enrich_payload(
        self, resource: Mapping[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        payload = super()._enrich_payload(resource, payload)
        if not self._can_add_representation(payload):
            return payload
        kind, container, mime_type = self._representation_shape(payload)
        self._append_representation(
            resource,
            payload,
            kind=kind,
            container=container,
            mime_type=mime_type,
        )
        return payload


SmartEduResourceInspector = SmartEduInspector
SmartEduPlatformInspector = SmartEduInspector


__all__ = [
    "SmartEduInspector",
    "SmartEduPlatformInspector",
    "SmartEduResourceInspector",
]
