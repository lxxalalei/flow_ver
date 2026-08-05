"""SQLite state store for flows, presented resources, plans, jobs, and assets."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class Store:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            with self._connect() as connection:
                try:
                    if immediate:
                        connection.execute("BEGIN IMMEDIATE")
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def _initialize(self) -> None:
        with self.transaction() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS flows (
                    flow_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    presented_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS resources (
                    resource_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flows(flow_id) ON DELETE CASCADE,
                    presented_version INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    summary TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resources_flow_version
                    ON resources(flow_id, presented_version);

                CREATE TABLE IF NOT EXISTS selections (
                    flow_id TEXT PRIMARY KEY REFERENCES flows(flow_id) ON DELETE CASCADE,
                    presented_version INTEGER NOT NULL,
                    selected_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS download_plans (
                    plan_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flows(flow_id) ON DELETE CASCADE,
                    presented_version INTEGER NOT NULL,
                    resource_ids_json TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    confirmation_token TEXT NOT NULL,
                    confirmation_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flows(flow_id) ON DELETE CASCADE,
                    plan_id TEXT NOT NULL REFERENCES download_plans(plan_id),
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    asset_ids_json TEXT NOT NULL DEFAULT '[]',
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                    status TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS archive_entries (
                    archive_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL UNIQUE REFERENCES assets(asset_id),
                    library_path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(scope, key)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    flow_id TEXT,
                    action TEXT NOT NULL,
                    object_id TEXT,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS search_result_sets (
                    result_set_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flows(flow_id) ON DELETE CASCADE,
                    search_run_id TEXT NOT NULL UNIQUE,
                    result_version INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    failures_json TEXT NOT NULL,
                    platform_runs_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    UNIQUE(flow_id, result_version)
                );
                CREATE INDEX IF NOT EXISTS idx_result_sets_flow
                    ON search_result_sets(flow_id, result_version DESC);

                CREATE TABLE IF NOT EXISTS presentations (
                    presentation_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL REFERENCES flows(flow_id) ON DELETE CASCADE,
                    result_set_id TEXT NOT NULL REFERENCES search_result_sets(result_set_id),
                    presented_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(flow_id, presented_version)
                );
                CREATE INDEX IF NOT EXISTS idx_presentations_flow
                    ON presentations(flow_id, presented_version DESC);

                CREATE TABLE IF NOT EXISTS presentation_items (
                    presentation_id TEXT NOT NULL REFERENCES presentations(presentation_id) ON DELETE CASCADE,
                    display_position INTEGER NOT NULL,
                    resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                    PRIMARY KEY(presentation_id, display_position),
                    UNIQUE(presentation_id, resource_id)
                );
                """
            )
            migrations = {
                "flows": [
                    ("task_version", "INTEGER NOT NULL DEFAULT 1"),
                    ("result_version", "INTEGER NOT NULL DEFAULT 0"),
                    ("selection_version", "INTEGER NOT NULL DEFAULT 0"),
                    ("current_result_set_id", "TEXT"),
                    ("current_presentation_id", "TEXT"),
                ],
                "resources": [
                    ("result_set_id", "TEXT"),
                    ("result_position", "INTEGER"),
                ],
                "selections": [
                    ("presentation_id", "TEXT"),
                    ("selection_version", "INTEGER NOT NULL DEFAULT 0"),
                    ("selection_digest", "TEXT NOT NULL DEFAULT ''"),
                ],
                "download_plans": [
                    ("presentation_id", "TEXT"),
                    ("selection_version", "INTEGER NOT NULL DEFAULT 0"),
                    ("selection_digest", "TEXT NOT NULL DEFAULT ''"),
                    ("plan_digest", "TEXT NOT NULL DEFAULT ''"),
                ],
                "search_result_sets": [
                    ("platform_runs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ],
            }
            for table, columns in migrations.items():
                existing = {
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for name, declaration in columns:
                    if name not in existing:
                        connection.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"
                        )

    def get_idempotency(self, scope: str, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM idempotency_keys WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = _load(result.pop("result_json"), None)
        return result

    def put_idempotency(
        self,
        scope: str,
        key: str,
        request_hash: str,
        result_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, ?, ?)",
                (
                    scope,
                    key,
                    request_hash,
                    result_id,
                    _json(result) if result is not None else None,
                    utc_now(),
                ),
            )

    def mark_incomplete_jobs_failed(self) -> int:
        error = _json(
            {
                "code": "INTERNAL_ERROR",
                "message": "MCP 服务重启，中断的本地任务未自动重放",
                "retriable": True,
            }
        )
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status = 'failed', error_json = ?, updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (error, utc_now()),
            )
            connection.execute(
                """
                UPDATE assets SET status = 'quarantined'
                WHERE job_id IN (SELECT job_id FROM jobs WHERE status = 'failed')
                """
            )
        return int(cursor.rowcount)

    @staticmethod
    def _request_digest(value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _replay_in_transaction(
        connection: sqlite3.Connection, scope: str, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT request_hash, result_json FROM idempotency_keys WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise ValueError("idempotency_conflict")
        result = _load(row["result_json"], None)
        return dict(result) if isinstance(result, dict) else None

    @staticmethod
    def _put_idempotency_in_transaction(
        connection: sqlite3.Connection,
        scope: str,
        key: str,
        request_hash: str,
        result_id: str,
        result: dict[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, ?, ?)",
            (scope, key, request_hash, result_id, _json(result), now),
        )

    @staticmethod
    def _audit_in_transaction(
        connection: sqlite3.Connection,
        flow_id: str | None,
        action: str,
        object_id: str | None,
        details: dict[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
            (new_id("evt"), flow_id, action, object_id, _json(details), now),
        )

    def create_flow_v2(
        self,
        task: dict[str, Any],
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = "v2:resource_flow_start"
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            replay = self._replay_in_transaction(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            flow_id = new_id("flow")
            topic = str(task["goal"]["topic"])
            connection.execute(
                """
                INSERT INTO flows(
                    flow_id, query, context_json, status, presented_version,
                    task_version, result_version, selection_version,
                    current_result_set_id, current_presentation_id, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', 0, 1, 0, 0, NULL, NULL, ?, ?)
                """,
                (flow_id, topic, _json(task), now, now),
            )
            result = {
                "flow_id": flow_id,
                "stage": "task_ready",
                "task_version": 1,
                "task": task,
                "created_at": now,
            }
            self._audit_in_transaction(
                connection, flow_id, "flow.start", flow_id, {"task_version": 1}, now
            )
            self._put_idempotency_in_transaction(
                connection, scope, idempotency_key, request_hash, flow_id, result, now
            )
        return result

    def create_result_set_v2(
        self,
        flow_id: str,
        resources: list[dict[str, Any]],
        *,
        query: str,
        task_version: int,
        filters: dict[str, Any],
        failures: list[dict[str, Any]],
        platform_runs: list[dict[str, Any]] | None = None,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = f"v2:resource_search:{flow_id}"
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            replay = self._replay_in_transaction(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            flow = connection.execute(
                "SELECT task_version, result_version FROM flows WHERE flow_id = ?",
                (flow_id,),
            ).fetchone()
            if flow is None:
                raise KeyError(flow_id)
            if int(flow["task_version"]) != int(task_version):
                raise RuntimeError("task_version_conflict")
            result_version = int(flow["result_version"]) + 1
            result_set_id = new_id("rset")
            search_run_id = new_id("search")
            status = "ready"
            connection.execute(
                """
                INSERT INTO search_result_sets(
                    result_set_id, flow_id, search_run_id, result_version, query,
                    filters_json, status, failures_json, platform_runs_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_set_id,
                    flow_id,
                    search_run_id,
                    result_version,
                    query,
                    _json(filters),
                    status,
                    _json(failures),
                    _json(platform_runs or []),
                    now,
                ),
            )
            for position, resource in enumerate(resources, 1):
                connection.execute(
                    """
                    INSERT INTO resources(
                        resource_id, flow_id, presented_version, platform, title,
                        source_url, resource_type, summary, metadata_json, created_at,
                        result_set_id, result_position
                    ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource["resource_id"],
                        flow_id,
                        resource["platform"],
                        resource["title"],
                        resource["source_url"],
                        resource["resource_type"],
                        resource.get("summary"),
                        _json(resource.get("metadata", {})),
                        now,
                        result_set_id,
                        position,
                    ),
                )
            connection.execute(
                "UPDATE presentations SET status = 'superseded' WHERE flow_id = ? AND status = 'active'",
                (flow_id,),
            )
            connection.execute(
                """
                UPDATE flows SET result_version = ?, current_result_set_id = ?,
                    current_presentation_id = NULL, status = 'reviewing', updated_at = ?
                WHERE flow_id = ?
                """,
                (result_version, result_set_id, now, flow_id),
            )
            candidates = []
            for resource in resources:
                metadata = resource.get("metadata") or {}
                candidate = {
                    "resource_id": resource["resource_id"],
                    "platform": resource["platform"],
                    "title": str(resource["title"])[:512],
                    "resource_type": resource["resource_type"],
                    "canonical_url": resource["source_url"],
                    "availability": "unknown",
                }
                if resource.get("summary"):
                    candidate["summary"] = str(resource["summary"])[:4000]
                if metadata.get("author"):
                    candidate["author"] = str(metadata["author"])[:256]
                if metadata.get("language"):
                    candidate["language"] = str(metadata["language"])[:35]
                candidates.append(candidate)
            result = {
                "flow_id": flow_id,
                "stage": "reviewing",
                "task_version": int(task_version),
                "search_run_id": search_run_id,
                "result_set_id": result_set_id,
                "result_version": result_version,
                "status": status,
                "platform_runs": platform_runs or [],
                "candidates": candidates,
                "failures": failures,
                "has_more": False,
                "created_at": now,
            }
            self._audit_in_transaction(
                connection,
                flow_id,
                "resource.search",
                result_set_id,
                {"query": query, "count": len(resources), "result_version": result_version},
                now,
            )
            self._put_idempotency_in_transaction(
                connection,
                scope,
                idempotency_key,
                request_hash,
                result_set_id,
                result,
                now,
            )
        return result

    def create_presentation_v2(
        self,
        flow_id: str,
        result_set_id: str,
        displayed_resource_ids: list[str],
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = f"v2:resource_presentation_save:{flow_id}"
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            replay = self._replay_in_transaction(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            flow = connection.execute(
                "SELECT presented_version, current_result_set_id FROM flows WHERE flow_id = ?",
                (flow_id,),
            ).fetchone()
            if flow is None:
                raise KeyError("flow_not_found")
            result_set = connection.execute(
                "SELECT flow_id FROM search_result_sets WHERE result_set_id = ?",
                (result_set_id,),
            ).fetchone()
            if result_set is None:
                raise LookupError("result_set_not_found")
            if result_set["flow_id"] != flow_id:
                raise PermissionError("result_set_flow_mismatch")
            if flow["current_result_set_id"] != result_set_id:
                raise RuntimeError("result_set_superseded")
            if len(displayed_resource_ids) != len(set(displayed_resource_ids)):
                raise ValueError("duplicate_resources")
            rows: list[sqlite3.Row] = []
            if displayed_resource_ids:
                placeholders = ",".join("?" for _ in displayed_resource_ids)
                rows = connection.execute(
                    f"SELECT resource_id FROM resources WHERE result_set_id = ? AND resource_id IN ({placeholders})",
                    (result_set_id, *displayed_resource_ids),
                ).fetchall()
                allowed = {row["resource_id"] for row in rows}
                if any(resource_id not in allowed for resource_id in displayed_resource_ids):
                    raise RuntimeError("resource_not_in_result_set")
            presented_version = int(flow["presented_version"]) + 1
            presentation_id = new_id("pres")
            connection.execute(
                "UPDATE presentations SET status = 'superseded' WHERE flow_id = ? AND status = 'active'",
                (flow_id,),
            )
            connection.execute(
                """
                INSERT INTO presentations(
                    presentation_id, flow_id, result_set_id, presented_version, status, created_at
                ) VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (presentation_id, flow_id, result_set_id, presented_version, now),
            )
            items = []
            for position, resource_id in enumerate(displayed_resource_ids, 1):
                connection.execute(
                    "INSERT INTO presentation_items VALUES (?, ?, ?)",
                    (presentation_id, position, resource_id),
                )
                items.append({"display_position": position, "resource_id": resource_id})
            connection.execute(
                """
                UPDATE flows SET presented_version = ?, current_presentation_id = ?,
                    status = 'presented', updated_at = ? WHERE flow_id = ?
                """,
                (presented_version, presentation_id, now, flow_id),
            )
            result = {
                "flow_id": flow_id,
                "stage": "presented",
                "result_set_id": result_set_id,
                "presentation_id": presentation_id,
                "presented_version": presented_version,
                "items": items,
                "empty": not items,
                "created_at": now,
            }
            self._audit_in_transaction(
                connection,
                flow_id,
                "presentation.save",
                presentation_id,
                {"result_set_id": result_set_id, "resource_ids": displayed_resource_ids},
                now,
            )
            self._put_idempotency_in_transaction(
                connection,
                scope,
                idempotency_key,
                request_hash,
                presentation_id,
                result,
                now,
            )
        return result

    def save_selection_v2(
        self,
        flow_id: str,
        presentation_id: str,
        presented_version: int,
        selected_positions: list[int],
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = f"v2:resource_selection_save:{flow_id}"
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
            if flow is None:
                raise KeyError("flow_not_found")
            presentation = connection.execute(
                "SELECT * FROM presentations WHERE presentation_id = ?", (presentation_id,)
            ).fetchone()
            if presentation is None:
                raise LookupError("presentation_not_found")
            if presentation["flow_id"] != flow_id:
                raise PermissionError("presentation_flow_mismatch")
            if (
                presentation["status"] != "active"
                or flow["current_presentation_id"] != presentation_id
                or int(flow["presented_version"]) != presented_version
                or int(presentation["presented_version"]) != presented_version
            ):
                raise RuntimeError("presentation_superseded")
            if len(selected_positions) != len(set(selected_positions)):
                raise ValueError("duplicate_positions")
            if any(position < 1 for position in selected_positions):
                raise ValueError("invalid_position")
            position_rows = connection.execute(
                """
                SELECT pi.display_position, pi.resource_id
                FROM presentation_items pi
                WHERE pi.presentation_id = ?
                ORDER BY pi.display_position
                """,
                (presentation_id,),
            ).fetchall()
            by_position = {int(row["display_position"]): row["resource_id"] for row in position_rows}
            invalid = [position for position in selected_positions if position not in by_position]
            if invalid:
                raise RuntimeError("position_not_presented")
            resource_ids = [by_position[position] for position in selected_positions]
            selection_version = int(flow["selection_version"]) + 1
            digest = self._request_digest(
                {
                    "presentation_id": presentation_id,
                    "presented_version": presented_version,
                    "selection_version": selection_version,
                    "resource_ids": resource_ids,
                }
            )
            status = "selected" if resource_ids else "cancelled"
            connection.execute(
                """
                INSERT INTO selections(
                    flow_id, presented_version, selected_ids_json, status, updated_at,
                    presentation_id, selection_version, selection_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(flow_id) DO UPDATE SET
                    presented_version = excluded.presented_version,
                    selected_ids_json = excluded.selected_ids_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    presentation_id = excluded.presentation_id,
                    selection_version = excluded.selection_version,
                    selection_digest = excluded.selection_digest
                """,
                (
                    flow_id,
                    presented_version,
                    _json(resource_ids),
                    status,
                    now,
                    presentation_id,
                    selection_version,
                    digest,
                ),
            )
            connection.execute(
                "UPDATE flows SET selection_version = ?, status = ?, updated_at = ? WHERE flow_id = ?",
                (selection_version, status, now, flow_id),
            )
            result = {
                "flow_id": flow_id,
                "stage": "selected" if resource_ids else "cancelled",
                "presentation_id": presentation_id,
                "presented_version": presented_version,
                "selection_version": selection_version,
                "selected_positions": selected_positions,
                "selected_resource_ids": resource_ids,
                "selection_digest": digest,
                "cancelled": not resource_ids,
                "updated_at": now,
            }
            self._audit_in_transaction(
                connection,
                flow_id,
                "selection.save",
                presentation_id,
                {
                    "selection_version": selection_version,
                    "positions": selected_positions,
                    "resource_ids": resource_ids,
                },
                now,
            )
            self._put_idempotency_in_transaction(
                connection,
                scope,
                idempotency_key,
                request_hash,
                str(selection_version),
                result,
                now,
            )
        return result

    def create_plan_v2(
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
    ) -> dict[str, Any]:
        scope = f"v2:resource_download_prepare:{flow_id}"
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
            if not resource_ids:
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
            by_id = {row["resource_id"]: dict(row) for row in rows}
            if any(resource_id not in by_id for resource_id in resource_ids):
                raise RuntimeError("resource_not_found")
            plan_digest = self._request_digest(
                {
                    "flow_id": flow_id,
                    "presentation_id": selection["presentation_id"],
                    "presented_version": int(selection["presented_version"]),
                    "selection_version": selection_version,
                    "selection_digest": selection_digest,
                    "resource_ids": resource_ids,
                    "options": options,
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
                    plan_id,
                    flow_id,
                    int(selection["presented_version"]),
                    _json(resource_ids),
                    _json(options),
                    confirmation_token,
                    confirmation_hash,
                    expires_at,
                    now,
                    selection["presentation_id"],
                    selection_version,
                    selection_digest,
                    plan_digest,
                ),
            )
            result = {
                "flow_id": flow_id,
                "stage": "prepared",
                "plan_id": plan_id,
                "presentation_id": selection["presentation_id"],
                "presented_version": int(selection["presented_version"]),
                "selection_version": selection_version,
                "selection_digest": selection_digest,
                "plan_digest": plan_digest,
                "expires_at": expires_at,
                "confirmation_required": True,
                "confirmation_token": confirmation_token,
                "items": [
                    {
                        "resource_id": resource_id,
                        "selected_position": int(
                            by_id[resource_id]["display_position"]
                        ),
                        "platform": by_id[resource_id]["platform"],
                        "planned_container": options["preferred_container"],
                        "estimated_size_bytes": None,
                        "effective_max_bytes": options["max_bytes"],
                        "risks": [
                            {
                                "code": "PUBLIC_NETWORK_ACCESS",
                                "level": "low",
                                "message": "将访问公开来源并写入隔离任务目录",
                            }
                        ],
                    }
                    for resource_id in resource_ids
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
                connection,
                scope,
                idempotency_key,
                request_hash,
                plan_id,
                result,
                now,
            )
        return result

    def get_result_set(self, result_set_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM search_result_sets WHERE result_set_id = ?", (result_set_id,)
            ).fetchone()
            if row is None:
                return None
            resource_rows = connection.execute(
                """
                SELECT * FROM resources
                WHERE result_set_id = ?
                ORDER BY result_position
                """,
                (result_set_id,),
            ).fetchall()
        result = dict(row)
        result["filters"] = _load(result.pop("filters_json"), {})
        result["failures"] = _load(result.pop("failures_json"), [])
        result["platform_runs"] = _load(result.pop("platform_runs_json", "[]"), [])
        resources = []
        for resource_row in resource_rows:
            resource = dict(resource_row)
            resource["metadata"] = _load(resource.pop("metadata_json"), {})
            resources.append(resource)
        result["resources"] = resources
        return result

    def get_presentation(self, presentation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM presentations WHERE presentation_id = ?", (presentation_id,)
            ).fetchone()
            if row is None:
                return None
            item_rows = connection.execute(
                """
                SELECT pi.display_position, r.*
                FROM presentation_items pi
                JOIN resources r ON r.resource_id = pi.resource_id
                WHERE pi.presentation_id = ? ORDER BY pi.display_position
                """,
                (presentation_id,),
            ).fetchall()
        result = dict(row)
        items = []
        for item_row in item_rows:
            item = dict(item_row)
            item["metadata"] = _load(item.pop("metadata_json"), {})
            items.append(item)
        result["items"] = items
        return result

    def get_latest_plan_for_flow(self, flow_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM download_plans WHERE flow_id = ? ORDER BY created_at DESC LIMIT 1",
                (flow_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["resource_ids"] = _load(result.pop("resource_ids_json"), [])
        result["options"] = _load(result.pop("options_json"), {})
        return result

    def get_latest_job_for_flow(self, flow_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE flow_id = ? ORDER BY created_at DESC LIMIT 1",
                (flow_id,),
            ).fetchone()
        return self._decode_job(row) if row is not None else None

    def create_flow(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        flow_id = new_id("flow")
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO flows(
                    flow_id, query, context_json, status, presented_version,
                    task_version, result_version, selection_version, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', 0, 1, 0, 0, ?, ?)
                """,
                (flow_id, query, _json(context), now, now),
            )
        self.audit(flow_id, "flow.start", flow_id, {"query": query})
        return self.get_flow(flow_id)

    def get_flow(self, flow_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM flows WHERE flow_id = ?", (flow_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["context"] = _load(result.pop("context_json"), {})
        return result

    def replace_presented_resources(
        self, flow_id: str, resources: list[dict[str, Any]]
    ) -> int:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT presented_version FROM flows WHERE flow_id = ?", (flow_id,)
            ).fetchone()
            if row is None:
                raise KeyError(flow_id)
            version = int(row["presented_version"]) + 1
            for resource in resources:
                connection.execute(
                    """
                    INSERT INTO resources(
                        resource_id, flow_id, presented_version, platform, title,
                        source_url, resource_type, summary, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource["resource_id"],
                        flow_id,
                        version,
                        resource["platform"],
                        resource["title"],
                        resource["source_url"],
                        resource["resource_type"],
                        resource.get("summary"),
                        _json(resource.get("metadata", {})),
                        now,
                    ),
                )
            connection.execute(
                "UPDATE flows SET presented_version = ?, updated_at = ? WHERE flow_id = ?",
                (version, now, flow_id),
            )
        return version

    def list_presented_resources(self, flow_id: str, version: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resources
                WHERE flow_id = ? AND presented_version = ?
                ORDER BY created_at, resource_id
                """,
                (flow_id, version),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _load(item.pop("metadata_json"), {})
            output.append(item)
        return output

    def get_resources(self, flow_id: str, resource_ids: list[str]) -> list[dict[str, Any]]:
        if not resource_ids:
            return []
        placeholders = ",".join("?" for _ in resource_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM resources WHERE flow_id = ? AND resource_id IN ({placeholders})",
                (flow_id, *resource_ids),
            ).fetchall()
        by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            item["metadata"] = _load(item.pop("metadata_json"), {})
            by_id[item["resource_id"]] = item
        return [by_id[item] for item in resource_ids if item in by_id]

    def save_selection(
        self, flow_id: str, presented_version: int, resource_ids: list[str]
    ) -> None:
        now = utc_now()
        status = "selected" if resource_ids else "cancelled"
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO selections(
                    flow_id, presented_version, selected_ids_json, status, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(flow_id) DO UPDATE SET
                    presented_version = excluded.presented_version,
                    selected_ids_json = excluded.selected_ids_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (flow_id, presented_version, _json(resource_ids), status, now),
            )
        self.audit(
            flow_id,
            "selection.save",
            flow_id,
            {"presented_version": presented_version, "resource_ids": resource_ids},
        )

    def get_selection(self, flow_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM selections WHERE flow_id = ?", (flow_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["resource_ids"] = _load(result.pop("selected_ids_json"), [])
        return result

    def create_plan(
        self,
        flow_id: str,
        presented_version: int,
        resource_ids: list[str],
        options: dict[str, Any],
        confirmation_token: str,
        confirmation_hash: str,
        expires_at: str,
    ) -> dict[str, Any]:
        plan_id = new_id("plan")
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO download_plans(
                    plan_id, flow_id, presented_version, resource_ids_json,
                    options_json, confirmation_token, confirmation_hash, expires_at, used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    plan_id,
                    flow_id,
                    presented_version,
                    _json(resource_ids),
                    _json(options),
                    confirmation_token,
                    confirmation_hash,
                    expires_at,
                    now,
                ),
            )
        self.audit(flow_id, "download.prepare", plan_id, {"resource_ids": resource_ids})
        return self.get_plan(plan_id) or {}

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM download_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["resource_ids"] = _load(result.pop("resource_ids_json"), [])
        result["options"] = _load(result.pop("options_json"), {})
        return result

    def reserve_job(
        self,
        plan_id: str,
        confirmation_hash: str,
        idempotency_key: str,
        request_hash: str,
        now: str,
        *,
        bindings: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        scope = "download.start"
        with self.transaction(immediate=True) as connection:
            previous = connection.execute(
                "SELECT result_id, request_hash FROM idempotency_keys WHERE scope = ? AND key = ?",
                (scope, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["request_hash"] != request_hash:
                    raise ValueError("idempotency_conflict")
                job = connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (previous["result_id"],)
                ).fetchone()
                if job is None:
                    raise RuntimeError("idempotency record points to a missing job")
                if job["plan_id"] != plan_id:
                    raise ValueError("idempotency_conflict")
                return self._decode_job(job), True

            plan = connection.execute(
                "SELECT * FROM download_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if plan is None:
                raise LookupError("plan_not_found")
            if (
                plan["presentation_id"] != bindings.get("presentation_id")
                or int(plan["presented_version"])
                != int(bindings.get("presented_version") or 0)
                or int(plan["selection_version"])
                != int(bindings.get("selection_version") or 0)
                or plan["selection_digest"] != bindings.get("selection_digest")
                or plan["plan_digest"] != bindings.get("plan_digest")
            ):
                raise RuntimeError("plan_binding_mismatch")
            if plan["confirmation_hash"] != confirmation_hash:
                raise PermissionError("confirmation_invalid")
            if bool(plan["used"]):
                raise RuntimeError("plan_used")
            if plan["expires_at"] <= now:
                raise TimeoutError("plan_expired")

            selection = connection.execute(
                "SELECT * FROM selections WHERE flow_id = ?", (plan["flow_id"],)
            ).fetchone()
            flow = connection.execute(
                "SELECT * FROM flows WHERE flow_id = ?", (plan["flow_id"],)
            ).fetchone()
            plan_ids = _load(plan["resource_ids_json"], [])
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
                "UPDATE download_plans SET used = 1 WHERE plan_id = ?", (plan_id,)
            )
            connection.execute(
                """
                INSERT INTO jobs(job_id, flow_id, plan_id, status, progress, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', 0, ?, ?)
                """,
                (job_id, plan["flow_id"], plan_id, now, now),
            )
            connection.execute(
                "INSERT INTO idempotency_keys VALUES (?, ?, ?, ?, NULL, ?)",
                (scope, idempotency_key, request_hash, job_id, now),
            )
            connection.execute(
                "UPDATE flows SET status = 'downloading', updated_at = ? WHERE flow_id = ?",
                (now, plan["flow_id"]),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to reserve job")
        return self._decode_job(row), False

    def _decode_job(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["asset_ids"] = _load(result.pop("asset_ids_json"), [])
        result["error"] = _load(result.pop("error_json"), None)
        return result

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._decode_job(row) if row is not None else None

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        asset_ids: list[str] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        current = self.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE jobs SET status = ?, progress = ?, asset_ids_json = ?,
                    error_json = ?, updated_at = ? WHERE job_id = ?
                """,
                (
                    status if status is not None else current["status"],
                    progress if progress is not None else current["progress"],
                    _json(asset_ids if asset_ids is not None else current["asset_ids"]),
                    _json(error) if error is not None else (
                        _json(current["error"]) if current["error"] is not None else None
                    ),
                    utc_now(),
                    job_id,
                ),
            )

    def create_asset(
        self,
        job_id: str,
        resource_id: str,
        local_path: Path,
        byte_size: int,
        media_type: str,
        sha256: str,
        filename: str,
    ) -> dict[str, Any]:
        asset_id = new_id("asset")
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO assets VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    job_id,
                    resource_id,
                    str(local_path),
                    byte_size,
                    media_type,
                    sha256,
                    filename,
                    now,
                ),
            )
        return self.get_asset(asset_id) or {}

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def quarantine_job_assets(self, job_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE assets SET status = 'quarantined' WHERE job_id = ?", (job_id,)
            )

    def get_archive_for_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM archive_entries WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = _load(result.pop("metadata_json"), {})
        return result

    def create_archive(
        self, asset_id: str, library_path: Path, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        archive_id = new_id("archive")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM archive_entries WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if existing is not None:
                result = dict(existing)
                result["metadata"] = _load(result.pop("metadata_json"), {})
                return result
            connection.execute(
                "INSERT INTO archive_entries VALUES (?, ?, ?, ?, ?)",
                (archive_id, asset_id, str(library_path), _json(metadata), now),
            )
        return self.get_archive_for_asset(asset_id) or {}

    def search_library(self, query: str | None, limit: int, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT a.archive_id, a.asset_id, a.library_path, a.metadata_json, a.created_at,
                   s.filename, s.byte_size, s.media_type, s.sha256, r.resource_id,
                   r.title, r.platform, r.resource_type, r.source_url
            FROM archive_entries a
            JOIN assets s ON s.asset_id = a.asset_id
            JOIN resources r ON r.resource_id = s.resource_id
        """
        params: tuple[Any, ...]
        conditions: list[str] = []
        values: list[Any] = []

        if query:
            needle = f"%{query.lower()}%"
            conditions.append("(lower(r.title) LIKE ? OR lower(a.metadata_json) LIKE ?)")
            values.extend([needle, needle])

        if filters:
            f = filters
            if f.get("primary_domain"):
                conditions.append("lower(a.metadata_json) LIKE ?")
                values.append(f'%"{f["primary_domain"].lower()}"%')
            for topic in (f.get("topics") or [])[:3]:
                conditions.append("lower(a.metadata_json) LIKE ?")
                values.append(f'%"{topic.lower()}"%')
            for tag in (f.get("tags") or [])[:5]:
                conditions.append("lower(a.metadata_json) LIKE ?")
                values.append(f'%"{tag.lower()}"%')
            for col in (f.get("collections") or [])[:3]:
                conditions.append("lower(a.metadata_json) LIKE ?")
                values.append(f'%"{col.lower()}"%')

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
            params = tuple(values) + (limit,)
        else:
            params = (limit,)
        sql += " ORDER BY a.created_at DESC LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _load(item.pop("metadata_json"), {})
            output.append(item)
        return output

    def audit(
        self,
        flow_id: str | None,
        action: str,
        object_id: str | None,
        details: dict[str, Any],
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("evt"), flow_id, action, object_id, _json(details), utc_now()),
            )
