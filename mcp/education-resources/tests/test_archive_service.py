
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
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
from education_resource_mcp.archive import ArchiveFileError, ArchiveFileManager
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService
from education_resource_mcp.storage import Store


class FixedContentDownloader:
    def __init__(
        self,
        jobs_dir: Path,
        *,
        payload: bytes = b"%PDF-1.7\nsame verified learning content",
        media_type: str = "application/pdf",
        extension: str = ".pdf",
    ) -> None:
        self.jobs_dir = jobs_dir
        self.payload = payload
        self.media_type = media_type
        self.extension = extension

    def download(
        self,
        resource: dict,
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        del strategy, cancel_event
        directory = self.jobs_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{resource['resource_id']}{self.extension}"
        path.write_bytes(self.payload)
        return DownloadResult(
            path=path,
            byte_size=len(self.payload),
            media_type=self.media_type,
            sha256=hashlib.sha256(self.payload).hexdigest(),
            filename=path.name,
        )


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


class FailingStageManager(ArchiveFileManager):
    def stage(self, *args, **kwargs):
        raise ArchiveFileError("copy_failed", "injected copy failure")


class FailOnceStageManager(ArchiveFileManager):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failed = False

    def stage(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise ArchiveFileError("copy_failed", "injected one-time failure")
        return super().stage(*args, **kwargs)


class FailReadyOnceStore(Store):
    def __init__(self, database_path: Path) -> None:
        self.fail_ready_once = True
        super().__init__(database_path)

    def mark_archive_ready(self, *args, **kwargs):
        if self.fail_ready_once:
            self.fail_ready_once = False
            raise sqlite3.OperationalError("injected final commit failure")
        return super().mark_archive_ready(*args, **kwargs)


class ArchiveServiceFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.settings = Settings(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=data_dir / "学习资料库",
            max_search_results=20,
            max_workers=2,
            plan_ttl_seconds=60,
        )
        self.resources = [
            {
                "platform": "generic",
                "title": f"太阳系资料 {index}",
                "source_url": f"https://example.com/resource-{index}",
                "resource_type": "document",
                "summary": "太阳系学习资料",
                "metadata": {},
            }
            for index in range(1, 5)
        ]
        self.services: list[ResourceService] = []

    def tearDown(self) -> None:
        for service in self.services:
            service.close()
        self.temp.cleanup()

    def _service(
        self,
        *,
        store: Store | None = None,
        archive_manager: ArchiveFileManager | None = None,
        downloader: FixedContentDownloader | None = None,
    ) -> ResourceService:
        exact_downloader = downloader or FixedContentDownloader(
            self.settings.jobs_dir
        )
        service = ResourceService(
            self.settings,
            store=store,
            search_provider=StaticSearchProvider(self.resources),
            acquisition_router=AcquisitionRouter(
                [
                    ProviderRegistration(
                        provider_id="generic-direct",
                        provider_version="1.0.0",
                        provider=exact_downloader,
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                ]
            ),
            inspection_router=InspectionRouter([OfflineGenericInspector()]),
            archive_file_manager=archive_manager,
        )
        self.services.append(service)
        return service

    def _download(self, service: ResourceService, count: int = 1):
        suffix = len(self.services)
        flow = service.flow_start(
            f"archive-flow-{suffix:08d}",
            {"goal": {"topic": "太阳系"}, "constraints": []},
        )
        search = service.search(
            flow["flow_id"],
            f"archive-search-{suffix:06d}",
            [{"platform": "generic", "queries": [{"query": "太阳系"}]}],
            limit=10,
        )
        ids = [item["resource_id"] for item in search["candidates"][:count]]
        presentation = service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            ids,
            f"archive-present-{suffix:05d}",
        )
        selection = service.selection_save(
            flow["flow_id"],
            f"archive-select-{suffix:06d}",
            presentation["presentation_id"],
            presentation["presented_version"],
            list(range(1, len(ids) + 1)),
        )
        for position, resource_id in enumerate(ids, start=1):
            resolution = service.inspect(
                flow["flow_id"],
                f"archive-inspect-{suffix:05d}-{position:03d}",
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
        plan = service.download_prepare(
            flow["flow_id"],
            f"archive-prepare-{suffix:05d}",
            selection["selection_version"],
            options={"preferred_container": "original"},
        )
        self.assertEqual(len(plan["items"]), len(ids))
        for item in plan["items"]:
            self.assertEqual("primary_resource", item["planned_scope"])
            self.assertEqual("direct_file", item["planned_strategy"])
            self.assertEqual(
                {
                    "provider_id": "generic-direct",
                    "version": "1.0.0",
                    "scope": "primary_resource",
                },
                item["planned_provider"],
            )
        started = service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            f"archive-start-{suffix:07d}",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = service.job_status(flow["flow_id"], started["job_id"])
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        else:
            self.fail("download did not finish")
        self.assertEqual(status["status"], "succeeded")
        return flow, started, status["assets"]

    @staticmethod
    def _classification(domain: str = "natural_science", topic: str = "天文与宇宙"):
        return {
            "classification": {
                "taxonomy_version": "learning-v1",
                "classification_status": "classified",
                "primary_domain": domain,
                "secondary_domains": [],
                "topics": [topic],
                "material_purposes": ["explanation"],
                "grade_levels": [],
                "curriculum_versions": [],
            },
            "tags": ["科普"],
        }

    def test_archive_uses_server_title_source_and_returns_only_relative_path(self) -> None:
        service = self._service()
        flow, job, assets = self._download(service)
        metadata = self._classification()
        metadata.update({"title": "模型伪造标题", "source_name": "模型伪造来源"})
        archived = service.archive(
            flow["flow_id"],
            job["job_id"],
            assets[0]["asset_id"],
            idempotency_key="archive-service-key-0001",
            metadata=metadata,
        )
        self.assertTrue(archived["relative_path"].startswith("04-自然科学/天文与宇宙/图文/"))
        self.assertIn("generic-太阳系资料 1", archived["relative_path"])
        self.assertNotIn("模型伪造", archived["relative_path"])
        self.assertFalse(Path(archived["relative_path"]).is_absolute())
        self.assertTrue((self.settings.library_dir / archived["relative_path"]).is_file())

    def test_archive_fails_closed_for_orphan_and_quarantined_assets(self) -> None:
        service = self._service()
        flow, job, assets = self._download(service)
        asset = service.store.get_asset(assets[0]["asset_id"])
        assert asset is not None
        orphan_asset_id = "asset_orphan_ready_without_bundle"
        with service.store.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO assets(
                    asset_id, job_id, resource_id, status, local_path, byte_size,
                    media_type, sha256, filename, created_at
                ) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?)
                """,
                (
                    orphan_asset_id,
                    asset["job_id"],
                    asset["resource_id"],
                    asset["local_path"],
                    asset["byte_size"],
                    asset["media_type"],
                    asset["sha256"],
                    asset["filename"],
                    asset["created_at"],
                ),
            )

        with self.assertRaises(DomainError) as orphan_error:
            service.archive(
                flow["flow_id"],
                job["job_id"],
                orphan_asset_id,
                idempotency_key="archive-orphan-reject-001",
                metadata=self._classification(),
            )
        self.assertEqual("ASSET_NOT_ARCHIVABLE", orphan_error.exception.code)
        with self.assertRaisesRegex(ValueError, "asset_not_archivable"):
            service.store.reserve_archive(
                orphan_asset_id,
                self._classification(),
                "04-自然科学/天文与宇宙/图文/orphan.pdf",
            )

        with service.store.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE assets SET status = 'quarantined' WHERE asset_id = ?",
                (asset["asset_id"],),
            )
        with self.assertRaises(DomainError) as quarantined_error:
            service.archive(
                flow["flow_id"],
                job["job_id"],
                asset["asset_id"],
                idempotency_key="archive-quarantine-reject-001",
                metadata=self._classification(),
            )
        self.assertEqual("ASSET_NOT_ARCHIVABLE", quarantined_error.exception.code)
        with service.store._connect() as connection:
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM archive_entries").fetchone()[0],
            )

    def test_archive_requires_exact_job_execution_authority(self) -> None:
        service = self._service()
        flow, job, assets = self._download(service)
        asset_id = assets[0]["asset_id"]
        with service.store.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM job_items WHERE job_id = ?",
                (job["job_id"],),
            )

        with self.assertRaises(DomainError) as captured:
            service.archive(
                flow["flow_id"],
                job["job_id"],
                asset_id,
                idempotency_key="archive-authority-reject-001",
                metadata=self._classification(),
            )
        self.assertEqual("ASSET_NOT_ARCHIVABLE", captured.exception.code)
        with service.store._connect() as connection:
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM archive_entries").fetchone()[0],
            )

    def test_different_assets_with_same_content_share_one_file_and_remain_traceable(self) -> None:
        service = self._service()
        flow, job, assets = self._download(service, count=2)
        first = service.archive(
            flow["flow_id"], job["job_id"], assets[0]["asset_id"],
            idempotency_key="archive-dedup-key-00001", metadata=self._classification(),
        )
        second = service.archive(
            flow["flow_id"], job["job_id"], assets[1]["asset_id"],
            idempotency_key="archive-dedup-key-00002", metadata=self._classification(),
        )
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(first["relative_path"], second["relative_path"])
        files = [
            path for path in self.settings.library_dir.rglob("*")
            if path.is_file() and ".archive-staging" not in path.parts
        ]
        self.assertEqual(len(files), 1)
        library = service.library_search(
            flow["flow_id"], filters={"primary_domains": ["natural_science"]}, limit=20
        )
        self.assertEqual({item["asset_id"] for item in library["assets"]}, {item["asset_id"] for item in assets[:2]})

    def test_precise_filters_and_signed_cursor_have_no_duplicates(self) -> None:
        service = self._service()
        flow, job, assets = self._download(service, count=3)
        domains = ["natural_science", "mathematics_reasoning", "natural_science"]
        topics = ["天文", "天文馆", "太阳系"]
        for index, asset in enumerate(assets):
            service.archive(
                flow["flow_id"], job["job_id"], asset["asset_id"],
                idempotency_key=f"archive-page-key-{index:05d}",
                metadata=self._classification(domains[index], topics[index]),
            )
        exact = service.library_search(
            flow["flow_id"], filters={"topics": ["天文"]}, limit=20
        )
        self.assertEqual(len(exact["assets"]), 1)
        seen: list[str] = []
        cursor = None
        while True:
            page = service.library_search(
                flow["flow_id"], filters={}, cursor=cursor, limit=1
            )
            seen.extend(item["archive_id"] for item in page["assets"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        self.assertEqual(len(seen), 3)
        self.assertEqual(len(set(seen)), 3)
        with self.assertRaises(DomainError):
            service.library_search(
                flow["flow_id"],
                filters={"primary_domains": ["natural_science"]},
                cursor=cursor,
                limit=1,
            )

    def test_copy_failure_never_creates_ready_index(self) -> None:
        manager = FailingStageManager(self.settings.library_dir)
        service = self._service(archive_manager=manager)
        flow, job, assets = self._download(service)
        with self.assertRaises(DomainError) as captured:
            service.archive(
                flow["flow_id"], job["job_id"], assets[0]["asset_id"],
                idempotency_key="archive-copy-fail-0001", metadata=self._classification(),
            )
        self.assertEqual(captured.exception.code, "STORAGE_UNAVAILABLE")
        entry = service.store.get_archive_for_asset(assets[0]["asset_id"])
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(service.library_search(flow["flow_id"], filters={}, limit=20)["assets"], [])

    def test_failed_archive_retries_with_same_idempotency_key(self) -> None:
        manager = FailOnceStageManager(self.settings.library_dir)
        service = self._service(archive_manager=manager)
        flow, job, assets = self._download(service)
        key = "archive-retry-key-0001"
        with self.assertRaises(DomainError):
            service.archive(
                flow["flow_id"], job["job_id"], assets[0]["asset_id"],
                idempotency_key=key, metadata=self._classification(),
            )
        replay = service.archive(
            flow["flow_id"], job["job_id"], assets[0]["asset_id"],
            idempotency_key=key, metadata=self._classification(),
        )
        self.assertEqual(replay["archive_status"], "ready")
        self.assertTrue((self.settings.library_dir / replay["relative_path"]).is_file())

    def test_database_final_commit_failure_is_recovered_from_pending(self) -> None:
        failing_store = FailReadyOnceStore(self.settings.database_path)
        service = self._service(store=failing_store)
        flow, job, assets = self._download(service)
        key = "archive-db-fail-key-001"
        with self.assertRaises(DomainError) as captured:
            service.archive(
                flow["flow_id"], job["job_id"], assets[0]["asset_id"],
                idempotency_key=key, metadata=self._classification(),
            )
        self.assertEqual(captured.exception.code, "STORAGE_UNAVAILABLE")
        pending = service.store.get_archive_for_asset(assets[0]["asset_id"])
        self.assertEqual(pending["status"], "pending")

        recovered = self._service(store=Store(self.settings.database_path))
        ready = recovered.store.get_archive_for_asset(assets[0]["asset_id"])
        self.assertEqual(ready["status"], "ready")
        replay = recovered.archive(
            flow["flow_id"], job["job_id"], assets[0]["asset_id"],
            idempotency_key=key, metadata=self._classification(),
        )
        self.assertEqual(replay["archive_status"], "ready")
        self.assertEqual(len(recovered.library_search(flow["flow_id"], filters={}, limit=20)["assets"]), 1)

    def test_legacy_absolute_archive_is_read_without_moving_or_exposing_its_path(self) -> None:
        service = self._service()
        flow, _job, assets = self._download(service)
        asset = service.store.get_asset(assets[0]["asset_id"])
        assert asset is not None
        legacy_root = self.settings.data_dir / "library"
        legacy_root.mkdir()
        legacy_file = legacy_root / "legacy.pdf"
        legacy_file.write_bytes(Path(asset["local_path"]).read_bytes())
        archive_id = "archive_legacy_absolute"
        content_id = "content_legacy_absolute"
        archived_at = str(asset["created_at"])
        legacy_metadata = {
            "primary_domain": "自然科学",
            "topics": ["天文与宇宙"],
            "tags": ["旧数据"],
        }
        with service.store.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO archive_contents(
                    content_id, sha256, byte_size, media_type, resource_format,
                    relative_path, status, owner_archive_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'document', NULL, 'ready', ?, ?, ?)
                """,
                (
                    content_id,
                    asset["sha256"],
                    asset["byte_size"],
                    asset["media_type"],
                    archive_id,
                    archived_at,
                    archived_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO archive_entries(
                    archive_id, asset_id, library_path, metadata_json, created_at,
                    content_id, status, taxonomy_version, classification_status,
                    primary_domain, primary_topic, legacy_metadata_json,
                    archived_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready', 'learning-v1', 'classified',
                          'natural_science', '天文与宇宙', ?, ?, ?)
                """,
                (
                    archive_id,
                    asset["asset_id"],
                    str(legacy_file),
                    json.dumps(legacy_metadata, ensure_ascii=False),
                    archived_at,
                    content_id,
                    json.dumps(legacy_metadata, ensure_ascii=False),
                    archived_at,
                    archived_at,
                ),
            )
            connection.execute(
                "INSERT INTO archive_topics(archive_id, value, position) VALUES (?, ?, 0)",
                (archive_id, "天文与宇宙"),
            )
            connection.execute(
                "INSERT INTO archive_tags(archive_id, value, position) VALUES (?, ?, 0)",
                (archive_id, "旧数据"),
            )

        legacy_settings = Settings(
            data_dir=self.settings.data_dir,
            database_path=self.settings.database_path,
            jobs_dir=self.settings.jobs_dir,
            library_dir=self.settings.library_dir,
            max_search_results=self.settings.max_search_results,
            max_workers=1,
            plan_ttl_seconds=60,
            legacy_library_dirs=(legacy_root,),
        )
        recovered = ResourceService(
            legacy_settings,
            store=Store(legacy_settings.database_path),
            search_provider=StaticSearchProvider(self.resources),
            acquisition_router=AcquisitionRouter(
                [
                    ProviderRegistration(
                        provider_id="generic-direct",
                        provider_version="1.0.0",
                        provider=FixedContentDownloader(legacy_settings.jobs_dir),
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                ]
            ),
            inspection_router=InspectionRouter([OfflineGenericInspector()]),
        )
        self.services.append(recovered)
        library = recovered.library_search(
            flow["flow_id"], filters={"primary_domains": ["natural_science"]}, limit=20
        )
        self.assertEqual(len(library["assets"]), 1)
        public = library["assets"][0]
        self.assertEqual(public["classification"]["primary_domain"], "natural_science")
        self.assertNotIn("relative_path", public)
        self.assertNotIn("library_path", public)
        self.assertTrue(legacy_file.exists())

    def test_deployed_flat_metadata_idempotency_hash_remains_replayable(self) -> None:
        service = self._service()
        flow, job, assets = self._download(service)
        metadata = {
            "primary_domain": "自然科学",
            "topics": ["天文与宇宙"],
            "title": "旧客户端标题",
            "tags": ["旧客户端"],
        }
        key = "archive-legacy-idem-001"
        archived = service.archive(
            flow["flow_id"], job["job_id"], assets[0]["asset_id"],
            idempotency_key=key, metadata=metadata,
        )
        legacy_hash = service._request_hash(
            {
                "flow_id": flow["flow_id"],
                "job_id": job["job_id"],
                "asset_id": assets[0]["asset_id"],
                "metadata": metadata,
            }
        )
        legacy_result = {
            key: value
            for key, value in archived.items()
            if key not in {"archive_id", "archive_status", "classification", "primary_domain_display_name", "relative_path"}
        }
        with service.store.transaction() as connection:
            connection.execute(
                """
                UPDATE idempotency_keys SET request_hash = ?, result_json = ?
                WHERE scope = ? AND key = ?
                """,
                (
                    legacy_hash,
                    json.dumps(legacy_result, ensure_ascii=False),
                    f"resource_archive:{flow['flow_id']}",
                    key,
                ),
            )
        replay = service.archive(
            flow["flow_id"], job["job_id"], assets[0]["asset_id"],
            idempotency_key=key, metadata=metadata,
        )
        self.assertEqual(replay["archive_status"], "ready")
        self.assertEqual(replay["asset_id"], assets[0]["asset_id"])


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
