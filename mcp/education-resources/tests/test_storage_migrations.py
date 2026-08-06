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
            self.assertEqual([(1,), (2,)], versions)
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
                }.issubset(tables)
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
                    2,
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                )


if __name__ == "__main__":
    unittest.main()
