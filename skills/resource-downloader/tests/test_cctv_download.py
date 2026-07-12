from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "platforms"
    / "cctv_download.py"
)
SPEC = importlib.util.spec_from_file_location("cctv_download", MODULE_PATH)
assert SPEC and SPEC.loader
CCTV = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CCTV
SPEC.loader.exec_module(CCTV)


SOURCE_URL = "https://tv.cctv.com/2026/07/08/VIDEexample260708.shtml"
GUID = "137d5338f9fc4b78ab0c6e2338e2855b"
API_URL = (
    "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do"
    f"?pid={GUID}&serviceId=tvcctv"
)
MASTER_URL = (
    "https://hls.cntv.lxdns.com/asp/hls/main/0303000a/3/default/"
    f"{GUID}/main.m3u8?maxbr=2048"
)
LOW_URL = (
    "https://hls.cntv.lxdns.com/asp/hls/450/0303000a/3/default/"
    f"{GUID}/450.m3u8"
)
HIGH_URL = (
    "https://hls.cntv.lxdns.com/asp/hls/1200/0303000a/3/default/"
    f"{GUID}/1200.m3u8"
)
SEGMENT_0 = HIGH_URL.rsplit("/", 1)[0] + "/0.ts"
SEGMENT_1 = HIGH_URL.rsplit("/", 1)[0] + "/1.ts"


def _headers(content_type: str = "application/octet-stream") -> Message:
    headers = Message()
    headers["Content-Type"] = content_type
    return headers


def _response(body: bytes | str, url: str, content_type: str = "application/octet-stream"):
    if isinstance(body, str):
        body = body.encode("utf-8")
    return CCTV.FetchedResponse(body, url, _headers(content_type))


def _ts_packet(fill: int) -> bytes:
    return b"\x47" + bytes([fill]) * 187


def _public_api_document() -> dict:
    return {
        "ack": "yes",
        "status": "001",
        "vid": GUID,
        "cvid": "VIDEexample260708",
        "public": "1",
        "is_preview": "0",
        "is_protected": "0",
        "is_invalid_copyright": "0",
        "asp_error_code": "0",
        "hls_url": MASTER_URL,
    }


class FakeFetcher:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        kwargs["url_validator"](url)
        return response


