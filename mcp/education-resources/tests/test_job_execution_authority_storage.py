from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import Store


STARTED_AT = "2026-08-08T12:00:00+00:00"
RESOURCE_ID = "res_execution_authority_0001"
REPRESENTATION_ID = "repr_execution_authority_0001"


def canonical_digest(character: str) -> str:
    return "sha256:" + character * 64


class JobExecutionAuthorityStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self._temporary_directory.name) / "execution.sqlite3"
        self.store = Store(self.database)
        self.fixture = self._create_fixture()

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _readiness(
        self,
        snapshot_id: str,
        *,
        observed_at: str,
        expires_at: str,
        status: str = "ready",
    ) -> dict[str, object]:
        return self.store.save_capability_readiness_snapshot(
            {
                "readiness_snapshot_id": snapshot_id,
                "capability_id": "cap_generic_landing_materialize_v1",
                "descriptor_version": "1.0.0",
                "descriptor_digest": canonical_digest("d"),
                "registry_version": "1.0.0",
                "registry_digest": canonical_digest("a"),
                "platform_id": "generic",
                "capability_scope": "landing_page",
                "strategy": "web_materialize",
                "provider_id": "generic-web-materializer",
                "provider_version": "1.0.0",
                "inspector_id": "generic",
                "inspector_version": "1.0.0",
                "status": status,
                "issues": [],
                "observed_at": observed_at,
                "expires_at": expires_at,
            }
        )

    def _eligibility(
        self,
        eligibility_id: str,
        readiness: dict[str, object],
        *,
        evaluated_at: str,
        expires_at: str,
        status: str = "eligible",
        action: str = "materialize",
    ) -> dict[str, object]:
        return self.store.save_eligibility_decision(
            {
                "eligibility_id": eligibility_id,
                "flow_id": self.fixture["flow_id"] if hasattr(self, "fixture") else self._flow_id,
                "resource_id": RESOURCE_ID,
                "resolution_id": self._resolution_id,
                "representation_id": REPRESENTATION_ID,
                "action": action,
                "status": status,
                "policy_class": "public",
                "reason_codes": ["PUBLIC_SOURCE"],
                "source_fingerprint": canonical_digest("f"),
                "capability_id": "cap_generic_landing_materialize_v1",
                "descriptor_digest": canonical_digest("d"),
                "readiness_snapshot_id": readiness["readiness_snapshot_id"],
                "evaluated_at": evaluated_at,
                "expires_at": expires_at,
            }
        )

    def _execution_with(
        self,
        readiness: dict[str, object],
        eligibility: dict[str, object],
    ) -> dict[str, object]:
        execution = copy.deepcopy(self.fixture["plan_item"])
        execution.pop("binding_digest", None)
        execution.update(
            {
                "readiness_snapshot_id": readiness["readiness_snapshot_id"],
                "readiness_digest": readiness["snapshot_digest"],
                "eligibility_id": eligibility["eligibility_id"],
                "eligibility_digest": eligibility["decision_digest"],
            }
        )
        return execution

    def _create_fixture(self) -> dict[str, object]:
        flow = self.store.create_flow(
            {"goal": {"topic": "execution authority"}},
            "flow-key-execution-0001",
            "flow-request-execution-0001",
        )
        self._flow_id = str(flow["flow_id"])
        result_set = self.store.create_result_set(
            self._flow_id,
            [
                {
                    "resource_id": RESOURCE_ID,
                    "platform": "generic",
                    "title": "Landing page materialization",
                    "source_url": "https://example.com/landing",
                    "resource_type": "article",
                    "summary": "Authority fixture",
                    "metadata": {},
                }
            ],
            query="execution authority",
            task_version=int(flow["task_version"]),
            filters={},
            failures=[],
            platform_runs=[],
            idempotency_key="search-key-execution-0001",
            request_hash="search-request-execution-0001",
        )
        presentation = self.store.create_presentation(
            self._flow_id,
            str(result_set["result_set_id"]),
            [RESOURCE_ID],
            idempotency_key="presentation-key-execution-0001",
            request_hash="presentation-request-execution-0001",
        )
        selection = self.store.save_selection(
            self._flow_id,
            str(presentation["presentation_id"]),
            int(presentation["presented_version"]),
            [1],
            idempotency_key="selection-key-execution-0001",
            request_hash="selection-request-execution-0001",
        )
        representation = {
            "representation_id": REPRESENTATION_ID,
            "scope": "landing_page",
            "kind": "webpage",
            "role": "landing",
            "container": "html",
            "mime_type": "text/html",
            "materializable": True,
            "technical_availability": "available",
        }
        resolution = self.store.save_resolution(
            self._flow_id,
            RESOURCE_ID,
            "inspect-v1",
            "f" * 64,
            "resolved",
            # Resolution cache identity intentionally remains a bare digest;
            # execution authority uses the schema-level sha256: spelling.
            resolved={"representations": [representation]},
            inspection={},
            failures=[],
            idempotency_key="inspection-key-execution-0001",
            request_hash="inspection-request-execution-0001",
            inspected_at="2026-08-01T00:00:00+00:00",
        )
        self._resolution_id = str(resolution["resolution_id"])

        # These Plan-time credentials are deliberately expired at Job start.
        # The reservation must validate their historical integrity but execute
        # only with the separate fresh credentials below.
        plan_readiness = self._readiness(
            "ready_plan_execution_0001",
            observed_at="2026-08-01T00:00:00+00:00",
            expires_at="2026-08-02T00:00:00+00:00",
        )
        plan_eligibility = self._eligibility(
            "elig_plan_execution_0001",
            plan_readiness,
            evaluated_at="2026-08-01T00:01:00+00:00",
            expires_at="2026-08-02T00:00:00+00:00",
        )
        plan_item = {
            "position": 0,
            "resource_id": RESOURCE_ID,
            "resolution_id": self._resolution_id,
            "representation_id": REPRESENTATION_ID,
            "capability_scope": "landing_page",
            "strategy": "web_materialize",
            "provider_id": "generic-web-materializer",
            "provider_version": "1.0.0",
            "capability_id": "cap_generic_landing_materialize_v1",
            "descriptor_version": "1.0.0",
            "descriptor_digest": canonical_digest("d"),
            "registry_version": "1.0.0",
            "registry_digest": canonical_digest("a"),
            "readiness_snapshot_id": plan_readiness["readiness_snapshot_id"],
            "readiness_digest": plan_readiness["snapshot_digest"],
            "eligibility_id": plan_eligibility["eligibility_id"],
            "eligibility_digest": plan_eligibility["decision_digest"],
            "source_fingerprint": canonical_digest("f"),
            "representation": representation,
        }
        prepared = self.store.create_plan(
            self._flow_id,
            str(presentation["presentation_id"]),
            int(presentation["presented_version"]),
            int(selection["selection_version"]),
            str(selection["selection_digest"]),
            {
                "strategy": "materialize",
                "preferred_container": "html",
                "allow_safe_fallback": False,
            },
            "confirmation-token-execution-0001",
            "confirmation-hash-execution-0001",
            "2099-01-01T00:00:00+00:00",
            idempotency_key="prepare-key-execution-0001",
            request_hash="prepare-request-execution-0001",
            capability_items=[plan_item],
        )
        persisted_plan = self.store.get_plan(str(prepared["plan_id"]))
        assert persisted_plan is not None
        persisted_item = persisted_plan["capability_items"][0]

        fresh_readiness = self._readiness(
            "ready_job_execution_0001",
            observed_at="2026-08-08T10:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        fresh_eligibility = self._eligibility(
            "elig_job_execution_0001",
            fresh_readiness,
            evaluated_at="2026-08-08T10:01:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        execution = copy.deepcopy(persisted_item)
        execution.pop("binding_digest", None)
        execution.update(
            {
                "readiness_snapshot_id": fresh_readiness["readiness_snapshot_id"],
                "readiness_digest": fresh_readiness["snapshot_digest"],
                "eligibility_id": fresh_eligibility["eligibility_id"],
                "eligibility_digest": fresh_eligibility["decision_digest"],
            }
        )
        return {
            "flow_id": self._flow_id,
            "plan": persisted_plan,
            "plan_item": persisted_item,
            "execution": execution,
        }

    def _bindings(self) -> dict[str, object]:
        plan = self.fixture["plan"]
        assert isinstance(plan, dict)
        return {
            "presentation_id": plan["presentation_id"],
            "presented_version": plan["presented_version"],
            "selection_version": plan["selection_version"],
            "selection_digest": plan["selection_digest"],
            "plan_digest": plan["plan_digest"],
            "authority_digest": plan["authority_digest"],
        }

    def _reserve(
        self,
        execution_bindings: list[dict[str, object]] | None,
        *,
        now: str = STARTED_AT,
        idempotency_key: str = "start-key-execution-0001",
        request_hash: str = "start-request-execution-0001",
    ) -> tuple[dict[str, object], bool]:
        plan = self.fixture["plan"]
        assert isinstance(plan, dict)
        return self.store.reserve_job(
            str(plan["plan_id"]),
            "confirmation-hash-execution-0001",
            idempotency_key,
            request_hash,
            now,
            bindings=self._bindings(),
            execution_bindings=execution_bindings,
        )

    def _start_outcome_and_bundle(
        self, item_specs: list[dict[str, object]]
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        job, replayed = self._reserve([copy.deepcopy(self.fixture["execution"])])
        self.assertFalse(replayed)
        job_id = str(job["job_id"])
        self.store.start_job_execution(job_id)
        outcome = self.store.start_acquisition_outcome(
            job_id, RESOURCE_ID, metadata={"attempt": 1}
        )
        bundle = self.store.persist_asset_bundle(
            job_id, RESOURCE_ID, item_specs=item_specs
        )
        return job, outcome, bundle

    @staticmethod
    def _ready_item(
        role: str,
        position: int,
        *,
        filename: str,
        digest_character: str,
        required: bool,
    ) -> dict[str, object]:
        return {
            "role": role,
            "position": position,
            "status": "ready",
            "required": required,
            "local_path": f"/controlled/{filename}",
            "byte_size": position + 1,
            "media_type": "text/html" if filename.endswith(".html") else "application/octet-stream",
            "sha256": digest_character * 64,
            "filename": filename,
            "metadata": {},
        }

    def _lookup_replay(
        self,
        *,
        flow_id: str | None = None,
        plan_id: str | None = None,
        request_hash: str = "start-request-execution-0001",
    ) -> dict[str, object] | None:
        plan = self.fixture["plan"]
        assert isinstance(plan, dict)
        return self.store.lookup_download_start_replay(
            idempotency_key="start-key-execution-0001",
            request_hash=request_hash,
            flow_id=flow_id or str(self.fixture["flow_id"]),
            plan_id=plan_id or str(plan["plan_id"]),
        )

    def test_download_start_replay_lookup_misses_without_idempotency_record(self) -> None:
        self.assertIsNone(self._lookup_replay())

    def test_download_start_replay_lookup_returns_existing_job_without_side_effects(self) -> None:
        job, replayed = self._reserve([copy.deepcopy(self.fixture["execution"])])
        self.assertFalse(replayed)

        with self.store._connect() as connection:
            job_count_before = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            execution_count_before = connection.execute(
                "SELECT COUNT(*) FROM job_execution_items"
            ).fetchone()[0]

        replay = self._lookup_replay()
        self.assertIsNotNone(replay)
        assert replay is not None
        self.assertEqual(job["job_id"], replay["job_id"])
        self.assertEqual(job, replay)

        with self.store._connect() as connection:
            self.assertEqual(
                job_count_before,
                connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            )
            self.assertEqual(
                execution_count_before,
                connection.execute("SELECT COUNT(*) FROM job_execution_items").fetchone()[0],
            )

    def test_download_start_replay_lookup_rejects_hash_and_binding_conflicts(self) -> None:
        self._reserve([copy.deepcopy(self.fixture["execution"])])

        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._lookup_replay(request_hash="different-start-request-hash")
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._lookup_replay(flow_id="flow-different")
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._lookup_replay(plan_id="plan-different")

    def test_download_start_replay_lookup_rejects_missing_execution_authority(self) -> None:
        job, replayed = self._reserve([copy.deepcopy(self.fixture["execution"])])
        self.assertFalse(replayed)
        with self.store.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM job_execution_items WHERE job_id = ?",
                (job["job_id"],),
            )

        with self.assertRaisesRegex(RuntimeError, "execution_binding_missing"):
            self._lookup_replay()

    def test_reservation_persists_fresh_authority_and_outcome_traceability(self) -> None:
        execution = copy.deepcopy(self.fixture["execution"])
        job, replayed = self._reserve([execution])
        self.assertFalse(replayed)

        items = self.store.get_job_execution_items(str(job["job_id"]))
        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual("landing_page", item["capability_scope"])
        self.assertEqual("web_materialize", item["strategy"])
        self.assertEqual(item["execution_binding_digest"], item["binding_digest"])
        self.assertNotEqual(item["plan_binding_digest"], item["execution_binding_digest"])
        self.assertEqual(STARTED_AT, item["revalidated_at"])

        reopened = Store(self.database)
        self.assertEqual(items, reopened.get_job_execution_items(str(job["job_id"])))
        reopened.start_job_execution(
            str(job["job_id"]), started_at="2026-08-08T12:00:30+00:00"
        )
        outcome = reopened.start_acquisition_outcome(
            str(job["job_id"]),
            RESOURCE_ID,
            metadata={"attempt": 1},
            started_at="2026-08-08T12:01:00+00:00",
        )
        self.assertEqual("landing_page", outcome["planned_scope"])
        self.assertEqual("web_materialize", outcome["planned_strategy"])
        self.assertEqual(item["plan_binding_digest"], outcome["plan_binding_digest"])
        self.assertEqual(
            item["execution_binding_digest"], outcome["execution_binding_digest"]
        )

        exact_actual = {
            "actual_strategy": "web_materialize",
            "actual_provider_id": "generic-web-materializer",
            "actual_provider_version": "1.0.0",
            "bundle_id": "bundle_missing_execution_authority",
            "asset_ids": ["asset_missing_execution_authority"],
            "metadata": {"attempt": 1},
        }
        for terminal_status in ("succeeded", "partial"):
            with self.subTest(status=terminal_status):
                with self.assertRaisesRegex(
                    ValueError, "acquisition_outcome_conflict"
                ):
                    reopened.complete_acquisition_outcome(
                        str(job["job_id"]),
                        RESOURCE_ID,
                        status=terminal_status,
                        actual_scope="metadata",
                        **exact_actual,
                    )
        with self.assertRaisesRegex(RuntimeError, "strategy_binding_conflict"):
            reopened.complete_acquisition_outcome(
                str(job["job_id"]),
                RESOURCE_ID,
                status="succeeded",
                actual_scope="landing_page",
                **{**exact_actual, "actual_strategy": "direct_file"},
            )
        with self.assertRaisesRegex(RuntimeError, "provider_binding_conflict"):
            reopened.complete_acquisition_outcome(
                str(job["job_id"]),
                RESOURCE_ID,
                status="succeeded",
                actual_scope="landing_page",
                **{**exact_actual, "actual_provider_id": "other-provider"},
            )
        with self.assertRaisesRegex(RuntimeError, "provider_binding_conflict"):
            reopened.complete_acquisition_outcome(
                str(job["job_id"]),
                RESOURCE_ID,
                status="succeeded",
                actual_scope="landing_page",
                **{**exact_actual, "actual_provider_version": "2.0.0"},
            )
        with self.assertRaisesRegex(ValueError, "acquisition_outcome_bundle_mismatch"):
            reopened.complete_acquisition_outcome(
                str(job["job_id"]),
                RESOURCE_ID,
                status="succeeded",
                actual_scope="landing_page",
                **exact_actual,
            )
        self.assertEqual(
            "running",
            reopened.get_acquisition_outcome(str(job["job_id"]), RESOURCE_ID)["status"],
        )

        completed = reopened.complete_acquisition_outcome(
            str(job["job_id"]),
            RESOURCE_ID,
            status="failed",
            actual_scope=None,
            actual_strategy=None,
            actual_provider_id=None,
            actual_provider_version=None,
            failure_code="UPSTREAM_UNAVAILABLE",
            metadata={"attempt": 1},
            completed_at="2026-08-08T12:02:00+00:00",
        )
        self.assertEqual(
            item["execution_binding_digest"], completed["execution_binding_digest"]
        )
        digest_projection = dict(completed)
        outcome_digest = digest_projection.pop("outcome_digest")
        self.assertEqual(Store._request_digest(digest_projection), outcome_digest)
        replayed_completion = reopened.complete_acquisition_outcome(
            str(job["job_id"]),
            RESOURCE_ID,
            status="failed",
            actual_scope=None,
            actual_strategy=None,
            actual_provider_id=None,
            actual_provider_version=None,
            failure_code="UPSTREAM_UNAVAILABLE",
            metadata={"attempt": 1},
        )
        self.assertEqual(completed, replayed_completion)
        with self.assertRaisesRegex(ValueError, "acquisition_outcome_conflict"):
            reopened.complete_acquisition_outcome(
                str(job["job_id"]),
                RESOURCE_ID,
                status="failed",
                actual_scope=None,
                actual_strategy=None,
                actual_provider_id=None,
                actual_provider_version=None,
                failure_code="DIFFERENT_FAILURE",
                metadata={"attempt": 1},
            )

    def test_idempotent_replay_uses_the_immutable_execution_snapshot(self) -> None:
        execution = copy.deepcopy(self.fixture["execution"])
        job, replayed = self._reserve([execution])
        self.assertFalse(replayed)
        replay, replayed = self._reserve(
            None,
            # Neither the expired Plan nor later expiration of execution TTLs
            # can reinterpret an already-created immutable Job.  The Service
            # therefore need not probe fresh authority before an idempotent hit.
            now="2100-01-01T00:00:00+00:00",
        )
        self.assertTrue(replayed)
        self.assertEqual(job, replay)

        explicit_replay, replayed = self._reserve(
            [execution], now="2100-01-01T00:00:00+00:00"
        )
        self.assertTrue(replayed)
        self.assertEqual(job, explicit_replay)

        newly_observed = copy.deepcopy(execution)
        newly_observed["provider_version"] = "2.0.0"
        observation_independent_replay, replayed = self._reserve(
            [newly_observed], now="2100-01-01T00:00:00+00:00"
        )
        self.assertTrue(replayed)
        self.assertEqual(job, observation_independent_replay)
        self.assertEqual(
            execution["provider_version"],
            self.store.get_job_execution_items(str(job["job_id"]))[0][
                "provider_version"
            ],
        )

    def test_failed_reservation_rolls_back_every_authoritative_state_change(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "execution_binding_missing"):
            self._reserve(None)

        plan = self.fixture["plan"]
        assert isinstance(plan, dict)
        with self.store._connect() as connection:
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE plan_id = ?", (plan["plan_id"],)
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM job_execution_items").fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT used FROM download_plans WHERE plan_id = ?", (plan["plan_id"],)
                ).fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM idempotency_keys "
                    "WHERE scope = 'download.start' AND key = ?",
                    ("start-key-execution-0001",),
                ).fetchone()[0],
            )
            self.assertEqual(
                "prepared",
                connection.execute(
                    "SELECT status FROM flows WHERE flow_id = ?", (self.fixture["flow_id"],)
                ).fetchone()[0],
            )

    def test_execution_drift_and_fresh_ttl_fail_closed(self) -> None:
        drifted = copy.deepcopy(self.fixture["execution"])
        drifted["provider_version"] = "2.0.0"
        with self.assertRaisesRegex(RuntimeError, "execution_binding_conflict"):
            self._reserve([drifted])

        expired_readiness = self._readiness(
            "ready_job_expired_0001",
            observed_at="2026-08-08T10:00:00+00:00",
            expires_at="2026-08-08T11:00:00+00:00",
        )
        expired_readiness_eligibility = self._eligibility(
            "elig_job_expired_readiness_0001",
            expired_readiness,
            evaluated_at="2026-08-08T10:01:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        with self.assertRaisesRegex(RuntimeError, "readiness_expired"):
            self._reserve(
                [self._execution_with(expired_readiness, expired_readiness_eligibility)]
            )

        valid_readiness = self._readiness(
            "ready_job_eligibility_expired_0001",
            observed_at="2026-08-08T10:00:00+00:00",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        expired_eligibility = self._eligibility(
            "elig_job_expired_0001",
            valid_readiness,
            evaluated_at="2026-08-08T10:01:00+00:00",
            expires_at="2026-08-08T11:00:00+00:00",
        )
        with self.assertRaisesRegex(RuntimeError, "eligibility_expired"):
            self._reserve([self._execution_with(valid_readiness, expired_eligibility)])

    def test_legacy_jobs_never_gain_inferred_execution_authority(self) -> None:
        plan = self.fixture["plan"]
        assert isinstance(plan, dict)
        job, _ = self._reserve([copy.deepcopy(self.fixture["execution"])])
        self.store.update_job(str(job["job_id"]), status="succeeded", progress=100)
        with self.assertRaisesRegex(ValueError, "acquisition_outcome_conflict"):
            self.store.start_acquisition_outcome(str(job["job_id"]), RESOURCE_ID)
        self.assertIsNone(
            self.store.get_acquisition_outcome(str(job["job_id"]), RESOURCE_ID)
        )

        with self.store.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, flow_id, plan_id, status, progress, created_at, updated_at
                ) VALUES (
                    'job_legacy_without_execution', ?, ?, 'queued', 0, ?, ?
                )
                """,
                (self.fixture["flow_id"], plan["plan_id"], STARTED_AT, STARTED_AT),
            )

        with self.assertRaisesRegex(RuntimeError, "execution_binding_missing"):
            self.store.get_job_execution_items("job_legacy_without_execution")
        with self.assertRaisesRegex(RuntimeError, "execution_binding_missing"):
            self.store.start_acquisition_outcome(
                "job_legacy_without_execution", RESOURCE_ID
            )
        with self.assertRaisesRegex(KeyError, "job_not_found"):
            self.store.get_job_execution_items("job_missing")

    def test_cancellation_before_outcome_blocks_late_runner_start(self) -> None:
        job, _ = self._reserve([copy.deepcopy(self.fixture["execution"])])
        job_id = str(job["job_id"])
        self.store.start_job_execution(job_id)
        self.store.request_job_cancellation(job_id)

        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self.store.start_acquisition_outcome(job_id, RESOURCE_ID)
        self.assertIsNone(self.store.get_acquisition_outcome(job_id, RESOURCE_ID))
        self.assertEqual("cancelling", self.store.get_job(job_id)["status"])

    def test_cancellation_after_outcome_blocks_late_completion(self) -> None:
        job, _ = self._reserve([copy.deepcopy(self.fixture["execution"])])
        job_id = str(job["job_id"])
        self.store.start_job_execution(job_id)
        running = self.store.start_acquisition_outcome(
            job_id, RESOURCE_ID, metadata={"attempt": 1}
        )
        self.store.request_job_cancellation(job_id)

        with self.assertRaisesRegex(ValueError, "job_cancelling"):
            self.store.complete_acquisition_outcome(
                job_id,
                RESOURCE_ID,
                status="failed",
                actual_scope=None,
                actual_strategy=None,
                actual_provider_id=None,
                actual_provider_version=None,
                failure_code="DOWNLOAD_FAILED",
                failure_message="late runner result",
                metadata={"attempt": 1},
            )
        unchanged = self.store.get_acquisition_outcome(job_id, RESOURCE_ID)
        assert unchanged is not None
        self.assertEqual("running", unchanged["status"])
        self.assertEqual(running["outcome_digest"], unchanged["outcome_digest"])

        self.store.finalize_job_cancellation(job_id)
        cancelled = self.store.get_acquisition_outcome(job_id, RESOURCE_ID)
        assert cancelled is not None
        self.assertEqual("cancelled", cancelled["status"])

    def test_outcome_requires_exact_ready_bundle_asset_projection(self) -> None:
        job, _, bundle = self._start_outcome_and_bundle(
            [
                self._ready_item(
                    "primary", 0, filename="lesson.html", digest_character="a", required=True
                ),
                self._ready_item(
                    "attachment", 1, filename="notes.bin", digest_character="b", required=False
                ),
            ]
        )
        job_id = str(job["job_id"])
        attachment_id = str(bundle["items"][1]["asset_id"])
        with self.assertRaisesRegex(
            ValueError, "acquisition_outcome_asset_mismatch"
        ):
            self.store.complete_acquisition_outcome(
                job_id,
                RESOURCE_ID,
                status="succeeded",
                actual_scope="landing_page",
                actual_strategy="web_materialize",
                actual_provider_id="generic-web-materializer",
                actual_provider_version="1.0.0",
                bundle_id=str(bundle["bundle_id"]),
                asset_ids=[attachment_id],
                metadata={"attempt": 1},
            )
        self.assertEqual(
            "running",
            self.store.get_acquisition_outcome(job_id, RESOURCE_ID)["status"],
        )

    def test_failed_outcome_quarantines_existing_usable_bundle(self) -> None:
        job, _, bundle = self._start_outcome_and_bundle(
            [
                self._ready_item(
                    "primary", 0, filename="failed.html", digest_character="c", required=True
                )
            ]
        )
        job_id = str(job["job_id"])
        asset_id = str(bundle["items"][0]["asset_id"])
        failed = self.store.complete_acquisition_outcome(
            job_id,
            RESOURCE_ID,
            status="failed",
            actual_scope="landing_page",
            actual_strategy="web_materialize",
            actual_provider_id="generic-web-materializer",
            actual_provider_version="1.0.0",
            failure_code="DOWNLOAD_FAILED",
            failure_message="provider failed after staging",
            metadata={"attempt": 1},
        )
        self.assertEqual("failed", failed["status"])
        refreshed = self.store.get_asset_bundle(str(bundle["bundle_id"]))
        assert refreshed is not None
        self.assertEqual("failed", refreshed["status"])
        self.assertEqual("quarantined", refreshed["items"][0]["status"])
        self.assertEqual("quarantined", self.store.get_asset(asset_id)["status"])
        self.assertEqual([], self.store.get_job(job_id)["asset_ids"])
        with self.assertRaisesRegex(ValueError, "job_success_without_primary"):
            self.store.finalize_job_success(job_id)

    def test_finalize_success_requires_outcome_for_every_execution_item(self) -> None:
        job, _, bundle = self._start_outcome_and_bundle(
            [
                self._ready_item(
                    "primary", 0, filename="missing-outcome.html", digest_character="d", required=True
                )
            ]
        )
        job_id = str(job["job_id"])
        with self.store.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM acquisition_outcomes WHERE job_id = ?",
                (job_id,),
            )
        with self.assertRaisesRegex(ValueError, "job_outcome_incomplete"):
            self.store.finalize_job_success(job_id)
        self.assertEqual("running", self.store.get_job(job_id)["status"])
        self.assertEqual("ready", self.store.get_asset(bundle["items"][0]["asset_id"])["status"])

    def test_terminal_outcome_allows_exact_bundle_replay_but_blocks_reopen(self) -> None:
        specs = [
            self._ready_item(
                "primary", 0, filename="terminal.html", digest_character="e", required=True
            ),
            {
                "role": "attachment",
                "position": 1,
                "status": "failed",
                "required": False,
                "metadata": {},
            },
        ]
        job, outcome, bundle = self._start_outcome_and_bundle(specs)
        job_id = str(job["job_id"])
        primary_id = str(bundle["items"][0]["asset_id"])
        terminal = self.store.complete_acquisition_outcome(
            job_id,
            RESOURCE_ID,
            status="partial",
            actual_scope="landing_page",
            actual_strategy="web_materialize",
            actual_provider_id="generic-web-materializer",
            actual_provider_version="1.0.0",
            bundle_id=str(bundle["bundle_id"]),
            asset_ids=[primary_id],
            metadata={"attempt": 1},
        )
        replay = self.store.persist_asset_bundle(job_id, RESOURCE_ID, item_specs=specs)
        self.assertEqual(bundle["bundle_id"], replay["bundle_id"])
        self.assertEqual(bundle["updated_at"], replay["updated_at"])
        changed = [
            self._ready_item(
                "primary", 0, filename="replacement.html", digest_character="f", required=True
            )
        ]
        with self.assertRaisesRegex(ValueError, "acquisition_outcome_not_running"):
            self.store.persist_asset_bundle(job_id, RESOURCE_ID, item_specs=changed)
        self.assertEqual(
            terminal["outcome_digest"],
            self.store.get_acquisition_outcome(job_id, RESOURCE_ID)["outcome_digest"],
        )
        self.assertEqual([primary_id], self.store.get_job(job_id)["asset_ids"])
        self.assertEqual("ready", self.store.get_asset(primary_id)["status"])
        self.assertEqual(outcome["outcome_id"], terminal["outcome_id"])

        self.store.request_job_cancellation(job_id)
        self.store.finalize_job_cancellation(job_id)
        self.assertEqual("quarantined", self.store.get_asset(primary_id)["status"])
        terminal_replay = self.store.complete_acquisition_outcome(
            job_id,
            RESOURCE_ID,
            status="partial",
            actual_scope="landing_page",
            actual_strategy="web_materialize",
            actual_provider_id="generic-web-materializer",
            actual_provider_version="1.0.0",
            bundle_id=str(bundle["bundle_id"]),
            asset_ids=[primary_id],
            metadata={"attempt": 1},
        )
        self.assertEqual(terminal, terminal_replay)

    def test_finalize_cancellation_requires_persisted_request(self) -> None:
        job, _ = self._reserve([copy.deepcopy(self.fixture["execution"])])
        job_id = str(job["job_id"])
        self.store.start_job_execution(job_id)
        with self.assertRaisesRegex(ValueError, "job_not_cancelling"):
            self.store.finalize_job_cancellation(job_id)
        self.assertEqual("running", self.store.get_job(job_id)["status"])

    def test_strategy_to_policy_action_mapping_is_exact(self) -> None:
        self.assertEqual("download", Store._eligibility_action_for_strategy("direct_file"))
        self.assertEqual(
            "materialize", Store._eligibility_action_for_strategy("web_materialize")
        )
        self.assertEqual(
            "materialize", Store._eligibility_action_for_strategy("web_capture")
        )
        with self.assertRaisesRegex(RuntimeError, "capability_strategy_mismatch"):
            Store._eligibility_action_for_strategy("platform_resource")


if __name__ == "__main__":
    unittest.main()
