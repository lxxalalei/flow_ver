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

    def test_libgen_platform_id_is_preserved(self) -> None:
        self.service.search([{"platform": "libgen", "queries": ["公益图书馆"]}])
        tasks = self.provider.calls[-1]
        self.assertEqual("libgen", tasks[0]["platform"])

    def test_unknown_platform_error_lists_available_ids(self) -> None:
        from education_resource_mcp.sessions import SessionStore

        settings = _settings(self.root)
        multi = MultiPlatformSearchProvider(
            settings, SessionStore(settings.data_dir), GenericWebSearchProvider(settings)
        )
        _, runs = multi.search(
            [{"platform": "libgen-typo", "queries": [{"query": "x"}]}], 5
        )
        message = str(runs[0]["query_runs"][0]["error"]["message"])
        self.assertIn("libgen", message)
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
            resources = list(self.adapter.iter_creator("111"))
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
                    "platform": "libgen",
                    "source_url": "https://libgen.example/ads.php?md5=" + "a" * 32,
                    "title": "某报告",
                    "author": "某人",
                    "summary": "报告摘要",
                    "published_at": "2026-08-01T08:00:00+08:00",
                    "language": "zh",
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
            manifest = root / "library" / ".manifest.jsonl"
            self.assertTrue(manifest.is_file())
            entry = json.loads(manifest.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual("溯源测试", entry["topic"])
            self.assertEqual("libgen", entry["platform"])
            self.assertEqual(
                "https://libgen.example/ads.php?md5=" + "a" * 32,
                entry["source_url"],
            )
            self.assertEqual("某人", entry["author"])
            self.assertEqual("报告摘要", entry["summary"])
            self.assertEqual("2026-08-01T08:00:00+08:00", entry["published_at"])
            self.assertEqual("zh", entry["language"])
            self.assertEqual(archived[0]["path"], entry["path"])
            stat = manifest.stat()
            if hasattr(stat, "st_file_attributes"):
                self.assertTrue(stat.st_file_attributes & 0x2)

    def test_manifest_migrates_legacy_visible_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            library = root / "library"
            library.mkdir()
            legacy = library / "manifest.jsonl"
            legacy.write_text(
                '{"archived_at": "2026-01-01T00:00:00+00:00", "files": []}\n',
                encoding="utf-8",
            )
            download_dir = root / "jobs" / ("job_" + "e" * 32)
            download_dir.mkdir(parents=True)
            media = download_dir / "old.mp4"
            media.write_bytes(b"video")
            archive_downloaded_files(
                [{
                    "resource_id": "res_2",
                    "platform": "douyin",
                    "source_url": "https://www.douyin.com/video/1",
                    "title": "旧记录",
                    "author": "作者",
                    "filename": "old.mp4",
                    "path": str(media),
                    "media_type": "video/mp4",
                }],
                library_root=library,
                domain_id="",
                topic="迁移",
            )
            self.assertFalse(legacy.is_file())
            manifest = library / ".manifest.jsonl"
            lines = manifest.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            self.assertEqual("2026-01-01T00:00:00+00:00", json.loads(lines[0])["archived_at"])
            self.assertEqual("res_2", json.loads(lines[1])["resource_id"])
            self.assertEqual("迁移", json.loads(lines[1])["topic"])
            # schema 统一：缺失的描述字段留空而不是消失
            self.assertEqual("", json.loads(lines[1])["summary"])
            self.assertEqual("", json.loads(lines[1])["published_at"])
            self.assertEqual("", json.loads(lines[1])["language"])


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
