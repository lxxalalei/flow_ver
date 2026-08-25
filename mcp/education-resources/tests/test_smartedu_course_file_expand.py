"""SmartEdu course files as stable logical child resources."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters.expansion import expand_resource
from education_resource_mcp.config import Settings
from education_resource_mcp.expand import read_expand, run_expand, start_expand
from education_resource_mcp.service import ResourceService


SOURCE_URL = "https://basic.smartedu.cn/qualityCourse?courseId=course-1"


def _item(item_id: str | None, filename: str, fmt: str, token: str) -> dict:
    item = {
        "ti_storage": f"https://r1-ndr.ykt.cbern.com.cn/{filename}?accessToken={token}",
        "ti_format": fmt,
        "ti_file_flag": "source",
        "ti_size": 1024,
        "title": filename,
    }
    if item_id is not None:
        item["id"] = item_id
    return item


def _detail(token: str, *, reverse: bool = False, unstable: bool = False) -> dict:
    items = [
        _item("video-mp4", "lesson.mp4", "mp4", token),
        _item("handout", "handout.pdf", "pdf", token),
        _item("audio", "audio.mp3", "mp3", token),
    ]
    if unstable:
        items.append(_item(None, "anonymous.pdf", "pdf", token))
    if reverse:
        items.reverse()
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


class _Provider:
    def __init__(self) -> None:
        self._adapters = {"smartedu": object()}


class _NoopSpawner:
    def submit(self, job_id, spawn) -> None:  # type: ignore[no-untyped-def]
        pass

    def is_pending(self, job_id) -> bool:  # type: ignore[no-untyped-def]
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


def _target() -> dict:
    return {
        "platform": "smartedu",
        "title": "课程",
        "source_url": SOURCE_URL,
        "resource_type": "course",
        "metadata": {},
    }


class SmartEduCourseFileExpandTests(unittest.TestCase):
    def test_file_keys_ignore_signed_urls_and_detail_order(self) -> None:
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_course_detail",
            return_value=("course-1", "quality_course", _detail("first")),
        ):
            first = list(expand_resource(_Provider(), _target()))
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_course_detail",
            return_value=(
                "course-1",
                "quality_course",
                _detail("second", reverse=True),
            ),
        ):
            second = list(expand_resource(_Provider(), _target()))

        first_keys = {
            item["title"]: item["metadata"]["platform_signals"]["file_key"]
            for item in first
        }
        second_keys = {
            item["title"]: item["metadata"]["platform_signals"]["file_key"]
            for item in second
        }
        self.assertEqual(first_keys, second_keys)
        self.assertEqual(3, len(first_keys))
        self.assertEqual({SOURCE_URL}, {item["source_url"] for item in first})
        self.assertNotIn("accessToken", repr(first))

    def test_unstable_file_is_reported_but_not_emitted(self) -> None:
        summary: dict = {}
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_course_detail",
            return_value=(
                "course-1",
                "quality_course",
                _detail("secret", unstable=True),
            ),
        ):
            resources = list(
                expand_resource(_Provider(), _target(), summary=summary)
            )

        self.assertEqual(3, len(resources))
        self.assertEqual(1, summary["smartedu"]["unstable_files"])
        self.assertEqual(3, summary["smartedu"]["emitted"])

    def test_expand_job_keeps_same_course_url_with_distinct_file_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            settings = Settings(
                data_dir=root,
                jobs_dir=root / "jobs",
                library_dir=root / "library",
                max_workers=1,
            )
            service = ResourceService(
                settings=settings,
                search_provider=_Provider(),
                job_runner=_NoopSpawner(),
            )
            try:
                remembered_course = service._remember_resources([_target()])  # noqa: SLF001
                started = start_expand(
                    service,
                    resource_id=remembered_course[0]["resource_id"],
                )
                with mock.patch(
                    "education_resource_mcp.adapters.expansion._smartedu_course_detail",
                    return_value=("course-1", "quality_course", _detail("secret")),
                ):
                    directory = settings.jobs_dir / started["job_id"]
                    self.assertEqual(0, run_expand(directory, service))
                page = read_expand(service, started["job_id"], limit=10)
            finally:
                service.shutdown()

        self.assertEqual("succeeded", page["status"])
        self.assertEqual(3, page["total"])
        self.assertEqual(3, len(page["items"]))
        self.assertEqual(3, len({item["resource_id"] for item in page["items"]}))


if __name__ == "__main__":
    unittest.main()
