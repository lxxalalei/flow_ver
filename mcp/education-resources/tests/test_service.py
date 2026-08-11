from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.acquisition.web_fetch import FetchResult
from education_resource_mcp.acquisition.web_materializer import WebMaterializer
from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    INSPECTION_PROFILE_VERSION,
    build_default_inspection,
    build_representation_authority,
    source_fingerprint,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


class OfflineLandingFetcher:
    def __init__(self, *, wait_for_cancel: bool = False) -> None:
        self.wait_for_cancel = wait_for_cancel
        self.started = threading.Event()

    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        self.started.set()
        if self.wait_for_cancel:
            if cancel_event is None:
                raise AssertionError("materializer must provide a cancellation event")
            if not cancel_event.wait(2):
                raise AssertionError("fixture materializer did not receive cancellation")
            raise DomainError("JOB_CANCELLED", "cancelled")
        payload = (
            "<html><body><article><h1>儿童恐龙知识网页</h1>"
            "<p>适合儿童理解恐龙的公开介绍。</p></article></body></html>"
        ).encode("utf-8")
        return FetchResult(
            url=url,
            status=200,
            media_type="text/html",
            body=payload,
            headers={},
        )


class OfflineLandingInspector:
    platform_id = "generic"
    inspector_id = "generic"
    version = "1.0.0"
    supported_scopes = ("landing_page",)

    def __init__(
        self,
        *,
        observed_at: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        self.observed_at = observed_at
        self.expires_at = expires_at

    def inspect(self, resource: dict) -> InspectionResult:
        authority = build_representation_authority(
            resource,
            scope="landing_page",
            role="landing",
            technical_availability="available",
            observed_at=self.observed_at,
            expires_at=self.expires_at,
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
                        "scope": "landing_page",
                        "kind": "webpage",
                        "container": "html",
                        "mime_type": "text/html",
                        "role": "landing",
                        "materializable": True,
                        "technical_availability": "available",
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                "generic",
                version="1.0.0",
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-09T00:00:00Z",
            ),
            failures=[],
        )


class ResourceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.settings = Settings(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=data_dir / "library",
            max_download_bytes=1024 * 1024,
            max_search_results=20,
            max_workers=2,
            plan_ttl_seconds=60,
        )
        self.resources = [
            {
                "platform": "generic",
                "title": "儿童恐龙知识网页",
                "source_url": "https://example.com/dinosaurs",
                "resource_type": "article",
                "summary": "适合儿童理解恐龙的公开介绍",
                "metadata": {"language": "zh-CN"},
            },
            {
                "platform": "generic",
                "title": "无关资源",
                "source_url": "https://example.org/other",
                "resource_type": "article",
                "summary": "其他内容",
                "metadata": {},
            },
        ]
        self.service = self._build_service()

    def _build_service(
        self,
        *,
        wait_for_cancel: bool = False,
        inspector: OfflineLandingInspector | None = None,
    ) -> ResourceService:
        self.fixture_fetcher = OfflineLandingFetcher(
            wait_for_cancel=wait_for_cancel
        )
        return ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(self.resources),
            acquisition_router=AcquisitionRouter(
                [
                    ProviderRegistration(
                        provider_id="generic-web-materializer",
                        provider_version="1.0.0",
                        provider=WebMaterializer(fetcher=self.fixture_fetcher),
                        strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                        scopes=("landing_page",),
                    )
                ]
            ),
            inspection_router=InspectionRouter(
                [inspector or OfflineLandingInspector()]
            ),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def _start_and_search(self):
        flow = self.service.flow_start(
            "flow-start-key-0001", {"goal": {"topic": "恐龙"}, "user_role": "parent", "resource_target": "child", "constraints": []}
        )
        search = self.service.search(
            flow["flow_id"],
            "search-key-0000001",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            filters={},
            limit=10,
        )
        for position, item in enumerate(search["candidates"], start=1):
            self.service.inspect(
                flow["flow_id"],
                f"inspect-key-{position:08d}",
                item["resource_id"],
            )
        presentation = self.service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            [item["resource_id"] for item in search["candidates"]],
            "presentation-key-0001",
        )
        return flow, search, presentation

    def _wait_terminal(self, flow_id: str, job_id: str):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = self.service.job_status(flow_id, job_id)
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                return status
            time.sleep(0.01)
        self.fail("job did not reach a terminal state")

    def _prepare_first_candidate(self):
        flow, search, presentation = self._start_and_search()
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-prepare-helper-0001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = self.service.download_prepare(
            flow["flow_id"],
            "prepare-helper-key-0001",
            selection["selection_version"],
            options={"preferred_container": "html", "max_bytes_per_resource": 4096},
        )
        return flow, plan

    def test_full_flow_is_idempotent_and_archives_by_asset_id(self) -> None:
        flow, search, presentation = self._start_and_search()
        self.assertEqual(search["stage"], "reviewing")
        self.assertEqual(len(search["candidates"]), 1)
        resource_id = search["candidates"][0]["resource_id"]

        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-0001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = self.service.download_prepare(
            flow["flow_id"],
            "prepare-key-000001",
            selection["selection_version"],
            options={"preferred_container": "html", "max_bytes_per_resource": 4096},
        )
        replayed_plan = self.service.download_prepare(
            flow["flow_id"],
            "prepare-key-000001",
            selection["selection_version"],
            options={"preferred_container": "html", "max_bytes_per_resource": 4096},
        )
        self.assertEqual(replayed_plan, plan)

        with self.assertRaisesRegex(DomainError, "确认令牌"):
            self.service.download_start(
                flow["flow_id"],
                plan["plan_id"],
                "wrong-token",
                "start-key-00000001",
                presentation_id=plan["presentation_id"],
                presented_version=plan["presented_version"],
                selection_version=plan["selection_version"],
                selection_digest=plan["selection_digest"],
                plan_digest=plan["plan_digest"],
                authority_digest=plan["authority_digest"],
            )
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-key-00000002",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
            authority_digest=plan["authority_digest"],
        )
        replayed_start = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-key-00000002",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
            authority_digest=plan["authority_digest"],
        )
        self.assertEqual(replayed_start["job_id"], started["job_id"])
        status = self._wait_terminal(flow["flow_id"], started["job_id"])
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(len(status["assets"]), 1)

        asset_id = status["assets"][0]["asset_id"]
        archived = self.service.archive(
            flow["flow_id"],
            started["job_id"],
            asset_id,
            idempotency_key="archive-key-000001",
            metadata={"title": "恐龙资料", "tags": ["恐龙", "儿童"]},
        )
        replayed_archive = self.service.archive(
            flow["flow_id"],
            started["job_id"],
            asset_id,
            idempotency_key="archive-key-000001",
            metadata={"title": "恐龙资料", "tags": ["恐龙", "儿童"]},
        )
        self.assertEqual(archived, replayed_archive)
        library = self.service.library_search(
            flow["flow_id"], filters={"query": "恐龙"}, limit=20
        )
        self.assertEqual(len(library["assets"]), 1)
        self.assertEqual(library["assets"][0]["asset_id"], asset_id)

    def test_idempotency_conflict_and_presented_set_guard(self) -> None:
        flow = self.service.flow_start(
            "flow-start-key-0002", {"goal": {"topic": "恐龙"}, "user_role": "parent", "resource_target": "child", "constraints": []}
        )
        self.assertEqual(
            flow,
            self.service.flow_start(
                "flow-start-key-0002", {"goal": {"topic": "恐龙"}, "user_role": "parent", "resource_target": "child", "constraints": []}
            ),
        )
        with self.assertRaisesRegex(DomainError, "幂等键"):
            self.service.flow_start(
                "flow-start-key-0002", {"goal": {"topic": "数学"}, "user_role": "parent", "resource_target": "child", "constraints": []}
            )
        search = self.service.search(
            flow["flow_id"], "search-key-0000002",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            limit=10,
        )
        presentation = self.service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            [search["candidates"][0]["resource_id"]],
            "presentation-key-0002",
        )
        with self.assertRaises(DomainError) as captured:
            self.service.selection_save(
                flow["flow_id"],
                "selection-key-0002",
                presentation["presentation_id"],
                presentation["presented_version"],
                [2],
            )
        self.assertEqual(captured.exception.code, "POSITION_NOT_PRESENTED")

    def test_download_start_authority_digest_is_optional_but_checked(self) -> None:
        flow, plan = self._prepare_first_candidate()
        bindings = {
            "presentation_id": plan["presentation_id"],
            "presented_version": plan["presented_version"],
            "selection_version": plan["selection_version"],
            "selection_digest": plan["selection_digest"],
            "plan_digest": plan["plan_digest"],
        }

        with self.assertRaises(DomainError) as captured:
            self.service.download_start(
                flow["flow_id"],
                plan["plan_id"],
                plan["confirmation_token"],
                "start-authority-wrong-0001",
                **bindings,
                authority_digest="0" * 64,
            )
        self.assertEqual("PLAN_BINDING_CONFLICT", captured.exception.code)

        # Compatibility omission is not an execution fallback: the server
        # still reads the immutable Plan authority and returns its exact digest.
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-authority-omitted-0001",
            **bindings,
        )
        self.assertEqual(plan["authority_digest"], started["authority_digest"])
        status = self._wait_terminal(flow["flow_id"], started["job_id"])
        self.assertEqual("succeeded", status["status"])
        self.assertEqual(plan["authority_digest"], status["authority_digest"])

    def test_download_start_runtime_failures_have_stable_public_codes(self) -> None:
        flow, plan = self._prepare_first_candidate()
        bindings = {
            "presentation_id": plan["presentation_id"],
            "presented_version": plan["presented_version"],
            "selection_version": plan["selection_version"],
            "selection_digest": plan["selection_digest"],
            "plan_digest": plan["plan_digest"],
            "authority_digest": plan["authority_digest"],
        }
        reserve_mappings = {
            "idempotency record points to a missing job": "INTERNAL_ERROR",
            "execution_binding_missing": "CAPABILITY_BINDING_CONFLICT",
            "plan_binding_mismatch": "PLAN_BINDING_CONFLICT",
            "plan_used": "PLAN_ALREADY_USED",
            "capability_binding_missing": "CAPABILITY_BINDING_CONFLICT",
            "capability_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
            "execution_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
            "capability_strategy_mismatch": "CAPABILITY_STRATEGY_MISMATCH",
            "readiness_not_ready": "CAPABILITY_NOT_READY",
            "readiness_expired": "READINESS_EXPIRED",
            "readiness_drift": "READINESS_DRIFT",
            "eligibility_required": "ELIGIBILITY_REQUIRED",
            "eligibility_expired": "ELIGIBILITY_EXPIRED",
            "eligibility_drift": "ELIGIBILITY_DRIFT",
            "resolution_stale": "RESOLUTION_STALE",
            "representation_drift": "REPRESENTATION_DRIFT",
            "selection_changed": "SELECTION_VERSION_CONFLICT",
            "failed to reserve job": "INTERNAL_ERROR",
        }
        for index, (runtime_error, public_code) in enumerate(
            reserve_mappings.items(), start=1
        ):
            with self.subTest(runtime_error=runtime_error):
                with patch.object(
                    self.service.store,
                    "reserve_job",
                    side_effect=RuntimeError(runtime_error),
                ):
                    with self.assertRaises(DomainError) as captured:
                        self.service.download_start(
                            flow["flow_id"],
                            plan["plan_id"],
                            plan["confirmation_token"],
                            f"start-runtime-map-{index:04d}",
                            **bindings,
                        )
                self.assertEqual(public_code, captured.exception.code)

        with patch.object(
            self.service.store,
            "lookup_download_start_replay",
            side_effect=RuntimeError("idempotency record points to a missing job"),
        ):
            with self.assertRaises(DomainError) as captured:
                self.service.download_start(
                    flow["flow_id"],
                    plan["plan_id"],
                    plan["confirmation_token"],
                    "start-replay-corrupt-0001",
                    **bindings,
                )
        self.assertEqual("INTERNAL_ERROR", captured.exception.code)

    def test_cancelled_selection_cannot_prepare(self) -> None:
        flow, search, presentation = self._start_and_search()
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-0003",
            presentation["presentation_id"],
            presentation["presented_version"],
            [],
        )
        self.assertTrue(selection["cancelled"])
        with self.assertRaises(DomainError) as captured:
            self.service.download_prepare(
                flow["flow_id"],
                "prepare-key-000003",
                selection["selection_version"],
            )
        self.assertEqual(captured.exception.code, "RESOURCE_NOT_SELECTED")

    def test_expired_representation_evidence_cannot_create_plan(self) -> None:
        self.service.close()
        self.service = self._build_service(
            inspector=OfflineLandingInspector(
                observed_at="2000-01-01T00:00:00Z",
                expires_at="2000-01-01T01:00:00Z",
            )
        )
        flow, _search, presentation = self._start_and_search()
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-expired-evidence-0001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        with self.assertRaises(DomainError) as captured:
            self.service.download_prepare(
                flow["flow_id"],
                "prepare-expired-evidence-0001",
                selection["selection_version"],
            )
        self.assertEqual("RESOLUTION_STALE", captured.exception.code)
        self.assertIsNone(self.service.flow_status(flow["flow_id"])["current_plan"])

    def test_evidence_expired_after_prepare_cannot_create_job(self) -> None:
        flow, plan = self._prepare_first_candidate()
        resource_id = plan["items"][0]["resource_id"]
        resource = self.service.store.get_resources(flow["flow_id"], [resource_id])[0]
        fingerprint = source_fingerprint(resource)
        resolution = self.service.store.get_resource_resolution(
            flow["flow_id"],
            resource_id,
            INSPECTION_PROFILE_VERSION,
            fingerprint,
        )
        self.assertIsNotNone(resolution)
        assert resolution is not None
        expired = deepcopy(resolution["resolved"])
        evidence = expired["representations"][0]["evidence"]
        evidence["observed_at"] = "2000-01-01T00:00:00Z"
        evidence["expires_at"] = "2000-01-01T01:00:00Z"
        self.service.store.save_resolution(
            flow["flow_id"],
            resource_id,
            INSPECTION_PROFILE_VERSION,
            fingerprint,
            resolution["resolution_status"],
            resolved=expired,
            inspection=resolution["inspection"],
            failures=resolution["failures"],
            idempotency_key="expire-resolution-before-start-0001",
        )
        with self.assertRaises(DomainError) as captured:
            self.service.download_start(
                flow["flow_id"],
                plan["plan_id"],
                plan["confirmation_token"],
                "start-expired-evidence-0001",
                presentation_id=plan["presentation_id"],
                presented_version=plan["presented_version"],
                selection_version=plan["selection_version"],
                selection_digest=plan["selection_digest"],
                plan_digest=plan["plan_digest"],
                authority_digest=plan["authority_digest"],
            )
        self.assertEqual("RESOLUTION_STALE", captured.exception.code)
        self.assertIsNone(self.service.store.get_latest_job_for_flow(flow["flow_id"]))

    def test_running_job_can_be_cancelled_and_assets_are_not_archivable(self) -> None:
        self.service.close()
        self.service = self._build_service(wait_for_cancel=True)
        flow, search, presentation = self._start_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-0004",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = self.service.download_prepare(
            flow["flow_id"], "prepare-key-000004", selection["selection_version"]
        )
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-key-00000004",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
            authority_digest=plan["authority_digest"],
        )
        self.assertTrue(self.fixture_fetcher.started.wait(1))
        cancelled = self.service.job_cancel(
            flow["flow_id"],
            started["job_id"],
            "cancel-key-0000004",
            "用户取消",
        )
        self.assertIn(cancelled["status"], {"cancelling", "cancelled"})
        status = self._wait_terminal(flow["flow_id"], started["job_id"])
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["assets"], [])
        flow_status = self.service.flow_status(flow["flow_id"])
        self.assertEqual(flow_status["current_job"]["asset_ids"], [])


if __name__ == "__main__":
    unittest.main()
