"""Bounded public inspection for Ximalaya album and track pages.

When the candidate resolves to a concrete ``track_id`` (a ``/sound/{id}`` URL
or explicit metadata), the inspector calls the signed ``baseInfo`` API to
verify that a playable audio stream exists and emits a materializable
``primary_resource / audio / mp3|m4a`` representation.  Album-only candidates
remain non-materializable — the user must select a specific track first; the
inspector never silently treats an album as its first track.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
from typing import Any
from urllib.parse import urlsplit

from ..inspection import InspectionResult
from .inspect_nlc import (
    PLATFORM_INSPECTION_METHOD,
    PlatformBoundedInspector,
    _first_text,
    _first_value,
    _safe_integer,
    _safe_numeric_id,
)
import re


INSPECTOR_ID = "ximalaya"
_PATH_ID_RE = re.compile(r"/(?:album|sound)/([0-9]{1,32})(?:/|$)", re.IGNORECASE)
_SOUND_PATH_RE = re.compile(r"/sound/([0-9]{1,32})(?:/|$)", re.IGNORECASE)

_MIME_BY_CONTAINER: dict[str, str] = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
}


def _path_identifier(resource: Mapping[str, Any], segment: str) -> str | None:
    source_url = resource.get("source_url")
    if not isinstance(source_url, str):
        return None
    try:
        path = urlsplit(source_url).path
    except ValueError:
        return None
    match = re.search(rf"/{re.escape(segment)}/([0-9]{{1,32}})(?:/|$)", path, re.IGNORECASE)
    return match.group(1) if match else None


class XimalayaInspector(PlatformBoundedInspector):
    """Inspect public landing metadata and, when a track is identified,
    verify a concrete audio stream via the baseInfo API."""

    platform_id = "ximalaya"
    inspector_id = INSPECTOR_ID
    allowed_host_suffixes = ("ximalaya.com", "xmcdn.com")

    def __init__(
        self,
        *args: Any,
        session_store: Any | None = None,
        track_verify_func: Callable[[str, str], dict[str, Any] | None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._session_store = session_store
        self._track_verify_func = track_verify_func

    # ------------------------------------------------------------------
    # track verification
    # ------------------------------------------------------------------

    def _resolve_track_id(self, resource: Mapping[str, Any]) -> str | None:
        """Return a concrete track_id, or None for album-only candidates."""

        track_id = _safe_numeric_id(_first_value(resource, "track_id", "trackId", "sound_id"))
        if track_id is None:
            track_id = _path_identifier(resource, "sound")
        return track_id

    def _verify_track(self, track_id: str) -> dict[str, Any] | None:
        """Call the baseInfo API (or injected verify func) and return track
        facts ``{title, container, file_size}`` or ``None`` on failure.

        The returned dict intentionally carries no download URL.
        """

        if self._track_verify_func is not None:
            return self._track_verify_func(track_id, self._cookie())
        # Production path: defer to the downloader's track-info helper.
        try:
            from .ximalaya_download import _get_track_info

            info = _get_track_info(track_id, self._cookie())
        except Exception:
            return None
        raw_type = str(info.get("type") or "").upper()
        container = "m4a" if "M4A" in raw_type else "mp3"
        return {
            "title": str(info.get("title") or ""),
            "container": container,
            "file_size": int(info.get("file_size") or 0),
        }

    def _cookie(self) -> str:
        if self._session_store is None:
            return ""
        from ..sessions import SessionStore

        data = self._session_store.get_session_data("ximalaya")
        if not data:
            return ""
        return SessionStore._cookie_header(data)

    # ------------------------------------------------------------------
    # enrichment
    # ------------------------------------------------------------------

    def _enrich(self, resource: Mapping[str, Any], result: InspectionResult) -> InspectionResult:
        if not self._enrichment_allowed(result):
            return result

        metadata: dict[str, Any] = {}
        album_id = _safe_numeric_id(_first_value(resource, "album_id", "albumId"))
        if album_id is None:
            album_id = _path_identifier(resource, "album")
        if album_id:
            metadata["album_id"] = album_id

        track_id = self._resolve_track_id(resource)
        if track_id:
            metadata["track_id"] = track_id

        author = _first_text(resource, "author", "creator", "nickname", "主播")
        if author:
            metadata["author"] = author

        duration = _safe_integer(
            _first_value(resource, "duration_seconds", "duration", "durationSeconds")
        )
        if duration is not None:
            metadata["duration_seconds"] = duration
        track_count = _safe_integer(
            _first_value(resource, "track_count", "tracks", "trackCount")
        )
        if track_count is not None:
            metadata["track_count"] = track_count
        play_count = _safe_integer(
            _first_value(resource, "play_count", "play", "plays", "playCount")
        )
        if play_count is not None:
            metadata["play_count"] = play_count

        current = result.to_mapping()["resolved_resource"]["representations"]
        base = current[0] if current else {}

        # Attempt concrete track verification
        verified = self._verify_track(track_id) if track_id else None

        if verified is not None:
            container = str(verified.get("container") or "mp3")
            audio: dict[str, Any] = {
                "representation_id": self._representation_id(
                    resource, "audio", "primary_resource"
                ),
                "kind": "audio",
                "container": container,
                "mime_type": _MIME_BY_CONTAINER.get(container, "audio/mpeg"),
                "scope": "primary_resource",
                "role": "primary",
                "technical_availability": "available",
                "materializable": True,
            }
            file_size = int(verified.get("file_size") or 0)
            if file_size > 0:
                audio["size_bytes"] = file_size
            representations = [audio]
            resource_type = "audio"
            availability = {"status": "available"}
        else:
            # Album-level or unverifiable: non-materializable companion audio
            audio = {
                "representation_id": self._representation_id(
                    resource, "audio", "representation"
                ),
                "kind": "audio",
                "container": "audio",
                "scope": "representation",
                "role": "companion",
                "technical_availability": "unknown",
                "materializable": False,
            }
            representations = [audio]
            resource_type = "audio"
            availability = {"status": "unknown"}

        if isinstance(base, Mapping) and base.get("language"):
            audio["language"] = base["language"]

        if isinstance(base, Mapping):
            landing = self._copy_representation(
                resource,
                base,
                kind="webpage",
                role="landing",
            )
        else:
            landing = {
                "representation_id": self._representation_id(resource, "webpage", "landing"),
                "kind": "webpage",
                "container": "html",
                "mime_type": "text/html",
                "scope": "landing_page",
                "role": "landing",
                "technical_availability": "unknown",
                "materializable": False,
            }
        landing.setdefault("container", "html")
        landing.setdefault("mime_type", "text/html")
        landing["kind"] = "webpage"
        landing["role"] = "landing"
        representations.append(landing)

        return self._rewrite_result(
            resource,
            result,
            resource_type=resource_type,
            metadata=metadata,
            representations=representations,
            creator=author,
            availability=availability.get("status") if isinstance(availability, dict) else None,
        )


__all__ = ["INSPECTOR_ID", "PLATFORM_INSPECTION_METHOD", "XimalayaInspector"]
