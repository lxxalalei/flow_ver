"""Public Bilibili inspection built on the bounded generic web inspector.

The platform inspectors in this directory only inspect a public landing page.
They deliberately do not use the search adapters' session state or copy
request headers into the result.  Platform metadata is an explicit scalar
allow-list so an ordinary candidate record cannot become an output side
channel for URLs, paths, cookies, or credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
from typing import Any
from urllib.parse import urlsplit

from ..inspection import (
    INSPECTOR_VERSION,
    InspectionResult,
    build_representation_authority,
)
from .inspect_generic import GenericWebInspector, _safe_text


def _platform_host_allowed(source_url: Any, suffixes: tuple[str, ...]) -> bool:
    """Return whether *source_url* has an explicitly allowed public host."""

    if not isinstance(source_url, str) or not source_url:
        return False
    try:
        parsed = urlsplit(source_url)
        host = parsed.hostname
    except (TypeError, ValueError):
        return False
    if not host or parsed.scheme.casefold() not in {"http", "https"}:
        return False
    normalized = host.casefold().rstrip(".")
    return any(normalized == suffix or normalized.endswith("." + suffix) for suffix in suffixes)


def _safe_candidate_scalar(value: Any) -> str | int | float | bool | None:
    """Keep only a bounded scalar safe for the public inspection envelope."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return value if math.isfinite(value) and value >= 0 else None
    if isinstance(value, str):
        return _safe_text(value, 1024)
    return None


def _allowlisted_metadata(
    resource: Mapping[str, Any], keys: tuple[str, ...]
) -> dict[str, str | int | float | bool]:
    metadata = resource.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    result: dict[str, str | int | float | bool] = {}
    for key in keys:
        value = _safe_candidate_scalar(metadata.get(key))
        if value is not None:
            result[key] = value
    return result


def _resource_seed(resource: Mapping[str, Any]) -> str:
    """Build an internal, non-output seed for synthetic representation IDs."""

    resource_id = resource.get("resource_id")
    title = resource.get("title") or resource.get("name")
    return str(resource_id or title or "resource")


def _new_representation_id(
    resource: Mapping[str, Any], kind: str, role: str, ordinal: int
) -> str:
    seed = f"platform-inspection|{_resource_seed(resource)}|{kind}|{role}|{ordinal}"
    return "repr_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


