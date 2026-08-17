"""0057 M4b: catalog_expand batch mode (SmartEdu CDN textbook discovery)."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.batch import run_batch_collect
from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.service import ResourceService


class _FakeSmartedu:
    platform_id = "smartedu"

    def __init__(self) -> None:
        self.specs_seen: list[list[str]] = []

    def discover_textbook_courses(self, specs: list[str]):
        self.specs_seen.append(specs)
        return [
            {"id": f"course_{i}", "title": f"课文{i}", "textbook": "语文 一年级 上册"}
            for i in range(3)
        ]


class _Provider:
    def __init__(self, adapters: dict[str, object]) -> None:
        self._adapters = adapters

    def search(self, search_tasks, limit):
        return [], []

    def search_creator(self, *a, **k):
        return [], []


class _NoopSpawner:
    def submit(self, job_id, spawn):  # noqa: ANN001
        pass

    def is_pending(self, job_id):  # noqa: ANN001
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


def _service(root: Path, adapter: object) -> ResourceService:
    return ResourceService(
        settings=Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=1,
        ),
        search_provider=_Provider({"smartedu": adapter}),
        job_runner=_NoopSpawner(),
    )


class CatalogExpandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.smartedu = _FakeSmartedu()
        self.service = _service(self.root, self.smartedu)

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_catalog_expand_produces_course_list(self) -> None:
        result = self.service.batch_collect(
            "smartedu",
            mode="catalog_expand",
            specs=["语文/一年级/上册/统编版"],
        )
        directory = self.root / "jobs" / result["job_id"]
        run_batch_collect(directory, self.service)
        status = self.service.job_status(result["job_id"])
        self.assertEqual("succeeded", status["status"])
        self.assertEqual(3, status["progress"]["completed"])
        self.assertEqual(["语文/一年级/上册/统编版"], self.smartedu.specs_seen[-1])

        page = self.service.batch_read(result["job_id"], limit=10)
        self.assertEqual(3, len(page["items"]))
        first = page["items"][0]
        self.assertEqual("课文0", first["title"])
        self.assertEqual("course_0", first["activity_id"])
        self.assertTrue(first["url"].startswith(
            "https://basic.smartedu.cn/syncClassroom/classActivity?activityId="
        ))

    def test_missing_specs_rejected_loudly(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.batch_collect("smartedu", mode="catalog_expand")
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)

    def test_wrong_platform_fails_honestly(self) -> None:
        service = _service(self.root, object())
        try:
            result = service.batch_collect(
                "bilibili", mode="catalog_expand", specs=["语文/一年级"]
            )
            directory = self.root / "jobs" / result["job_id"]
            run_batch_collect(directory, service)
            status = service.job_status(result["job_id"])
            self.assertEqual("failed", status["status"])
            self.assertEqual("FEATURE_NOT_SUPPORTED", status["failures"][0]["code"])
        finally:
            service.shutdown()


if __name__ == "__main__":
    unittest.main()
