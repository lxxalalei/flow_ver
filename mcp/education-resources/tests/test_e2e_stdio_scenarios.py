"""Complete offline business scenarios over a real MCP stdio subprocess."""


from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest


from e2e_stdio_client import RawMcpClient
from test_e2e_process_recovery import (
    CONTRACT,
    EXPECTED_TOOLS,
    begin_flow,
    call_ok,
    inspect_titles,
    prepare_and_start,
    select_titles,
    wait_job,
)


class StdioScenarioE2ETests(unittest.TestCase):
    def test_new_presentation_invalidates_selection_and_prepared_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with RawMcpClient(Path(raw_dir), mode="standard") as client:
                flow, search = begin_flow(client, "invalidate-e2e")
                title = "恐龙视频课"
                inspected = inspect_titles(
                    client, flow, search, [title], "invalidate-e2e"
                )
                self.assertEqual("resolved", inspected[0]["resolution_status"])
                presentation, selection = select_titles(
                    client, flow, search, [title], "invalidate-e2e"
                )
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
                        "idempotency_key": "invalidate-e2e-prepare-key-001",
                        **binding,
                        "options": {
                            "preferred_container": "mp4",
                        },
                    },
                )

                article = next(
                    item
                    for item in search["candidates"]
                    if item["title"] == "恐龙网页图文"
                )
                replacement = call_ok(
                    client,
                    "resource_presentation_save",
                    {
                        "flow_id": flow["flow_id"],
                        "result_set_id": search["result_set_id"],
                        "displayed_resource_ids": [article["resource_id"]],
                        "idempotency_key": "invalidate-e2e-present-key-002",
                    },
                )
                self.assertGreater(
                    replacement["presented_version"], presentation["presented_version"]
                )

                stale_selection = client.call(
                    "resource_selection_save",
                    {
                        **CONTRACT,
                        "flow_id": flow["flow_id"],
                        "idempotency_key": "invalidate-e2e-select-key-002",
                        "presentation_id": presentation["presentation_id"],
                        "presented_version": presentation["presented_version"],
                        "selected_positions": [1],
                    },
                )
                self.assertFalse(stale_selection["ok"])
                self.assertEqual(
                    "PRESENTATION_VERSION_CONFLICT", stale_selection["error"]["code"]
                )

                status = call_ok(
                    client,
                    "resource_flow_status",
                    {"flow_id": flow["flow_id"]},
                )
                self.assertIsNone(status["current_selection"])
                self.assertEqual("invalidated", status["current_plan"]["status"])
                self.assertIsNone(status["current_job"])

                stale_start = client.call(
                    "resource_download_start",
                    {
                        **CONTRACT,
                        "flow_id": flow["flow_id"],
                        "plan_id": plan["plan_id"],
                        "confirmation_token": plan["confirmation_token"],
                        "idempotency_key": "invalidate-e2e-start-key-001",
                    },
                )
                self.assertFalse(stale_start["ok"])
                self.assertEqual(
                    "SELECTION_VERSION_CONFLICT", stale_start["error"]["code"]
                )
                after_rejection = call_ok(
                    client,
                    "resource_flow_status",
                    {"flow_id": flow["flow_id"]},
                )
                self.assertIsNone(after_rejection["current_job"])

    def test_policy_blocked_inspection_cannot_create_plan_or_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with RawMcpClient(Path(raw_dir), mode="standard") as client:
                flow, search = begin_flow(client, "policy-e2e")
                title = "策略阻止恐龙百科"
                inspected = inspect_titles(client, flow, search, [title], "policy-e2e")
                self.assertEqual(
                    "policy_blocked",
                    inspected[0]["resolved_resource"]["availability"]["status"],
                )
                presentation, selection = select_titles(
                    client, flow, search, [title], "policy-e2e"
                )
                rejected = client.call(
                    "resource_download_prepare",
                    {
                        **CONTRACT,
                        "flow_id": flow["flow_id"],
                        "idempotency_key": "policy-e2e-prepare-key-001",
                        "presentation_id": presentation["presentation_id"],
                        "presented_version": presentation["presented_version"],
                        "selection_version": selection["selection_version"],
                        "selection_digest": selection["selection_digest"],
                        "options": {
                            "preferred_container": "pdf",
                        },
                    },
                )
                self.assertFalse(rejected["ok"])
                self.assertEqual("POLICY_DENIED", rejected["error"]["code"])
                self.assertFalse(rejected["error"]["retriable"])
                status = call_ok(
                    client,
                    "resource_flow_status",
                    {"flow_id": flow["flow_id"]},
                )
                self.assertIsNone(status["current_plan"])
                self.assertIsNone(status["current_job"])

    def test_running_job_can_be_cancelled_without_archivable_assets(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with RawMcpClient(Path(raw_dir), mode="restart") as client:
                flow, search = begin_flow(client, "cancel-e2e", topic="重启")
                title = "重启阻塞图书"
                inspect_titles(client, flow, search, [title], "cancel-e2e")
                presentation, selection = select_titles(
                    client, flow, search, [title], "cancel-e2e"
                )
                started = prepare_and_start(
                    client,
                    flow,
                    presentation,
                    selection,
                    "cancel-e2e",
                    container="pdf",
                )

                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    running = call_ok(
                        client,
                        "resource_job_status",
                        {"flow_id": flow["flow_id"], "job_id": started["job_id"]},
                    )
                    if running["status"] == "running":
                        break
                    time.sleep(0.02)
                else:
                    self.fail("blocking fixture job did not enter running state")

                cancelled = call_ok(
                    client,
                    "resource_job_cancel",
                    {
                        "flow_id": flow["flow_id"],
                        "job_id": started["job_id"],
                        "idempotency_key": "cancel-e2e-job-key-001",
                        "reason": "用户取消隔离夹具任务",
                    },
                )
                self.assertIn(cancelled["status"], {"cancelling", "cancelled"})
                terminal = wait_job(client, flow["flow_id"], started["job_id"])
                self.assertEqual("cancelled", terminal["status"])
                self.assertEqual([], terminal["assets"])
                status = call_ok(
                    client,
                    "resource_flow_status",
                    {"flow_id": flow["flow_id"]},
                )
                self.assertEqual("cancelled", status["current_job"]["status"])
                self.assertEqual([], status["current_job"]["asset_ids"])
                self.assertNotIn("resource_archive", status["allowed_next_actions"])

    def test_cross_flow_archive_is_rejected_before_valid_origin_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with RawMcpClient(Path(raw_dir), mode="standard") as client:
                source_flow, source_search = begin_flow(client, "archive-source-e2e")
                title = "恐龙视频课"
                inspect_titles(
                    client,
                    source_flow,
                    source_search,
                    [title],
                    "archive-source-e2e",
                )
                presentation, selection = select_titles(
                    client,
                    source_flow,
                    source_search,
                    [title],
                    "archive-source-e2e",
                )
                started = prepare_and_start(
                    client,
                    source_flow,
                    presentation,
                    selection,
                    "archive-source-e2e",
                    container="mp4",
                )
                job = wait_job(client, source_flow["flow_id"], started["job_id"])
                self.assertEqual("succeeded", job["status"])
                asset = job["assets"][0]

                foreign_flow, _ = begin_flow(client, "archive-foreign-e2e")
                rejected = client.call(
                    "resource_archive",
                    {
                        **CONTRACT,
                        "flow_id": foreign_flow["flow_id"],
                        "job_id": started["job_id"],
                        "asset_id": asset["asset_id"],
                        "idempotency_key": "archive-foreign-e2e-key-001",
                        "metadata": {"title": "越权归档", "tags": ["拒绝"]},
                    },
                )
                self.assertFalse(rejected["ok"])
                self.assertEqual("ASSET_NOT_FOUND", rejected["error"]["code"])

                archived = call_ok(
                    client,
                    "resource_archive",
                    {
                        "flow_id": source_flow["flow_id"],
                        "job_id": started["job_id"],
                        "asset_id": asset["asset_id"],
                        "idempotency_key": "archive-source-e2e-key-001",
                        "metadata": {"title": "合法归档", "tags": ["恐龙"]},
                    },
                )
                self.assertEqual(asset["asset_id"], archived["asset_id"])

    def test_multi_resource_inspect_partial_bundle_archive_and_library(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with RawMcpClient(Path(raw_dir), mode="standard") as client:
                self.assertEqual(EXPECTED_TOOLS, {tool["name"] for tool in client.list_tools()})
                flow, search = begin_flow(client, "multi-e2e")
                by_title = {item["title"]: item for item in search["candidates"]}
                titles = ["恐龙视频课", "恐龙百科 2024 版", "恐龙综合课程"]
                inspections = {}
                for index, title in enumerate(titles, 1):
                    inspections[title] = call_ok(
                        client,
                        "resource_inspect",
                        {
                            "flow_id": flow["flow_id"],
                            "resource_id": by_title[title]["resource_id"],
                            "idempotency_key": f"multi-e2e-inspect-key-{index:02d}",
                        },
                    )
                book = inspections["恐龙百科 2024 版"]["resolved_resource"]
                self.assertEqual("2024", book["metadata"]["edition"])
                self.assertTrue(
                    any(
                        item["kind"] == "document"
                        and item["container"] == "pdf"
                        and item["role"] == "primary"
                        for item in book["representations"]
                    )
                )

                presentation, selection = select_titles(
                    client, flow, search, titles, "multi-e2e"
                )
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
                        "idempotency_key": "multi-e2e-prepare-key-01",
                        **binding,
                        "options": {
                            "preferred_container": "mp4",
                        },
                    },
                )

                wrong = client.call(
                    "resource_download_start",
                    {
                        **CONTRACT,
                        "flow_id": flow["flow_id"],
                        "plan_id": plan["plan_id"],
                        "confirmation_token": "wrong-token",
                        "idempotency_key": "multi-e2e-wrong-start-1",
                    },
                )
                self.assertFalse(wrong["ok"])
                self.assertEqual("CONFIRMATION_INVALID", wrong["error"]["code"])
                before_start = call_ok(
                    client,
                    "resource_flow_status",
                    {"flow_id": flow["flow_id"]},
                )
                self.assertIsNone(before_start["current_job"])

                started = call_ok(
                    client,
                    "resource_download_start",
                    {
                        "flow_id": flow["flow_id"],
                        "plan_id": plan["plan_id"],
                        "confirmation_token": plan["confirmation_token"],
                        "idempotency_key": "multi-e2e-start-key-001",
                    },
                )
                self.assertEqual(started["plan_digest"], plan["plan_digest"])
                job = wait_job(client, flow["flow_id"], started["job_id"])
                self.assertEqual("succeeded", job["status"])
                self.assertEqual("partial", job["completion"])
                self.assertEqual(3, job["progress"]["completed_items"])
                self.assertEqual(3, job["progress"]["total_items"])
                self.assertEqual(5, len(job["assets"]))
                self.assertEqual(3, len({item["bundle_id"] for item in job["assets"]}))
                self.assertEqual("transcript", job["failures"][0]["role"])
                self.assertEqual("DOWNLOAD_FAILED", job["failures"][0]["code"])
                for bundle_id in {item["bundle_id"] for item in job["assets"]}:
                    members = [item for item in job["assets"] if item["bundle_id"] == bundle_id]
                    self.assertEqual(1, sum(item["role"] == "primary" for item in members))
                    self.assertEqual(
                        list(range(1, len(members) + 1)),
                        [item["order"] for item in members],
                    )

                for index, asset in enumerate(job["assets"], 1):
                    archived = call_ok(
                        client,
                        "resource_archive",
                        {
                            "flow_id": flow["flow_id"],
                            "job_id": started["job_id"],
                            "asset_id": asset["asset_id"],
                            "idempotency_key": f"multi-e2e-archive-key-{index:02d}",
                            "metadata": {"title": "恐龙 E2E", "tags": ["恐龙"]},
                        },
                    )
                    self.assertEqual(asset["bundle_id"], archived["bundle_id"])
                    self.assertEqual(asset["role"], archived["role"])
                library = call_ok(
                    client,
                    "resource_library_search",
                    {
                        "flow_id": flow["flow_id"],
                        "filters": {"query": "恐龙"},
                        "limit": 20,
                    },
                )
                self.assertEqual(5, len(library["assets"]))
                self.assertTrue(
                    all(item.get("bundle_id") and item.get("role") for item in library["assets"])
                )

                conflict = client.call(
                    "resource_search",
                    {
                        **CONTRACT,
                        "flow_id": flow["flow_id"],
                        "task_version": flow["task_version"],
                        "idempotency_key": "multi-e2e-search-key-001",
                        "search_tasks": [
                            {"platform": "generic", "queries": [{"query": "不同查询"}]}
                        ],
                        "filters": {},
                        "limit": 20,
                    },
                )
                self.assertFalse(conflict["ok"])
                self.assertEqual("IDEMPOTENCY_CONFLICT", conflict["error"]["code"])

    def test_article_materializes_zip_and_archives_portably(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with RawMcpClient(Path(raw_dir), mode="standard") as client:
                flow, search = begin_flow(client, "web-e2e")
                article = next(
                    item for item in search["candidates"] if item["title"] == "恐龙网页图文"
                )
                inspected = call_ok(
                    client,
                    "resource_inspect",
                    {
                        "flow_id": flow["flow_id"],
                        "resource_id": article["resource_id"],
                        "idempotency_key": "web-e2e-inspect-key-01",
                    },
                )
                self.assertEqual(
                    "webpage",
                    inspected["resolved_resource"]["representations"][0]["kind"],
                )
                presentation, selection = select_titles(
                    client, flow, search, ["恐龙网页图文"], "web-e2e"
                )
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
                        "idempotency_key": "web-e2e-prepare-key-001",
                        **binding,
                        "options": {
                            "preferred_container": "html",
                        },
                    },
                )
                started = call_ok(
                    client,
                    "resource_download_start",
                    {
                        "flow_id": flow["flow_id"],
                        "plan_id": plan["plan_id"],
                        "confirmation_token": plan["confirmation_token"],
                        "idempotency_key": "web-e2e-start-key-0001",
                    },
                )
                self.assertEqual(started["plan_digest"], plan["plan_digest"])
                job = wait_job(client, flow["flow_id"], started["job_id"])
                self.assertEqual("succeeded", job["status"])
                self.assertEqual("complete", job["completion"])
                self.assertEqual(1, len(job["assets"]))
                asset = job["assets"][0]
                self.assertEqual("text/html", asset["media_type"])
                self.assertEqual("primary", asset["role"])
                self.assertEqual(1, asset["order"])
                archived = call_ok(
                    client,
                    "resource_archive",
                    {
                        "flow_id": flow["flow_id"],
                        "job_id": started["job_id"],
                        "asset_id": asset["asset_id"],
                        "idempotency_key": "web-e2e-archive-key-01",
                        "metadata": {"title": "恐龙网页", "tags": ["恐龙"]},
                    },
                )
                self.assertEqual(asset["bundle_id"], archived["bundle_id"])
                library = call_ok(
                    client,
                    "resource_library_search",
                    {
                        "flow_id": flow["flow_id"],
                        "filters": {"query": "恐龙"},
                        "limit": 20,
                    },
                )
                self.assertEqual(asset["bundle_id"], library["assets"][0]["bundle_id"])


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
