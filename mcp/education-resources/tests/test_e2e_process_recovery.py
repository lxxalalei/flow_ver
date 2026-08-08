"""Process-level restart and authentication recovery through public MCP tools."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest


from e2e_stdio_client import RawMcpClient


CONTRACT = {"contract_version": "1.0.0"}
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


def call_ok(client: RawMcpClient, name: str, arguments: dict) -> dict:
    result = client.call(name, {**CONTRACT, **arguments})
    if not result.get("ok"):
        raise AssertionError(f"{name} failed: {result!r}")
    return result


def begin_flow(client: RawMcpClient, key_prefix: str, topic: str = "恐龙") -> tuple[dict, dict]:
    flow = call_ok(
        client,
        "resource_flow_start",
        {
            "idempotency_key": f"{key_prefix}-flow-start-001",
            "task": {"goal": {"topic": topic}, "constraints": []},
        },
    )
    search = call_ok(
        client,
        "resource_search",
        {
            "flow_id": flow["flow_id"],
            "task_version": flow["task_version"],
            "idempotency_key": f"{key_prefix}-search-key-001",
            "search_tasks": [
                {"platform": "generic", "queries": [{"query": topic}]}
            ],
            "filters": {},
            "limit": 20,
        },
    )
    return flow, search


def select_titles(
    client: RawMcpClient,
    flow: dict,
    search: dict,
    titles: list[str],
    key_prefix: str,
) -> tuple[dict, dict]:
    candidates = {item["title"]: item["resource_id"] for item in search["candidates"]}
    presentation = call_ok(
        client,
        "resource_presentation_save",
        {
            "flow_id": flow["flow_id"],
            "result_set_id": search["result_set_id"],
            "displayed_resource_ids": [candidates[title] for title in titles],
            "idempotency_key": f"{key_prefix}-present-key-001",
        },
    )
    selection = call_ok(
        client,
        "resource_selection_save",
        {
            "flow_id": flow["flow_id"],
            "idempotency_key": f"{key_prefix}-select-key-001",
            "presentation_id": presentation["presentation_id"],
            "presented_version": presentation["presented_version"],
            "selected_positions": list(range(1, len(titles) + 1)),
        },
    )
    return presentation, selection


def prepare_and_start(
    client: RawMcpClient,
    flow: dict,
    presentation: dict,
    selection: dict,
    key_prefix: str,
    *,
    container: str,
) -> dict:
    binding = {
        "presentation_id": presentation["presentation_id"],
        "presented_version": presentation["presented_version"],
        "selection_version": selection["selection_version"],
        "selection_digest": selection["selection_digest"],
    }
    plan = call_ok(
        client,
        "resource_download_prepare",
        {
            "flow_id": flow["flow_id"],
            "idempotency_key": f"{key_prefix}-prepare-key-001",
            **binding,
            "options": {
                "preferred_container": container,
                "max_bytes_per_resource": 512 * 1024,
            },
        },
    )
    return call_ok(
        client,
        "resource_download_start",
        {
            "flow_id": flow["flow_id"],
            "plan_id": plan["plan_id"],
            **binding,
            "plan_digest": plan["plan_digest"],
            "confirmation_token": plan["confirmation_token"],
            "idempotency_key": f"{key_prefix}-start-key-0001",
        },
    )


def wait_job(client: RawMcpClient, flow_id: str, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = call_ok(
            client,
            "resource_job_status",
            {"flow_id": flow_id, "job_id": job_id},
        )
        if result["status"] in {"succeeded", "failed", "cancelled"}:
            return result
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal state")


class ProcessRecoveryE2ETests(unittest.TestCase):
    def test_abrupt_kill_recovers_failed_without_network_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            data_dir = Path(raw_dir)
            client = RawMcpClient(data_dir, mode="restart")
            client.start()
            try:
                self.assertEqual(EXPECTED_TOOLS, {tool["name"] for tool in client.list_tools()})
                flow, search = begin_flow(client, "restart-e2e", topic="重启")
                presentation, selection = select_titles(
                    client,
                    flow,
                    search,
                    ["重启前快速视频", "重启阻塞图书"],
                    "restart-e2e",
                )
                started = prepare_and_start(
                    client,
                    flow,
                    presentation,
                    selection,
                    "restart-e2e",
                    container="mp4",
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    running = call_ok(
                        client,
                        "resource_job_status",
                        {"flow_id": flow["flow_id"], "job_id": started["job_id"]},
                    )
                    if running["status"] == "running" and len(running["assets"]) == 1:
                        break
                    time.sleep(0.02)
                else:
                    self.fail("first resource was not persisted before the blocker")
                files_before = sorted(
                    path.relative_to(data_dir)
                    for path in (data_dir / "jobs").rglob("*")
                    if path.is_file()
                )
                self.assertEqual(1, len(files_before))
            finally:
                client.kill()

            with RawMcpClient(data_dir, mode="restart") as recovered:
                flow_status = call_ok(
                    recovered,
                    "resource_flow_status",
                    {"flow_id": flow["flow_id"]},
                )
                self.assertEqual("failed", flow_status["current_job"]["status"])
                self.assertEqual([], flow_status["current_job"]["asset_ids"])
                self.assertEqual(1, len(flow_status["current_job"]["bundle_ids"]))
                job = call_ok(
                    recovered,
                    "resource_job_status",
                    {"flow_id": flow["flow_id"], "job_id": started["job_id"]},
                )
                self.assertEqual("failed", job["status"])
                self.assertEqual([], job["assets"])
                self.assertEqual("INTERNAL_ERROR", job["failures"][0]["code"])
                time.sleep(0.1)
                files_after = sorted(
                    path.relative_to(data_dir)
                    for path in (data_dir / "jobs").rglob("*")
                    if path.is_file()
                )
                self.assertEqual(files_before, files_after)

    def test_auth_required_then_external_session_ready_uses_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            data_dir = Path(raw_dir)
            with RawMcpClient(data_dir, mode="standard") as client:
                flow, search = begin_flow(client, "auth-e2e")
                presentation, selection = select_titles(
                    client,
                    flow,
                    search,
                    ["授权恐龙课程"],
                    "auth-e2e",
                )
                first = prepare_and_start(
                    client,
                    flow,
                    presentation,
                    selection,
                    "auth-first-e2e",
                    container="mp4",
                )
                first_job = wait_job(client, flow["flow_id"], first["job_id"])
                self.assertEqual("failed", first_job["status"])
                self.assertEqual([], first_job["assets"])
                self.assertEqual("AUTH_REQUIRED", first_job["failures"][0]["code"])

                (data_dir / "fixture-auth-ready").touch()
                second = prepare_and_start(
                    client,
                    flow,
                    presentation,
                    selection,
                    "auth-second-e2e",
                    container="mp4",
                )
                self.assertNotEqual(first["job_id"], second["job_id"])
                second_job = wait_job(client, flow["flow_id"], second["job_id"])
                self.assertEqual("succeeded", second_job["status"])
                self.assertEqual("complete", second_job["completion"])
                self.assertEqual(1, len(second_job["assets"]))
                archived = call_ok(
                    client,
                    "resource_archive",
                    {
                        "flow_id": flow["flow_id"],
                        "job_id": second["job_id"],
                        "asset_id": second_job["assets"][0]["asset_id"],
                        "idempotency_key": "auth-e2e-archive-key-01",
                        "metadata": {"title": "授权课程", "tags": ["认证恢复"]},
                    },
                )
                library = call_ok(
                    client,
                    "resource_library_search",
                    {
                        "flow_id": flow["flow_id"],
                        "filters": {"query": "授权"},
                        "limit": 20,
                    },
                )
                self.assertEqual(archived["asset_id"], library["assets"][0]["asset_id"])


if __name__ == "__main__":
    unittest.main()
