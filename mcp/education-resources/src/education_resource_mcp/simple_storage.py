"""Simplified acquisition persistence for the 0037 cutover.

The existing Store still owns retrieval, inspection, assets, archive, and
idempotency primitives.  This subclass replaces only the acquisition state
path with three business tables:

- acquisition_plan_items: what the user confirmed;
- job_items: the immutable per-resource Job snapshot;
- execution_outcomes: what actually happened.

No new readiness/eligibility row or authority/binding/outcome digest is written.
Legacy v7 tables are backfilled for recovery but are not used by this path.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import sqlite3
from typing import Any

from .storage import (
    ACQUISITION_OUTCOME_STATUSES,
    CAPABILITY_SCOPES,
    RESOLUTION_CACHEABLE_STATUSES,
    Store as _LegacyStore,
    _json,
    _load,
    new_id,
    utc_now,
)


LATEST_SCHEMA_VERSION = 9
_STRATEGIES = frozenset({"direct_file", "web_materialize", "web_capture"})


def _bare_fingerprint(value: Any) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        text = text[7:]
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError("invalid_source_fingerprint")
    return text


class Store(_LegacyStore):
    """Old Store plus a simpler active acquisition state model."""

    def _apply_migrations(self) -> None:
        super()._apply_migrations()
        with self.transaction(immediate=True) as connection:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 8"
            ).fetchone()
            if applied is None:
                self._migration_simple_acquisition(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (8, ?, ?)",
                    ("simple_acquisition_state", utc_now()),
                )
                connection.execute("PRAGMA user_version = 8")
        with self.transaction(immediate=True) as connection:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 9"
            ).fetchone()
            if applied is None:
                self._migration_drop_legacy_acquisition_authority(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (9, ?, ?)",
                    ("drop_legacy_acquisition_authority", utc_now()),
                )
                connection.execute("PRAGMA user_version = 9")

    def _migration_simple_acquisition(self, connection: sqlite3.Connection) -> None:
        self._execute_statements(
            connection,
            """
            CREATE TABLE IF NOT EXISTS acquisition_plan_items (
                plan_id TEXT NOT NULL REFERENCES download_plans(plan_id) ON DELETE CASCADE,
                position INTEGER NOT NULL CHECK(position >= 0),
                resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                resolution_id TEXT,
                representation_id TEXT NOT NULL,
                planned_scope TEXT NOT NULL CHECK(planned_scope IN (
                    'primary_resource', 'representation', 'landing_page', 'metadata'
                )),
                strategy TEXT NOT NULL CHECK(strategy IN (
                    'direct_file', 'web_materialize', 'web_capture'
                )),
                provider_id TEXT NOT NULL,
                provider_version TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                representation_json TEXT NOT NULL CHECK(
                    json_valid(representation_json) AND json_type(representation_json) = 'object'
                ),
                PRIMARY KEY(plan_id, resource_id),
                UNIQUE(plan_id, position)
            );
            CREATE INDEX IF NOT EXISTS idx_acquisition_plan_items_provider
                ON acquisition_plan_items(provider_id, provider_version, strategy);

            CREATE TABLE IF NOT EXISTS job_items (
                job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                plan_id TEXT NOT NULL REFERENCES download_plans(plan_id),
                position INTEGER NOT NULL CHECK(position >= 0),
                resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                resolution_id TEXT,
                representation_id TEXT NOT NULL,
                planned_scope TEXT NOT NULL CHECK(planned_scope IN (
                    'primary_resource', 'representation', 'landing_page', 'metadata'
                )),
                strategy TEXT NOT NULL CHECK(strategy IN (
                    'direct_file', 'web_materialize', 'web_capture'
                )),
                provider_id TEXT NOT NULL,
                provider_version TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                representation_json TEXT NOT NULL CHECK(
                    json_valid(representation_json) AND json_type(representation_json) = 'object'
                ),
                revalidated_at TEXT NOT NULL,
                PRIMARY KEY(job_id, resource_id),
                UNIQUE(job_id, position)
            );
            CREATE INDEX IF NOT EXISTS idx_job_items_plan
                ON job_items(plan_id, position);
            CREATE INDEX IF NOT EXISTS idx_job_items_provider
                ON job_items(provider_id, provider_version, strategy);

            CREATE TABLE IF NOT EXISTS execution_outcomes (
                outcome_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                plan_id TEXT NOT NULL REFERENCES download_plans(plan_id),
                resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                planned_scope TEXT NOT NULL,
                planned_strategy TEXT NOT NULL,
                planned_provider_id TEXT NOT NULL,
                planned_provider_version TEXT NOT NULL,
                actual_scope TEXT,
                actual_strategy TEXT,
                actual_provider_id TEXT,
                actual_provider_version TEXT,
                status TEXT NOT NULL CHECK(status IN (
                    'running', 'succeeded', 'partial', 'failed', 'cancelled'
                )),
                failure_code TEXT,
                failure_message TEXT,
                retriable INTEGER NOT NULL DEFAULT 0 CHECK(retriable IN (0, 1)),
                bundle_id TEXT REFERENCES asset_bundles(bundle_id),
                asset_ids_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(job_id, resource_id)
            );
            CREATE INDEX IF NOT EXISTS idx_execution_outcomes_job
                ON execution_outcomes(job_id, started_at, outcome_id);
            """,
        )

        # Preserve recoverability for v7 Plans/Jobs without carrying their
        # hashes forward as execution credentials.
        old_plan_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='download_plan_items'"
        ).fetchone()
        if old_plan_table is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO acquisition_plan_items(
                    plan_id, position, resource_id, resolution_id,
                    representation_id, planned_scope, strategy,
                    provider_id, provider_version, source_fingerprint,
                    representation_json
                )
                SELECT plan_id, position, resource_id, resolution_id,
                       representation_id, capability_scope, strategy,
                       provider_id, provider_version,
                       CASE WHEN substr(source_fingerprint, 1, 7) = 'sha256:'
                            THEN substr(source_fingerprint, 8)
                            ELSE source_fingerprint END,
                       representation_json
                FROM download_plan_items
                """
            )
        old_job_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_execution_items'"
        ).fetchone()
        if old_job_table is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO job_items(
                    job_id, plan_id, position, resource_id, resolution_id,
                    representation_id, planned_scope, strategy,
                    provider_id, provider_version, source_fingerprint,
                    representation_json, revalidated_at
                )
                SELECT job_id, plan_id, position, resource_id, resolution_id,
                       representation_id, capability_scope, strategy,
                       provider_id, provider_version,
                       CASE WHEN substr(source_fingerprint, 1, 7) = 'sha256:'
                            THEN substr(source_fingerprint, 8)
                            ELSE source_fingerprint END,
                       representation_json, revalidated_at
                FROM job_execution_items
                """
            )
        old_outcome_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='acquisition_outcomes'"
        ).fetchone()
        if old_outcome_table is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO execution_outcomes(
                    outcome_id, job_id, plan_id, resource_id,
                    planned_scope, planned_strategy, planned_provider_id,
                    planned_provider_version, actual_scope, actual_strategy,
                    actual_provider_id, actual_provider_version, status,
                    failure_code, failure_message, retriable, bundle_id,
                    asset_ids_json, metadata_json, started_at, completed_at
                )
                SELECT outcome_id, job_id, plan_id, resource_id,
                       planned_scope, planned_strategy, planned_provider_id,
                       planned_provider_version, actual_scope, actual_strategy,
                       actual_provider_id, actual_provider_version, status,
                       failure_code, failure_message, retriable, bundle_id,
                       asset_ids_json, metadata_json, started_at, completed_at
                FROM acquisition_outcomes
                """
            )

    def _migration_drop_legacy_acquisition_authority(
        self, connection: sqlite3.Connection
    ) -> None:
        """Drop the v6/v7 acquisition proof tables after v8 backfill."""

        self._execute_statements(
            connection,
            """
            DROP TABLE IF EXISTS job_execution_items;
            DROP TABLE IF EXISTS acquisition_outcomes;
            DROP TABLE IF EXISTS download_plan_items;
            DROP TABLE IF EXISTS eligibility_decisions;
            DROP TABLE IF EXISTS capability_readiness_snapshots;
            """,
        )

    @staticmethod
    def _normalize_plan_items(
        items: list[dict[str, Any]] | None,
        *,
        resource_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(items, list) or len(items) != len(resource_ids):
            raise ValueError("plan_items_missing")
        normalized: list[dict[str, Any]] = []
        seen_resources: set[str] = set()
        for expected_position, raw in enumerate(items):
            if not isinstance(raw, Mapping):
                raise ValueError("invalid_plan_item")
            resource_id = str(raw.get("resource_id") or "")
            if resource_id != resource_ids[expected_position] or resource_id in seen_resources:
                raise ValueError("plan_item_resource_mismatch")
            seen_resources.add(resource_id)
            representation_id = str(raw.get("representation_id") or "")
            planned_scope = str(raw.get("planned_scope") or "")
            strategy = str(raw.get("strategy") or "")
            provider_id = str(raw.get("provider_id") or "")
            provider_version = str(raw.get("provider_version") or "")
            representation = raw.get("representation")
            if (
                not representation_id
                or planned_scope not in CAPABILITY_SCOPES
                or strategy not in _STRATEGIES
                or not provider_id
                or not provider_version
                or not isinstance(representation, Mapping)
            ):
                raise ValueError("invalid_plan_item")
            try:
                representation_copy = json.loads(
                    json.dumps(
                        representation,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("invalid_plan_item_representation") from exc
            normalized.append(
                {
                    "position": expected_position,
                    "resource_id": resource_id,
                    "resolution_id": (
                        str(raw["resolution_id"])
                        if raw.get("resolution_id") is not None
                        else None
                    ),
                    "representation_id": representation_id,
                    "planned_scope": planned_scope,
                    "strategy": strategy,
                    "provider_id": provider_id,
                    "provider_version": provider_version,
                    "source_fingerprint": _bare_fingerprint(raw.get("source_fingerprint")),
                    "representation": representation_copy,
                }
            )
        return normalized

    def create_plan(
        self,
        flow_id: str,
        presentation_id: str,
        presented_version: int,
        selection_version: int,
        selection_digest: str,
        options: dict[str, Any],
        confirmation_token: str,
        confirmation_hash: str,
        expires_at: str,
        *,
        idempotency_key: str,
        request_hash: str,
        plan_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        scope = f"resource_download_prepare:{flow_id}"
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            replay = self._replay_in_transaction(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            flow = connection.execute(
                "SELECT current_presentation_id, presented_version, selection_version FROM flows WHERE flow_id = ?",
                (flow_id,),
            ).fetchone()
            selection = connection.execute(
                "SELECT * FROM selections WHERE flow_id = ?", (flow_id,)
            ).fetchone()
            if flow is None:
                raise KeyError("flow_not_found")
            if selection is None or selection["status"] != "selected":
                raise LookupError("resource_not_selected")
            if int(selection["selection_version"]) != selection_version:
                raise RuntimeError("selection_version_conflict")
            if (
                selection["presentation_id"] != presentation_id
                or int(selection["presented_version"]) != int(presented_version)
            ):
                raise RuntimeError("presentation_version_conflict")
            if str(selection["selection_digest"]) != selection_digest:
                raise RuntimeError("selection_digest_conflict")
            if (
                int(flow["selection_version"]) != selection_version
                or flow["current_presentation_id"] != presentation_id
                or int(flow["presented_version"]) != int(presented_version)
            ):
                raise RuntimeError("selection_changed")
            resource_ids = _load(selection["selected_ids_json"], [])
            if not isinstance(resource_ids, list) or not resource_ids:
                raise LookupError("resource_not_selected")
            placeholders = ",".join("?" for _ in resource_ids)
            rows = connection.execute(
                f"""
                SELECT r.resource_id, r.platform, pi.display_position
                FROM resources r
                JOIN presentation_items pi ON pi.resource_id = r.resource_id
                WHERE r.flow_id = ? AND pi.presentation_id = ?
                  AND r.resource_id IN ({placeholders})
                """,
                (flow_id, presentation_id, *resource_ids),
            ).fetchall()
            by_id = {str(row["resource_id"]): dict(row) for row in rows}
            if any(resource_id not in by_id for resource_id in resource_ids):
                raise RuntimeError("resource_not_found")
            normalized_items = self._normalize_plan_items(
                plan_items, resource_ids=[str(item) for item in resource_ids]
            )
            plan_digest = self._request_digest(
                {
                    "flow_id": flow_id,
                    "presentation_id": presentation_id,
                    "presented_version": int(presented_version),
                    "selection_version": selection_version,
                    "selection_digest": selection_digest,
                    "resource_ids": resource_ids,
                    "options": options,
                    "items": normalized_items,
                }
            )
            plan_id = new_id("plan")
            connection.execute(
                """
                INSERT INTO download_plans(
                    plan_id, flow_id, presented_version, resource_ids_json,
                    options_json, confirmation_token, confirmation_hash, expires_at,
                    used, created_at, presentation_id, selection_version,
                    selection_digest, plan_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id, flow_id, int(presented_version), _json(resource_ids),
                    _json(options), confirmation_token, confirmation_hash, expires_at,
                    now, presentation_id, selection_version, selection_digest, plan_digest,
                ),
            )
            for item in normalized_items:
                connection.execute(
                    """
                    INSERT INTO acquisition_plan_items(
                        plan_id, position, resource_id, resolution_id,
                        representation_id, planned_scope, strategy,
                        provider_id, provider_version, source_fingerprint,
                        representation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id, item["position"], item["resource_id"], item["resolution_id"],
                        item["representation_id"], item["planned_scope"], item["strategy"],
                        item["provider_id"], item["provider_version"], item["source_fingerprint"],
                        _json(item["representation"]),
                    ),
                )
            result = {
                "flow_id": flow_id,
                "stage": "prepared",
                "plan_id": plan_id,
                "presentation_id": presentation_id,
                "presented_version": int(presented_version),
                "selection_version": selection_version,
                "selection_digest": selection_digest,
                "plan_digest": plan_digest,
                "expires_at": expires_at,
                "confirmation_required": True,
                "confirmation_token": confirmation_token,
                "items": [
                    {
                        "resource_id": item["resource_id"],
                        "selected_position": int(by_id[item["resource_id"]]["display_position"]),
                        "platform": by_id[item["resource_id"]]["platform"],
                        "representation_id": item["representation_id"],
                        "planned_scope": item["planned_scope"],
                        "planned_strategy": item["strategy"],
                        "planned_provider": {
                            "provider_id": item["provider_id"],
                            "version": item["provider_version"],
                            "scope": item["planned_scope"],
                        },
                        "planned_container": options["preferred_container"],
                        "estimated_size_bytes": item["representation"].get("estimated_size_bytes"),
                        "risks": [
                            {
                                "code": "PUBLIC_NETWORK_ACCESS",
                                "level": "low",
                                "message": "将按已确认的资源表示访问来源并写入隔离任务目录",
                            }
                        ],
                    }
                    for item in normalized_items
                ],
            }
            connection.execute(
                "UPDATE flows SET status = 'prepared', updated_at = ? WHERE flow_id = ?",
                (now, flow_id),
            )
            self._audit_in_transaction(
                connection,
                flow_id,
                "download.prepare",
                plan_id,
                {"selection_version": selection_version, "plan_digest": plan_digest},
                now,
            )
            self._put_idempotency_in_transaction(
                connection, scope, idempotency_key, request_hash, plan_id, result, now
            )
            return result

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM download_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            items = connection.execute(
                """
                SELECT * FROM acquisition_plan_items
                WHERE plan_id = ? ORDER BY position, resource_id
                """,
                (plan_id,),
            ).fetchall() if row is not None else []
        if row is None:
            return None
        result = dict(row)
        result["resource_ids"] = _load(result.pop("resource_ids_json"), [])
        result["options"] = _load(result.pop("options_json"), {})
        plan_items = []
        for item_row in items:
            item = dict(item_row)
            item.pop("plan_id", None)
            item["representation"] = _load(item.pop("representation_json"), {})
            plan_items.append(item)
        result["plan_items"] = plan_items
        return result

    def lookup_download_start_replay(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        flow_id: str,
        plan_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT result_id, request_hash FROM idempotency_keys WHERE scope='download.start' AND key=?",
                (idempotency_key,),
            ).fetchone()
            if previous is None:
                return None
            if previous["request_hash"] != request_hash:
                raise ValueError("idempotency_conflict")
            job = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (previous["result_id"],)
            ).fetchone()
            if job is None:
                raise RuntimeError("idempotency record points to a missing job")
            if str(job["flow_id"]) != flow_id or str(job["plan_id"]) != plan_id:
                raise ValueError("idempotency_conflict")
            item = connection.execute(
                "SELECT 1 FROM job_items WHERE job_id = ? LIMIT 1",
                (job["job_id"],),
            ).fetchone()
            if item is None:
                raise RuntimeError("job_item_missing")
            return self._decode_job(job)

    def reserve_job(
        self,
        plan_id: str,
        confirmation_hash: str,
        idempotency_key: str,
        request_hash: str,
        now: str,
        *,
        bindings: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        checked_now = self._normalize_authority_timestamp(now, "now")
        with self.transaction(immediate=True) as connection:
            previous = connection.execute(
                "SELECT result_id, request_hash FROM idempotency_keys WHERE scope='download.start' AND key=?",
                (idempotency_key,),
            ).fetchone()
            if previous is not None:
                if previous["request_hash"] != request_hash:
                    raise ValueError("idempotency_conflict")
                job = connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (previous["result_id"],)
                ).fetchone()
                if job is None or str(job["plan_id"]) != plan_id:
                    raise ValueError("idempotency_conflict")
                return self._decode_job(job), True

            plan = connection.execute(
                "SELECT * FROM download_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise LookupError("plan_not_found")
            if not isinstance(bindings, Mapping):
                raise RuntimeError("plan_binding_mismatch")
            try:
                bound_presented = int(bindings.get("presented_version"))
                bound_selection = int(bindings.get("selection_version"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("plan_binding_mismatch") from exc
            if (
                plan["presentation_id"] != bindings.get("presentation_id")
                or int(plan["presented_version"]) != bound_presented
                or int(plan["selection_version"]) != bound_selection
                or plan["selection_digest"] != bindings.get("selection_digest")
                or plan["plan_digest"] != bindings.get("plan_digest")
            ):
                raise RuntimeError("plan_binding_mismatch")
            if plan["confirmation_hash"] != confirmation_hash:
                raise PermissionError("confirmation_invalid")
            if bool(plan["used"]):
                raise RuntimeError("plan_used")
            if self._normalize_authority_timestamp(plan["expires_at"], "plan_expires_at") <= checked_now:
                raise TimeoutError("plan_expired")

            plan_ids = _load(plan["resource_ids_json"], [])
            if not isinstance(plan_ids, list) or not plan_ids:
                raise RuntimeError("plan_item_missing")
            item_rows = connection.execute(
                """
                SELECT * FROM acquisition_plan_items
                WHERE plan_id = ? ORDER BY position, resource_id
                """,
                (plan_id,),
            ).fetchall()
            if (
                len(item_rows) != len(plan_ids)
                or [str(row["resource_id"]) for row in item_rows] != [str(x) for x in plan_ids]
            ):
                raise RuntimeError("plan_item_missing")
            for item in item_rows:
                resolution_id = item["resolution_id"]
                if not isinstance(resolution_id, str) or not resolution_id:
                    raise RuntimeError("resolution_stale")
                resolution = connection.execute(
                    """
                    SELECT resolution_status, source_fingerprint
                    FROM resource_resolutions
                    WHERE resolution_id = ? AND flow_id = ? AND resource_id = ?
                    """,
                    (resolution_id, plan["flow_id"], item["resource_id"]),
                ).fetchone()
                if (
                    resolution is None
                    or str(resolution["resolution_status"]) not in RESOLUTION_CACHEABLE_STATUSES
                    or _bare_fingerprint(resolution["source_fingerprint"])
                    != _bare_fingerprint(item["source_fingerprint"])
                ):
                    raise RuntimeError("resolution_stale")

            selection = connection.execute(
                "SELECT * FROM selections WHERE flow_id = ?", (plan["flow_id"],)
            ).fetchone()
            flow = connection.execute(
                "SELECT * FROM flows WHERE flow_id = ?", (plan["flow_id"],)
            ).fetchone()
            if (
                selection is None
                or flow is None
                or selection["status"] != "selected"
                or selection["presentation_id"] != plan["presentation_id"]
                or flow["current_presentation_id"] != plan["presentation_id"]
                or int(selection["presented_version"]) != int(plan["presented_version"])
                or int(flow["presented_version"]) != int(plan["presented_version"])
                or int(selection["selection_version"]) != int(plan["selection_version"])
                or int(flow["selection_version"]) != int(plan["selection_version"])
                or selection["selection_digest"] != plan["selection_digest"]
                or _load(selection["selected_ids_json"], []) != plan_ids
            ):
                raise RuntimeError("selection_changed")

            job_id = new_id("job")
            connection.execute(
                """
                INSERT INTO jobs(job_id, flow_id, plan_id, status, progress, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', 0, ?, ?)
                """,
                (job_id, plan["flow_id"], plan_id, checked_now, checked_now),
            )
            for item in item_rows:
                connection.execute(
                    """
                    INSERT INTO job_items(
                        job_id, plan_id, position, resource_id, resolution_id,
                        representation_id, planned_scope, strategy,
                        provider_id, provider_version, source_fingerprint,
                        representation_json, revalidated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id, plan_id, item["position"], item["resource_id"],
                        item["resolution_id"], item["representation_id"], item["planned_scope"],
                        item["strategy"], item["provider_id"], item["provider_version"],
                        item["source_fingerprint"], item["representation_json"], checked_now,
                    ),
                )
            cursor = connection.execute(
                "UPDATE download_plans SET used=1 WHERE plan_id=? AND used=0",
                (plan_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("plan_used")
            connection.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, NULL, ?)",
                ("download.start", idempotency_key, request_hash, job_id, checked_now),
            )
            connection.execute(
                "UPDATE flows SET status='downloading', updated_at=? WHERE flow_id=?",
                (checked_now, plan["flow_id"]),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to reserve job")
            return self._decode_job(row), False

    @staticmethod
    def _decode_job_item(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        resource = {
            "resource_id": item["resource_id"],
            "platform": item.pop("_resource_platform"),
            "title": item.pop("_resource_title"),
            "source_url": item.pop("_resource_source_url"),
            "resource_type": item.pop("_resource_type"),
            "summary": item.pop("_resource_summary"),
            "metadata": _load(item.pop("_resource_metadata_json"), {}),
            "identity": _load(item.pop("_resource_identity_json"), {}),
        }
        item["resource"] = resource
        item["representation"] = _load(item.pop("representation_json"), {})
        return item

    def get_job_items(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            job = connection.execute(
                "SELECT 1 FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError("job_not_found")
            rows = connection.execute(
                """
                SELECT item.*,
                       resources.platform AS _resource_platform,
                       resources.title AS _resource_title,
                       resources.source_url AS _resource_source_url,
                       resources.resource_type AS _resource_type,
                       resources.summary AS _resource_summary,
                       resources.metadata_json AS _resource_metadata_json,
                       resources.identity_json AS _resource_identity_json
                FROM job_items AS item
                JOIN resources ON resources.resource_id = item.resource_id
                WHERE item.job_id=? ORDER BY item.position, item.resource_id
                """,
                (job_id,),
            ).fetchall()
        if not rows:
            raise RuntimeError("job_item_missing")
        return [self._decode_job_item(row) for row in rows]

    @staticmethod
    def _decode_execution_outcome(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["retriable"] = bool(result["retriable"])
        result["asset_ids"] = _load(result.pop("asset_ids_json"), [])
        result["metadata"] = _load(result.pop("metadata_json"), {})
        return result

    def start_acquisition_outcome(
        self,
        job_id: str,
        resource_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        started_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_metadata = self._normalize_outcome_metadata(metadata)
        observed_at = started_at or utc_now()
        with self.transaction(immediate=True) as connection:
            job = connection.execute(
                "SELECT plan_id, status FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError("job_not_found")
            item = connection.execute(
                """
                SELECT * FROM job_items WHERE job_id=? AND resource_id=?
                """,
                (job_id, resource_id),
            ).fetchone()
            if item is None:
                raise RuntimeError("job_item_missing")
            existing = connection.execute(
                "SELECT * FROM execution_outcomes WHERE job_id=? AND resource_id=?",
                (job_id, resource_id),
            ).fetchone()
            if existing is not None:
                result = self._decode_execution_outcome(existing)
                if result["metadata"] != normalized_metadata:
                    raise ValueError("acquisition_outcome_conflict")
                return result
            if str(job["status"]) in {"cancelling", "cancelled"}:
                raise ValueError("job_cancelling")
            if str(job["status"]) != "running":
                raise ValueError("acquisition_outcome_conflict")
            outcome_id = new_id("outcome")
            connection.execute(
                """
                INSERT INTO execution_outcomes(
                    outcome_id, job_id, plan_id, resource_id,
                    planned_scope, planned_strategy, planned_provider_id,
                    planned_provider_version, status, retriable,
                    asset_ids_json, metadata_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', 0, '[]', ?, ?)
                """,
                (
                    outcome_id, job_id, item["plan_id"], resource_id,
                    item["planned_scope"], item["strategy"], item["provider_id"],
                    item["provider_version"], _json(normalized_metadata), observed_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM execution_outcomes WHERE outcome_id=?", (outcome_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("failed_to_create_acquisition_outcome")
            return self._decode_execution_outcome(row)

    def complete_acquisition_outcome(
        self,
        job_id: str,
        resource_id: str,
        *,
        status: str,
        actual_scope: str | None,
        actual_strategy: str | None,
        actual_provider_id: str | None,
        actual_provider_version: str | None,
        bundle_id: str | None = None,
        asset_ids: list[str] | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
        retriable: bool = False,
        metadata: Mapping[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_status = str(status).strip().lower()
        if normalized_status not in ACQUISITION_OUTCOME_STATUSES - {"running"}:
            raise ValueError("invalid_acquisition_outcome_status")
        normalized_metadata = self._normalize_outcome_metadata(metadata)
        normalized_assets = list(asset_ids or [])
        if len(normalized_assets) != len(set(normalized_assets)):
            raise ValueError("invalid_acquisition_outcome_assets")
        finished_at = completed_at or utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM execution_outcomes WHERE job_id=? AND resource_id=?",
                (job_id, resource_id),
            ).fetchone()
            if row is None:
                raise LookupError("acquisition_outcome_not_started")
            current = self._decode_execution_outcome(row)
            if current["status"] != "running":
                return current
            job = connection.execute(
                "SELECT status FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError("job_not_found")
            if str(job["status"]) in {"cancelling", "cancelled"}:
                raise ValueError("job_cancelling")
            if str(job["status"]) != "running":
                raise ValueError("acquisition_outcome_conflict")
            planned = (
                str(current["planned_scope"]), str(current["planned_strategy"]),
                str(current["planned_provider_id"]), str(current["planned_provider_version"]),
            )
            actual = (
                actual_scope, actual_strategy, actual_provider_id, actual_provider_version
            )
            if any(value is not None for value in actual) and actual != planned:
                raise RuntimeError("provider_binding_conflict")
            if normalized_status in {"succeeded", "partial"}:
                if actual != planned or not bundle_id or not normalized_assets:
                    raise ValueError("acquisition_outcome_evidence_missing")
                bundle, ready_assets, ready_primary = self._bundle_asset_evidence(
                    connection, bundle_id, job_id, resource_id
                )
                expected_status = "succeeded" if normalized_status == "succeeded" else "partial"
                expected_completion = "complete" if normalized_status == "succeeded" else "partial"
                if (
                    str(bundle["status"]) != expected_status
                    or str(bundle["completion"]) != expected_completion
                    or len(ready_primary) != 1
                    or ready_assets != normalized_assets
                ):
                    raise ValueError("acquisition_outcome_asset_mismatch")
            else:
                if bundle_id is not None or normalized_assets:
                    raise ValueError("acquisition_outcome_assets_forbidden")
                if failure_code is None:
                    raise ValueError("acquisition_outcome_failure_missing")
            if normalized_status == "failed":
                self._quarantine_resource_bundle_in_transaction(
                    connection, job_id, resource_id,
                    bundle_status="failed", updated_at=finished_at,
                )
            connection.execute(
                """
                UPDATE execution_outcomes
                SET actual_scope=?, actual_strategy=?, actual_provider_id=?,
                    actual_provider_version=?, status=?, failure_code=?,
                    failure_message=?, retriable=?, bundle_id=?, asset_ids_json=?,
                    metadata_json=?, completed_at=?
                WHERE outcome_id=? AND status='running'
                """,
                (
                    actual_scope, actual_strategy, actual_provider_id, actual_provider_version,
                    normalized_status, failure_code, failure_message,
                    1 if retriable else 0, bundle_id, _json(normalized_assets),
                    _json(normalized_metadata), finished_at, current["outcome_id"],
                ),
            )
            updated = connection.execute(
                "SELECT * FROM execution_outcomes WHERE outcome_id=?",
                (current["outcome_id"],),
            ).fetchone()
            if updated is None:
                raise RuntimeError("failed_to_complete_acquisition_outcome")
            return self._decode_execution_outcome(updated)

    def _finalize_running_acquisition_outcomes_in_transaction(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        *,
        status: str,
        failure_code: str,
        failure_message: str | None,
        retriable: bool,
        completed_at: str,
    ) -> list[dict[str, Any]]:
        if status not in {"failed", "cancelled"}:
            raise ValueError("invalid_acquisition_outcome_cleanup_status")
        rows = connection.execute(
            "SELECT * FROM execution_outcomes WHERE job_id=? AND status='running'",
            (job_id,),
        ).fetchall()
        finalized = []
        for row in rows:
            connection.execute(
                """
                UPDATE execution_outcomes
                SET status=?, failure_code=?, failure_message=?, retriable=?,
                    bundle_id=NULL, asset_ids_json='[]', completed_at=?
                WHERE outcome_id=? AND status='running'
                """,
                (
                    status, failure_code, failure_message, 1 if retriable else 0,
                    completed_at, row["outcome_id"],
                ),
            )
            updated = connection.execute(
                "SELECT * FROM execution_outcomes WHERE outcome_id=?", (row["outcome_id"],)
            ).fetchone()
            if updated is not None:
                finalized.append(self._decode_execution_outcome(updated))
        return finalized

    def get_acquisition_outcome(self, job_id: str, resource_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM execution_outcomes WHERE job_id=? AND resource_id=?",
                (job_id, resource_id),
            ).fetchone()
        return self._decode_execution_outcome(row) if row is not None else None

    def get_acquisition_outcomes_for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_outcomes WHERE job_id=? ORDER BY started_at, outcome_id",
                (job_id,),
            ).fetchall()
        return [self._decode_execution_outcome(row) for row in rows]

    @staticmethod
    def _assert_bundle_mutation_authority(
        connection: sqlite3.Connection, job_id: str, resource_id: str
    ) -> None:
        item = connection.execute(
            """
            SELECT 1 FROM job_items AS item
            JOIN jobs AS job ON job.job_id=item.job_id AND job.plan_id=item.plan_id
            JOIN resources AS resource ON resource.resource_id=item.resource_id
             AND resource.flow_id=job.flow_id
            WHERE item.job_id=? AND item.resource_id=?
            """,
            (job_id, resource_id),
        ).fetchone()
        if item is None:
            raise RuntimeError("job_item_missing")
        outcome = connection.execute(
            "SELECT status FROM execution_outcomes WHERE job_id=? AND resource_id=?",
            (job_id, resource_id),
        ).fetchone()
        if outcome is None:
            raise LookupError("acquisition_outcome_not_started")
        if str(outcome["status"]) != "running":
            raise ValueError("acquisition_outcome_not_running")

    def finalize_job_success(
        self, job_id: str, *, completed_at: str | None = None
    ) -> dict[str, Any]:
        finished_at = completed_at or utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError("job_not_found")
            if str(row["status"]) == "succeeded":
                return self._decode_job(row)
            if str(row["status"]) in {"cancelling", "cancelled"}:
                raise ValueError("job_cancelling")
            if str(row["status"]) != "running":
                raise ValueError("job_not_succeedable")
            items = connection.execute(
                "SELECT resource_id FROM job_items WHERE job_id=? ORDER BY position, resource_id",
                (job_id,),
            ).fetchall()
            if not items:
                raise ValueError("job_outcome_incomplete")
            resource_ids = [str(item["resource_id"]) for item in items]
            outcomes = connection.execute(
                "SELECT * FROM execution_outcomes WHERE job_id=?",
                (job_id,),
            ).fetchall()
            by_resource = {
                str(outcome["resource_id"]): self._decode_execution_outcome(outcome)
                for outcome in outcomes
            }
            if set(by_resource) != set(resource_ids) or any(
                outcome["status"] == "running" for outcome in by_resource.values()
            ):
                raise ValueError("job_outcome_incomplete")
            claimed: list[str] = []
            primary_count = 0
            for resource_id in resource_ids:
                outcome = by_resource[resource_id]
                if outcome["status"] not in {"succeeded", "partial"}:
                    continue
                bundle_id = outcome.get("bundle_id")
                if not isinstance(bundle_id, str) or not bundle_id:
                    raise ValueError("job_asset_graph_conflict")
                bundle, ready_assets, ready_primary = self._bundle_asset_evidence(
                    connection, bundle_id, job_id, resource_id
                )
                expected_status = "succeeded" if outcome["status"] == "succeeded" else "partial"
                expected_completion = "complete" if outcome["status"] == "succeeded" else "partial"
                if (
                    str(bundle["status"]) != expected_status
                    or str(bundle["completion"]) != expected_completion
                    or len(ready_primary) != 1
                    or outcome.get("asset_ids") != ready_assets
                ):
                    raise ValueError("job_asset_graph_conflict")
                claimed.extend(ready_assets)
                primary_count += 1
            if primary_count < 1 or len(claimed) != len(set(claimed)):
                raise ValueError("job_success_without_primary")
            ready_rows = connection.execute(
                "SELECT asset_id FROM assets WHERE job_id=? AND status='ready'", (job_id,)
            ).fetchall()
            if {str(item["asset_id"]) for item in ready_rows} != set(claimed):
                raise ValueError("job_asset_graph_conflict")
            cursor = connection.execute(
                """
                UPDATE jobs SET status='succeeded', progress=100,
                    asset_ids_json=?, error_json=NULL, updated_at=?
                WHERE job_id=? AND status='running'
                """,
                (_json(claimed), finished_at, job_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("failed_to_finalize_job_success")
            updated = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if updated is None:
                raise RuntimeError("failed_to_finalize_job_success")
            return self._decode_job(updated)

    def _assert_asset_archivable_in_transaction(
        self, connection: sqlite3.Connection, asset_id: str
    ) -> dict[str, Any]:
        asset = connection.execute(
            """
            SELECT asset.*, job.status AS job_status, job.plan_id AS job_plan_id,
                   job.asset_ids_json AS job_asset_ids_json,
                   resource.platform, resource.resource_type, resource.title
            FROM assets AS asset
            JOIN jobs AS job ON job.job_id=asset.job_id
            JOIN resources AS resource ON resource.resource_id=asset.resource_id
            WHERE asset.asset_id=?
            """,
            (asset_id,),
        ).fetchone()
        if asset is None:
            raise KeyError(asset_id)
        if str(asset["status"]) != "ready" or str(asset["job_status"]) != "succeeded":
            raise ValueError("asset_not_archivable")
        job_assets = self._decode_bundle_json(asset["job_asset_ids_json"], [])
        if not isinstance(job_assets, list) or asset_id not in [str(x) for x in job_assets]:
            raise ValueError("asset_not_archivable")
        item = connection.execute(
            "SELECT 1 FROM job_items WHERE job_id=? AND plan_id=? AND resource_id=?",
            (asset["job_id"], asset["job_plan_id"], asset["resource_id"]),
        ).fetchone()
        outcome_row = connection.execute(
            "SELECT * FROM execution_outcomes WHERE job_id=? AND plan_id=? AND resource_id=?",
            (asset["job_id"], asset["job_plan_id"], asset["resource_id"]),
        ).fetchone()
        if item is None or outcome_row is None:
            raise ValueError("asset_not_archivable")
        outcome = self._decode_execution_outcome(outcome_row)
        if outcome["status"] not in {"succeeded", "partial"}:
            raise ValueError("asset_not_archivable")
        bundle_id = outcome.get("bundle_id")
        if not isinstance(bundle_id, str) or not bundle_id:
            raise ValueError("asset_not_archivable")
        relations = connection.execute(
            """
            SELECT bundle.status AS bundle_status, bundle.completion,
                   item.status AS item_status
            FROM asset_bundle_items AS item
            JOIN asset_bundles AS bundle ON bundle.bundle_id=item.bundle_id
            WHERE item.asset_id=? AND bundle.bundle_id=?
              AND bundle.job_id=? AND bundle.resource_id=?
            """,
            (asset_id, bundle_id, asset["job_id"], asset["resource_id"]),
        ).fetchall()
        if len(relations) != 1 or str(relations[0]["item_status"]) != "ready":
            raise ValueError("asset_not_archivable")
        expected_status = "succeeded" if outcome["status"] == "succeeded" else "partial"
        expected_completion = "complete" if outcome["status"] == "succeeded" else "partial"
        if (
            str(relations[0]["bundle_status"]) != expected_status
            or str(relations[0]["completion"]) != expected_completion
        ):
            raise ValueError("asset_not_archivable")
        _, ready_assets, ready_primary = self._bundle_asset_evidence(
            connection, bundle_id, str(asset["job_id"]), str(asset["resource_id"])
        )
        if (
            len(ready_primary) != 1
            or outcome.get("asset_ids") != ready_assets
            or asset_id not in ready_assets
        ):
            raise ValueError("asset_not_archivable")
        result = dict(asset)
        result.pop("job_status", None)
        result.pop("job_plan_id", None)
        result.pop("job_asset_ids_json", None)
        return result


__all__ = ["LATEST_SCHEMA_VERSION", "Store"]
