from __future__ import annotations

import re
from urllib.parse import urljoin

_STREAM_INF_RE = re.compile(r"(?:^|,)BANDWIDTH=(\d+)(?:,|$)", re.IGNORECASE)


def select_highest_bandwidth_variant(playlist_text: str) -> str | None:
    """Return the URI of the highest-bandwidth HLS variant in a master list.

    CCTV's getHttpVideoInfo URLs already carry ``maxbr=2048`` for the current
    quality contract. Selecting the highest BANDWIDTH from that bounded master
    therefore chooses the intended top tier instead of accidentally taking the
    first (commonly 450 kbps) variant.
    """

    lines = [line.strip() for line in playlist_text.splitlines()]
    best_uri: str | None = None
    best_bandwidth = -1

    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        match = _STREAM_INF_RE.search(line.split(":", 1)[1])
        if match is None:
            continue
        bandwidth = int(match.group(1))
        uri: str | None = None
        for candidate in lines[index + 1 :]:
            if not candidate:
                continue
            if candidate.startswith("#"):
                continue
            uri = candidate
            break
        if uri is not None and bandwidth > best_bandwidth:
            best_uri = uri
            best_bandwidth = bandwidth

    return best_uri


def resolve_hls_uri(parent_url: str, child_uri: str) -> str:
    """Resolve relative, root-relative, or absolute HLS child URIs."""

    return urljoin(parent_url, child_uri)


__all__ = ["resolve_hls_uri", "select_highest_bandwidth_variant"]
