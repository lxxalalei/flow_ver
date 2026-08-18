"""Web materialization preserves source HTML and derives views with Trafilatura."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from education_resource_mcp.errors import DomainError
from education_resource_mcp.acquisition.models import AcquisitionRequest, AcquisitionStrategy
from education_resource_mcp.acquisition.web_fetch import FetchResult
from education_resource_mcp.acquisition.web_materializer import MaterializerConfig, WebMaterializer


class FakeFetcher:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls = 0

    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        self.calls += 1
        return FetchResult(url, 200, "text/html", self.body, {})


def request(root: Path, url: str = "https://example.org/article") -> AcquisitionRequest:
    return AcquisitionRequest(
        job_id="job-web-001",
        resource={
            "resource_id": "res-web",
            "title": "火山资料",
            "source_url": url,
        },
        strategy=AcquisitionStrategy.WEB_MATERIALIZE,
        provider_id="generic-web-materializer",
        scope="primary_resource",
        representation_id="repr-web",
        preferred_container="html",
        jobs_root=root,
        cancel_event=threading.Event(),
    )


class WebMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.html = b'''<!doctype html><html><body><nav>noise</nav><article>
        <h1>Volcano Formation</h1><p>Magma rises and forms a volcano.</p>
        <p><a href="https://example.org/next">Next lesson</a></p>
        <img src="https://cdn.example.org/volcano.jpg" alt="volcano">
        </article></body></html>'''

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_source_snapshot_is_exact_and_readable_views_exist(self) -> None:
        result = WebMaterializer(fetcher=FakeFetcher(self.html)).acquire(request(self.root))
        self.assertTrue(result.ok)
        job = self.root / "job-web-001"
        self.assertEqual(self.html, (job / "source.html").read_bytes())
        markdown = (job / "content.md").read_text(encoding="utf-8")
        self.assertIn("Volcano Formation", markdown)
        self.assertIn("Magma rises", markdown)
        readable = (job / "index.html").read_text(encoding="utf-8")
        self.assertIn("Volcano Formation", readable)
        self.assertEqual(1, readable.casefold().count("<html"))
        self.assertEqual(1, readable.casefold().count("<body"))
        metadata = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual("trafilatura", metadata["extractor"])
        self.assertEqual("succeeded", metadata["extraction_status"])
        self.assertEqual(len(self.html), metadata["source_bytes"])
        self.assertTrue(metadata["links_requested"])
        self.assertTrue(metadata["images_requested"])
        with zipfile.ZipFile(job / "webbundle.zip") as archive:
            self.assertEqual(
                ["content.md", "index.html", "metadata.json", "source.html"],
                archive.namelist(),
            )

    def test_extraction_failure_keeps_source_snapshot_and_reports_partial(self) -> None:
        fetcher = FakeFetcher(self.html)
        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=ValueError("extract failed"),
        ):
            result = WebMaterializer(fetcher=fetcher).acquire(request(self.root))
        job = self.root / "job-web-001"
        self.assertEqual(self.html, (job / "source.html").read_bytes())
        self.assertEqual("partial", result.completion)
        self.assertIn("content_extraction_failed", result.warnings)
        metadata = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual("source_only", metadata["extraction_status"])
        self.assertIn("source.html", (job / "index.html").read_text(encoding="utf-8"))

    def test_real_fetch_bound_fails_explicitly(self) -> None:
        materializer = WebMaterializer(
            fetcher=FakeFetcher(b"<article>" + b"x" * 1024 + b"</article>"),
            config=MaterializerConfig(max_html_bytes=128),
        )
        with self.assertRaises(DomainError) as ctx:
            materializer.acquire(request(self.root))
        self.assertEqual("DOWNLOAD_TOO_LARGE", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
