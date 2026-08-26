"""Focused tests for truncated-download detection and Range resume (2026-08-26).

Anna's Archive slow links cut connections mid-transfer; read-to-EOF alone
reported the truncated payload as success. The downloader must verify
Content-Length and resume with Range requests.
"""

from __future__ import annotations

from email.message import Message
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import PublicHttpDownloader
from education_resource_mcp.errors import DomainError


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        jobs_dir=root / "jobs",
        download_timeout_seconds=5,
    )


class _FakeResponse:
    def __init__(self, body: bytes, status: int, headers: dict) -> None:
        self._body = body
        self.status = status
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def read(self, size: int = -1) -> bytes:
        chunk = self._body[: max(size, 0) if size and size > 0 else None]
        self._body = self._body[len(chunk):] if size and size > 0 else b""
        return chunk

    def geturl(self) -> str:
        return "https://mirror.example.org/book.pdf"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DownloadResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.downloader = PublicHttpDownloader(_settings(self.root))
        # offline tests: skip real DNS validation, fake the transport
        patcher = mock.patch(
            "education_resource_mcp.downloader.validate_public_http_url",
            lambda url: None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _resource(self) -> dict:
        return {
            "resource_id": "res-dl",
            "title": "测试书",
            "source_url": "https://mirror.example.org/book.pdf",
        }

    def test_truncated_without_resume_reports_failure(self) -> None:
        """Every attempt EOFs short of Content-Length -> explicit failure."""

        def fake_open(request, timeout=None):
            # always truncated: 400 of 1000 bytes declared
            return _FakeResponse(b"x" * 400, 200, {"Content-Length": "1000"})

        with mock.patch(
            "education_resource_mcp.downloader.build_opener"
        ) as opener_factory:
            opener = opener_factory.return_value
            opener.open.side_effect = fake_open
            with self.assertRaises(DomainError) as ctx:
                self.downloader.download(
                    self._resource(), "job-trunc", "direct", threading.Event()
                )
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
        self.assertIn("未能续传完整", ctx.exception.message)

    def test_range_ignored_but_full_content_recovers(self) -> None:
        """Server ignores Range yet serves the full body -> restart succeeds."""

        full = b"w" * 1000
        calls = {"n": 0}

        def fake_open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(full[:400], 200, {"Content-Length": "1000"})
            return _FakeResponse(full, 200, {"Content-Length": "1000"})

        with mock.patch(
            "education_resource_mcp.downloader.build_opener"
        ) as opener_factory:
            opener = opener_factory.return_value
            opener.open.side_effect = fake_open
            result = self.downloader.download(
                self._resource(), "job-restart", "direct", threading.Event()
            )
        self.assertEqual(result.byte_size, 1000)
        self.assertEqual(result.path.read_bytes(), full)

    def test_range_resume_completes_truncated_transfer(self) -> None:
        """First read cuts at 400/1000; Range resume serves the rest (206)."""

        full = b"y" * 1000
        calls = {"n": 0}

        def fake_open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(
                    full[:400], 200, {"Content-Length": "1000"}
                )
            start = int(request.get_header("Range").split("=")[1].split("-")[0])
            body = full[start:]
            return _FakeResponse(
                body,
                206,
                {
                    "Content-Length": str(len(body)),
                    "Content-Range": f"bytes {start}-999/1000",
                },
            )

        with mock.patch(
            "education_resource_mcp.downloader.build_opener"
        ) as opener_factory:
            opener = opener_factory.return_value
            opener.open.side_effect = fake_open
            result = self.downloader.download(
                self._resource(), "job-resume", "direct", threading.Event()
            )
        self.assertEqual(result.byte_size, 1000)
        self.assertEqual(result.path.read_bytes(), full)
        self.assertEqual(calls["n"], 2)

    def test_exact_length_first_pass_succeeds(self) -> None:
        full = b"z" * 500
        with mock.patch(
            "education_resource_mcp.downloader.build_opener"
        ) as opener_factory:
            opener = opener_factory.return_value
            opener.open.side_effect = lambda req, timeout=None: _FakeResponse(
                full, 200, {"Content-Length": "500"}
            )
            result = self.downloader.download(
                self._resource(), "job-full", "direct", threading.Event()
            )
        self.assertEqual(result.byte_size, 500)


if __name__ == "__main__":
    unittest.main()
