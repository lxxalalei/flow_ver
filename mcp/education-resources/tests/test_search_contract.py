"""Loud validation of the resource_search input contract.

A malformed search_task used to be dropped silently, producing a
successful-but-empty search (0056 follow-up: the agent then spent a dozen
turns reading source code to guess the shape).  These tests pin the loud
behaviour: reject with INVALID_ARGUMENT and spell out the structure.
"""

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
    """Offline search provider that records the tasks it received."""

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

    # -- accepted forms -------------------------------------------------

    def test_platform_schema_explains_capability_levels(self) -> None:
        description = SearchTask.model_json_schema()["properties"]["platform"][
            "description"
        ]
        for fact in (
            "Search + Inspect + Download",
            "zjer 只接受 courseCateId 或详情 URL",
            "nlc 支持 Search + Inspect，但没有 Download 路由",
            "weibo 支持 Search 和创作者完整枚举",
            "当前仅提供 Search 发现",
            "仅发现平台返回的原 resource_id 不能直接 Inspect/Download",
        ):
            self.assertIn(fact, description)

    def test_string_queries_are_normalized_to_legacy_shape(self) -> None:
        self.service.search(
            [{"platform": "bilibili", "queries": ["火山喷发 原理", " 去抖动 "]}]
        )
        tasks, _ = self.provider.calls[-1]
        self.assertEqual(
            [{"platform": "bilibili",
              "queries": [{"query": "火山喷发 原理"}, {"query": "去抖动"}]}],
            tasks,
        )

    def test_query_dict_items_still_accepted(self) -> None:
        self.service.search(
            [{"platform": "generic", "queries": [{"query": "太阳系 图文"}]}]
        )
        tasks, _ = self.provider.calls[-1]
        self.assertEqual(
            [{"query": "太阳系 图文"}], tasks[0]["queries"]
        )

    # -- loud rejections -------------------------------------------------

    def _assert_invalid(self, payload: object, fragment: str) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.search(payload)
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        self.assertIn(fragment, ctx.exception.message)
        # every rejection spells out the expected structure
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
            [{"platform": "bilibili", "queries": []}], "queries 必须是非空列表"
        )

    def test_non_string_query_item_rejected(self) -> None:
        self._assert_invalid(
            [{"platform": "bilibili", "queries": [42]}], "每一项必须是搜索短语"
        )

    def test_non_dict_task_rejected(self) -> None:
        self._assert_invalid(["bilibili"], "每一项必须是对象")


if __name__ == "__main__":
    unittest.main()
