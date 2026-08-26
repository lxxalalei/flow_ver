"""Public Session Tool contract should not teach the Agent credential internals."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.sessions import PLATFORM_REGISTRY, SessionStore
from education_resource_mcp.errors import DomainError
from education_resource_mcp.server import _session_manage, _session_status


def _list_tools() -> list[dict]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        env = dict(os.environ)
        env.update(
            {
                "PYTHONPATH": str(SRC),
                "EDUCATION_RESOURCE_MCP_DATA_DIR": str(root),
                "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(root / "library"),
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "education_resource_mcp.server"],
            cwd=SERVICE_ROOT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "schema-test", "version": "1.0"},
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        json.loads(process.stdout.readline())
        process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            )
            + "\n"
        )
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            + "\n"
        )
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        process.stdin.close()
        return_code = process.wait(timeout=15)
        stderr = process.stderr.read()
        if return_code != 0:
            raise AssertionError(stderr)
        return response["result"]["tools"]


class SessionPublicContractTests(unittest.TestCase):
    def test_session_manage_exposes_action_and_one_opaque_capture_object(self) -> None:
        tool = next(item for item in _list_tools() if item["name"] == "resource_session_manage")
        schema = tool["inputSchema"]
        properties = schema["properties"]

        self.assertEqual(["save", "delete"], properties["action"]["enum"])
        self.assertIn("capture", properties)
        self.assertNotIn("session_data", properties)
        capture_schema = properties["capture"]
        capture_text = json.dumps(capture_schema, ensure_ascii=False)
        self.assertIn("object", capture_text)
        for internal_name in ("cookies", "local_storage", "session_storage", "tokens"):
            self.assertNotIn(internal_name, capture_text)

    def test_status_includes_login_steps_when_session_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            result = _session_status(
                SimpleNamespace(session_store=store),
                ["smartedu"],
                False,
            )
        self.assertEqual(1, len(result["needs_login"]))
        guide = result["needs_login"][0]
        self.assertTrue(guide["steps"])
        self.assertEqual("resource_session_manage", guide["steps"][-1]["action"])

    def test_full_status_does_not_repeat_login_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            result = _session_status(
                SimpleNamespace(session_store=store),
                None,
                False,
            )
        self.assertTrue(result["needs_login"])
        self.assertTrue(all("steps" not in item for item in result["needs_login"]))

    def test_manage_save_and_delete_have_explicit_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            service = SimpleNamespace(session_store=store)
            saved = _session_manage(
                service,
                "save",
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {"accessToken": "TOKEN"},
                },
                None,
            )
            self.assertEqual("stored", saved["status"])
            deleted = _session_manage(service, "delete", "smartedu", None, None)
            self.assertTrue(deleted["deleted"])
            with self.assertRaises(DomainError):
                _session_manage(service, "save", "smartedu", None, None)
            with self.assertRaises(DomainError):
                _session_manage(service, "delete", "smartedu", {}, None)

    def test_public_session_metadata_hides_platform_credential_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            guide = store.login_guide("smartedu")
        self.assertNotIn("cookie_domains", guide)
        self.assertNotIn("storage_keys", guide)

        config = PLATFORM_REGISTRY["smartedu"]
        self.assertEqual(("accessToken",), config.required_storage_keys)
        self.assertIn("accessToken", config.storage_keys)


if __name__ == "__main__":
    unittest.main()
