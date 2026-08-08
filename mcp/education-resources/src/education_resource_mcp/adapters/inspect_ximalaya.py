"""Bounded public inspection for Ximalaya album and track pages."""

from __future__ import annotations

from collections.abc import Mapping
import re
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


INSPECTOR_ID = "ximalaya"
_PATH_ID_RE = re.compile(r"/(?:album|sound)/([0-9]{1,32})(?:/|$)", re.IGNORECASE)


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
    """Inspect public landing metadata without requesting an audio stream."""

    platform_id = "ximalaya"
    inspector_id = INSPECTOR_ID
    allowed_host_suffixes = ("ximalaya.com", "xmcdn.com")

    def _enrich(self, resource: Mapping[str, Any], result: InspectionResult) -> InspectionResult:
        if not self._enrichment_allowed(result):
            return result

        metadata: dict[str, Any] = {}
        album_id = _safe_numeric_id(_first_value(resource, "album_id", "albumId"))
        if album_id is None:
            album_id = _path_identifier(resource, "album")
        if album_id:
            metadata["album_id"] = album_id

        track_id = _safe_numeric_id(_first_value(resource, "track_id", "trackId", "sound_id"))
        if track_id is None:
            track_id = _path_identifier(resource, "sound")
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
        audio: dict[str, Any] = {
            "representation_id": self._representation_id(resource, "audio", "primary"),
            "kind": "audio",
            "container": "audio",
            "role": "primary",
            # Inspection proves that an audio representation exists in the
            # public model; it does not authorize or materialize a stream.
            "materializable": False,
            "requires_auth": False,
        }
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
                "role": "landing",
                "materializable": True,
                "requires_auth": False,
            }
        landing.setdefault("container", "html")
        landing.setdefault("mime_type", "text/html")
        landing["kind"] = "webpage"
        landing["role"] = "landing"

        return self._rewrite_result(
            resource,
            result,
            resource_type="audio",
            metadata=metadata,
            representations=[audio, landing],
            creator=author,
        )


__all__ = ["INSPECTOR_ID", "PLATFORM_INSPECTION_METHOD", "XimalayaInspector"]
