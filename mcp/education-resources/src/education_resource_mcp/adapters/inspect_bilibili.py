"""Bilibili inspection backed by current playurl DASH facts.

Fetches the public landing page for metadata, then calls the WBI-signed
playurl API (the same chain the downloader uses) to verify that a concrete
DASH video stream is obtainable.  When verified, emits a materializable
``primary_resource / video / mp4`` representation.  Requires ffmpeg on the
host for the download step (the merge happens at Job time, not here).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import math
from typing import Any
from urllib.parse import urlsplit

from ..inspection import (
    INSPECTOR_VERSION,
    InspectionResult,
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
    """Inspect a public Bilibili video and verify a concrete DASH stream."""

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

    def __init__(
        self,
        *args: Any,
        session_store: Any | None = None,
        playurl_verify_func: Callable[[str, str], dict[str, Any] | None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._session_store = session_store
        self._playurl_verify_func = playurl_verify_func

    # ------------------------------------------------------------------
    # DASH verification
    # ------------------------------------------------------------------

    def _cookie(self) -> str:
        if self._session_store is None:
            return ""
        from ..sessions import SessionStore

        data = self._session_store.get_session_data("bilibili")
        if not data:
            return ""
        return SessionStore._cookie_header(data)

    def _verify_dash(self, bvid: str) -> dict[str, Any] | None:
        """Call the playurl chain and return ``{title}`` or ``None``.

        The returned dict carries no stream URL — only the fact that a
        concrete DASH video was confirmed and its title.
        """

        if self._playurl_verify_func is not None:
            return self._playurl_verify_func(bvid, self._cookie())
        try:
            from .bilibili_download import (
                NAV_URL,
                PLAYURL_URL,
                VIEW_URL,
                _request_json,
            )
            from .wbi import wbi_sign
            from urllib.parse import urlencode

            cookie = self._cookie()
            nav = _request_json(NAV_URL, cookie)
            wbi = (nav.get("data") or {}).get("wbi_img") or {}
            img_key = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
            sub_key = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
            if not img_key or not sub_key:
                return None
            view = _request_json(f"{VIEW_URL}?bvid={bvid}", cookie)
            if view.get("code") != 0:
                return None
            view_data = view.get("data") or {}
            cid = view_data.get("cid")
            if not cid:
                return None
            params = wbi_sign(
                {"bvid": bvid, "cid": str(cid), "qn": "80", "fnval": "16", "fourk": "1"},
                img_key,
                sub_key,
            )
            play = _request_json(f"{PLAYURL_URL}?{urlencode(params)}", cookie)
            if play.get("code") != 0:
                return None
            dash = (play.get("data") or {}).get("dash")
            if not dash:
                return None
            videos = [
                v for v in (dash.get("video") or [])
                if v.get("baseUrl") or v.get("base_url")
            ]
            if not videos:
                return None
            return {"title": str(view_data.get("title") or "")}
        except Exception:
            return None

    def _enrich_payload(
        self, resource: Mapping[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        payload = super()._enrich_payload(resource, payload)
        if not self._can_add_representation(payload):
            return payload

        import re as _re

        bvid_match = _re.search(r"BV[A-Za-z0-9]{10}", str(resource.get("source_url") or ""))
        verified = self._verify_dash(bvid_match.group(0)) if bvid_match else None

        if verified is not None:
            # Replace any existing companion video with a concrete primary.
            resolved = dict(payload["resolved_resource"])
            representations = [
                dict(item) for item in resolved.get("representations", [])
                if not (item.get("kind") == "video")
            ]
            primary: dict[str, Any] = {
                "representation_id": _new_representation_id(
                    resource, "video", "primary", 0
                ),
                "kind": "video",
                "container": "mp4",
                "mime_type": "video/mp4",
                "scope": "primary_resource",
                "role": "primary",
                "technical_availability": "available",
                "materializable": True,
            }
            representations.insert(0, primary)
            resolved["representations"] = representations
            resolved["availability"] = {"status": "available"}
            resolved["resource_type"] = "video"
            payload["resolved_resource"] = resolved
            payload["inspection"]["method"] = "platform_playurl_api"
        else:
            # Non-materializable companion when DASH cannot be verified.
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
