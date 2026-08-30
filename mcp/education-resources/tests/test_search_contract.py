"""Loud validation of the generic resource_search input contract."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.server import SearchTask
from education_resource_mcp.service import ResourceService


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], int]] = []

    def search(self, search_tasks, limit):
        self.calls.append((search_tasks, limit))
        return [], []


class SearchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.provider = _RecordingProvider()
        self.service = ResourceService(
            settings=Settings(
                data_dir=root,
                jobs_dir=root / "jobs",
                library_dir=root / "library",
                max_workers=1,
            ),
            search_provider=self.provider,
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_public_search_schema_has_only_platform_and_natural_queries(self) -> None:
        schema = SearchTask.model_json_schema()["properties"]
        self.assertEqual({"platform", "queries"}, set(schema))
        description = schema["platform"]["description"]
        self.assertIn("libgen", description)
        self.assertIn("zlibrary", description)
        self.assertIn("不要传平台内部分类代码", description)
        self.assertNotIn("tabs", description)
        self.assertNotIn("catalog_expand", description)

    def test_string_queries_are_normalized_to_internal_shape(self) -> None:
        self.service.search(
            [{"platform": "bilibili", "queries": ["火山喷发 原理", " 去抖动 "]}]
        )
        tasks, _ = self.provider.calls[-1]
        self.assertEqual(
            [{
                "platform": "bilibili",
                "queries": [
                    {"query": "火山喷发 原理"},
                    {"query": "去抖动"},
                ],
            }],
            tasks,
        )

    def test_query_dict_items_still_accepted_by_service(self) -> None:
        self.service.search(
            [{"platform": "generic", "queries": [{"query": "太阳系 图文"}]}]
        )
        tasks, _ = self.provider.calls[-1]
        self.assertEqual([{"query": "太阳系 图文"}], tasks[0]["queries"])

    def _assert_invalid(self, payload: object, fragment: str) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.search(payload)
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        self.assertIn(fragment, ctx.exception.message)
        self.assertIn('"platform"', ctx.exception.message)
        self.assertIn('"queries"', ctx.exception.message)

    def test_task_level_query_key_rejected(self) -> None:
        self._assert_invalid(
            [{"platform": "bilibili", "query": "听见你说"}],
            "未知字段 ['query']",
        )

    def test_missing_platform_rejected(self) -> None:
        self._assert_invalid([{"queries": ["x"]}], "缺少 platform")

    def test_empty_queries_rejected(self) -> None:
        self._assert_invalid(
            [{"platform": "bilibili", "queries": []}],
            "queries 必须是非空列表",
        )

    def test_non_string_query_item_rejected(self) -> None:
        self._assert_invalid(
            [{"platform": "bilibili", "queries": [42]}],
            "每一项必须是搜索短语",
        )

    def test_non_dict_task_rejected(self) -> None:
        self._assert_invalid(["bilibili"], "每一项必须是对象")


if __name__ == "__main__":
    unittest.main()
