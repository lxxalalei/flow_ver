"""SmartEdu textbook expansion through the current Resource/Expand route."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from education_resource_mcp.adapters.expansion import expand_resource
from education_resource_mcp.config import Settings
from education_resource_mcp.expand import read_expand, run_expand, start_expand
from education_resource_mcp.service import ResourceService


TEXTBOOK_URL = (
    "https://basic.smartedu.cn/tchMaterial/detail?"
    "contentType=teaching_material&contentId=mid_test"
    "&catalogType=tchMaterial&subCatalog=tchMaterial"
)


def _not_found(url: str) -> HTTPError:
    return HTTPError(url, 404, "not found", {}, None)


class _SmartEduAdapter:
    platform_id = "smartedu"
    timeout = 3.0

    @staticmethod
    def _build_headers() -> dict[str, str]:
        return {"Accept": "application/json"}


class _Provider:
    def __init__(self, adapter: object) -> None:
        self._adapters = {"smartedu": adapter}

    def search(self, search_tasks, limit):
        return [], []


class _NoopSpawner:
    def submit(self, job_id, spawn):
        pass

    def is_pending(self, job_id):
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


def _target() -> dict:
    return {
        "platform": "smartedu",
        "title": "一年级语文上册",
        "source_url": TEXTBOOK_URL,
        "resource_type": "textbook",
        "metadata": {
            "platform_signals": {
                "subject": "语文",
                "grade": "一年级",
                "volume": "上册",
                "version": "统编版",
                "edition": "新教材",
                "stage": "小学",
            }
        },
    }


class SmartEduTextbookIteratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _SmartEduAdapter()
        self.provider = _Provider(self.adapter)

    def test_routes_page_backed_types_and_reports_every_other_item(self) -> None:
        pages = {
            100: [
                {"id": "course_1", "title": "同步课", "resource_type_code": "national_lesson"},
                {"id": "elite_1", "title": "精品课", "resource_type_code": "elite_lesson"},
                {"id": "sing_1", "title": "朗读", "resource_type_code": "singing"},
                {"id": "other_1", "title": "新类型", "resource_type_code": "future_type"},
                {"id": "", "title": "损坏项", "resource_type_code": "national_lesson"},
                "invalid",
            ]
        }

        def fetch(adapter, url, headers):
            del adapter, headers
            part = int(url.rsplit("part_", 1)[1].split(".", 1)[0])
            if part not in pages:
                raise _not_found(url)
            return pages[part]

        summary: dict = {}
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_cdn_json",
            side_effect=fetch,
        ):
            resources = list(expand_resource(self.provider, _target(), summary=summary))

        self.assertEqual(2, len(resources))
        self.assertIn("activityId=course_1", resources[0]["source_url"])
        self.assertIn("qualityCourse?courseId=elite_1", resources[1]["source_url"])
        signals = resources[0]["metadata"]["platform_signals"]
        self.assertEqual("新教材", signals["edition"])
        self.assertEqual("上册", signals["volume"])

        report = summary["smartedu"]
        self.assertEqual(
            {
                "national_lesson": 1,
                "elite_lesson": 1,
                "singing": 1,
                "future_type": 1,
            },
            report["resource_counts"],
        )
        self.assertEqual({"singing": 1, "future_type": 1}, report["skipped_types"])
        self.assertEqual(2, report["invalid_items"])
        self.assertEqual("not_found", report["termination"])

    def test_reads_successive_shards_until_real_404(self) -> None:
        seen: list[int] = []

        def fetch(adapter, url, headers):
            del adapter, headers
            part = int(url.rsplit("part_", 1)[1].split(".", 1)[0])
            seen.append(part)
            if part == 100:
                return [{"id": "a", "title": "第一片", "resource_type_code": "national_lesson"}]
            if part == 101:
                return [{"id": "b", "title": "第二片", "resource_type_code": "elite_lesson"}]
            raise _not_found(url)

        summary: dict = {}
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_cdn_json",
            side_effect=fetch,
        ):
            resources = list(expand_resource(self.provider, _target(), summary=summary))

        self.assertEqual([100, 101, 102], seen)
        self.assertEqual(2, len(resources))
        self.assertEqual(2, summary["smartedu"]["parts_read"])

    def test_non_404_failure_is_not_treated_as_complete(self) -> None:
        failure = HTTPError("https://cdn.invalid", 503, "unavailable", {}, None)
        summary: dict = {}
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_cdn_json",
            side_effect=failure,
        ):
            with self.assertRaises(HTTPError):
                list(expand_resource(self.provider, _target(), summary=summary))
        self.assertEqual("error", summary["smartedu"]["termination"])


class SmartEduTextbookJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=1,
            ),
            search_provider=_Provider(_SmartEduAdapter()),
            job_runner=_NoopSpawner(),
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self.tmp.cleanup()

    def test_job_exposes_skipped_binding_census_without_fake_urls(self) -> None:
        def fetch(adapter, url, headers):
            del adapter, headers
            if "part_100.json" in url:
                return [
                    {"id": "sing_1", "title": "朗读", "resource_type_code": "singing"},
                ]
            raise _not_found(url)

        started = start_expand(self.service, source_url=TEXTBOOK_URL)
        directory = self.root / "jobs" / started["job_id"]
        with mock.patch(
            "education_resource_mcp.adapters.expansion._smartedu_cdn_json",
            side_effect=fetch,
        ):
            self.assertEqual(0, run_expand(directory, self.service))

        status = self.service.job_status(started["job_id"])
        page = read_expand(self.service, started["job_id"], limit=20)
        self.assertEqual("succeeded", status["status"])
        self.assertEqual(0, page["total"])
        self.assertEqual([], page["items"])
        self.assertEqual(
            {"singing": 1},
            status["summary"]["smartedu"]["skipped_types"],
        )
        self.assertEqual(status["summary"], page["summary"])


if __name__ == "__main__":
    unittest.main()
