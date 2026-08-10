from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import Store


NOW = "2026-01-01T00:00:00+00:00"


class AssetBundleStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "database.sqlite"
        self.store = Store(self.database)
        self._insert_flow()
        self._insert_resource("resource_a")
        self._insert_job("job_a", "plan_a", "resource_a")
        self._insert_resource("resource_b")
        self._insert_job("job_b", "plan_b", "resource_b")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _insert_flow(self) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO flows(
                    flow_id, query, context_json, status, presented_version,
                    task_version, result_version, selection_version, created_at, updated_at
                ) VALUES ('flow_a', '资料', '{}', 'downloading', 1, 1, 1, 1, ?, ?)
                """,
                (NOW, NOW),
            )

    def _insert_job(self, job_id: str, plan_id: str, resource_id: str) -> None:
        marker = "a" if job_id.endswith("a") else "b"
        canonical = "sha256:" + marker * 64
        snapshot_id = f"readiness_{job_id}"
        eligibility_id = f"eligibility_{job_id}"
        representation_id = f"representation_{job_id}"
        capability_id = f"capability_{job_id}"
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO download_plans(
                    plan_id, flow_id, presented_version, resource_ids_json, options_json,
                    confirmation_token, confirmation_hash, expires_at, used, created_at,
                    selection_version, selection_digest, plan_digest
                ) VALUES (?, 'flow_a', 1, ?, '{}', 'token', 'hash', ?, 1, ?, 1, 'selection', 'plan')
                """,
                (
                    plan_id,
                    json.dumps([resource_id]),
                    "2099-01-01T00:00:00+00:00",
                    NOW,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, flow_id, plan_id, status, progress, asset_ids_json,
                    created_at, updated_at
                ) VALUES (?, 'flow_a', ?, 'running', 0, '[]', ?, ?)
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
                ) VALUES (?, ?, '1.0.0', ?, '1.0.0', ?, 'generic',
                          'primary_resource', 'direct_file', 'generic-direct',
                          '1.0.0', 'generic', '1.0.0', 'ready', '[]', ?, ?, ?)
                """,
                (
                    snapshot_id,
                    capability_id,
                    canonical,
                    canonical,
                    NOW,
                    "2099-01-01T00:00:00+00:00",
                    canonical,
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
                ) VALUES (?, 'flow_a', ?, NULL, ?, 'download', 'eligible',
                          'public', '[]', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eligibility_id,
                    resource_id,
                    representation_id,
                    canonical,
                    capability_id,
                    canonical,
                    snapshot_id,
                    NOW,
                    "2099-01-01T00:00:00+00:00",
                    canonical,
                ),
            )
            common = (
                plan_id,
                resource_id,
                representation_id,
                capability_id,
                canonical,
                canonical,
                snapshot_id,
                canonical,
                eligibility_id,
                canonical,
                canonical,
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
                (*common, marker * 64),
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
                    marker * 64,
                    ("c" if marker == "a" else "d") * 64,
                    NOW,
                ),
            )
        self.store.start_acquisition_outcome(
            job_id, resource_id, metadata={"attempt": 1}
        )

    def _insert_resource(self, resource_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO resources(
                    resource_id, flow_id, presented_version, platform, title,
                    source_url, resource_type, summary, metadata_json, created_at
                ) VALUES (?, 'flow_a', 1, 'generic', ?, ?, 'video', NULL, '{}', ?)
                """,
                (resource_id, resource_id, f"https://example.com/{resource_id}", NOW),
            )

    def _complete_outcome(self, job_id: str, resource_id: str, bundle: dict) -> dict:
        ready_asset_ids = [
            str(item["asset_id"])
            for item in bundle["items"]
            if item["status"] == "ready" and item.get("asset_id")
        ]
        return self.store.complete_acquisition_outcome(
            job_id,
            resource_id,
            status="succeeded" if bundle["status"] == "succeeded" else "partial",
            actual_scope="primary_resource",
            actual_strategy="direct_file",
            actual_provider_id="generic-direct",
            actual_provider_version="1.0.0",
            bundle_id=str(bundle["bundle_id"]),
            asset_ids=ready_asset_ids,
            metadata={"attempt": 1},
        )

    @staticmethod
    def item(
        role: str,
        position: int,
        *,
        filename: str | None = None,
        sha256: str | None = None,
        status: str = "ready",
        required: bool | None = None,
        metadata: dict | None = None,
    ) -> dict:
        result = {
            "role": role,
            "position": position,
            "status": status,
            "required": required if required is not None else role == "primary",
            "metadata": metadata or {},
        }
        if status == "ready":
            result.update(
                {
                    "local_path": f"/controlled/{filename or f'{position}.bin'}",
                    "byte_size": position + 1,
                    "media_type": "application/octet-stream",
                    "sha256": sha256 or (chr(ord("a") + position) * 64),
                    "filename": filename or f"{position}.bin",
                }
            )
        return result

    def test_persist_bundle_generates_ids_and_updates_job_atomically(self) -> None:
        bundle = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [
                self.item("primary", 0, filename="lesson.mp4"),
                self.item("subtitle", 1, filename="lesson.srt"),
            ],
        )

        self.assertTrue(bundle["bundle_id"].startswith("bundle_"))
        self.assertEqual("succeeded", bundle["status"])
        self.assertEqual("complete", bundle["completion"])
        self.assertEqual(["primary", "subtitle"], [item["role"] for item in bundle["items"]])
        self.assertTrue(all(item["asset_id"].startswith("asset_") for item in bundle["items"]))
        job = self.store.get_job("job_a")
        assert job is not None
        self.assertEqual([item["asset_id"] for item in bundle["items"]], job["asset_ids"])
        self.assertEqual(
            bundle["bundle_id"],
            self.store.get_asset_bundle_for_asset(bundle["items"][0]["asset_id"])["bundle_id"],
        )
        self.assertEqual([bundle["bundle_id"]], [item["bundle_id"] for item in self.store.get_asset_bundles_for_job("job_a")])

    def test_replay_is_idempotent_and_partial_bundle_can_reopen(self) -> None:
        specs = [self.item("primary", 0, filename="lesson.pdf")]
        first = self.store.persist_asset_bundle("job_a", "resource_a", specs)
        replay = self.store.persist_asset_bundle("job_a", "resource_a", specs)
        self.assertEqual(first["bundle_id"], replay["bundle_id"])
        with self.store._connect() as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM asset_bundles").fetchone()[0])

        partial = self.store.persist_asset_bundle(
            "job_b",
            "resource_b",
            [
                self.item("primary", 0, filename="lesson.mp4"),
                self.item("subtitle", 1, status="failed"),
            ],
            failures={
                "position": 1,
                "code": "SUBTITLE_UNAVAILABLE",
                "message": "字幕源暂时不可用",
            },
            completion="partial",
        )
        primary_id = partial["items"][0]["asset_id"]
        reopened = self.store.persist_asset_bundle(
            "job_b",
            "resource_b",
            [
                {
                    "role": "primary",
                    "position": 0,
                    "status": "ready",
                    "required": True,
                    "asset_id": primary_id,
                },
                self.item("subtitle", 1, filename="lesson.srt"),
            ],
        )
        self.assertEqual(partial["bundle_id"], reopened["bundle_id"])
        self.assertEqual("succeeded", reopened["status"])
        self.assertEqual("complete", reopened["completion"])
        self.assertEqual([], reopened["failures"])
        self.assertEqual(2, len(reopened["items"]))

    def test_partial_bundle_reopen_reuses_bundle_and_promotes_existing_primary(self) -> None:
        partial = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [self.item("primary", 0), self.item("subtitle", 1, status="failed")],
            failures=[
                {"position": 1, "code": "SUBTITLE_MISSING", "message": "字幕缺失"}
            ],
            completion="partial",
        )
        primary_asset_id = partial["items"][0]["asset_id"]
        completed = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [
                {"role": "primary", "position": 0, "status": "ready", "asset_id": primary_asset_id},
                self.item("subtitle", 1, filename="lesson.srt"),
            ],
            completion="complete",
        )
        self.assertEqual(partial["bundle_id"], completed["bundle_id"])
        self.assertEqual("succeeded", completed["status"])
        self.assertEqual("complete", completed["completion"])
        self.assertEqual([], completed["failures"])
        self.assertEqual(primary_asset_id, completed["items"][0]["asset_id"])


    def test_partial_bundle_keeps_failed_item_and_failure_fact(self) -> None:
        bundle = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [
                self.item("primary", 0, filename="lesson.mp4"),
                self.item("subtitle", 1, status="failed"),
            ],
            failures=[
                {
                    "position": 1,
                    "attempt": 2,
                    "code": "SUBTITLE_UNAVAILABLE",
                    "message": "字幕源暂时不可用",
                    "retriable": True,
                    "details": {"provider": "fixture"},
                }
            ],
            completion="partial",
        )

        self.assertEqual("partial", bundle["status"])
        self.assertEqual("partial", bundle["completion"])
        failed = bundle["items"][1]
        self.assertEqual("failed", failed["status"])
        self.assertIsNone(failed["asset_id"])
        self.assertEqual(1, len(bundle["failures"]))
        self.assertEqual(failed["bundle_item_id"], bundle["failures"][0]["bundle_item_id"])
        self.assertTrue(bundle["failures"][0]["retriable"])
        self.assertEqual([], self.store.get_job("job_a")["asset_ids"][1:])

    def test_failed_bundle_has_a_failed_primary_without_fake_asset(self) -> None:
        bundle = self.store.persist_failed_asset_bundle(
            "job_a",
            "resource_a",
            failure={
                "code": "SOURCE_DENIED",
                "message": "来源需要授权",
                "retriable": False,
            },
        )
        self.assertEqual("failed", bundle["status"])
        self.assertEqual("partial", bundle["completion"])
        self.assertEqual("primary", bundle["items"][0]["role"])
        self.assertIsNone(bundle["items"][0]["asset_id"])
        self.assertEqual([], self.store.get_job("job_a")["asset_ids"])

    def test_constraints_reject_invalid_role_duplicate_position_and_cross_flow(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate_asset_bundle_position"):
            self.store.persist_asset_bundle(
                "job_a",
                "resource_a",
                [self.item("primary", 0), self.item("attachment", 0)],
            )
        with self.assertRaisesRegex(ValueError, "exactly_one_primary"):
            self.store.persist_asset_bundle(
                "job_a",
                "resource_a",
                [self.item("primary", 0), self.item("primary", 1)],
            )
        with self.assertRaisesRegex(ValueError, "invalid_asset_bundle_role"):
            self.store.persist_asset_bundle(
                "job_a", "resource_a", [self.item("unknown", 0)]
            )
        self._insert_resource("resource_unplanned")
        with self.assertRaisesRegex(RuntimeError, "execution_binding_missing"):
            self.store.persist_asset_bundle(
                "job_a", "resource_unplanned", [self.item("primary", 0)]
            )
        with self.assertRaisesRegex(ValueError, "job_resource_flow_mismatch"):
            with self.store.transaction() as connection:
                connection.execute(
                    "INSERT INTO flows(flow_id,query,context_json,status,presented_version,created_at,updated_at) VALUES ('flow_b','q','{}','new',0,?,?)",
                    (NOW, NOW),
                )
                connection.execute(
                    "INSERT INTO resources(resource_id,flow_id,presented_version,platform,title,source_url,resource_type,metadata_json,created_at) VALUES ('resource_b2','flow_b',1,'generic','R','https://example.com/r','video','{}',?)",
                    (NOW,),
                )
            self.store.persist_asset_bundle("job_a", "resource_b2", [self.item("primary", 0)])

    def test_sql_constraints_protect_position_asset_and_primary_relations(self) -> None:
        bundle = self.store.persist_asset_bundle(
            "job_a", "resource_a", [self.item("primary", 0)]
        )
        item = bundle["items"][0]
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO asset_bundle_items(
                        bundle_item_id, bundle_id, asset_id, position, role, status,
                        required, metadata_json, created_at, updated_at
                    ) VALUES ('duplicate_item', ?, ?, 1, 'attachment', 'ready', 0, '{}', ?, ?)
                    """,
                    (bundle["bundle_id"], item["asset_id"], NOW, NOW),
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO asset_bundle_items(
                        bundle_item_id, bundle_id, asset_id, position, role, status,
                        required, metadata_json, created_at, updated_at
                    ) VALUES ('duplicate_primary', ?, NULL, 1, 'primary', 'failed', 1, '{}', ?, ?)
                    """,
                    (bundle["bundle_id"], NOW, NOW),
                )

        asset = self.store.persist_asset_bundle(
            "job_b", "resource_b", [self.item("primary", 0, filename="scope.pdf")]
        )["items"][0]["asset_id"]
        with self.assertRaisesRegex(ValueError, "asset_bundle_asset_scope_mismatch"):
            self.store.persist_asset_bundle(
                "job_a",
                "resource_a",
                [{"role": "primary", "position": 0, "status": "ready", "asset_id": asset}],
            )

    def test_create_asset_compatibility_wrapper_persists_singleton_bundle(self) -> None:
        asset = self.store.create_asset(
            "job_a",
            "resource_a",
            Path("/controlled/compat.pdf"),
            17,
            "application/pdf",
            "f" * 64,
            "compat.pdf",
        )
        bundle = self.store.get_asset_bundle_for_asset(asset["asset_id"])
        assert bundle is not None
        self.assertEqual("job_a", bundle["job_id"])
        self.assertEqual("resource_a", bundle["resource_id"])
        self.assertEqual("complete", bundle["completion"])
        self.assertEqual(1, len(bundle["items"]))
        self.assertEqual("primary", bundle["items"][0]["role"])
        self.assertEqual(asset["asset_id"], bundle["items"][0]["asset_id"])

        replay = self.store.create_asset(
            "job_a",
            "resource_a",
            Path("/controlled/compat.pdf"),
            17,
            "application/pdf",
            "f" * 64,
            "compat.pdf",
        )
        self.assertEqual(asset["asset_id"], replay["asset_id"])

    def test_create_asset_rejects_non_running_or_cancelling_job(self) -> None:
        with self.store.transaction() as connection:
            connection.execute("UPDATE jobs SET status = 'queued' WHERE job_id = 'job_a'")
        with self.assertRaisesRegex(ValueError, "asset_bundle_job_not_running"):
            self.store.create_asset(
                "job_a",
                "resource_a",
                Path("/controlled/queued.pdf"),
                1,
                "application/pdf",
                "e" * 64,
                "queued.pdf",
            )

        with self.store.transaction() as connection:
            connection.execute("UPDATE jobs SET status = 'cancelling' WHERE job_id = 'job_b'")
        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self.store.create_asset(
                "job_b",
                "resource_b",
                Path("/controlled/cancelled.pdf"),
                1,
                "application/pdf",
                "d" * 64,
                "cancelled.pdf",
            )

    def test_quarantine_synchronizes_asset_item_and_cancelled_bundle(self) -> None:
        bundle = self.store.persist_asset_bundle(
            "job_a", "resource_a", [self.item("primary", 0)]
        )
        with self.store.transaction() as connection:
            connection.execute("UPDATE jobs SET status = 'cancelling' WHERE job_id = 'job_a'")
        self.store.quarantine_job_assets("job_a")
        refreshed = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed is not None
        self.assertEqual("cancelled", refreshed["status"])
        self.assertEqual("quarantined", refreshed["items"][0]["status"])
        self.assertEqual("quarantined", self.store.get_asset(bundle["items"][0]["asset_id"])["status"])

    def test_restart_marks_only_interrupted_bundles_failed(self) -> None:
        interrupted = self.store.persist_asset_bundle(
            "job_a", "resource_a", [self.item("primary", 0)]
        )
        completed = self.store.persist_asset_bundle(
            "job_b", "resource_b", [self.item("primary", 0, filename="done.pdf")]
        )
        with self.store.transaction() as connection:
            connection.execute("UPDATE jobs SET status = 'succeeded' WHERE job_id = 'job_b'")
        self.assertEqual(1, self.store.mark_incomplete_jobs_failed())
        failed = self.store.get_asset_bundle(interrupted["bundle_id"])
        still_complete = self.store.get_asset_bundle(completed["bundle_id"])
        assert failed is not None and still_complete is not None
        self.assertEqual("failed", failed["status"])
        self.assertEqual("quarantined", failed["items"][0]["status"])
        self.assertEqual("succeeded", still_complete["status"])
        self.assertEqual("ready", still_complete["items"][0]["status"])
        self.assertEqual("failed", self.store.get_job("job_a")["status"])
        self.assertEqual("succeeded", self.store.get_job("job_b")["status"])

    def test_running_reopen_quarantines_removed_asset_and_rebuilds_job_projection(self) -> None:
        partial = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [self.item("primary", 0), self.item("subtitle", 1, status="failed")],
            failures=[{"position": 1, "code": "SUBTITLE_MISSING", "message": "字幕缺失"}],
        )
        removed_asset_id = str(partial["items"][0]["asset_id"])
        replacement = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [
                self.item(
                    "primary",
                    0,
                    filename="replacement.pdf",
                    sha256="e" * 64,
                )
            ],
        )
        replacement_id = str(replacement["items"][0]["asset_id"])
        self.assertEqual(partial["bundle_id"], replacement["bundle_id"])
        self.assertNotEqual(removed_asset_id, replacement_id)
        self.assertEqual("quarantined", self.store.get_asset(removed_asset_id)["status"])
        self.assertIsNone(self.store.get_asset_bundle_for_asset(removed_asset_id))
        self.assertEqual([replacement_id], self.store.get_job("job_a")["asset_ids"])

    def test_running_reopen_rolls_back_the_entire_graph_on_quarantine_failure(self) -> None:
        partial = self.store.persist_asset_bundle(
            "job_a",
            "resource_a",
            [self.item("primary", 0), self.item("subtitle", 1, status="failed")],
            failures=[{"position": 1, "code": "SUBTITLE_MISSING", "message": "字幕缺失"}],
        )
        removed_asset_id = str(partial["items"][0]["asset_id"])

        def graph_snapshot() -> tuple:
            with self.store._connect() as connection:
                return (
                    tuple(connection.execute(
                        "SELECT * FROM asset_bundles WHERE bundle_id = ?",
                        (partial["bundle_id"],),
                    ).fetchone()),
                    [tuple(row) for row in connection.execute(
                        "SELECT * FROM asset_bundle_items WHERE bundle_id = ? ORDER BY position",
                        (partial["bundle_id"],),
                    ).fetchall()],
                    [tuple(row) for row in connection.execute(
                        "SELECT * FROM asset_bundle_failures WHERE bundle_id = ? ORDER BY failure_id",
                        (partial["bundle_id"],),
                    ).fetchall()],
                    [tuple(row) for row in connection.execute(
                        "SELECT * FROM assets WHERE job_id = 'job_a' ORDER BY asset_id"
                    ).fetchall()],
                    tuple(connection.execute(
                        "SELECT status, asset_ids_json, updated_at FROM jobs WHERE job_id = 'job_a'"
                    ).fetchone()),
                )

        before = graph_snapshot()
        with self.store.transaction(immediate=True) as connection:
            connection.execute(
                f"""
                CREATE TRIGGER abort_bundle_reopen_quarantine
                BEFORE UPDATE OF status ON assets
                WHEN OLD.asset_id = '{removed_asset_id}'
                 AND NEW.status = 'quarantined'
                BEGIN
                    SELECT RAISE(ABORT, 'injected reopen quarantine failure');
                END
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "injected reopen quarantine failure"
        ):
            self.store.persist_asset_bundle(
                "job_a",
                "resource_a",
                [
                    self.item(
                        "primary",
                        0,
                        filename="replacement.pdf",
                        sha256="e" * 64,
                    )
                ],
            )

        self.assertEqual(before, graph_snapshot())

    def test_bundle_mutation_requires_running_outcome(self) -> None:
        with self.store.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM acquisition_outcomes WHERE job_id = 'job_a'"
            )
        with self.assertRaisesRegex(LookupError, "acquisition_outcome_not_started"):
            self.store.persist_asset_bundle(
                "job_a", "resource_a", [self.item("primary", 0)]
            )
        self.store.start_acquisition_outcome(
            "job_a", "resource_a", metadata={"attempt": 1}
        )
        bundle = self.store.persist_asset_bundle(
            "job_a", "resource_a", [self.item("primary", 0)]
        )
        self.assertEqual("succeeded", bundle["status"])

    def test_library_search_attaches_bundle_relation_without_archive_columns(self) -> None:
        bundle = self.store.persist_asset_bundle(
            "job_a", "resource_a", [self.item("primary", 0, filename="lesson.pdf")]
        )
        asset_id = bundle["items"][0]["asset_id"]
        self._complete_outcome("job_a", "resource_a", bundle)
        self.store.finalize_job_success("job_a")
        reservation = self.store.reserve_archive(
            asset_id,
            {
                "classification": {
                    "primary_domain": "natural_science",
                    "topics": ["天文与宇宙"],
                }
            },
            "04-science/lesson.pdf",
        )
        self.store.mark_archive_ready(
            reservation["archive_id"], relative_path="04-science/lesson.pdf"
        )
        page = self.store.search_library(None, 10)
        self.assertEqual(1, len(page["items"]))
        item = page["items"][0]
        self.assertEqual(bundle["bundle_id"], item["bundle_id"])
        self.assertEqual("primary", item["role"])
        self.assertEqual(0, item["position"])
        self.assertEqual("complete", item["completion"])
        with self.store._connect() as connection:
            archive_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(archive_entries)").fetchall()
            }
        self.assertNotIn("bundle_id", archive_columns)

    def test_reopen_preserves_bundle_relations_without_duplication(self) -> None:
        first = self.store.persist_asset_bundle(
            "job_a", "resource_a", [self.item("primary", 0)]
        )
        reopened = Store(self.database)
        second = reopened.get_asset_bundle(first["bundle_id"])
        assert second is not None
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        with reopened._connect() as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM asset_bundles").fetchone()[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
