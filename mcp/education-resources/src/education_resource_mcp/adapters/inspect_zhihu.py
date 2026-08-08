"""Public Zhihu inspection with platform-scoped metadata enrichment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..inspection import INSPECTOR_VERSION
from .inspect_bilibili import _PlatformWebInspector


class ZhihuInspector(_PlatformWebInspector):
    """Inspect a public Zhihu answer, article, or question page."""

    platform_id = "zhihu"
    inspector_id = "zhihu"
    version = INSPECTOR_VERSION
    host_suffixes = ("zhihu.com",)
    metadata_allowlist = (
        "answer_id",
        "article_id",
        "question_id",
        "published_at",
        "vote_count",
        "author",
    )

    def _enrich_payload(
        self, resource: Mapping[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        payload = super()._enrich_payload(resource, payload)
        if not self._can_add_representation(payload):
            return payload

        representations = payload["resolved_resource"].get("representations", [])
        if not any(item.get("kind") == "webpage" for item in representations):
            metadata = payload["resolved_resource"].get("metadata", {})
            container = "article" if metadata.get("article_id") else "webpage"
            self._append_representation(
                resource,
                payload,
                kind="webpage",
                container=container,
            )
        return payload


ZhihuResourceInspector = ZhihuInspector
ZhihuPlatformInspector = ZhihuInspector


__all__ = [
    "ZhihuInspector",
    "ZhihuPlatformInspector",
    "ZhihuResourceInspector",
]
