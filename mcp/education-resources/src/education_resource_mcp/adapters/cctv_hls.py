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


def select_highest_bandwidth_variant(playlist_text: str) -> str | None:
    """Return the highest-quality HLS variant exposed by a master playlist.

    Quality is ranked by encoded resolution first and BANDWIDTH second. When a
    master omits RESOLUTION entirely, BANDWIDTH remains the deciding signal.
    The function intentionally does not impose a 450/1200/2000 ceiling: the
    server-provided master decides which quality levels actually exist.
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

    return best_uri


def resolve_hls_uri(parent_url: str, child_uri: str) -> str:
    """Resolve relative, root-relative, or absolute HLS child URIs."""

    return urljoin(parent_url, child_uri)


__all__ = ["resolve_hls_uri", "select_highest_bandwidth_variant"]
