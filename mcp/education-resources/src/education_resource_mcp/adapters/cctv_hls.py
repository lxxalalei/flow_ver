from __future__ import annotations

import re
from urllib.parse import urljoin

_BANDWIDTH_RE = re.compile(
    r"(?:^|,)\s*BANDWIDTH\s*=\s*(\d+)\s*(?:,|$)", re.IGNORECASE
)
_RESOLUTION_RE = re.compile(
    r"(?:^|,)\s*RESOLUTION\s*=\s*(\d+)\s*x\s*(\d+)\s*(?:,|$)",
    re.IGNORECASE,
)


def select_highest_quality_variant(
    playlist_text: str,
) -> tuple[str, tuple[int, int]] | None:
    """Return ``(uri, (pixels, bandwidth))`` for the best master variant.

    Resolution is the primary quality signal and BANDWIDTH breaks ties. When a
    variant omits RESOLUTION its pixel score is zero, so masters that expose
    real resolution metadata are ranked by that fact rather than by URL order.
    No fixed CCTV bitrate ceiling is imposed here.
    """

    lines = [line.strip() for line in playlist_text.splitlines()]
    best_uri: str | None = None
    best_score = (-1, -1)

    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = line.split(":", 1)[1]
        bandwidth_match = _BANDWIDTH_RE.search(attributes)
        if bandwidth_match is None:
            continue
        bandwidth = int(bandwidth_match.group(1))
        resolution_match = _RESOLUTION_RE.search(attributes)
        pixels = 0
        if resolution_match is not None:
            width = int(resolution_match.group(1))
            height = int(resolution_match.group(2))
            pixels = width * height

        uri: str | None = None
        for candidate in lines[index + 1 :]:
            if not candidate:
                continue
            if candidate.startswith("#"):
                continue
            uri = candidate
            break

        score = (pixels, bandwidth)
        if uri is not None and score > best_score:
            best_uri = uri
            best_score = score

    if best_uri is None:
        return None
    return best_uri, best_score


def select_highest_bandwidth_variant(playlist_text: str) -> str | None:
    """Backward-compatible URI-only wrapper for the highest-quality variant."""

    selected = select_highest_quality_variant(playlist_text)
    return selected[0] if selected is not None else None


def resolve_hls_uri(parent_url: str, child_uri: str) -> str:
    """Resolve relative, root-relative, or absolute HLS child URIs."""

    return urljoin(parent_url, child_uri)


__all__ = [
    "resolve_hls_uri",
    "select_highest_bandwidth_variant",
    "select_highest_quality_variant",
]
