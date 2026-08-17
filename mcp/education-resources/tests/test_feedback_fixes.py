"""Focused regression tests for real OpenClaw integration feedback."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
from education_resource_mcp.archive import archive_downloaded_files
from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.search import (
    GenericWebSearchProvider,
    MultiPlatformSearchProvider,
)
from education_resource_mcp.service import ResourceService


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        jobs_dir=root / "jobs",
        library_dir=root / "library",
        max_workers=2,
    )


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def search(self, search_tasks, limit):
        self.calls.append(search_tasks)
        return [], []


class PlatformIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.provider = _RecordingProvider()
        self.service = ResourceService(
            settings=_settings(self.root), search_provider=self.provider
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_underscore_platform_normalizes_to_hyphen(self) -> None:
        self.service.search([{"platform": "annas_archive", "queries": ["公益图书馆"]}])
        tasks = self.provider.calls[-1]
        self.assertEqual("annas-archive", tasks[0]["platform"])

    def test_unknown_platform_error_lists_available_ids(self) -> None:
        from education_resource_mcp.session_bridge import create_session_store

        settings = _settings(self.root)
        multi = MultiPlatformSearchProvider(
            settings, create_session_store(settings), GenericWebSearchProvider(settings)
        )
        _, runs = multi.search(
            [{"platform": "annas-archive-typo", "queries": [{"query": "x"}]}], 5
        )
        message = str(runs[0]["query_runs"][0]["error"]["message"])
        self.assertIn("annas-archive", message)
        self.assertIn("bilibili", message)


class BilibiliSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.settings = _settings(self.root)
        from education_resource_mcp.adapters import bilibili as bilibili_module

        self._module = bilibili_module

        class _Store:
            def __init__(self) -> None:
                self.session: dict | None = {"cookies": []}

            def get_session_data(self, platform: str):
                return self.session

        self.store = _Store()
        self.adapter = BilibiliSearchAdapter(self.store, self.settings)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _patch_cookie(self) -> None:
        patcher = mock.patch.object(
            self._module.SessionStore,
            "_cookie_header",
            staticmethod(lambda session_data: "SESSDATA=dead"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dead_session_reports_auth_required(self) -> None:
        self._patch_cookie()
        with mock.patch.object(
            self.adapter,
            "_request_json",
            return_value={
                "code": 0,
                "data": {"isLogin": False, "wbi_img": {
                    "img_url": "https://x/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                    "sub_url": "https://x/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
                }},
            },
        ):
            resources, error = self.adapter.search("纪录片", 5)
        self.assertEqual([], resources)
        self.assertEqual("AUTH_REQUIRED", error["code"])

    def test_guest_mode_skips_probe(self) -> None:
        self.store.session = None
        with mock.patch.object(
            self.adapter,
            "_request_json",
            return_value={
                "code": 0,
                "data": {
                    "isLogin": False,
                    "wbi_img": {
                        "img_url": "https://x/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                        "sub_url": "https://x/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
                    },
                    "result": [],
                },
            },
        ):
            resources, error = self.adapter.search("纪录片", 5)
        self.assertEqual([], resources)
        self.assertIsNone(error)

    def test_creator_listing_filters_foreign_works(self) -> None:
        self._patch_cookie()
        nav = {
            "code": 0,
            "data": {"isLogin": True, "wbi_img": {
                "img_url": "https://x/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                "sub_url": "https://x/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png",
            }},
        }
        creator_page = {
            "code": 0,
            "data": {"list": {"vlist": [
                {"bvid": "BV1own", "title": "本人作品", "author": "我",
                 "mid": 111, "created": 1700000000, "length": "3:00"},
                {"bvid": "BV1foreign", "title": "互投的别人作品", "author": "别人",
                 "mid": 222, "created": 1700000001, "length": "4:00"},
            ]}},
        }

        def fake_request(url, referer=None, cookie=""):
            if "nav" in url:
                return nav
            return creator_page

        with mock.patch.object(
            self.adapter, "_request_json", side_effect=fake_request
        ):
            resources, error = self.adapter.search_creator("111", 10)
        self.assertIsNone(error)
        self.assertEqual(1, len(resources))
        self.assertEqual("本人作品", resources[0]["title"])
        self.assertEqual("111", resources[0]["metadata"]["creator_mid"])


class ProcessLocalResourceHandleTests(unittest.TestCase):
    """Search handles are ephemeral; durable state starts only at a real Job."""

    def test_handles_do_not_reload_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            class _OneHit:
                def search(self, tasks, limit):
                    return [{
                        "platform": "bilibili",
                        "title": "候选",
                        "source_url": "https://www.bilibili.com/video/BV1x",
                        "resource_type": "video",
                        "metadata": {},
                    }], []

            first = ResourceService(
                settings=_settings(root), search_provider=_OneHit()
            )
            result = first.search([{"platform": "bilibili", "queries": ["候选"]}])
            resource_id = result["candidates"][0]["resource_id"]
            first.shutdown()

            second = ResourceService(settings=_settings(root))
            try:
                with self.assertRaises(DomainError) as ctx:
                    second._get_resource(resource_id)
                self.assertEqual("RESOURCE_NOT_FOUND", ctx.exception.code)
                self.assertIn("resource_import_url", ctx.exception.message)
            finally:
                second.shutdown()
            self.assertFalse((root / "resources.jsonl").exists())


class ArchiveManifestTests(unittest.TestCase):
    def test_manifest_records_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            download_dir = root / "jobs" / ("job_" + "f" * 32)
            download_dir.mkdir(parents=True)
            media = download_dir / "report.pdf"
            media.write_bytes(b"%PDF-1.4 manifest")
            archived, failures = archive_downloaded_files(
                [{
                    "resource_id": "res_1",
                    "platform": "annas-archive",
                    "source_url": "https://annas.example/seeds/report",
                    "title": "某报告",
                    "author": "某人",
                    "filename": "report.pdf",
                    "path": str(media),
                    "media_type": "application/pdf",
                }],
                library_root=root / "library",
                domain_id="",
                topic="溯源测试",
            )
            self.assertEqual([], failures)
            self.assertEqual(1, len(archived))
            manifest = root / "library" / "manifest.jsonl"
            self.assertTrue(manifest.is_file())
            record = json.loads(manifest.read_text(encoding="utf-8").splitlines()[-1])
            (entry,) = record["files"]
            self.assertEqual("annas-archive", entry["platform"])
            self.assertEqual("https://annas.example/seeds/report", entry["source_url"])
            self.assertEqual("某人", entry["author"])


class QueryTuningTests(unittest.TestCase):
    def test_book_title_becomes_quoted_phrase(self) -> None:
        self.assertEqual(
            '"毛泽东选集" 人民出版社',
            GenericWebSearchProvider._tuned_query("《毛泽东选集》 人民出版社"),
        )

    def test_plain_query_untouched(self) -> None:
        self.assertEqual(
            "火山喷发 原理 动画",
            GenericWebSearchProvider._tuned_query("火山喷发 原理 动画"),
        )


if __name__ == "__main__":
    unittest.main()