class CCTVDownloadTests(unittest.TestCase):
    def test_parse_source_restricts_domain_and_shape(self) -> None:
        self.assertEqual(CCTV.parse_source(SOURCE_URL), "VIDEexample260708")
        with self.assertRaisesRegex(CCTV.DownloadError, "域名"):
            CCTV.parse_source(
                "https://tv.cctv.com.evil.test/2026/07/08/VIDEexample260708.shtml"
            )
        with self.assertRaisesRegex(CCTV.DownloadError, "单视频"):
            CCTV.parse_source("https://tv.cctv.com/2026/07/08/index.shtml")
        with self.assertRaisesRegex(CCTV.DownloadError, "查询参数"):
            CCTV.parse_source(SOURCE_URL + "?download=1")

    def test_extract_guid_ignores_parent_guid(self) -> None:
        html = (
            f'<script>var parentGuid = "{"a" * 32}"; '
            f'var guid = "{GUID}";</script>'
        )
        self.assertEqual(CCTV.extract_guid(html), GUID)
        with self.assertRaisesRegex(CCTV.DownloadError, "GUID"):
            CCTV.extract_guid('<script>var parentGuid = "bad";</script>')

    def test_public_api_rejects_protected_or_unknown_media(self) -> None:
        sparse = _public_api_document()
        sparse.pop("vid")
        sparse.pop("cvid")
        self.assertEqual(
            CCTV.extract_public_hls_url(sparse, GUID, "VIDEexample260708"),
            MASTER_URL,
        )

        protected = _public_api_document()
        protected["is_protected"] = "1"
        with self.assertRaisesRegex(CCTV.DownloadError, "受保护"):
            CCTV.extract_public_hls_url(protected, GUID, "VIDEexample260708")

        unknown_host = _public_api_document()
        unknown_host["hls_url"] = "https://example.com/video/main.m3u8"
        with self.assertRaisesRegex(CCTV.DownloadError, "域名"):
            CCTV.extract_public_hls_url(unknown_host, GUID, "VIDEexample260708")

        mismatched_path = _public_api_document()
        mismatched_path["hls_url"] = MASTER_URL.replace(GUID, "a" * 32)
        with self.assertRaisesRegex(CCTV.DownloadError, "页面 GUID"):
            CCTV.extract_public_hls_url(mismatched_path, GUID, "VIDEexample260708")

    def test_master_playlist_selects_highest_bandwidth(self) -> None:
        master = f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=460800,RESOLUTION=480x270
{LOW_URL}
#EXT-X-STREAM-INF:BANDWIDTH=1228800,RESOLUTION=1280x720
{HIGH_URL}
"""
        kind, urls = CCTV.parse_playlist(MASTER_URL, master)
        self.assertEqual(kind, "master")
        self.assertEqual(urls, [HIGH_URL])

    def test_rejects_encrypted_or_live_hls(self) -> None:
        encrypted = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:10,
0.ts
#EXT-X-ENDLIST
"""
        with self.assertRaisesRegex(CCTV.DownloadError, "加密"):
            CCTV.parse_playlist(HIGH_URL, encrypted)

        live = """#EXTM3U
#EXTINF:10,
0.ts
"""
        with self.assertRaisesRegex(CCTV.DownloadError, "VOD"):
            CCTV.parse_playlist(HIGH_URL, live)

    def test_downloads_public_unencrypted_hls_atomically(self) -> None:
        page = f'<html><script>var guid = "{GUID}";</script></html>'
        master = f"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=460800,RESOLUTION=480x270
{LOW_URL}
#EXT-X-STREAM-INF:BANDWIDTH=1228800,RESOLUTION=1280x720
{HIGH_URL}
"""
        media = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:10.0,
0.ts
#EXTINF:5.0,
1.ts
#EXT-X-ENDLIST
"""
        first = _ts_packet(1) * 3
        second = _ts_packet(2) * 2
        fetcher = FakeFetcher(
            {
                SOURCE_URL: _response(page, SOURCE_URL, "text/html; charset=utf-8"),
                API_URL: _response(
                    json.dumps(_public_api_document()),
                    API_URL,
                    "application/json; charset=utf-8",
                ),
                MASTER_URL: _response(master, MASTER_URL, "application/vnd.apple.mpegurl"),
                HIGH_URL: _response(media, HIGH_URL, "application/vnd.apple.mpegurl"),
                SEGMENT_0: _response(first, SEGMENT_0, "video/mp2t"),
                SEGMENT_1: _response(second, SEGMENT_1, "video/mp2t"),
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            path = CCTV.download_video(
                SOURCE_URL,
                directory,
                timeout=5,
                total_timeout=30,
                max_bytes=len(first) + len(second),
                fetcher=fetcher,
            )

            self.assertEqual(path.name, f"cctv-{GUID}.ts")
            self.assertEqual(path.read_bytes(), first + second)
            self.assertEqual(list(Path(directory).glob("*.part")), [])
            CCTV.validate_transport_stream(path)

        called_urls = [url for url, _kwargs in fetcher.calls]
        self.assertEqual(
            called_urls,
            [SOURCE_URL, API_URL, MASTER_URL, HIGH_URL, SEGMENT_0, SEGMENT_1],
        )
        segment_limits = [
            kwargs["max_bytes"]
            for url, kwargs in fetcher.calls
            if url in {SEGMENT_0, SEGMENT_1}
        ]
        self.assertEqual(segment_limits, [len(first) + len(second), len(second)])

    def test_size_failure_removes_partial_file(self) -> None:
        page = f'<script>var guid = "{GUID}";</script>'
        media = """#EXTM3U
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:10,
0.ts
#EXT-X-ENDLIST
"""
        oversized = _ts_packet(7) * 4
        fetcher = FakeFetcher(
            {
                SOURCE_URL: _response(page, SOURCE_URL, "text/html"),
                API_URL: _response(json.dumps(_public_api_document()), API_URL, "application/json"),
                MASTER_URL: _response(media, MASTER_URL, "application/vnd.apple.mpegurl"),
                MASTER_URL.rsplit("/", 1)[0] + "/0.ts": _response(
                    oversized,
                    MASTER_URL.rsplit("/", 1)[0] + "/0.ts",
                    "video/mp2t",
                ),
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CCTV.DownloadError, "最大下载大小"):
                CCTV.download_video(
                    SOURCE_URL,
                    directory,
                    timeout=5,
                    total_timeout=30,
                    max_bytes=len(oversized) - CCTV.TS_PACKET_SIZE,
                    fetcher=fetcher,
                )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_invalid_ts_and_limit_overrides(self) -> None:
        with self.assertRaisesRegex(CCTV.DownloadError, "MPEG-TS"):
            CCTV.validate_ts_segment(b"<html>not a video</html>")
        with self.assertRaisesRegex(CCTV.DownloadError, "不得超过"):
            CCTV.download_video(
                SOURCE_URL,
                tempfile.gettempdir(),
                max_bytes=CCTV.HARD_MAX_BYTES + 1,
                fetcher=mock.Mock(),
            )
        with self.assertRaisesRegex(CCTV.DownloadError, "单请求超时"):
            CCTV.download_video(
                SOURCE_URL,
                tempfile.gettempdir(),
                timeout=CCTV.HARD_MAX_TIMEOUT_SECONDS + 1,
                fetcher=mock.Mock(),
            )


if __name__ == "__main__":
    unittest.main()
