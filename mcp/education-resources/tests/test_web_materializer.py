"""Golden and security tests for the static web materializer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.errors import DomainError
from education_resource_mcp.acquisition.models import AcquisitionRequest, AcquisitionStrategy
from education_resource_mcp.acquisition.web_blocks import (
    BlockLimits,
    extract_block_ir,
)
from education_resource_mcp.acquisition.web_materializer import (
    MaterializerConfig,
    WebMaterializer,
)
import education_resource_mcp.acquisition.web_materializer as materializer_module
from education_resource_mcp.acquisition.web_fetch import BoundedWebFetcher, FetchResult


FIXTURES = Path(__file__).parent / "fixtures" / "web_materializer"


_PNG = b"\x89PNG\r\n\x1a\n" + b"fixture-png"


class _TransportResponse:
    def __init__(self, url: str, body: bytes, media_type: str) -> None:
        self.url = url
        self.status = 200
        self.headers = {"Content-Type": media_type, "Content-Length": str(len(body))}
        self._body = body
        self._read = False

    def geturl(self) -> str:
        return self.url

    def read(self, amount: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body

    def close(self) -> None:
        return None


class _StaticTransport:
    def __init__(self, responses: dict[str, tuple[bytes, str]]) -> None:
        self.responses = responses

    def __call__(self, request, timeout: float) -> _TransportResponse:
        body, media_type = self.responses[request.full_url]
        return _TransportResponse(request.full_url, body, media_type)


class FakeFetcher:
    def __init__(self, pages: dict[str, bytes], images: dict[str, bytes | Exception] | None = None) -> None:
        self.pages = pages
        self.images = images or {}
        self.calls: list[dict[str, object]] = []

    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        self.calls.append({"url": url, "purpose": "page"})
        if url not in self.pages:
            raise DomainError("WEB_FETCH_FAILED", "page missing")
        return FetchResult(url, 200, "text/html", self.pages[url], {})

    def fetch_image(self, url: str, *, cancel_event=None):
        self.calls.append({"url": url, "purpose": "image"})
        value = self.images.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise DomainError("WEB_FETCH_FAILED", "image missing")
        return FetchResult(url, 200, "image/png", value, {}), None


def _request(
    root: Path,
    source_url: str,
    *,
    job_id: str = "job-web-001",
    max_bytes: int = 8 * 1024 * 1024,
    cancel_event: threading.Event | None = None,
):
    return AcquisitionRequest(
        job_id=job_id,
        resource={
            "resource_id": "res_web_materializer_0001",
            "title": "测试网页",
            "source_url": source_url,
        },
        strategy=AcquisitionStrategy.WEB_MATERIALIZE,
        provider_id="fixture-web-materializer",
        provider_version="1.0.0",
        planned_scope="landing_page",
        representation_id="repr_web_materializer_0001",
        binding_digest="a" * 64,
        source_fingerprint="sha256:" + "e" * 64,
        capability_id="cap_web_materializer_landing_v1",
        descriptor_version="1.0.0",
        descriptor_digest="sha256:" + "b" * 64,
        readiness_snapshot_id="ready_web_materializer_v1",
        readiness_digest="sha256:" + "c" * 64,
        eligibility_id="elig_web_materializer_v1",
        eligibility_digest="sha256:" + "d" * 64,
        jobs_root=root,
        max_bytes=max_bytes,
        cancel_event=cancel_event or threading.Event(),
    )


class WebMaterializerGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self, name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    def test_four_golden_shapes_extract_expected_blocks(self) -> None:
        cases = {
            "ordinary-article.html": {"heading", "paragraph", "quote"},
            "classical-poem.html": {"heading", "paragraph", "linebreak"},
            "zhihu-long.html": {"heading", "paragraph", "list", "quote", "code", "table"},
            "image-blog.html": {"heading", "paragraph", "image"},
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                ir = extract_block_ir(self._fixture(filename), source_url="https://example.com/article")
                self.assertTrue(expected.issubset({block.kind for block in ir.blocks}))
                self.assertLessEqual(len(ir.blocks), 4096)
                self.assertNotIn("script", {block.kind for block in ir.blocks})

    def test_materializer_returns_zip_primary_and_exposes_readable_artifacts(self) -> None:
        url = "https://example.com/article"
        fetcher = FakeFetcher({url: self._fixture("ordinary-article.html")})
        result = WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url))

        artifacts = tuple(result.bundle.artifacts)
        self.assertGreaterEqual(len(artifacts), 4)
        self.assertTrue(_get(artifacts[0], "primary"))
        self.assertEqual(_get(artifacts[0], "role"), "bundle")
        self.assertEqual(_get(artifacts[0], "filename"), "webbundle.zip")
        self.assertEqual(
            {"sanitized_html", "markdown", "metadata"},
            {_get(artifact, "role") for artifact in artifacts[1:4]},
        )
        job_dir = self.root / "job-web-001"
        self.assertEqual(
            {"index.html", "content.md", "metadata.json", "webbundle.zip", "assets"},
            {path.name for path in job_dir.iterdir()},
        )
        self.assertIn("<h1>云为什么会下雨</h1>", (job_dir / "index.html").read_text())
        self.assertNotIn("site-nav", (job_dir / "index.html").read_text())

    def test_output_is_deterministic_and_zip_links_are_relative(self) -> None:
        url = "https://example.com/image-blog"
        html = self._fixture("image-blog.html")
        fetcher = FakeFetcher({url: html}, {"https://example.com/images/seed.png": _PNG})
        first = WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url, job_id="job-a"))
        second = WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url, job_id="job-b"))
        first_zip = (self.root / "job-a" / "webbundle.zip").read_bytes()
        second_zip = (self.root / "job-b" / "webbundle.zip").read_bytes()
        self.assertEqual(first_zip, second_zip)
        self.assertEqual(
            hashlib.sha256(first_zip).hexdigest(),
            _get(first.bundle.artifacts[0], "sha256"),
        )
        with zipfile.ZipFile(io.BytesIO(first_zip)) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertTrue(names)
            self.assertTrue(all(not name.startswith("/") for name in names))
            self.assertTrue(all(".." not in name.split("/") for name in names))
            index = archive.read("index.html").decode()
            markdown = archive.read("content.md").decode()
            self.assertIn("assets/image-", index)
            self.assertIn("assets/image-", markdown)
            self.assertNotIn("https://", index)
            self.assertNotIn("https://", markdown)

    def test_real_bounded_web_fetcher_fetch_html_and_fetch_image_shape(self) -> None:
        url = "https://example.com/image-blog"
        transport = _StaticTransport(
            {
                url: (FIXTURES.joinpath("image-blog.html").read_bytes(), "text/html; charset=utf-8"),
                "https://example.com/images/seed.png": (_PNG, "image/png"),
            }
        )
        fetcher = BoundedWebFetcher(
            resolver=lambda _hostname, _port: ("93.184.216.34",),
            transport=transport,
            timeout_seconds=1,
            max_bytes=1024 * 1024,
        )
        result = WebMaterializer(fetcher=fetcher).materialize(_request(self.root, url))
        self.assertTrue(result.ok)
        self.assertEqual(result.strategy, AcquisitionStrategy.WEB_MATERIALIZE)
        self.assertEqual(result.metadata["provider"], "static_web")
        self.assertTrue(any(_get(item, "role") == "image" for item in result.bundle.artifacts))

    def test_same_origin_image_failure_becomes_placeholder(self) -> None:
        url = "https://example.com/image-blog"
        fetcher = FakeFetcher(
            {url: self._fixture("image-blog.html")},
            {"https://example.com/images/seed.png": DomainError("WEB_FETCH_FAILED", "timeout")},
        )
        result = WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url))
        job_dir = self.root / "job-web-001"
        self.assertIn("图片未能安全加载", (job_dir / "index.html").read_text())
        self.assertIn("image_fetch_failed", result.warnings)
        self.assertFalse(list((job_dir / "assets").iterdir()))

    def test_image_limit_keeps_first_asset_and_placeholder_for_rest(self) -> None:
        url = "https://example.com/two-images"
        page = """
        <article><h1>图片</h1>
          <img src='/a.png' alt='a'><img src='/b.png' alt='b'>
        </article>
        """.encode("utf-8")
        fetcher = FakeFetcher(
            {url: page},
            {"https://example.com/a.png": _PNG, "https://example.com/b.png": _PNG},
        )
        config = MaterializerConfig(max_image_count=1)
        WebMaterializer(fetcher=fetcher, config=config).acquire(_request(self.root, url))
        job_dir = self.root / "job-web-001"
        self.assertEqual(len(list((job_dir / "assets").iterdir())), 1)
        self.assertIn("图片未能安全加载", (job_dir / "index.html").read_text())
        image_calls = [call for call in fetcher.calls if call["purpose"] == "image"]
        self.assertEqual(len(image_calls), 1)

    def test_html_limit_is_rejected_before_rendering(self) -> None:
        url = "https://example.com/large"
        fetcher = FakeFetcher({url: b"<article>" + b"x" * 1024 + b"</article>"})
        materializer = WebMaterializer(fetcher=fetcher, config=MaterializerConfig(max_html_bytes=128))
        with self.assertRaises(DomainError) as context:
            materializer.acquire(_request(self.root, url))
        self.assertEqual(context.exception.code, "DOWNLOAD_TOO_LARGE")

    def test_package_files_and_zip_are_counted_together(self) -> None:
        url = "https://example.com/article-total-limit"
        fetcher = FakeFetcher({url: self._fixture("ordinary-article.html")})
        WebMaterializer(fetcher=fetcher).acquire(
            _request(self.root, url, job_id="job-measure", max_bytes=8 * 1024 * 1024)
        )
        measured_dir = self.root / "job-measure"
        package_size = sum(
            (measured_dir / name).stat().st_size
            for name in ("index.html", "content.md", "metadata.json")
        )
        total_size = package_size + (measured_dir / "webbundle.zip").stat().st_size
        self.assertGreater(total_size, package_size)

        with self.assertRaises(DomainError) as context:
            WebMaterializer(fetcher=fetcher).acquire(
                _request(self.root, url, job_id="job-total-limit", max_bytes=total_size - 1)
            )
        self.assertEqual(context.exception.code, "DOWNLOAD_TOO_LARGE")
        limited_dir = self.root / "job-total-limit"
        self.assertFalse((limited_dir / "webbundle.zip").exists())
        self.assertFalse((limited_dir / "index.html").exists())

    def test_cancellation_after_fetch_stops_before_output(self) -> None:
        url = "https://example.com/cancelled"
        event = threading.Event()

        class CancellingFetcher(FakeFetcher):
            def fetch_html(self, target: str, *, cancel_event=None) -> FetchResult:
                result = super().fetch_html(target, cancel_event=cancel_event)
                event.set()
                return result

        fetcher = CancellingFetcher({url: self._fixture("ordinary-article.html")})
        with self.assertRaises(DomainError) as context:
            WebMaterializer(fetcher=fetcher).acquire(
                _request(self.root, url, cancel_event=event)
            )
        self.assertEqual(context.exception.code, "JOB_CANCELLED")
        job_dir = self.root / "job-web-001"
        self.assertFalse((job_dir / "index.html").exists())
        self.assertFalse((job_dir / "webbundle.zip").exists())

    def test_partial_write_failure_cleans_materialized_files(self) -> None:
        url = "https://example.com/write-failure"
        fetcher = FakeFetcher({url: self._fixture("ordinary-article.html")})
        original = materializer_module._write_output
        calls = 0

        def fail_second_write(path, data, job_dir):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("fixture write failure")
            return original(path, data, job_dir)

        with patch.object(materializer_module, "_write_output", fail_second_write):
            with self.assertRaises(OSError):
                WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url))
        job_dir = self.root / "job-web-001"
        self.assertFalse((job_dir / "index.html").exists())
        self.assertFalse((job_dir / "content.md").exists())
        self.assertFalse((job_dir / "metadata.json").exists())
        self.assertFalse((job_dir / "webbundle.zip").exists())


class WebMaterializerSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_xss_and_dangerous_links_are_not_reemitted(self) -> None:
        url = "https://example.com/xss"
        page = """
        <html><head><title><script>alert(1)</script>安全页</title></head>
        <body><article>
          <h1 onclick='alert(1)'>标题 &lt;安全&gt;</h1>
          <p><a href='javascript:alert(1)'>危险链接</a> <a href='https://evil.example/'>外链</a></p>
          <img src='javascript:alert(1)' onerror='alert(1)' alt='<坏图片>'>
          <script>alert('xss')</script><iframe src='https://evil.example'></iframe>
          <pre><code>&lt;script&gt;alert(2)&lt;/script&gt;</code></pre>
        </article></body></html>
        """.encode("utf-8")
        fetcher = FakeFetcher({url: page})
        WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url))
        job_dir = self.root / "job-web-001"
        sanitized = (job_dir / "index.html").read_text()
        markdown = (job_dir / "content.md").read_text()
        self.assertNotIn("<script", sanitized.casefold())
        self.assertNotIn("javascript:", sanitized.casefold())
        self.assertNotIn("onerror", sanitized.casefold())
        self.assertNotIn("javascript:", markdown.casefold())
        self.assertIn("&lt;script&gt;", sanitized)
        self.assertIn("Content-Security-Policy", sanitized)

    def test_job_id_and_generated_asset_names_cannot_escape_job_directory(self) -> None:
        url = "https://example.com/path-traversal"
        page = "<article><img src='../../../../etc/passwd' alt='bad'><p>正文</p></article>".encode("utf-8")
        fetcher = FakeFetcher({url: page}, {"https://example.com/etc/passwd": _PNG})
        with self.assertRaises(ValueError) as context:
            WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url, job_id="../escape"))
        self.assertIn("job_id", str(context.exception))

        result = WebMaterializer(fetcher=fetcher).acquire(_request(self.root, url, job_id="job-safe"))
        self.assertTrue(result.bundle.artifacts)
        self.assertFalse((self.root / "etc").exists())
        with zipfile.ZipFile(self.root / "job-safe" / "webbundle.zip") as archive:
            self.assertTrue(all(".." not in name.split("/") for name in archive.namelist()))

    def test_dom_and_block_limits_are_bounded(self) -> None:
        page = "<article>" + "".join(f"<p>{index}</p>" for index in range(20)) + "</article>"
        ir = extract_block_ir(page, limits=BlockLimits(max_blocks=3, max_text_chars=20))
        self.assertLessEqual(len(ir.blocks), 3)
        self.assertTrue(ir.truncated)
        self.assertTrue(any(block.kind == "placeholder" for block in ir.blocks))


def _get(value: object, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


if __name__ == "__main__":
    unittest.main()
