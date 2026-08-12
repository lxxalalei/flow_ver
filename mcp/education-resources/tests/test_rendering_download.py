"""Tests for the explicit CDP capture adapter and static-first service routing."""

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
from education_resource_mcp.acquisition import (
    AcquisitionResult,
    AcquisitionRouter,
    AcquisitionStrategy,
    Artifact,
    ProviderRegistration,
    ArtifactBundle,
)
from education_resource_mcp.cdp_renderer import CDPRenderer
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.service import ResourceService


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
        max_search_results=20,
        max_workers=2,
        plan_ttl_seconds=60,
    )


class _StaticLandingInspector:
    """Offline landing-page evidence for static materialization routing."""

    platform_id = "generic"
    inspector_id = "generic"
    version = "1.0.0"

    def inspect(self, resource: dict) -> InspectionResult:
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": resource["title"],
                "resource_type": resource["resource_type"],
                "availability": {"status": "available"},
                "representations": [
                    {
                        "scope": "landing_page",
                        "kind": "webpage",
                        "container": "html",
                        "mime_type": "text/html",
                        "role": "landing",
                        "materializable": True,
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-08T00:00:00Z",
            ),
            failures=[],
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

    def render(self, url, job_dir, *, formats, cancel_event, cookies=""):
        self.calls.append({
            "url": url,
            "job_dir": job_dir,
            "formats": formats,
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
            "source_url": "https://93.184.216.34/article",
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
            self._resource(), "job_1", "webpage", threading.Event()
        )
        self.assertIsInstance(result, DownloadResult)
        self.assertEqual(result.filename, "天文知识页.mhtml")
        self.assertEqual(result.media_type, "multipart/related")
        self.assertTrue(result.path.is_file())
        self.assertEqual(result.sha256, hashlib.sha256(_mhtml_bytes()).hexdigest())
        call = renderer.calls[0]
        self.assertEqual(call["formats"], {"mhtml"})
        self.assertEqual(call["url"], "https://93.184.216.34/article")

    def test_preferred_container_pdf_adds_pdf(self) -> None:
        job_dir = self.settings.jobs_dir / "job_2"
        job_dir.mkdir(parents=True, exist_ok=True)
        mhtml = job_dir / "page.mhtml"
        mhtml.write_bytes(_mhtml_bytes())
        renderer = FakeRenderer(produced=[(mhtml, "multipart/related", ".mhtml", "rendered mhtml")])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]

        downloader.download(
            self._resource(preferred_container="pdf"),
            "job_2", "webpage", threading.Event(),
        )
        self.assertEqual(renderer.calls[0]["formats"], {"mhtml", "pdf"})

    def test_non_webpage_strategy_rejected(self) -> None:
        renderer = FakeRenderer()
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        with self.assertRaises(DomainError) as ctx:
            downloader.download(self._resource(), "job_3", "direct", threading.Event())
        self.assertEqual(ctx.exception.code, "INVALID_ARGUMENT")

    def test_non_http_scheme_blocked(self) -> None:
        renderer = FakeRenderer()
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        with self.assertRaises(DomainError) as ctx:
            downloader.download(
                self._resource(source_url="ftp://example.com/private"),
                "job_4", "webpage", threading.Event(),
            )
        self.assertEqual(ctx.exception.code, "NETWORK_BLOCKED")
        self.assertEqual(renderer.calls, [])

    def test_rendered_file_has_no_size_gate(self) -> None:
        job_dir = self.settings.jobs_dir / "job_5"
        job_dir.mkdir(parents=True, exist_ok=True)
        page = job_dir / "page.mhtml"
        page.write_bytes(b"x" * 10)
        renderer = FakeRenderer(produced=[(page, "multipart/related", ".mhtml", "rendered mhtml")])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        result = downloader.download(
            self._resource(), "job_5", "webpage", threading.Event()
        )
        self.assertEqual(result.byte_size, 10)

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
            self._resource(platform="bilibili"), "job_6", "webpage",
            threading.Event(),
        )
        self.assertEqual(renderer.calls[0]["cookies"], "sid=abc")

    def test_empty_render_produces_validation_error(self) -> None:
        renderer = FakeRenderer(produced=[])
        downloader = RenderingDownloader(self.settings, renderer=renderer)  # type: ignore[arg-type]
        with self.assertRaises(DomainError) as ctx:
            downloader.download(
                self._resource(), "job_7", "webpage", threading.Event()
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
                formats=set(), cancel_event=threading.Event(),
            )
        self.assertEqual(ctx.exception.code, "INVALID_ARGUMENT")

    def test_missing_chrome_reports_browser_failure(self) -> None:
        renderer = CDPRenderer(chrome_executable="/nonexistent/chrome")
        with self.assertRaises(DomainError) as ctx:
            renderer.render(
                "https://example.com/", self.job_dir,
                formats={"mhtml"},
                cancel_event=threading.Event(),
            )
        self.assertEqual(ctx.exception.code, "RENDER_BROWSER_FAILED")


class ServiceRoutingTests(unittest.TestCase):
    """A webpage plan uses the static materializer, never implicit browser capture."""

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

            def render(self, url, job_dir, *, formats, cancel_event, cookies=""):
                self.called = True
                job_dir = Path(job_dir)
                job_dir.mkdir(parents=True, exist_ok=True)
                p = job_dir / "page.mhtml"
                p.write_bytes(_mhtml_bytes())
                return [(p, "multipart/related", ".mhtml", "rendered mhtml")]

        # A browser renderer may exist in the process, but it is deliberately
        # not registered as an executable capability for this landing-page Plan.
        fake = RoutingRenderer()

        class StaticMaterializer:
            def __init__(self) -> None:
                self.called = False

            def materialize(self, request):
                self.called = True
                job_dir = request.jobs_root / request.job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                payload = b"PK\\x03\\x04static-web-bundle"
                path = (job_dir / "webbundle.zip").resolve()
                path.write_bytes(payload)
                artifact = Artifact(
                    artifact_id=f"{request.job_id}:artifact:bundle",
                    role="bundle",
                    path=path,
                    filename="webbundle.zip",
                    byte_size=len(payload),
                    media_type="application/zip",
                    sha256=hashlib.sha256(payload).hexdigest(),
                    primary=True,
                )
                return AcquisitionResult.success(
                    AcquisitionStrategy.WEB_MATERIALIZE,
                    ArtifactBundle((artifact,)),
                )

        static = StaticMaterializer()
        acquisition_router = AcquisitionRouter(
            [
                ProviderRegistration(
                    provider_id="generic-web-materializer",
                    provider_version="1.0.0",
                    provider=static,
                    strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                    scopes=("landing_page",),
                )
            ]
        )
        service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(resources),
            acquisition_router=acquisition_router,
            inspection_router=InspectionRouter([_StaticLandingInspector()]),
        )
        service._fake_renderer = fake  # type: ignore[attr-defined]
        service._fake_static_materializer = static  # type: ignore[attr-defined]
        return service

    def test_webpage_job_uses_static_materializer_without_browser(self) -> None:
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
        service.inspect(
            flow["flow_id"],
            "inspect-routing-00001",
            search["candidates"][0]["resource_id"],
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
            options={"preferred_container": "html"},
        )
        started = service.download_start(
            flow["flow_id"], plan["plan_id"], plan["confirmation_token"],
            "start-routing-000001",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
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
        self.assertTrue(service._fake_static_materializer.called)  # type: ignore[attr-defined]
        self.assertFalse(service._fake_renderer.called)  # type: ignore[attr-defined]
        assets = status.get("assets") or []
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["media_type"], "application/zip")
        service.close()


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
