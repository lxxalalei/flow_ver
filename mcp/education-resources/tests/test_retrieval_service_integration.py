from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.service import ResourceService
from education_resource_mcp.errors import DomainError
from education_resource_mcp.storage import Store


class _IntegrationProvider:
    def __init__(
        self,
        *,
        search_resources: list[dict],
        creator_resources: list[dict],
    ) -> None:
        self.search_resources = search_resources
        self.creator_resources = creator_resources
        self.search_calls = 0
        self.creator_calls = 0

    def search(self, search_tasks: list[dict], limit: int):
        self.search_calls += 1
        return deepcopy(self.search_resources), [
            {
                "platform": "generic",
                "status": "succeeded",
                "query_runs": [
                    {
                        "query": search_tasks[0]["queries"][0]["query"],
                        "candidate_count": len(self.search_resources),
                        "failure_count": 0,
                    }
                ],
            }
        ]

    def search_creator(self, platform: str, creator_id: str, limit: int):
        self.creator_calls += 1
        return deepcopy(self.creator_resources), [
            {
                "platform": platform,
                "status": "succeeded",
                "query_runs": [
                    {
                        "query": creator_id,
                        "candidate_count": len(self.creator_resources),
                        "failure_count": 0,
                    }
                ],
            }
        ]


class RetrievalServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(root / "database.sqlite")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _service(self, provider: _IntegrationProvider) -> ResourceService:
        service = object.__new__(ResourceService)
        service.store = self.store
        service.settings = SimpleNamespace(max_search_results=50)
        service.search_provider = provider
        return service

    def _flow(self, suffix: str) -> dict:
        return self.store.create_flow(
            {"goal": {"topic": "检索集成测试"}, "constraints": []},
            f"flow-integration-{suffix}",
            f"flow-request-{suffix}",
        )

    def test_fact_coverage_is_factual_and_keeps_identity_separate_from_availability(self) -> None:
        coverage = ResourceService._fact_coverage(
            [
                {
                    "platform": "generic",
                    "resource_type": "article",
                    # Deliberately no stable identity: provenance owns that
                    # observation; it is not availability evidence.
                    "identity": {},
                },
                {
                    "platform": "bilibili",
                    "resource_type": "video",
                    "identity": {"canonical_url": "https://example.test/video"},
                },
            ],
            [
                {"platform": "generic", "status": "succeeded"},
                {"platform": "bilibili", "status": "failed"},
            ],
            [
                {
                    "platform": "bilibili",
                    "code": "PROVIDER_FAILED",
                    "message": "fixture failure",
                }
            ],
        )

        self.assertEqual("factual", coverage["kind"])
        self.assertEqual("factual-coverage-v1", coverage["schema_version"])
        self.assertEqual("partial", coverage["status"])
        self.assertEqual(2, coverage["candidate_count"])
        self.assertEqual(2, coverage["platform_count"])
        self.assertEqual(
            [
                {"resource_type": "article", "count": 1},
                {"resource_type": "video", "count": 1},
            ],
            coverage["resource_types"],
        )
        self.assertEqual(
            ["source", "inspection"],
            [gap["dimension"] for gap in coverage["gaps"]],
        )
        self.assertNotIn("availability", {gap["dimension"] for gap in coverage["gaps"]})
        self.assertTrue(
            {"factual_coverage", "semantic_review", "stop_decision", "model_version"}.isdisjoint(
                coverage
            )
        )

    def test_empty_fact_coverage_reports_observed_empty_result_not_displayability(self) -> None:
        coverage = ResourceService._fact_coverage(
            [],
            [{"platform": "generic", "status": "succeeded"}],
            [],
        )

        self.assertEqual("empty", coverage["status"])
        self.assertEqual(0, coverage["candidate_count"])
        self.assertEqual(1, coverage["platform_count"])
        self.assertEqual([], coverage["resource_types"])
        self.assertEqual(
            [
                {
                    "dimension": "source",
                    "reason": "本轮没有服务端记录的候选",
                    "count": 0,
                }
            ],
            coverage["gaps"],
        )

    def test_search_uses_identity_dedup_before_limit_and_fills_facts(self) -> None:
        provider = _IntegrationProvider(
            search_resources=[
                {
                    "resource_id": "adapter-owned-id",
                    "platform": "generic",
                    "title": "首见论文",
                    "source_url": "https://example.test/article#first",
                    "resource_type": "article",
                    "summary": "",
                    "metadata": {"origin": "first", "nested": {"known": True}},
                },
                {
                    "platform": "generic",
                    "title": "首见论文补充事实",
                    "source_url": "https://example.test/article#second",
                    "resource_type": "article",
                    "summary": "补充摘要",
                    "metadata": {
                        "nested": {"author": "论文作者"},
                        "language": "zh-CN",
                    },
                },
                {
                    "platform": "generic",
                    "title": "论文 DOI 首见",
                    "doi": "10.1000/XYZ.1",
                    "source_url": "https://example.test/doi-a",
                    "resource_type": "article",
                    "summary": "",
                    "metadata": {"origin": "doi"},
                },
                {
                    "platform": "generic",
                    "title": "DOI 解析器补充事实",
                    "source_url": "https://doi.org/10.1000/xyz.1?source=resolver",
                    "resource_type": "article",
                    "summary": "DOI 补充摘要",
                    "metadata": {},
                },
                {
                    "platform": "nlc",
                    "title": "ISBN 十位版本",
                    "source_url": "https://catalog.example/book/10",
                    "isbn": "0-306-40615-2",
                    "resource_type": "book",
                    "metadata": {},
                },
                {
                    "platform": "annas-archive",
                    "title": "ISBN 十三位版本",
                    "source_url": "https://annas.example/book/13",
                    "isbn": "978-0-306-40615-7",
                    "resource_type": "book",
                    "metadata": {"language": "zh-CN"},
                },
                {
                    "platform": "bilibili",
                    "title": "同名视频 A",
                    "source_url": "https://www.bilibili.com/video/BV1First",
                    "resource_type": "video",
                    "metadata": {},
                },
                {
                    "platform": "bilibili",
                    "title": "同名视频 B",
                    "source_url": "https://www.bilibili.com/video/BV1Second",
                    "resource_type": "video",
                    "metadata": {},
                },
                {
                    "platform": "generic",
                    "title": "",
                    "source_url": "https://example.test/empty-title",
                    "resource_type": "article",
                    "metadata": {},
                },
                {
                    "platform": "generic",
                    "title": "非法地址",
                    "source_url": "file:///tmp/not-http",
                    "resource_type": "article",
                    "metadata": {},
                },
            ],
            creator_resources=[],
        )
        service = self._service(provider)
        flow = self._flow("search")

        result = service.search(
            flow["flow_id"],
            "search-integration-key-01",
            [{"platform": "generic", "queries": [{"query": "论文"}]}],
            task_version=flow["task_version"],
            limit=5,
        )

        self.assertEqual(
            ["首见论文", "论文 DOI 首见", "ISBN 十位版本", "同名视频 A", "同名视频 B"],
            [item["title"] for item in result["candidates"]],
        )
        self.assertEqual(5, len(result["candidates"]))
        self.assertTrue(
            all(item["resource_id"].startswith("res_") for item in result["candidates"])
        )
        self.assertEqual(
            len(result["candidates"]),
            len({item["resource_id"] for item in result["candidates"]}),
        )
        self.assertNotIn(
            "adapter-owned-id",
            {item["resource_id"] for item in result["candidates"]},
        )
        self.assertEqual("补充摘要", result["candidates"][0]["summary"])
        self.assertEqual("DOI 补充摘要", result["candidates"][1]["summary"])

        stored = self.store.get_result_set(result["result_set_id"])
        assert stored is not None
        self.assertEqual(
            {"origin": "first", "nested": {"known": True, "author": "论文作者"}, "language": "zh-CN"},
            stored["resources"][0]["metadata"],
        )
        self.assertEqual("https://example.test/article", stored["resources"][0]["source_url"])
        self.assertEqual(1, provider.search_calls)

    def test_search_idempotency_replays_same_random_public_ids(self) -> None:
        provider = _IntegrationProvider(
            search_resources=[
                {
                    "platform": "generic",
                    "title": "可重放资源",
                    "source_url": "https://example.test/replay",
                    "resource_type": "article",
                    "metadata": {},
                }
            ],
            creator_resources=[],
        )
        service = self._service(provider)
        flow = self._flow("replay")
        request = {
            "flow_id": flow["flow_id"],
            "idempotency_key": "search-integration-replay-01",
            "search_tasks": [{"platform": "generic", "queries": [{"query": "重放"}]}],
            "task_version": flow["task_version"],
            "limit": 10,
        }

        first = service.search(**request)
        replay = service.search(**request)

        self.assertEqual(first, replay)
        self.assertTrue(first["candidates"][0]["resource_id"].startswith("res_"))
        self.assertEqual(1, provider.search_calls)
        self.assertEqual(
            first["result_set_id"],
            self.store.get_idempotency(
                f"resource_search:{flow['flow_id']}", request["idempotency_key"]
            )["result_id"],
        )
        self.assertEqual("factual", first["coverage"]["kind"])
        self.assertEqual("factual-coverage-v1", first["coverage"]["schema_version"])
        self.assertEqual(
            first["coverage"],
            self.store.get_result_set(first["result_set_id"])["coverage"],
        )

    def test_direction_is_trace_only_and_cannot_change_factual_coverage(self) -> None:
        provider = _IntegrationProvider(
            search_resources=[
                {
                    "platform": "generic",
                    "title": "同一服务端候选",
                    "source_url": "https://example.test/direction-neutral",
                    "resource_type": "article",
                    "metadata": {
                        "coverage": {"status": "covered"},
                        "model_version": "untrusted-adapter-field",
                    },
                    "coverage": {"status": "covered"},
                    "model_version": "untrusted-adapter-field",
                }
            ],
            creator_resources=[],
        )
        service = self._service(provider)
        first_flow = self._flow("direction-a")
        second_flow = self._flow("direction-b")

        first = service.search(
            first_flow["flow_id"],
            "search-direction-neutral-a",
            [
                {
                    "platform": "generic",
                    "direction": "建立概念解释",
                    "queries": [{"query": "同一查询"}],
                }
            ],
            task_version=first_flow["task_version"],
            limit=10,
        )
        second = service.search(
            second_flow["flow_id"],
            "search-direction-neutral-b",
            [
                {
                    "platform": "generic",
                    "direction": "寻找实践案例",
                    "queries": [{"query": "同一查询"}],
                }
            ],
            task_version=second_flow["task_version"],
            limit=10,
        )

        self.assertEqual(first["coverage"], second["coverage"])
        self.assertEqual("建立概念解释", first["platform_runs"][0]["direction"])
        self.assertEqual("寻找实践案例", second["platform_runs"][0]["direction"])
        self.assertNotIn("direction", first["coverage"])
        self.assertNotIn("model_version", first["coverage"])
        self.assertNotIn("semantic_review", first["coverage"])
        self.assertEqual(
            first["coverage"],
            service.flow_status(first_flow["flow_id"])["current_result_set"]["coverage"],
        )

    def test_search_extend_creates_fresh_immutable_snapshot_and_provenance(self) -> None:
        provider = _IntegrationProvider(
            search_resources=[
                {
                    "platform": "generic",
                    "title": "基础文章",
                    "source_url": "https://example.test/base",
                    "resource_type": "article",
                    "metadata": {},
                }
            ],
            creator_resources=[],
        )
        service = self._service(provider)
        flow = self._flow("extend")
        first = service.search(
            flow["flow_id"],
            "search-integration-extend-01",
            [{"platform": "generic", "direction": "建立基础解释", "queries": [{"query": "基础"}]}],
            task_version=flow["task_version"],
            limit=10,
        )
        base_snapshot = deepcopy(self.store.get_result_set(first["result_set_id"]))

        provider.search_resources = [
            {
                "platform": "generic",
                "title": "基础文章重复",
                "source_url": "https://example.test/base#repeat",
                "resource_type": "article",
                "summary": "第二轮补充事实",
                "metadata": {},
            },
            {
                "platform": "bilibili",
                "title": "新增视频",
                "source_url": "https://www.bilibili.com/video/BV1Adaptive",
                "resource_type": "video",
                "metadata": {},
            },
        ]
        extended = service.search(
            flow["flow_id"],
            "search-integration-extend-02",
            [{"platform": "generic", "direction": "补充直观演示", "queries": [{"query": "演示"}]}],
            task_version=flow["task_version"],
            mode="extend",
            base_result_set_id=first["result_set_id"],
            limit=10,
        )

        self.assertEqual("extend", extended["mode"])
        self.assertEqual(first["result_set_id"], extended["base_result_set_id"])
        self.assertEqual(2, extended["round"])
        self.assertEqual(1, extended["provenance"]["new_unique_count"])
        self.assertEqual(1, extended["provenance"]["duplicate_of_base_count"])
        self.assertEqual(["基础文章", "新增视频"], [item["title"] for item in extended["candidates"]])
        self.assertEqual("第二轮补充事实", extended["candidates"][0]["summary"])
        self.assertNotEqual(
            first["candidates"][0]["resource_id"],
            extended["candidates"][0]["resource_id"],
        )
        self.assertEqual(base_snapshot, self.store.get_result_set(first["result_set_id"]))
        status = service.flow_status(flow["flow_id"])
        self.assertEqual(extended["result_set_id"], status["current_result_set"]["result_set_id"])
        self.assertEqual(2, status["current_result_set"]["round"])

    def test_search_extend_rejects_stale_base_without_provider_call(self) -> None:
        provider = _IntegrationProvider(
            search_resources=[
                {
                    "platform": "generic",
                    "title": "第一轮",
                    "source_url": "https://example.test/round-one",
                    "resource_type": "article",
                    "metadata": {},
                }
            ],
            creator_resources=[],
        )
        service = self._service(provider)
        flow = self._flow("stale")
        first = service.search(
            flow["flow_id"],
            "search-integration-stale-01",
            [{"platform": "generic", "queries": [{"query": "第一轮"}]}],
            task_version=flow["task_version"],
        )
        provider.search_resources = []
        service.search(
            flow["flow_id"],
            "search-integration-stale-02",
            [{"platform": "generic", "queries": [{"query": "第二轮"}]}],
            task_version=flow["task_version"],
        )
        calls_before = provider.search_calls
        with self.assertRaises(DomainError) as caught:
            service.search(
                flow["flow_id"],
                "search-integration-stale-03",
                [{"platform": "generic", "queries": [{"query": "陈旧扩展"}]}],
                task_version=flow["task_version"],
                mode="extend",
                base_result_set_id=first["result_set_id"],
            )
        self.assertEqual("RESULT_SET_STATE_CONFLICT", caught.exception.code)
        self.assertEqual(calls_before, provider.search_calls)

    def test_browse_creator_reuses_the_same_identity_path_and_scope(self) -> None:
        provider = _IntegrationProvider(
            search_resources=[
                {
                    "platform": "generic",
                    "title": "关键词结果",
                    "source_url": "https://example.test/search-result",
                    "resource_type": "article",
                    "metadata": {},
                }
            ],
            creator_resources=[
                {
                    "platform": "bilibili",
                    "title": "创作者首见视频",
                    "source_url": "https://www.bilibili.com/video/BV1Creator?from=share",
                    "resource_type": "video",
                    "summary": "",
                    "metadata": {"author": "creator"},
                },
                {
                    "platform": "bilibili",
                    "title": "创作者重复视频",
                    "source_url": "https://www.bilibili.com/video/BV1Creator?vd_source=feed",
                    "resource_type": "video",
                    "summary": "创作者补充摘要",
                    "metadata": {"language": "zh-CN"},
                },
                {
                    "platform": "bilibili",
                    "title": "创作者另一个视频",
                    "source_url": "https://www.bilibili.com/video/BV1Other",
                    "resource_type": "video",
                    "metadata": {},
                },
            ],
        )
        service = self._service(provider)
        flow = self._flow("creator")
        key = "browse-integration-key-01"

        first = service.browse_creator(
            flow["flow_id"],
            key,
            "bilibili",
            "up-creator",
            task_version=flow["task_version"],
            limit=10,
        )
        replay = service.browse_creator(
            flow["flow_id"],
            key,
            "bilibili",
            "up-creator",
            task_version=flow["task_version"],
            limit=10,
        )

        self.assertEqual(first, replay)
        self.assertEqual(
            ["创作者首见视频", "创作者另一个视频"],
            [item["title"] for item in first["candidates"]],
        )
        self.assertEqual("创作者补充摘要", first["candidates"][0]["summary"])
        self.assertEqual(1, provider.creator_calls)

        stored = self.store.get_result_set(first["result_set_id"])
        assert stored is not None
        self.assertEqual(
            f"browse_creator:{flow['flow_id']}",
            self.store.get_idempotency(
                f"browse_creator:{flow['flow_id']}", key
            )["scope"],
        )
        self.assertEqual("zh-CN", stored["resources"][0]["metadata"]["language"])


if __name__ == "__main__":
    unittest.main()
