from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from education_resource_mcp.config import Settings
from education_resource_mcp.search import MultiPlatformSearchProvider, canonical_http_url


def _task(platform: str, query: str) -> dict:
    return {"platform": platform, "queries": [{"query": query}]}


class _Adapter:
    platform_id = "demo"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        return [
            {
                "platform": "demo",
                "title": "公开资源",
                "source_url": "https://example.com/resource",
                "resource_type": "article",
                "summary": query,
                "metadata": {},
            }
        ], None


class PlatformSearchProviderTests(unittest.TestCase):
    def _provider(self) -> tuple[MultiPlatformSearchProvider, _Adapter]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        settings = Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=2,
        )
        provider = MultiPlatformSearchProvider.__new__(MultiPlatformSearchProvider)
        provider.settings = settings
        provider.session_store = object()
        provider._adapters = {}
        adapter = _Adapter()
        provider.register_adapter(adapter)
        return provider, adapter

    def test_dispatches_natural_query_to_registered_platform(self) -> None:
        provider, adapter = self._provider()
        resources, runs = provider.search([_task("demo", "火山喷发 原理")], 5)

        self.assertEqual(adapter.calls, [("火山喷发 原理", 5)])
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["platform"], "demo")
        self.assertEqual(runs[0]["status"], "succeeded")
        self.assertEqual(runs[0]["query_runs"][0]["candidate_count"], 1)

    def test_generic_search_is_not_an_mcp_search_platform(self) -> None:
        provider, _ = self._provider()
        resources, runs = provider.search([_task("generic", "太阳系 图文")], 5)

        self.assertEqual(resources, [])
        self.assertEqual(runs[0]["status"], "skipped")
        error = runs[0]["query_runs"][0]["error"]
        self.assertEqual(error["code"], "PLATFORM_UNAVAILABLE")
        self.assertIn("宿主 web_search", error["message"])
        self.assertIn("resource_import_url", error["message"])

    def test_unknown_platform_reports_actual_available_platforms(self) -> None:
        provider, _ = self._provider()
        _, runs = provider.search([_task("missing", "测试")], 5)

        message = runs[0]["query_runs"][0]["error"]["message"]
        self.assertIn("demo", message)
        self.assertNotIn("generic,", message)


class CanonicalUrlTests(unittest.TestCase):
    def test_removes_fragment_but_preserves_query(self) -> None:
        self.assertEqual(
            canonical_http_url("https://Example.com/a?q=1#frag"),
            "https://example.com/a?q=1",
        )


if __name__ == "__main__":
    unittest.main()
