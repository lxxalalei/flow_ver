from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlparse

from education_resource_mcp.adapters import generic_web
from education_resource_mcp.config import Settings
from education_resource_mcp.search import GenericWebSearchProvider, SearXNGSearchProvider


def _task(platform: str, query: str) -> dict:
    return {"platform": platform, "queries": [{"query": query}]}


class GenericWebSearchProviderTests(unittest.TestCase):
    def test_uses_mcp_owned_adapter_and_normalizes_results(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            settings = Settings(
                data_dir=root,
                database_path=root / "database.sqlite",
                jobs_dir=root / "jobs",
                library_dir=root / "library",
            )
            provider = GenericWebSearchProvider(settings, engines=["duckduckgo"])
            response = {
                "results": [
                    {
                        "platform": "generic",
                        "title": "公开资源",
                        "source_url": "https://example.com/resource#fragment",
                        "type": "网页",
                        "description": "测试摘要",
                        "platform_signals": {"engine": "duckduckgo", "rank": 1},
                    }
                ],
                "errors": [],
            }
            with patch(
                "education_resource_mcp.search.generic_web.search",
                return_value=response,
            ) as search:
                resources, platform_runs = provider.search([_task("generic", "测试主题")], 5)

            search.assert_called_once_with("测试主题", ["duckduckgo"], 5, 20.0)
            self.assertEqual(len(resources), 1)
            self.assertEqual(resources[0]["source_url"], "https://example.com/resource")
            self.assertEqual(len(platform_runs), 1)
            self.assertEqual(platform_runs[0]["platform"], "generic")
            self.assertEqual(platform_runs[0]["status"], "succeeded")
            self.assertEqual(platform_runs[0]["query_runs"][0]["candidate_count"], 1)

    def test_default_cjk_route_preserves_query_and_prefers_cjk_engines(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            settings = Settings(
                data_dir=root,
                database_path=root / "database.sqlite",
                jobs_dir=root / "jobs",
                library_dir=root / "library",
            )
            provider = GenericWebSearchProvider(settings)
            query = "为什么会有四季 图文科普"
            with patch(
                "education_resource_mcp.search.generic_web.search",
                return_value={"results": [], "errors": []},
            ) as search:
                provider.search([_task("generic", query)], 8)

            search.assert_called_once_with(
                query,
                ["duckduckgo", "baidu", "bing"],
                8,
                20.0,
            )

    def test_default_non_cjk_route_keeps_bing(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            settings = Settings(
                data_dir=root,
                database_path=root / "database.sqlite",
                jobs_dir=root / "jobs",
                library_dir=root / "library",
            )
            provider = GenericWebSearchProvider(settings)
            with patch(
                "education_resource_mcp.search.generic_web.search",
                return_value={"results": [], "errors": []},
            ) as search:
                provider.search([_task("generic", "seasons explained")], 8)

            search.assert_called_once_with(
                "seasons explained",
                ["bing"],
                8,
                20.0,
            )

    def test_non_generic_platform_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            settings = Settings(
                data_dir=root,
                database_path=root / "database.sqlite",
                jobs_dir=root / "jobs",
                library_dir=root / "library",
            )
            provider = GenericWebSearchProvider(settings)
            resources, platform_runs = provider.search([_task("bilibili", "测试主题")], 5)

        self.assertEqual(resources, [])
        self.assertEqual(len(platform_runs), 1)
        self.assertEqual(platform_runs[0]["platform"], "bilibili")
        self.assertEqual(platform_runs[0]["status"], "skipped")


class GenericWebAdapterTests(unittest.TestCase):
    def test_bing_request_encodes_the_complete_cjk_query(self) -> None:
        query = "为什么会有四季 图文科普"
        rss = """<?xml version="1.0" encoding="utf-8"?>
        <rss><channel><item>
          <title>四季科普</title>
          <link>https://example.com/seasons</link>
          <description>地轴倾斜与公转</description>
        </item></channel></rss>"""
        with patch(
            "education_resource_mcp.adapters.generic_web._fetch",
            return_value=rss,
        ) as fetch:
            response = generic_web.search(query, ["bing"], 1, 20.0)

        requested_url = fetch.call_args.args[0]
        self.assertEqual(parse_qs(urlparse(requested_url).query)["q"], [query])
        self.assertEqual(response["returned_count"], 1)


class SearXNGSearchProviderTests(unittest.TestCase):
    def _make_settings(self, data_dir: Path) -> Settings:
        return Settings(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=data_dir / "library",
            searxng_base_url="http://localhost:8888",
        )

    def test_normalizes_searxng_results(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            settings = self._make_settings(Path(data_dir))
            provider = SearXNGSearchProvider(settings)
            searxng_response = {
                "results": [
                    {
                        "title": "儿童科普太阳系",
                        "url": "https://example.com/solar#frag",
                        "content": "太阳系八大行星介绍",
                        "engines": ["baidu", "bing"],
                        "score": 8.5,
                    }
                ],
                "unresponsive_engines": [["google", "timeout"]],
            }
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(searxng_response).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("education_resource_mcp.search.urlopen", return_value=mock_resp):
                resources, platform_runs = provider.search([_task("generic", "太阳系")], 10)

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["title"], "儿童科普太阳系")
        self.assertEqual(resources[0]["source_url"], "https://example.com/solar")
        self.assertEqual(resources[0]["platform"], "generic")
        self.assertEqual(resources[0]["metadata"]["engine"], "baidu")
        self.assertEqual(len(platform_runs), 1)
        self.assertEqual(platform_runs[0]["status"], "partial")
        self.assertEqual(platform_runs[0]["query_runs"][0]["failure_count"], 1)

    def test_skips_invalid_urls_and_empty_titles(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            settings = self._make_settings(Path(data_dir))
            provider = SearXNGSearchProvider(settings)
            searxng_response = {
                "results": [
                    {"title": "", "url": "https://example.com/a"},
                    {"title": "有效", "url": "javascript:alert(1)"},
                    {"title": "保留", "url": "https://example.com/b"},
                ],
            }
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(searxng_response).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("education_resource_mcp.search.urlopen", return_value=mock_resp):
                resources, _ = provider.search([_task("generic", "测试")], 10)

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["title"], "保留")


if __name__ == "__main__":
    unittest.main()
