"""0057 M4: time_range_search batch mode (bilibili day-by-day enumeration)."""

from __future__ import annotations

from datetime import date
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


class _FakeBili:
    platform_id = "bilibili"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.day_count = 3  # fake catalogue spans 3 days

    def search(self, query, limit, *, pubtime_begin_s=0, pubtime_end_s=0):
        from datetime import datetime

        day = datetime.fromtimestamp(pubtime_begin_s).date()
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "begin": day,
                "begin_s": pubtime_begin_s,
                "end_s": pubtime_end_s,
            }
        )
        # every day yields 2 distinct items
        return [
            {
                "platform": "bilibili",
                "title": f"{day} 作品{i}",
                "source_url": f"https://www.bilibili.com/video/BV{day.day}{i}",
                "resource_type": "video",
                "metadata": {},
            }
            for i in (1, 2)
        ], None


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


def _service(root: Path, provider: _Provider) -> ResourceService:
    return ResourceService(
        settings=Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=1,
        ),
        search_provider=provider,
        job_runner=_NoopSpawner(),
    )


class TimeRangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bili = _FakeBili()
        self.service = _service(self.root, _Provider({"bilibili": self.bili}))

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def _run(self, **kwargs) -> str:
        result = self.service.batch_collect("bilibili", **kwargs)
        directory = self.root / "jobs" / result["job_id"]
        run_batch_collect(directory, self.service)
        return result["job_id"]

    def test_iterates_day_by_day_and_dedupes(self) -> None:
        job_id = self._run(
            mode="time_range_search",
            keyword="纪录片",
            start_day="2026-08-01",
            end_day="2026-08-03",
            max_items=50,
        )
        status = self.service.job_status(job_id)
        self.assertEqual("succeeded", status["status"])
        # 3 days x 2 items
        self.assertEqual(6, status["progress"]["completed"])
        begins = sorted(c["begin"] for c in self.bili.calls)
        self.assertEqual(
            [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)], begins
        )
        # day window is one full day inclusive
        self.assertEqual(86399, self.bili.calls[0]["end_s"] - self.bili.calls[0]["begin_s"])
        page = self.service.batch_read(job_id, limit=20)
        self.assertEqual(6, len(page["items"]))
        self.assertTrue(page["complete"])

    def test_dedup_across_days(self) -> None:
        # same URL appears on every day → single item
        original = self.bili.search

        def same_url_every_day(query, limit, *, pubtime_begin_s=0, pubtime_end_s=0):
            return [
                {
                    "platform": "bilibili",
                    "title": "重复",
                    "source_url": "https://www.bilibili.com/video/BVdup",
                    "resource_type": "video",
                    "metadata": {},
                }
            ], None

        self.bili.search = same_url_every_day
        try:
            job_id = self._run(
                mode="time_range_search",
                keyword="x",
                start_day="2026-08-01",
                end_day="2026-08-03",
                max_items=10,
            )
        finally:
            self.bili.search = original
        status = self.service.job_status(job_id)
        self.assertEqual(1, status["progress"]["completed"])

    def test_validation(self) -> None:
        for kwargs in (
            {"mode": "time_range_search", "keyword": "", "start_day": "2026-08-01", "end_day": "2026-08-02"},
            {"mode": "time_range_search", "keyword": "x", "start_day": "", "end_day": "2026-08-02"},
            {"mode": "time_range_search", "keyword": "x", "start_day": "2026-08-03", "end_day": "2026-08-01"},
        ):
            with self.assertRaises(DomainError) as ctx:
                self.service.batch_collect("bilibili", **kwargs)
            self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        # >90 day window rejected
        with self.assertRaises(DomainError):
            self.service.batch_collect(
                "bilibili",
                mode="time_range_search",
                keyword="x",
                start_day="2026-01-01",
                end_day="2026-12-31",
            )

    def test_unsupported_platform_fails_honestly(self) -> None:
        service = _service(self.root, _Provider({}))
        try:
            result = service.batch_collect(
                "douyin",
                mode="time_range_search",
                keyword="x",
                start_day="2026-08-01",
                end_day="2026-08-02",
                max_items=10,
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
