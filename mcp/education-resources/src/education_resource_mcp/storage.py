"""SQLite state store for flows, presented resources, plans, jobs, and assets."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
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
                """
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

    def create_flow(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        flow_id = new_id("flow")
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO flows VALUES (?, ?, ?, 'active', 0, ?, ?)",
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
                INSERT INTO selections VALUES (?, ?, ?, ?, ?)
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
                INSERT INTO download_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
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
            if plan["confirmation_hash"] != confirmation_hash:
                raise PermissionError("confirmation_invalid")
            if bool(plan["used"]):
                raise RuntimeError("plan_used")
            if plan["expires_at"] <= now:
                raise TimeoutError("plan_expired")

            selection = connection.execute(
                "SELECT * FROM selections WHERE flow_id = ?", (plan["flow_id"],)
            ).fetchone()
            plan_ids = _load(plan["resource_ids_json"], [])
            if (
                selection is None
                or selection["status"] != "selected"
                or selection["presented_version"] != plan["presented_version"]
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

    def search_library(self, query: str | None, limit: int) -> list[dict[str, Any]]:
        sql = """
            SELECT a.archive_id, a.asset_id, a.library_path, a.metadata_json, a.created_at,
                   s.filename, s.byte_size, s.media_type, s.sha256, r.resource_id,
                   r.title, r.platform, r.resource_type, r.source_url
            FROM archive_entries a
            JOIN assets s ON s.asset_id = a.asset_id
            JOIN resources r ON r.resource_id = s.resource_id
        """
        params: tuple[Any, ...]
        if query:
            sql += " WHERE lower(r.title) LIKE ? OR lower(a.metadata_json) LIKE ?"
            needle = f"%{query.lower()}%"
            params = (needle, needle, limit)
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
