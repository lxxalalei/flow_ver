"""Web materialization preserves source HTML and renders cleaned views for reading."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from education_resource_mcp.errors import DomainError
from education_resource_mcp.acquisition.models import AcquisitionRequest, AcquisitionStrategy
from education_resource_mcp.acquisition.web_fetch import FetchResult, ImageFormat
from education_resource_mcp.acquisition.web_materializer import MaterializerConfig, WebMaterializer


class FakeFetcher:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls = 0
        self.image_calls = 0
        self.image_body = b"\x89PNG\r\n\x1a\nreader-image"

    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        self.calls += 1
        return FetchResult(url, 200, "text/html", self.body, {})

    def fetch_image(self, url: str, *, cancel_event=None):
        self.image_calls += 1
        return (
            FetchResult(url, 200, "image/png", self.image_body, {}),
            ImageFormat("png", "image/png", ".png"),
        )


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

    def test_source_snapshot_is_exact_and_reader_view_is_standalone(self) -> None:
        fetcher = FakeFetcher(self.html)
        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=[
                "# Volcano Formation\n\nMagma rises and forms a volcano.",
                '''<article><h1>Volcano Formation</h1>
                <p>Magma rises and forms a volcano.</p>
                <img src="https://cdn.example.org/volcano.jpg" alt="volcano">
                </article>''',
            ],
        ):
            result = WebMaterializer(fetcher=fetcher).acquire(request(self.root))
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
        self.assertIn('class="reader-bar"', readable)
        self.assertIn('class="reader-main"', readable)
        self.assertIn("网页资料 · 清洗版", readable)
        self.assertIn("example.org", readable)
        self.assertIn("Reader base theme: Simple.css 2.3.7", readable)
        self.assertIn("MIT License", readable)
        self.assertIn("<style>", readable)
        self.assertNotIn('<link rel="stylesheet"', readable.casefold())
        self.assertIn('src="data:image/png;base64,', readable)
        self.assertNotIn("https://cdn.example.org/volcano.jpg", readable)
        self.assertIn("img-src &#x27;self&#x27; data:", readable)
        self.assertNotIn("http: https: data:", readable)
        self.assertEqual(1, fetcher.image_calls)

        metadata = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual("trafilatura", metadata["extractor"])
        self.assertEqual("succeeded", metadata["extraction_status"])
        self.assertEqual(len(self.html), metadata["source_bytes"])
        self.assertEqual("clean-reader-v2", metadata["reader_template"])
        self.assertEqual("Simple.css 2.3.7", metadata["reader_theme"])
        self.assertTrue(metadata["reader_css_embedded"])
        self.assertTrue(metadata["reader_images_embedded"])
        self.assertEqual(1, metadata["embedded_image_count"])
        self.assertEqual(0, metadata["failed_image_count"])
        self.assertEqual(1, metadata["image_fetch_count"])
        self.assertTrue(metadata["links_requested"])
        self.assertTrue(metadata["images_requested"])

        # webbundle.zip was removed (user-facing single-file deliverable only)
        self.assertFalse((job / "webbundle.zip").exists())
        reader = (job / "index.html").read_text(encoding="utf-8")
        self.assertIn("Reader base theme: Simple.css 2.3.7", reader)
        self.assertIn('src="data:image/png;base64,', reader)

    def test_duplicate_images_are_fetched_once(self) -> None:
        html = b'''<html><body><article><h1>Images</h1>
        <img src="/same.png" alt="first"><img src="/same.png" alt="second">
        </article></body></html>'''
        fetcher = FakeFetcher(html)
        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=[
                "# Images",
                '''<article><h1>Images</h1><img src="/same.png" alt="first">
                <img src="/same.png" alt="second"></article>''',
            ],
        ):
            result = WebMaterializer(fetcher=fetcher).acquire(request(self.root))
        self.assertTrue(result.ok)
        self.assertEqual("complete", result.completion)
        self.assertEqual(1, fetcher.image_calls)
        readable = (self.root / "job-web-001" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertEqual(2, readable.count('src="data:image/png;base64,'))

    def test_failed_image_is_replaced_and_reported_as_partial(self) -> None:
        class FailingImageFetcher(FakeFetcher):
            def fetch_image(self, url: str, *, cancel_event=None):
                self.image_calls += 1
                raise DomainError("RESOURCE_NOT_FOUND", "missing")

        fetcher = FailingImageFetcher(self.html)
        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=[
                "# Volcano Formation",
                '<article><img src="https://cdn.example.org/volcano.jpg" '
                'alt="volcano"></article>',
            ],
        ):
            result = WebMaterializer(fetcher=fetcher).acquire(request(self.root))
        self.assertTrue(result.ok)
        self.assertEqual("partial", result.completion)
        self.assertIn("image_embedding_incomplete", result.warnings)
        readable = (self.root / "job-web-001" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("https://cdn.example.org/volcano.jpg", readable)
        self.assertIn("图片未能离线保存：volcano", readable)
        metadata = json.loads(
            (self.root / "job-web-001" / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertFalse(metadata["reader_images_embedded"])
        self.assertEqual(0, metadata["embedded_image_count"])
        self.assertEqual(1, metadata["failed_image_count"])

    def test_image_fetch_cancellation_is_not_downgraded_to_partial(self) -> None:
        class CancelledImageFetcher(FakeFetcher):
            def fetch_image(self, url: str, *, cancel_event=None):
                raise DomainError("JOB_CANCELLED", "cancelled")

        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=[
                "# Volcano Formation",
                '<article><img src="https://cdn.example.org/volcano.jpg"></article>',
            ],
        ):
            with self.assertRaises(DomainError) as ctx:
                WebMaterializer(fetcher=CancelledImageFetcher(self.html)).acquire(
                    request(self.root)
                )
        self.assertEqual("JOB_CANCELLED", ctx.exception.code)

    def test_retryable_image_fetch_can_recover(self) -> None:
        class RetryImageFetcher(FakeFetcher):
            def fetch_image(self, url: str, *, cancel_event=None):
                self.image_calls += 1
                if self.image_calls == 1:
                    raise DomainError("RATE_LIMITED", "retry", retryable=True)
                return (
                    FetchResult(url, 200, "image/png", self.image_body, {}),
                    ImageFormat("png", "image/png", ".png"),
                )

        fetcher = RetryImageFetcher(self.html)
        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=[
                "# Volcano Formation",
                '<article><img src="https://cdn.example.org/volcano.jpg"></article>',
            ],
        ), patch(
            "education_resource_mcp.acquisition.web_materializer._wait_before_image_retry"
        ):
            result = WebMaterializer(fetcher=fetcher).acquire(request(self.root))
        self.assertEqual("complete", result.completion)
        self.assertEqual(2, fetcher.image_calls)
        metadata = json.loads(
            (self.root / "job-web-001" / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, metadata["image_fetch_count"])

    def test_cleaned_document_wrapper_is_replaced_by_one_reader_shell(self) -> None:
        cleaned_html = """<!doctype html><html><head><title>Clean</title></head><body>
        <article><h1>Clean title</h1><blockquote>quoted</blockquote>
        <table><tr><th>A</th></tr><tr><td>B</td></tr></table>
        <pre><code>print('ok')</code></pre></article></body></html>"""
        with patch(
            "education_resource_mcp.acquisition.web_materializer.trafilatura_extract",
            side_effect=["# Clean title", cleaned_html],
        ):
            result = WebMaterializer(fetcher=FakeFetcher(self.html)).acquire(request(self.root))
        self.assertTrue(result.ok)
        readable = (self.root / "job-web-001" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(1, readable.casefold().count("<html"))
        self.assertEqual(1, readable.casefold().count("<body"))
        self.assertIn("<blockquote>quoted</blockquote>", readable)
        self.assertIn("<table>", readable)
        self.assertIn("<pre><code>print('ok')</code></pre>", readable)

    def test_extraction_failure_keeps_source_snapshot_and_styled_partial_page(self) -> None:
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
        readable = (job / "index.html").read_text(encoding="utf-8")
        self.assertIn("source.html", readable)
        self.assertIn('class="reader-empty"', readable)
        self.assertIn("Reader base theme: Simple.css 2.3.7", readable)

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
