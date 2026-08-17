"""0057 M2: smartedu search tabs parameter flows task → adapter → payload."""

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
from education_resource_mcp.service import ResourceService


class _FakeSmartedu:
    platform_id = "smartedu"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, list[str] | None]] = []

    def search(self, query: str, limit: int, tabs: list[str] | None = None):
        self.calls.append((query, limit, tabs))
        return [], None


class _FakeBilibili:
    platform_id = "bilibili"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        return [], None


class _Provider:
    def __init__(self, adapters: dict[str, object]) -> None:
        self._adapters = adapters

    def search(self, search_tasks, limit):
        # minimal parallel-free stub mirroring MultiPlatformSearchProvider
        for task in search_tasks:
            platform = task["platform"]
            adapter = self._adapters.get(platform)
            if adapter is None:
                continue
            for q in task.get("queries") or []:
                tabs = task.get("tabs")
                if platform == "smartedu" and tabs:
                    adapter.search(q["query"], limit, tabs=tabs)
                else:
                    adapter.search(q["query"], limit)
        return [], []

    def search_creator(self, *a, **k):
        return [], []


class SmarteduTabsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.smartedu = _FakeSmartedu()
        self.bilibili = _FakeBilibili()
        self.provider = _Provider(
            {"smartedu": self.smartedu, "bilibili": self.bilibili}
        )
        self.service = ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=1,
            ),
            search_provider=self.provider,
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_tabs_flow_to_smartedu_search(self) -> None:
        self.service.search(
            [
                {
                    "platform": "smartedu",
                    "queries": ["一元二次方程"],
                    "tabs": ["tchMaterial", "qualityCourse"],
                }
            ]
        )
        (query, limit, tabs) = self.smartedu.calls[-1]
        self.assertEqual("一元二次方程", query)
        self.assertEqual(["tchMaterial", "qualityCourse"], tabs)

    def test_no_tabs_means_default(self) -> None:
        self.service.search([{"platform": "smartedu", "queries": ["方程"]}])
        (_, _, tabs) = self.smartedu.calls[-1]
        self.assertIsNone(tabs)

    def test_tabs_ignored_for_other_platforms(self) -> None:
        self.service.search(
            [{"platform": "bilibili", "queries": ["纪录片"], "tabs": ["x"]}]
        )
        self.assertEqual(("纪录片", 8), self.bilibili.calls[-1])

    def test_invalid_tabs_rejected_loudly(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.search(
                [{"platform": "smartedu", "queries": ["x"], "tabs": "tchMaterial"}]
            )
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        with self.assertRaises(DomainError) as ctx:
            self.service.search(
                [{"platform": "smartedu", "queries": ["x"], "tabs": [""]}]
            )
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
