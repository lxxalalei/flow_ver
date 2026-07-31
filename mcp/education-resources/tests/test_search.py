from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from education_resource_mcp.config import Settings
from education_resource_mcp.search import GenericWebSearchProvider, SearXNGSearchProvider


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
                resources, errors = provider.search("测试主题", 5, ["generic"])

            search.assert_called_once_with("测试主题", ["duckduckgo"], 5, 20.0)
            self.assertEqual(errors, [])
            self.assertEqual(len(resources), 1)
            self.assertEqual(resources[0]["source_url"], "https://example.com/resource")

    def test_reports_platforms_not_migrated_to_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            settings = Settings(
                data_dir=root,
                database_path=root / "database.sqlite",
                jobs_dir=root / "jobs",
                library_dir=root / "library",
            )
            provider = GenericWebSearchProvider(settings)
            resources, errors = provider.search("测试主题", 5, ["bilibili"])

        self.assertEqual(resources, [])
        self.assertEqual(errors[0]["platform"], "bilibili")
        self.assertEqual(errors[0]["code"], "PLATFORM_UNAVAILABLE")


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
                resources, errors = provider.search("太阳系", 10, ["generic"])

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["title"], "儿童科普太阳系")
        self.assertEqual(resources[0]["source_url"], "https://example.com/solar")
        self.assertEqual(resources[0]["platform"], "generic")
        self.assertEqual(resources[0]["metadata"]["engine"], "baidu")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "PARTIAL_FAILURE")

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
                resources, _ = provider.search("测试", 10)

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["title"], "保留")


if __name__ == "__main__":
    unittest.main()
