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


def contiguous_segment_groups(segment_count: int, max_groups: int) -> list[list[int]]:
    """Split ordered HLS segment indexes into contiguous groups.

    Group-level parallelism is safe only when each worker receives a contiguous
    slice and group outputs are concatenated in group order. Interleaving
    indexes across workers (0,4,8 / 1,5,9 / ...) destroys playback order when
    the resulting TS files are concatenated by group.
    """

    if segment_count <= 0 or max_groups <= 0:
        return []
    group_count = min(segment_count, max_groups)
    chunk_size = (segment_count + group_count - 1) // group_count
    return [
        list(range(start, min(start + chunk_size, segment_count)))
        for start in range(0, segment_count, chunk_size)
    ]


__all__ = [
    "contiguous_segment_groups",
    "resolve_hls_uri",
    "select_highest_bandwidth_variant",
]
