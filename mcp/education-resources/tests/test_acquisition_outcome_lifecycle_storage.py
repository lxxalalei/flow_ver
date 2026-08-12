
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import Store


NOW = "2026-08-09T01:00:00+00:00"
COMPLETED_AT = "2026-08-09T01:05:00+00:00"


class AcquisitionOutcomeLifecycleStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self._temporary_directory.name) / "lifecycle.sqlite3"
        self.store = Store(self.database)
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO flows(
                    flow_id, query, context_json, status, presented_version,
                    task_version, result_version, selection_version,
                    created_at, updated_at
                ) VALUES (
                    'flow_lifecycle', 'authority lifecycle', '{}', 'downloading',
                    1, 1, 1, 1, ?, ?
                )
                """,
                (NOW, NOW),
            )

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _insert_job(
        self,
        name: str,
        *,
        status: str = "running",
        progress: int = 0,
    ) -> dict[str, str]:
        job_id = f"job_{name}"
        plan_id = f"plan_{name}"
        resource_id = f"resource_{name}"
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO resources(
                    resource_id, flow_id, presented_version, platform, title,
                    source_url, resource_type, summary, metadata_json, created_at
                ) VALUES (?, 'flow_lifecycle', 1, 'generic', ?, ?, 'video',
                          NULL, '{}', ?)
                """,
                (
                    resource_id,
                    resource_id,
                    f"https://example.com/{resource_id}",
                    NOW,
                ),
            )
            connection.execute(
                """
                INSERT INTO download_plans(
                    plan_id, flow_id, presented_version, resource_ids_json,
                    options_json, confirmation_token, confirmation_hash,
                    expires_at, used, created_at, selection_version,
                    selection_digest, plan_digest
                ) VALUES (?, 'flow_lifecycle', 1, ?, '{}', ?, ?, ?, 1, ?,
                          1, ?, ?)
                """,
                (
                    plan_id,
                    json.dumps([resource_id]),
                    f"token_{name}",
                    f"hash_{name}",
                    "2099-01-01T00:00:00+00:00",
                    NOW,
                    f"selection_{name}",
                    f"plan_digest_{name}",
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, flow_id, plan_id, status, progress,
                    asset_ids_json, created_at, updated_at
                ) VALUES (?, 'flow_lifecycle', ?, ?, ?, '[]', ?, ?)
                """,
                (job_id, plan_id, status, progress, NOW, NOW),
            )
            representation_id = f"representation_{name}"
            source_fingerprint = self.store._request_digest(
                {"fixture": name, "kind": "source"}
            )
            representation_json = json.dumps(
                {"scope": "primary_resource"}, ensure_ascii=False
            )
            connection.execute(
                """
                INSERT INTO acquisition_plan_items(
                    plan_id, position, resource_id, resolution_id,
                    representation_id, planned_scope, strategy, provider_id,
                    provider_version, source_fingerprint, representation_json
                ) VALUES (?, 0, ?, NULL, ?, 'primary_resource', 'direct_file',
                          'generic-direct', '1.0.0', ?, ?)
                """,
                (
                    plan_id,
                    resource_id,
                    representation_id,
                    source_fingerprint,
                    representation_json,
                ),
            )
            connection.execute(
                """
                INSERT INTO job_items(
                    job_id, plan_id, position, resource_id, resolution_id,
                    representation_id, planned_scope, strategy, provider_id,
                    provider_version, source_fingerprint, representation_json,
                    revalidated_at
                ) VALUES (?, ?, 0, ?, NULL, ?, 'primary_resource', 'direct_file',
                          'generic-direct', '1.0.0', ?, ?, ?)
                """,
                (
                    job_id,
                    plan_id,
                    resource_id,
                    representation_id,
                    source_fingerprint,
                    representation_json,
                    NOW,
                ),
            )
        return {"job_id": job_id, "plan_id": plan_id, "resource_id": resource_id}

    def _insert_additional_resource(self, name: str) -> str:
        resource_id = f"resource_{name}"
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO resources(
                    resource_id, flow_id, presented_version, platform, title,
                    source_url, resource_type, summary, metadata_json, created_at
                ) VALUES (?, 'flow_lifecycle', 1, 'generic', ?, ?, 'video',
                          NULL, '{}', ?)
                """,
                (
                    resource_id,
                    resource_id,
                    f"https://example.com/{resource_id}",
                    NOW,
                ),
            )
        return resource_id

    def _insert_outcome(
        self,
        fixture: dict[str, str],
        *,
        resource_id: str | None = None,
        name: str | None = None,
        status: str = "running",
    ) -> dict[str, object]:
        resource_id = resource_id or fixture["resource_id"]
        outcome_id = f"outcome_{name or fixture['job_id']}"
        terminal = status != "running"
        projection: dict[str, object] = {
            "outcome_id": outcome_id,
            "job_id": fixture["job_id"],
            "plan_id": fixture["plan_id"],
            "resource_id": resource_id,
            "planned_scope": "primary_resource",
            "planned_strategy": "direct_file",
            "planned_provider_id": "generic-direct",
            "planned_provider_version": "1.0.0",
            "actual_scope": None,
            "actual_strategy": None,
            "actual_provider_id": None,
            "actual_provider_version": None,
            "status": status,
            "failure_code": "DOWNLOAD_FAILED" if terminal else None,
            "failure_message": "already terminal" if terminal else None,
            "retriable": False,
            "bundle_id": None,
            "asset_ids": [],
            "metadata": {"attempt": 1, "authority": "execution_snapshot"},
            "started_at": NOW,
            "completed_at": COMPLETED_AT if terminal else None,
        }
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO execution_outcomes(
                    outcome_id, job_id, plan_id, resource_id,
                    planned_scope, planned_strategy, planned_provider_id,
                    planned_provider_version, actual_scope, actual_strategy,
                    actual_provider_id, actual_provider_version, status,
                    failure_code, failure_message, retriable, bundle_id,
                    asset_ids_json, metadata_json, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL,
                          ?, ?, ?, ?, NULL, '[]', ?, ?, ?)
                """,
                (
                    outcome_id,
                    fixture["job_id"],
                    fixture["plan_id"],
                    resource_id,
                    projection["planned_scope"],
                    projection["planned_strategy"],
                    projection["planned_provider_id"],
                    projection["planned_provider_version"],
                    status,
                    projection["failure_code"],
                    projection["failure_message"],
                    1 if projection["retriable"] else 0,
                    json.dumps(projection["metadata"], ensure_ascii=False),
                    NOW,
                    projection["completed_at"],
                ),
            )
        return projection

    def _persist_ready_bundle(
        self, fixture: dict[str, str], *, filename: str = "lesson.mp4"
    ) -> dict[str, object]:
        job = self.store.get_job(fixture["job_id"])
        if (
            job is not None
            and job["status"] == "running"
            and self.store.get_acquisition_outcome(
                fixture["job_id"], fixture["resource_id"]
            )
            is None
        ):
            self._insert_outcome(fixture)
        return self.store.persist_asset_bundle(
            fixture["job_id"],
            fixture["resource_id"],
            [
                {
                    "role": "primary",
                    "position": 0,
                    "status": "ready",
                    "required": True,
                    "local_path": f"/controlled/{filename}",
                    "byte_size": 8,
                    "media_type": "video/mp4",
                    "sha256": "a" * 64,
                    "filename": filename,
                    "metadata": {},
                }
            ],
        )

    def test_batch_finalization_closes_only_running_outcomes(self) -> None:
        fixture = self._insert_job("batch")
        running = self._insert_outcome(fixture)
        terminal_resource = self._insert_additional_resource("batch_terminal")
        terminal = self._insert_outcome(
            fixture,
            resource_id=terminal_resource,
            name="batch_terminal",
            status="failed",
        )
        bundle = self._persist_ready_bundle(fixture)

        finalized = self.store.finalize_running_acquisition_outcomes(
            fixture["job_id"],
            status="failed",
            failure_code="INTERNAL_ERROR",
            failure_message="runner stopped before terminal publication",
            retriable=True,
            completed_at=COMPLETED_AT,
        )

        self.assertEqual(1, len(finalized))
        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("failed", outcome["status"])
        self.assertEqual("INTERNAL_ERROR", outcome["failure_code"])
        self.assertTrue(outcome["retriable"])
        self.assertEqual(COMPLETED_AT, outcome["completed_at"])
        self.assertEqual(running["metadata"], outcome["metadata"])
        self.assertIsNone(outcome["actual_provider_id"])
        self.assertIsNone(outcome["bundle_id"])
        self.assertEqual([], outcome["asset_ids"])

        unchanged = self.store.get_acquisition_outcome(
            fixture["job_id"], terminal_resource
        )
        assert unchanged is not None
        self.assertEqual(terminal["outcome_id"], unchanged["outcome_id"])
        self.assertEqual("failed", unchanged["status"])

        self.assertEqual("running", self.store.get_job(fixture["job_id"])["status"])
        refreshed_bundle = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed_bundle is not None
        self.assertEqual("succeeded", refreshed_bundle["status"])
        self.assertEqual("ready", refreshed_bundle["items"][0]["status"])

        outcome_id = outcome["outcome_id"]
        self.assertEqual(
            [],
            self.store.finalize_running_acquisition_outcomes(
                fixture["job_id"],
                status="failed",
                failure_code="INTERNAL_ERROR",
                failure_message="runner stopped before terminal publication",
                retriable=True,
                completed_at="2026-08-09T01:10:00+00:00",
            ),
        )
        self.assertEqual(
            outcome_id,
            self.store.get_acquisition_outcome(
                fixture["job_id"], fixture["resource_id"]
            )["outcome_id"],
        )
        with self.assertRaisesRegex(
            ValueError, "invalid_acquisition_outcome_cleanup_status"
        ):
            self.store.finalize_running_acquisition_outcomes(
                fixture["job_id"],
                status="succeeded",
                failure_code="INTERNAL_ERROR",
            )

    def test_partial_outcome_helper_cannot_publish_cancellation(self) -> None:
        fixture = self._insert_job("partial_cancel_rejected")
        running = self._insert_outcome(fixture)

        with self.assertRaisesRegex(
            ValueError, "invalid_acquisition_outcome_cleanup_status"
        ):
            self.store.finalize_running_acquisition_outcomes(
                fixture["job_id"],
                status="cancelled",
                failure_code="JOB_CANCELLED",
                failure_message="must require a persisted Job cancellation",
                completed_at=COMPLETED_AT,
            )

        self.assertEqual("running", self.store.get_job(fixture["job_id"])["status"])
        unchanged = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert unchanged is not None
        self.assertEqual("running", unchanged["status"])
        self.assertEqual(running["outcome_id"], unchanged["outcome_id"])

    def test_restart_recovery_terminalizes_outcomes_before_job(self) -> None:
        interrupted = self._insert_job("restart")
        self._insert_outcome(interrupted)
        interrupted_bundle = self._persist_ready_bundle(interrupted, filename="partial.mp4")
        queued = self._insert_job("queued", status="queued")
        complete = self._insert_job("complete", status="running")
        complete_bundle = self._persist_ready_bundle(complete, filename="complete.mp4")
        self.store.update_job(complete["job_id"], status="succeeded", progress=100)

        self.assertEqual(2, self.store.mark_incomplete_jobs_failed())

        outcome = self.store.get_acquisition_outcome(
            interrupted["job_id"], interrupted["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("failed", outcome["status"])
        self.assertEqual("INTERNAL_ERROR", outcome["failure_code"])
        self.assertIn("服务重启", outcome["failure_message"])
        self.assertTrue(outcome["retriable"])
        self.assertIsNotNone(outcome["completed_at"])

        failed_job = self.store.get_job(interrupted["job_id"])
        queued_job = self.store.get_job(queued["job_id"])
        assert failed_job is not None and queued_job is not None
        self.assertEqual("failed", failed_job["status"])
        self.assertEqual("INTERNAL_ERROR", failed_job["error"]["code"])
        self.assertTrue(failed_job["error"]["retriable"])
        self.assertEqual("failed", queued_job["status"])

        failed_bundle = self.store.get_asset_bundle(interrupted_bundle["bundle_id"])
        assert failed_bundle is not None
        self.assertEqual("failed", failed_bundle["status"])
        self.assertEqual("partial", failed_bundle["completion"])
        self.assertEqual("quarantined", failed_bundle["items"][0]["status"])
        self.assertEqual(
            "quarantined",
            self.store.get_asset(interrupted_bundle["items"][0]["asset_id"])["status"],
        )

        untouched_bundle = self.store.get_asset_bundle(complete_bundle["bundle_id"])
        assert untouched_bundle is not None
        self.assertEqual("succeeded", untouched_bundle["status"])
        self.assertEqual("ready", untouched_bundle["items"][0]["status"])
        self.assertEqual("succeeded", self.store.get_job(complete["job_id"])["status"])

        outcome_id = outcome["outcome_id"]
        completed_at = outcome["completed_at"]
        self.assertEqual(0, self.store.mark_incomplete_jobs_failed())
        replayed = self.store.get_acquisition_outcome(
            interrupted["job_id"], interrupted["resource_id"]
        )
        assert replayed is not None
        self.assertEqual(outcome_id, replayed["outcome_id"])
        self.assertEqual(completed_at, replayed["completed_at"])

    def test_restart_recovery_rolls_back_the_whole_authority_graph(self) -> None:
        fixture = self._insert_job("rollback")
        original_outcome = self._insert_outcome(fixture)
        bundle = self._persist_ready_bundle(fixture, filename="rollback.mp4")
        with self.store.transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER abort_restart_terminal_job
                BEFORE UPDATE OF status ON jobs
                WHEN OLD.job_id = 'job_rollback' AND NEW.status = 'failed'
                BEGIN
                    SELECT RAISE(ABORT, 'forced restart rollback');
                END
                """
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.mark_incomplete_jobs_failed()

        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("running", outcome["status"])
        self.assertEqual(original_outcome["outcome_id"], outcome["outcome_id"])
        self.assertIsNone(outcome["completed_at"])
        self.assertEqual("running", self.store.get_job(fixture["job_id"])["status"])
        refreshed_bundle = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed_bundle is not None
        self.assertEqual("succeeded", refreshed_bundle["status"])
        self.assertEqual("complete", refreshed_bundle["completion"])
        self.assertEqual("ready", refreshed_bundle["items"][0]["status"])
        self.assertEqual(
            "ready", self.store.get_asset(bundle["items"][0]["asset_id"])["status"]
        )

    def test_cancellation_support_atomically_closes_and_quarantines(self) -> None:
        fixture = self._insert_job("cancel", status="running", progress=37)
        self._insert_outcome(fixture)
        bundle = self._persist_ready_bundle(fixture, filename="cancel.mp4")
        self.store.request_job_cancellation(
            fixture["job_id"], requested_at="2026-08-09T01:11:00+00:00"
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET error_json = ? WHERE job_id = ?",
                (
                    json.dumps(
                        {
                            "code": "DOWNLOAD_FAILED",
                            "message": "stale failure",
                            "retriable": True,
                        }
                    ),
                    fixture["job_id"],
                ),
            )

        cancelled = self.store.finalize_job_cancellation(
            fixture["job_id"], completed_at=COMPLETED_AT
        )

        self.assertEqual("cancelled", cancelled["status"])
        self.assertEqual(37, cancelled["progress"])
        self.assertIsNone(cancelled["error"])
        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("cancelled", outcome["status"])
        self.assertEqual("JOB_CANCELLED", outcome["failure_code"])
        self.assertEqual("任务已取消", outcome["failure_message"])
        self.assertFalse(outcome["retriable"])
        self.assertEqual(COMPLETED_AT, outcome["completed_at"])

        refreshed_bundle = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed_bundle is not None
        self.assertEqual("cancelled", refreshed_bundle["status"])
        self.assertEqual("partial", refreshed_bundle["completion"])
        self.assertEqual("quarantined", refreshed_bundle["items"][0]["status"])
        self.assertEqual(
            "quarantined", self.store.get_asset(bundle["items"][0]["asset_id"])["status"]
        )

        outcome_id = outcome["outcome_id"]
        job_updated_at = cancelled["updated_at"]
        bundle_updated_at = refreshed_bundle["updated_at"]
        replayed = self.store.finalize_job_cancellation(
            fixture["job_id"], completed_at="2026-08-09T01:20:00+00:00"
        )
        self.assertEqual(job_updated_at, replayed["updated_at"])
        self.assertEqual(
            outcome_id,
            self.store.get_acquisition_outcome(
                fixture["job_id"], fixture["resource_id"]
            )["outcome_id"],
        )
        self.assertEqual(
            bundle_updated_at,
            self.store.get_asset_bundle(bundle["bundle_id"])["updated_at"],
        )

        terminal = self._insert_job("terminal", status="succeeded")
        with self.assertRaisesRegex(ValueError, "job_not_cancellable"):
            self.store.finalize_job_cancellation(terminal["job_id"])
        self.assertEqual("succeeded", self.store.get_job(terminal["job_id"])["status"])

    def test_runner_state_compare_and_set_preserves_cancellation(self) -> None:
        queued = self._insert_job("cancel_before_start", status="queued", progress=0)
        requested = self.store.request_job_cancellation(
            queued["job_id"], requested_at="2026-08-09T01:01:00+00:00"
        )
        self.assertEqual("cancelling", requested["status"])
        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self.store.start_job_execution(
                queued["job_id"], started_at="2026-08-09T01:02:00+00:00"
            )
        self.assertEqual("cancelling", self.store.get_job(queued["job_id"])["status"])

        running = self._insert_job("cancel_before_progress", status="running", progress=23)
        self.store.request_job_cancellation(
            running["job_id"], requested_at="2026-08-09T01:03:00+00:00"
        )
        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self.store.update_job_progress(
                running["job_id"], 77, updated_at="2026-08-09T01:04:00+00:00"
            )
        unchanged = self.store.get_job(running["job_id"])
        assert unchanged is not None
        self.assertEqual("cancelling", unchanged["status"])
        self.assertEqual(23, unchanged["progress"])

        # Even the low-level partial update helper must not replay a stale
        # status while updating a different column.
        self.store.update_job(running["job_id"], progress=31)
        low_level = self.store.get_job(running["job_id"])
        assert low_level is not None
        self.assertEqual("cancelling", low_level["status"])
        self.assertEqual(31, low_level["progress"])

        late_success = self._insert_job("cancel_before_success", status="running")
        self._persist_ready_bundle(late_success, filename="late-success.mp4")
        self.store.request_job_cancellation(
            late_success["job_id"], requested_at="2026-08-09T01:05:00+00:00"
        )
        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self.store.finalize_job_success(
                late_success["job_id"], completed_at="2026-08-09T01:06:00+00:00"
            )
        cancelled = self.store.finalize_job_cancellation(
            late_success["job_id"], completed_at="2026-08-09T01:07:00+00:00"
        )
        self.assertEqual("cancelled", cancelled["status"])

    def test_job_execution_start_and_progress_are_stable_replays(self) -> None:
        fixture = self._insert_job("runner_progress", status="queued", progress=0)
        started = self.store.start_job_execution(
            fixture["job_id"], started_at="2026-08-09T01:08:00+00:00"
        )
        self.assertEqual("running", started["status"])
        replayed = self.store.start_job_execution(
            fixture["job_id"], started_at="2026-08-09T01:09:00+00:00"
        )
        self.assertEqual(started, replayed)
        progressed = self.store.update_job_progress(
            fixture["job_id"], 42, updated_at="2026-08-09T01:10:00+00:00"
        )
        self.assertEqual("running", progressed["status"])
        self.assertEqual(42, progressed["progress"])
        stale = self.store.update_job_progress(
            fixture["job_id"], 17, updated_at="2026-08-09T01:11:00+00:00"
        )
        self.assertEqual(42, stale["progress"])
        with self.assertRaisesRegex(ValueError, "invalid_job_progress"):
            self.store.update_job_progress(fixture["job_id"], 101)

    def test_restart_recovery_finishes_persisted_cancellation(self) -> None:
        fixture = self._insert_job("restart_cancel", status="running", progress=37)
        self._insert_outcome(fixture)
        bundle = self._persist_ready_bundle(fixture, filename="restart-cancel.mp4")
        self.store.request_job_cancellation(
            fixture["job_id"], requested_at="2026-08-09T01:12:00+00:00"
        )

        self.assertEqual(1, self.store.mark_incomplete_jobs_failed())

        job = self.store.get_job(fixture["job_id"])
        assert job is not None
        self.assertEqual("cancelled", job["status"])
        self.assertEqual(37, job["progress"])
        self.assertIsNone(job["error"])
        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("cancelled", outcome["status"])
        self.assertEqual("JOB_CANCELLED", outcome["failure_code"])
        self.assertEqual("任务已取消", outcome["failure_message"])
        self.assertFalse(outcome["retriable"])
        refreshed = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed is not None
        self.assertEqual("cancelled", refreshed["status"])
        self.assertEqual("quarantined", refreshed["items"][0]["status"])

        outcome_id = outcome["outcome_id"]
        completed_at = outcome["completed_at"]
        self.assertEqual(0, self.store.mark_incomplete_jobs_failed())
        replayed = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert replayed is not None
        self.assertEqual(outcome_id, replayed["outcome_id"])
        self.assertEqual(completed_at, replayed["completed_at"])

    def test_cancelled_job_rejects_late_bundle_publication(self) -> None:
        fixture = self._insert_job("late_bundle", status="running", progress=51)
        self.store.request_job_cancellation(fixture["job_id"])

        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self._persist_ready_bundle(fixture, filename="must-not-publish.mp4")
        self.assertIsNone(
            self.store.get_asset_bundle_for_job_resource(
                fixture["job_id"], fixture["resource_id"]
            )
        )
        job = self.store.get_job(fixture["job_id"])
        assert job is not None
        self.assertEqual("cancelling", job["status"])
        self.assertEqual([], job["asset_ids"])

    def test_restart_cancellation_recovery_rolls_back_whole_graph(self) -> None:
        fixture = self._insert_job("restart_cancel_rollback", status="running")
        original_outcome = self._insert_outcome(fixture)
        bundle = self._persist_ready_bundle(
            fixture, filename="restart-cancel-rollback.mp4"
        )
        self.store.request_job_cancellation(fixture["job_id"])
        original_job = self.store.get_job(fixture["job_id"])
        assert original_job is not None
        with self.store.transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER abort_restart_cancel_terminal_job
                BEFORE UPDATE OF status ON jobs
                WHEN OLD.job_id = 'job_restart_cancel_rollback'
                  AND NEW.status = 'cancelled'
                BEGIN
                    SELECT RAISE(ABORT, 'forced restart cancellation rollback');
                END
                """
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.mark_incomplete_jobs_failed()

        self.assertEqual(original_job, self.store.get_job(fixture["job_id"]))
        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("running", outcome["status"])
        self.assertEqual(original_outcome["outcome_id"], outcome["outcome_id"])
        refreshed = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed is not None
        self.assertEqual("succeeded", refreshed["status"])
        self.assertEqual("ready", refreshed["items"][0]["status"])
        self.assertEqual(
            "ready", self.store.get_asset(bundle["items"][0]["asset_id"])["status"]
        )


    def test_failure_support_atomically_closes_and_quarantines_with_stable_replay(
        self,
    ) -> None:
        fixture = self._insert_job("failure", status="running", progress=61)
        running = self._insert_outcome(fixture)
        terminal_resource = self._insert_additional_resource("failure_terminal")
        terminal = self._insert_outcome(
            fixture,
            resource_id=terminal_resource,
            name="failure_terminal",
            status="cancelled",
        )
        bundle = self._persist_ready_bundle(fixture, filename="failure.mp4")
        original_job = self.store.get_job(fixture["job_id"])
        assert original_job is not None

        failed = self.store.finalize_job_failure(
            fixture["job_id"],
            failure_code="CONTENT_VALIDATION_FAILED",
            failure_message="primary asset failed validation",
            retriable=False,
            completed_at=COMPLETED_AT,
        )

        self.assertEqual("failed", failed["status"])
        self.assertEqual(61, failed["progress"])
        self.assertEqual(original_job["asset_ids"], failed["asset_ids"])
        self.assertEqual(
            {
                "code": "CONTENT_VALIDATION_FAILED",
                "message": "primary asset failed validation",
                "retriable": False,
            },
            failed["error"],
        )
        self.assertEqual(COMPLETED_AT, failed["updated_at"])

        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("failed", outcome["status"])
        self.assertEqual("CONTENT_VALIDATION_FAILED", outcome["failure_code"])
        self.assertEqual(
            "primary asset failed validation", outcome["failure_message"]
        )
        self.assertFalse(outcome["retriable"])
        self.assertEqual(COMPLETED_AT, outcome["completed_at"])
        self.assertEqual(running["metadata"], outcome["metadata"])

        unchanged = self.store.get_acquisition_outcome(
            fixture["job_id"], terminal_resource
        )
        assert unchanged is not None
        self.assertEqual("cancelled", unchanged["status"])
        self.assertEqual(terminal["outcome_id"], unchanged["outcome_id"])
        self.assertEqual(terminal["completed_at"], unchanged["completed_at"])

        refreshed_bundle = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed_bundle is not None
        self.assertEqual("failed", refreshed_bundle["status"])
        self.assertEqual("partial", refreshed_bundle["completion"])
        self.assertEqual("quarantined", refreshed_bundle["items"][0]["status"])
        self.assertEqual(
            "quarantined",
            self.store.get_asset(bundle["items"][0]["asset_id"])["status"],
        )

        outcome_id = outcome["outcome_id"]
        job_updated_at = failed["updated_at"]
        bundle_updated_at = refreshed_bundle["updated_at"]
        replayed = self.store.finalize_job_failure(
            fixture["job_id"],
            failure_code="INTERNAL_ERROR",
            failure_message="must not replace the authoritative first failure",
            retriable=True,
            completed_at="2026-08-09T01:20:00+00:00",
        )
        self.assertEqual(failed, replayed)
        self.assertEqual(job_updated_at, replayed["updated_at"])
        self.assertEqual(
            outcome_id,
            self.store.get_acquisition_outcome(
                fixture["job_id"], fixture["resource_id"]
            )["outcome_id"],
        )
        self.assertEqual(
            bundle_updated_at,
            self.store.get_asset_bundle(bundle["bundle_id"])["updated_at"],
        )

        for status in ("succeeded", "cancelled"):
            terminal_job = self._insert_job(f"failure_{status}", status=status)
            with self.assertRaisesRegex(ValueError, "job_not_failable"):
                self.store.finalize_job_failure(
                    terminal_job["job_id"],
                    failure_code="INTERNAL_ERROR",
                    failure_message="must not rewrite terminal job",
                    retriable=False,
                )
            self.assertEqual(
                status, self.store.get_job(terminal_job["job_id"])["status"]
            )

    def test_failure_support_rolls_back_the_whole_authority_graph(self) -> None:
        fixture = self._insert_job("failure_rollback", status="running", progress=29)
        original_outcome = self._insert_outcome(fixture)
        bundle = self._persist_ready_bundle(fixture, filename="failure-rollback.mp4")
        original_job = self.store.get_job(fixture["job_id"])
        assert original_job is not None
        with self.store.transaction() as connection:
            connection.execute(
                """
                CREATE TRIGGER abort_atomic_job_failure
                BEFORE UPDATE OF status ON jobs
                WHEN OLD.job_id = 'job_failure_rollback' AND NEW.status = 'failed'
                BEGIN
                    SELECT RAISE(ABORT, 'forced failure rollback');
                END
                """
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.finalize_job_failure(
                fixture["job_id"],
                failure_code="INTERNAL_ERROR",
                failure_message="runner failed",
                retriable=True,
                completed_at=COMPLETED_AT,
            )

        outcome = self.store.get_acquisition_outcome(
            fixture["job_id"], fixture["resource_id"]
        )
        assert outcome is not None
        self.assertEqual("running", outcome["status"])
        self.assertEqual(original_outcome["outcome_id"], outcome["outcome_id"])
        self.assertIsNone(outcome["completed_at"])
        self.assertEqual(original_job, self.store.get_job(fixture["job_id"]))

        refreshed_bundle = self.store.get_asset_bundle(bundle["bundle_id"])
        assert refreshed_bundle is not None
        self.assertEqual("succeeded", refreshed_bundle["status"])
        self.assertEqual("complete", refreshed_bundle["completion"])
        self.assertEqual("ready", refreshed_bundle["items"][0]["status"])
        self.assertEqual(
            "ready", self.store.get_asset(bundle["items"][0]["asset_id"])["status"]
        )


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
