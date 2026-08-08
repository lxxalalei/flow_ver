"""Offline regression tests for SmartEdu multi-asset semantics."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadBatchResult, DownloadResult
from education_resource_mcp.errors import DomainError
from education_resource_mcp.adapters.smartedu_download import (
    SmartEduDownloader,
    _find_files,
)


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        database_path=root / "database.sqlite",
        jobs_dir=root / "jobs",
        library_dir=root / "library",
        max_download_bytes=1024 * 1024,
        max_search_results=20,
        max_workers=2,
        plan_ttl_seconds=60,
    )


class _SessionStore:
    def __init__(self, token: str = "") -> None:
        self.token = token

    def get_session_data(self, platform: str) -> dict:
        if not self.token:
            return {}
        return {"tokens": {"accessToken": self.token}}


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _item(
    item_id: str,
    url: str,
    fmt: str,
    flag: str,
    *,
    size: int = 16,
    title: str = "课程资源",
) -> dict:
    return {
        "id": item_id,
        "ti_storage": url,
        "ti_format": fmt,
        "ti_file_flag": flag,
        "ti_size": size,
        "title": title,
    }


def _course_detail(*, with_video: bool = True) -> dict:
    items = []
    if with_video:
        items.append(
            _item(
                "video-1",
                "https://cdn.example.test/course/video.m3u8?accessToken=secret-token",
                "m3u8",
                "href-720p-m3u8",
                title="课程视频",
            )
        )
    items.extend(
        [
            _item(
                "handout-1",
                "https://cdn.example.test/course/handout.pdf?accessToken=secret-token",
                "pdf",
                "source",
                title="课程讲义",
            ),
            _item(
                "audio-1",
                "https://cdn.example.test/course/audio.mp3?accessToken=secret-token",
                "mp3",
                "source",
                title="课程音频",
            ),
        ]
    )
    return {
        "relations": {
            "course_resource": [
                {
                    "id": "lesson-1",
                    "global_title": "课程资源",
                    "ti_items": items,
                }
            ]
        }
    }


def _document_detail() -> dict:
    return {
        "global_title": "英语教材",
        "ti_items": [
            _item(
                "book-docx",
                "https://cdn.example.test/book/book.docx?accessToken=secret-token",
                "docx",
                "source",
                size=8,
                title="教材文档",
            ),
            _item(
                "book-pdf",
                "https://cdn.example.test/book/book.pdf?accessToken=secret-token",
                "pdf",
                "source",
                size=16,
                title="教材 PDF",
            ),
        ],
    }


def _batch_parts(value: object) -> tuple[list[DownloadResult], list[object]]:
    if isinstance(value, DownloadBatchResult):
        return list(value.results), list(value.failures)
    if isinstance(value, DownloadResult):
        return [value], []
    raise AssertionError(f"unexpected SmartEdu result: {type(value)!r}")


class SmartEduBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = _settings(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _downloader(self, token: str = "") -> SmartEduDownloader:
        return SmartEduDownloader(_SessionStore(token), self.settings)  # type: ignore[arg-type]

    def _download(
        self,
        detail: dict,
        *,
        source_url: str = "https://basic.smartedu.cn/qualityCourse?courseId=course-1",
        audio: list[dict] | None = None,
        stream_failure_formats: set[str] | None = None,
        cancel_on_format: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> object:
        stream_failure_formats = stream_failure_formats or set()
        cancel_event = cancel_event or threading.Event()

        def fake_open(request, timeout):  # type: ignore[no-untyped-def]
            if "relation_audios" in request.full_url:
                return _Response(audio or [])
            return _Response(detail)

        def fake_stream(url, destination, event, max_bytes, token):  # type: ignore[no-untyped-def]
            fmt = Path(destination).suffix.lstrip(".")
            if fmt in stream_failure_formats:
                raise DomainError(
                    "DOWNLOAD_FAILED",
                    "upstream failed at https://cdn.example.test/private?token=secret-token",
                    retryable=True,
                )
            if cancel_on_format == fmt:
                event.set()
                raise DomainError("JOB_CANCELLED", "cancelled")
            Path(destination).write_bytes((fmt or "file").encode("ascii"))

        def fake_m3u8(url, destination, event, token):  # type: ignore[no-untyped-def]
            if "m3u8" in stream_failure_formats:
                raise DomainError(
                    "DOWNLOAD_FAILED",
                    "video failed at https://cdn.example.test/private?accessToken=secret-token",
                    retryable=True,
                )
            if cancel_on_format == "m3u8":
                event.set()
                raise DomainError("JOB_CANCELLED", "cancelled")
            Path(destination).write_bytes(b"video")

        with (
            patch(
                "education_resource_mcp.adapters.smartedu_download.urlopen_with_fallback",
                side_effect=fake_open,
            ),
            patch(
                "education_resource_mcp.adapters.smartedu_download._stream_download",
                side_effect=fake_stream,
            ),
            patch(
                "education_resource_mcp.adapters.smartedu_download._download_m3u8",
                side_effect=fake_m3u8,
            ),
        ):
            return self._downloader("test-token").download(
                {
                    "source_url": source_url,
                    "title": "固定夹具资源",
                    "platform": "smartedu",
                },
                "job-1",
                "direct",
                1024,
                cancel_event,
            )

    def test_course_complete_has_video_primary_and_ordered_companions(self) -> None:
        raw = self._download(_course_detail())
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual(["primary", "attachment", "companion"], [item.role for item in results])
        self.assertEqual([True, False, False], [item.required for item in results])
        self.assertEqual(
            [0, 1, 2],
            [item.metadata["source_order"] for item in results],
        )

    def test_course_partial_preserves_item_failure_without_secrets(self) -> None:
        raw = self._download(_course_detail(), stream_failure_formats={"pdf"})
        results, failures = _batch_parts(raw)

        self.assertEqual(2, len(results))
        self.assertEqual(1, len(failures))
        failure = failures[0]
        self.assertEqual("DOWNLOAD_FAILED", failure.code)
        self.assertEqual("attachment", failure.role)
        self.assertFalse(failure.required)
        serialized = json.dumps(failure.to_dict(), ensure_ascii=False)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("/private", serialized)

    def test_course_primary_failure_is_retained_and_not_downgraded_to_success(self) -> None:
        raw = self._download(_course_detail(), stream_failure_formats={"m3u8"})
        results, failures = _batch_parts(raw)

        self.assertEqual(2, len(results))
        self.assertEqual(1, len(failures))
        self.assertEqual("primary", failures[0].role)
        self.assertTrue(failures[0].required)
        self.assertEqual("DOWNLOAD_FAILED", failures[0].code)

    def test_textbook_pdf_is_primary_and_relation_audio_is_companion(self) -> None:
        audio = [
            {
                "id": "relation-audio-1",
                "global_title": "教材听力",
                "ti_items": [
                    _item(
                        "audio-1",
                        "https://cdn.example.test/book/audio.mp3?token=secret-token",
                        "mp3",
                        "href",
                        title="听力音频",
                    )
                ],
            }
        ]
        raw = self._download(
            _document_detail(),
            source_url=(
                "https://basic.smartedu.cn/tchMaterial/detail?"
                "contentType=assets_document&contentId=book-1"
            ),
            audio=audio,
        )
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual(2, len(results))
        self.assertEqual("primary", results[0].role)
        self.assertEqual("application/pdf", results[0].media_type)
        self.assertEqual("companion", results[1].role)
        self.assertEqual("relation_audios", results[1].metadata["relation_key"])

    def test_find_files_preserves_facts_and_redacts_metadata(self) -> None:
        detail = _course_detail()
        first = _find_files(detail)
        second = _find_files(detail)

        self.assertEqual([0, 1, 2], [item["source_order"] for item in first])
        self.assertEqual([item["item_key"] for item in first], [item["item_key"] for item in second])
        self.assertEqual("course_resource", first[0]["relation_key"])
        self.assertEqual("href-720p-m3u8", first[0]["ti_file_flag"])
        self.assertEqual("m3u8", first[0]["format"])
        metadata = json.dumps([item["metadata"] for item in first], ensure_ascii=False)
        self.assertNotIn("https://", metadata)
        self.assertNotIn("secret-token", metadata)

    def test_cancel_aborts_whole_acquisition_and_cleans_prior_results(self) -> None:
        cancel_event = threading.Event()
        with self.assertRaises(DomainError) as context:
            self._download(
                _course_detail(),
                cancel_on_format="pdf",
                cancel_event=cancel_event,
            )
        self.assertEqual("JOB_CANCELLED", context.exception.code)
        self.assertFalse((self.settings.jobs_dir / "job-1" / "课程资源.mp4").exists())
        self.assertFalse(any((self.settings.jobs_dir / "job-1").glob("*")))


if __name__ == "__main__":
    unittest.main()
