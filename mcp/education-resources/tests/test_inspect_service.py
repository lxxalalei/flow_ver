from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import time
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SRC = Path(__file__).resolve().parents[1] / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError, ok
from education_resource_mcp.inspection import (
    InspectionResult,
    build_default_inspection,
    build_representation_authority,
)
from education_resource_mcp.inspection_registry import default_inspection_router
from education_resource_mcp.retrieval.registry import INSPECTION_PLATFORM_IDS
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


class CountingInspector:
    platform_id = "generic"
    inspector_id = "test-inspector"
    version = "1.0.0"

    def __init__(self, *, unresolved_first: bool = False, delay: float = 0.0) -> None:
        self.calls = 0
        self._lock = threading.Lock()
        self.unresolved_first = unresolved_first
        self.delay = delay

    def inspect(self, resource: dict) -> InspectionResult:
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.calls += 1
            call_number = self.calls
        if self.unresolved_first and call_number == 1:
            return InspectionResult(
                resolution_status="unresolved",
                resolved_resource={
                    "title": resource["title"],
                    "resource_type": resource["resource_type"],
                    "availability": {"status": "unknown"},
                    "representations": [],
                    "metadata": {},
                },
                inspection=build_default_inspection(
                    self.inspector_id,
                    method="stub",
                    cache_status="miss",
                    inspected_at="2026-08-08T00:00:00Z",
                ),
                failures=[
                    {
                        "platform": "generic",
                        "resource_id": resource["resource_id"],
                        "code": "PARTIAL_FAILURE",
                        "message": "fixture retry",
                        "retriable": True,
                    }
                ],
            )
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": resource["title"],
                "resource_type": resource["resource_type"],
                "availability": {"status": "available"},
                "representations": [
                    {
                        "kind": "webpage",
                        "container": "html",
                        "mime_type": "text/html",
                        "role": "primary",
                        "materializable": True,
                        "requires_auth": False,
                    }
                ],
                "metadata": {"fixture": True},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="stub",
                cache_status="miss",
                inspected_at="2026-08-08T00:00:00Z",
            ),
            failures=[],
        )


class UnsupportedInspector:
    platform_id = "douyin"
    inspector_id = "unsupported"
    version = "1.0.0"

    def inspect(self, resource: dict) -> InspectionResult:
        raise AssertionError("unsupported fixture must not be called")


class ExpiringInspector:
    platform_id = "generic"
    inspector_id = "expiring-inspector"
    version = "1.0.0"

    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, resource: dict) -> InspectionResult:
        self.calls += 1
        now = datetime.now(timezone.utc)
        if self.calls == 1:
            observed = now - timedelta(hours=2)
            expires = now - timedelta(hours=1)
        else:
            observed = now - timedelta(minutes=1)
            expires = now + timedelta(hours=1)
        authority = build_representation_authority(
            resource,
            scope="landing_page",
            role="landing",
            technical_availability="available",
            observed_at=observed.isoformat(),
            expires_at=expires.isoformat(),
        )
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": resource["title"],
                "resource_type": resource["resource_type"],
                "availability": {"status": "available"},
                "representations": [
                    {
                        **authority,
                        "kind": "webpage",
                        "container": "html",
                        "mime_type": "text/html",
                        "role": "landing",
                        "materializable": True,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="stub",
                cache_status="miss",
                inspected_at=observed.isoformat(),
            ),
            failures=[],
        )


class InspectServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(
            data_dir=root,
            database_path=root / "database.sqlite",
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_search_results=20,
            max_workers=2,
        )
        self.inspector = CountingInspector()
        from education_resource_mcp.inspection import InspectionRouter

        self.router = InspectionRouter([self.inspector])
        self.resources = [
            {
                "platform": "generic",
                "title": "儿童网页资料",
                "source_url": "https://example.com/child-resource",
                "resource_type": "article",
                "summary": "用于服务验收的固定资源",
                "metadata": {"language": "zh-CN"},
            },
            {
                "platform": "generic",
                "title": "另一份资料",
                "source_url": "https://example.com/second-resource",
                "resource_type": "article",
                "summary": "第二个固定资源",
                "metadata": {},
            },
        ]
        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(self.resources),
            inspection_router=self.router,
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def _flow_and_search(self, *, resources=None):
        flow = self.service.flow_start(
            "inspect-flow-start-001",
            {"goal": {"topic": "网页资料"}, "constraints": []},
        )
        search = self.service.search(
            flow["flow_id"],
            "inspect-search-key-001",
            [{"platform": "generic", "queries": [{"query": "网页资料"}]}],
            limit=20,
        )
        return flow, search

    def _schema_registry(self) -> Registry:
        contracts = Path(__file__).resolve().parents[1] / "contracts"
        registry = Registry()
        for path in contracts.rglob("*.json"):
            document = __import__("json").loads(path.read_text(encoding="utf-8"))
            identifier = document.get("$id")
            if identifier:
                registry = registry.with_resource(
                    identifier, Resource.from_contents(document)
                )
        return registry

    def test_success_output_matches_schema_and_assigns_representation_id(self) -> None:
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]

        result = self.service.inspect(
            flow["flow_id"], "inspect-success-key-001", resource_id
        )
        public = ok(result)
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "contracts"
            / "schemas"
            / "tools"
            / "resource_inspect.schema.json"
        )
        schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            {**schema, "$ref": "#/$defs/success"},
            registry=self._schema_registry(),
        )
        self.assertEqual([], [error.message for error in validator.iter_errors(public)])
        representation = result["resolved_resource"]["representations"][0]
        self.assertRegex(representation["representation_id"], r"^repr_[A-Za-z0-9_-]{16,64}$")
        self.assertEqual(1, self.inspector.calls)

    def test_cross_flow_and_unknown_resource_are_equivalent(self) -> None:
        flow_a, search_a = self._flow_and_search()
        resource_a = search_a["candidates"][0]["resource_id"]
        flow_b = self.service.flow_start(
            "inspect-flow-start-002",
            {"goal": {"topic": "另一流程"}, "constraints": []},
        )
        with self.assertRaises(DomainError) as crossed:
            self.service.inspect(
                flow_b["flow_id"], "inspect-cross-flow-key", resource_a
            )
        with self.assertRaises(DomainError) as missing:
            self.service.inspect(
                flow_a["flow_id"],
                "inspect-missing-resource",
                "res_00000000000000000000000000000000",
            )
        self.assertEqual("RESOURCE_NOT_FOUND", crossed.exception.code)
        self.assertEqual(crossed.exception.code, missing.exception.code)
        self.assertEqual(0, self.inspector.calls)

    def test_same_key_replay_and_conflict_happen_before_inspector(self) -> None:
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        first = self.service.inspect(flow["flow_id"], "inspect-replay-key", resource_id)
        replay = self.service.inspect(flow["flow_id"], "inspect-replay-key", resource_id)
        self.assertEqual(first, replay)
        self.assertEqual(1, self.inspector.calls)
        with self.assertRaises(DomainError) as conflict:
            self.service.inspect(
                flow["flow_id"],
                "inspect-replay-key",
                "res_11111111111111111111111111111111",
            )
        self.assertEqual("IDEMPOTENCY_CONFLICT", conflict.exception.code)
        self.assertEqual(1, self.inspector.calls)

    def test_cache_hit_skips_inspector_and_marks_hit(self) -> None:
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        first = self.service.inspect(flow["flow_id"], "inspect-cache-key-01", resource_id)
        second = self.service.inspect(flow["flow_id"], "inspect-cache-key-02", resource_id)
        self.assertEqual("miss", first["inspection"]["cache_status"])
        self.assertEqual("hit", second["inspection"]["cache_status"])
        self.assertEqual(first["resolution_status"], second["resolution_status"])
        self.assertEqual(1, self.inspector.calls)

    def test_expired_cache_runs_inspector_and_marks_refresh(self) -> None:
        self.service.close()
        self.inspector = ExpiringInspector()
        from education_resource_mcp.inspection import InspectionRouter

        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(self.resources),
            inspection_router=InspectionRouter([self.inspector]),
        )
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        first = self.service.inspect(
            flow["flow_id"], "inspect-expired-cache-01", resource_id
        )
        refreshed = self.service.inspect(
            flow["flow_id"], "inspect-expired-cache-02", resource_id
        )
        cached = self.service.inspect(
            flow["flow_id"], "inspect-expired-cache-03", resource_id
        )
        self.assertEqual("miss", first["inspection"]["cache_status"])
        self.assertEqual("refresh", refreshed["inspection"]["cache_status"])
        self.assertEqual("hit", cached["inspection"]["cache_status"])
        self.assertNotEqual(first["resolution_id"], refreshed["resolution_id"])
        self.assertEqual(2, self.inspector.calls)

    def test_unresolved_is_persisted_but_a_new_key_retries(self) -> None:
        self.service.close()
        from education_resource_mcp.inspection import InspectionRouter

        self.inspector = CountingInspector(unresolved_first=True)
        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(self.resources),
            inspection_router=InspectionRouter([self.inspector]),
        )
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        first = self.service.inspect(flow["flow_id"], "inspect-unresolved-01", resource_id)
        replay = self.service.inspect(flow["flow_id"], "inspect-unresolved-01", resource_id)
        retry = self.service.inspect(flow["flow_id"], "inspect-unresolved-02", resource_id)
        self.assertEqual("unresolved", first["resolution_status"])
        self.assertEqual(first, replay)
        self.assertEqual("resolved", retry["resolution_status"])
        self.assertEqual(2, self.inspector.calls)

    def test_concurrent_same_key_performs_one_inspection(self) -> None:
        self.service.close()
        from education_resource_mcp.inspection import InspectionRouter

        self.inspector = CountingInspector(delay=0.02)
        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(self.resources),
            inspection_router=InspectionRouter([self.inspector]),
        )
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]

        def inspect_once(_: int):
            return self.service.inspect(flow["flow_id"], "inspect-concurrent-key", resource_id)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(inspect_once, range(8)))
        self.assertEqual(1, self.inspector.calls)
        self.assertTrue(all(item == results[0] for item in results))

    def test_snapshot_is_unchanged_and_flow_status_recovers_resolution(self) -> None:
        flow, search = self._flow_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        before_result_set = deepcopy(self.service.store.get_result_set(search["result_set_id"]))
        before_resources = deepcopy(self.service.store.get_resources(flow["flow_id"], [resource_id]))
        self.service.inspect(flow["flow_id"], "inspect-recovery-key", resource_id)
        self.assertEqual(before_result_set, self.service.store.get_result_set(search["result_set_id"]))
        self.assertEqual(before_resources, self.service.store.get_resources(flow["flow_id"], [resource_id]))

        status = self.service.flow_status(flow["flow_id"])
        self.assertEqual(1, len(status["current_resolutions"]))
        self.assertEqual(resource_id, status["current_resolutions"][0]["resource_id"])
        self.assertIn("resource_inspect", status["allowed_next_actions"])
        self.assertIn("resource_browse_creator", status["allowed_next_actions"])
        self.assertNotIn("resource_flow_start", status["allowed_next_actions"])

    def test_unsupported_platform_preserves_feature_not_supported(self) -> None:
        from education_resource_mcp.inspection import InspectionRouter

        unsupported_service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(
                [
                    {
                        "platform": "douyin",
                        "title": "未启用平台资源",
                        "source_url": "https://www.douyin.com/video/1",
                        "resource_type": "video",
                        "metadata": {},
                    }
                ]
            ),
            inspection_router=InspectionRouter([self.inspector]),
        )
        try:
            flow = unsupported_service.flow_start(
                "inspect-unsupported-flow",
                {"goal": {"topic": "未启用平台"}, "constraints": []},
            )
            search = unsupported_service.search(
                flow["flow_id"],
                "inspect-unsupported-search",
                [{"platform": "douyin", "queries": [{"query": "未启用平台"}]}],
                limit=1,
            )
            with self.assertRaises(DomainError) as error:
                unsupported_service.inspect(
                    flow["flow_id"], "inspect-unsupported-key", search["candidates"][0]["resource_id"]
                )
            self.assertEqual("FEATURE_NOT_SUPPORTED", error.exception.code)
            self.assertEqual(0, self.inspector.calls)
        finally:
            unsupported_service.close()

    def test_default_router_matches_registry_exactly(self) -> None:
        router = default_inspection_router(self.settings)
        self.assertEqual(set(INSPECTION_PLATFORM_IDS), set(router.registered_platforms))


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
