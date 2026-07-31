from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "content_validation.py"
SPEC = importlib.util.spec_from_file_location("resource_downloader_content_validation", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
CONTENT_VALIDATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTENT_VALIDATION)
validate_download_file = CONTENT_VALIDATION.validate_download_file


class ContentValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_bytes(self, name: str, content: bytes) -> Path:
        path = self.root / name
        path.write_bytes(content)
        return path

    def write_zip(self, name: str, entries: dict[str, bytes]) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for entry_name, content in entries.items():
                archive.writestr(entry_name, content)
        return path

    def assert_detected(self, path: Path, expected_format: str) -> None:
        result = validate_download_file(path, [expected_format])
        self.assertTrue(result["valid"], result)
        self.assertEqual(expected_format, result["detected_format"])
        self.assertEqual([], result["errors"])

    def test_detects_signature_and_text_formats(self) -> None:
        fixtures = {
            "page.html": (b"<!doctype html><html><head><title>Article</title></head><body>ok</body></html>", "html"),
            "book.pdf": (b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n", "pdf"),
            "photo.jpg": (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00image-data\xff\xd9", "jpeg"),
            "image.png": (b"\x89PNG\r\n\x1a\nchunk-data-IEND\xaeB`\x82", "png"),
            "animation.gif": (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "gif"),
            "audio.mp3": (b"ID3\x04\x00\x00\x00\x00\x00\x00audio-data", "mp3"),
            "video.mp4": (b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42", "mp4"),
            "image.webp": (b"RIFF\x10\x00\x00\x00WEBPVP8 image-data", "webp"),
            "image.bmp": (b"BMbitmap-data", "bmp"),
            "image.tiff": (b"II*\x00tiff-data", "tiff"),
            "image.avif": (b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1", "avif"),
            "audio.wav": (b"RIFF\x10\x00\x00\x00WAVEfmt audio-data", "wav"),
            "audio.flac": (b"fLaC\x00\x00\x00\x22audio-data", "flac"),
            "video.webm": (b"\x1a\x45\xdf\xa3webm-data", "webm"),
            "video.ts": (b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 187, "mpegts"),
            "archive.7z": (b"7z\xbc\xaf\x27\x1carchive-data", "7z"),
            "legacy.doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy-office", "ole"),
            "notes.txt": ("标准库文本校验\nplain text\n".encode("utf-8"), "text"),
        }
        for filename, (content, expected_format) in fixtures.items():
            with self.subTest(expected_format=expected_format):
                self.assert_detected(self.write_bytes(filename, content), expected_format)

    def test_detects_zip_based_formats_by_internal_structure(self) -> None:
        fixtures = {
            "archive.zip": ({"folder/item.txt": b"value"}, "zip"),
            "book.epub": (
                {
                    "mimetype": b"application/epub+zip",
                    "META-INF/container.xml": b"<container/>",
                    "OEBPS/content.opf": b"<package/>",
                },
                "epub",
            ),
            "document.docx": ({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<document/>"}, "docx"),
            "workbook.xlsx": ({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>"}, "xlsx"),
            "slides.pptx": ({"[Content_Types].xml": b"<Types/>", "ppt/presentation.xml": b"<presentation/>"}, "pptx"),
        }
        for filename, (entries, expected_format) in fixtures.items():
            with self.subTest(expected_format=expected_format):
                self.assert_detected(self.write_zip(filename, entries), expected_format)

    def test_rejects_html_error_page_disguised_as_pdf(self) -> None:
        path = self.write_bytes(
            "download.pdf",
            b"<!doctype html><html><head><title>404 Not Found</title></head><body><h1>Not Found</h1></body></html>",
        )
        result = validate_download_file(path)
        error_codes = {error["code"] for error in result["errors"]}

        self.assertFalse(result["valid"])
        self.assertEqual("html", result["detected_format"])
        self.assertTrue(result["is_html_error_page"])
        self.assertTrue(result["is_masquerading_html"])
        self.assertIn("FORMAT_MISMATCH", error_codes)
        self.assertIn("HTML_ERROR_PAGE", error_codes)
        self.assertIn("UNEXPECTED_HTML_CONTENT", error_codes)

    def test_rejects_html_response_when_epub_is_explicitly_expected(self) -> None:
        path = self.write_bytes("download.bin", b"<html><head><title>Login required</title></head><body>login</body></html>")
        result = validate_download_file(path, "application/epub+zip")

        self.assertFalse(result["valid"])
        self.assertEqual(["epub"], result["expected_formats"])
        self.assertTrue(result["is_masquerading_html"])

    def test_rejects_invalid_zip_container(self) -> None:
        path = self.write_bytes("broken.epub", b"PK\x03\x04not-a-real-archive")
        result = validate_download_file(path)
        error_codes = {error["code"] for error in result["errors"]}

        self.assertFalse(result["valid"])
        self.assertIn("INVALID_ZIP_CONTAINER", error_codes)

    def test_reports_missing_and_empty_files(self) -> None:
        missing = validate_download_file(self.root / "missing.pdf")
        empty = validate_download_file(self.write_bytes("empty.pdf", b""))

        self.assertEqual("FILE_NOT_FOUND", missing["errors"][0]["code"])
        self.assertEqual("EMPTY_FILE", empty["errors"][0]["code"])

    def test_rejects_unsupported_expected_format(self) -> None:
        path = self.write_bytes("notes.txt", b"hello")
        with self.assertRaisesRegex(ValueError, "unsupported expected format"):
            validate_download_file(path, ["exe"])


if __name__ == "__main__":
    unittest.main()
