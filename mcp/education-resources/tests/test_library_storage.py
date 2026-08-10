from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import Store


NOW = "2026-01-01T00:00:00+00:00"


class LibraryStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "database.sqlite")
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO flows(
                    flow_id, query, context_json, status, presented_version,
                    task_version, result_version, selection_version, created_at, updated_at
                ) VALUES ('flow_test', '资料', '{}', 'downloaded', 1, 1, 1, 1, ?, ?)
                """,
                (NOW, NOW),
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_asset(
        self,
        suffix: str,
        *,
        sha256: str,
        byte_size: int = 100,
        platform: str = "generic",
        resource_type: str = "document",
        title: str | None = None,
    ) -> str:
        resource_id = f"res_{suffix}"
        plan_id = f"plan_{suffix}"
        job_id = f"job_{suffix}"
        snapshot_id = f"readiness_{suffix}"
        eligibility_id = f"eligibility_{suffix}"
        representation_id = f"representation_{suffix}"
        capability_id = f"capability_{suffix}"
        authority_digest = "sha256:" + hashlib.sha256(
            f"library-authority:{suffix}".encode("utf-8")
        ).hexdigest()
        plan_binding_digest = hashlib.sha256(
            f"library-plan:{suffix}".encode("utf-8")
        ).hexdigest()
        execution_binding_digest = hashlib.sha256(
            f"library-execution:{suffix}".encode("utf-8")
        ).hexdigest()
        filename = f"{suffix}.mp4" if resource_type == "video" else f"{suffix}.pdf"
        media_type = "video/mp4" if resource_type == "video" else "application/pdf"
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO resources(
                    resource_id, flow_id, presented_version, platform, title, source_url,
                    resource_type, summary, metadata_json, created_at, result_position
                ) VALUES (?, 'flow_test', 1, ?, ?, ?, ?, NULL, '{}', ?, 1)
                """,
                (
                    resource_id,
                    platform,
                    title or suffix,
                    f"https://example.com/{suffix}",
                    resource_type,
                    NOW,
                ),
            )
            connection.execute(
                """
                INSERT INTO download_plans(
                    plan_id, flow_id, presented_version, resource_ids_json, options_json,
                    confirmation_token, confirmation_hash, expires_at, used, created_at,
                    selection_version, selection_digest, plan_digest
                ) VALUES (?, 'flow_test', 1, ?, '{}', 'token', 'hash', ?, 1, ?, 1, ?, ?)
                """,
                (
                    plan_id,
                    json.dumps([resource_id]),
                    "2099-01-01T00:00:00+00:00",
                    NOW,
                    plan_binding_digest,
                    plan_binding_digest,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, flow_id, plan_id, status, progress, asset_ids_json,
                    created_at, updated_at
                ) VALUES (?, 'flow_test', ?, 'running', 0, '[]', ?, ?)
                """,
                (job_id, plan_id, NOW, NOW),
            )
            connection.execute(
                """
                INSERT INTO capability_readiness_snapshots(
                    snapshot_id, capability_id, descriptor_version,
                    descriptor_digest, registry_version, registry_digest,
                    platform_id, capability_scope, strategy, provider_id,
                    provider_version, inspector_id, inspector_version, status,
                    issues_json, observed_at, expires_at, snapshot_digest
                ) VALUES (?, ?, '1.0.0', ?, '1.0.0', ?, ?,
                          'primary_resource', 'direct_file', 'generic-direct',
                          '1.0.0', 'generic', '1.0.0', 'ready', '[]', ?, ?, ?)
                """,
                (
                    snapshot_id,
                    capability_id,
                    authority_digest,
                    authority_digest,
                    platform,
                    NOW,
                    "2099-01-01T00:00:00+00:00",
                    authority_digest,
                ),
            )
            connection.execute(
                """
                INSERT INTO eligibility_decisions(
                    eligibility_id, flow_id, resource_id, resolution_id,
                    representation_id, action, status, policy_class,
                    reason_codes_json, source_fingerprint, capability_id,
                    descriptor_digest, readiness_snapshot_id, evaluated_at,
                    expires_at, decision_digest
                ) VALUES (?, 'flow_test', ?, NULL, ?, 'download', 'eligible',
                          'public', '[]', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eligibility_id,
                    resource_id,
                    representation_id,
                    authority_digest,
                    capability_id,
                    authority_digest,
                    snapshot_id,
                    NOW,
                    "2099-01-01T00:00:00+00:00",
                    authority_digest,
                ),
            )
            common = (
                plan_id,
                resource_id,
                representation_id,
                capability_id,
                authority_digest,
                authority_digest,
                snapshot_id,
                authority_digest,
                eligibility_id,
                authority_digest,
                authority_digest,
                json.dumps({"scope": "primary_resource"}),
            )
            connection.execute(
                """
                INSERT INTO download_plan_items(
                    plan_id, position, resource_id, resolution_id,
                    representation_id, capability_scope, strategy, provider_id,
                    provider_version, capability_id, descriptor_version,
                    descriptor_digest, registry_version, registry_digest,
                    readiness_snapshot_id, readiness_digest, eligibility_id,
                    eligibility_digest, source_fingerprint, representation_json,
                    binding_digest
                ) VALUES (?, 0, ?, NULL, ?, 'primary_resource', 'direct_file',
                          'generic-direct', '1.0.0', ?, '1.0.0', ?, '1.0.0', ?,
                          ?, ?, ?, ?, ?, ?, ?)
                """,
                (*common, plan_binding_digest),
            )
            connection.execute(
                """
                INSERT INTO job_execution_items(
                    job_id, plan_id, position, resource_id, resolution_id,
                    representation_id, capability_scope, strategy, provider_id,
                    provider_version, capability_id, descriptor_version,
                    descriptor_digest, registry_version, registry_digest,
                    readiness_snapshot_id, readiness_digest, eligibility_id,
                    eligibility_digest, source_fingerprint, representation_json,
                    plan_binding_digest, execution_binding_digest, revalidated_at
                ) VALUES (?, ?, 0, ?, NULL, ?, 'primary_resource', 'direct_file',
                          'generic-direct', '1.0.0', ?, '1.0.0', ?, '1.0.0', ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    *common,
                    plan_binding_digest,
                    execution_binding_digest,
                    NOW,
                ),
            )

        outcome_metadata = {"fixture": "library-storage"}
        self.store.start_acquisition_outcome(
            job_id, resource_id, metadata=outcome_metadata
        )
        bundle = self.store.persist_asset_bundle(
            job_id,
            resource_id,
            [
                {
                    "role": "primary",
                    "position": 0,
                    "status": "ready",
                    "required": True,
                    "metadata": {},
                    "local_path": f"/internal/jobs/{job_id}/{filename}",
                    "byte_size": byte_size,
                    "media_type": media_type,
                    "sha256": sha256,
                    "filename": filename,
                }
            ],
        )
        asset_id = str(bundle["items"][0]["asset_id"])
        self.store.complete_acquisition_outcome(
            job_id,
            resource_id,
            status="succeeded",
            actual_scope="primary_resource",
            actual_strategy="direct_file",
            actual_provider_id="generic-direct",
            actual_provider_version="1.0.0",
            bundle_id=str(bundle["bundle_id"]),
            asset_ids=[asset_id],
            metadata=outcome_metadata,
        )
        self.store.finalize_job_success(job_id)
        return asset_id

    @staticmethod
    def metadata(
        domain: str,
        topics: list[str],
        *,
        secondary: list[str] | None = None,
        purposes: list[str] | None = None,
        grade_levels: list[str] | None = None,
        difficulty: str | None = None,
        curriculum_versions: list[str] | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        notes: str = "",
    ) -> dict:
        return {
            "classification": {
                "taxonomy_version": "learning-v1",
                "classification_status": "classified",
                "primary_domain": domain,
                "secondary_domains": secondary or [],
                "topics": topics,
                "material_purposes": purposes or [],
                "grade_levels": grade_levels or [],
                "difficulty": difficulty,
                "curriculum_versions": curriculum_versions or [],
            },
            "collection": collection,
            "tags": tags or [],
            "notes": notes,
        }

    def reserve_ready(
        self,
        asset_id: str,
        metadata: dict,
        relative_path: str,
        *,
        resource_format: str = "document",
    ) -> dict:
        reservation = self.store.reserve_archive(asset_id, metadata, relative_path)
        self.store.mark_archive_ready(
            reservation["archive_id"],
            relative_path=relative_path,
            resource_format=resource_format,
            flow_id="flow_test",
        )
        return reservation

    def test_content_dedup_links_distinct_assets_without_duplicate_content(self) -> None:
        first_asset = self.add_asset("first", sha256="a" * 64)
        second_asset = self.add_asset("second", sha256="a" * 64)
        metadata = self.metadata("natural_science", ["天文与宇宙"], tags=["科普"])

        first = self.reserve_ready(first_asset, metadata, "04-自然科学/天文与宇宙/图文/first.pdf")
        second = self.store.reserve_archive(
            second_asset, metadata, "04-自然科学/天文与宇宙/图文/second.pdf"
        )

        self.assertTrue(first["owns_content"])
        self.assertFalse(second["owns_content"])
        self.assertTrue(second["deduplicated_candidate"])
        self.assertEqual(first["content_id"], second["content_id"])
        self.store.mark_archive_ready(second["archive_id"], flow_id="flow_test")
        with self.store._connect() as connection:
            self.assertEqual(
                1, connection.execute("SELECT COUNT(*) FROM archive_contents").fetchone()[0]
            )
            self.assertEqual(
                2, connection.execute("SELECT COUNT(*) FROM archive_entries").fetchone()[0]
            )

    def test_reservation_replays_real_state_and_rejects_metadata_conflict(self) -> None:
        asset_id = self.add_asset("pending", sha256="b" * 64)
        metadata = self.metadata("mathematics_reasoning", ["应用题"])
        first = self.store.reserve_archive(
            asset_id,
            metadata,
            "02-数学与思维/应用题/图文/pending.pdf",
            idempotency_scope="resource_archive:flow_test",
            idempotency_key="archive-key-000001",
            request_hash="request-one",
        )
        replay = self.store.reserve_archive(
            asset_id,
            metadata,
            "02-数学与思维/应用题/图文/pending.pdf",
            idempotency_scope="resource_archive:flow_test",
            idempotency_key="archive-key-000001",
            request_hash="request-one",
        )
        self.assertEqual("pending", replay["status"])
        self.assertTrue(replay["replayed"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.store.reserve_archive(
                asset_id,
                metadata,
                "02-数学与思维/应用题/图文/pending.pdf",
                idempotency_scope="resource_archive:flow_test",
                idempotency_key="archive-key-000001",
                request_hash="different-request",
            )
        with self.assertRaisesRegex(ValueError, "archive_metadata_conflict"):
            self.store.reserve_archive(
                asset_id,
                self.metadata("natural_science", ["其他"]),
                "04-自然科学/其他/图文/pending.pdf",
            )
        self.store.mark_archive_failed(first["archive_id"], {"code": "COPY_FAILED"})
        item = self.store.list_archive_reconciliation_items(("failed",))[0]
        self.assertEqual("failed", item["status"])
        self.assertEqual("failed", item["content_status"])
        retried = self.store.retry_archive_reservation(first["archive_id"])
        self.assertEqual(first["archive_id"], retried["archive_id"])
        self.assertEqual(first["content_id"], retried["content_id"])
        self.assertEqual("pending", retried["status"])
        self.assertTrue(retried["retried"])
        self.assertEqual(
            "pending",
            self.store.get_idempotency(
                "resource_archive:flow_test", "archive-key-000001"
            )["result"]["status"],
        )
        with self.assertRaisesRegex(ValueError, "archive_retry_not_allowed"):
            self.store.retry_archive_reservation(first["archive_id"])

    def test_finalize_commits_ready_audit_and_idempotency_result_together(self) -> None:
        asset_id = self.add_asset("finalize", sha256="9" * 64)
        reservation = self.store.reserve_archive(
            asset_id,
            self.metadata("natural_science", ["科学实验"]),
            "04-自然科学/科学实验/图文/finalize.pdf",
            idempotency_scope="resource_archive:flow_test",
            idempotency_key="archive-finalize-key-01",
            request_hash="finalize-request",
        )
        result = {"archive_status": "ready", "archive_id": reservation["archive_id"]}
        ready = self.store.mark_archive_ready(
            reservation["archive_id"],
            resource_format="document",
            flow_id="flow_test",
            result=result,
        )

        self.assertEqual("ready", ready["status"])
        self.assertEqual(
            result,
            self.store.get_idempotency(
                "resource_archive:flow_test", "archive-finalize-key-01"
            )["result"],
        )
        with self.store._connect() as connection:
            audit = connection.execute(
                "SELECT action, object_id FROM audit_events WHERE object_id = ?",
                (reservation["archive_id"],),
            ).fetchone()
        self.assertEqual(("asset.archive", reservation["archive_id"]), tuple(audit))

    def test_exact_filters_use_or_within_field_and_and_across_fields(self) -> None:
        science = self.add_asset(
            "science", sha256="c" * 64, platform="bilibili", resource_type="video", title="太阳系动画"
        )
        math = self.add_asset(
            "math", sha256="d" * 64, platform="generic", title="分数练习"
        )
        self.reserve_ready(
            science,
            self.metadata(
                "natural_science",
                ["天文与宇宙", "太阳系"],
                secondary=["information_technology"],
                purposes=["explanation"],
                grade_levels=["小学"],
                difficulty="introductory",
                curriculum_versions=["通用版"],
                collection="太阳系专题",
                tags=["科普", "动画"],
            ),
            "04-自然科学/天文与宇宙/视频/science.mp4",
            resource_format="video",
        )
        self.reserve_ready(
            math,
            self.metadata(
                "mathematics_reasoning", ["应用题"], purposes=["practice"], tags=["练习"]
            ),
            "02-数学与思维/应用题/图文/math.pdf",
        )

        topic_or = self.store.search_library(None, 20, {"topics": ["太阳系", "应用题"]})
        self.assertEqual(2, len(topic_or["items"]))
        combined = self.store.search_library(
            None,
            20,
            {
                "primary_domains": ["natural_science"],
                "topics": ["太阳系", "应用题"],
                "secondary_domains": ["information_technology"],
                "material_purposes": ["explanation"],
                "grade_levels": ["小学"],
                "difficulties": ["introductory"],
                "curriculum_versions": ["通用版"],
                "taxonomy_versions": ["learning-v1"],
                "classification_statuses": ["classified"],
                "resource_formats": ["video"],
                "platforms": ["bilibili"],
                "resource_types": ["video"],
                "collections": ["太阳系专题"],
                "tags": ["动画", "不存在的另一个可选值"],
                "archived_after": "2025-01-01T00:00:00+00:00",
                "archived_before": "2027-01-01T08:00:00+08:00",
            },
        )
        self.assertEqual([science], [item["asset_id"] for item in combined["items"]])
        substring = self.store.search_library(
            None, 20, {"primary_domains": ["science"]}
        )
        self.assertEqual([], substring["items"])
        self.assertEqual(
            ["04-自然科学/天文与宇宙/视频/science.mp4"],
            [item["relative_path"] for item in combined["items"]],
        )
        self.assertEqual(
            combined["items"][0]["relative_path"], combined["items"][0]["library_path"]
        )

    def test_ready_only_and_keyset_pagination_have_no_repeat(self) -> None:
        ready_assets: list[str] = []
        for index, char in enumerate(("e", "f", "1"), start=1):
            asset_id = self.add_asset(f"page{index}", sha256=char * 64)
            ready_assets.append(asset_id)
            self.reserve_ready(
                asset_id,
                self.metadata("learning_skills", ["信息检索"]),
                f"09-学习方法与通用能力/信息检索/图文/{index}.pdf",
            )
        pending_asset = self.add_asset("notready", sha256="2" * 64)
        self.store.reserve_archive(
            pending_asset,
            self.metadata("learning_skills", ["信息检索"]),
            "09-学习方法与通用能力/信息检索/图文/pending.pdf",
        )
        with self.store.transaction() as connection:
            connection.execute("UPDATE archive_entries SET archived_at = ?", (NOW,))

        first = self.store.search_library(None, 2)
        second = self.store.search_library(None, 2, cursor=first["next_keyset"])
        first_ids = [item["asset_id"] for item in first["items"]]
        second_ids = [item["asset_id"] for item in second["items"]]
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(3, len(first_ids + second_ids))
        self.assertEqual(3, len(set(first_ids + second_ids)))
        self.assertNotIn(pending_asset, first_ids + second_ids)

    def test_missing_or_corrupt_content_is_removed_from_search(self) -> None:
        asset_id = self.add_asset("missing", sha256="3" * 64)
        reservation = self.reserve_ready(
            asset_id,
            self.metadata("natural_science", ["其他"]),
            "04-自然科学/其他/图文/missing.pdf",
        )
        self.assertEqual(1, len(self.store.search_library(None, 20)["items"]))
        self.store.mark_archive_missing(reservation["archive_id"], {"code": "FILE_MISSING"})
        self.assertEqual([], self.store.search_library(None, 20)["items"])


if __name__ == "__main__":
    unittest.main()
