"""Static-first service routing: a webpage plan uses the static materializer."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition.models import (
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.service import ResourceService


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
        max_workers=2,
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
                self.partial = False

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
                    warnings=("image_embedding_incomplete",) if self.partial else (),
                    completion="partial" if self.partial else "complete",
                )

        static = StaticMaterializer()
        service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(resources),
            download_handlers={"generic-web-materializer": static},
            inspection_router=InspectionRouter([_StaticLandingInspector()]),
        )
        service._fake_renderer = fake  # type: ignore[attr-defined]
        service._fake_static_materializer = static  # type: ignore[attr-defined]
        return service

    def test_webpage_job_uses_static_materializer_without_browser(self) -> None:
        service = self._make_service()
        search = service.search(
            [{"platform": "generic", "queries": [{"query": "天文"}]}], limit=10
        )
        resource_id = search["candidates"][0]["resource_id"]
        files, failures = service.download_resource(
            "job-routing-0001",
            service._get_resource(resource_id),
            "html",
            threading.Event(),
        )
        self.assertTrue(service._fake_static_materializer.called)  # type: ignore[attr-defined]
        self.assertFalse(service._fake_renderer.called)  # type: ignore[attr-defined]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["media_type"], "application/zip")
        self.assertEqual([], failures)
        service.shutdown()

    def test_partial_materialization_is_exposed_to_job_worker(self) -> None:
        service = self._make_service()
        service._fake_static_materializer.partial = True  # type: ignore[attr-defined]
        search = service.search(
            [{"platform": "generic", "queries": [{"query": "天文"}]}], limit=10
        )
        resource_id = search["candidates"][0]["resource_id"]
        files, failures = service.download_resource(
            "job-routing-0002",
            service._get_resource(resource_id),
            "html",
            threading.Event(),
        )
        self.assertEqual(1, len(files))
        self.assertEqual(1, len(failures))
        self.assertEqual("PARTIAL_FAILURE", failures[0]["code"])
        self.assertIn("部分正文图片", failures[0]["message"])
        service.shutdown()


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
