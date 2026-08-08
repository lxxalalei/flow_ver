from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import LATEST_SCHEMA_VERSION, Store


def create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE flows (
            flow_id TEXT PRIMARY KEY, query TEXT NOT NULL, context_json TEXT NOT NULL,
            status TEXT NOT NULL, presented_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE resources (
            resource_id TEXT PRIMARY KEY, flow_id TEXT NOT NULL,
            presented_version INTEGER NOT NULL, platform TEXT NOT NULL,
            title TEXT NOT NULL, source_url TEXT NOT NULL, resource_type TEXT NOT NULL,
            summary TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE download_plans (
            plan_id TEXT PRIMARY KEY, flow_id TEXT NOT NULL,
            presented_version INTEGER NOT NULL, resource_ids_json TEXT NOT NULL,
            options_json TEXT NOT NULL, confirmation_token TEXT NOT NULL,
            confirmation_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, flow_id TEXT NOT NULL, plan_id TEXT NOT NULL,
            status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
            asset_ids_json TEXT NOT NULL DEFAULT '[]', error_json TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE assets (
            asset_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, resource_id TEXT NOT NULL,
            status TEXT NOT NULL, local_path TEXT NOT NULL, byte_size INTEGER NOT NULL,
            media_type TEXT NOT NULL, sha256 TEXT NOT NULL, filename TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE archive_entries (
            archive_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL UNIQUE,
            library_path TEXT NOT NULL, metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    now = "2025-01-02T03:04:05+00:00"
    connection.execute(
        "INSERT INTO flows VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("flow_old", "科学", "{}", "downloaded", 1, now, now),
    )
    connection.execute(
        "INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "res_old", "flow_old", 1, "legacy", "太阳系", "https://example.com/a",
            "document", None, "{}", now,
        ),
    )
    connection.execute(
        "INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "res_unknown", "flow_old", 1, "legacy", "旧资料", "https://example.com/b",
            "document", None, "{}", now,
        ),
    )
    connection.execute(
        "INSERT INTO download_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "plan_old", "flow_old", 1, '["res_old"]', "{}", "token", "hash",
            "2099-01-01T00:00:00+00:00", 1, now,
        ),
    )
    connection.execute(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("job_old", "flow_old", "plan_old", "succeeded", 100, '["asset_old"]', None, now, now),
    )
    connection.execute(
        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "asset_old", "job_old", "res_old", "ready", "/legacy/jobs/a.pdf", 123,
            "application/pdf", "a" * 64, "a.pdf", now,
        ),
    )
    connection.execute(
        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "asset_unknown", "job_old", "res_unknown", "ready", "/legacy/jobs/b.pdf", 321,
            "application/pdf", "b" * 64, "b.pdf", now,
        ),
    )
    metadata = {
        "primary_domain": "自然科学",
        "topics": ["天文与宇宙"],
        "tags": ["科普"],
        "legacy_extra": {"preserve": True},
    }
    connection.execute(
        "INSERT INTO archive_entries VALUES (?, ?, ?, ?, ?)",
        ("archive_old", "asset_old", "/legacy/library/a.pdf", json.dumps(metadata), now),
    )
    connection.execute(
        "INSERT INTO archive_entries VALUES (?, ?, ?, ?, ?)",
        (
            "archive_unknown",
            "asset_unknown",
            "/legacy/library/b.pdf",
            json.dumps({"primary_domain": "亲子陪伴", "topics": ["共同阅读"]}),
            now,
        ),
    )
    connection.commit()
    connection.close()


