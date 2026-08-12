"""Cross-layer acceptance for authoritative multi-asset bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import (
    DownloadBatchResult,
    DownloadItemFailure,
    DownloadResult,
)
from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.retrieval.registry import (
    build_registry_snapshot,
    canonical_descriptor_digest,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
        max_search_results=20,
        max_workers=2,
        plan_ttl_seconds=60,
    )


class _BundleProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _result(
        path: Path,
        body: bytes,
        media_type: str,
        *,
        role: str,
        required: bool,
        item_key: str,
    ) -> DownloadResult:
        path.write_bytes(body)
        return DownloadResult(
            path,
            len(body),
            media_type,
            hashlib.sha256(body).hexdigest(),
            path.name,
            role=role,
            required=required,
            item_key=item_key,
            metadata={"relation_key": item_key},
        )

    def download(
        self,
        resource,
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadBatchResult:
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "任务已取消")
        variant = str((resource.get("metadata") or {}).get("variant") or "partial")
        if variant == "unknown-error":
            raise DomainError("MATERIALIZER_UNAVAILABLE", "内部物化器不可用")
        if variant == "failed":
            raise DomainError("DOWNLOAD_FAILED", "夹具资源不可用", retryable=True)
        if variant == "raised-cancel":
            raise DomainError("JOB_CANCELLED", "提供方伪造取消")
        if variant == "fabricated-cancel":
            return DownloadBatchResult(
                failures=[
                    DownloadItemFailure(
                        item_key="fabricated:primary",
                        code="JOB_CANCELLED",
                        message="提供方伪造取消",
                        role="primary",
                        required=True,
                        retryable=False,
                    )
                ]
            )
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        prefix = str(resource["resource_id"])[-8:]
        primary = self._result(
            job_dir / f"{prefix}-lesson.mp4",
            b"video-fixture",
            "video/mp4",
            role="primary",
            required=True,
            item_key=f"{prefix}:video",
        )
        attachment = self._result(
            job_dir / f"{prefix}-worksheet.pdf",
            b"%PDF-1.4\nworksheet",
            "application/pdf",
            role="attachment",
            required=False,
            item_key=f"{prefix}:worksheet",
        )
        if variant == "complete":
            return DownloadBatchResult(results=[primary, attachment])
        return DownloadBatchResult(
            results=[primary, attachment],
            failures=[
                DownloadItemFailure(
                    item_key=f"{prefix}:transcript",
                    code="DOWNLOAD_FAILED",
                    message="字幕暂不可用",
                    role="transcript",
                    required=False,
                    retryable=True,
                    details={"attempt": 1},
                )
            ],
        )


class _BundlePrimaryInspector:
    """Offline primary-resource evidence for the direct course fixture."""

    platform_id = "generic"
    inspector_id = "asset-bundle-primary-fixture"
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
                        "kind": "video",
                        "container": "mp4",
                        "mime_type": "video/mp4",
                        "role": "primary",
                        "materializable": True,
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-08T00:00:00Z",
            ),
            failures=[],
        )


class AssetBundleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _capability_snapshot():
        descriptor = {
            "descriptor_id": "cap_asset_bundle_course_primary_mp4_v1",
            "descriptor_version": "1.1.0",
            "descriptor_digest": "",
            "registry_version": "1.1.0",
            "platform_id": "generic",
            "resource_types": ["course"],
            "scope": "primary_resource",
            "representation": {
                "kind": "video",
                "role": "primary",
                "containers": ["mp4"],
                "mime_types": ["video/mp4"],
                "materializable": True,
            },
            "strategy": "direct_file",
            "provider": {
                "provider_id": "generic-direct",
                "version": "1.0.0",
                "scope": "primary_resource",
            },
            "inspector": {
                "inspector_id": "asset-bundle-primary-fixture",
                "version": "1.0.0",
            },
            "prerequisites": {
                "required_fields": [],
                "auth_mode": "none",
                "network_policy": "public_http",
                "max_retries": 0,
                "requires_session": False,
            },
            "policy_class": "asset_bundle_fixture_public_direct",
            "fallback": {
                "allowed": False,
                "max_scope": "primary_resource",
                "allowed_scopes": [],
                "on_errors": [],
                "scope_preserving": True,
            },
            "source": {
                "kind": "deployment",
                "name": "asset-bundle-service-fixture",
                "published_at": "2026-08-09T00:00:00Z",
            },
            "compatibility": {
                "read_min": "1.0.0",
                "write_version": "1.1.0",
                "breaking_major": 1,
            },
            "deprecated": False,
        }
        descriptor["descriptor_digest"] = (
            "sha256:" + canonical_descriptor_digest(descriptor)
        )
        return build_registry_snapshot(
            {
                "$schema": "../schemas/capability-descriptors.schema.json",
                "catalog_version": "1.1.0",
                "registry_version": "1.1.0",
                "descriptors": [descriptor],
            }
        )

    def _service(self, variants: list[str]) -> ResourceService:
        provider = _BundleProvider(self.settings)
        resources = [
            {
                "platform": "generic",
                "title": f"课程夹具 {index}",
                "source_url": f"https://example.com/course/{index}",
                "resource_type": "course",
                "summary": "多资产课程",
                "metadata": {"variant": variant},
            }
            for index, variant in enumerate(variants, 1)
        ]
        return ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(resources),
            download_provider=provider,
            acquisition_router=AcquisitionRouter(
                [
                    ProviderRegistration(
                        provider_id="generic-direct",
                        provider_version="1.0.0",
                        provider=provider,
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                ]
            ),
            capability_registry_snapshot=self._capability_snapshot(),
            inspection_router=InspectionRouter([_BundlePrimaryInspector()]),
        )

    def _run(self, service: ResourceService, count: int) -> tuple[str, dict]:
        flow = service.flow_start(
            "flow-bundle-service-00001",
            {"goal": {"topic": "课程"}, "constraints": []},
        )
        result_set = service.search(
            flow["flow_id"],
            "search-bundle-service-0001",
            [{"platform": "generic", "queries": [{"query": "课程"}]}],
            limit=10,
        )
        selected_candidates = result_set["candidates"][:count]
        for index, candidate in enumerate(selected_candidates, start=1):
            service.inspect(
                flow["flow_id"],
                f"inspect-bundle-service-{index:04d}",
                candidate["resource_id"],
            )
        presentation = service.presentation_save(
            flow["flow_id"],
            result_set["result_set_id"],
            [item["resource_id"] for item in selected_candidates],
            "present-bundle-service-001",
        )
        selection = service.selection_save(
            flow["flow_id"],
            "select-bundle-service-0001",
            presentation["presentation_id"],
            presentation["presented_version"],
            list(range(1, count + 1)),
        )
        plan = service.download_prepare(
            flow["flow_id"],
            "prepare-bundle-service-001",
            selection["selection_version"],
            options={
                "preferred_container": "mp4",
            },
        )
        started = service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-bundle-service-00001",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
        )
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status = service.job_status(flow["flow_id"], started["job_id"])
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                return flow["flow_id"], status
            time.sleep(0.01)
        self.fail("bundle job did not reach a terminal state")

    def test_partial_bundle_projects_relationships_and_archives_a_member(self) -> None:
        service = self._service(["partial"])
        try:
            flow_id, status = self._run(service, 1)
            self.assertEqual("succeeded", status["status"])
            self.assertEqual("partial", status["completion"])
            self.assertEqual(1, status["progress"]["completed_items"])
            self.assertEqual(2, len(status["assets"]))
            self.assertEqual(["primary", "attachment"], [a["role"] for a in status["assets"]])
            self.assertEqual([1, 2], [a["order"] for a in status["assets"]])
            self.assertEqual(1, len({a["bundle_id"] for a in status["assets"]}))
            self.assertEqual("transcript", status["failures"][0]["role"])
            self.assertEqual(3, status["failures"][0]["order"])

            flow_status = service.flow_status(flow_id)
            self.assertEqual("partial", flow_status["current_job"]["completion"])
            self.assertEqual(1, len(flow_status["current_job"]["bundle_ids"]))

            attachment = status["assets"][1]
            archived = service.archive(
                flow_id,
                status["job_id"],
                attachment["asset_id"],
                idempotency_key="archive-bundle-service-001",
                metadata={"title": "课程练习", "tags": ["课程"]},
            )
            self.assertEqual(attachment["bundle_id"], archived["bundle_id"])
            self.assertEqual("attachment", archived["role"])
            library = service.library_search(flow_id, limit=20)
            self.assertEqual(attachment["bundle_id"], library["assets"][0]["bundle_id"])
            self.assertEqual("attachment", library["assets"][0]["role"])
        finally:
            service.close()

    def test_one_failed_resource_keeps_successful_primary_and_partial_job(self) -> None:
        service = self._service(["complete", "failed"])
        try:
            _, status = self._run(service, 2)
            self.assertEqual("succeeded", status["status"])
            self.assertEqual("partial", status["completion"])
            self.assertEqual(2, status["progress"]["completed_items"])
            self.assertEqual(2, len(status["assets"]))
            self.assertEqual(1, len(status["failures"]))
            self.assertEqual("DOWNLOAD_FAILED", status["failures"][0]["code"])
        finally:
            service.close()

    def test_provider_cannot_fabricate_job_cancellation(self) -> None:
        for variant in ("fabricated-cancel", "raised-cancel"):
            with self.subTest(variant=variant):
                service = self._service([variant])
                try:
                    _, status = self._run(service, 1)
                    self.assertEqual("failed", status["status"])
                    self.assertNotEqual("cancelled", status["status"])
                    self.assertEqual("DOWNLOAD_FAILED", status["failures"][0]["code"])
                    persisted = service.store.get_job(status["job_id"])
                    assert persisted is not None
                    self.assertEqual("failed", persisted["status"])
                    with service.store._connect() as connection:
                        rejected = connection.execute(
                            """
                            SELECT COUNT(*) FROM audit_events
                            WHERE action = 'download.provider_cancel_rejected'
                              AND object_id = ?
                            """,
                            (status["job_id"],),
                        ).fetchone()[0]
                    self.assertGreaterEqual(rejected, 1)
                finally:
                    service.close()

    def test_all_failed_resources_produce_no_fake_asset(self) -> None:
        service = self._service(["unknown-error"])
        try:
            _, status = self._run(service, 1)
            self.assertEqual("failed", status["status"])
            self.assertNotIn("completion", status)
            self.assertEqual([], status["assets"])
            self.assertEqual(1, status["progress"]["completed_items"])
            self.assertEqual("DOWNLOAD_FAILED", status["failures"][0]["code"])
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
