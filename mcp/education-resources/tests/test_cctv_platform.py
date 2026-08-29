"""Offline focused tests for the CCTV platform integration."""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from education_resource_mcp.adapters import cctv as cctv_adapter
from education_resource_mcp.adapters import cctv_download
from education_resource_mcp.adapters.cctv_download import CctvVideoDownloader
from education_resource_mcp.adapters.expansion import expand_resource
from education_resource_mcp.adapters.inspect_cctv import CctvInspector
from education_resource_mcp.adapters.resource_urls import identify_resource_url
from education_resource_mcp.errors import DomainError


_GUID = "0123456789abcdef0123456789abcdef"
_SERIES_URL = "https://tv.cctv.com/2012/12/10/VIDA1360523007111240.shtml"
_COLUMN_URL = "https://tv.cctv.com/lm/djldzg/index.shtml"


def _series_html() -> str:
    links = "".join(
        f'<a href="https://tv.cctv.com/2012/12/10/VIDE000000{i}.shtml">第{i}集</a>'
        for i in (1, 2, 3)
    )
    return (
        "<html><title>地球脉动 第一季</title>"
        f'<a href="{_SERIES_URL}">自己</a>{links}</html>'
    )


def _episode_html(title: str = "地球脉动 第一集") -> str:
    return (
        f"<html><title>{title}</title><script>var guid='{_GUID}';</script></html>"
    )


class _FakeProvider:
    def __init__(self, adapters: dict[str, object]) -> None:
        self._adapters = adapters


class _FakeCctvAdapter:
    platform_id = "cctv"
    timeout = 5.0

    def __init__(self) -> None:
        self.column_url: str | None = None

    def iter_column(self, column_url: str, *, cancel_event=None):
        self.column_url = column_url
        return [
            {
                "platform": "cctv",
                "title": "典籍里的中国 第一期",
                "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
                "resource_type": "视频",
                "metadata": {"platform_signals": {"guid": _GUID}},
            },
            {
                "platform": "cctv",
                "title": "典籍里的中国 第二期",
                "source_url": "https://tv.cctv.com/2021/02/19/VIDE002.shtml",
                "resource_type": "视频",
                "metadata": {"platform_signals": {"guid": "f" * 32}},
            },
        ]


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        search_timeout_seconds=5,
        download_timeout_seconds=10,
        jobs_dir=tmp_path / "jobs",
    )


class CctvUrlIdentificationTests(unittest.TestCase):
    def test_column_episode_and_other_shapes(self) -> None:
        column = identify_resource_url(_COLUMN_URL)
        self.assertEqual(column["platform"], "cctv")
        self.assertEqual(column["resource_type"], "column")

        episode = identify_resource_url(_SERIES_URL)
        self.assertEqual(episode["platform"], "cctv")
        self.assertEqual(episode["resource_type"], "视频")

        other = identify_resource_url("https://tv.cctv.com/special/djldzg/")
        self.assertEqual(other["platform"], "cctv")
        self.assertEqual(other["resource_type"], "网页")

        generic = identify_resource_url("https://example.com/page")
        self.assertEqual(generic["platform"], "generic")


