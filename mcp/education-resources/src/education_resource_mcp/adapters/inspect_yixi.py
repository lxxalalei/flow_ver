"""Bounded Yixi (一席) direct-media inspection.

Yixi search resolves a stable speech_id through the public play-detail API and,
when available, exposes the highest public MP4 as the candidate source URL.
This inspector requires both the server-derived speech identity and the
resolved-direct-media fact, then delegates HTTP/content verification to the
shared bounded inspector.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..inspection import InspectionResult
from .inspect_platform_bounded import PlatformBoundedInspector


INSPECTOR_ID = "yixi"
ALLOWED_HOST_SUFFIXES = ("yixi.tv",)


class YixiInspector(PlatformBoundedInspector):
    """Inspect a Yixi candidate only after Search resolved a public MP4."""

    platform_id = "yixi"
    inspector_id = INSPECTOR_ID
    allowed_host_suffixes = ALLOWED_HOST_SUFFIXES
    allow_any_public_host = False

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if not isinstance(resource, Mapping):
            return self._validation_result(
                {},
                "PLATFORM_VALIDATION_BLOCKED",
                "一席检查需要有效资源对象",
            )
        speech_id = None
        direct_video = False
        for mapping in self._identity_mappings(resource):
            candidate = mapping.get("speech_id")
            if speech_id is None:
                if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                    speech_id = candidate
                elif isinstance(candidate, str) and candidate.isdigit() and int(candidate) > 0:
                    speech_id = int(candidate)
            if mapping.get("direct_video") is True:
                direct_video = True
        if speech_id is None:
            return self._validation_result(
                resource,
                "PLATFORM_VALIDATION_BLOCKED",
                "一席检查需要资源元数据中的服务端 speech_id 字段",
            )
        if not direct_video:
            return self._validation_result(
                resource,
                "PLATFORM_VALIDATION_BLOCKED",
                "一席候选尚未解析出公开 MP4 视频",
            )
        return super().inspect(resource)

    @staticmethod
    def _identity_mappings(resource: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        values: list[Mapping[str, Any]] = [resource]
        metadata = resource.get("metadata")
        if isinstance(metadata, Mapping):
            values.append(metadata)
            signals = metadata.get("platform_signals")
            if isinstance(signals, Mapping):
                values.append(signals)
        signals = resource.get("platform_signals")
        if isinstance(signals, Mapping):
            values.append(signals)
        return tuple(values)


__all__ = ["INSPECTOR_ID", "YixiInspector"]
