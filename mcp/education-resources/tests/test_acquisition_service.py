"""Service-level acceptance for the private 0021 acquisition seam."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import zipfile


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.acquisition.web_fetch import FetchResult
from education_resource_mcp.acquisition.web_materializer import WebMaterializer
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


PNG = b"\x89PNG\r\n\x1a\nservice-fixture"


class _UnusedDirectProvider:
    def download(
        self,
        resource,
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        raise AssertionError("web materialization must not use direct download")


class _FixtureFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        self.calls.append(("page", url))
        body = (
            "<html><body><article><h1>恐龙如何生活</h1>"
            "<p>这是一份静态可读资料。</p>"
            "<img src='/images/dinosaur.png' alt='恐龙图'>"
            "<script>alert(1)</script></article></body></html>"
        ).encode("utf-8")
        return FetchResult(url, 200, "text/html", body, {})

    def fetch_image(self, url: str, *, cancel_event=None):
        self.calls.append(("image", url))
        return FetchResult(url, 200, "image/png", PNG, {}), None


class _StaticLandingInspector:
    """Offline evidence for the landing page materialized by this fixture."""

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


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
        max_workers=2,
        plan_ttl_seconds=60,
    )


class AcquisitionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self.temp.name))
        self.fetcher = _FixtureFetcher()
        direct = _UnusedDirectProvider()
        self.service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider(
                [
                    {
                        "platform": "generic",
                        "title": "儿童恐龙网页",
                        "source_url": "https://example.com/dinosaurs",
                        "resource_type": "article",
                        "summary": "静态文章",
                        "metadata": {},
                    }
                ]
            ),
            download_provider=direct,
            acquisition_router=AcquisitionRouter(
                [
                    ProviderRegistration(
                        provider_id="generic-direct",
                        provider_version="1.0.0",
                        provider=direct,
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    ),
                    ProviderRegistration(
                        provider_id="generic-web-materializer",
                        provider_version="1.0.0",
                        provider=WebMaterializer(fetcher=self.fetcher),
                        strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                        scopes=("landing_page",),
                    ),
                ]
            ),
            inspection_router=InspectionRouter([_StaticLandingInspector()]),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def _run_job(self) -> tuple[str, dict]:
        flow = self.service.flow_start(
            "flow-acquisition-service-0001",
            {"goal": {"topic": "恐龙"}, "constraints": []},
        )
        result_set = self.service.search(
            flow["flow_id"],
            "search-acquisition-service-0001",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            limit=10,
        )
        candidate = result_set["candidates"][0]
        self.service.inspect(
            flow["flow_id"],
            "inspect-acquisition-service-0001",
            candidate["resource_id"],
        )
        presentation = self.service.presentation_save(
            flow["flow_id"],
            result_set["result_set_id"],
            [candidate["resource_id"]],
            "present-acquisition-service-0001",
        )
        selection = self.service.selection_save(
            flow["flow_id"],
            "select-acquisition-service-00001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        plan = self.service.download_prepare(
            flow["flow_id"],
            "prepare-acquisition-service-0001",
            selection["selection_version"],
            options={
                "preferred_container": "html",
            },
        )
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "start-acquisition-service-00001",
            presentation_id=plan["presentation_id"],
            presented_version=plan["presented_version"],
            selection_version=plan["selection_version"],
            selection_digest=plan["selection_digest"],
            plan_digest=plan["plan_digest"],
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = self.service.job_status(flow["flow_id"], started["job_id"])
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                return flow["flow_id"], status
            time.sleep(0.01)
        self.fail("acquisition job did not reach a terminal state")

    def test_standalone_html_is_single_public_asset_and_archives_directly(self) -> None:
        flow_id, status = self._run_job()
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(len(status["assets"]), 1)
        self.assertEqual(status["assets"][0]["media_type"], "text/html")
        self.assertEqual(1, len(status["outcomes"]))
        outcome = status["outcomes"][0]
        self.assertEqual(
            {
                "provider_id": "generic-web-materializer",
                "version": "1.0.0",
                "scope": "landing_page",
            },
            outcome["planned"]["provider"],
        )
        self.assertEqual("landing_page", outcome["planned"]["scope"])
        self.assertEqual("web_materialize", outcome["planned"]["strategy"])
        self.assertEqual(outcome["planned"]["provider"], outcome["actual"]["provider"])
        self.assertEqual(outcome["planned"]["scope"], outcome["actual"]["scope"])
        self.assertEqual(outcome["planned"]["strategy"], outcome["actual"]["strategy"])
        asset_id = status["assets"][0]["asset_id"]
        asset = self.service.store.get_asset(asset_id)
        self.assertIsNotNone(asset)
        assert asset is not None
        self.assertEqual(asset["filename"], "index.html")
        primary_html = Path(asset["local_path"]).read_text(encoding="utf-8")
        self.assertNotIn("<script", primary_html.casefold())
        self.assertIn("data:image/png;base64,", primary_html)
        self.assertNotIn("assets/image-", primary_html)

        job_bundle = self.settings.jobs_dir / status["job_id"] / "webbundle.zip"
        self.assertTrue(job_bundle.is_file())
        with zipfile.ZipFile(job_bundle) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertIn("index.html", names)
            self.assertIn("content.md", names)
            self.assertIn("metadata.json", names)
            self.assertTrue(any(name.startswith("assets/image-") for name in names))
            sanitized = archive.read("index.html").decode("utf-8")
            markdown = archive.read("content.md").decode("utf-8")
            self.assertIn("data:image/png;base64,", sanitized)
            self.assertIn("assets/image-", markdown)

        archived = self.service.archive(
            flow_id,
            status["job_id"],
            asset_id,
            idempotency_key="archive-acquisition-service-001",
            metadata={"title": "恐龙网页资料", "tags": ["恐龙"]},
        )
        self.assertEqual(archived["asset_id"], asset_id)
        stored_archive = self.service.store.get_archive_for_asset(asset_id)
        self.assertIsNotNone(stored_archive)
        assert stored_archive is not None
        archived_path = self.settings.library_dir / Path(stored_archive["library_path"])
        self.assertEqual(".html", archived_path.suffix)
        archived_html = archived_path.read_text(encoding="utf-8")
        self.assertNotIn("<script", archived_html.casefold())
        self.assertIn("data:image/png;base64,", archived_html)

        self.assertEqual(
            self.fetcher.calls,
            [
                ("page", "https://example.com/dinosaurs"),
                ("image", "https://example.com/images/dinosaur.png"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
