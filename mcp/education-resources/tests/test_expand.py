"""Targeted tests for the generic resource_expand capability."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from education_resource_mcp.config import Settings
from education_resource_mcp.expand import read_expand, run_expand, start_expand
from education_resource_mcp.service import ResourceService


class _FakeBilibili:
    platform_id = "bilibili"

    @staticmethod
    def _video(index: int) -> dict:
        return {
            "platform": "bilibili",
            "title": f"video {index}",
            "source_url": f"https://www.bilibili.com/video/BV{index:010d}",
            "resource_type": "视频",
            "metadata": {},
        }

    def iter_creator(self, creator_id: str, *, cancel_event=None):
        self.creator_id = creator_id
        yield self._video(1)
        yield self._video(2)

    def iter_collection(self, source_url: str, *, cancel_event=None):
        self.collection_url = source_url
        yield self._video(3)
        yield self._video(4)


class _FakeDouyin:
    platform_id = "douyin"

    @staticmethod
    def _video(index: int) -> dict:
        return {
            "platform": "douyin",
            "title": f"douyin {index}",
            "source_url": f"https://www.douyin.com/video/{100 + index}",
            "resource_type": "视频",
            "metadata": {},
        }

    def iter_creator(self, creator_id: str, *, cancel_event=None):
        self.creator_id = creator_id
        yield self._video(1)

    def iter_collection(self, source_url: str, *, cancel_event=None):
        self.collection_url = source_url
        yield self._video(2)
        yield self._video(3)


class _Provider:
    def __init__(self, adapters: dict[str, object]) -> None:
        self._adapters = adapters

    def search(self, search_tasks, limit):
        return [], []


class _NoopSpawner:
    def submit(self, job_id, spawn):
        pass

    def is_pending(self, job_id):
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


class ExpandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bilibili = _FakeBilibili()
        self.douyin = _FakeDouyin()
        self.service = ResourceService(
            settings=Settings(
                data_dir=self.root,
                jobs_dir=self.root / "jobs",
                library_dir=self.root / "library",
                max_workers=1,
            ),
            search_provider=_Provider({
                "bilibili": self.bilibili,
                "douyin": self.douyin,
            }),
            job_runner=_NoopSpawner(),
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self.tmp.cleanup()

    def _run(self, result: dict) -> dict:
        directory = self.root / "jobs" / result["job_id"]
        self.assertEqual(0, run_expand(directory, self.service))
        return read_expand(self.service, result["job_id"], limit=50)

    def test_creator_url_expands_to_all_videos(self) -> None:
        result = start_expand(
            self.service,
            source_url="https://space.bilibili.com/42",
        )
        page = self._run(result)
        self.assertEqual("succeeded", page["status"])
        self.assertEqual(2, page["total"])
        self.assertEqual(
            ["video 1", "video 2"],
            [item["title"] for item in page["items"]],
        )
        self.assertEqual(
            "https://space.bilibili.com/42",
            self.bilibili.creator_id,
        )

    def test_collection_url_uses_collection_expander(self) -> None:
        url = "https://space.bilibili.com/42/lists/99?type=season"
        page = self._run(start_expand(self.service, source_url=url))
        self.assertEqual(
            ["video 3", "video 4"],
            [item["title"] for item in page["items"]],
        )
        self.assertEqual(url, self.bilibili.collection_url)

    def test_douyin_collection_expands_to_videos(self) -> None:
        url = "https://www.douyin.com/collection/123"
        page = self._run(start_expand(self.service, source_url=url))
        self.assertEqual("succeeded", page["status"])
        self.assertEqual(2, page["total"])
        self.assertEqual(
            ["douyin 2", "douyin 3"],
            [item["title"] for item in page["items"]],
        )
        self.assertEqual(url, self.douyin.collection_url)

    def test_leaf_video_never_expands_to_creator_even_with_creator_fact(self) -> None:
        remembered = self.service._remember_resources([{
            "platform": "bilibili",
            "title": "one video",
            "source_url": "https://www.bilibili.com/video/BV0000000001",
            "resource_type": "视频",
            "metadata": {"creator_mid": "777"},
        }])
        result = start_expand(
            self.service,
            resource_id=remembered[0]["resource_id"],
        )
        directory = self.root / "jobs" / result["job_id"]
        run_expand(directory, self.service)
        status = self.service.job_status(result["job_id"])
        self.assertEqual("failed", status["status"])
        self.assertEqual(
            "FEATURE_NOT_SUPPORTED",
            status["failures"][0]["code"],
        )

    def test_leaf_video_is_not_silently_reinterpreted(self) -> None:
        remembered = self.service._remember_resources([{
            "platform": "bilibili",
            "title": "leaf",
            "source_url": "https://www.bilibili.com/video/BV0000000002",
            "resource_type": "视频",
            "metadata": {},
        }])
        result = start_expand(
            self.service,
            resource_id=remembered[0]["resource_id"],
        )
        directory = self.root / "jobs" / result["job_id"]
        run_expand(directory, self.service)
        status = self.service.job_status(result["job_id"])
        self.assertEqual("failed", status["status"])
        self.assertEqual(
            "FEATURE_NOT_SUPPORTED",
            status["failures"][0]["code"],
        )


if __name__ == "__main__":
    unittest.main()
