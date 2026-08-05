from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


class FakeDownloader:
    def __init__(self, jobs_dir: Path, *, wait_for_cancel: bool = False) -> None:
        self.jobs_dir = jobs_dir
        self.wait_for_cancel = wait_for_cancel

    def download(
        self,
        resource,
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        if self.wait_for_cancel:
            for _ in range(200):
                if cancel_event.wait(0.005):
                    raise DomainError("JOB_CANCELLED", "cancelled")
        payload = f"<html>{resource['title']}</html>".encode()
        if len(payload) > max_bytes:
            raise DomainError("DOWNLOAD_TOO_LARGE", "too large")
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "resource.html"
        path.write_bytes(payload)
        return DownloadResult(
            path=path,
            byte_size=len(payload),
            media_type="text/html",
            sha256=hashlib.sha256(payload).hexdigest(),
            filename=path.name,
        )


class ResourceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.settings = Settings(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=data_dir / "library",
            max_download_bytes=1024 * 1024,
            max_search_results=20,
            max_workers=2,
            plan_ttl_seconds=60,
        )
        resources = [
            {
                "platform": "generic",
                "title": "儿童恐龙知识网页",
                "source_url": "https://example.com/dinosaurs",
                "resource_type": "article",
                "summary": "适合儿童理解恐龙的公开介绍",
                "metadata": {"language": "zh-CN"},
            },
            {
                "platform": "generic",
                "title": "无关资源",
                "source_url": "https://example.org/other",
                "resource_type": "article",
                "summary": "其他内容",
                "metadata": {},
            },
        ]
        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(resources),
            download_provider=FakeDownloader(self.settings.jobs_dir),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def _start_and_search(self):
        flow = self.service.flow_start(
            "flow-start-key-0001", {"goal": {"topic": "恐龙"}, "user_role": "parent", "resource_target": "child", "constraints": []}
        )
        search = self.service.search(
            flow["flow_id"],
            "search-key-0000001",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            filters={},
            limit=10,
        )
        presentation = self.service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            [item["resource_id"] for item in search["candidates"]],
            "presentation-key-0001",
        )
        return flow, search, presentation

    def _wait_terminal(self, flow_id: str, job_id: str):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = self.service.job_status(flow_id, job_id)
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                return status
            time.sleep(0.01)
        self.fail("job did not reach a terminal state")

    def test_full_flow_is_idempotent_and_archives_by_asset_id(self) -> None:
        flow, search, presentation = self._start_and_search()
        self.assertEqual(search["stage"], "reviewing")
        self.assertEqual(len(search["candidates"]), 1)
        resource_id = search["candidates"][0]["resource_id"]

        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-0001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = self.service.download_prepare(
            flow["flow_id"],
            "prepare-key-000001",
            selection["selection_version"],
            options={"preferred_container": "html", "max_bytes_per_resource": 4096},
        )
        replayed_plan = self.service.download_prepare(
            flow["flow_id"],
            "prepare-key-000001",
            selection["selection_version"],
            options={"preferred_container": "html", "max_bytes_per_resource": 4096},
        )
        self.assertEqual(replayed_plan, plan)

        with self.assertRaisesRegex(DomainError, "确认令牌"):
            self.service.download_start(
                flow["flow_id"], plan["plan_id"], "wrong-token", "start-key-00000001"
            )
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-key-00000002",
        )
        replayed_start = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-key-00000002",
        )
        self.assertEqual(replayed_start["job_id"], started["job_id"])
        status = self._wait_terminal(flow["flow_id"], started["job_id"])
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(len(status["assets"]), 1)

        asset_id = status["assets"][0]["asset_id"]
        archived = self.service.archive(
            flow["flow_id"],
            started["job_id"],
            asset_id,
            idempotency_key="archive-key-000001",
            metadata={"title": "恐龙资料", "tags": ["恐龙", "儿童"]},
        )
        replayed_archive = self.service.archive(
            flow["flow_id"],
            started["job_id"],
            asset_id,
            idempotency_key="archive-key-000001",
            metadata={"title": "恐龙资料", "tags": ["恐龙", "儿童"]},
        )
        self.assertEqual(archived, replayed_archive)
        library = self.service.library_search(
            flow["flow_id"], filters={"query": "恐龙"}, limit=20
        )
        self.assertEqual(len(library["assets"]), 1)
        self.assertEqual(library["assets"][0]["asset_id"], asset_id)

    def test_idempotency_conflict_and_presented_set_guard(self) -> None:
        flow = self.service.flow_start(
            "flow-start-key-0002", {"goal": {"topic": "恐龙"}, "user_role": "parent", "resource_target": "child", "constraints": []}
        )
        self.assertEqual(
            flow,
            self.service.flow_start(
                "flow-start-key-0002", {"goal": {"topic": "恐龙"}, "user_role": "parent", "resource_target": "child", "constraints": []}
            ),
        )
        with self.assertRaisesRegex(DomainError, "幂等键"):
            self.service.flow_start(
                "flow-start-key-0002", {"goal": {"topic": "数学"}, "user_role": "parent", "resource_target": "child", "constraints": []}
            )
        search = self.service.search(
            flow["flow_id"], "search-key-0000002",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            limit=10,
        )
        presentation = self.service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            [search["candidates"][0]["resource_id"]],
            "presentation-key-0002",
        )
        with self.assertRaises(DomainError) as captured:
            self.service.selection_save(
                flow["flow_id"],
                "selection-key-0002",
                presentation["presentation_id"],
                presentation["presented_version"],
                [2],
            )
        self.assertEqual(captured.exception.code, "POSITION_NOT_PRESENTED")

    def test_cancelled_selection_cannot_prepare(self) -> None:
        flow, search, presentation = self._start_and_search()
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-0003",
            presentation["presentation_id"],
            presentation["presented_version"],
            [],
        )
        self.assertTrue(selection["cancelled"])
        with self.assertRaises(DomainError) as captured:
            self.service.download_prepare(
                flow["flow_id"],
                "prepare-key-000003",
                selection["selection_version"],
            )
        self.assertEqual(captured.exception.code, "RESOURCE_NOT_SELECTED")

    def test_running_job_can_be_cancelled_and_assets_are_not_archivable(self) -> None:
        self.service.close()
        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(
                [
                    {
                        "platform": "generic",
                        "title": "儿童恐龙知识网页",
                        "source_url": "https://example.com/dinosaurs",
                        "resource_type": "article",
                        "summary": "恐龙",
                        "metadata": {},
                    }
                ]
            ),
            download_provider=FakeDownloader(self.settings.jobs_dir, wait_for_cancel=True),
        )
        flow, search, presentation = self._start_and_search()
        resource_id = search["candidates"][0]["resource_id"]
        selection = self.service.selection_save(
            flow["flow_id"],
            "selection-key-0004",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = self.service.download_prepare(
            flow["flow_id"], "prepare-key-000004", selection["selection_version"]
        )
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-key-00000004",
        )
        cancelled = self.service.job_cancel(
            flow["flow_id"],
            started["job_id"],
            "cancel-key-0000004",
            "用户取消",
        )
        self.assertIn(cancelled["status"], {"cancelling", "cancelled"})
        status = self._wait_terminal(flow["flow_id"], started["job_id"])
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["assets"], [])
        flow_status = self.service.flow_status(flow["flow_id"])
        self.assertEqual(flow_status["current_job"]["asset_ids"], [])


if __name__ == "__main__":
    unittest.main()

