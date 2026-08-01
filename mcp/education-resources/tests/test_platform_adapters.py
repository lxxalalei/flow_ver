"""Tests for platform-specific search adapters and the multi-platform dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from education_resource_mcp.adapters.base import make_resource, adapter_error
from education_resource_mcp.adapters.wbi import wbi_sign, _get_mixin_key
from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
from education_resource_mcp.adapters.zhihu import ZhihuSearchAdapter
from education_resource_mcp.adapters.smartedu import SmartEduSearchAdapter
from education_resource_mcp.config import Settings
from education_resource_mcp.search import (
    MultiPlatformSearchProvider,
    GenericWebSearchProvider,
    default_search_provider,
)
from education_resource_mcp.sessions import SessionStore


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
    )


def _mock_response(body: dict | str, status: int = 200, content_type: str = "application/json"):
    """Build a context-manager mock matching urlopen_with_fallback's interface."""
    resp = MagicMock()
    if isinstance(body, str):
        resp.read.return_value = body.encode("utf-8")
    else:
        resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.status = status
    resp.headers = {"Content-Type": content_type}
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# WBI signing
# ---------------------------------------------------------------------------

class WbiSignTests(unittest.TestCase):
    # Real WBI keys are 32 chars each; combined length must be >= 64
    # because WBI_KEY_TABLE indices go up to 63.
    _IMG_KEY = "7cd084941338484aae1ad9425b84077c"
    _SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

    def test_sign_adds_wts_and_wrid(self) -> None:
        params = {"keyword": "test", "page": 1}
        signed = wbi_sign(params, self._IMG_KEY, self._SUB_KEY)
        self.assertIn("wts", signed)
        self.assertIn("w_rid", signed)
        self.assertEqual(len(signed["w_rid"]), 32)  # MD5 hex

    def test_mixin_key_is_32_chars(self) -> None:
        key = _get_mixin_key(self._IMG_KEY + self._SUB_KEY)
        self.assertEqual(len(key), 32)

    def test_sign_is_deterministic_for_same_inputs(self) -> None:
        import time
        t = int(time.time())
        with patch("education_resource_mcp.adapters.wbi.time.time", return_value=t):
            s1 = wbi_sign({"q": "x"}, self._IMG_KEY, self._SUB_KEY)
            s2 = wbi_sign({"q": "x"}, self._IMG_KEY, self._SUB_KEY)
        self.assertEqual(s1["w_rid"], s2["w_rid"])


# ---------------------------------------------------------------------------
# make_resource / adapter_error helpers
# ---------------------------------------------------------------------------

class MakeResourceTests(unittest.TestCase):
    def test_minimal_fields(self) -> None:
        r = make_resource(platform="test", title="T", source_url="https://example.com")
        self.assertEqual(r["platform"], "test")
        self.assertEqual(r["title"], "T")
        self.assertEqual(r["resource_type"], "其他")
        self.assertIsNone(r["summary"])
        self.assertEqual(r["metadata"]["platform_signals"], {})

    def test_full_fields(self) -> None:
        r = make_resource(
            platform="bilibili", title="T", source_url="https://example.com",
            resource_type="视频", summary="desc", author="UP主",
            published_at="2024-01-01", language="zh", download_feasibility="中",
            platform_signals={"views": 100},
        )
        self.assertEqual(r["metadata"]["author"], "UP主")
        self.assertEqual(r["metadata"]["platform_signals"]["views"], 100)


# ---------------------------------------------------------------------------
# Bilibili adapter
# ---------------------------------------------------------------------------

class BilibiliAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> BilibiliSearchAdapter:
        return BilibiliSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_missing_session_returns_auth_required(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            results, error = adapter.search("test", 10)
        self.assertEqual(results, [])
        self.assertEqual(error["code"], "AUTH_REQUIRED")
        self.assertFalse(error["retryable"])

    def test_search_returns_normalized_results(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("bilibili", {"cookies": [{"name": "SESSDATA", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            nav_response = {
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                    }
                },
            }
            search_response = {
                "code": 0,
                "data": {
                    "result": [
                        {
                            "bvid": "BV1xx411c7mD",
                            "title": "<em class=\"keyword\">英语</em>启蒙动画",
                            "description": "幼儿英语启蒙",
                            "author": "UP主",
                            "play": 12345,
                            "video_review": 100,
                            "pubdate": 1700000000,
                        }
                    ]
                },
            }

            responses = [_mock_response(nav_response), _mock_response(search_response)]
            with patch(
                "education_resource_mcp.adapters.bilibili.urlopen_with_fallback",
                side_effect=responses,
            ):
                results, error = adapter.search("英语启蒙", 10)

        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "bilibili")
        self.assertEqual(r["title"], "英语启蒙动画")  # HTML stripped
        self.assertEqual(r["source_url"], "https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(r["resource_type"], "视频")
        self.assertEqual(r["metadata"]["platform_signals"]["views"], 12345)

    def test_api_auth_error_returns_auth_required(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("bilibili", {"cookies": [{"name": "SESSDATA", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            nav_response = {
                "code": 0,
                "data": {"wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }},
            }
            search_response = {"code": -101, "message": "账号未登录"}

            responses = [_mock_response(nav_response), _mock_response(search_response)]
            with patch(
                "education_resource_mcp.adapters.bilibili.urlopen_with_fallback",
                side_effect=responses,
            ):
                results, error = adapter.search("test", 10)

        self.assertEqual(results, [])
        self.assertEqual(error["code"], "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# Zhihu adapter
# ---------------------------------------------------------------------------

class ZhihuAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> ZhihuSearchAdapter:
        return ZhihuSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_no_session_degrades_to_html_then_engine(self) -> None:
        """Without session, the adapter should not crash — it tries HTML/engine fallback."""
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            # All HTTP returns empty.
            with patch(
                "education_resource_mcp.adapters.zhihu.urlopen_with_fallback",
                return_value=_mock_response("<html></html>", content_type="text/html"),
            ):
                results, error = adapter.search("test", 5)
        self.assertEqual(results, [])
        # Should report either AUTH_REQUIRED or PARTIAL_FAILURE.
        self.assertIn(error["code"], ("AUTH_REQUIRED", "PARTIAL_FAILURE"))

    def test_api_search_with_valid_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("zhihu", {"cookies": [
                {"name": "z_c0", "value": "session_token"},
                {"name": "d_c0", "value": "device_token"},
            ]})
            adapter = self._adapter(data_dir)

            api_response = {
                "data": [
                    {
                        "object": {
                            "type": "answer",
                            "id": "12345",
                            "title": "如何教孩子<em>学英语</em>",
                            "excerpt": "英语启蒙方法",
                            "author": {"name": "教育专家"},
                            "question": {"id": "67890"},
                        }
                    }
                ],
                "paging": {"is_end": True},
            }

            with patch(
                "education_resource_mcp.adapters.zhihu.urlopen_with_fallback",
                return_value=_mock_response(api_response),
            ):
                results, error = adapter.search("学英语", 10)

        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "zhihu")
        self.assertEqual(r["title"], "如何教孩子学英语")
        self.assertEqual(r["resource_type"], "问答")
        self.assertIn("/question/67890/answer/12345", r["source_url"])


# ---------------------------------------------------------------------------
# SmartEdu adapter
# ---------------------------------------------------------------------------

class SmartEduAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> SmartEduSearchAdapter:
        return SmartEduSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_search_returns_normalized_results(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("smartedu", {"tokens": {"accessToken": "test_token_abc"}})
            adapter = self._adapter(data_dir)

            search_response = {
                "data": {
                    "list": [
                        {
                            "id": "res-001",
                            "title": "三年级数学上册",
                            "description": "人教版三年级数学",
                            "tab_code": "qualityCourse",
                            "content_type": "resource",
                            "tags": [
                                {"dimension_id": "zxxnj", "title": "三年级"},
                                {"dimension_id": "zxxbb", "title": "人教版"},
                            ],
                        }
                    ]
                }
            }

            with patch(
                "education_resource_mcp.adapters.smartedu.urlopen_with_fallback",
                return_value=_mock_response(search_response),
            ):
                results, error = adapter.search("三年级数学", 10)

        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "smartedu")
        self.assertEqual(r["title"], "三年级数学上册")
        self.assertTrue(r["source_url"].startswith("https://basic.smartedu.cn/"))

    def test_all_endpoints_fail_returns_partial_failure(self) -> None:
        from urllib.error import URLError
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("smartedu", {"tokens": {"accessToken": "token"}})
            adapter = self._adapter(data_dir)

            with patch(
                "education_resource_mcp.adapters.smartedu.urlopen_with_fallback",
                side_effect=URLError("connection refused"),
            ):
                results, error = adapter.search("test", 10)

        self.assertEqual(results, [])
        self.assertEqual(error["code"], "PARTIAL_FAILURE")
        self.assertTrue(error["retryable"])


# ---------------------------------------------------------------------------
# MultiPlatformSearchProvider dispatcher
# ---------------------------------------------------------------------------

class MultiPlatformSearchProviderTests(unittest.TestCase):
    def test_dispatches_to_platform_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            generic = GenericWebSearchProvider(settings)
            provider = MultiPlatformSearchProvider(settings, store, generic)

            # Register a stub adapter.
            stub = MagicMock()
            stub.platform_id = "bilibili"
            stub.search.return_value = (
                [make_resource(platform="bilibili", title="T", source_url="https://bilibili.com/v/1")],
                None,
            )
            provider.register_adapter(stub)

            resources, errors = provider.search("test", 10, ["bilibili"])

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["platform"], "bilibili")
        self.assertEqual(errors, [])
        stub.search.assert_called_once_with("test", 10)

    def test_unknown_platform_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            generic = GenericWebSearchProvider(settings)
            provider = MultiPlatformSearchProvider(settings, store, generic)

            resources, errors = provider.search("test", 10, ["nonexistent"])

        self.assertEqual(resources, [])
        self.assertEqual(errors[0]["code"], "PLATFORM_UNAVAILABLE")

    def test_generic_path_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            generic = GenericWebSearchProvider(settings, engines=["duckduckgo"])
            provider = MultiPlatformSearchProvider(settings, store, generic)

            response = {
                "results": [
                    {"platform": "generic", "title": "网页", "source_url": "https://example.com/a", "type": "网页"},
                ],
                "errors": [],
            }
            with patch(
                "education_resource_mcp.search.generic_web.search",
                return_value=response,
            ):
                resources, errors = provider.search("test", 5, ["generic"])

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["platform"], "generic")

    def test_default_search_provider_returns_multi_when_session_store_given(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            provider = default_search_provider(settings, store)
        self.assertIsInstance(provider, MultiPlatformSearchProvider)

    def test_default_search_provider_returns_generic_without_session_store(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            provider = default_search_provider(settings)
        self.assertIsInstance(provider, GenericWebSearchProvider)


if __name__ == "__main__":
    unittest.main()
