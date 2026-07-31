from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts" / "v1"


def contract_input_schema(tool_name: str) -> dict:
    path = (
        CONTRACTS_ROOT
        / "schemas"
        / "tools"
        / f"{tool_name}.schema.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    return document["$defs"]["input"]


@unittest.skipUnless(MCP_AVAILABLE, "install the service dependencies to run MCP stdio tests")
class McpStdioTests(unittest.TestCase):
    def test_initialize_list_and_call(self) -> None:
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        service_root = SERVICE_ROOT
        source_root = service_root / "src"
        expected_tools = {
            "resource_flow_start",
            "resource_search",
            "resource_selection_save",
            "resource_download_prepare",
            "resource_download_start",
            "resource_job_status",
            "resource_job_cancel",
            "resource_archive",
            "resource_library_search",
            "resource_session_status",
            "resource_session_save",
            "resource_session_delete",
        }

        async def run() -> None:
            with tempfile.TemporaryDirectory() as data_dir:
                environment = {
                    **os.environ,
                    "PYTHONPATH": str(source_root),
                    "EDUCATION_RESOURCE_MCP_DATA_DIR": data_dir,
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "education_resource_mcp.server"],
                    cwd=service_root,
                    env=environment,
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.server_info.name, "education-resources")
                        tools = await session.list_tools()
                        self.assertEqual({tool.name for tool in tools.tools}, expected_tools)
                        for tool in tools.tools:
                            expected_schema = contract_input_schema(tool.name)
                            with self.subTest(tool=tool.name):
                                self.assertEqual(
                                    set(tool.input_schema.get("required", [])),
                                    set(expected_schema.get("required", [])),
                                )
                                self.assertEqual(
                                    set(tool.input_schema.get("properties", {})),
                                    set(expected_schema.get("properties", {})),
                                )
                        result = await session.call_tool(
                            "resource_flow_start",
                            {
                                "contract_version": "1.0.0",
                                "idempotency_key": "stdio-contract-key-01",
                                "intent": {"topic": "恐龙", "audience": "primary"},
                            },
                        )
                        self.assertFalse(result.is_error)
                        self.assertTrue(result.structured_content["ok"])
                        self.assertTrue(
                            result.structured_content["flow_id"].startswith("flow_")
                        )

        anyio.run(run)


if __name__ == "__main__":
    unittest.main()
