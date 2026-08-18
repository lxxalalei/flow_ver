"""End-to-end MCP stdio initialize, discovery, and tool-call tests."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
SERVICE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SERVICE_ROOT / "src"
CONTRACTS_ROOT = SERVICE_ROOT / "contracts" / "v1"
EXPECTED_TOOLS = {
    "resource_session_status",
    "resource_session_login_guide",
    "resource_session_save",
    "resource_session_delete",
}


def _contract_input_schema(tool_name: str) -> dict[str, object]:
    path = (
        CONTRACTS_ROOT
        / "schemas"
        / "tools"
        / f"{tool_name}.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["$defs"]["input"]


@unittest.skipUnless(MCP_AVAILABLE, "install the service dependencies to run MCP stdio tests")
class McpStdioTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires native Windows path semantics")
    def test_native_windows_default_data_dir_uses_local_app_data(self) -> None:
        from session_manager.server import _data_dir

        with tempfile.TemporaryDirectory(
            prefix="session-manager-localappdata-", dir=Path.home()
        ) as temp_dir, patch.dict(
            os.environ, {"LOCALAPPDATA": str(Path(temp_dir) / "本地数据")}, clear=False
        ):
            os.environ.pop("SESSION_MANAGER_DATA_DIR", None)
            self.assertEqual(
                _data_dir(),
                Path(os.environ["LOCALAPPDATA"]) / "OpenClaw" / "session-manager",
            )

    def test_initialize_list_and_call_all_four_tools(self) -> None:
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def run() -> None:
            with tempfile.TemporaryDirectory(
                prefix="session-manager-stdio-", dir=Path.home()
            ) as temp_dir:
                data_dir = Path(temp_dir) / "session-data"
                environment = {
                    **os.environ,
                    "PYTHONPATH": str(SOURCE_ROOT),
                    "SESSION_MANAGER_DATA_DIR": str(data_dir),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "session_manager.server"],
                    cwd=SERVICE_ROOT,
                    env=environment,
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.server_info.name, "session-manager")
                        self.assertEqual(initialized.server_info.version, "0.4.1")
                        self.assertIn(
                            "explicitly names the supported platform",
                            initialized.instructions or "",
                        )
                        self.assertIn(
                            "resource_session_save",
                            initialized.instructions or "",
                        )

                        listed = await session.list_tools()
                        self.assertEqual(
                            {tool.name for tool in listed.tools}, EXPECTED_TOOLS
                        )
                        for tool in listed.tools:
                            expected = _contract_input_schema(tool.name)
                            with self.subTest(tool=tool.name):
                                self.assertEqual(
                                    set(tool.input_schema.get("required", [])),
                                    set(expected.get("required", [])),
                                )
                                self.assertEqual(
                                    set(tool.input_schema.get("properties", {})),
                                    set(expected.get("properties", {})),
                                )

                        guide = await session.call_tool(
                            "resource_session_login_guide",
                            {"contract_version": "1.0.0", "platform": "bilibili"},
                        )
                        self.assertFalse(guide.is_error)
                        self.assertTrue(guide.structured_content["ok"])
                        self.assertEqual(
                            guide.structured_content["capture_method"],
                            "browser_cookies",
                        )

                        cookie_secret = "stdio-cookie-must-not-leak"
                        saved = await session.call_tool(
                            "resource_session_save",
                            {
                                "contract_version": "1.0.0",
                                "platform": "bilibili",
                                "session_data": {
                                    "cookies": [
                                        {
                                            "name": "SESSDATA",
                                            "value": cookie_secret,
                                            "domain": ".bilibili.com",
                                            "path": "/",
                                            "httpOnly": True,
                                            "secure": True,
                                            "partitionKey": {
                                                "topLevelSite": "https://www.bilibili.com",
                                                "hasCrossSiteAncestor": False,
                                            },
                                        }
                                    ]
                                },
                                "idempotency_key": "stdio-save-key-01",
                            },
                        )
                        self.assertFalse(saved.is_error)
                        self.assertTrue(saved.structured_content["ok"])
                        self.assertEqual(saved.structured_content["status"], "stored")
                        self.assertRegex(
                            saved.structured_content["session_revision"],
                            r"^[0-9a-f]{32}$",
                        )
                        self.assertEqual(
                            saved.structured_content["stored_credential_count"], 1
                        )
                        self.assertNotIn(
                            cookie_secret,
                            json.dumps(saved.structured_content, ensure_ascii=False),
                        )

                        status = await session.call_tool(
                            "resource_session_status",
                            {
                                "contract_version": "1.0.0",
                                "platforms": ["bilibili"],
                                "deep": False,
                            },
                        )
                        self.assertFalse(status.is_error)
                        self.assertTrue(status.structured_content["ok"])
                        self.assertEqual(
                            status.structured_content["sessions"][0]["status"],
                            "stored",
                        )
                        self.assertNotIn(
                            cookie_secret,
                            json.dumps(status.structured_content, ensure_ascii=False),
                        )

                        smartedu_guide = await session.call_tool(
                            "resource_session_login_guide",
                            {"contract_version": "1.0.0", "platform": "smartedu"},
                        )
                        self.assertFalse(smartedu_guide.is_error)
                        self.assertTrue(smartedu_guide.structured_content["ok"])
                        self.assertEqual(
                            smartedu_guide.structured_content["capture_method"],
                            "browser_storage",
                        )
                        self.assertIn(
                            "ND_UC_AUTH-*&ncet-xedu&token",
                            smartedu_guide.structured_content["storage_key_patterns"],
                        )

                        storage_secret = "stdio-smartedu-token-must-not-leak"
                        storage_noise = "stdio-storage-noise-must-not-leak"
                        cookie_noise = "stdio-cookie-noise-must-not-leak"
                        smartedu_saved = await session.call_tool(
                            "resource_session_save",
                            {
                                "contract_version": "1.0.0",
                                "platform": "smartedu",
                                "session_data": {
                                    "cookies": [
                                        {
                                            "name": "unrelated",
                                            "value": cookie_noise,
                                            "domain": ".example.com",
                                            "path": "/",
                                        }
                                    ],
                                    "storage_origin": "https://basic.smartedu.cn",
                                    "local_storage": {
                                        "ND_UC_AUTH-stdio-id&ncet-xedu&token": json.dumps(
                                            {
                                                "profile": {
                                                    "credential": {
                                                        "access_token": storage_secret
                                                    }
                                                }
                                            }
                                        ),
                                        "unrelated": storage_noise,
                                    },
                                    "session_storage": {"temporary": storage_noise},
                                },
                                "idempotency_key": "stdio-smartedu-save-01",
                            },
                        )
                        self.assertFalse(smartedu_saved.is_error)
                        self.assertTrue(smartedu_saved.structured_content["ok"])
                        self.assertEqual(
                            smartedu_saved.structured_content["status"], "stored"
                        )
                        self.assertEqual(
                            smartedu_saved.structured_content["auth_kind"], "token"
                        )
                        self.assertEqual(
                            smartedu_saved.structured_content["stored_credential_count"],
                            1,
                        )
                        self.assertGreaterEqual(
                            smartedu_saved.structured_content[
                                "discarded_credential_count"
                            ],
                            3,
                        )
                        serialized_smartedu = json.dumps(
                            smartedu_saved.model_dump(mode="json"), ensure_ascii=False
                        )
                        for secret in (storage_secret, storage_noise, cookie_noise):
                            self.assertNotIn(secret, serialized_smartedu)
                        self.assertNotIn("session_data", serialized_smartedu)
                        self.assertNotIn("local_storage", serialized_smartedu)

                        direct_secret = "stdio-smartedu-direct-token-must-not-leak"
                        direct_saved = await session.call_tool(
                            "resource_session_save",
                            {
                                "contract_version": "1.0.0",
                                "platform": "smartedu",
                                "session_data": {
                                    "tokens": {"accessToken": direct_secret}
                                },
                                "idempotency_key": "stdio-smartedu-direct-save-01",
                            },
                        )
                        self.assertFalse(direct_saved.is_error)
                        self.assertTrue(direct_saved.structured_content["ok"])
                        self.assertEqual(
                            direct_saved.structured_content["status"], "stored"
                        )
                        self.assertEqual(
                            direct_saved.structured_content["stored_credential_count"],
                            1,
                        )
                        self.assertNotIn(
                            direct_secret,
                            json.dumps(
                                direct_saved.model_dump(mode="json"),
                                ensure_ascii=False,
                            ),
                        )

                        invalid_secret_marker = (
                            "stdio-invalid-direct-token-must-not-leak"
                        )
                        invalid_saved = await session.call_tool(
                            "resource_session_save",
                            {
                                "contract_version": "1.0.0",
                                "platform": "smartedu",
                                "session_data": {
                                    "tokens": {
                                        "accessToken": invalid_secret_marker + "\x00"
                                    }
                                },
                                "idempotency_key": "stdio-smartedu-invalid-save-01",
                            },
                        )
                        self.assertFalse(invalid_saved.is_error)
                        self.assertFalse(invalid_saved.structured_content["ok"])
                        self.assertEqual(
                            invalid_saved.structured_content["error"]["code"],
                            "SESSION_PAYLOAD_INVALID",
                        )
                        self.assertNotIn(
                            invalid_secret_marker,
                            json.dumps(
                                invalid_saved.model_dump(mode="json"),
                                ensure_ascii=False,
                            ),
                        )

                        direct_status = await session.call_tool(
                            "resource_session_status",
                            {
                                "contract_version": "1.0.0",
                                "platforms": ["smartedu"],
                                "deep": False,
                            },
                        )
                        self.assertFalse(direct_status.is_error)
                        self.assertEqual(
                            direct_status.structured_content["sessions"][0]["status"],
                            "stored",
                        )
                        self.assertNotIn(
                            direct_secret,
                            json.dumps(
                                direct_status.model_dump(mode="json"),
                                ensure_ascii=False,
                            ),
                        )

                        smartedu_deleted = await session.call_tool(
                            "resource_session_delete",
                            {
                                "contract_version": "1.0.0",
                                "platform": "smartedu",
                                "idempotency_key": "stdio-smartedu-delete-01",
                            },
                        )
                        self.assertFalse(smartedu_deleted.is_error)
                        self.assertTrue(smartedu_deleted.structured_content["deleted"])

                        deleted = await session.call_tool(
                            "resource_session_delete",
                            {
                                "contract_version": "1.0.0",
                                "platform": "bilibili",
                                "idempotency_key": "stdio-delete-key-01",
                            },
                        )
                        self.assertFalse(deleted.is_error)
                        self.assertTrue(deleted.structured_content["ok"])
                        self.assertTrue(deleted.structured_content["deleted"])

                        missing = await session.call_tool(
                            "resource_session_status",
                            {
                                "contract_version": "1.0.0",
                                "platforms": ["bilibili"],
                            },
                        )
                        self.assertEqual(
                            missing.structured_content["sessions"][0]["status"],
                            "missing",
                        )

        anyio.run(run)


if __name__ == "__main__":
    unittest.main()
