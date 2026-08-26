from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from education_resource_mcp.config import Settings
from education_resource_mcp.job_state import read_job, write_job
from education_resource_mcp.service import ResourceService


class JobContextViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=1,
            ),
            recover_jobs=False,
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self.temp.cleanup()

    def _write_job(self, job_id: str, status: str, *, live: bool = False) -> Path:
        directory = self.root / "jobs" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "resource.pdf"
        path.write_bytes(b"pdf")
        write_job(directory, {
            "job_id": job_id,
            "status": status,
            "total": 2 if live else 1,
            "completed": 1,
            "files": [{
                "asset_id": "asset_" + "a" * 32,
                "resource_id": "res_" + "b" * 32,
                "filename": path.name,
                "path": str(path),
                "media_type": "application/pdf",
                "size_bytes": path.stat().st_size,
                "role": "primary",
                "primary": True,
                "platform": "generic",
                "source_url": "https://example.com/source.pdf",
                "title": "Verbose title",
                "author": "Author",
                "summary": "Verbose metadata stays persisted outside the Agent view.",
                "published_at": "2026-08-27",
                "language": "zh",
            }],
            "failures": [],
            "pid": os.getpid() if live else None,
        })
        return directory

    def test_running_status_returns_only_progress_and_counts(self) -> None:
        job_id = "job_" + "1" * 32
        self._write_job(job_id, "running", live=True)

        result = self.service.job_status(job_id)

        self.assertEqual("running", result["status"])
        self.assertEqual({"completed": 1, "total": 2}, result["progress"])
        self.assertEqual(1, result["file_count"])
        self.assertEqual(0, result["failure_count"])
        self.assertNotIn("files", result)
        self.assertNotIn("failures", result)

    def test_terminal_and_archive_views_are_compact_without_losing_persisted_metadata(self) -> None:
        job_id = "job_" + "2" * 32
        directory = self._write_job(job_id, "succeeded")

        status = self.service.job_status(job_id)
        public_file = status["files"][0]
        self.assertEqual(
            {"resource_id", "filename", "path", "media_type", "size_bytes", "role", "primary"},
            set(public_file),
        )
        self.assertNotIn("summary", public_file)
        self.assertEqual(
            "Verbose metadata stays persisted outside the Agent view.",
            read_job(directory)["files"][0]["summary"],
        )

        archived = self.service.archive(job_id, topic="上下文测试")
        self.assertEqual(1, archived["file_count"])
        self.assertEqual(0, archived["failure_count"])
        self.assertNotIn("summary", archived["files"][0])
        self.assertNotIn("source_url", archived["files"][0])

        persisted = read_job(directory)["files"][0]
        self.assertEqual(
            "Verbose metadata stays persisted outside the Agent view.",
            persisted["summary"],
        )
        self.assertEqual("https://example.com/source.pdf", persisted["source_url"])
        self.assertEqual(archived["files"][0]["path"], persisted["path"])


if __name__ == "__main__":
    unittest.main()
