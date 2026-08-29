from __future__ import annotations

from education_resource_mcp.adapters.cctv_hls import (
    resolve_hls_uri,
    select_highest_bandwidth_variant,
    select_highest_quality_variant,
)


def test_selects_highest_bandwidth_variant_from_bounded_master() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=450000,RESOLUTION=480x270
450.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=850000,RESOLUTION=640x360
850.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=960x540
1200.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2048000,RESOLUTION=1280x720
2000.m3u8
"""

    assert select_highest_bandwidth_variant(playlist) == "2000.m3u8"


def test_variant_selection_does_not_depend_on_playlist_order() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2048000
2000.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=450000
450.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000
1200.m3u8
"""

    assert select_highest_bandwidth_variant(playlist) == "2000.m3u8"


def test_resolution_has_priority_over_bandwidth() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=960x540
high-bitrate-540p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720
lower-bitrate-720p.m3u8
"""

    assert select_highest_bandwidth_variant(playlist) == "lower-bitrate-720p.m3u8"


def test_bandwidth_breaks_tie_at_same_resolution() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720
1200.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2048000,RESOLUTION=1280x720
2000.m3u8
"""

    assert select_highest_bandwidth_variant(playlist) == "2000.m3u8"


def test_quality_selector_returns_score_for_cross_stream_comparison() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2048000,RESOLUTION=1280x720
720p.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=4096000,RESOLUTION=1920x1080
1080p.m3u8
"""

    assert select_highest_quality_variant(playlist) == (
        "1080p.m3u8",
        (1920 * 1080, 4096000),
    )


def test_selects_variant_from_cctv_master_with_spaced_attributes() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:PROGRAM-ID=1, BANDWIDTH=460800, RESOLUTION=640x360
/asp/h5e/hls/450/video/450.m3u8
#EXT-X-STREAM-INF:PROGRAM-ID=1, BANDWIDTH=1228800, RESOLUTION=1280x720
/asp/h5e/hls/1200/video/1200.m3u8
"""

    assert (
        select_highest_bandwidth_variant(playlist)
        == "/asp/h5e/hls/1200/video/1200.m3u8"
    )


def test_does_not_impose_a_fixed_2000_ceiling() -> None:
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2048000,RESOLUTION=1280x720
2000.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3072000,RESOLUTION=1920x1080
3000.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=4096000,RESOLUTION=3840x2160
4000.m3u8
"""

    assert select_highest_bandwidth_variant(playlist) == "4000.m3u8"


def test_returns_none_for_media_playlist() -> None:
    playlist = """#EXTM3U
#EXTINF:10,
seg-001.ts
#EXTINF:10,
seg-002.ts
"""

    assert select_highest_bandwidth_variant(playlist) is None
    assert select_highest_quality_variant(playlist) is None


def test_resolve_hls_uri_supports_relative_root_and_absolute_urls() -> None:
    parent = "https://cdn.example/path/main.m3u8?maxbr=2048"

    assert resolve_hls_uri(parent, "2000.m3u8") == "https://cdn.example/path/2000.m3u8"
    assert resolve_hls_uri(parent, "/video/2000.m3u8") == "https://cdn.example/video/2000.m3u8"
    assert (
        resolve_hls_uri(parent, "https://other.example/2000.m3u8")
        == "https://other.example/2000.m3u8"
    )
