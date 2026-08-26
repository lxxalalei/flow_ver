"""Process-boundary smoke test for the public stdio MCP surface."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
EXPECTED_TOOLS = {
    "resource_search",
    "resource_expand",
    "resource_import_url",
    "resource_inspect",
    "resource_download",
    "resource_job_status",
    "resource_job_cancel",
    "resource_job_read",
    "resource_html_design",
    "resource_archive",
    "resource_session_status",
    "resource_session_manage",
}


class McpStdioTests(unittest.TestCase):
    def test_initialize_and_list_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ)
            env.update({
                "PYTHONPATH": str(SRC),
                "EDUCATION_RESOURCE_MCP_DATA_DIR": str(root),
                "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(root / "library"),
            })
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
            initialize = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-test", "version": "1.0"},
                },
            }
            process.stdin.write(json.dumps(initialize) + "\n")
            process.stdin.flush()
            initialize_response = json.loads(process.stdout.readline())

            process.stdin.write(json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }) + "\n")
            process.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
            }) + "\n")
            process.stdin.flush()
            tools_response = json.loads(process.stdout.readline())
            process.stdin.close()
            return_code = process.wait(timeout=15)
            stderr = process.stderr.read()

        self.assertEqual(0, return_code, stderr)
        self.assertEqual(
            "education-resources",
            initialize_response["result"]["serverInfo"]["name"],
        )
        tools = tools_response["result"]["tools"]
        self.assertEqual(EXPECTED_TOOLS, {item["name"] for item in tools})

        search_tool = next(item for item in tools if item["name"] == "resource_search")
        search_schema = json.dumps(search_tool["inputSchema"], ensure_ascii=False)
        self.assertNotIn('"tabs"', search_schema)

        expand_tool = next(item for item in tools if item["name"] == "resource_expand")
        expand_properties = expand_tool["inputSchema"]["properties"]
        self.assertEqual({"resource_id", "source_url"}, set(expand_properties))

        design_tool = next(item for item in tools if item["name"] == "resource_html_design")
        design_schema = json.dumps(design_tool["inputSchema"], ensure_ascii=False)
        self.assertIn('"light_palette"', design_schema)
        self.assertIn('"dark_palette"', design_schema)
        self.assertNotIn('"custom_css"', design_schema)
        self.assertNotIn('"html"', design_schema.casefold())

        all_schema = json.dumps(tools, ensure_ascii=False)
        for removed in (
            "creator_full",
            "time_range_search",
            "catalog_expand",
            "collection_expand",
            "start_day",
            "end_day",
            '"specs"',
        ):
            self.assertNotIn(removed, all_schema)


if __name__ == "__main__":
    unittest.main()
