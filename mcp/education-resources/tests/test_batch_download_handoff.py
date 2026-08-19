"""Batch discovery stays candidate-only, then hands selected resources to download."""

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
from education_resource_mcp.job_state import read_job, read_request, write_job
from education_resource_mcp.service import ResourceService


class _NoopSpawner:
    def submit(self, job_id, spawn):  # noqa: ANN001
        pass

    def is_pending(self, job_id):  # noqa: ANN001
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


class _CreatorProvider:
    def search(self, search_tasks, limit):  # pragma: no cover - unused
        return [], []

    def search_creator(self, platform, creator_id, limit, cancel_event=None):
        return [
            {
                "platform": platform,
                "title": f"作品 {index}",
                "source_url": f"https://example.com/{creator_id}/{index}",
                "resource_type": "video",
                "metadata": {"author": "测试作者"},
            }
            for index in range(limit)
        ], []


class BatchDownloadHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        self.service = ResourceService(
            settings=Settings(
                data_dir=root,
                jobs_dir=root / "jobs",
                library_dir=root / "library",
                max_workers=1,
            ),
            search_provider=_CreatorProvider(),
            job_runner=_NoopSpawner(),
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def _completed_batch(self) -> str:
        result = self.service.batch_collect(
            "bilibili",
            mode="creator_full",
            creator_id="12345",
            max_items=3,
        )
        directory = self.root / "jobs" / result["job_id"]
        self.assertEqual(0, run_batch_collect(directory, self.service))
        self.assertEqual("succeeded", self.service.job_status(result["job_id"])["status"])
        return result["job_id"]

    def test_batch_read_registers_page_candidates_for_subset_download(self) -> None:
        batch_id = self._completed_batch()
        page = self.service.batch_read(batch_id, limit=2)
        self.assertEqual(2, len(page["items"]))
        first_id = page["items"][0].get("resource_id")
        self.assertTrue(str(first_id).startswith("res_"))

        download = self.service.download([str(first_id)])
        request = read_request(self.root / "jobs" / download["job_id"])
        self.assertEqual(1, len(request["resources"]))
        self.assertEqual(first_id, request["resources"][0]["resource_id"])
        self.assertIsNone(request["source_batch_job_id"])

    def test_completed_batch_can_feed_one_download_job_without_paging_all_urls(self) -> None:
        batch_id = self._completed_batch()
        download = self.service.download(batch_job_id=batch_id)
        request = read_request(self.root / "jobs" / download["job_id"])

        self.assertEqual(batch_id, request["source_batch_job_id"])
        self.assertEqual(3, len(request["resources"]))
        self.assertEqual(
            ["作品 0", "作品 1", "作品 2"],
            [item["title"] for item in request["resources"]],
        )
        status = read_job(self.root / "jobs" / download["job_id"])
        self.assertEqual(3, status["total"])

    def test_batch_source_requires_complete_success(self) -> None:
        batch_id = self._completed_batch()
        directory = self.root / "jobs" / batch_id
        write_job(directory, {**read_job(directory), "status": "partial"})

        with self.assertRaises(DomainError) as ctx:
            self.service.download(batch_job_id=batch_id)
        self.assertEqual("BATCH_INCOMPLETE", ctx.exception.code)

    def test_download_source_is_explicitly_one_of_ids_or_complete_batch(self) -> None:
        batch_id = self._completed_batch()
        page = self.service.batch_read(batch_id, limit=1)
        resource_id = page["items"][0]["resource_id"]

        with self.assertRaises(DomainError):
            self.service.download()
        with self.assertRaises(DomainError):
            self.service.download([resource_id], batch_job_id=batch_id)


if __name__ == "__main__":
    unittest.main()
