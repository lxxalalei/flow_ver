from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock


PLATFORMS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "platforms"
sys.path.insert(0, str(PLATFORMS_DIR))

import open163_download


MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42payload"


class _Response(io.BytesIO):
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        content_type: str = "application/octet-stream",
        content_length: int | None = None,
    ) -> None:
        super().__init__(body)
        self.status = 200
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(
            len(body) if content_length is None else content_length
        )

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _page_html() -> str:
    return """<!doctype html><html><head><title>Fallback</title></head><body>
<div class="video-title">A safe / public lesson</div>
<video src="https://mov.bn.netease.com/course/CURRENT_shd.m3u8"></video>
<script>
window.__NUXT__={mp4SdUrl:"https:\\u002F\\u002Fmov.bn.netease.com\\u002Fcourse\\u002FCURRENT_sd.mp4",
mp4HdUrl:"https:\\u002F\\u002Fmov.bn.netease.com\\u002Fcourse\\u002FCURRENT_hd.mp4",
mostClearMp4Info:{"https:\\u002F\\u002Fmov.bn.netease.com\\u002Fcourse\\u002FCURRENT_shd.mp4":1}};
</script></body></html>"""


class Open163DownloadTests(unittest.TestCase):
    def test_parse_source_accepts_current_and_legacy_urls(self) -> None:
        self.assertEqual(
            open163_download.parse_source_url(
                "https://open.163.com/newview/movie/free?mid=MID1&pid=PID1#fragment"
            ),
            "https://open.163.com/newview/movie/free?pid=PID1&mid=MID1",
        )
        self.assertEqual(
            open163_download.parse_source_url(
                "https://open.163.com/movie/2017/1/V/U/PID2_MID2.html"
            ),
            "https://open.163.com/newview/movie/free?pid=PID2&mid=MID2",
        )

    def test_parse_source_rejects_other_domains_and_nonstandard_ports(self) -> None:
        with self.assertRaisesRegex(open163_download.DownloadError, "open.163.com"):
            open163_download.parse_source_url(
                "https://evil.example/newview/movie/free?pid=PID1"
            )
        with self.assertRaisesRegex(open163_download.DownloadError, "端口"):
            open163_download.parse_source_url(
                "https://open.163.com:8443/newview/movie/free?pid=PID1"
            )

    def test_extract_media_prefers_current_highest_quality_mp4(self) -> None:
        direct, hls, title = open163_download.extract_media_options(
            _page_html(),
            "https://open.163.com/newview/movie/free?pid=PID1&mid=MID1",
        )

        self.assertEqual(
            direct,
            [
                "https://mov.bn.netease.com/course/CURRENT_shd.mp4",
                "https://mov.bn.netease.com/course/CURRENT_hd.mp4",
                "https://mov.bn.netease.com/course/CURRENT_sd.mp4",
            ],
        )
        self.assertEqual(
            hls, "https://mov.bn.netease.com/course/CURRENT_shd.m3u8"
        )
        self.assertEqual(title, "A safe / public lesson")

    def test_extract_media_rejects_unapproved_cdn(self) -> None:
        page = '<video src="https://cdn.evil.example/video.m3u8"></video>'
        with self.assertRaisesRegex(open163_download.DownloadError, "允许列表"):
            open163_download.extract_media_options(
                page,
                "https://open.163.com/newview/movie/free?pid=PID1&mid=MID1",
            )

    def test_stream_media_enforces_content_length_before_writing(self) -> None:
        response = _Response(
            MP4_BYTES,
            url="https://mov.bn.netease.com/video.mp4",
            content_type="video/mp4",
            content_length=10_000,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "video.mp4"
            with self.assertRaises(open163_download.SizeLimitError):
                open163_download.stream_media(
                    "https://mov.bn.netease.com/video.mp4",
                    destination,
                    "https://open.163.com/newview/movie/free?pid=PID1",
                    timeout=2,
                    max_bytes=100,
                    opener=mock.Mock(return_value=response),
                )
            self.assertFalse(destination.exists())

    def test_download_falls_back_to_lower_mp4_when_largest_exceeds_limit(self) -> None:
        final_url = "https://open.163.com/newview/movie/free?pid=PID1&mid=MID1"
        page_response = _Response(
            _page_html().encode(),
            url=final_url,
            content_type="text/html; charset=utf-8",
        )
        requested: list[str] = []

        def media_open(request, timeout):
            requested.append(request.full_url)
            if request.full_url.endswith("_shd.mp4"):
                return _Response(
                    MP4_BYTES,
                    url=request.full_url,
                    content_type="video/mp4",
                    content_length=10_000,
                )
            return _Response(
                MP4_BYTES,
                url=request.full_url,
                content_type="video/mp4",
            )

        with tempfile.TemporaryDirectory() as directory:
            result = open163_download.download_open163(
                "https://open.163.com/newview/movie/free?pid=PID1",
                directory,
                timeout=2,
                max_bytes=100,
                page_opener=mock.Mock(return_value=page_response),
                media_opener=media_open,
            )

            self.assertEqual(result.read_bytes(), MP4_BYTES)
            self.assertEqual(
                requested[:2],
                [
                    "https://mov.bn.netease.com/course/CURRENT_shd.mp4",
                    "https://mov.bn.netease.com/course/CURRENT_hd.mp4",
                ],
            )
            self.assertEqual(result.name, "A safe _ public lesson-MID1.mp4")

    def test_hls_rejects_encryption_live_and_byte_ranges(self) -> None:
        cases = (
            "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n",
            "#EXTM3U\n#EXTINF:1,\na.ts\n",
            "#EXTM3U\n#EXT-X-BYTERANGE:100@0\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n",
            "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\",BYTERANGE=\"100@0\"\n#EXTINF:1,\na.m4s\n#EXT-X-ENDLIST\n",
            "#EXTM3U\n#EXT-X-I-FRAMES-ONLY\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST\n",
        )
        for playlist in cases:
            with self.subTest(playlist=playlist):
                with self.assertRaises(open163_download.DownloadError):
                    open163_download.prepare_hls_media_playlist(
                        playlist,
                        "https://mov.bn.netease.com/course/index.m3u8",
                    )

    def test_hls_master_selects_highest_public_variant(self) -> None:
        playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720
high/index.m3u8
"""
        self.assertEqual(
            open163_download.select_hls_media_playlist(
                playlist, "https://mov.bn.netease.com/course/master.m3u8"
            ),
            "https://mov.bn.netease.com/course/high/index.m3u8",
        )

    def test_download_hls_uses_only_local_files_for_ffmpeg(self) -> None:
        playlist_url = "https://mov.bn.netease.com/course/index.m3u8"
        playlist = b"#EXTM3U\n#EXTINF:1,\nseg1.ts\n#EXTINF:1,\nseg2.ts\n#EXT-X-ENDLIST\n"
        payloads = {
            playlist_url: playlist,
            "https://mov.bn.netease.com/course/seg1.ts": b"segment-one",
            "https://mov.bn.netease.com/course/seg2.ts": b"segment-two",
        }

        def media_open(request, timeout):
            return _Response(payloads[request.full_url], url=request.full_url)

        commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            commands.append(command)
            Path(command[-1]).write_bytes(MP4_BYTES)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "merged.mp4"
            with mock.patch.object(open163_download.subprocess, "run", side_effect=fake_run):
                open163_download.download_hls(
                    playlist_url,
                    destination,
                    "https://open.163.com/newview/movie/free?pid=PID1",
                    timeout=2,
                    max_bytes=1_000,
                    opener=media_open,
                    ffmpeg_path="ffmpeg-test",
                )

            self.assertEqual(destination.read_bytes(), MP4_BYTES)
            self.assertEqual(commands[0][commands[0].index("-protocol_whitelist") + 1], "file")
            self.assertFalse(any("https://" in argument for argument in commands[0]))

    def test_main_supports_download_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "result.mp4"
            with mock.patch.object(
                open163_download,
                "download_open163",
                return_value=expected,
            ) as download, mock.patch.object(
                sys,
                "argv",
                [
                    "open163_download.py",
                    "download",
                    "https://open.163.com/newview/movie/free?pid=PID1",
                    "-o",
                    directory,
                ],
            ):
                self.assertEqual(open163_download.main(), 0)
            download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