class CctvColumnNativeApiTests(unittest.TestCase):
    def test_column_id_from_page_finds_topic_id(self) -> None:
        html = '<script>var topicID = "TOPC1234567890";</script>'
        with mock.patch.object(
            cctv_adapter, "page_text", lambda url, *, timeout: html
        ):
            column_id = cctv_adapter.column_id_from_page(_COLUMN_URL, timeout=5)
        self.assertEqual(column_id, "TOPC1234567890")

    def test_column_id_falls_back_to_videoset_page(self) -> None:
        def fake_page(url: str, *, timeout: float) -> str:
            if "videoset" in url:
                return '<script>var lmtopId = "TOPC999999";</script>'
            return "<html>no id here</html>"

        with mock.patch.object(cctv_adapter, "page_text", fake_page):
            column_id = cctv_adapter.column_id_from_page(_COLUMN_URL, timeout=5)
        self.assertEqual(column_id, "TOPC999999")

    def test_column_id_missing_raises(self) -> None:
        with mock.patch.object(
            cctv_adapter,
            "page_text",
            lambda url, *, timeout: "<html>nothing</html>",
        ):
            with self.assertRaises(DomainError) as ctx:
                cctv_adapter.column_id_from_page(_COLUMN_URL, timeout=5)
        self.assertEqual(ctx.exception.code, "CONTENT_VALIDATION_FAILED")

    def test_iter_column_via_api_paginates_and_parses(self) -> None:
        page1 = {
            "data": [
                {
                    "guid": _GUID,
                    "title": "第一期",
                    "time": "2021-02-12 12:00",
                    "channel": "CCTV-1",
                    "brief": "简介",
                    "length": "45:00",
                }
            ],
            "pageCount": 2,
        }
        page2 = {"data": [], "pageCount": 2}
        responses = [page1, page2]

        def fake_open(request, timeout):
            payload = json.dumps(responses.pop(0)).encode("utf-8")
            return mock.MagicMock(
                __enter__=lambda self: self,
                __exit__=lambda *a: None,
                read=lambda: payload,
            )

        with mock.patch.object(
            cctv_adapter, "column_id_from_page", lambda url, *, timeout: "TOPC1"
        ), mock.patch.object(cctv_adapter, "urlopen_with_fallback", fake_open):
            results = cctv_adapter.iter_column_via_api(_COLUMN_URL, timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["platform_signals"]["guid"], _GUID)
        self.assertEqual(
            results[0]["metadata"]["platform_signals"]["publish_time"],
            "2021-02-12 12:00",
        )
        self.assertEqual(results[0]["resource_type"], "视频")

    def test_iter_column_via_api_stops_on_short_page(self) -> None:
        page1 = {
            "data": [{"guid": "a" * 32, "title": "only one"}],
            "pageCount": 9,
        }
        responses = [page1]

        def fake_open(request, timeout):
            payload = json.dumps(responses.pop(0)).encode("utf-8")
            return mock.MagicMock(
                __enter__=lambda self: self,
                __exit__=lambda *a: None,
                read=lambda: payload,
            )

        with mock.patch.object(
            cctv_adapter, "column_id_from_page", lambda url, *, timeout: "TOPC1"
        ), mock.patch.object(cctv_adapter, "urlopen_with_fallback", fake_open):
            results = cctv_adapter.iter_column_via_api(_COLUMN_URL, timeout=5)
        self.assertEqual(len(results), 1)


class CctvExpansionTests(unittest.TestCase):
    def test_column_expand_routes_to_adapter(self) -> None:
        fake = _FakeCctvAdapter()
        target = {
            "platform": "cctv",
            "resource_type": "column",
            "source_url": _COLUMN_URL,
        }
        results = list(expand_resource(_FakeProvider({"cctv": fake}), target))
        self.assertEqual(fake.column_url, _COLUMN_URL)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["platform"], "cctv")

    def test_series_page_expands_episodes(self) -> None:
        def fake_resolve(url: str, *, timeout: float) -> dict:
            return {"guid": _GUID, "title": "第1集", "page_url": url}

        with mock.patch.object(
            cctv_adapter, "page_text", lambda url, *, timeout: _series_html()
        ), mock.patch.object(cctv_adapter, "resolve_episode", fake_resolve):
            target = {
                "platform": "cctv",
                "resource_type": "视频",
                "source_url": _SERIES_URL,
            }
            results = list(
                expand_resource(_FakeProvider({"cctv": _FakeCctvAdapter()}), target)
            )
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item["resource_type"] == "视频" for item in results))
        self.assertEqual(results[0]["metadata"]["platform_signals"]["guid"], _GUID)

    def test_single_episode_is_leaf(self) -> None:
        with mock.patch.object(
            cctv_adapter, "page_text", lambda url, *, timeout: _episode_html()
        ):
            target = {
                "platform": "cctv",
                "resource_type": "视频",
                "source_url": "https://tv.cctv.com/2012/12/10/VIDE999.shtml",
            }
            with self.assertRaises(DomainError) as ctx:
                list(
                    expand_resource(
                        _FakeProvider({"cctv": _FakeCctvAdapter()}), target
                    )
                )
        self.assertEqual(ctx.exception.code, "FEATURE_NOT_SUPPORTED")


