from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.service import ResourceService


class _Provider:
    def __init__(self, resources: list[dict], runs: list[dict]) -> None:
        self.resources = resources
        self.runs = runs

    def search(self, search_tasks, limit):
        return [dict(item) for item in self.resources], self.runs


def _query_run(query: str, count: int, *, error: dict | None = None) -> dict:
    return {
        "query": query,
        "candidate_count": count,
        "failure_count": 1 if error else 0,
        **({"error": error} if error else {}),
    }


class SearchProvenanceTests(unittest.TestCase):
    def _search(self, resources: list[dict], runs: list[dict], tasks: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            service = ResourceService(
                settings=Settings(
                    data_dir=root,
                    jobs_dir=root / "jobs",
                    library_dir=root / "library",
                    max_workers=1,
                ),
                search_provider=_Provider(resources, runs),
            )
            try:
                return service.search(tasks)
            finally:
                service.shutdown()

    def test_duplicate_candidate_merges_matched_queries(self) -> None:
        resource = {
            "platform": "bilibili",
            "title": "同一个火山视频",
            "source_url": "https://example.com/video",
            "resource_type": "video",
        }
        runs = [{
            "platform": "bilibili",
            "status": "succeeded",
            "query_runs": [
                _query_run("火山喷发 原理 动画", 1),
                _query_run("火山形成 科普", 1),
            ],
        }]
        result = self._search(
            [resource, resource],
            runs,
            [{"platform": "bilibili", "queries": ["火山喷发 原理 动画", "火山形成 科普"]}],
        )

        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(
            result["candidates"][0]["matched_queries"],
            ["火山喷发 原理 动画", "火山形成 科普"],
        )
        self.assertEqual([run["status"] for run in result["runs"]], ["succeeded", "succeeded"])

    def test_provenance_does_not_cross_platforms(self) -> None:
        resources = [
            {"platform": "bilibili", "title": "B站结果", "source_url": "https://example.com/b"},
            {"platform": "douyin", "title": "抖音结果", "source_url": "https://example.com/d"},
        ]
        runs = [
            {"platform": "bilibili", "status": "succeeded", "query_runs": [_query_run("B站火山", 1)]},
            {"platform": "douyin", "status": "succeeded", "query_runs": [_query_run("抖音火山", 1)]},
        ]
        result = self._search(
            resources,
            runs,
            [
                {"platform": "bilibili", "queries": ["B站火山"]},
                {"platform": "douyin", "queries": ["抖音火山"]},
            ],
        )

        by_platform = {item["platform"]: item for item in result["candidates"]}
        self.assertEqual(by_platform["bilibili"]["matched_queries"], ["B站火山"])
        self.assertEqual(by_platform["douyin"]["matched_queries"], ["抖音火山"])

    def test_zero_result_and_failure_are_visible_in_runs(self) -> None:
        error = {"code": "AUTH_REQUIRED", "message": "需要登录", "retryable": True}
        runs = [
            {"platform": "generic", "status": "succeeded", "query_runs": [_query_run("火山 官方科普", 0)]},
            {"platform": "douyin", "status": "failed", "query_runs": [_query_run("火山 短科普", 0, error=error)]},
        ]
        result = self._search(
            [],
            runs,
            [
                {"platform": "generic", "queries": ["火山 官方科普"]},
                {"platform": "douyin", "queries": ["火山 短科普"]},
            ],
        )

        self.assertEqual(
            [(run["platform"], run["status"], run["candidate_count"]) for run in result["runs"]],
            [("generic", "succeeded", 0), ("douyin", "failed", 0)],
        )
        self.assertEqual(result["failures"][0]["code"], "AUTH_REQUIRED")


if __name__ == "__main__":
    unittest.main()
