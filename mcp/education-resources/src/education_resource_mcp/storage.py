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
from typing import Any, Iterator
import uuid


LATEST_SCHEMA_VERSION = 2
ARCHIVE_STATES = {"pending", "ready", "failed", "missing", "corrupt"}


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
    ) -> dict[str, Any]:
        scope = f"resource_search:{flow_id}"
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
                """
                SELECT ae.*, c.sha256 AS content_sha256, c.byte_size AS content_byte_size,
                       c.media_type AS content_media_type, c.resource_format,
                       c.relative_path, c.temporary_path, c.status AS content_status
                FROM archive_entries ae
                LEFT JOIN archive_contents c ON c.content_id = ae.content_id
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
                   r.title, r.platform, r.resource_type, r.source_url
            FROM archive_entries ae
            JOIN archive_contents c ON c.content_id = ae.content_id
            JOIN assets s ON s.asset_id = ae.asset_id
            JOIN resources r ON r.resource_id = s.resource_id
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
