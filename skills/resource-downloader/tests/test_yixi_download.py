from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest import mock


PLATFORMS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "platforms"
sys.path.insert(0, str(PLATFORMS_DIR))

import yixi_download


class _Response(io.BytesIO):
    def __init__(self, body: bytes, content_type: str = "video/mp4") -> None:
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return self.response


class YixiDownloadTests(unittest.TestCase):
    def test_parses_supported_stage3_detail_urls(self) -> None:
        speech = yixi_download.parse_source_url(
            "https://www.yixi.tv/speech/detail?id=768"
        )
        record = yixi_download.parse_source_url(
            "https://www.yixi.tv/record/detail?id=9"
        )
        zhiya = yixi_download.parse_source_url(
            "https://www.yixi.tv/zhiya/detail?id=74&episodeId=144"
        )

        self.assertEqual((speech.kind, speech.video_id, speech.video_type), ("speech", "768", 0))
        self.assertEqual((record.kind, record.video_id, record.video_type), ("record", "9", 4))
        self.assertEqual(
            (zhiya.kind, zhiya.video_id, zhiya.video_type, zhiya.album_id),
            ("zhiya", "144", 2, "74"),
        )

    def test_rejects_foreign_hosts_credentials_and_incomplete_zhiya_urls(self) -> None:
        invalid = [
            "https://example.com/speech/detail?id=768",
            "https://user:pass@www.yixi.tv/speech/detail?id=768",
            "https://www.yixi.tv/zhiya/detail?id=74",
            "https://www.yixi.tv/speech/detail?id=abc",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(yixi_download.DownloadError):
                yixi_download.parse_source_url(url)

    def test_selects_highest_public_video_quality(self) -> None:
        metadata = {
            "video_url": [
                {"type": 1, "video_url": "http://alicdn.yixi.tv/low.mp4"},
                {"type": 3, "video_url": ""},
                {"type": 2, "video_url": "https://alicdn.yixi.tv/high.mp4"},
            ]
        }

        self.assertEqual(
            yixi_download.select_media_urls(metadata),
            [
                "https://alicdn.yixi.tv/high.mp4",
                "https://alicdn.yixi.tv/low.mp4",
            ],
        )

    def test_downloads_public_mp4_atomically(self) -> None:
        body = b"\x00\x00\x00\x18ftypisom" + b"video-data"
        opener = _Opener(_Response(body))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "talk.mp4"
            with mock.patch.object(yixi_download, "_validate_media_url"), mock.patch.object(
                yixi_download.urllib.request,
                "build_opener",
                return_value=opener,
            ):
                result = yixi_download._download_direct_media(
                    "https://alicdn.yixi.tv/talk.mp4",
                    destination,
                    timeout=4.0,
                    max_bytes=10_000,
                )

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), body)
            self.assertEqual(opener.timeout, 4.0)
            self.assertFalse(any(Path(directory).glob("*.part")))

    def test_member_only_resource_is_never_downloaded_or_degraded(self) -> None:
        metadata = {
            "title": "会员内容",
            "member_type": 2,
            "video_url": [{"type": 2, "video_url": "https://alicdn.yixi.tv/locked.mp4"}],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            yixi_download, "fetch_play_metadata", return_value=metadata
        ), mock.patch.object(yixi_download, "_download_media_candidate") as media, mock.patch.object(
            yixi_download, "request_api"
        ) as request_api:
            with self.assertRaisesRegex(yixi_download.DownloadError, "会员专享"):
                yixi_download.download_resource(
                    "https://www.yixi.tv/speech/detail?id=768",
                    directory,
                )

        media.assert_not_called()
        request_api.assert_not_called()

    def test_saves_public_draft_as_explicit_level2_markdown(self) -> None:
        metadata = {
            "title": "测试演讲",
            "member_type": 1,
            "speaker": {"name": "测试讲者"},
            "video_url": [],
        }
        draft = (
            "<p>这是第一段公开完整文稿，包含足够多的正文用于验证。</p>"
            "<p>这是第二段正文，继续提供完整、可读且明确的内容。</p>"
        )

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            yixi_download, "fetch_play_metadata", return_value=metadata
        ), mock.patch.object(
            yixi_download,
            "request_api",
            return_value={"draft": draft},
        ) as request_api:
            result = yixi_download.download_resource(
                "https://www.yixi.tv/speech/detail?id=768",
                directory,
            )

            content = result.path.read_text(encoding="utf-8")

        self.assertEqual(result.level, "Level 2")
        self.assertEqual(result.artifact_type, "public-transcript")
        self.assertIn("Level 2（公开完整文稿，非原视频）", content)
        self.assertIn("测试讲者", content)
        self.assertIn("第一段公开完整文稿", content)
        request_api.assert_called_once_with(
            yixi_download.DRAFT_URL,
            {"id": "768", "type": "0"},
            30.0,
        )

    def test_downloads_highest_bandwidth_unencrypted_hls_as_ts(self) -> None:
        master = b"""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=100000
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=500000
high/index.m3u8
"""
        media = b"""#EXTM3U
#EXT-X-TARGETDURATION:5
#EXTINF:5,
seg-1.ts
#EXTINF:5,
seg-2.ts
#EXT-X-ENDLIST
"""
        responses = {
            "https://alicdn.yixi.tv/master.m3u8": master,
            "https://alicdn.yixi.tv/high/index.m3u8": media,
            "https://alicdn.yixi.tv/high/seg-1.ts": b"Gsegment-one",
            "https://alicdn.yixi.tv/high/seg-2.ts": b"Gsegment-two",
        }

        def read_url(url, **kwargs):
            return responses[url]

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            yixi_download, "_validate_media_url"
        ), mock.patch.object(yixi_download, "_read_url_bytes", side_effect=read_url):
            destination = Path(directory) / "talk.ts"
            result = yixi_download._download_hls(
                "https://alicdn.yixi.tv/master.m3u8",
                destination,
                timeout=5.0,
                max_bytes=10_000,
            )

            self.assertEqual(result.read_bytes(), b"Gsegment-oneGsegment-two")

    def test_rejects_encrypted_hls(self) -> None:
        manifest = b"""#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="key.bin"
#EXTINF:5,
seg-1.ts
#EXT-X-ENDLIST
"""
        with mock.patch.object(yixi_download, "_validate_media_url"), mock.patch.object(
            yixi_download, "_read_url_bytes", return_value=manifest
        ):
            with self.assertRaisesRegex(yixi_download.DownloadError, "加密密钥"):
                yixi_download._select_hls_playlist(
                    "https://alicdn.yixi.tv/media.m3u8",
                    timeout=5.0,
                )

    def test_cli_reports_level_clearly(self) -> None:
        result = yixi_download.DownloadResult(
            Path("C:/downloads/talk.md"),
            "Level 2",
            "public-transcript",
            "测试演讲",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(yixi_download, "download_resource", return_value=result), redirect_stdout(
            stdout
        ), redirect_stderr(stderr):
            code = yixi_download.main(
                [
                    "download",
                    "https://www.yixi.tv/speech/detail?id=768",
                    "-o",
                    "C:/downloads",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("Level 2 (公开完整文稿，非原视频)", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
