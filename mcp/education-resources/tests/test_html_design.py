"""Adaptive HTML design preserves cleaned content and terminal Job truth."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from education_resource_mcp.errors import DomainError
from education_resource_mcp.html_design import design_context, render_design
from education_resource_mcp.job_state import read_job, write_job


def _palette(*, dark: bool = False) -> dict[str, str]:
    if dark:
        return {
            "background": "#101820",
            "surface": "#182631",
            "text": "#F5F7F8",
            "muted": "#A8BAC6",
            "accent": "#78D5E3",
            "accent_soft": "#233B47",
            "border": "#35505E",
        }
    return {
        "background": "#F7FAFC",
        "surface": "#EAF2F6",
        "text": "#14232D",
        "muted": "#526B78",
        "accent": "#006A7A",
        "accent_soft": "#D9EEF1",
        "border": "#AFC6CF",
    }


def _spec() -> dict:
    return {
        "theme_name": "火山观测志",
        "subject": "火山形成与喷发机制",
        "audience": "希望理解地质过程的小学生家庭",
        "page_purpose": "用清楚的层级帮助读者理解岩浆上升和喷发过程",
        "rationale": "采用冷静的地质观察配色，以宽图和清晰章节突出过程证据。",
        "treatment": "editorial",
        "light_palette": _palette(),
        "dark_palette": _palette(dark=True),
        "type_system": "humanist",
        "layout": "wide",
        "hero": "poster",
        "section_style": "ruled",
        "image_style": "framed",
        "density": "comfortable",
        "signature": "corner_mark",
    }


class HtmlDesignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.job_id = "job_" + "a" * 32
        self.directory = self.root / self.job_id
        self.directory.mkdir()
        self.fragment = (
            "\n<article><h1>火山形成</h1><p>岩浆沿地壳裂隙上升并积聚。</p>"
            '<img src="data:image/png;base64,AAAA" alt="火山剖面">'
            "<h2>喷发过程</h2><blockquote>压力改变喷发方式。</blockquote></article>\n"
        )
        self.index = (
            '<!doctype html><html><head><title>火山形成</title></head><body>'
            '<header class="reader-bar"></header>'
            f'<main class="reader-main" id="content">{self.fragment}</main>'
            '<footer class="reader-footer"></footer></body></html>'
        )
        self.markdown = "# 火山形成\n\n岩浆沿地壳裂隙上升并积聚。\n\n## 喷发过程\n\n压力改变喷发方式。\n"
        (self.directory / "index.html").write_text(self.index, encoding="utf-8")
        (self.directory / "content.md").write_text(self.markdown, encoding="utf-8")
        (self.directory / "source.html").write_text("<html>source</html>", encoding="utf-8")
        (self.directory / "metadata.json").write_text(
            json.dumps(
                {
                    "schema_version": "web-materialization-v2",
                    "source_url": "https://science.example/volcano",
                    "reader_template": "clean-reader-v2",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        write_job(
            self.directory,
            {
                "job_id": self.job_id,
                "status": "succeeded",
                "files": [
                    {
                        "asset_id": "artifact_index",
                        "resource_id": "res_web",
                        "filename": "index.html",
                        "path": str(self.directory / "index.html"),
                        "size_bytes": len(self.index.encode("utf-8")),
                        "source_url": "https://science.example/volcano",
                        "title": "火山形成",
                    },
                    {
                        "asset_id": "artifact_source",
                        "resource_id": "res_web",
                        "filename": "source.html",
                        "path": str(self.directory / "source.html"),
                    },
                    {
                        "asset_id": "artifact_markdown",
                        "resource_id": "res_web",
                        "filename": "content.md",
                        "path": str(self.directory / "content.md"),
                    },
                    {
                        "asset_id": "artifact_metadata",
                        "resource_id": "res_web",
                        "filename": "metadata.json",
                        "path": str(self.directory / "metadata.json"),
                    },
                ],
                "failures": [],
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_context_is_bounded_structural_and_marks_untrusted_content(self) -> None:
        context = design_context(self.directory, read_job(self.directory))
        self.assertEqual("火山形成", context["title"])
        self.assertEqual("science.example", context["source_domain"])
        self.assertEqual(2, context["structure"]["headings"])
        self.assertEqual(1, context["structure"]["images"])
        self.assertEqual(2, context["outline_total"])
        self.assertFalse(context["excerpt_truncated"])
        self.assertTrue(context["untrusted_content"])
        self.assertTrue(context["constraints"]["content_must_remain_complete"])

    def test_nested_main_inside_cleaned_content_is_preserved(self) -> None:
        nested = "<main><p>正文里的语义 main</p></main>"
        path = self.directory / "index.html"
        path.write_text(self.index.replace(self.fragment, nested), encoding="utf-8")
        result = render_design(self.directory, read_job(self.directory), _spec())
        self.assertTrue(result["content_preserved"])
        self.assertIn(nested, path.read_text(encoding="utf-8"))

    def test_render_preserves_body_and_updates_metadata_and_job(self) -> None:
        source_before = (self.directory / "source.html").read_bytes()
        markdown_before = (self.directory / "content.md").read_bytes()
        result = render_design(self.directory, read_job(self.directory), _spec())

        rendered = (self.directory / "index.html").read_text(encoding="utf-8")
        self.assertIn(self.fragment, rendered)
        self.assertIn('data-treatment="editorial"', rendered)
        self.assertIn(':root[data-theme="dark"]', rendered)
        self.assertIn(':root:not([data-theme="light"])', rendered)
        self.assertNotIn("<script", rendered.casefold())
        self.assertNotIn('<link rel="stylesheet"', rendered.casefold())
        self.assertEqual(source_before, (self.directory / "source.html").read_bytes())
        self.assertEqual(markdown_before, (self.directory / "content.md").read_bytes())
        self.assertTrue(result["content_preserved"])

        metadata = json.loads((self.directory / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual("adaptive-reader-v1", metadata["reader_template"])
        self.assertEqual("火山观测志", metadata["reader_theme"])
        job = read_job(self.directory)
        self.assertTrue(job["summary"]["html_design"]["content_preserved"])
        by_name = {item["filename"]: item for item in job["files"]}
        self.assertEqual(
            (self.directory / "index.html").stat().st_size,
            by_name["index.html"]["size_bytes"],
        )
        self.assertEqual(
            (self.directory / "metadata.json").stat().st_size,
            by_name["metadata.json"]["size_bytes"],
        )

    def test_rejects_ambiguous_multi_web_job(self) -> None:
        job = read_job(self.directory)
        duplicate = dict(job["files"][0])
        duplicate["resource_id"] = "res_other"
        job["files"].append(duplicate)
        with self.assertRaises(DomainError) as context:
            design_context(self.directory, job)
        self.assertEqual("FEATURE_NOT_SUPPORTED", context.exception.code)

    def test_rejects_low_contrast_and_arbitrary_fields(self) -> None:
        low_contrast = _spec()
        low_contrast["light_palette"] = {
            **_palette(),
            "text": "#F7FAFC",
        }
        with self.assertRaises(DomainError) as contrast:
            render_design(self.directory, read_job(self.directory), low_contrast)
        self.assertEqual("INVALID_ARGUMENT", contrast.exception.code)

        arbitrary = _spec()
        arbitrary["custom_css"] = "body { display: none }"
        with self.assertRaises(DomainError) as custom:
            render_design(self.directory, read_job(self.directory), arbitrary)
        self.assertEqual("INVALID_ARGUMENT", custom.exception.code)


if __name__ == "__main__":
    unittest.main()
