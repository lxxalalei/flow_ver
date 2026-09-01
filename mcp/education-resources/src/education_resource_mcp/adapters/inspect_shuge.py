"""Bounded Shuge (书格) inspection.

The search adapter returns direct-download URLs into the public OpenList
storage (shuge.hanjihebi.com).  This inspector requires a server-controlled
``file_path`` in platform metadata and then lets the shared Generic inspector
verify the real host, DNS, redirects, response size and content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..inspection import InspectionResult
from .inspect_platform_bounded import PlatformBoundedInspector


INSPECTOR_ID = "shuge"
ALLOWED_HOST_SUFFIXES = ("hanjihebi.com", "shuge.org")


class ShugeInspector(PlatformBoundedInspector):
    """Inspect a Shuge public-storage direct-download resource."""

    platform_id = "shuge"
    inspector_id = INSPECTOR_ID
    allowed_host_suffixes = ALLOWED_HOST_SUFFIXES
    allow_any_public_host = False

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if isinstance(resource, Mapping):
            file_path = None
            for mapping in self._file_path_mappings(resource):
                candidate = mapping.get("file_path")
                if isinstance(candidate, str) and candidate.strip():
                    file_path = candidate.strip()
                    break
            if file_path is None:
                return self._validation_result(
                    resource,
                    "PLATFORM_VALIDATION_BLOCKED",
                    "书格检查需要资源元数据中的服务端 file_path 字段",
                )
        return super().inspect(resource)

    @staticmethod
    def _file_path_mappings(resource: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
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