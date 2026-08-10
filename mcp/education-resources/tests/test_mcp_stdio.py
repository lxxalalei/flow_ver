from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from e2e_stdio_client import build_fixture_subprocess_environment


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
EXPECTED_TOOLS = {
    "resource_flow_start",
    "resource_flow_status",
    "resource_search",
    "resource_browse_creator",
    "resource_inspect",
    "resource_presentation_save",
    "resource_selection_save",
    "resource_download_prepare",
    "resource_download_start",
    "resource_job_status",
    "resource_job_cancel",
    "resource_archive",
    "resource_library_search",
}
BINDING_FIELDS = (
    "presentation_id",
    "presented_version",
    "selection_version",
    "selection_digest",
)


def contract_input_schema(tool_name: str) -> dict:
    path = CONTRACTS_ROOT / "schemas" / "tools" / f"{tool_name}.schema.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return document["$defs"]["input"]


def stdio_parameters(data_dir: str):
    from mcp.client.stdio import StdioServerParameters

    return StdioServerParameters(
        command=sys.executable,
        args=[str(SERVICE_ROOT / "tests" / "stdio_fixture_server.py")],
        cwd=SERVICE_ROOT,
        env=build_fixture_subprocess_environment(data_dir),
    )


@unittest.skipUnless(MCP_AVAILABLE, "install the service dependencies to run MCP stdio tests")
class McpStdioTests(unittest.TestCase):
    def test_initialize_lists_exact_13_tools_and_input_schemas(self) -> None:
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async def run() -> None:
            with tempfile.TemporaryDirectory() as data_dir:
                async with stdio_client(stdio_parameters(data_dir)) as (
                    read_stream,
                    write_stream,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        initialized = await session.initialize()
                        self.assertEqual(
                            initialized.server_info.name, "education-resources"
                        )
                        self.assertEqual(initialized.server_info.version, "0.2.0")
                        tools = await session.list_tools()
                        actual_tools = {tool.name for tool in tools.tools}
                        self.assertEqual(actual_tools, EXPECTED_TOOLS)
                        self.assertEqual(len(tools.tools), len(EXPECTED_TOOLS))
                        for tool in tools.tools:
                            expected_schema = contract_input_schema(tool.name)
                            with self.subTest(tool=tool.name, part="required"):
                                self.assertEqual(
                                    set(tool.input_schema.get("required", [])),
                                    set(expected_schema.get("required", [])),
                                )
                            with self.subTest(tool=tool.name, part="properties"):
                                self.assertEqual(
                                    set(tool.input_schema.get("properties", {})),
                                    set(expected_schema.get("properties", {})),
                                )

                        search_schema = next(
                            tool.input_schema
                            for tool in tools.tools
                            if tool.name == "resource_search"
                        )
                        self.assertIn("task_version", search_schema["required"])
                        self.assertIn("filters", search_schema["properties"])

        anyio.run(run)

    def test_deterministic_fixture_full_round_trip(self) -> None:
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async def call(session, name: str, arguments: dict) -> dict:
            result = await session.call_tool(name, arguments)
            self.assertFalse(result.is_error, name)
            self.assertIsNotNone(result.structured_content, name)
            content = result.structured_content
            self.assertEqual(content["contract_version"], "1.0.0", name)
            self.assertTrue(content["ok"], content)
            return content

        async def run() -> None:
            with tempfile.TemporaryDirectory() as data_dir:
                async with stdio_client(stdio_parameters(data_dir)) as (
                    read_stream,
                    write_stream,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        flow = await call(
                            session,
                            "resource_flow_start",
                            {
                                "contract_version": "1.0.0",
                                "idempotency_key": "stdio-flow-key-01",
                                "task": {
                                    "goal": {
                                        "topic": "恐龙",
                                        "outcome": "找到入门资料",
                                    },
                                    "user_role": "parent",
                                    "resource_target": "child",
                                    "constraints": [],
                                },
                            },
                        )
                        search = await call(
                            session,
                            "resource_search",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "task_version": flow["task_version"],
                                "idempotency_key": "stdio-search-key-1",
                                "search_tasks": [
                                    {
                                        "platform": "generic",
                                        "queries": [{"query": "恐龙"}],
                                    }
                                ],
                                "filters": {
                                    "resource_types": ["article"],
                                    "languages": ["zh-CN"],
                                },
                                "limit": 10,
                            },
                        )
                        displayed = [
                            search["candidates"][1]["resource_id"],
                            search["candidates"][0]["resource_id"],
                        ]
                        for index, resource_id in enumerate(displayed, start=1):
                            inspected = await call(
                                session,
                                "resource_inspect",
                                {
                                    "contract_version": "1.0.0",
                                    "flow_id": flow["flow_id"],
                                    "resource_id": resource_id,
                                    "idempotency_key": f"stdio-inspect-key-{index}",
                                },
                            )
                            self.assertEqual("resolved", inspected["resolution_status"])
                            self.assertEqual(
                                "landing_page",
                                inspected["resolved_resource"]["representations"][0]["scope"],
                            )
                        presentation = await call(
                            session,
                            "resource_presentation_save",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "result_set_id": search["result_set_id"],
                                "displayed_resource_ids": displayed,
                                "idempotency_key": "stdio-present-key-1",
                            },
                        )
                        self.assertFalse(presentation["empty"])
                        self.assertEqual(
                            [item["resource_id"] for item in presentation["items"]],
                            displayed,
                        )
                        selection = await call(
                            session,
                            "resource_selection_save",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "idempotency_key": "stdio-select-key-01",
                                "presentation_id": presentation["presentation_id"],
                                "presented_version": presentation["presented_version"],
                                "selected_positions": [1],
                            },
                        )
                        binding = {
                            "presentation_id": presentation["presentation_id"],
                            "presented_version": presentation["presented_version"],
                            "selection_version": selection["selection_version"],
                            "selection_digest": selection["selection_digest"],
                        }
                        plan = await call(
                            session,
                            "resource_download_prepare",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "idempotency_key": "stdio-prepare-key-1",
                                **binding,
                                "options": {"preferred_container": "html"},
                            },
                        )
                        self.assertTrue(plan["plan_digest"])
                        self.assertEqual(
                            {field: plan[field] for field in BINDING_FIELDS}, binding
                        )

                        recovered = await call(
                            session,
                            "resource_flow_status",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                            },
                        )
                        self.assertTrue(
                            {
                                "current_result_set",
                                "current_presentation",
                                "current_selection",
                                "current_plan",
                                "current_job",
                            }.issubset(recovered)
                        )
                        self.assertTrue(
                            {"latest_result_set", "active_plan", "latest_job"}.isdisjoint(
                                recovered
                            )
                        )
                        self.assertEqual(
                            [
                                item["resource_id"]
                                for item in recovered["current_presentation"]["items"]
                            ],
                            displayed,
                        )
                        self.assertNotIn(
                            "confirmation_token", recovered["current_plan"]
                        )

                        started = await call(
                            session,
                            "resource_download_start",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "plan_id": plan["plan_id"],
                                **binding,
                                "plan_digest": plan["plan_digest"],
                                "authority_digest": plan["authority_digest"],
                                "confirmation_token": plan["confirmation_token"],
                                "idempotency_key": "stdio-start-key-001",
                            },
                        )
                        self.assertEqual(
                            {field: started[field] for field in BINDING_FIELDS}, binding
                        )
                        self.assertEqual(started["plan_digest"], plan["plan_digest"])
                        self.assertEqual(
                            started["authority_digest"], plan["authority_digest"]
                        )

                        deadline = time.monotonic() + 3
                        while True:
                            job = await call(
                                session,
                                "resource_job_status",
                                {
                                    "contract_version": "1.0.0",
                                    "flow_id": flow["flow_id"],
                                    "job_id": started["job_id"],
                                },
                            )
                            if job["status"] in {"succeeded", "failed", "cancelled"}:
                                break
                            if time.monotonic() >= deadline:
                                self.fail("stdio job timeout")
                            await anyio.sleep(0.01)
                        self.assertEqual(job["status"], "succeeded")
                        self.assertEqual(job["plan_id"], plan["plan_id"])
                        self.assertEqual(
                            {field: job[field] for field in BINDING_FIELDS}, binding
                        )
                        self.assertEqual(job["plan_digest"], plan["plan_digest"])

                        recovered = await call(
                            session,
                            "resource_flow_status",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                            },
                        )
                        self.assertEqual(
                            recovered["current_job"]["job_id"], started["job_id"]
                        )

                        archived = await call(
                            session,
                            "resource_archive",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "job_id": started["job_id"],
                                "asset_id": job["assets"][0]["asset_id"],
                                "idempotency_key": "stdio-archive-key-01",
                                "metadata": {
                                    "title": "恐龙入门资料",
                                    "collection": "科学",
                                    "tags": ["恐龙"],
                                },
                            },
                        )
                        library = await call(
                            session,
                            "resource_library_search",
                            {
                                "contract_version": "1.0.0",
                                "flow_id": flow["flow_id"],
                                "filters": {"query": "恐龙"},
                                "limit": 20,
                            },
                        )
                        self.assertEqual(archived["asset_id"], library["assets"][0]["asset_id"])

        anyio.run(run)


if __name__ == "__main__":
    unittest.main()
