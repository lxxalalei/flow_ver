"""Offline focused tests for the CCTV platform integration (0068)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from education_resource_mcp.adapters import cctv as cctv_adapter
from education_resource_mcp.adapters import cctv_download
from education_resource_mcp.adapters.cctv import CctvSearchAdapter
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
        def fake_page_text(url: str, *, timeout: float) -> str:
            return _series_html()

        def fake_resolve(url: str, *, timeout: float) -> dict:
            return {"guid": _GUID, "title": "第1集", "page_url": url}

        with mock.patch.object(cctv_adapter, "page_text", fake_page_text), \
                mock.patch.object(cctv_adapter, "resolve_episode", fake_resolve):
            target = {
                "platform": "cctv",
                "resource_type": "视频",
                "source_url": _SERIES_URL,
            }
            results = list(
                expand_resource(_FakeProvider({"cctv": _FakeCctvAdapter()}), target)
            )
        self.assertEqual(len(results), 3)
        self.assertTrue(
            all(item["resource_type"] == "视频" for item in results)
        )
        self.assertEqual(
            results[0]["metadata"]["platform_signals"]["guid"], _GUID
        )

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

    def test_column_list_requires_cctv_dl_exe(self) -> None:
        adapter = CctvSearchAdapter(None, _settings(Path(".")))
        missing = Path("Z:/definitely/missing/cctv-dl.exe")
        with mock.patch.object(cctv_download, "DEFAULT_CCTV_DL_EXE", missing), \
                mock.patch.dict(os.environ, {"CCTV_DL_EXE": ""}):
            with self.assertRaises(DomainError) as ctx:
                adapter.iter_column(_COLUMN_URL)
        self.assertEqual(ctx.exception.code, "PROVIDER_UNAVAILABLE")
        self.assertIn("CCTV_DL_EXE", ctx.exception.message)

    def test_iter_column_normalizes_events(self) -> None:
        adapter = CctvSearchAdapter(None, _settings(Path(".")))
        events = [
            {
                "event": "video",
                "guid": _GUID,
                "title": "第1期 典籍",
                "url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
                "time": "2021-02-12 12:00",
            },
            {"event": "status", "ignored": True},
        ]
        with mock.patch.object(
            cctv_download, "run_cctv_dl_list", lambda url, **kwargs: events
        ):
            results = adapter.iter_column(_COLUMN_URL)
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["metadata"]["platform_signals"]["guid"], _GUID
        )
        self.assertEqual(results[0]["metadata"]["platform_signals"]["publish_time"], "2021-02-12 12:00")


class CctvDownloaderTests(unittest.TestCase):
    def test_download_success(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))
        payload = b"x" * 128

        def fake_runner(cmd, *, timeout, cancel_event):
            output = Path(cmd[cmd.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "第1期.mp4").write_bytes(payload)
            stdout = json.dumps(
                {"event": "download_complete", "failed": 0, "total": 10}
            )
            return 0, stdout + "\n", ""

        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            exe_resolver=lambda: Path("C:/fake/cctv-dl.exe"),
            runner=fake_runner,
            health_checker=lambda path: 0,
        )
        resource = {
            "platform": "cctv",
            "title": "第1期",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {"platform_signals": {"guid": _GUID}},
        }
        result = downloader.download(resource, "job1", "direct", threading.Event())

        self.assertTrue(result.path.is_file())
        self.assertEqual(result.filename, "第1期.mp4")
        self.assertEqual(result.byte_size, len(payload))
        self.assertEqual(result.media_type, "video/mp4")
        self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(result.metadata["guid"], _GUID)

    def test_download_retries_after_health_failure(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))

        def fake_runner(cmd, *, timeout, cancel_event):
            output = Path(cmd[cmd.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "video.mp4").write_bytes(b"data")
            return 0, '{"event":"download_complete","failed":0,"total":5}\n', ""

        health_results = iter([500, 0])
        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            exe_resolver=lambda: Path("C:/fake/cctv-dl.exe"),
            runner=fake_runner,
            health_checker=lambda path: next(health_results),
        )
        resource = {
            "platform": "cctv",
            "title": "video",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {"platform_signals": {"guid": _GUID}},
        }
        result = downloader.download(resource, "job2", "direct", threading.Event())
        self.assertEqual(result.metadata["attempts"], 2)

    def test_download_reports_final_failure(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))
        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            exe_resolver=lambda: Path("C:/fake/cctv-dl.exe"),
            runner=lambda cmd, *, timeout, cancel_event: (1, "", "boom"),
            health_checker=lambda path: 0,
        )
        resource = {
            "platform": "cctv",
            "title": "video",
            "source_url": "https://tv.cctv.com/2021/02/12/VIDE001.shtml",
            "metadata": {"platform_signals": {"guid": _GUID}},
        }
        with self.assertRaises(DomainError) as ctx:
            downloader.download(resource, "job3", "direct", threading.Event())
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
        self.assertFalse(ctx.exception.retryable)

    def test_download_requires_resolvable_guid(self) -> None:
        tmp = Path(self.enterContext(_tmp_dir()))
        downloader = CctvVideoDownloader(
            None,
            _settings(tmp),
            exe_resolver=lambda: Path("C:/fake/cctv-dl.exe"),
        )
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
        self.assertEqual(
            result.resolved_resource["resource_type"], "column"
        )
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
        self.assertEqual(
            result.resolved_resource["resource_type"], "series"
        )

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
        self.assertEqual(
            resolved["metadata"]["platform_signals"]["guid"], _GUID
        )

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
        self.assertEqual(
            result.failures[0]["code"], "CONTENT_VALIDATION_FAILED"
        )


def _tmp_dir():
    import tempfile

    return tempfile.TemporaryDirectory()


if __name__ == "__main__":
    unittest.main()
