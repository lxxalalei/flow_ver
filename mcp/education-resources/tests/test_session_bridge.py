"""Tests for consuming the standalone session-manager credential store."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from education_resource_mcp.adapters.smartedu import SmartEduSearchAdapter
from education_resource_mcp.config import Settings
from education_resource_mcp.session_bridge import create_session_store
from education_resource_mcp.sessions import SessionStore as LegacySessionStore


STANDALONE_SESSION_MANAGER_AVAILABLE = (
    importlib.util.find_spec("session_manager") is not None
)


class FakeStandaloneStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


class SessionBridgeTests(unittest.TestCase):
    def _settings(
        self, data_dir: Path, session_manager_data_dir: Path | None = None
    ) -> Settings:
        return Settings(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=data_dir / "library",
            session_manager_data_dir=session_manager_data_dir,
        )

    def test_unconfigured_store_keeps_legacy_test_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data_dir = Path(raw)
            store = create_session_store(self._settings(data_dir))
        self.assertIsInstance(store, LegacySessionStore)

    def test_configured_store_uses_standalone_session_manager_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data_dir = Path(raw)
            session_dir = data_dir / "standalone-sessions"
            module = SimpleNamespace(SessionStore=FakeStandaloneStore)
            with patch(
                "education_resource_mcp.session_bridge.import_module",
                return_value=module,
            ) as imported:
                store = create_session_store(
                    self._settings(data_dir, session_manager_data_dir=session_dir)
                )
        imported.assert_called_once_with("session_manager.store")
        self.assertIsInstance(store, FakeStandaloneStore)
        self.assertEqual(store.data_dir, session_dir)

    @unittest.skipUnless(
        STANDALONE_SESSION_MANAGER_AVAILABLE,
        "openclaw-session-manager is required for the real bridge integration test",
    )
    def test_real_bridge_feeds_canonical_smartedu_token_to_adapter(self) -> None:
        from session_manager.store import SessionStore as StandaloneSessionStore

        with tempfile.TemporaryDirectory(
            prefix="education-session-bridge-", dir=Path.home()
        ) as raw:
            root = Path(raw)
            data_dir = root / "education"
            session_dir = root / "session-manager"
            secret = "synthetic-standalone-bridge-token"
            StandaloneSessionStore(session_dir).save(
                "smartedu",
                {"tokens": {"accessToken": secret}},
                idempotency_key="bridge-direct-import-save-01",
            )
            settings = self._settings(
                data_dir,
                session_manager_data_dir=session_dir,
            )
            bridged_store = create_session_store(settings)
            adapter = SmartEduSearchAdapter(bridged_store, settings)
            response = {
                "data": {
                    "list": [
                        {
                            "id": "bridge-resource-001",
                            "title": "分数的初步认识",
                            "description": "合成桥接测试",
                            "tab_code": "qualityCourse",
                            "search_resource_type": "course",
                            "resource_type": "elite_lesson",
                            "tags": [],
                        }
                    ]
                }
            }

            with patch.object(
                adapter,
                "_post_search",
                return_value=response,
            ) as post_search:
                results, error = adapter.search("分数的初步认识", 5)

        self.assertIsNone(error)
        self.assertGreaterEqual(len(results), 1)
        headers = post_search.call_args.args[2]
        self.assertEqual(headers["Authorization"], f"Bearer {secret}")
        self.assertEqual(headers["accessToken"], secret)

    def test_configured_store_never_silently_falls_back_when_dependency_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data_dir = Path(raw)
            with patch(
                "education_resource_mcp.session_bridge.import_module",
                side_effect=ImportError("not installed"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "openclaw-session-manager is not installed"
                ):
                    create_session_store(
                        self._settings(
                            data_dir,
                            session_manager_data_dir=data_dir / "standalone-sessions",
                        )
                    )

    def test_settings_reads_standalone_store_path_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data_dir = root / "education"
            session_dir = root / "sessions"
            with patch.dict(
                os.environ,
                {
                    "EDUCATION_RESOURCE_MCP_DATA_DIR": str(data_dir),
                    "EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR": str(
                        session_dir
                    ),
                },
                clear=False,
            ):
                settings = Settings.from_env()
        self.assertEqual(settings.session_manager_data_dir, session_dir)


if __name__ == "__main__":
    unittest.main()