class CctvDownloaderTests(unittest.TestCase):
    """CCTV delivery is native-only after highest-quality selection."""

    def test_native_plain_stream_success(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))

        def fake_stream(url, title, job_dir, *, timeout, cancel_event):
            mp4 = job_dir / f"{title}.mp4"
            mp4.write_bytes(b"stream-data")
            return mp4

        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            video_info_func=lambda guid, *, timeout: {
                "hls_url": "https://cdn.example/v.m3u8"
            },
            health_checker=lambda path: 0,
        )
        resource = {
            "platform": "cctv",
            "title": "新视频",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {"platform_signals": {"guid": _GUID}},
        }
        with mock.patch.object(cctv_download, "download_stream_native", fake_stream):
            result = downloader.download(resource, "job8", "direct", threading.Event())
        self.assertEqual(result.metadata["route"], "native")
        self.assertEqual(result.metadata["stream_type"], "clear")
        self.assertEqual(result.filename, "新视频.mp4")

    def test_native_h5e_success(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))

        def fake_h5e(resource, guid, title, job_dir, *, timeout, cancel_event, h5e_url=None):
            mp4 = job_dir / f"{title}.mp4"
            mp4.write_bytes(b"decrypted-data")
            return mp4

        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            video_info_func=lambda guid, *, timeout: {
                "h5e_url": "https://dh5ws01.v.cntv.cn/asp/h5e/hls/x/y/abc/2000.m3u8"
            },
            health_checker=lambda path: 0,
        )
        resource = {
            "platform": "cctv",
            "title": "老视频",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {"platform_signals": {"guid": _GUID}},
        }
        with mock.patch.object(cctv_download, "download_h5e_native", fake_h5e):
            result = downloader.download(resource, "job9", "direct", threading.Event())
        self.assertEqual(result.metadata["route"], "native")
        self.assertEqual(result.metadata["stream_type"], "h5e")

    def test_native_h5e_failure_is_final(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))
        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            video_info_func=lambda guid, *, timeout: {
                "h5e_url": "https://dh5ws01.v.cntv.cn/asp/h5e/hls/x/y/abc/2000.m3u8"
            },
            health_checker=lambda path: 0,
        )
        resource = {
            "platform": "cctv",
            "title": "老视频",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {"platform_signals": {"guid": _GUID}},
        }
        with mock.patch.object(
            cctv_download,
            "download_h5e_native",
            side_effect=DomainError("DOWNLOAD_FAILED", "native 解密失败"),
        ):
            with self.assertRaises(DomainError) as ctx:
                downloader.download(resource, "job10", "direct", threading.Event())
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
        self.assertIn("native 解密失败", ctx.exception.message)
        self.assertIn("不自动改下更低画质", ctx.exception.message)

    def test_download_requires_resolvable_guid(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))
        downloader = CctvVideoDownloader(None, _settings(tmp))
        resource = {
            "platform": "cctv",
            "title": "video",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {},
        }
        with mock.patch.object(cctv_adapter, "resolve_episode", lambda url, **kw: None):
            with self.assertRaises(DomainError) as ctx:
                downloader.download(resource, "job4", "direct", threading.Event())
        self.assertEqual(ctx.exception.code, "CONTENT_VALIDATION_FAILED")


def _tea_encrypt_block(data: bytearray, pos: int, key: bytes) -> None:
    """Test-only TEA-16 encrypt matching the calibrated classic implementation."""

    import struct as _struct

    mask32 = 0xFFFFFFFF
    v0, v1 = _struct.unpack_from("<II", data, pos)
    k0, k1, k2, k3 = _struct.unpack_from("<IIII", key, 0)
    delta = 0x9E3779B9
    total = 0
    for _ in range(16):
        total = (total + delta) & mask32
        v0 = (
            v0
            + ((((v1 << 4) & mask32) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))
        ) & mask32
        v1 = (
            v1
            + ((((v0 << 4) & mask32) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))
        ) & mask32
    _struct.pack_into("<II", data, pos, v0, v1)


def _classic_encrypted_ts() -> tuple[bytes, bytes]:
    """Build a plaintext 2-packet TS with one classic NAL and its encrypted form."""

    key = bytes(range(16))

    def build(fill: int) -> bytearray:
        nal = bytearray(200)
        nal[0] = 0x65
        nal[1:16] = bytes([fill]) * 15
        nal[16:32] = key
        nal[32:] = bytes([fill]) * 168
        return nal

    def has_fake_start(nal: bytes) -> bool:
        return b"\x00\x00\x01" in nal or b"\x00\x00\x00\x01" in nal

    nal = build(0x55)
    for _ in range(50):
        candidate = bytearray(nal)
        for j in range(0, 200, 80):
            if 32 + j + 80 <= len(candidate):
                _tea_encrypt_block(candidate, 32 + j, key)
        if not has_fake_start(bytes(candidate)):
            nal = candidate
            break
    else:
        raise AssertionError("无法构造不含假 start code 的加密 NAL")

    def packet(payload: bytes, pusi: bool, cc: int) -> bytes:
        pkt = bytearray(188)
        pkt[0] = 0x47
        pkt[1] = 0x41 if pusi else 0x01
        pkt[2] = 0x00
        pkt[3] = 0x10 | (cc & 0x0F)
        pkt[4 : 4 + len(payload)] = payload
        return bytes(pkt)

    pes_header = b"\x00\x00\x01\xe0\x00\x00\x80\x80\x00"
    start_code = b"\x00\x00\x01"
    trailer = b"\x00\x00\x01\x09" + bytes([0x55]) * 152
    plain_nal = build(0x55)
    body = pes_header + start_code + bytes(plain_nal) + trailer
    assert len(body) == 368
    plain = packet(body[:184], True, 0) + packet(body[184:], False, 1)
    enc_body = pes_header + start_code + bytes(nal) + trailer
    assert len(enc_body) == 368
    encrypted = packet(enc_body[:184], True, 0) + packet(enc_body[184:], False, 1)
    return plain, encrypted


