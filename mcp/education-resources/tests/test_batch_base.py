"""0057 M1: batch_collect / batch_read base (file-backed, O(1) summaries)."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.batch import run_batch_collect
from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.job_state import write_job
from education_resource_mcp.service import ResourceService


class _NoopSpawner:
    """JobSpawner stand-in that never spawns; tests drive the runner directly."""

    def submit(self, job_id, spawn):  # noqa: ANN001
        pass

    def is_pending(self, job_id):  # noqa: ANN001
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


class _CreatorProvider:
    """Offline provider enumerating a fake creator catalogue."""

    def __init__(self, count: int = 120) -> None:
        self.count = count
        self.calls: list[tuple[str, int]] = []

    def search(self, search_tasks, limit):  # pragma: no cover - unused here
        return [], []

    def search_creator(self, platform, creator_id, limit, cancel_event=None):
        self.calls.append((creator_id, limit))
        items = [
            {
                "platform": platform,
                "title": f"作品 {i:03d}",
                "source_url": f"https://example.com/{creator_id}/{i}",
                "resource_type": "video",
                "metadata": {"author": "测试UP", "published_at": "2026-08-01"},
            }
            for i in range(min(limit, self.count))
        ]
        return items, []


class _NoCreatorProvider:
    def search(self, search_tasks, limit):  # pragma: no cover
        return [], []


class BatchCollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.provider = _CreatorProvider(count=120)
        self.service = self._service(self.provider)

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def _service(self, provider) -> ResourceService:
        return ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=1,
            ),
            search_provider=provider,
            job_runner=_NoopSpawner(),
        )

    def test_collect_writes_jsonl_and_pages(self) -> None:
        result = self.service.batch_collect(
            "bilibili", creator_id="434377496", max_items=120
        )
        job_id = result["job_id"]
        self.assertEqual("queued", result["status"])
        directory = self.root / "jobs" / job_id
        self.assertEqual(0, run_batch_collect(directory, self.service))

        status = self.service.job_status(job_id)
        self.assertEqual("succeeded", status["status"])
        self.assertEqual(120, status["progress"]["completed"])
        (file_entry,) = status["files"]
        self.assertEqual("results.jsonl", file_entry["filename"])
        self.assertTrue(Path(file_entry["path"]).is_file())
        # provider received the batch budget, not a conversational limit
        self.assertEqual(("434377496", 120), self.provider.calls[-1])

        page1 = self.service.batch_read(job_id, offset=0, limit=20)
        self.assertEqual(20, len(page1["items"]))
        self.assertFalse(page1["complete"])
        self.assertEqual("作品 000", page1["items"][0]["title"])
        self.assertEqual("测试UP", page1["items"][0]["author"])

        last = self.service.batch_read(job_id, offset=100, limit=20)
        self.assertEqual(20, len(last["items"]))
        self.assertTrue(last["complete"])

        tail = self.service.batch_read(job_id, offset=119, limit=50)
        self.assertEqual(1, len(tail["items"]))
        self.assertTrue(tail["complete"])

    def test_invalid_arguments_are_loud(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.batch_collect("bilibili", mode="unknown", creator_id="x")
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        for payload in (
            lambda: self.service.batch_collect("", creator_id="x"),
            lambda: self.service.batch_collect("douyin", creator_id=""),
            lambda: self.service.batch_collect("douyin", creator_id="x", max_items=0),
            lambda: self.service.batch_collect(
                "douyin", creator_id="x", max_items=1001
            ),
        ):
            with self.assertRaises(DomainError) as ctx:
                payload()
            self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)

    def test_read_rejects_download_jobs_and_bad_paging(self) -> None:
        directory = self.root / "jobs" / ("job_" + "e" * 32)
        directory.mkdir(parents=True)
        write_job(directory, {"job_id": "job_" + "e" * 32, "status": "succeeded"})
        with self.assertRaises(DomainError) as ctx:
            self.service.batch_read("job_" + "e" * 32)
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)

        result = self.service.batch_collect("bilibili", creator_id="u1", max_items=5)
        run_batch_collect(self.root / "jobs" / result["job_id"], self.service)
        with self.assertRaises(DomainError):
            self.service.batch_read(result["job_id"], offset=-1)
        with self.assertRaises(DomainError):
            self.service.batch_read(result["job_id"], limit=0)

    def test_unsupported_creator_platform_fails_honestly(self) -> None:
        service = self._service(_NoCreatorProvider())
        try:
            result = service.batch_collect("smartedu", creator_id="x", max_items=5)
            directory = self.root / "jobs" / result["job_id"]
            self.assertEqual(0, run_batch_collect(directory, service))
            status = service.job_status(result["job_id"])
            self.assertEqual("failed", status["status"])
            (failure,) = status["failures"]
            self.assertEqual("FEATURE_NOT_SUPPORTED", failure["code"])
        finally:
            service.shutdown()


if __name__ == "__main__":
    unittest.main()
