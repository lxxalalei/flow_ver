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

from education_resource_mcp.acquisition import AcquisitionRouter
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import (
    DownloadBatchResult,
    DownloadItemFailure,
    DownloadResult,
)
from education_resource_mcp.errors import DomainError
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
        max_download_bytes=1024 * 1024,
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
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadBatchResult:
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "任务已取消")
        variant = str((resource.get("metadata") or {}).get("variant") or "partial")
        if variant == "unknown-error":
            raise DomainError("MATERIALIZER_UNAVAILABLE", "内部物化器不可用")
        if variant == "failed":
            raise DomainError("DOWNLOAD_FAILED", "夹具资源不可用", retryable=True)
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


class AssetBundleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

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
            acquisition_router=AcquisitionRouter(direct_provider=provider),
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
        presentation = service.presentation_save(
            flow["flow_id"],
            result_set["result_set_id"],
            [item["resource_id"] for item in result_set["candidates"][:count]],
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
                "max_bytes_per_resource": 512 * 1024,
            },
        )
        started = service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-bundle-service-00001",
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