class _PlatformWebInspector(GenericWebInspector):
    """Shared platform wrapper around GenericWebInspector.

    Subclasses only provide host suffixes, identity metadata, and optional
    representation enrichment.  All actual requests still go through the
    generic resolver/transport/redirect loop.
    """

    platform_id = "generic"
    inspector_id = "generic"
    version = INSPECTOR_VERSION
    host_suffixes: tuple[str, ...] = ()
    metadata_allowlist: tuple[str, ...] = ()

    def _platformize(
        self,
        result: InspectionResult,
        resource: Mapping[str, Any] | None,
        *,
        enrich: bool,
    ) -> InspectionResult:
        payload = result.to_mapping()
        inspection = dict(payload["inspection"])
        inspection.update(
            {
                "inspector_id": self.inspector_id,
                "version": self.version,
                "method": "platform_bounded_get",
            }
        )
        payload["inspection"] = inspection

        failures = []
        for raw_failure in payload.get("failures", []):
            failure = dict(raw_failure)
            failure["platform"] = self.platform_id
            failures.append(failure)
        payload["failures"] = failures

        if enrich and isinstance(resource, Mapping):
            payload = self._enrich_payload(resource, payload)
        return InspectionResult.from_mapping(payload)

    def _enrich_payload(
        self, resource: Mapping[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        metadata = _allowlisted_metadata(resource, self.metadata_allowlist)
        resolved = dict(payload["resolved_resource"])
        merged_metadata = dict(resolved.get("metadata") or {})
        merged_metadata.update(metadata)
        resolved["metadata"] = merged_metadata
        author = metadata.get("author")
        if isinstance(author, str) and author and not resolved.get("creator"):
            resolved["creator"] = author
        payload["resolved_resource"] = resolved
        return payload

    @staticmethod
    def _can_add_representation(payload: Mapping[str, Any]) -> bool:
        status = payload.get("resolution_status")
        if status not in {"resolved", "partial"}:
            return False
        availability = payload.get("resolved_resource", {}).get("availability", {})
        if availability.get("status") in {
            "auth_required",
            "unavailable",
            "policy_blocked",
        }:
            return False
        return True

    def _append_representation(
        self,
        resource: Mapping[str, Any],
        payload: dict[str, Any],
        *,
        kind: str,
        role: str = "companion",
        container: str | None = None,
        mime_type: str | None = None,
        scope: str | None = None,
    ) -> None:
        resolved = payload["resolved_resource"]
        representations = [dict(item) for item in resolved.get("representations", [])]
        if any(
            item.get("kind") == kind
            and item.get("role") == role
            and (
                container is None
                or item.get("container") in {None, container}
            )
            for item in representations
        ):
            return
        if scope is None:
            scope = {
                "primary": "primary_resource",
                "landing": "landing_page",
                "metadata": "metadata",
            }.get(role, "representation")
        representation: dict[str, Any] = {
            "representation_id": _new_representation_id(
                resource, kind, role, len(representations)
            ),
            "kind": kind,
            "scope": scope,
            "role": role,
            "technical_availability": "unknown",
            "materializable": False,
        }
        if container:
            representation["container"] = container
        if mime_type:
            representation["mime_type"] = mime_type
        observed_at = payload.get("inspection", {}).get("inspected_at")
        representation.update(
            build_representation_authority(
                resource,
                scope=scope,
                role=role,
                technical_availability="unknown",
                source="metadata",
                observed_at=observed_at if isinstance(observed_at, str) else None,
            )
        )
        for item in representations:
            if item.get("kind") == "webpage" and item.get("role") == "primary":
                item["role"] = "landing"
        representations.append(representation)
        resolved["representations"] = representations

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if isinstance(resource, Mapping):
            source_url = resource.get("source_url")
            if isinstance(source_url, str) and source_url:
                if not _platform_host_allowed(source_url, self.host_suffixes):
                    blocked = super()._error_result(
                        resource,
                        "NETWORK_BLOCKED",
                        "候选地址不属于当前平台允许的公开域名",
                        False,
                        availability="policy_blocked",
                    )
                    return self._platformize(blocked, resource, enrich=False)

        try:
            result = super().inspect(resource)
            return self._platformize(result, resource, enrich=True)
        except Exception:
            safe_resource = resource if isinstance(resource, Mapping) else {}
            fallback = super()._error_result(
                safe_resource,
                "PARTIAL_FAILURE",
                "平台公开详情检查失败",
                True,
            )
            return self._platformize(fallback, safe_resource, enrich=False)


class BilibiliInspector(_PlatformWebInspector):
    """Inspect a public Bilibili video landing page."""

    platform_id = "bilibili"
    inspector_id = "bilibili"
    version = INSPECTOR_VERSION
    host_suffixes = ("bilibili.com", "b23.tv", "hdslb.com")
    metadata_allowlist = (
        "bvid",
        "duration_seconds",
        "play_count",
        "published_at",
        "author",
    )

    def _enrich_payload(
        self, resource: Mapping[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        payload = super()._enrich_payload(resource, payload)
        if self._can_add_representation(payload):
            self._append_representation(
                resource, payload, kind="video", container="video", role="companion"
            )
        return payload


# Explicit aliases keep the adapter discoverable to callers that use the
# platform-name convention instead of the longer ResourceInspector name.
BilibiliResourceInspector = BilibiliInspector
BilibiliPlatformInspector = BilibiliInspector


__all__ = [
    "BilibiliInspector",
    "BilibiliPlatformInspector",
    "BilibiliResourceInspector",
]
