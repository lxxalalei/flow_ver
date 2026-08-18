"""Focused tests for real platform search behavior."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from education_resource_mcp.adapters.base import make_resource
from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
from education_resource_mcp.adapters.douyin import DouyinSearchAdapter
from education_resource_mcp.adapters.smartedu import SmartEduSearchAdapter
from education_resource_mcp.config import Settings
from education_resource_mcp.search import MultiPlatformSearchProvider, default_search_provider
from education_resource_mcp.sessions import SessionStore


def _settings(data_dir: Path, *, max_workers: int = 8) -> Settings:
    return Settings(
        data_dir=data_dir,
        jobs_dir=data_dir / "jobs",
        max_workers=max_workers,
    )


def _response(body: dict):
    response = MagicMock()
    response.read.return_value = json.dumps(body).encode("utf-8")
    response.status = 200
    response.headers = {"Content-Type": "application/json"}
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


class PlatformSearchAdapterTests(unittest.TestCase):
    def test_bilibili_search_normalizes_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root)
            store.save("bilibili", {"cookies": [{"name": "SESSDATA", "value": "abc"}]})
            adapter = BilibiliSearchAdapter(store, _settings(root))
            nav = {
                "code": 0,
                "data": {
                    "isLogin": True,
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                    },
                },
            }
            search = {
                "code": 0,
                "data": {
                    "result": [
                        {
                            "bvid": "BV1xx411c7mD",
                            "title": '<em class="keyword">英语</em>启蒙动画',
                            "description": "幼儿英语启蒙",
                            "author": "UP主",
                            "play": 12345,
                            "video_review": 100,
                            "pubdate": 1700000000,
                        }
                    ]
                },
            }
            with patch(
                "education_resource_mcp.adapters.bilibili.urlopen_with_fallback",
                side_effect=[_response(nav), _response(search)],
            ):
                results, error = adapter.search("英语启蒙", 10)

        self.assertIsNone(error)
        self.assertEqual(1, len(results))
        self.assertEqual("bilibili", results[0]["platform"])
        self.assertEqual("英语启蒙动画", results[0]["title"])
        self.assertEqual(
            "https://www.bilibili.com/video/BV1xx411c7mD",
            results[0]["source_url"],
        )

    def test_douyin_requires_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = DouyinSearchAdapter(SessionStore(root), _settings(root))
            results, error = adapter.search("test", 10)
        self.assertEqual([], results)
        self.assertEqual("AUTH_REQUIRED", error["code"])

    def test_douyin_search_exposes_creator_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root)
            store.save("douyin", {"cookies": [{"name": "sessionid", "value": "abc"}]})
            adapter = DouyinSearchAdapter(store, _settings(root))
            response = {
                "status_code": 0,
                "has_more": False,
                "data": [
                    {
                        "aweme_info": {
                            "aweme_id": "7300000000000000001",
                            "desc": "幼儿英语启蒙动画",
                            "statistics": {"digg_count": 5200},
                            "author": {
                                "nickname": "教育小课堂",
                                "sec_uid": "MS4wLjABAAAAtest_sec_uid_0001",
                            },
                            "create_time": 1700000000,
                        }
                    }
                ],
            }
            with patch(
                "education_resource_mcp.adapters.douyin.urlopen_with_fallback",
                return_value=_response(response),
            ):
                results, error = adapter.search("英语启蒙", 10)

        self.assertIsNone(error)
        self.assertEqual(1, len(results))
        self.assertEqual(
            "MS4wLjABAAAAtest_sec_uid_0001",
            results[0]["metadata"]["creator_sec_uid"],
        )

    def test_auth_failure_is_returned_not_raised(self) -> None:
        denied = HTTPError(
            "https://basic.smartedu.cn/api", 401, "Unauthorized", {}, io.BytesIO(b"")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = SmartEduSearchAdapter(SessionStore(root), _settings(root))
            with patch(
                "education_resource_mcp.adapters.smartedu.urlopen_with_fallback",
                side_effect=denied,
            ):
                results, error = adapter.search("test", 10)
        self.assertEqual([], results)
        self.assertEqual("AUTH_REQUIRED", error["code"])
        self.assertFalse(error["retryable"])

    def test_unreachable_endpoints_report_partial_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = SmartEduSearchAdapter(SessionStore(root), _settings(root))
            with patch.object(SmartEduSearchAdapter, "_post_search", return_value=None):
                results, error = adapter.search("test", 10)
        self.assertEqual([], results)
        self.assertEqual("PARTIAL_FAILURE", error["code"])
        self.assertTrue(error["retryable"])

    def test_smartedu_wide_search_uses_same_extraction_limit(self) -> None:
        wide_item = {
            "id": "course-1",
            "title": "火山形成与喷发",
            "search_resource_type": "course",
            "resource_type": "elite_lesson",
            "content_type": "elite_lesson",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = SmartEduSearchAdapter(SessionStore(root), _settings(root))
            with patch.object(
                SmartEduSearchAdapter,
                "_post_search",
                side_effect=[{"data": []}, {"data": [wide_item]}],
            ):
                results, error = adapter.search("火山", 1)
        self.assertIsNone(error)
        self.assertEqual(1, len(results))
        self.assertEqual("火山形成与喷发", results[0]["title"])


class MultiPlatformSearchTests(unittest.TestCase):
    def test_only_requested_platform_runs(self) -> None:
        first = MagicMock()
        first.platform_id = "first"
        first.descriptor = MagicMock(platform_id="first")
        first.search.return_value = (
            [make_resource(platform="first", title="A", source_url="https://a.example")],
            None,
        )
        second = MagicMock()
        second.platform_id = "second"
        second.descriptor = MagicMock(platform_id="second")
        second.search.return_value = (
            [make_resource(platform="second", title="B", source_url="https://b.example")],
            None,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = MultiPlatformSearchProvider(
                _settings(root),
                SessionStore(root),
                MagicMock(),
            )
            provider.register_adapter(first)
            provider.register_adapter(second)
            resources, _ = provider.search(
                [{"platform": "first", "queries": [{"query": "q"}]}], 10
            )

        first.search.assert_called_once_with("q", 10)
        second.search.assert_not_called()
        self.assertEqual(["first"], [item["platform"] for item in resources])

    def test_different_platforms_can_run_concurrently(self) -> None:
        barrier = threading.Barrier(2)

        def adapter(platform: str):
            value = MagicMock()
            value.platform_id = platform
            value.descriptor = MagicMock(platform_id=platform)

            def search(query, limit):
                barrier.wait(timeout=2)
                return (
                    [make_resource(
                        platform=platform,
                        title=platform,
                        source_url=f"https://{platform}.example",
                    )],
                    None,
                )

            value.search.side_effect = search
            return value

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = MultiPlatformSearchProvider(
                _settings(root, max_workers=2),
                SessionStore(root),
                MagicMock(),
            )
            provider.register_adapter(adapter("a"))
            provider.register_adapter(adapter("b"))
            resources, _ = provider.search(
                [
                    {"platform": "a", "queries": [{"query": "q1"}]},
                    {"platform": "b", "queries": [{"query": "q2"}]},
                ],
                10,
            )
        self.assertEqual({"a", "b"}, {item["platform"] for item in resources})

    def test_unknown_platform_is_a_normal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = MultiPlatformSearchProvider(
                _settings(root),
                SessionStore(root),
                MagicMock(),
            )
            resources, runs = provider.search(
                [{"platform": "missing", "queries": [{"query": "q"}]}], 10
            )
        self.assertEqual([], resources)
        self.assertEqual(
            "PLATFORM_UNAVAILABLE",
            runs[0]["query_runs"][0]["error"]["code"],
        )

    def test_default_provider_registers_real_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = default_search_provider(_settings(root), SessionStore(root))
        registered = set(provider._adapters)
        for platform in (
            "bilibili", "douyin", "smartedu", "ximalaya", "zhihu",
            "annas-archive", "shuge", "yixi", "zjer",
        ):
            self.assertIn(platform, registered)
        self.assertNotIn("generic", registered)
        self.assertIsNotNone(provider.generic_provider)


if __name__ == "__main__":
    unittest.main()