class CctvH5eDecryptTests(unittest.TestCase):
    def test_classic_mode_round_trip(self) -> None:
        from education_resource_mcp.adapters.cctv_h5e import decrypt_ts

        plain, encrypted = _classic_encrypted_ts()
        out, nal_count = decrypt_ts(encrypted)
        self.assertEqual(nal_count, 2)
        self.assertEqual(out, plain)

    def test_plain_ts_passthrough(self) -> None:
        from education_resource_mcp.adapters.cctv_h5e import decrypt_ts

        ts = b"\x47" + bytes(187)
        out, nal_count = decrypt_ts(ts)
        self.assertEqual(nal_count, 0)
        self.assertEqual(out, ts)


class CctvInspectorTests(unittest.TestCase):
    def test_column_is_container_guidance(self) -> None:
        inspector = CctvInspector(timeout_seconds=5)
        result = inspector.inspect(
            {
                "platform": "cctv",
                "resource_type": "column",
                "source_url": _COLUMN_URL,
                "title": "典籍里的中国",
            }
        )
        self.assertEqual(result.resolution_status, "partial")
        self.assertEqual(result.resolved_resource["resource_type"], "column")
        self.assertEqual(result.failures[0]["code"], "FEATURE_NOT_SUPPORTED")

    def test_series_page_is_container_guidance(self) -> None:
        inspector = CctvInspector(timeout_seconds=5)
        with mock.patch.object(
            cctv_adapter, "page_text", lambda url, *, timeout: _series_html()
        ):
            result = inspector.inspect(
                {
                    "platform": "cctv",
                    "resource_type": "视频",
                    "source_url": _SERIES_URL,
                    "title": "地球脉动",
                }
            )
        self.assertEqual(result.resolution_status, "partial")
        self.assertEqual(result.resolved_resource["resource_type"], "series")

    def test_episode_resolves_primary_video(self) -> None:
        inspector = CctvInspector(timeout_seconds=5)

        def fake_info(guid: str, *, timeout: float) -> dict:
            return {
                "title": "地球脉动 第一集",
                "status": "1",
                "is_protected": "",
                "is_invalid_copyright": "",
                "hls_url": "https://hls.example/master.m3u8",
                "h5e_url": "",
                "enc_url": "",
                "column": "地球脉动",
                "image_url": "",
            }

        with mock.patch.object(
            cctv_adapter, "page_text", lambda url, *, timeout: _episode_html()
        ), mock.patch.object(cctv_adapter, "video_info", fake_info):
            result = inspector.inspect(
                {
                    "platform": "cctv",
                    "resource_type": "视频",
                    "source_url": "https://tv.cctv.com/2012/12/10/VIDE999.shtml",
                    "title": "候选",
                }
            )
        self.assertEqual(result.resolution_status, "resolved")
        resolved = result.resolved_resource
        self.assertEqual(resolved["resource_type"], "video")
        self.assertEqual(resolved["availability"]["status"], "available")
        representation = resolved["representations"][0]
        self.assertTrue(representation["materializable"])
        self.assertEqual(representation["container"], "mp4")
        self.assertEqual(resolved["metadata"]["platform_signals"]["guid"], _GUID)

    def test_episode_without_streams_is_unavailable(self) -> None:
        inspector = CctvInspector(timeout_seconds=5)

        def empty_info(guid: str, *, timeout: float) -> dict:
            return {
                "title": "老视频",
                "status": "",
                "is_protected": "",
                "is_invalid_copyright": "",
                "hls_url": "",
                "h5e_url": "",
                "enc_url": "",
                "column": "",
                "image_url": "",
            }

        with mock.patch.object(
            cctv_adapter, "page_text", lambda url, *, timeout: _episode_html()
        ), mock.patch.object(cctv_adapter, "video_info", empty_info):
            result = inspector.inspect(
                {
                    "platform": "cctv",
                    "resource_type": "视频",
                    "source_url": "https://tv.cctv.com/2012/12/10/VIDE998.shtml",
                    "title": "候选",
                }
            )
        resolved = result.resolved_resource
        self.assertEqual(resolved["availability"]["status"], "unavailable")
        self.assertFalse(resolved["representations"][0]["materializable"])

    def test_non_cctv_host_rejected(self) -> None:
        inspector = CctvInspector(timeout_seconds=5)
        result = inspector.inspect(
            {
                "platform": "cctv",
                "resource_type": "视频",
                "source_url": "https://example.com/video",
                "title": "候选",
            }
        )
        self.assertEqual(result.failures[0]["code"], "CONTENT_VALIDATION_FAILED")


def _tmp_dir():
    import tempfile

    return tempfile.TemporaryDirectory()


if __name__ == "__main__":
    unittest.main()
