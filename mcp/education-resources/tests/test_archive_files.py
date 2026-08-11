from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.archive import (
    ArchiveFileError,
    ArchiveFileManager,
    build_relative_path,
    format_directory,
    media_signature_matches,
    resource_format,
    sanitize_component,
    validate_relative_path,
)
from education_resource_mcp.taxonomy import DOMAIN_REGISTRY


class ArchivePathTests(unittest.TestCase):
    def test_format_directory_uses_other_for_unknown_content(self) -> None:
        self.assertEqual(format_directory("video/mp4", "lesson.bin"), "视频")
        self.assertEqual(format_directory("audio/mpeg", "lesson.bin"), "音频")
        self.assertEqual(format_directory("application/pdf", "lesson.pdf"), "图文")
        self.assertEqual(
            format_directory("application/octet-stream", "lesson.unknown"),
            "其他",
        )
        self.assertEqual(resource_format("application/pdf", "lesson.pdf"), "document")
        self.assertTrue(media_signature_matches("application/pdf", "lesson.pdf", b"%PDF-1.7"))
        self.assertFalse(media_signature_matches("application/pdf", "lesson.pdf", b"not pdf"))

    def test_build_path_uses_registered_directory_and_server_facts(self) -> None:
        path = build_relative_path(
            {
                "classification_status": "classified",
                "primary_domain": "natural_science",
                "topics": [" 天文与宇宙 "],
            },
            source_name="B站",
            title="太阳系动画讲解",
            filename="asset.mp4",
            media_type="video/mp4",
        )
        self.assertEqual(
            path,
            "04-自然科学/天文与宇宙/视频/B站-太阳系动画讲解.mp4",
        )

    def test_unclassified_path_and_missing_source_have_no_extra_separator(self) -> None:
        path = build_relative_path(
            {
                "classification_status": "needs_review",
                "primary_domain": None,
                "topics": [],
            },
            source_name="",
            title="资料",
            filename="asset.bin",
            media_type="application/octet-stream",
        )
        self.assertEqual(path, "99-待分类/其他/其他/资料.bin")

    def test_every_domain_generates_its_fixed_chinese_directory(self) -> None:
        for domain_id, record in DOMAIN_REGISTRY.items():
            with self.subTest(domain_id=domain_id):
                path = build_relative_path(
                    {
                        "classification_status": "classified",
                        "primary_domain": domain_id,
                        "topics": ["其他"],
                    },
                    source_name="来源",
                    title="资料",
                    filename="asset.pdf",
                    media_type="application/pdf",
                )
                self.assertEqual(path.split("/", 1)[0], record["directory"])

    def test_component_cleaning_blocks_separators_controls_and_dot_segments(self) -> None:
        cleaned = sanitize_component(" ../坏\x00/名\\试卷  ", fallback="其他", max_bytes=40)
        self.assertNotIn("/", cleaned)
        self.assertNotIn("\\", cleaned)
        self.assertNotIn("\x00", cleaned)
        self.assertNotEqual(cleaned, "..")
        with self.assertRaises(ArchiveFileError):
            validate_relative_path("../../escape.pdf")
        with self.assertRaises(ArchiveFileError):
            validate_relative_path("/absolute/path.pdf")
        with self.assertRaises(ArchiveFileError):
            validate_relative_path("safe/" + "x" * 1000)


class ArchiveFileManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "学习资料库"
        self.manager = ArchiveFileManager(self.root)
        self.source = Path(self.tempdir.name) / "asset.bin"
        self.payload = b"verified learning resource"
        self.source.write_bytes(self.payload)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _stage(self, operation_id: str = "archive_test"):
        return self.manager.stage(
            self.source,
            media_type="application/octet-stream",
            operation_id=operation_id,
        )

    def test_stage_copies_file_without_integrity_metadata(self) -> None:
        staged = self._stage("copy")
        self.assertEqual(self.payload, (self.root / staged.relative_path).read_bytes())

    def test_stage_rejects_declared_pdf_with_invalid_signature(self) -> None:
        pdf_source = Path(self.tempdir.name) / "invalid.pdf"
        pdf_source.write_bytes(self.payload)
        with self.assertRaisesRegex(ArchiveFileError, "文件签名"):
            self.manager.stage(
                pdf_source,
                media_type="application/pdf",
                operation_id="bad_format",
            )
        self.assertFalse((self.root / ".archive-staging" / "bad_format.pending").exists())

    def test_same_name_uses_next_available_filename(self) -> None:
        first = self._stage("first")
        first_result = self.manager.publish_no_replace(
            first.relative_path,
            "04-自然科学/其他/其他/资料.bin",
        )
        second = self._stage("second")
        second_result = self.manager.publish_no_replace(
            second.relative_path,
            "04-自然科学/其他/其他/资料.bin",
        )
        self.assertFalse(first_result.deduplicated)
        self.assertFalse(second_result.deduplicated)
        self.assertEqual(second_result.relative_path, "04-自然科学/其他/其他/资料-2.bin")

    def test_same_name_different_content_gets_numeric_suffix(self) -> None:
        existing = self.root / "04-自然科学" / "其他" / "其他" / "资料.bin"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"different")
        staged = self._stage("collision")
        published = self.manager.publish_no_replace(
            staged.relative_path,
            "04-自然科学/其他/其他/资料.bin",
        )
        self.assertEqual(published.relative_path, "04-自然科学/其他/其他/资料-2.bin")
        self.assertEqual(existing.read_bytes(), b"different")
        self.assertEqual((self.root / published.relative_path).read_bytes(), self.payload)

    def test_symlink_parent_escape_is_rejected(self) -> None:
        outside = Path(self.tempdir.name) / "outside"
        outside.mkdir()
        domain = self.root / "04-自然科学"
        try:
            domain.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        staged = self._stage("symlink")
        with self.assertRaises(ArchiveFileError):
            self.manager.publish_no_replace(
                staged.relative_path,
                "04-自然科学/其他/其他/资料.bin",
            )
        self.assertFalse((outside / "其他" / "其他" / "资料.bin").exists())


if __name__ == "__main__":
    unittest.main()
