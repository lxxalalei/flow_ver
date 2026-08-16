"""0056 download job durability: file-backed state and detached workers."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.job_state import FileCancelEvent, write_job
from education_resource_mcp.service import ResourceService

PDF_BYTES = b"%PDF-1.4 durable job test\n" + b"x" * 4096


def _job_dict(job_id: str, status: str, *, pid: int | None = None) -> dict:
    return {
        "job_id": job_id,
        "status": status,
        "total": 1,
        "completed": 0 if status in {"queued", "running"} else 1,
        "files": [],
        "failures": [],
        "pid": pid,
    }


def _make_job_dir(root: Path, job_id: str, status: str, *, pid: int | None = None,
                  stale: bool = False) -> Path:
    directory = root / "jobs" / job_id
    directory.mkdir(parents=True, exist_ok=True)
    write_job(directory, _job_dict(job_id, status, pid=pid))
    if stale:
        # Push updated_at beyond the spawn grace window so the recovery scan
        # treats the job as a genuine orphan instead of a starting worker.
        data = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        data["updated_at"] = "2000-01-01T00:00:00+00:00"
        (directory / "job.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return directory


class _PdfHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        body = PDF_BYTES
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class FileCancelEventTests(unittest.TestCase):
    def test_flag_file_flips_the_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "cancel.flag"
            event = FileCancelEvent(flag)
            self.assertFalse(event.is_set())
            flag.write_text("", encoding="utf-8")
            self.assertTrue(event.is_set())


class RecoveryScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_job_dir(self.root, "job_" + "a" * 32, "queued", pid=None, stale=True)
        _make_job_dir(self.root, "job_" + "b" * 32, "running", pid=999999999)
        _make_job_dir(self.root, "job_" + "c" * 32, "running", pid=os.getpid())
        _make_job_dir(self.root, "job_" + "d" * 32, "succeeded", pid=None)
        self.service = ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=2,
            )
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_orphans_interrupted_and_survivors_kept(self) -> None:
        self.assertEqual(
            "interrupted", self.service.job_status("job_" + "a" * 32)["status"]
        )
        self.assertEqual(
            "interrupted", self.service.job_status("job_" + "b" * 32)["status"]
        )
        # Our own pid is alive: the scan must not touch this job.
        self.assertEqual(
            "running", self.service.job_status("job_" + "c" * 32)["status"]
        )
        self.assertEqual(
            "succeeded", self.service.job_status("job_" + "d" * 32)["status"]
        )

    def test_archive_rejects_interrupted_job(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.archive("job_" + "a" * 32)
        self.assertEqual("JOB_NOT_FINISHED", ctx.exception.code)

    def test_malformed_job_id_rejected(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.job_status("../escape")
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


class CancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.service = ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=2,
            )
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_cancel_without_worker_writes_cancelled(self) -> None:
        job_id = "job_" + "a" * 32
        _make_job_dir(self.root, job_id, "queued", pid=None)
        result = self.service.job_cancel(job_id)
        self.assertEqual("cancelled", result["status"])
        self.assertEqual("cancelled", self.service.job_status(job_id)["status"])

    def test_repeat_cancel_force_kills_stubborn_worker(self) -> None:
        job_id = "job_" + "b" * 32
        stub = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
        )
        try:
            _make_job_dir(self.root, job_id, "running", pid=stub.pid)
            first = self.service.job_cancel(job_id)
            self.assertEqual("cancelling", first["status"])
            self.assertEqual("running", self.service.job_status(job_id)["status"])
            second = self.service.job_cancel(job_id)
            self.assertEqual("cancelled", second["status"])
            stub.wait(timeout=10)
            self.assertEqual(
                "cancelled", self.service.job_status(job_id)["status"]
            )
        finally:
            if stub.poll() is None:
                stub.kill()
                stub.wait(timeout=10)


class WorkerRoundtripTests(unittest.TestCase):
    """End-to-end: spawn a real detached worker over a local HTTP server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.jobs_root = cls.root / "jobs"
        cls.jobs_root.mkdir(parents=True, exist_ok=True)
        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), _PdfHandler)
        cls.port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls._env = mock.patch.dict(
            os.environ,
            {
                "EDUCATION_RESOURCE_MCP_DATA_DIR": str(cls.root),
                "EDUCATION_RESOURCE_MCP_LIBRARY_DIR": str(cls.root / "library"),
                "PYTHONPATH": str(SRC),
            },
        )
        cls._env.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._env.stop()
        cls._server.shutdown()
        cls._server.server_close()
        cls._tmp.cleanup()

    def _service(self) -> ResourceService:
        return ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.jobs_root,
                library_dir=self.root / "library",
                max_workers=2,
            )
        )

    def _wait_terminal(self, service: ResourceService, job_id: str) -> dict:
        deadline = time.monotonic() + 60
        last: dict = {}
        while time.monotonic() < deadline:
            last = service.job_status(job_id)
            if str(last["status"]) in {
                "succeeded", "partial", "failed", "cancelled", "interrupted"
            }:
                return last
            time.sleep(0.2)
        self.fail(f"job did not finish in time: {json.dumps(last, ensure_ascii=False)}")

    def test_download_survives_service_restart_and_archive(self) -> None:
        starter = self._service()
        with starter._lock:
            starter._resources["res_" + "1" * 32] = {
                "resource_id": "res_" + "1" * 32,
                "platform": "generic",
                "title": "durable sample pdf",
                "source_url": f"http://127.0.0.1:{self.port}/sample.pdf",
                "resource_type": "document",
                "metadata": {},
            }
        result = starter.download(["res_" + "1" * 32])
        job_id = result["job_id"]
        starter.shutdown()  # "restart": the parent that spawned is gone
        del starter

        survivor = self._service()
        status = self._wait_terminal(survivor, job_id)
        self.assertIn(status["status"], {"succeeded", "partial"}, status)
        files = status["files"]
        self.assertEqual(1, len(files))
        downloaded = Path(str(files[0]["path"]))
        self.assertTrue(downloaded.is_file())
        self.assertEqual(PDF_BYTES, downloaded.read_bytes())

        # archive via yet another instance (cross-restart archive)
        archiver = self._service()
        archive_result = archiver.archive(job_id, domain_id="", topic="持久化测试")
        self.assertEqual("succeeded", archive_result["status"])
        archived_path = Path(str(archive_result["files"][0]["path"]))
        self.assertTrue(archived_path.is_file())
        self.assertNotEqual(downloaded, archived_path)
        after = archiver.job_status(job_id)
        self.assertEqual(
            str(archived_path), str(after["files"][0]["path"])
        )
        survivor.shutdown()
        archiver.shutdown()


if __name__ == "__main__":
    unittest.main()
