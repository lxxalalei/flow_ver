"""Tests for the CDP rendering downloader.

The CDP renderer is exercised at the unit level with a mocked renderer, plus
error paths that do not need a real browser.  The service routing test asserts
that the ``webpage`` strategy selects the rendering downloader rather than the
raw HTTP downloader.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters.rendering_download import RenderingDownloader
from education_resource_mcp.cdp_renderer import CDPRenderer
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError
from education_resource_mcp.service import ResourceService


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
        max_download_bytes=1024 * 1024,
        max_search_results=20,
        max_workers=2,
        plan_ttl_seconds=60,
    )


def _mhtml_bytes() -> bytes:
    return (
        b"From: <Saved by Blink>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/related; boundary=\"----X\"\r\n\r\n"
        b"----X\r\nContent-Type: text/html\r\n\r\n<html><body>ok</body></html>\r\n"
        b"----X--\r\n"
    )


class FakeRenderer:
    """Records calls and returns a stub produced-file list."""

    def __init__(self, produced: list[tuple[Path, str, str, str]] | None = None) -> None:
        self.produced = produced
        self.calls: list[dict] = []

    def render(self, url, job_dir, *, formats, max_bytes, cancel_event, cookies=""):
        self.calls.append({
            "url": url,
            "job_dir": job_dir,
            "formats": formats,
            "max_bytes": max_bytes,
            "cookies": cookies,
        })
        if self.produced is None:
            return []
        return self.produced


class RenderingDownloaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _resource(self, **overrides) -> dict:
        base = {
            "resource_id": "res_1",
            "title": "天文知识页",
            "source_url": "https://example.com/article",
            "platform": "generic",
        }
        base.update(overrides)
        return base

    def test_webpage_strategy_renders_mhtml_by_default(self) -> None:
        job_dir = self.settings.jobs_dir / "job_1"
        job_dir.mkdir(parents=True, exist_ok=True)
        page = job_dir / "page.mhtml"
        page.write_bytes(_mhtml_bytes())
        renderer = FakeRenderer(produced=[(page, "multipart/related", ".mhtml", "rendered mhtml")])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]

        result = downloader.download(
            self._resource(), "job_1", "webpage", 1024 * 1024, threading.Event()
        )
        self.assertIsInstance(result, DownloadResult)
        self.assertEqual(result.filename, "天文知识页.mhtml")
        self.assertEqual(result.media_type, "multipart/related")
        self.assertTrue(result.path.is_file())
        self.assertEqual(result.sha256, hashlib.sha256(_mhtml_bytes()).hexdigest())
        call = renderer.calls[0]
        self.assertEqual(call["formats"], {"mhtml"})
        self.assertEqual(call["url"], "https://example.com/article")

    def test_preferred_container_pdf_adds_pdf(self) -> None:
        job_dir = self.settings.jobs_dir / "job_2"
        job_dir.mkdir(parents=True, exist_ok=True)
        mhtml = job_dir / "page.mhtml"
        mhtml.write_bytes(_mhtml_bytes())
        renderer = FakeRenderer(produced=[(mhtml, "multipart/related", ".mhtml", "rendered mhtml")])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]

        downloader.download(
            self._resource(preferred_container="pdf"),
            "job_2", "webpage", 1024 * 1024, threading.Event(),
        )
        self.assertEqual(renderer.calls[0]["formats"], {"mhtml", "pdf"})

    def test_non_webpage_strategy_rejected(self) -> None:
        renderer = FakeRenderer()
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        with self.assertRaises(DomainError) as ctx:
            downloader.download(self._resource(), "job_3", "direct", 1024, threading.Event())
        self.assertEqual(ctx.exception.code, "INVALID_ARGUMENT")

    def test_ssrf_blocked(self) -> None:
        renderer = FakeRenderer()
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        with self.assertRaises(DomainError) as ctx:
            downloader.download(
                self._resource(source_url="http://127.0.0.1:8080/private"),
                "job_4", "webpage", 1024, threading.Event(),
            )
        self.assertEqual(ctx.exception.code, "NETWORK_BLOCKED")
        self.assertEqual(renderer.calls, [])

    def test_oversize_rejected(self) -> None:
        job_dir = self.settings.jobs_dir / "job_5"
        job_dir.mkdir(parents=True, exist_ok=True)
        page = job_dir / "page.mhtml"
        page.write_bytes(b"x" * 10)
        renderer = FakeRenderer(produced=[(page, "multipart/related", ".mhtml", "rendered mhtml")])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        # max_bytes smaller than the produced file -> the downloader checks size.
        with self.assertRaises(DomainError):
            downloader.download(
                self._resource(), "job_5", "webpage", 5, threading.Event()
            )

    def test_cookies_forwarded_from_session_store(self) -> None:
        job_dir = self.settings.jobs_dir / "job_6"
        job_dir.mkdir(parents=True, exist_ok=True)
        page = job_dir / "page.mhtml"
        page.write_bytes(_mhtml_bytes())
        renderer = FakeRenderer(produced=[(page, "multipart/related", ".mhtml", "rendered mhtml")])
        session_store = MagicMock()
        session_store.get_session_data.return_value = {
            "cookies": [{"name": "sid", "value": "abc"}]
        }
        downloader = RenderingDownloader(
            self.settings, session_store=session_store, renderer=renderer  # type: ignore[arg-type]
        )
        downloader.download(
            self._resource(platform="bilibili"), "job_6", "webpage", 1024 * 1024,
            threading.Event(),
        )
        self.assertEqual(renderer.calls[0]["cookies"], "sid=abc")

    def test_empty_render_produces_validation_error(self) -> None:
        renderer = FakeRenderer(produced=[])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        with self.assertRaises(DomainError) as ctx:
            downloader.download(
                self._resource(), "job_7", "webpage", 1024 * 1024, threading.Event()
            )
        self.assertEqual(ctx.exception.code, "CONTENT_VALIDATION_FAILED")


class CDPRendererErrorPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.temp.name) / "job"
        self.job_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_no_formats_rejected(self) -> None:
        renderer = CDPRenderer(chrome_executable="/nonexistent/chrome")
        with self.assertRaises(DomainError) as ctx:
            renderer.render(
                "https://example.com/", self.job_dir,
                formats=set(), max_bytes=1024, cancel_event=threading.Event(),
            )
        self.assertEqual(ctx.exception.code, "INVALID_ARGUMENT")

    def test_missing_chrome_reports_browser_failure(self) -> None:
        renderer = CDPRenderer(chrome_executable="/nonexistent/chrome")
        with self.assertRaises(DomainError) as ctx:
            renderer.render(
                "https://example.com/", self.job_dir,
                formats={"mhtml"}, max_bytes=1024 * 1024,
                cancel_event=threading.Event(),
            )
        self.assertEqual(ctx.exception.code, "RENDER_BROWSER_FAILED")


class ServiceRoutingTests(unittest.TestCase):
    """The ``webpage`` strategy must select the rendering downloader in a real job."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_service(self) -> ResourceService:
        from education_resource_mcp.search import StaticSearchProvider

        resources = [
            {
                "platform": "generic",
                "title": "儿童天文知识网页",
                "source_url": "https://example.com/astronomy",
                "resource_type": "article",
                "summary": "网页型知识资源",
                "metadata": {},
            }
        ]

        class RoutingRenderer:
            def __init__(self) -> None:
                self.called = False

            def render(self, url, job_dir, *, formats, max_bytes, cancel_event, cookies=""):
                self.called = True
                job_dir = Path(job_dir)
                job_dir.mkdir(parents=True, exist_ok=True)
                p = job_dir / "page.mhtml"
                p.write_bytes(_mhtml_bytes())
                return [(p, "multipart/related", ".mhtml", "rendered mhtml")]

        fake = RoutingRenderer()
        renderer = RenderingDownloader(
            self.settings, renderer=fake  # type: ignore[arg-type]
        )
        service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(resources),
            download_provider=MagicMock(),  # must NOT be used for webpage
            rendering_downloader=renderer,
        )
        service._fake_renderer = fake  # type: ignore[attr-defined]
        return service

    def test_webpage_job_produces_rendered_asset(self) -> None:
        service = self._make_service()
        flow = service.flow_start(
            "flow-routing-0001", {"goal": {"topic": "天文"}, "constraints": []}
        )
        search = service.search(
            flow["flow_id"],
            "search-routing-00001",
            [{"platform": "generic", "queries": [{"query": "天文"}]}],
            filters={},
            limit=10,
        )
        presentation = service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            [item["resource_id"] for item in search["candidates"]],
            "presentation-routing-0001",
        )
        selection = service.selection_save(
            flow["flow_id"],
            "selection-routing-0001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = service.download_prepare(
            flow["flow_id"],
            "prepare-routing-000001",
            selection["selection_version"],
            options={"preferred_container": "html", "max_bytes_per_resource": 4096},
        )
        started = service.download_start(
            flow["flow_id"], plan["plan_id"], plan["confirmation_token"],
            "start-routing-000001",
        )
        job_id = started["job_id"]
        deadline = time.monotonic() + 3
        status = None
        while time.monotonic() < deadline:
            status = service.job_status(flow["flow_id"], job_id)
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "succeeded")
        self.assertTrue(service._fake_renderer.called)  # type: ignore[attr-defined]
        assets = status.get("assets") or []
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["media_type"], "multipart/related")
        self.assertEqual(assets[0]["size_bytes"], len(_mhtml_bytes()))
        service.close()


if __name__ == "__main__":
    unittest.main()