def create_schema_v3_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE flows (
            flow_id TEXT PRIMARY KEY, query TEXT NOT NULL, context_json TEXT NOT NULL,
            status TEXT NOT NULL, presented_version INTEGER NOT NULL DEFAULT 0,
            task_version INTEGER NOT NULL DEFAULT 1,
            result_version INTEGER NOT NULL DEFAULT 0,
            selection_version INTEGER NOT NULL DEFAULT 0,
            current_result_set_id TEXT, current_presentation_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE resources (
            resource_id TEXT PRIMARY KEY, flow_id TEXT NOT NULL,
            presented_version INTEGER NOT NULL, platform TEXT NOT NULL,
            title TEXT NOT NULL, source_url TEXT NOT NULL, resource_type TEXT NOT NULL,
            summary TEXT, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
            result_set_id TEXT, result_position INTEGER
        );
        CREATE TABLE search_result_sets (
            result_set_id TEXT PRIMARY KEY,
            flow_id TEXT NOT NULL,
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
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        );
        """
    )
    now = "2025-02-03T04:05:06+00:00"
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, ?)",
        (1, "v2_control_plane_columns", now),
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, ?)",
        (2, "learning_archive_foundation", now),
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, ?)",
        (3, "resource_resolution_foundation", now),
    )
    connection.execute(
        "INSERT INTO flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("flow_v3", "旧搜索", "{}", "reviewing", 0, 1, 1, 0, "rset_v3", None, now, now),
    )
    connection.execute(
        "INSERT INTO search_result_sets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rset_v3", "flow_v3", "search_v3", 1, "旧搜索", "{}", "ready", "[]", "[]", now),
    )
    connection.execute(
        "INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "res_v3", "flow_v3", 0, "generic", "旧资源", "https://example.com/v3",
            "article", None, "{}", now, "rset_v3", 1,
        ),
    )
    connection.execute("PRAGMA user_version = 3")
    connection.commit()
    connection.close()


class StorageMigrationTests(unittest.TestCase):
    def test_fresh_database_has_explicit_latest_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fresh.sqlite"
            store = Store(database)
            self.assertEqual(LATEST_SCHEMA_VERSION, store.schema_version())
            with closing(sqlite3.connect(database)) as connection:
                versions = connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                result_set_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(search_result_sets)"
                    ).fetchall()
                }
                resource_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(resources)"
                    ).fetchall()
                }
            self.assertEqual([(1,), (2,), (3,), (4,), (5,)], versions)
            self.assertTrue(
                {
                    "archive_contents",
                    "archive_secondary_domains",
                    "archive_topics",
                    "archive_purposes",
                    "archive_grade_levels",
                    "archive_curriculum_versions",
                    "archive_tags",
                    "store_metadata",
                    "resource_resolutions",
                    "asset_bundles",
                    "asset_bundle_items",
                    "asset_bundle_failures",
                }.issubset(tables)
            )
            self.assertTrue(
                {
                    "task_version",
                    "mode",
                    "base_result_set_id",
                    "round",
                    "provenance_json",
                    "coverage_json",
                }.issubset(result_set_columns)
            )
            self.assertTrue(
                {"identity_json", "identity_rules_version"}.issubset(resource_columns)
            )

    def test_legacy_archive_is_backfilled_without_rewriting_original_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite"
            create_legacy_database(database)

            store = Store(database)
            archive = store.get_archive_for_asset("asset_old")

            self.assertIsNotNone(archive)
            assert archive is not None
            self.assertEqual("/legacy/library/a.pdf", archive["library_path"])
            self.assertEqual("自然科学", archive["legacy_metadata"]["primary_domain"])
            self.assertEqual("natural_science", archive["primary_domain"])
            self.assertEqual("classified", archive["classification_status"])
            self.assertEqual(["天文与宇宙"], archive["classification"]["topics"])
            self.assertEqual(["科普"], archive["tags"])
            self.assertIsNone(archive["relative_path"])
            self.assertEqual("document", archive["resource_format"])
            unknown = store.get_archive_for_asset("asset_unknown")
            assert unknown is not None
            self.assertEqual("needs_review", unknown["classification_status"])
            self.assertIsNone(unknown["primary_domain"])
            self.assertEqual(
                "亲子陪伴",
                unknown["legacy_metadata"]["primary_domain"],
            )
            reconciliation = {
                item["archive_id"]: item
                for item in store.list_archive_reconciliation_items(("ready",))
            }
            self.assertEqual(
                "/legacy/library/a.pdf",
                reconciliation["archive_old"]["library_path"],
            )

    def test_migration_and_metadata_secret_are_idempotent_across_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite"
            create_legacy_database(database)
            first = Store(database)
            secret = first.get_or_create_metadata_secret("library_cursor_hmac")

            second = Store(database)
            self.assertEqual(secret, second.get_or_create_metadata_secret("library_cursor_hmac"))
            self.assertEqual(64, len(secret))
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    1,
                    connection.execute(
                        "SELECT COUNT(*) FROM archive_entries WHERE archive_id = 'archive_old'"
                    ).fetchone()[0],
                )
                self.assertEqual(
                    2,
                    connection.execute("SELECT COUNT(*) FROM archive_contents").fetchone()[0],
                )
                self.assertEqual(
                    5,
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                )
                bundle_rows = connection.execute(
                    """
                    SELECT b.bundle_id, b.job_id, b.resource_id, b.status, b.completion,
                           i.asset_id, i.position, i.role
                    FROM asset_bundles b
                    JOIN asset_bundle_items i ON i.bundle_id = b.bundle_id
                    WHERE b.job_id = 'job_old'
                    ORDER BY b.resource_id, i.position
                    """
                ).fetchall()
            self.assertEqual(1, len(bundle_rows))
            self.assertEqual(
                [
                    ("asset_old", 0, "primary"),
                ],
                [(row[5], row[6], row[7]) for row in bundle_rows],
            )

    def test_schema_version_2_database_applies_resolution_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "v2.sqlite"
            Store(database)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("DROP TABLE resource_resolutions")
                connection.execute(
                    "DELETE FROM schema_migrations WHERE version IN (3, 4, 5)"
                )
                connection.execute("PRAGMA user_version = 2")
                connection.commit()

            migrated = Store(database)
            self.assertEqual(5, migrated.schema_version())
            with closing(sqlite3.connect(database)) as connection:
                migration = connection.execute(
                    "SELECT name FROM schema_migrations WHERE version = 3"
                ).fetchone()
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(resource_resolutions)"
                    ).fetchall()
                }
                foreign_keys = connection.execute(
                    "PRAGMA foreign_key_list(resource_resolutions)"
                ).fetchall()
            self.assertEqual(("resource_resolution_foundation",), migration)
            self.assertTrue(
                {
                    "resolution_id",
                    "flow_id",
                    "resource_id",
                    "profile_version",
                    "source_fingerprint",
                    "resolution_status",
                    "resolved_json",
                    "inspection_json",
                    "failures_json",
                    "inspected_at",
                    "created_at",
                    "updated_at",
                }.issubset(columns)
            )
            self.assertEqual({"flows", "resources"}, {row[2] for row in foreign_keys})

    def test_schema_version_3_database_applies_result_set_extend_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "v3.sqlite"
            create_schema_v3_database(database)

            migrated = Store(database)

            self.assertEqual(5, migrated.schema_version())
            result_set = migrated.get_result_set("rset_v3")
            self.assertIsNotNone(result_set)
            assert result_set is not None
            self.assertEqual("replace", result_set["mode"])
            self.assertIsNone(result_set["base_result_set_id"])
            self.assertEqual(1, result_set["round"])
            self.assertEqual({}, result_set["provenance"])
            self.assertEqual({}, result_set["coverage"])
            self.assertEqual(1, result_set["task_version"])
            self.assertEqual({}, result_set["resources"][0]["identity"])
            self.assertEqual("identity-v1", result_set["resources"][0]["identity_rules_version"])

            with closing(sqlite3.connect(database)) as connection:
                migration = connection.execute(
                    "SELECT name FROM schema_migrations WHERE version = 4"
                ).fetchone()
                stored_defaults = connection.execute(
                    """
                    SELECT task_version, mode, base_result_set_id, round,
                           provenance_json, coverage_json
                    FROM search_result_sets WHERE result_set_id = 'rset_v3'
                    """
                ).fetchone()
            self.assertEqual(("result_set_extend_storage",), migration)
            self.assertEqual((1, "replace", None, 1, "{}", "{}"), stored_defaults)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    ("multimodal_asset_bundle",),
                    connection.execute(
                        "SELECT name FROM schema_migrations WHERE version = 5"
                    ).fetchone(),
                )

    def test_schema_version_4_backfills_ordered_group_bundles_with_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "v4.sqlite"
            store = Store(database)
            with store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO flows(
                        flow_id, query, context_json, status, presented_version,
                        task_version, result_version, selection_version, created_at, updated_at
                    ) VALUES ('flow_v4', '旧资源', '{}', 'downloaded', 1, 1, 1, 1, ?, ?)
                    """,
                    ("2025-03-01T00:00:00+00:00", "2025-03-01T00:00:00+00:00"),
                )
                connection.execute(
                    """
                    INSERT INTO download_plans(
                        plan_id, flow_id, presented_version, resource_ids_json, options_json,
                        confirmation_token, confirmation_hash, expires_at, used, created_at,
                        selection_version, selection_digest, plan_digest
                    ) VALUES ('plan_v4', 'flow_v4', 1, '[]', '{}', 'token', 'hash',
                              '2099-01-01T00:00:00+00:00', 1, ?, 1, 'selection', 'plan')
                    """,
                    ("2025-03-01T00:00:00+00:00",),
                )
                connection.execute(
                    """
                    INSERT INTO jobs(
                        job_id, flow_id, plan_id, status, progress, asset_ids_json,
                        created_at, updated_at
                    ) VALUES ('job_v4', 'flow_v4', 'plan_v4', 'succeeded', 100,
                              '["asset_b","asset_c","asset_a"]', ?, ?)
                    """,
                    ("2025-03-01T00:00:00+00:00", "2025-03-01T00:00:00+00:00"),
                )
                for resource_id, title in (("resource_v4_a", "甲"), ("resource_v4_b", "乙")):
                    connection.execute(
                        """
                        INSERT INTO resources(
                            resource_id, flow_id, presented_version, platform, title,
                            source_url, resource_type, metadata_json, created_at
                        ) VALUES (?, 'flow_v4', 1, 'generic', ?, ?, 'document', '{}', ?)
                        """,
                        (
                            resource_id,
                            title,
                            f"https://example.com/{resource_id}",
                            "2025-03-01T00:00:00+00:00",
                        ),
                    )
                for asset_id, resource_id, filename in (
                    ("asset_b", "resource_v4_a", "second.pdf"),
                    ("asset_c", "resource_v4_b", "other.pdf"),
                    ("asset_a", "resource_v4_a", "first.pdf"),
                ):
                    connection.execute(
                        """
                        INSERT INTO assets(
                            asset_id, job_id, resource_id, status, local_path, byte_size,
                            media_type, sha256, filename, created_at
                        ) VALUES (?, 'job_v4', ?, 'ready', ?, 1, 'application/pdf', ?, ?, ?)
                        """,
                        (
                            asset_id,
                            resource_id,
                            f"/legacy/{filename}",
                            asset_id.ljust(64, "0"),
                            filename,
                            "2025-03-01T00:00:00+00:00",
                        ),
                    )
                connection.execute("DELETE FROM schema_migrations WHERE version = 5")
                connection.execute("PRAGMA user_version = 4")

            migrated = Store(database)
            bundles = migrated.get_asset_bundles_for_job("job_v4")
            self.assertEqual(2, len(bundles))
            grouped = {
                bundle["resource_id"]: [(item["asset_id"], item["position"], item["role"]) for item in bundle["items"]]
                for bundle in bundles
            }
            self.assertEqual(
                [("asset_b", 0, "primary"), ("asset_a", 1, "attachment")],
                grouped["resource_v4_a"],
            )
            self.assertEqual([("asset_c", 0, "primary")], grouped["resource_v4_b"])
            first_ids = [bundle["bundle_id"] for bundle in bundles]

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM schema_migrations WHERE version = 5")
                connection.execute("PRAGMA user_version = 4")
                connection.commit()
            reopened = Store(database)
            second_ids = [bundle["bundle_id"] for bundle in reopened.get_asset_bundles_for_job("job_v4")]
            self.assertEqual(first_ids, second_ids)
            with reopened._connect() as connection:
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM asset_bundles").fetchone()[0])
                self.assertEqual(3, connection.execute("SELECT COUNT(*) FROM asset_bundle_items").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
