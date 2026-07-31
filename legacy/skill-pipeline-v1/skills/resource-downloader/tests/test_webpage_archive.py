import io
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import webpage_archive


class _Response(io.BytesIO):
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://example.test/articles/page",
        content_type: str = "text/html; charset=utf-8",
        content_length: int | None = None,
    ) -> None:
        super().__init__(body)
        self.status = 200
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(
            len(body) if content_length is None else content_length
        )

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class WebpageArchiveTests(unittest.TestCase):
    def test_archives_clean_markdown_metadata_and_original_source(self) -> None:
        source = b"""<!doctype html>
<html>
  <head>
    <title>Fallback title</title>
    <meta property="og:title" content="Archived Article">
    <style>.hidden { display: none; }</style>
  </head>
  <body>
    <header><a href="/home">Site navigation</a></header>
    <nav>Products Pricing Sign in</nav>
    <article class="article-content">
      <h1>Archived Article</h1>
      <p>First paragraph with <strong>important</strong> details and
         <a href="../guide?q=1">the guide</a>.</p>
      <h2>Details</h2>
      <p>Second paragraph keeps useful text.</p>
      <ul>
        <li>Alpha</li>
        <li>Beta <a href="https://other.test/item">resource</a></li>
      </ul>
      <ol><li>First step</li><li>Second step</li></ol>
      <img src="/images/should-not-download.png" alt="ignored image">
      <script>window.secret = "noise";</script>
    </article>
    <aside>Related links and advertisements</aside>
    <footer>Copyright noise</footer>
  </body>
</html>"""
        response = _Response(source)

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                webpage_archive,
                "urlopen_with_fallback",
                return_value=response,
            ) as urlopen:
                result = webpage_archive.archive_webpage(
                    "https://example.test/articles/page",
                    directory,
                    timeout_seconds=3.5,
                    max_bytes=100_000,
                )

            output_dir = Path(directory)
            markdown = (output_dir / "content.md").read_text(encoding="utf-8")
            metadata = json.loads(
                (output_dir / "metadata.json").read_text(encoding="utf-8")
            )

            self.assertEqual((output_dir / "source.html").read_bytes(), source)
            self.assertEqual(result, metadata)
            self.assertEqual(metadata["title"], "Archived Article")
            self.assertEqual(metadata["source_bytes"], len(source))
            self.assertEqual(metadata["extraction_strategy"], "article")
            self.assertIn("# Archived Article", markdown)
            self.assertIn("## Details", markdown)
            self.assertIn("First paragraph with **important** details", markdown)
            self.assertIn(
                "[the guide](https://example.test/guide?q=1)", markdown
            )
            self.assertIn("- Alpha", markdown)
            self.assertIn("- Beta [resource](https://other.test/item)", markdown)
            self.assertIn("1. First step", markdown)
            self.assertNotIn("Site navigation", markdown)
            self.assertNotIn("Copyright noise", markdown)
            self.assertNotIn("window.secret", markdown)
            self.assertNotIn("should-not-download", markdown)
            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 3.5)
            self.assertEqual(
                metadata["links"],
                [
                    {
                        "text": "the guide",
                        "url": "https://example.test/guide?q=1",
                    },
                    {"text": "resource", "url": "https://other.test/item"},
                ],
            )

    def test_uses_meta_charset_when_header_has_no_charset(self) -> None:
        source = (
            '<html><head><meta charset="windows-1252"></head>'
            '<body><main><h1>Caf\xe9</h1><p>Cr\xe8me br\xfbl\xe9e</p></main></body></html>'
        ).encode("latin-1")

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                webpage_archive,
                "urlopen_with_fallback",
                return_value=_Response(source, content_type="text/html"),
            ):
                metadata = webpage_archive.archive_webpage(
                    "https://example.test/latin",
                    directory,
                    timeout_seconds=2,
                    max_bytes=10_000,
                )

            markdown = (Path(directory) / "content.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["encoding"], "windows-1252")
            self.assertIn("# Caf\xe9", markdown)
            self.assertIn("Cr\xe8me br\xfbl\xe9e", markdown)

    def test_ignores_heading_inside_navigation_header_for_title(self) -> None:
        source = b"""<html><head><title>Document title</title></head><body>
<header><h1>Site name</h1></header>
<main><h1>Useful article</h1><p>Useful body text.</p></main>
</body></html>"""

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                webpage_archive,
                "urlopen_with_fallback",
                return_value=_Response(source),
            ):
                metadata = webpage_archive.archive_webpage(
                    "https://example.test/useful",
                    directory,
                    timeout_seconds=2,
                    max_bytes=10_000,
                )

            markdown = (Path(directory) / "content.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["title"], "Useful article")
            self.assertNotIn("Site name", markdown)

    def test_rejects_response_larger_than_max_bytes(self) -> None:
        response = _Response(b"0123456789", content_length=10)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "archive"
            with mock.patch.object(
                webpage_archive,
                "urlopen_with_fallback",
                return_value=response,
            ):
                with self.assertRaises(webpage_archive.ArchiveSizeLimitError):
                    webpage_archive.archive_webpage(
                        "https://example.test/large",
                        output_dir,
                        timeout_seconds=2,
                        max_bytes=5,
                    )

            self.assertFalse(output_dir.exists())

    def test_passes_timeout_to_urlopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                webpage_archive,
                "urlopen_with_fallback",
                side_effect=TimeoutError("timed out"),
            ) as urlopen:
                with self.assertRaises(TimeoutError):
                    webpage_archive.archive_webpage(
                        "https://example.test/slow",
                        directory,
                        timeout_seconds=0.25,
                        max_bytes=1_000,
                    )

            self.assertEqual(urlopen.call_args.kwargs["timeout"], 0.25)


if __name__ == "__main__":
    unittest.main()
