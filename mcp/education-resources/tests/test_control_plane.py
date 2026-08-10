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
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


RESOURCES = [
    {
        "platform": "generic",
        "title": "恐龙入门资料",
        "source_url": "https://example.com/dinosaur-a",
        "resource_type": "article",
        "summary": "A",
        "metadata": {"language": "zh-CN"},
    },
    {
        "platform": "generic",
        "title": "恐龙化石资料",
        "source_url": "https://example.com/dinosaur-b",
        "resource_type": "article",
        "summary": "B",
        "metadata": {},
    },
]


class OfflineGenericInspector:
    """Return exact built-in generic primary-document evidence without I/O."""

    platform_id = "generic"
    inspector_id = "generic"
    version = "1.0.0"
    supported_scopes = ("primary_resource",)

    def inspect(self, resource: dict) -> InspectionResult:
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": resource["title"],
                "resource_type": resource["resource_type"],
                "availability": {"status": "available"},
                "representations": [
                    {
                        "scope": "primary_resource",
                        "kind": "document",
                        "container": "pdf",
                        "mime_type": "application/pdf",
                        "role": "primary",
                        "materializable": True,
                        "technical_availability": "available",
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                version=self.version,
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-10T00:00:00Z",
            ),
            failures=[],
        )


class V2ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(
            data_dir=root,
            database_path=root / "database.sqlite",
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_search_results=20,
            max_workers=1,
        )
        self.service = self._service()

    def _service(self) -> ResourceService:
        return ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(RESOURCES),
            inspection_router=InspectionRouter([OfflineGenericInspector()]),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def _start_search(self, suffix: str = "01") -> tuple[dict, dict]:
        flow = self.service.flow_start(
            f"flow-start-key-{suffix}",
            {
                "goal": {"topic": "恐龙", "outcome": "找到入门资料"},
                "user_role": "parent",
                "resource_target": "child",
                "constraints": [{"kind": "language", "value": "zh-CN"}],
            },
        )
        search = self.service.search(
            flow["flow_id"], f"search-key-{suffix}000",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            limit=10,
        )
        return flow, search

    def _present(self, flow: dict, search: dict, ids: list[str], suffix: str) -> dict:
        return self.service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            ids,
            f"presentation-{suffix}",
        )

    def _inspect(self, flow: dict, resource_id: str, suffix: str) -> dict:
        resolution = self.service.inspect(
            flow["flow_id"],
            f"inspect-{suffix}",
            resource_id,
        )
        self.assertEqual(
            ("generic", "1.0.0"),
            (
                resolution["inspection"]["inspector_id"],
                resolution["inspection"]["version"],
            ),
        )
        self.assertEqual(
            "primary_resource",
            resolution["resolved_resource"]["representations"][0]["scope"],
        )
        return resolution

    def test_hidden_candidate_and_cross_flow_result_set_are_rejected(self) -> None:
        flow_a, search_a = self._start_search("01")
        flow_b, _ = self._start_search("02")
        visible = search_a["candidates"][0]["resource_id"]
        presentation = self._present(flow_a, search_a, [visible], "key-00000001")
        with self.assertRaises(DomainError) as hidden:
            self.service.selection_save(
                flow_a["flow_id"],
                "selection-key-001",
                presentation["presentation_id"],
                presentation["presented_version"],
                [2],
            )
        self.assertEqual(hidden.exception.code, "POSITION_NOT_PRESENTED")
        with self.assertRaises(DomainError) as crossed:
            self.service.presentation_save(
                flow_b["flow_id"],
                search_a["result_set_id"],
                [visible],
                "presentation-cross-1",
            )
        self.assertEqual(crossed.exception.code, "RESULT_SET_NOT_FOUND")

    def test_display_order_survives_restart_and_changed_replay_conflicts(self) -> None:
        flow, search = self._start_search("03")
        ids = [item["resource_id"] for item in reversed(search["candidates"])]
        presentation = self._present(flow, search, ids, "key-00000002")
        self.assertEqual(
            [item["resource_id"] for item in presentation["items"]], ids
        )
        with self.assertRaises(DomainError) as conflict:
            self._present(flow, search, list(reversed(ids)), "key-00000002")
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")
        self.service.close()
        self.service = self._service()
        recovered = self.service.flow_status(flow["flow_id"])
        self.assertEqual(
            [item["resource_id"] for item in recovered["current_presentation"]["items"]],
            ids,
        )
        self.assertEqual(
            [item["display_position"] for item in recovered["current_presentation"]["items"]],
            [1, 2],
        )

    def test_new_presentation_invalidates_old_selection_and_plan(self) -> None:
        flow, search = self._start_search("04")
        ids = [item["resource_id"] for item in search["candidates"]]
        first = self._present(flow, search, ids, "key-00000003")
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-002",
            first["presentation_id"],
            first["presented_version"],
            [1],
        )
        self._inspect(flow, ids[0], "prepare-00000001")
        plan = self.service.download_prepare(
            flow["flow_id"], "prepare-key-0001", selection["selection_version"]
        )
        second = self._present(
            flow, search, list(reversed(ids)), "key-00000004"
        )
        self.assertGreater(second["presented_version"], first["presented_version"])
        with self.assertRaises(DomainError) as old_selection:
            self.service.selection_save(
                flow["flow_id"],
                "selection-key-003",
                first["presentation_id"],
                first["presented_version"],
                [1],
            )
        self.assertEqual(old_selection.exception.code, "PRESENTATION_VERSION_CONFLICT")
        with self.assertRaises(DomainError) as old_plan:
            self.service.download_start(
                flow["flow_id"],
                plan["plan_id"],
                plan["confirmation_token"],
                "start-key-000001",
                presentation_id=plan["presentation_id"],
                presented_version=plan["presented_version"],
                selection_version=plan["selection_version"],
                selection_digest=plan["selection_digest"],
                plan_digest=plan["plan_digest"],
                authority_digest=plan["authority_digest"],
            )
        self.assertEqual(old_plan.exception.code, "SELECTION_VERSION_CONFLICT")

    def test_a_b_a_selection_versions_are_monotonic_and_old_plan_never_revives(self) -> None:
        flow, search = self._start_search("05")
        ids = [item["resource_id"] for item in search["candidates"]]
        presentation = self._present(flow, search, ids, "key-00000005")

        def select(position: int, key: str) -> dict:
            return self.service.selection_save(
                flow["flow_id"],
                key,
                presentation["presentation_id"],
                presentation["presented_version"],
                [position],
            )

        first_a = select(1, "selection-key-004")
        self._inspect(flow, ids[0], "prepare-00000002")
        old_plan = self.service.download_prepare(
            flow["flow_id"], "prepare-key-0002", first_a["selection_version"]
        )
        selected_b = select(2, "selection-key-005")
        second_a = select(1, "selection-key-006")
        self.assertEqual(
            [
                first_a["selection_version"],
                selected_b["selection_version"],
                second_a["selection_version"],
            ],
            [1, 2, 3],
        )
        self.assertNotEqual(first_a["selection_digest"], second_a["selection_digest"])
        with self.assertRaises(DomainError) as old_plan_error:
            self.service.download_start(
                flow["flow_id"],
                old_plan["plan_id"],
                old_plan["confirmation_token"],
                "start-key-000002",
                presentation_id=old_plan["presentation_id"],
                presented_version=old_plan["presented_version"],
                selection_version=old_plan["selection_version"],
                selection_digest=old_plan["selection_digest"],
                plan_digest=old_plan["plan_digest"],
                authority_digest=old_plan["authority_digest"],
            )
        self.assertEqual(old_plan_error.exception.code, "SELECTION_VERSION_CONFLICT")

    def test_selection_idempotency_replay_and_conflict(self) -> None:
        flow, search = self._start_search("06")
        ids = [item["resource_id"] for item in search["candidates"]]
        presentation = self._present(flow, search, ids, "key-00000006")
        selected = self.service.selection_save(
            flow["flow_id"],
            "selection-key-007",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        replay = self.service.selection_save(
            flow["flow_id"],
            "selection-key-007",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        self.assertEqual(replay, selected)
        with self.assertRaises(DomainError) as conflict:
            self.service.selection_save(
                flow["flow_id"],
                "selection-key-007",
                presentation["presentation_id"],
                presentation["presented_version"],
                [2],
            )
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_flow_status_recovers_state_without_confirmation_secret(self) -> None:
        flow, search = self._start_search("07")
        resource_id = search["candidates"][0]["resource_id"]
        presentation = self._present(flow, search, [resource_id], "key-00000007")
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-008",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        self._inspect(flow, resource_id, "prepare-00000003")
        plan = self.service.download_prepare(
            flow["flow_id"], "prepare-key-0003", selection["selection_version"]
        )
        status = self.service.flow_status(flow["flow_id"])
        self.assertEqual(status["task"]["user_role"], "parent")
        self.assertEqual(status["task"]["resource_target"], "child")
        self.assertTrue(status["task"]["constraints"][0]["constraint_id"].startswith("con_"))
        self.assertEqual(status["current_result_set"]["result_set_id"], search["result_set_id"])
        self.assertEqual(status["current_plan"]["plan_id"], plan["plan_id"])
        self.assertNotIn("confirmation_token", status["current_plan"])
        self.assertNotIn("confirmation_hash", status["current_plan"])
        self.assertIn("resource_download_start", status["allowed_next_actions"])


if __name__ == "__main__":
    unittest.main()
