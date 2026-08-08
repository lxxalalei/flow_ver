"""SQLite state store for flows, presented resources, plans, jobs, and assets."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import secrets
import sqlite3
import threading
from typing import Any, Iterator, Mapping
import uuid


LATEST_SCHEMA_VERSION = 5
ARCHIVE_STATES = {"pending", "ready", "failed", "missing", "corrupt"}
ASSET_BUNDLE_STATUSES = frozenset(
    {"pending", "running", "succeeded", "partial", "failed", "cancelled", "quarantined"}
)
ASSET_BUNDLE_COMPLETIONS = frozenset({"complete", "partial"})
ASSET_BUNDLE_ITEM_STATUSES = frozenset({"pending", "ready", "failed", "quarantined"})
ASSET_BUNDLE_ROLES = frozenset(
    {
        "primary",
        "subtitle",
        "cover",
        "metadata",
        "attachment",
        "transcript",
        "companion",
    }
)
RESOLUTION_STATUSES = frozenset({"resolved", "partial", "unresolved"})
RESOLUTION_CACHEABLE_STATUSES = frozenset({"resolved", "partial"})
_RESOLUTION_PRIVATE_KEYS = frozenset(
    {
        "source_url",
        "canonical_url",
        "url",
        "uri",
        "href",
        "path",
        "file_path",
        "local_path",
        "locator",
        "download_url",
        "stream_url",
        "cookie",
        "cookies",
        "token",
        "access_token",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
    }
)
RESULT_SET_IDEMPOTENCY_SCOPE_PREFIXES = {
    "resource.search": "resource_search",
    "resource.browse_creator": "browse_creator",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _stable_id(prefix: str, *parts: object) -> str:
    """Create a deterministic opaque ID for migration-created relations."""

    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:32]}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _copy_resolution_json(value: Any) -> Any:
    """Return a JSON-safe copy without source locators.

    Inspectors must not be able to persist a source URL into the resolution
    payload that may later be returned by a recovery/status read.  The copy is
    deliberately recursive so nested adapter payloads cannot bypass the
    boundary.  JSON serialization below remains the final type validation.
    """

    if isinstance(value, Mapping):
        return {
            str(key): _copy_resolution_json(item)
            for key, item in value.items()
            if str(key).casefold() not in _RESOLUTION_PRIVATE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_copy_resolution_json(item) for item in value]
    return value


def _encode_resolution_json(value: Any) -> str:
    """Copy and encode a resolution payload using the store's JSON policy."""

    return _json(_copy_resolution_json(value))


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
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.commit()
        with self.transaction(immediate=True) as connection:
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

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                """
            )
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        migrations = (
            (1, "v2_control_plane_columns", self._migration_control_plane_columns),
            (2, "learning_archive_foundation", self._migration_archive_foundation),
            (3, "resource_resolution_foundation", self._migration_resource_resolution_foundation),
            (4, "result_set_extend_storage", self._migration_result_set_extend_storage),
            (5, "multimodal_asset_bundle", self._migration_asset_bundle),
        )
        for version, name, migration in migrations:
            with self.transaction(immediate=True) as connection:
                applied = connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if applied is not None:
                    continue
                migration(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, utc_now()),
                )
                connection.execute(f"PRAGMA user_version = {version}")

    @staticmethod
    def _add_columns(
        connection: sqlite3.Connection,
        table: str,
        columns: list[tuple[str, str]],
    ) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, declaration in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _execute_statements(connection: sqlite3.Connection, script: str) -> None:
        for statement in script.split(";"):
            sql = statement.strip()
            if sql:
                connection.execute(sql)

    def _migration_control_plane_columns(self, connection: sqlite3.Connection) -> None:
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
            self._add_columns(connection, table, columns)

    def _migration_archive_foundation(self, connection: sqlite3.Connection) -> None:
        self._execute_statements(
            connection,
            """
            CREATE TABLE IF NOT EXISTS archive_contents (
                content_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
                media_type TEXT NOT NULL,
                resource_format TEXT NOT NULL DEFAULT 'other',
                relative_path TEXT,
                temporary_path TEXT,
                status TEXT NOT NULL CHECK(status IN ('pending','ready','failed','missing','corrupt')),
                owner_archive_id TEXT,
                error_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(sha256, byte_size)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_contents_status
                ON archive_contents(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_archive_contents_format
                ON archive_contents(resource_format, status, content_id);

            CREATE TABLE IF NOT EXISTS store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS archive_secondary_domains (
                archive_id TEXT NOT NULL REFERENCES archive_entries(archive_id) ON DELETE CASCADE,
                value TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(archive_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_secondary_domains_value
                ON archive_secondary_domains(value, archive_id);

            CREATE TABLE IF NOT EXISTS archive_topics (
                archive_id TEXT NOT NULL REFERENCES archive_entries(archive_id) ON DELETE CASCADE,
                value TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(archive_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_topics_value
                ON archive_topics(value, archive_id);

            CREATE TABLE IF NOT EXISTS archive_purposes (
                archive_id TEXT NOT NULL REFERENCES archive_entries(archive_id) ON DELETE CASCADE,
                value TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(archive_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_purposes_value
                ON archive_purposes(value, archive_id);

            CREATE TABLE IF NOT EXISTS archive_grade_levels (
                archive_id TEXT NOT NULL REFERENCES archive_entries(archive_id) ON DELETE CASCADE,
                value TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(archive_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_grade_levels_value
                ON archive_grade_levels(value, archive_id);

            CREATE TABLE IF NOT EXISTS archive_curriculum_versions (
                archive_id TEXT NOT NULL REFERENCES archive_entries(archive_id) ON DELETE CASCADE,
                value TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(archive_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_curriculum_versions_value
                ON archive_curriculum_versions(value, archive_id);

            CREATE TABLE IF NOT EXISTS archive_tags (
                archive_id TEXT NOT NULL REFERENCES archive_entries(archive_id) ON DELETE CASCADE,
                value TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(archive_id, value)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_tags_value
                ON archive_tags(value, archive_id);
            """
        )
        self._add_columns(
            connection,
            "archive_entries",
            [
                ("content_id", "TEXT REFERENCES archive_contents(content_id)"),
                ("status", "TEXT NOT NULL DEFAULT 'ready'"),
                ("taxonomy_version", "TEXT NOT NULL DEFAULT 'learning-v1'"),
                ("classification_status", "TEXT NOT NULL DEFAULT 'needs_review'"),
                ("primary_domain", "TEXT"),
                ("primary_topic", "TEXT NOT NULL DEFAULT '其他'"),
                ("collection", "TEXT"),
                ("difficulty", "TEXT"),
                ("notes", "TEXT"),
                ("legacy_metadata_json", "TEXT"),
                ("archived_at", "TEXT"),
                ("updated_at", "TEXT"),
                ("error_json", "TEXT"),
            ],
        )
        self._execute_statements(
            connection,
            """
            CREATE INDEX IF NOT EXISTS idx_archive_entries_ready_order
                ON archive_entries(status, archived_at DESC, archive_id DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_entries_primary_domain
                ON archive_entries(primary_domain, status, archived_at DESC, archive_id DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_entries_classification_status
                ON archive_entries(classification_status, status, archived_at DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_entries_taxonomy_version
                ON archive_entries(taxonomy_version, status, archived_at DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_entries_collection
                ON archive_entries(collection, status, archived_at DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_entries_difficulty
                ON archive_entries(difficulty, status, archived_at DESC);
            CREATE INDEX IF NOT EXISTS idx_resources_library_filters
                ON resources(platform, resource_type, resource_id);
            """
        )
        rows = connection.execute(
            """
            SELECT ae.*, s.sha256, s.byte_size, s.media_type, s.filename
            FROM archive_entries ae
            JOIN assets s ON s.asset_id = ae.asset_id
            WHERE ae.content_id IS NULL
            ORDER BY ae.created_at, ae.archive_id
            """
        ).fetchall()
        for row in rows:
            try:
                metadata = _load(row["metadata_json"], {})
                if not isinstance(metadata, dict):
                    raise ValueError("legacy archive metadata is not an object")
                legacy_metadata = metadata
            except (json.JSONDecodeError, TypeError, ValueError):
                metadata = {}
                legacy_metadata = {"unparseable_metadata_json": row["metadata_json"]}
            try:
                normalized = self._normalize_archive_metadata(metadata)
            except (TypeError, ValueError):
                normalized = {
                    "classification": {
                        "taxonomy_version": "learning-v1",
                        "classification_status": "needs_review",
                        "secondary_domains": [],
                        "topics": [],
                        "material_purposes": [],
                        "grade_levels": [],
                        "curriculum_versions": [],
                    },
                    "legacy_classification_raw": metadata,
                    "tags": [],
                }
            content = connection.execute(
                "SELECT content_id FROM archive_contents WHERE sha256 = ? AND byte_size = ?",
                (row["sha256"], row["byte_size"]),
            ).fetchone()
            content_id = content["content_id"] if content is not None else new_id("content")
            if content is None:
                legacy_path = str(row["library_path"] or "")
                relative_path = None
                if legacy_path and not Path(legacy_path).is_absolute():
                    try:
                        relative_path = self._safe_relative_path(legacy_path)
                    except ValueError:
                        relative_path = None
                now = str(row["created_at"] or utc_now())
                connection.execute(
                    """
                    INSERT INTO archive_contents(
                        content_id, sha256, byte_size, media_type, resource_format,
                        relative_path, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?)
                    """,
                    (
                        content_id,
                        row["sha256"],
                        int(row["byte_size"]),
                        row["media_type"],
                        self._infer_resource_format(row["media_type"], row["filename"]),
                        relative_path,
                        now,
                        now,
                    ),
                )
            self._update_archive_classification(
                connection,
                row["archive_id"],
                normalized,
                content_id=content_id,
                status="ready",
                archived_at=str(row["created_at"]),
                legacy_metadata=legacy_metadata,
            )

    def _migration_resource_resolution_foundation(
        self, connection: sqlite3.Connection
    ) -> None:
        """Create the isolated, cache-keyed Resolution store.

        Resolution data is intentionally not added to ``resources`` or a
        ResultSet. The foreign keys provide lifecycle cleanup while the
        service-level ownership checks below ensure that a caller cannot use a
        resource belonging to another Flow.
        """

        self._execute_statements(
            connection,
            """
            CREATE TABLE IF NOT EXISTS resource_resolutions (
                resolution_id TEXT PRIMARY KEY,
                flow_id TEXT NOT NULL REFERENCES flows(flow_id) ON DELETE CASCADE,
                resource_id TEXT NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
                profile_version TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL,
                resolution_status TEXT NOT NULL,
                resolved_json TEXT NOT NULL,
                inspection_json TEXT NOT NULL,
                failures_json TEXT NOT NULL,
                inspected_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(resource_id, profile_version, source_fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_resource_resolutions_flow_resource
                ON resource_resolutions(flow_id, resource_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_resource_resolutions_resource_cache
                ON resource_resolutions(
                    resource_id, profile_version, source_fingerprint,
                    resolution_status, updated_at DESC
                );
            CREATE INDEX IF NOT EXISTS idx_resource_resolutions_flow_updated
                ON resource_resolutions(flow_id, updated_at DESC, resolution_id);
            """,
        )

    def _migration_result_set_extend_storage(
        self, connection: sqlite3.Connection
    ) -> None:
        """Add immutable retrieval-round and private identity snapshots."""

        self._add_columns(
            connection,
            "search_result_sets",
            [
                ("task_version", "INTEGER NOT NULL DEFAULT 1"),
                ("mode", "TEXT NOT NULL DEFAULT 'replace'"),
                ("base_result_set_id", "TEXT"),
                ("round", "INTEGER NOT NULL DEFAULT 1"),
                ("provenance_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("coverage_json", "TEXT NOT NULL DEFAULT '{}'"),
            ],
        )
        self._add_columns(
            connection,
            "resources",
            [
                ("identity_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("identity_rules_version", "TEXT NOT NULL DEFAULT 'identity-v1'"),
            ],
        )

    def _migration_asset_bundle(self, connection: sqlite3.Connection) -> None:
        """Create the authoritative multi-asset relation and backfill v1 rows.

        The old schema only recorded an ordered flat ``jobs.asset_ids_json``
        list.  Migration deliberately uses that order and never infers a
        semantic role from a filename: the first asset for a Job x Resource
        becomes ``primary`` and every later asset becomes ``attachment``.
        Deterministic IDs make the migration safe to rerun after an interrupted
        database upgrade.
        """

        self._execute_statements(
            connection,
            """
            CREATE TABLE IF NOT EXISTS asset_bundles (
                bundle_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                resource_id TEXT NOT NULL REFERENCES resources(resource_id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK(status IN (
                    'pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled',
                    'quarantined'
                )),
                completion TEXT CHECK(completion IS NULL OR completion IN ('complete', 'partial')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, resource_id)
            );
            CREATE INDEX IF NOT EXISTS idx_asset_bundles_job
                ON asset_bundles(job_id, created_at, bundle_id);
            CREATE INDEX IF NOT EXISTS idx_asset_bundles_resource
                ON asset_bundles(resource_id, updated_at DESC, bundle_id);

            CREATE TABLE IF NOT EXISTS asset_bundle_items (
                bundle_item_id TEXT PRIMARY KEY,
                bundle_id TEXT NOT NULL REFERENCES asset_bundles(bundle_id) ON DELETE CASCADE,
                asset_id TEXT REFERENCES assets(asset_id) ON DELETE SET NULL,
                position INTEGER NOT NULL CHECK(position >= 0),
                role TEXT NOT NULL CHECK(role IN (
                    'primary', 'subtitle', 'cover', 'metadata', 'attachment',
                    'transcript', 'companion'
                )),
                status TEXT NOT NULL CHECK(status IN (
                    'pending', 'ready', 'failed', 'quarantined'
                )),
                required INTEGER NOT NULL CHECK(required IN (0, 1)),
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(bundle_id, position),
                UNIQUE(bundle_id, asset_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_bundle_items_primary
                ON asset_bundle_items(bundle_id) WHERE role = 'primary';
            CREATE INDEX IF NOT EXISTS idx_asset_bundle_items_bundle
                ON asset_bundle_items(bundle_id, position);
            CREATE INDEX IF NOT EXISTS idx_asset_bundle_items_asset
                ON asset_bundle_items(asset_id);

            CREATE TABLE IF NOT EXISTS asset_bundle_failures (
                failure_id TEXT PRIMARY KEY,
                bundle_id TEXT NOT NULL REFERENCES asset_bundles(bundle_id) ON DELETE CASCADE,
                bundle_item_id TEXT REFERENCES asset_bundle_items(bundle_item_id) ON DELETE SET NULL,
                attempt INTEGER NOT NULL CHECK(attempt >= 1),
                code TEXT NOT NULL CHECK(length(trim(code)) > 0),
                message TEXT NOT NULL CHECK(length(trim(message)) > 0),
                retriable INTEGER NOT NULL CHECK(retriable IN (0, 1)),
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_asset_bundle_failures_bundle
                ON asset_bundle_failures(bundle_id, created_at, failure_id);
            CREATE INDEX IF NOT EXISTS idx_asset_bundle_failures_item
                ON asset_bundle_failures(bundle_item_id, created_at, failure_id);
            """,
        )
        self._backfill_asset_bundles(connection)

    def _backfill_asset_bundles(self, connection: sqlite3.Connection) -> None:
        """Backfill all historical assets into deterministic Job x Resource bundles."""

        jobs = connection.execute(
            "SELECT job_id, asset_ids_json FROM jobs ORDER BY created_at, job_id"
        ).fetchall()
        assets = connection.execute(
            """
            SELECT asset_id, job_id, resource_id, status, created_at
            FROM assets
            ORDER BY created_at, asset_id
            """
        ).fetchall()
        assets_by_id: dict[str, sqlite3.Row] = {}
        for asset in assets:
            assets_by_id[str(asset["asset_id"])] = asset

        now = utc_now()
        seen_assets: set[str] = set()
        for job in jobs:
            job_id = str(job["job_id"])
            ordered_ids: list[str] = []
            try:
                raw_ids = _load(job["asset_ids_json"], [])
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_ids = []
            if isinstance(raw_ids, list):
                for raw_id in raw_ids:
                    asset_id = str(raw_id)
                    if asset_id not in ordered_ids:
                        ordered_ids.append(asset_id)
            grouped: dict[str, list[sqlite3.Row]] = {}
            for asset_id in ordered_ids:
                asset = assets_by_id.get(asset_id)
                if asset is None or str(asset["job_id"]) != job_id:
                    continue
                grouped.setdefault(str(asset["resource_id"]), []).append(asset)

            for resource_id, resource_assets in grouped.items():
                resource = connection.execute(
                    "SELECT 1 FROM resources WHERE resource_id = ?", (resource_id,)
                ).fetchone()
                if resource is None:
                    # Keep migration forward-compatible with a partially
                    # restored legacy database whose Resource row is missing.
                    continue
                existing = connection.execute(
                    "SELECT bundle_id FROM asset_bundles WHERE job_id = ? AND resource_id = ?",
                    (job_id, resource_id),
                ).fetchone()
                if existing is not None:
                    seen_assets.update(str(asset["asset_id"]) for asset in resource_assets)
                    continue

                bundle_id = _stable_id("bundle", "legacy", job_id, resource_id)
                created_at = min(
                    (str(asset["created_at"] or now) for asset in resource_assets),
                    default=now,
                )
                updated_at = max(
                    (str(asset["created_at"] or now) for asset in resource_assets),
                    default=created_at,
                )
                ready_count = sum(str(asset["status"]) == "ready" for asset in resource_assets)
                all_ready = ready_count == len(resource_assets)
                bundle_status = (
                    "succeeded" if all_ready else "partial" if ready_count else "failed"
                )
                completion = "complete" if all_ready else "partial"
                connection.execute(
                    """
                    INSERT INTO asset_bundles(
                        bundle_id, job_id, resource_id, status, completion,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bundle_id,
                        job_id,
                        resource_id,
                        bundle_status,
                        completion,
                        created_at,
                        updated_at,
                    ),
                )
                for position, asset in enumerate(resource_assets):
                    asset_id = str(asset["asset_id"])
                    asset_status = str(asset["status"])
                    item_status = "ready" if asset_status == "ready" else (
                        "quarantined" if asset_status == "quarantined" else "failed"
                    )
                    item_id = _stable_id("bundle_item", "legacy", bundle_id, position, asset_id)
                    connection.execute(
                        """
                        INSERT INTO asset_bundle_items(
                            bundle_item_id, bundle_id, asset_id, position, role,
                            status, required, metadata_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                        """,
                        (
                            item_id,
                            bundle_id,
                            asset_id,
                            position,
                            "primary" if position == 0 else "attachment",
                            item_status,
                            1 if position == 0 else 0,
                            str(asset["created_at"] or created_at),
                            str(asset["created_at"] or updated_at),
                        ),
                    )
                    if item_status == "failed":
                        connection.execute(
                            """
                            INSERT INTO asset_bundle_failures(
                                failure_id, bundle_id, bundle_item_id, attempt, code,
                                message, retriable, details_json, created_at
                            ) VALUES (?, ?, ?, 1, 'LEGACY_ASSET_NOT_READY', ?, 0, '{}', ?)
                            """,
                            (
                                _stable_id("bundle_failure", "legacy", bundle_id, position, asset_id),
                                bundle_id,
                                item_id,
                                f"legacy asset status: {asset_status}",
                                str(asset["created_at"] or updated_at),
                            ),
                        )
                    seen_assets.add(asset_id)

    @staticmethod
    def _normalize_archive_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        try:
            from .taxonomy import normalize_archive_metadata

            return normalize_archive_metadata(metadata)
        except ImportError:
            pass

        normalized = dict(metadata)
        raw_classification = metadata.get("classification")
        classification = (
            dict(raw_classification) if isinstance(raw_classification, dict) else {}
        )
        for field in (
            "taxonomy_version",
            "classification_status",
            "primary_domain",
            "secondary_domains",
            "topics",
            "material_purposes",
            "grade_levels",
            "difficulty",
            "curriculum_versions",
        ):
            if field not in classification and field in metadata:
                classification[field] = metadata[field]
        classification.setdefault("taxonomy_version", "learning-v1")
        primary_domain = classification.get("primary_domain")
        if primary_domain is not None and not isinstance(primary_domain, str):
            primary_domain = str(primary_domain)
            classification["primary_domain"] = primary_domain
        domain_aliases = {
            "语文": "chinese_language",
            "语文与中文": "chinese_language",
            "01-语文与中文": "chinese_language",
            "数学": "mathematics_reasoning",
            "数学与思维": "mathematics_reasoning",
            "02-数学与思维": "mathematics_reasoning",
            "英语": "english_foreign_languages",
            "英语与外语": "english_foreign_languages",
            "03-英语与外语": "english_foreign_languages",
            "自然科学": "natural_science",
            "04-自然科学": "natural_science",
            "人文与社会": "humanities_social_studies",
            "05-人文与社会": "humanities_social_studies",
            "信息科技": "information_technology",
            "06-信息科技": "information_technology",
            "艺术与审美": "arts_aesthetics",
            "07-艺术与审美": "arts_aesthetics",
            "体育与健康": "physical_health",
            "08-体育与健康": "physical_health",
            "学习方法与通用能力": "learning_skills",
            "09-学习方法与通用能力": "learning_skills",
            "综合实践与跨学科": "interdisciplinary_practice",
            "10-综合实践与跨学科": "interdisciplinary_practice",
        }
        domain_ids = {
            "chinese_language",
            "mathematics_reasoning",
            "english_foreign_languages",
            "natural_science",
            "humanities_social_studies",
            "information_technology",
            "arts_aesthetics",
            "physical_health",
            "learning_skills",
            "interdisciplinary_practice",
        }
        if primary_domain in domain_aliases:
            classification["primary_domain"] = domain_aliases[str(primary_domain)]
            primary_domain = classification["primary_domain"]
        elif primary_domain and primary_domain not in domain_ids:
            normalized["legacy_classification_raw"] = {
                "primary_domain": primary_domain,
                "classification": raw_classification,
            }
            classification["primary_domain"] = None
            classification["classification_status"] = "needs_review"
            primary_domain = None
        classification.setdefault(
            "classification_status", "classified" if primary_domain else "needs_review"
        )
        classification.setdefault("secondary_domains", [])
        classification.setdefault("topics", [])
        classification.setdefault("material_purposes", [])
        classification.setdefault("grade_levels", [])
        classification.setdefault("curriculum_versions", [])
        normalized["classification"] = classification
        return normalized

    @staticmethod
    def _normalized_values(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        output: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                output.append(text)
        return output

    @staticmethod
    def _infer_resource_format(media_type: str, filename: str = "") -> str:
        normalized_media = str(media_type or "").split(";", 1)[0].strip().lower()
        suffix = Path(str(filename or "")).suffix.lower()
        if normalized_media.startswith("video/"):
            return "video"
        if normalized_media.startswith("audio/"):
            return "audio"
        document_media = {
            "application/pdf",
            "application/epub+zip",
            "application/msword",
            "application/rtf",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        document_suffixes = {
            ".html", ".htm", ".pdf", ".doc", ".docx", ".ppt", ".pptx",
            ".txt", ".epub", ".mobi", ".jpg", ".jpeg", ".png", ".gif",
            ".webp", ".xls", ".xlsx", ".rtf",
        }
        if (
            normalized_media.startswith("text/")
            or normalized_media.startswith("image/")
            or normalized_media in document_media
            or suffix in document_suffixes
        ):
            return "document"
        return "other"

    @staticmethod
    def _replace_archive_values(
        connection: sqlite3.Connection,
        table: str,
        archive_id: str,
        values: list[str],
    ) -> None:
        connection.execute(f"DELETE FROM {table} WHERE archive_id = ?", (archive_id,))
        connection.executemany(
            f"INSERT INTO {table}(archive_id, value, position) VALUES (?, ?, ?)",
            ((archive_id, value, position) for position, value in enumerate(values)),
        )

    def _update_archive_classification(
        self,
        connection: sqlite3.Connection,
        archive_id: str,
        normalized: dict[str, Any],
        *,
        content_id: str,
        status: str,
        archived_at: str,
        legacy_metadata: dict[str, Any] | None = None,
    ) -> None:
        classification = normalized.get("classification")
        classification = classification if isinstance(classification, dict) else {}
        topics = self._normalized_values(classification.get("topics"))
        tags = self._normalized_values(normalized.get("tags"))
        now = utc_now()
        connection.execute(
            """
            UPDATE archive_entries SET
                content_id = ?, status = ?, taxonomy_version = ?,
                classification_status = ?, primary_domain = ?, primary_topic = ?,
                collection = ?, difficulty = ?, notes = ?, legacy_metadata_json = ?,
                archived_at = ?, updated_at = ?, error_json = NULL
            WHERE archive_id = ?
            """,
            (
                content_id,
                status,
                str(classification.get("taxonomy_version") or "learning-v1"),
                str(classification.get("classification_status") or "needs_review"),
                classification.get("primary_domain"),
                topics[0] if topics else "其他",
                normalized.get("collection"),
                classification.get("difficulty"),
                normalized.get("notes"),
                _json(legacy_metadata) if legacy_metadata is not None else None,
                archived_at,
                now,
                archive_id,
            ),
        )
        values_by_table = {
            "archive_secondary_domains": self._normalized_values(
                classification.get("secondary_domains")
            ),
            "archive_topics": topics,
            "archive_purposes": self._normalized_values(
                classification.get("material_purposes")
            ),
            "archive_grade_levels": self._normalized_values(
                classification.get("grade_levels")
            ),
            "archive_curriculum_versions": self._normalized_values(
                classification.get("curriculum_versions")
            ),
            "archive_tags": tags,
        }
        for table, values in values_by_table.items():
            self._replace_archive_values(connection, table, archive_id, values)

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row is not None else 0

    def get_or_create_metadata_secret(self, key: str) -> str:
        if not key or len(key) > 128:
            raise ValueError("invalid_metadata_key")
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT value FROM store_metadata WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                return str(row["value"])
            value = secrets.token_hex(32)
            connection.execute(
                "INSERT INTO store_metadata(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, utc_now()),
            )
            return value

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
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            interrupted = connection.execute(
                """
                SELECT job_id FROM jobs
                WHERE status IN ('queued', 'running', 'cancelling')
                ORDER BY created_at, job_id
                """
            ).fetchall()
            job_ids = [str(row["job_id"]) for row in interrupted]
            if not job_ids:
                return 0
            cursor = connection.execute(
                """
                UPDATE jobs SET status = 'failed', error_json = ?, updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (error, now),
            )
            placeholders = ",".join("?" for _ in job_ids)
            connection.execute(
                f"UPDATE assets SET status = 'quarantined' WHERE job_id IN ({placeholders})",
                job_ids,
            )
            connection.execute(
                f"""
                UPDATE asset_bundle_items
                SET status = CASE
                        WHEN asset_id IS NOT NULL OR status IN ('pending', 'ready')
                            THEN 'quarantined'
                        ELSE status
                    END,
                    updated_at = ?
                WHERE bundle_id IN (
                    SELECT bundle_id FROM asset_bundles WHERE job_id IN ({placeholders})
                )
                """,
                [now, *job_ids],
            )
            connection.execute(
                f"""
                UPDATE asset_bundles
                SET status = 'failed', completion = 'partial', updated_at = ?
                WHERE job_id IN ({placeholders})
                """,
                [now, *job_ids],
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

    @staticmethod
    def _validate_resolution_key(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"invalid_{name}")
        return value

    @staticmethod
    def _validate_resolution_status(value: str) -> str:
        if value not in RESOLUTION_STATUSES:
            raise ValueError("invalid_resolution_status")
        return value

    @staticmethod
    def _decode_resolution(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["resolved"] = _copy_resolution_json(
            _load(result.pop("resolved_json"), {})
        )
        result["inspection"] = _copy_resolution_json(
            _load(result.pop("inspection_json"), {})
        )
        result["failures"] = _copy_resolution_json(
            _load(result.pop("failures_json"), [])
        )
        result["cacheable"] = result["resolution_status"] in RESOLUTION_CACHEABLE_STATUSES
        return result

    @staticmethod
    def _assert_resolution_ownership(
        connection: sqlite3.Connection, flow_id: str, resource_id: str
    ) -> sqlite3.Row:
        flow = connection.execute(
            "SELECT flow_id FROM flows WHERE flow_id = ?", (flow_id,)
        ).fetchone()
        if flow is None:
            raise KeyError("flow_not_found")
        resource = connection.execute(
            "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if resource is None:
            raise LookupError("resource_not_found")
        if resource["flow_id"] != flow_id:
            raise PermissionError("resource_flow_mismatch")
        return resource

    def get_cached_resolution(
        self,
        flow_id: str,
        resource_id: str,
        profile_version: str,
        source_fingerprint: str,
        *,
        allow_unresolved: bool = False,
    ) -> dict[str, Any] | None:
        """Read one exact resolution cache key after ownership validation.

        ``unresolved`` rows are retained for audit/recovery but are not cache
        hits by default.  Callers that are explicitly replaying the same
        inspection attempt may opt in with ``allow_unresolved``.
        """

        self._validate_resolution_key("flow_id", flow_id)
        self._validate_resolution_key("resource_id", resource_id)
        self._validate_resolution_key("profile_version", profile_version)
        self._validate_resolution_key("source_fingerprint", source_fingerprint)
        with self._connect() as connection:
            self._assert_resolution_ownership(connection, flow_id, resource_id)
            row = connection.execute(
                """
                SELECT * FROM resource_resolutions
                WHERE flow_id = ? AND resource_id = ?
                  AND profile_version = ? AND source_fingerprint = ?
                """,
                (flow_id, resource_id, profile_version, source_fingerprint),
            ).fetchone()
        if row is None:
            return None
        if not allow_unresolved and row["resolution_status"] not in RESOLUTION_CACHEABLE_STATUSES:
            return None
        return self._decode_resolution(row)

    def get_resource_resolution(
        self,
        flow_id: str,
        resource_id: str,
        profile_version: str,
        source_fingerprint: str,
        *,
        allow_unresolved: bool = False,
    ) -> dict[str, Any] | None:
        """Compatibility name for an exact Resolution cache read."""

        return self.get_cached_resolution(
            flow_id,
            resource_id,
            profile_version,
            source_fingerprint,
            allow_unresolved=allow_unresolved,
        )

    def list_latest_resolutions(
        self,
        flow_id: str,
        *,
        result_set_id: str | None = None,
        include_unresolved: bool = False,
    ) -> list[dict[str, Any]]:
        """List the newest safe Resolution for each resource in a Flow.

        With no explicit ResultSet, only resources in the Flow's current
        ResultSet are considered.  The default excludes unresolved attempts;
        this prevents a retryable failure from being used as a cache hit for a
        different idempotency key.
        """

        self._validate_resolution_key("flow_id", flow_id)
        with self._connect() as connection:
            flow = connection.execute(
                "SELECT current_result_set_id FROM flows WHERE flow_id = ?",
                (flow_id,),
            ).fetchone()
            if flow is None:
                raise KeyError("flow_not_found")
            selected_result_set_id = result_set_id or flow["current_result_set_id"]
            if result_set_id is not None:
                result_set = connection.execute(
                    "SELECT flow_id FROM search_result_sets WHERE result_set_id = ?",
                    (result_set_id,),
                ).fetchone()
                if result_set is None:
                    raise LookupError("result_set_not_found")
                if result_set["flow_id"] != flow_id:
                    raise PermissionError("result_set_flow_mismatch")

            status_sql = ""
            status_args: tuple[Any, ...] = ()
            if not include_unresolved:
                status_sql = " AND rr.resolution_status IN ('resolved', 'partial')"
            if selected_result_set_id is None:
                rows = connection.execute(
                    f"""
                    SELECT rr.*, r.result_position, r.created_at AS resource_created_at
                    FROM resource_resolutions rr
                    JOIN resources r ON r.resource_id = rr.resource_id
                    WHERE rr.flow_id = ? AND r.flow_id = ?{status_sql}
                    ORDER BY rr.resource_id, rr.updated_at DESC, rr.resolution_id DESC
                    """,
                    (flow_id, flow_id, *status_args),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT rr.*, r.result_position, r.created_at AS resource_created_at
                    FROM resource_resolutions rr
                    JOIN resources r ON r.resource_id = rr.resource_id
                    WHERE rr.flow_id = ? AND r.flow_id = ? AND r.result_set_id = ?{status_sql}
                    ORDER BY rr.resource_id, rr.updated_at DESC, rr.resolution_id DESC
                    """,
                    (flow_id, flow_id, selected_result_set_id, *status_args),
                ).fetchall()

        latest: dict[str, dict[str, Any]] = {}
        positions: dict[str, tuple[int, str, str]] = {}
        for row in rows:
            if row["resource_id"] in latest:
                continue
            latest[row["resource_id"]] = self._decode_resolution(row)
            positions[row["resource_id"]] = (
                int(row["result_position"])
                if row["result_position"] is not None
                else 2**31 - 1,
                str(row["resource_created_at"] or ""),
                str(row["resource_id"]),
            )
        return [
            latest[resource_id]
            for resource_id in sorted(latest, key=lambda item: positions[item])
        ]

    def list_latest_resolutions_for_flow(
        self,
        flow_id: str,
        *,
        result_set_id: str | None = None,
        include_unresolved: bool = False,
    ) -> list[dict[str, Any]]:
        """Explicit name for the current Flow/ResultSet recovery query."""

        return self.list_latest_resolutions(
            flow_id,
            result_set_id=result_set_id,
            include_unresolved=include_unresolved,
        )

    def save_resolution(
        self,
        flow_id: str,
        resource_id: str,
        profile_version: str,
        source_fingerprint: str,
        resolution_status: str,
        resolved: Any = None,
        inspection: Any = None,
        failures: Any = None,
        *,
        idempotency_key: str,
        request_hash: str | None = None,
        inspected_at: str | None = None,
        resolved_json: Any = None,
        inspection_json: Any = None,
        failures_json: Any = None,
    ) -> dict[str, Any]:
        """Atomically save a Resolution, audit event, and inspect idempotency.

        The cache row is keyed by resource/profile/source fingerprint.  A
        retryable unresolved result is still stored, but the read APIs exclude
        it from cross-key cache hits unless the caller opts in.
        """

        self._validate_resolution_key("flow_id", flow_id)
        self._validate_resolution_key("resource_id", resource_id)
        self._validate_resolution_key("profile_version", profile_version)
        self._validate_resolution_key("source_fingerprint", source_fingerprint)
        self._validate_resolution_key("idempotency_key", idempotency_key)
        status = self._validate_resolution_status(resolution_status)
        if resolved_json is not None:
            if resolved is not None:
                raise ValueError("duplicate_resolved_payload")
            resolved = resolved_json
        if inspection_json is not None:
            if inspection is not None:
                raise ValueError("duplicate_inspection_payload")
            inspection = inspection_json
        if failures_json is not None:
            if failures is not None:
                raise ValueError("duplicate_failures_payload")
            failures = failures_json
        resolved = {} if resolved is None else resolved
        inspection = {} if inspection is None else inspection
        failures = [] if failures is None else failures
        encoded_resolved = _encode_resolution_json(resolved)
        encoded_inspection = _encode_resolution_json(inspection)
        encoded_failures = _encode_resolution_json(failures)
        inspected_at = inspected_at or utc_now()
        request_hash = request_hash or self._request_digest(
            {
                "flow_id": flow_id,
                "resource_id": resource_id,
                "profile_version": profile_version,
                "source_fingerprint": source_fingerprint,
                "resolution_status": status,
                "resolved_json": _load(encoded_resolved, {}),
                "inspection_json": _load(encoded_inspection, {}),
                "failures_json": _load(encoded_failures, []),
                "inspected_at": inspected_at,
            }
        )
        scope = f"resource_inspect:{flow_id}"
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            self._assert_resolution_ownership(connection, flow_id, resource_id)
            replay = self._replay_in_transaction(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            previous = connection.execute(
                """
                SELECT created_at FROM resource_resolutions
                WHERE resource_id = ? AND profile_version = ? AND source_fingerprint = ?
                """,
                (resource_id, profile_version, source_fingerprint),
            ).fetchone()
            resolution_id = new_id("resolve")
            created_at = str(previous["created_at"]) if previous is not None else now
            connection.execute(
                """
                INSERT INTO resource_resolutions(
                    resolution_id, flow_id, resource_id, profile_version,
                    source_fingerprint, resolution_status, resolved_json,
                    inspection_json, failures_json, inspected_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(resource_id, profile_version, source_fingerprint) DO UPDATE SET
                    resolution_id = excluded.resolution_id,
                    flow_id = excluded.flow_id,
                    resolution_status = excluded.resolution_status,
                    resolved_json = excluded.resolved_json,
                    inspection_json = excluded.inspection_json,
                    failures_json = excluded.failures_json,
                    inspected_at = excluded.inspected_at,
                    updated_at = excluded.updated_at
                """,
                (
                    resolution_id,
                    flow_id,
                    resource_id,
                    profile_version,
                    source_fingerprint,
                    status,
                    encoded_resolved,
                    encoded_inspection,
                    encoded_failures,
                    inspected_at,
                    created_at,
                    now,
                ),
            )
            result = {
                "resolution_id": resolution_id,
                "flow_id": flow_id,
                "resource_id": resource_id,
                "profile_version": profile_version,
                "source_fingerprint": source_fingerprint,
                "resolution_status": status,
                "resolved": _load(encoded_resolved, {}),
                "inspection": _load(encoded_inspection, {}),
                "failures": _load(encoded_failures, []),
                "inspected_at": inspected_at,
                "created_at": created_at,
                "updated_at": now,
                "cacheable": status in RESOLUTION_CACHEABLE_STATUSES,
            }
            self._audit_in_transaction(
                connection,
                flow_id,
                "resource.inspect",
                resolution_id,
                {
                    "resource_id": resource_id,
                    "profile_version": profile_version,
                    "source_fingerprint": source_fingerprint,
                    "resolution_status": status,
                },
                now,
            )
            self._put_idempotency_in_transaction(
                connection,
                scope,
                idempotency_key,
                request_hash,
                resolution_id,
                result,
                now,
            )
        return result

    def save_resource_resolution(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Compatibility name for the atomic Resolution write."""

        return self.save_resolution(*args, **kwargs)

    def create_flow(
        self,
        task: dict[str, Any],
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = "resource_flow_start"
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

    def create_result_set(
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
        idempotency_scope: str | None = None,
        idempotency_action: str = "resource.search",
        mode: str = "replace",
        base_result_set_id: str | None = None,
        provenance: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope_prefix = RESULT_SET_IDEMPOTENCY_SCOPE_PREFIXES.get(idempotency_action)
        if scope_prefix is None:
            raise ValueError("unsupported_result_set_idempotency_action")
        scope = f"{scope_prefix}:{flow_id}"
        if idempotency_scope is not None and idempotency_scope != scope:
            raise ValueError("invalid_result_set_idempotency_scope")
        normalised_mode = str(mode or "replace").strip().lower()
        if normalised_mode not in {"replace", "extend"}:
            raise ValueError("invalid_result_set_mode")
        normalised_base_result_set_id = (
            str(base_result_set_id).strip() if base_result_set_id is not None else None
        )
        if not normalised_base_result_set_id:
            normalised_base_result_set_id = None
        if normalised_mode == "replace" and normalised_base_result_set_id is not None:
            raise ValueError("base_result_set_forbidden")
        if normalised_mode == "extend" and normalised_base_result_set_id is None:
            raise ValueError("base_result_set_required")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            replay = self._replay_in_transaction(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            flow = connection.execute(
                """
                SELECT task_version, result_version, current_result_set_id
                FROM flows WHERE flow_id = ?
                """,
                (flow_id,),
            ).fetchone()
            if flow is None:
                raise KeyError(flow_id)
            if int(flow["task_version"]) != int(task_version):
                raise RuntimeError("task_version_conflict")

            base_result_set: sqlite3.Row | None = None
            if normalised_mode == "extend":
                base_result_set = connection.execute(
                    "SELECT * FROM search_result_sets WHERE result_set_id = ?",
                    (normalised_base_result_set_id,),
                ).fetchone()
                if base_result_set is None:
                    raise ValueError("base_result_set_not_found")
                if base_result_set["flow_id"] != flow_id:
                    raise ValueError("base_result_set_flow_mismatch")
                if flow["current_result_set_id"] != normalised_base_result_set_id:
                    raise RuntimeError("base_result_set_stale")
                if int(base_result_set["task_version"]) != int(task_version):
                    raise RuntimeError("base_task_version_conflict")

            result_version = int(flow["result_version"]) + 1
            result_set_id = new_id("rset")
            search_run_id = new_id("search")
            status = "ready"
            round_number = (
                int(base_result_set["round"]) + 1
                if base_result_set is not None
                else 1
            )
            connection.execute(
                """
                INSERT INTO search_result_sets(
                    result_set_id, flow_id, search_run_id, result_version, query,
                    filters_json, status, failures_json, platform_runs_json,
                    task_version, mode, base_result_set_id, round,
                    provenance_json, coverage_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(task_version),
                    normalised_mode,
                    normalised_base_result_set_id,
                    round_number,
                    _json(provenance if provenance is not None else {}),
                    _json(coverage if coverage is not None else {}),
                    now,
                ),
            )
            for position, resource in enumerate(resources, 1):
                connection.execute(
                    """
                    INSERT INTO resources(
                        resource_id, flow_id, presented_version, platform, title,
                        source_url, resource_type, summary, metadata_json, created_at,
                        result_set_id, result_position, identity_json,
                        identity_rules_version
                    ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        _json(resource.get("identity", {})),
                        str(resource.get("identity_rules_version") or "identity-v1"),
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
            if idempotency_action == "resource.search":
                result.update(
                    {
                        "mode": normalised_mode,
                        "base_result_set_id": normalised_base_result_set_id,
                        "round": round_number,
                        "provenance": provenance if provenance is not None else {},
                        "coverage": coverage if coverage is not None else {},
                    }
                )
            self._audit_in_transaction(
                connection,
                flow_id,
                idempotency_action,
                result_set_id,
                {
                    "query": query,
                    "count": len(resources),
                    "result_version": result_version,
                    "mode": normalised_mode,
                    "base_result_set_id": normalised_base_result_set_id,
                    "round": round_number,
                },
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

    def create_presentation(
        self,
        flow_id: str,
        result_set_id: str,
        displayed_resource_ids: list[str],
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = f"resource_presentation_save:{flow_id}"
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

    def save_selection(
        self,
        flow_id: str,
        presentation_id: str,
        presented_version: int,
        selected_positions: list[int],
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        scope = f"resource_selection_save:{flow_id}"
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
        result["provenance"] = _load(result.pop("provenance_json", "{}"), {})
        result["coverage"] = _load(result.pop("coverage_json", "{}"), {})
        resources = []
        for resource_row in resource_rows:
            resource = dict(resource_row)
            resource["metadata"] = _load(resource.pop("metadata_json"), {})
            resource["identity"] = _load(resource.pop("identity_json", "{}"), {})
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
            item["identity"] = _load(item.pop("identity_json", "{}"), {})
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
            item["identity"] = _load(item.pop("identity_json", "{}"), {})
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
            item["identity"] = _load(item.pop("identity_json", "{}"), {})
            by_id[item["resource_id"]] = item
        return [by_id[item] for item in resource_ids if item in by_id]

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

    @staticmethod
    def _bundle_json(value: Any, field: str, *, default: Any = None) -> Any:
        if value is None:
            return {} if default is None else default
        if isinstance(value, str):
            try:
                value = _load(value, {})
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid_{field}") from exc
        try:
            encoded = _json(value)
            return _load(encoded, {})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid_{field}") from exc

    @staticmethod
    def _bundle_bool(value: Any, field: str, *, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError(f"invalid_{field}")

    @staticmethod
    def _bundle_position(value: Any, field: str = "position") -> int:
        if isinstance(value, bool):
            raise ValueError(f"invalid_{field}")
        try:
            position = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid_{field}") from exc
        if position < 0 or str(position) != str(value).strip() and not isinstance(value, int):
            raise ValueError(f"invalid_{field}")
        return position

    @staticmethod
    def _bundle_hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .encode("utf-8")
        ).hexdigest()

    @classmethod
    def _normalize_bundle_items(
        cls,
        item_specs: Any,
        *,
        job_id: str,
        resource_id: str,
    ) -> list[dict[str, Any]]:
        if item_specs is None:
            return []
        if isinstance(item_specs, Mapping):
            item_specs = [item_specs]
        if isinstance(item_specs, (str, bytes)):
            raise ValueError("invalid_asset_bundle_items")
        try:
            raw_items = list(item_specs)
        except TypeError as exc:
            raise ValueError("invalid_asset_bundle_items") from exc

        normalized: list[dict[str, Any]] = []
        positions: set[int] = set()
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, Mapping) and hasattr(raw, "to_dict"):
                raw = raw.to_dict(include_path=True)
            if not isinstance(raw, Mapping):
                raise ValueError("invalid_asset_bundle_item")
            position = cls._bundle_position(raw.get("position", index))
            if position in positions:
                raise ValueError("duplicate_asset_bundle_position")
            positions.add(position)
            role = str(raw.get("role") or ("primary" if index == 0 else "attachment"))
            if role not in ASSET_BUNDLE_ROLES:
                raise ValueError("invalid_asset_bundle_role")
            required = cls._bundle_bool(
                raw.get("required"), "asset_bundle_required", default=role == "primary"
            )
            if role == "primary" and not required:
                raise ValueError("primary_asset_bundle_item_must_be_required")
            status = str(raw.get("status") or "ready").lower()
            if status == "succeeded":
                status = "ready"
            if status not in ASSET_BUNDLE_ITEM_STATUSES:
                raise ValueError("invalid_asset_bundle_item_status")
            if raw.get("job_id") is not None and str(raw["job_id"]) != job_id:
                raise ValueError("asset_bundle_job_mismatch")
            if raw.get("resource_id") is not None and str(raw["resource_id"]) != resource_id:
                raise ValueError("asset_bundle_resource_mismatch")
            asset_id = raw.get("asset_id")
            if asset_id is not None:
                if not isinstance(asset_id, str) or not asset_id.strip():
                    raise ValueError("invalid_asset_id")
                asset_id = asset_id.strip()
            metadata = cls._bundle_json(
                raw.get("metadata", raw.get("metadata_json")),
                "asset_bundle_metadata",
                default={},
            )
            item: dict[str, Any] = {
                "position": position,
                "role": role,
                "status": status,
                "required": required,
                "metadata": metadata,
                "failure": raw.get("failure"),
            }
            if asset_id is not None:
                item["asset_id"] = asset_id
            if status == "ready":
                if asset_id is None:
                    local_path = raw.get("local_path", raw.get("path"))
                    if local_path is None or not str(local_path).strip():
                        raise ValueError("asset_bundle_file_metadata_required")
                    byte_size = raw.get("byte_size", raw.get("size_bytes"))
                    if isinstance(byte_size, bool):
                        raise ValueError("invalid_asset_byte_size")
                    try:
                        byte_size = int(byte_size)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("invalid_asset_byte_size") from exc
                    if byte_size < 0:
                        raise ValueError("invalid_asset_byte_size")
                    media_type = str(raw.get("media_type") or "").strip()
                    filename = str(raw.get("filename") or "").strip()
                    sha256 = str(raw.get("sha256") or "").strip().lower()
                    if not media_type or not filename or len(sha256) != 64 or any(
                        char not in "0123456789abcdef" for char in sha256
                    ):
                        raise ValueError("invalid_asset_file_metadata")
                    portable_filename = filename.replace("\\", "/")
                    filename_path = PurePosixPath(portable_filename)
                    if (
                        "\x00" in filename
                        or filename_path.is_absolute()
                        or portable_filename.startswith("//")
                        or ".." in filename_path.parts
                    ):
                        raise ValueError("invalid_asset_filename")
                    filename = PurePosixPath(
                        *(part for part in filename_path.parts if part not in {"", "."})
                    ).as_posix()
                    if not filename:
                        raise ValueError("invalid_asset_filename")
                    item["asset"] = {
                        "local_path": str(local_path),
                        "byte_size": byte_size,
                        "media_type": media_type,
                        "sha256": sha256,
                        "filename": filename,
                    }
                elif any(
                    key in raw
                    for key in (
                        "local_path",
                        "path",
                        "byte_size",
                        "size_bytes",
                        "media_type",
                        "sha256",
                        "filename",
                    )
                ):
                    raise ValueError("asset_id_and_file_metadata_are_mutually_exclusive")
            elif any(
                key in raw
                for key in ("local_path", "path", "byte_size", "size_bytes", "media_type", "sha256", "filename")
            ):
                raise ValueError("failed_asset_bundle_item_cannot_have_file")
            normalized.append(item)

        primary_count = sum(item["role"] == "primary" for item in normalized)
        if primary_count != 1:
            raise ValueError("asset_bundle_requires_exactly_one_primary")
        return normalized

    @classmethod
    def _normalize_bundle_failures(cls, failures: Any) -> list[dict[str, Any]]:
        if failures is None:
            return []
        if isinstance(failures, Mapping):
            failures = [failures]
        if isinstance(failures, (str, bytes)):
            raise ValueError("invalid_asset_bundle_failures")
        try:
            raw_failures = list(failures)
        except TypeError as exc:
            raise ValueError("invalid_asset_bundle_failures") from exc
        normalized: list[dict[str, Any]] = []
        for raw in raw_failures:
            if not isinstance(raw, Mapping) and hasattr(raw, "to_dict"):
                raw = raw.to_dict()
            if not isinstance(raw, Mapping):
                raise ValueError("invalid_asset_bundle_failure")
            attempt = raw.get("attempt", 1)
            if isinstance(attempt, bool):
                raise ValueError("invalid_asset_bundle_failure_attempt")
            try:
                attempt = int(attempt)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_asset_bundle_failure_attempt") from exc
            if attempt < 1:
                raise ValueError("invalid_asset_bundle_failure_attempt")
            code = str(raw.get("code") or "").strip()
            message = str(raw.get("message") or "").strip()
            if not code or not message:
                raise ValueError("invalid_asset_bundle_failure")
            item_position = raw.get("item_position", raw.get("position"))
            if item_position is not None:
                item_position = cls._bundle_position(item_position, "item_position")
            item_role = raw.get("item_role", raw.get("role"))
            if item_role is not None:
                item_role = str(item_role)
                if item_role not in ASSET_BUNDLE_ROLES:
                    raise ValueError("invalid_asset_bundle_failure_role")
            normalized.append(
                {
                    "attempt": attempt,
                    "code": code,
                    "message": message,
                    "retriable": cls._bundle_bool(
                        raw.get("retriable", raw.get("retryable")), "retriable"
                    ),
                    "details": cls._bundle_json(
                        raw.get("details", raw.get("details_json")),
                        "asset_bundle_failure_details",
                        default={},
                    ),
                    "item_position": item_position,
                    "item_role": item_role,
                    "bundle_item_id": raw.get("bundle_item_id"),
                }
            )
        return normalized

    @staticmethod
    def _bundle_request_fingerprint(
        items: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        completion: str,
    ) -> str:
        return Store._bundle_hash(
            {
                "completion": completion,
                "items": [
                    {
                        "position": item["position"],
                        "role": item["role"],
                        "status": item["status"],
                        "required": bool(item["required"]),
                        "metadata": item["metadata"],
                        "asset": item.get("asset"),
                    }
                    for item in sorted(items, key=lambda item: int(item["position"]))
                ],
                "failures": [
                    {
                        "attempt": failure["attempt"],
                        "code": failure["code"],
                        "message": failure["message"],
                        "retriable": bool(failure["retriable"]),
                        "details": failure["details"],
                        "item_position": failure["item_position"],
                        "item_role": failure["item_role"],
                    }
                    for failure in sorted(
                        failures,
                        key=lambda failure: json.dumps(
                            {
                                "attempt": failure["attempt"],
                                "code": failure["code"],
                                "message": failure["message"],
                                "retriable": bool(failure["retriable"]),
                                "details": failure["details"],
                                "item_position": failure["item_position"],
                                "item_role": failure["item_role"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                ],
            }
        )

    @staticmethod
    def _decode_bundle_json(value: str | None, default: Any) -> Any:
        try:
            return _load(value, default)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    def _decode_asset_bundle(
        self, connection: sqlite3.Connection, bundle_row: sqlite3.Row
    ) -> dict[str, Any]:
        bundle = dict(bundle_row)
        item_rows = connection.execute(
            """
            SELECT i.*, a.local_path, a.byte_size, a.media_type, a.sha256,
                   a.filename, a.status AS asset_status, a.job_id AS asset_job_id,
                   a.resource_id AS asset_resource_id
            FROM asset_bundle_items i
            LEFT JOIN assets a ON a.asset_id = i.asset_id
            WHERE i.bundle_id = ?
            ORDER BY i.position, i.bundle_item_id
            """,
            (bundle["bundle_id"],),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in item_rows:
            item = dict(row)
            item["required"] = bool(item["required"])
            item["metadata"] = self._decode_bundle_json(item.pop("metadata_json"), {})
            asset_fields = {
                key: item.pop(key)
                for key in (
                    "local_path",
                    "byte_size",
                    "media_type",
                    "sha256",
                    "filename",
                    "asset_status",
                    "asset_job_id",
                    "asset_resource_id",
                )
                if key in item and item[key] is not None
            }
            if asset_fields:
                asset_fields["asset_id"] = item["asset_id"]
                item["asset"] = asset_fields
            items.append(item)

        failure_rows = connection.execute(
            """
            SELECT * FROM asset_bundle_failures
            WHERE bundle_id = ?
            ORDER BY created_at, failure_id
            """,
            (bundle["bundle_id"],),
        ).fetchall()
        failures: list[dict[str, Any]] = []
        for row in failure_rows:
            failure = dict(row)
            failure["retriable"] = bool(failure["retriable"])
            failure["details"] = self._decode_bundle_json(failure.pop("details_json"), {})
            failures.append(failure)
        bundle["items"] = items
        bundle["failures"] = failures
        bundle["completion"] = str(bundle["completion"])
        return bundle

    def _bundle_fingerprint_from_row(
        self, connection: sqlite3.Connection, bundle_row: sqlite3.Row
    ) -> str:
        bundle_id = str(bundle_row["bundle_id"])
        items = connection.execute(
            """
            SELECT i.asset_id, i.position, i.role, i.status, i.required, i.metadata_json,
                   a.local_path, a.byte_size, a.media_type, a.sha256, a.filename
            FROM asset_bundle_items i
            LEFT JOIN assets a ON a.asset_id = i.asset_id
            WHERE i.bundle_id = ?
            ORDER BY i.position, i.bundle_item_id
            """,
            (bundle_id,),
        ).fetchall()
        failures = connection.execute(
            """
            SELECT f.attempt, f.code, f.message, f.retriable, f.details_json,
                   i.position, i.role
            FROM asset_bundle_failures f
            LEFT JOIN asset_bundle_items i ON i.bundle_item_id = f.bundle_item_id
            WHERE f.bundle_id = ?
            ORDER BY f.created_at, f.failure_id
            """,
            (bundle_id,),
        ).fetchall()
        normalized_items = [
            {
                "position": int(row["position"]),
                "role": str(row["role"]),
                "status": str(row["status"]),
                "required": bool(row["required"]),
                "metadata": self._decode_bundle_json(row["metadata_json"], {}),
                "asset": (
                    {
                        "local_path": str(row["local_path"]),
                        "byte_size": int(row["byte_size"]),
                        "media_type": str(row["media_type"]),
                        "sha256": str(row["sha256"]),
                        "filename": str(row["filename"]),
                    }
                    if row["asset_id"] is not None
                    else None
                ),
            }
            for row in items
        ]
        normalized_failures = [
            {
                "attempt": int(row["attempt"]),
                "code": str(row["code"]),
                "message": str(row["message"]),
                "retriable": bool(row["retriable"]),
                "details": self._decode_bundle_json(row["details_json"], {}),
                "item_position": int(row["position"]) if row["position"] is not None else None,
                "item_role": str(row["role"]) if row["role"] is not None else None,
            }
            for row in failures
        ]
        return self._bundle_request_fingerprint(
            normalized_items,
            normalized_failures,
            str(bundle_row["completion"]),
        )

    def _assert_bundle_job_resource(
        self, connection: sqlite3.Connection, job_id: str, resource_id: str
    ) -> None:
        job = connection.execute(
            "SELECT flow_id FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if job is None:
            raise KeyError(job_id)
        resource = connection.execute(
            "SELECT flow_id FROM resources WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if resource is None:
            raise KeyError(resource_id)
        if str(job["flow_id"]) != str(resource["flow_id"]):
            raise ValueError("job_resource_flow_mismatch")

    def persist_asset_bundle(
        self,
        job_id: str,
        resource_id: str,
        item_specs: Any = None,
        failures: Any = None,
        completion: str | None = None,
        *,
        status: str | None = None,
        items: Any = None,
        **aliases: Any,
    ) -> dict[str, Any]:
        """Atomically promote validated acquisition file metadata into a Bundle.

        ``item_specs`` may contain server-validated file metadata or existing
        Asset IDs.  The store generates IDs for new files.  A second identical
        call replays the existing Job x Resource Bundle; a changed payload
        reopens that same relation atomically instead of creating a duplicate.
        """

        if item_specs is not None and items is not None:
            raise ValueError("duplicate_asset_bundle_items")
        if item_specs is None:
            item_specs = items
        if item_specs is None:
            item_specs = aliases.pop("artifacts", None)
        if failures is None and aliases.get("failure_specs") is not None:
            failures = aliases.pop("failure_specs")
        if failures is None and aliases.get("failure") is not None:
            failures = [aliases.pop("failure")]
        if aliases:
            raise TypeError(f"unexpected_asset_bundle_arguments: {sorted(aliases)}")
        return self._persist_asset_bundle_v2(
            job_id,
            resource_id,
            item_specs,
            failures,
            completion,
            status=status,
        )
        completion = str(completion).lower()
        if completion not in ASSET_BUNDLE_COMPLETIONS:
            raise ValueError("invalid_asset_bundle_completion")
        normalized_items = self._normalize_bundle_items(
            item_specs,
            job_id=job_id,
            resource_id=resource_id,
        )
        normalized_failures = self._normalize_bundle_failures(failures)
        for item in normalized_items:
            if item.get("failure") is not None:
                if not isinstance(item["failure"], Mapping):
                    raise ValueError("invalid_asset_bundle_failure")
                normalized_failures.extend(
                    self._normalize_bundle_failures(
                        [{**item["failure"], "item_position": item["position"]}]
                    )
                )
        positions_by_role: dict[str, list[int]] = {}
        for item in normalized_items:
            positions_by_role.setdefault(str(item["role"]), []).append(int(item["position"]))
        for failure in normalized_failures:
            if failure.get("bundle_item_id") is not None:
                raise ValueError("bundle_item_id_must_be_generated_by_store")
            if failure.get("item_position") is None and failure.get("item_role") is not None:
                matches = positions_by_role.get(str(failure["item_role"]), [])
                if len(matches) != 1:
                    raise ValueError("asset_bundle_failure_item_not_found")
                failure["item_position"] = matches[0]
            if failure.get("item_position") is not None:
                matching_items = [
                    item
                    for item in normalized_items
                    if int(item["position"]) == int(failure["item_position"])
                ]
                if len(matching_items) != 1:
                    raise ValueError("asset_bundle_failure_item_not_found")
                if (
                    failure.get("item_role") is not None
                    and str(failure["item_role"]) != str(matching_items[0]["role"])
                ):
                    raise ValueError("asset_bundle_failure_item_mismatch")
                failure["item_role"] = matching_items[0]["role"]
        request_fingerprint = self._bundle_request_fingerprint(
            normalized_items, normalized_failures, completion
        )
        with self.transaction(immediate=True) as connection:
            self._assert_bundle_job_resource(connection, job_id, resource_id)
            existing = connection.execute(
                "SELECT * FROM asset_bundles WHERE job_id = ? AND resource_id = ?",
                (job_id, resource_id),
            ).fetchone()
            if existing is not None:
                if self._bundle_fingerprint_from_row(connection, existing) != request_fingerprint:
                    raise ValueError("asset_bundle_conflict")
                result_id = str(existing["bundle_id"])
            else:
                primary_items = [
                    item for item in normalized_items if item["role"] == "primary"
                ]
                if len(primary_items) != 1:
                    raise ValueError("asset_bundle_requires_exactly_one_primary")
                primary = primary_items[0]
                primary_ready = primary["status"] == "ready"
                all_ready = all(item["status"] == "ready" for item in normalized_items)
                if status is None:
                    resolved_status = (
                        "succeeded"
                        if primary_ready and all_ready and not normalized_failures
                        else "partial"
                        if primary_ready
                        else "failed"
                    )
                else:
                    resolved_status = str(status).lower()
                    if resolved_status not in ASSET_BUNDLE_STATUSES:
                        raise ValueError("invalid_asset_bundle_status")
                if completion == "complete" and (
                    resolved_status != "succeeded" or not primary_ready or not all_ready
                ):
                    raise ValueError("complete_asset_bundle_has_incomplete_items")
                if resolved_status in {"succeeded", "partial"} and not primary_ready:
                    raise ValueError("usable_asset_bundle_requires_ready_primary")
                if resolved_status == "succeeded" and (
                    not all_ready or normalized_failures or completion != "complete"
                ):
                    raise ValueError("succeeded_asset_bundle_has_partial_items")
                if resolved_status == "partial" and completion != "partial":
                    raise ValueError("partial_asset_bundle_requires_partial_completion")
                if resolved_status in {"pending", "running", "cancelled"}:
                    raise ValueError("invalid_persisted_asset_bundle_status")

                now = utc_now()
                bundle_id = new_id("bundle")
                connection.execute(
                    """
                    INSERT INTO asset_bundles(
                        bundle_id, job_id, resource_id, status, completion,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (bundle_id, job_id, resource_id, resolved_status, completion, now, now),
                )
                asset_ids: list[str] = []
                item_ids_by_position: dict[int, str] = {}
                for item in normalized_items:
                    item_id = new_id("bundle_item")
                    item_ids_by_position[item["position"]] = item_id
                    asset_id: str | None = None
                    asset = item.get("asset")
                    if asset is not None:
                        asset_id = new_id("asset")
                        connection.execute(
                            """
                            INSERT INTO assets(
                                asset_id, job_id, resource_id, status, local_path,
                                byte_size, media_type, sha256, filename, created_at
                            ) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                asset_id,
                                job_id,
                                resource_id,
                                asset["local_path"],
                                asset["byte_size"],
                                asset["media_type"],
                                asset["sha256"],
                                asset["filename"],
                                now,
                            ),
                        )
                        asset_ids.append(asset_id)
                    connection.execute(
                        """
                        INSERT INTO asset_bundle_items(
                            bundle_item_id, bundle_id, asset_id, position, role,
                            status, required, metadata_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            bundle_id,
                            asset_id,
                            item["position"],
                            item["role"],
                            item["status"],
                            1 if item["required"] else 0,
                            _json(item["metadata"]),
                            now,
                            now,
                        ),
                    )
                for failure in normalized_failures:
                    item_id = failure.get("bundle_item_id")
                    if item_id is None and failure.get("item_position") is not None:
                        item_id = item_ids_by_position.get(failure["item_position"])
                        if item_id is None:
                            raise ValueError("asset_bundle_failure_item_not_found")
                    elif item_id is not None and item_id not in item_ids_by_position.values():
                        raise ValueError("asset_bundle_failure_item_not_found")
                    if item_id is None and failure.get("item_role") is not None:
                        matches = [
                            candidate_id
                            for position, candidate_id in item_ids_by_position.items()
                            if next(
                                item["role"]
                                for item in normalized_items
                                if item["position"] == position
                            )
                            == failure["item_role"]
                        ]
                        if len(matches) == 1:
                            item_id = matches[0]
                    connection.execute(
                        """
                        INSERT INTO asset_bundle_failures(
                            failure_id, bundle_id, bundle_item_id, attempt, code,
                            message, retriable, details_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("bundle_failure"),
                            bundle_id,
                            item_id,
                            failure["attempt"],
                            failure["code"],
                            failure["message"],
                            1 if failure["retriable"] else 0,
                            _json(failure["details"]),
                            now,
                        ),
                    )
                job = connection.execute(
                    "SELECT asset_ids_json FROM jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                current_asset_ids = self._decode_bundle_json(
                    job["asset_ids_json"] if job is not None else None, []
                )
                if not isinstance(current_asset_ids, list):
                    current_asset_ids = []
                current_asset_ids = [str(asset_id) for asset_id in current_asset_ids]
                for asset_id in asset_ids:
                    if asset_id not in current_asset_ids:
                        current_asset_ids.append(asset_id)
                connection.execute(
                    "UPDATE jobs SET asset_ids_json = ?, updated_at = ? WHERE job_id = ?",
                    (_json(current_asset_ids), now, job_id),
                )
                result_id = bundle_id
        result = self.get_asset_bundle(result_id)
        if result is None:
            raise RuntimeError("asset_bundle_persist_failed")
        return result

    def _persist_asset_bundle_v2(
        self,
        job_id: str,
        resource_id: str,
        item_specs: Any,
        failures: Any,
        completion: str | None,
        *,
        status: str | None,
    ) -> dict[str, Any]:
        """Persist or reopen one authoritative Job x Resource Bundle.

        The first implementation of the migration accepted only a replay of
        an identical payload.  A real acquisition can first produce a partial
        result and later reopen the same relation with a repaired primary or
        companion.  This helper keeps the relation stable, replaces its
        current item projection atomically, and never creates an Asset for a
        failed item that has no existing ``asset_id``.
        """

        normalized_items = self._normalize_bundle_items(
            item_specs,
            job_id=job_id,
            resource_id=resource_id,
        )
        normalized_failures = self._normalize_bundle_failures(failures)
        for item in normalized_items:
            if item.get("failure") is not None:
                if not isinstance(item["failure"], Mapping):
                    raise ValueError("invalid_asset_bundle_failure")
                normalized_failures.extend(
                    self._normalize_bundle_failures(
                        [{**item["failure"], "item_position": item["position"]}]
                    )
                )
        positions_by_role: dict[str, list[int]] = {}
        for item in normalized_items:
            positions_by_role.setdefault(str(item["role"]), []).append(int(item["position"]))
        for failure in normalized_failures:
            if failure.get("bundle_item_id") is not None:
                raise ValueError("bundle_item_id_must_be_generated_by_store")
            if failure.get("item_position") is None and failure.get("item_role") is not None:
                matches = positions_by_role.get(str(failure["item_role"]), [])
                if len(matches) != 1:
                    raise ValueError("asset_bundle_failure_item_not_found")
                failure["item_position"] = matches[0]
            if failure.get("item_position") is not None:
                matching_items = [
                    item
                    for item in normalized_items
                    if int(item["position"]) == int(failure["item_position"])
                ]
                if len(matching_items) != 1:
                    raise ValueError("asset_bundle_failure_item_not_found")
                if (
                    failure.get("item_role") is not None
                    and str(failure["item_role"]) != str(matching_items[0]["role"])
                ):
                    raise ValueError("asset_bundle_failure_item_mismatch")
                failure["item_role"] = matching_items[0]["role"]

        with self.transaction(immediate=True) as connection:
            self._assert_bundle_job_resource(connection, job_id, resource_id)
            for item in normalized_items:
                asset_id = item.get("asset_id")
                if asset_id is None:
                    continue
                asset_row = connection.execute(
                    """
                    SELECT job_id, resource_id, local_path, byte_size,
                           media_type, sha256, filename
                    FROM assets WHERE asset_id = ?
                    """,
                    (asset_id,),
                ).fetchone()
                if asset_row is None:
                    raise KeyError(asset_id)
                if (
                    str(asset_row["job_id"]) != job_id
                    or str(asset_row["resource_id"]) != resource_id
                ):
                    raise ValueError("asset_bundle_asset_scope_mismatch")
                # Canonicalize an existing Asset to the same file projection
                # used by file-metadata calls, so replay does not depend on
                # whether the caller used create_asset first.
                item["asset"] = {
                    "local_path": str(asset_row["local_path"]),
                    "byte_size": int(asset_row["byte_size"]),
                    "media_type": str(asset_row["media_type"]),
                    "sha256": str(asset_row["sha256"]),
                    "filename": str(asset_row["filename"]),
                }

            primary_items = [
                item for item in normalized_items if item["role"] == "primary"
            ]
            if len(primary_items) != 1:
                raise ValueError("asset_bundle_requires_exactly_one_primary")
            primary = primary_items[0]
            primary_ready = primary["status"] == "ready"
            all_ready = all(item["status"] == "ready" for item in normalized_items)
            resolved_status = str(status).lower() if status is not None else None
            if resolved_status is None:
                resolved_status = (
                    "succeeded"
                    if primary_ready and all_ready and not normalized_failures
                    else "partial"
                    if primary_ready
                    else "failed"
                )
            if resolved_status not in ASSET_BUNDLE_STATUSES:
                raise ValueError("invalid_asset_bundle_status")
            if completion is None:
                resolved_completion = (
                    "complete"
                    if resolved_status == "succeeded"
                    and primary_ready
                    and all_ready
                    and not normalized_failures
                    else "partial"
                )
            else:
                resolved_completion = str(completion).lower()
                if resolved_completion not in ASSET_BUNDLE_COMPLETIONS:
                    raise ValueError("invalid_asset_bundle_completion")
            if resolved_completion == "complete" and (
                resolved_status != "succeeded"
                or not primary_ready
                or not all_ready
                or normalized_failures
            ):
                raise ValueError("complete_asset_bundle_has_incomplete_items")
            if resolved_status in {"succeeded", "partial"} and not primary_ready:
                raise ValueError("usable_asset_bundle_requires_ready_primary")
            if resolved_status == "succeeded" and resolved_completion != "complete":
                raise ValueError("succeeded_asset_bundle_has_partial_items")

            existing = connection.execute(
                "SELECT * FROM asset_bundles WHERE job_id = ? AND resource_id = ?",
                (job_id, resource_id),
            ).fetchone()
            request_fingerprint = self._bundle_request_fingerprint(
                normalized_items, normalized_failures, resolved_completion
            )
            if existing is not None:
                bundle_id = str(existing["bundle_id"])
                same_projection = (
                    self._bundle_fingerprint_from_row(connection, existing)
                    == request_fingerprint
                    and str(existing["status"]) == resolved_status
                    and str(existing["completion"]) == resolved_completion
                )
                if same_projection:
                    return self._decode_asset_bundle(connection, existing)
                if str(existing["status"]) == "succeeded":
                    raise ValueError("asset_bundle_conflict")
                created_at = str(existing["created_at"])
                now = utc_now()
                connection.execute(
                    "DELETE FROM asset_bundle_failures WHERE bundle_id = ?",
                    (bundle_id,),
                )
                connection.execute(
                    "DELETE FROM asset_bundle_items WHERE bundle_id = ?",
                    (bundle_id,),
                )
                connection.execute(
                    """
                    UPDATE asset_bundles
                    SET status = ?, completion = ?, updated_at = ?
                    WHERE bundle_id = ?
                    """,
                    (resolved_status, resolved_completion, now, bundle_id),
                )
            else:
                bundle_id = new_id("bundle")
                created_at = utc_now()
                now = created_at
                connection.execute(
                    """
                    INSERT INTO asset_bundles(
                        bundle_id, job_id, resource_id, status, completion,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bundle_id,
                        job_id,
                        resource_id,
                        resolved_status,
                        resolved_completion,
                        created_at,
                        now,
                    ),
                )

            asset_ids: list[str] = []
            item_ids_by_position: dict[int, str] = {}
            roles_by_position = {
                int(item["position"]): str(item["role"]) for item in normalized_items
            }
            for item in normalized_items:
                item_id = new_id("bundle_item")
                item_ids_by_position[int(item["position"])] = item_id
                asset_id = item.get("asset_id")
                asset = item.get("asset")
                # An existing asset was hydrated above only for its
                # fingerprint.  It must never be copied into a new Asset.
                if asset_id is None and asset is not None:
                    asset_id = new_id("asset")
                    connection.execute(
                        """
                        INSERT INTO assets(
                            asset_id, job_id, resource_id, status, local_path,
                            byte_size, media_type, sha256, filename, created_at
                        ) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            job_id,
                            resource_id,
                            asset["local_path"],
                            asset["byte_size"],
                            asset["media_type"],
                            asset["sha256"],
                            asset["filename"],
                            now,
                        ),
                    )
                if asset_id is not None:
                    asset_ids.append(str(asset_id))
                connection.execute(
                    """
                    INSERT INTO asset_bundle_items(
                        bundle_item_id, bundle_id, asset_id, position, role,
                        status, required, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        bundle_id,
                        asset_id,
                        int(item["position"]),
                        item["role"],
                        item["status"],
                        1 if item["required"] else 0,
                        _json(item["metadata"]),
                        created_at,
                        now,
                    ),
                )

            for failure in normalized_failures:
                item_id = None
                if failure.get("item_position") is not None:
                    item_id = item_ids_by_position.get(int(failure["item_position"]))
                    if item_id is None:
                        raise ValueError("asset_bundle_failure_item_not_found")
                elif failure.get("item_role") is not None:
                    matches = [
                        candidate_id
                        for position, candidate_id in item_ids_by_position.items()
                        if roles_by_position[position] == failure["item_role"]
                    ]
                    if len(matches) == 1:
                        item_id = matches[0]
                failure_id = _stable_id(
                    "bundle_failure",
                    bundle_id,
                    failure["attempt"],
                    failure["code"],
                    failure.get("item_position"),
                    failure.get("item_role"),
                )
                connection.execute(
                    """
                    INSERT INTO asset_bundle_failures(
                        failure_id, bundle_id, bundle_item_id, attempt, code,
                        message, retriable, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        failure_id,
                        bundle_id,
                        item_id,
                        failure["attempt"],
                        failure["code"],
                        failure["message"],
                        1 if failure["retriable"] else 0,
                        _json(failure["details"]),
                        now,
                    ),
                )

            job = connection.execute(
                "SELECT asset_ids_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            current_asset_ids = self._decode_bundle_json(
                job["asset_ids_json"] if job is not None else None, []
            )
            if not isinstance(current_asset_ids, list):
                current_asset_ids = []
            current_asset_ids = [str(asset_id) for asset_id in current_asset_ids]
            for asset_id in asset_ids:
                if asset_id not in current_asset_ids:
                    current_asset_ids.append(asset_id)
            connection.execute(
                "UPDATE jobs SET asset_ids_json = ?, updated_at = ? WHERE job_id = ?",
                (_json(current_asset_ids), now, job_id),
            )
            row = connection.execute(
                "SELECT * FROM asset_bundles WHERE bundle_id = ?", (bundle_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("asset_bundle_persist_failed")
            return self._decode_asset_bundle(connection, row)

    def persist_failed_asset_bundle(
        self,
        job_id: str,
        resource_id: str,
        item_specs: Any = None,
        failures: Any = None,
        *,
        items: Any = None,
        failure: Any = None,
        completion: str = "partial",
    ) -> dict[str, Any]:
        if item_specs is not None and items is not None:
            raise ValueError("duplicate_asset_bundle_items")
        if item_specs is not None and failures is None:
            candidate_items_raw = (
                [item_specs]
                if isinstance(item_specs, Mapping) or hasattr(item_specs, "to_dict")
                else list(item_specs)
            )
            candidate_items = [
                candidate.to_dict() if not isinstance(candidate, Mapping) and hasattr(candidate, "to_dict") else candidate
                for candidate in candidate_items_raw
            ]
            if candidate_items and all(
                isinstance(candidate, Mapping)
                and "code" in candidate
                and "message" in candidate
                and not any(key in candidate for key in ("role", "status", "position"))
                for candidate in candidate_items
            ):
                failures = candidate_items
                item_specs = None
        if item_specs is None:
            item_specs = items
        if item_specs is None:
            item_specs = [
                {
                    "position": 0,
                    "role": "primary",
                    "status": "failed",
                    "required": True,
                    "metadata": {},
                }
            ]
        if failure is not None:
            failures = list(failures or []) if not isinstance(failures, Mapping) else [failures]
            failures.append(failure)
        return self.persist_asset_bundle(
            job_id,
            resource_id,
            item_specs=item_specs,
            failures=failures,
            completion=completion,
            status="failed",
        )

    def get_asset_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM asset_bundles WHERE bundle_id = ?", (bundle_id,)
            ).fetchone()
            return self._decode_asset_bundle(connection, row) if row is not None else None

    def get_asset_bundle_for_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT b.*
                FROM asset_bundles b
                JOIN asset_bundle_items i ON i.bundle_id = b.bundle_id
                WHERE i.asset_id = ?
                """,
                (asset_id,),
            ).fetchone()
            return self._decode_asset_bundle(connection, row) if row is not None else None

    def get_asset_bundle_for_job_resource(
        self, job_id: str, resource_id: str
    ) -> dict[str, Any] | None:
        """Return the unique Bundle for one Job x Resource pair."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM asset_bundles
                WHERE job_id = ? AND resource_id = ?
                """,
                (job_id, resource_id),
            ).fetchone()
            return self._decode_asset_bundle(connection, row) if row is not None else None

    # Keep a concise alias for internal callers that use the domain term.
    get_asset_bundle_for_resource = get_asset_bundle_for_job_resource

    def get_asset_bundles_for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM asset_bundles
                WHERE job_id = ?
                ORDER BY created_at, bundle_id
                """,
                (job_id,),
            ).fetchall()
            return [self._decode_asset_bundle(connection, row) for row in rows]

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
        with self.transaction(immediate=True) as connection:
            job = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if job is None:
                return
            bundle_status = (
                "cancelled"
                if str(job["status"]) in {"cancelling", "cancelled"}
                else "failed"
            )
            now = utc_now()
            connection.execute(
                "UPDATE assets SET status = 'quarantined' WHERE job_id = ?", (job_id,)
            )
            connection.execute(
                """
                UPDATE asset_bundle_items
                SET status = CASE
                        WHEN asset_id IS NOT NULL OR status IN ('pending', 'ready')
                            THEN 'quarantined'
                        ELSE status
                    END,
                    updated_at = ?
                WHERE bundle_id IN (
                    SELECT bundle_id FROM asset_bundles WHERE job_id = ?
                )
                """,
                (now, job_id),
            )
            connection.execute(
                """
                UPDATE asset_bundles
                SET status = ?, completion = 'partial', updated_at = ?
                WHERE job_id = ?
                """,
                (bundle_status, now, job_id),
            )

    def get_archive_for_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ae.*, c.sha256 AS content_sha256, c.byte_size AS content_byte_size,
                       c.media_type AS content_media_type, c.resource_format,
                       c.relative_path, c.temporary_path, c.status AS content_status,
                       b.bundle_id, b.completion AS bundle_completion,
                       i.role AS bundle_role, i.position AS bundle_order
                FROM archive_entries ae
                LEFT JOIN archive_contents c ON c.content_id = ae.content_id
                LEFT JOIN asset_bundle_items i ON i.asset_id = ae.asset_id
                LEFT JOIN asset_bundles b ON b.bundle_id = i.bundle_id
                WHERE ae.asset_id = ?
                """,
                (asset_id,),
            ).fetchone()
            return self._decode_archive_row(connection, row) if row is not None else None

    def get_ready_content(
        self, sha256: str, byte_size: int, media_type: str | None = None
    ) -> dict[str, Any] | None:
        sql = """
            SELECT * FROM archive_contents
            WHERE sha256 = ? AND byte_size = ? AND status = 'ready'
        """
        values: list[Any] = [sha256, byte_size]
        if media_type:
            sql += " AND media_type = ?"
            values.append(media_type)
        with self._connect() as connection:
            row = connection.execute(sql, values).fetchone()
        return self._decode_content(row) if row is not None else None

    @staticmethod
    def _safe_relative_path(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).replace("\\", "/").strip()
        path = PurePosixPath(text)
        if (
            not text
            or path.is_absolute()
            or ":" in path.parts[0]
            or any(ord(character) < 32 or ord(character) == 127 for character in text)
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("archive_path_must_be_relative")
        return path.as_posix()

    @staticmethod
    def _decode_content(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["error"] = _load(result.pop("error_json"), None)
        return result

    def _archive_values(
        self, connection: sqlite3.Connection, archive_id: str
    ) -> dict[str, list[str]]:
        output: dict[str, list[str]] = {}
        for key, table in (
            ("secondary_domains", "archive_secondary_domains"),
            ("topics", "archive_topics"),
            ("material_purposes", "archive_purposes"),
            ("grade_levels", "archive_grade_levels"),
            ("curriculum_versions", "archive_curriculum_versions"),
            ("tags", "archive_tags"),
        ):
            rows = connection.execute(
                f"SELECT value FROM {table} WHERE archive_id = ? ORDER BY position, value",
                (archive_id,),
            ).fetchall()
            output[key] = [str(row["value"]) for row in rows]
        return output

    def _decode_archive_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        result = dict(row)
        raw_metadata = result.pop("metadata_json")
        try:
            metadata = _load(raw_metadata, {})
        except (json.JSONDecodeError, TypeError, ValueError):
            metadata = {}
        result["metadata"] = metadata
        result["legacy_metadata"] = _load(result.pop("legacy_metadata_json", None), None)
        result["error"] = _load(result.pop("error_json", None), None)
        bundle_role = result.pop("bundle_role", None)
        if bundle_role is None:
            bundle_role = result.pop("role", None)
        bundle_order = result.pop("bundle_order", None)
        if bundle_order is None:
            bundle_order = result.pop("position", None)
        bundle_completion = result.pop("bundle_completion", None)
        if bundle_completion is None:
            bundle_completion = result.pop("completion", None)
        result.setdefault("bundle_id", None)
        result["role"] = bundle_role
        result["position"] = bundle_order
        result["order"] = bundle_order
        result["completion"] = bundle_completion
        values = self._archive_values(connection, result["archive_id"])
        classification: dict[str, Any] = {
            "taxonomy_version": result.get("taxonomy_version") or "learning-v1",
            "classification_status": result.get("classification_status") or "needs_review",
            "secondary_domains": values["secondary_domains"],
            "topics": values["topics"],
            "material_purposes": values["material_purposes"],
            "grade_levels": values["grade_levels"],
            "curriculum_versions": values["curriculum_versions"],
        }
        if result.get("primary_domain") is not None:
            classification["primary_domain"] = result["primary_domain"]
        if result.get("difficulty") is not None:
            classification["difficulty"] = result["difficulty"]
        result["classification"] = classification
        result["tags"] = values["tags"]
        return result

    def create_archive(
        self, asset_id: str, library_path: Path, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        archive_id = new_id("archive")
        now = utc_now()
        normalized = self._normalize_archive_metadata(metadata)
        with self.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM archive_entries WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if existing is not None:
                return self._decode_archive_row(connection, existing)
            asset = connection.execute(
                "SELECT sha256, byte_size, media_type, filename FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            if asset is None:
                raise KeyError(asset_id)
            content = connection.execute(
                "SELECT * FROM archive_contents WHERE sha256 = ? AND byte_size = ?",
                (asset["sha256"], asset["byte_size"]),
            ).fetchone()
            relative_path = None
            raw_path = str(library_path)
            if raw_path and not Path(raw_path).is_absolute():
                relative_path = self._safe_relative_path(raw_path)
            if content is None:
                content_id = new_id("content")
                connection.execute(
                    """
                    INSERT INTO archive_contents(
                        content_id, sha256, byte_size, media_type, resource_format,
                        relative_path, status, owner_archive_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)
                    """,
                    (
                        content_id,
                        asset["sha256"],
                        asset["byte_size"],
                        asset["media_type"],
                        self._infer_resource_format(asset["media_type"], asset["filename"]),
                        relative_path,
                        archive_id,
                        now,
                        now,
                    ),
                )
            else:
                content_id = str(content["content_id"])
            connection.execute(
                """
                INSERT INTO archive_entries(
                    archive_id, asset_id, library_path, metadata_json, created_at,
                    content_id, status, archived_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?)
                """,
                (
                    archive_id,
                    asset_id,
                    raw_path,
                    _json(normalized),
                    now,
                    content_id,
                    now,
                    now,
                ),
            )
            self._update_archive_classification(
                connection,
                archive_id,
                normalized,
                content_id=content_id,
                status="ready",
                archived_at=now,
            )
        return self.get_archive_for_asset(asset_id) or {}

    def reserve_archive(
        self,
        asset_id: str,
        metadata: dict[str, Any],
        intended_relative_path: str,
        *,
        temporary_path: str | None = None,
        idempotency_scope: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> dict[str, Any]:
        intended = self._safe_relative_path(intended_relative_path)
        temporary = self._safe_relative_path(temporary_path)
        normalized = self._normalize_archive_metadata(metadata)
        idem_values = (idempotency_scope, idempotency_key, request_hash)
        if any(idem_values) and not all(idem_values):
            raise ValueError("incomplete_idempotency_reservation")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            if all(idem_values):
                replay = self._replay_in_transaction(
                    connection,
                    str(idempotency_scope),
                    str(idempotency_key),
                    str(request_hash),
                )
                if replay is not None:
                    replay["replayed"] = True
                    return replay
            existing = connection.execute(
                "SELECT * FROM archive_entries WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if existing is not None:
                existing_metadata = self._normalize_archive_metadata(
                    _load(existing["metadata_json"], {})
                )
                if _json(existing_metadata) != _json(normalized):
                    raise ValueError("archive_metadata_conflict")
                existing_content = connection.execute(
                    "SELECT * FROM archive_contents WHERE content_id = ?",
                    (existing["content_id"],),
                ).fetchone()
                content_status = (
                    str(existing_content["status"]) if existing_content is not None else "missing"
                )
                result = {
                    "archive_id": str(existing["archive_id"]),
                    "content_id": existing["content_id"],
                    "asset_id": asset_id,
                    "status": str(existing["status"]),
                    "content_status": content_status,
                    "intended_relative_path": (
                        existing_content["relative_path"] if existing_content is not None else None
                    ),
                    "temporary_path": (
                        existing_content["temporary_path"] if existing_content is not None else None
                    ),
                    "deduplicated_candidate": content_status == "ready",
                    "owns_content": bool(
                        existing_content is not None
                        and existing_content["owner_archive_id"] == existing["archive_id"]
                    ),
                    "replayed": False,
                }
                if all(idem_values):
                    self._put_idempotency_in_transaction(
                        connection,
                        str(idempotency_scope),
                        str(idempotency_key),
                        str(request_hash),
                        result["archive_id"],
                        result,
                        now,
                    )
                return result
            asset = connection.execute(
                """
                SELECT s.*, r.platform, r.resource_type, r.title
                FROM assets s JOIN resources r ON r.resource_id = s.resource_id
                WHERE s.asset_id = ?
                """,
                (asset_id,),
            ).fetchone()
            if asset is None:
                raise KeyError(asset_id)
            if asset["status"] != "ready":
                raise ValueError("asset_not_ready")
            archive_id = new_id("archive")
            content = connection.execute(
                "SELECT * FROM archive_contents WHERE sha256 = ? AND byte_size = ?",
                (asset["sha256"], asset["byte_size"]),
            ).fetchone()
            if content is not None and content["media_type"] != asset["media_type"]:
                raise ValueError("content_media_type_conflict")
            if content is None:
                content_id = new_id("content")
                owns_content = True
                content_status = "pending"
                connection.execute(
                    """
                    INSERT INTO archive_contents(
                        content_id, sha256, byte_size, media_type, resource_format, relative_path,
                        temporary_path, status, owner_archive_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        content_id,
                        asset["sha256"],
                        int(asset["byte_size"]),
                        asset["media_type"],
                        self._infer_resource_format(asset["media_type"], asset["filename"]),
                        intended,
                        temporary,
                        archive_id,
                        now,
                        now,
                    ),
                )
            else:
                content_id = str(content["content_id"])
                owns_content = str(content["owner_archive_id"] or "") == archive_id
                content_status = str(content["status"])
            connection.execute(
                """
                INSERT INTO archive_entries(
                    archive_id, asset_id, library_path, metadata_json, created_at,
                    content_id, status, archived_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    archive_id,
                    asset_id,
                    intended,
                    _json(normalized),
                    now,
                    content_id,
                    now,
                    now,
                ),
            )
            self._update_archive_classification(
                connection,
                archive_id,
                normalized,
                content_id=content_id,
                status="pending",
                archived_at=now,
            )
            result = {
                "archive_id": archive_id,
                "content_id": content_id,
                "asset_id": asset_id,
                "status": "pending",
                "content_status": content_status,
                "intended_relative_path": intended,
                "temporary_path": temporary,
                "sha256": str(asset["sha256"]),
                "byte_size": int(asset["byte_size"]),
                "media_type": str(asset["media_type"]),
                "deduplicated_candidate": content_status == "ready",
                "owns_content": owns_content,
                "replayed": False,
            }
            if all(idem_values):
                self._put_idempotency_in_transaction(
                    connection,
                    str(idempotency_scope),
                    str(idempotency_key),
                    str(request_hash),
                    archive_id,
                    result,
                    now,
                )
            return result

    def mark_archive_ready(
        self,
        archive_id: str,
        *,
        relative_path: str | None = None,
        resource_format: str | None = None,
        flow_id: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_path = self._safe_relative_path(relative_path)
        if resource_format is not None and resource_format not in {
            "video",
            "document",
            "audio",
            "other",
        }:
            raise ValueError("invalid_resource_format")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM archive_entries WHERE archive_id = ?", (archive_id,)
            ).fetchone()
            if row is None or not row["content_id"]:
                raise KeyError(archive_id)
            content = connection.execute(
                "SELECT * FROM archive_contents WHERE content_id = ?", (row["content_id"],)
            ).fetchone()
            if content is None:
                raise KeyError(str(row["content_id"]))
            final_path = safe_path or content["relative_path"]
            if not final_path:
                raise ValueError("ready_archive_requires_relative_path")
            connection.execute(
                """
                UPDATE archive_contents SET status = 'ready', relative_path = ?,
                    temporary_path = NULL, resource_format = COALESCE(?, resource_format),
                    error_json = NULL, updated_at = ? WHERE content_id = ?
                """,
                (final_path, resource_format, now, row["content_id"]),
            )
            connection.execute(
                """
                UPDATE archive_entries SET status = 'ready', error_json = NULL,
                    updated_at = ? WHERE archive_id = ?
                """,
                (now, archive_id),
            )
            if row["status"] != "ready":
                self._audit_in_transaction(
                    connection,
                    flow_id,
                    "asset.archive",
                    archive_id,
                    {"asset_id": row["asset_id"], "content_id": row["content_id"]},
                    now,
                )
            if result is not None:
                connection.execute(
                    "UPDATE idempotency_keys SET result_json = ? WHERE result_id = ?",
                    (_json(result), archive_id),
                )
            output = connection.execute(
                """
                SELECT ae.*, c.relative_path, c.temporary_path,
                       c.status AS content_status, c.resource_format
                FROM archive_entries ae JOIN archive_contents c ON c.content_id = ae.content_id
                WHERE ae.archive_id = ?
                """,
                (archive_id,),
            ).fetchone()
            return self._decode_archive_row(connection, output)

    def _mark_archive_problem(
        self, archive_id: str, status: str, error: dict[str, Any] | None
    ) -> None:
        if status not in {"failed", "missing", "corrupt"}:
            raise ValueError("invalid_archive_problem_status")
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT content_id FROM archive_entries WHERE archive_id = ?", (archive_id,)
            ).fetchone()
            if row is None:
                raise KeyError(archive_id)
            error_json = _json(error) if error is not None else None
            if status in {"missing", "corrupt"}:
                content = connection.execute(
                    "SELECT relative_path FROM archive_contents WHERE content_id = ?",
                    (row["content_id"],),
                ).fetchone()
                if content is not None and content["relative_path"] is None:
                    # Migrated legacy entries can point at separate old files even
                    # when their hashes deduplicate to one content row.  Degrade
                    # only the broken legacy relation while another copy is ready.
                    connection.execute(
                        """
                        UPDATE archive_entries SET status = ?, error_json = ?, updated_at = ?
                        WHERE archive_id = ?
                        """,
                        (status, error_json, now, archive_id),
                    )
                    remaining = connection.execute(
                        """
                        SELECT 1 FROM archive_entries
                        WHERE content_id = ? AND status = 'ready' LIMIT 1
                        """,
                        (row["content_id"],),
                    ).fetchone()
                    if remaining is None:
                        connection.execute(
                            """
                            UPDATE archive_contents SET status = ?, error_json = ?, updated_at = ?
                            WHERE content_id = ?
                            """,
                            (status, error_json, now, row["content_id"]),
                        )
                else:
                    connection.execute(
                        """
                        UPDATE archive_contents SET status = ?, error_json = ?, updated_at = ?
                        WHERE content_id = ?
                        """,
                        (status, error_json, now, row["content_id"]),
                    )
                    connection.execute(
                        """
                        UPDATE archive_entries SET status = ?, error_json = ?, updated_at = ?
                        WHERE content_id = ?
                        """,
                        (status, error_json, now, row["content_id"]),
                    )
            else:
                content = connection.execute(
                    "SELECT owner_archive_id FROM archive_contents WHERE content_id = ?",
                    (row["content_id"],),
                ).fetchone()
                if content is not None and content["owner_archive_id"] == archive_id:
                    connection.execute(
                        """
                        UPDATE archive_contents SET status = 'failed', error_json = ?, updated_at = ?
                        WHERE content_id = ? AND status = 'pending'
                        """,
                        (error_json, now, row["content_id"]),
                    )
                    connection.execute(
                        """
                        UPDATE archive_entries SET status = 'failed', error_json = ?, updated_at = ?
                        WHERE content_id = ? AND status = 'pending'
                        """,
                        (error_json, now, row["content_id"]),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE archive_entries SET status = 'failed', error_json = ?, updated_at = ?
                        WHERE archive_id = ?
                        """,
                        (error_json, now, archive_id),
                    )

    def mark_archive_failed(
        self, archive_id: str, error: dict[str, Any] | None = None
    ) -> None:
        self._mark_archive_problem(archive_id, "failed", error)

    def retry_archive_reservation(self, archive_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                """
                SELECT ae.archive_id, ae.asset_id, ae.content_id, ae.status,
                       c.status AS content_status, c.owner_archive_id,
                       c.relative_path, c.temporary_path, c.sha256, c.byte_size,
                       c.media_type
                FROM archive_entries ae
                JOIN archive_contents c ON c.content_id = ae.content_id
                WHERE ae.archive_id = ?
                """,
                (archive_id,),
            ).fetchone()
            if row is None:
                raise KeyError(archive_id)
            if (
                row["status"] != "failed"
                or row["content_status"] != "failed"
                or row["owner_archive_id"] != archive_id
            ):
                raise ValueError("archive_retry_not_allowed")
            connection.execute(
                """
                UPDATE archive_contents SET status = 'pending', error_json = NULL,
                    updated_at = ? WHERE content_id = ?
                """,
                (now, row["content_id"]),
            )
            connection.execute(
                """
                UPDATE archive_entries SET status = 'pending', error_json = NULL,
                    updated_at = ? WHERE archive_id = ?
                """,
                (now, archive_id),
            )
            result = {
                "archive_id": archive_id,
                "content_id": str(row["content_id"]),
                "asset_id": str(row["asset_id"]),
                "status": "pending",
                "content_status": "pending",
                "intended_relative_path": row["relative_path"],
                "temporary_path": row["temporary_path"],
                "sha256": str(row["sha256"]),
                "byte_size": int(row["byte_size"]),
                "media_type": str(row["media_type"]),
                "deduplicated_candidate": False,
                "owns_content": True,
                "replayed": False,
                "retried": True,
            }
            connection.execute(
                "UPDATE idempotency_keys SET result_json = ? WHERE result_id = ?",
                (_json(result), archive_id),
            )
            return result

    def mark_archive_missing(
        self, archive_id: str, error: dict[str, Any] | None = None
    ) -> None:
        self._mark_archive_problem(archive_id, "missing", error)

    def mark_archive_corrupt(
        self, archive_id: str, error: dict[str, Any] | None = None
    ) -> None:
        self._mark_archive_problem(archive_id, "corrupt", error)

    def list_archive_reconciliation_items(
        self,
        statuses: tuple[str, ...] = ("pending", "ready"),
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        invalid = set(statuses) - ARCHIVE_STATES
        if invalid or not statuses or not 1 <= limit <= 5000:
            raise ValueError("invalid_reconciliation_query")
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT ae.archive_id, ae.asset_id, ae.status, ae.updated_at,
                       ae.library_path,
                       c.content_id, c.status AS content_status, c.sha256, c.byte_size,
                       c.media_type, c.resource_format, c.relative_path, c.temporary_path,
                       c.owner_archive_id
                FROM archive_entries ae
                JOIN archive_contents c ON c.content_id = ae.content_id
                WHERE ae.status IN ({placeholders})
                ORDER BY ae.updated_at, ae.archive_id LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _filter_values(filters: dict[str, Any], *names: str) -> list[str]:
        for name in names:
            raw = filters.get(name)
            if raw is None:
                continue
            if isinstance(raw, list):
                return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
            text = str(raw).strip()
            return [text] if text else []
        return []

    @staticmethod
    def _append_in_filter(
        conditions: list[str], values: list[Any], expression: str, choices: list[str]
    ) -> None:
        if not choices:
            return
        placeholders = ",".join("?" for _ in choices)
        conditions.append(f"{expression} IN ({placeholders})")
        values.extend(choices)

    @staticmethod
    def _append_relation_filter(
        conditions: list[str],
        values: list[Any],
        table: str,
        choices: list[str],
    ) -> None:
        if not choices:
            return
        placeholders = ",".join("?" for _ in choices)
        conditions.append(
            f"EXISTS (SELECT 1 FROM {table} mv WHERE mv.archive_id = ae.archive_id "
            f"AND mv.value IN ({placeholders}))"
        )
        values.extend(choices)

    def search_library(
        self,
        query: str | None,
        limit: int,
        filters: dict[str, Any] | None = None,
        *,
        cursor: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise ValueError("library_limit_out_of_range")
        f = filters or {}
        sql = """
            SELECT ae.archive_id, ae.asset_id, ae.metadata_json, ae.created_at,
                   ae.library_path,
                   ae.archived_at, ae.taxonomy_version, ae.classification_status,
                   ae.primary_domain, ae.primary_topic, ae.collection, ae.difficulty,
                   ae.notes, ae.status, ae.content_id,
                   c.relative_path, c.resource_format, c.status AS content_status,
                   s.filename, s.byte_size, s.media_type, s.sha256, r.resource_id,
                   r.title, r.platform, r.resource_type, r.source_url,
                   b.bundle_id AS bundle_id, bi.role AS role, bi.position AS position,
                   b.completion AS completion
            FROM archive_entries ae
            JOIN archive_contents c ON c.content_id = ae.content_id
            JOIN assets s ON s.asset_id = ae.asset_id
            JOIN resources r ON r.resource_id = s.resource_id
            LEFT JOIN asset_bundle_items bi ON bi.asset_id = s.asset_id
            LEFT JOIN asset_bundles b ON b.bundle_id = bi.bundle_id
        """
        conditions = ["ae.status = 'ready'", "c.status = 'ready'", "s.status = 'ready'"]
        values: list[Any] = []

        text_query = str(query or f.get("query") or "").strip()
        if text_query:
            escaped = (
                text_query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            needle = f"%{escaped}%"
            conditions.append(
                """
                (lower(r.title) LIKE ? ESCAPE '\\'
                 OR lower(COALESCE(ae.notes, '')) LIKE ? ESCAPE '\\'
                 OR EXISTS (SELECT 1 FROM archive_topics qt
                            WHERE qt.archive_id = ae.archive_id
                              AND lower(qt.value) LIKE ? ESCAPE '\\')
                 OR EXISTS (SELECT 1 FROM archive_tags qg
                            WHERE qg.archive_id = ae.archive_id
                              AND lower(qg.value) LIKE ? ESCAPE '\\'))
                """
            )
            values.extend([needle, needle, needle, needle])

        self._append_in_filter(
            conditions,
            values,
            "ae.taxonomy_version",
            self._filter_values(f, "taxonomy_versions", "taxonomy_version"),
        )
        self._append_in_filter(
            conditions,
            values,
            "ae.classification_status",
            self._filter_values(f, "classification_statuses", "classification_status"),
        )
        self._append_in_filter(
            conditions,
            values,
            "ae.primary_domain",
            self._filter_values(f, "primary_domains", "primary_domain"),
        )
        self._append_in_filter(
            conditions,
            values,
            "ae.difficulty",
            self._filter_values(f, "difficulties", "difficulty"),
        )
        self._append_in_filter(
            conditions,
            values,
            "ae.collection",
            self._filter_values(f, "collections", "collection"),
        )
        self._append_in_filter(
            conditions, values, "r.platform", self._filter_values(f, "platforms", "platform")
        )
        self._append_in_filter(
            conditions,
            values,
            "r.resource_type",
            self._filter_values(f, "resource_types", "resource_type"),
        )
        self._append_in_filter(
            conditions,
            values,
            "c.resource_format",
            self._filter_values(f, "resource_formats", "resource_format"),
        )
        for names, table in (
            (("secondary_domains", "secondary_domain"), "archive_secondary_domains"),
            (("topics", "topic"), "archive_topics"),
            (("material_purposes", "purposes", "purpose"), "archive_purposes"),
            (("grade_levels", "grade_level"), "archive_grade_levels"),
            (("curriculum_versions", "curriculum_version"), "archive_curriculum_versions"),
            (("tags", "tag"), "archive_tags"),
        ):
            self._append_relation_filter(
                conditions, values, table, self._filter_values(f, *names)
            )
        if f.get("archived_after"):
            conditions.append("julianday(ae.archived_at) >= julianday(?)")
            values.append(str(f["archived_after"]))
        if f.get("archived_before"):
            conditions.append("julianday(ae.archived_at) <= julianday(?)")
            values.append(str(f["archived_before"]))
        if cursor is not None:
            archived_at, archive_id = cursor
            conditions.append(
                "(ae.archived_at < ? OR (ae.archived_at = ? AND ae.archive_id < ?))"
            )
            values.extend([archived_at, archived_at, archive_id])

        sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY ae.archived_at DESC, ae.archive_id DESC LIMIT ?"
        values.append(limit + 1)
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
            has_more = len(rows) > limit
            page = rows[:limit]
            items = [self._decode_archive_row(connection, row) for row in page]
        next_keyset = None
        if has_more and items:
            next_keyset = (str(items[-1]["archived_at"]), str(items[-1]["archive_id"]))
        return {"items": items, "has_more": has_more, "next_keyset": next_keyset}

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
