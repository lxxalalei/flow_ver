"""Guard rails for creator_id: format validation + resource_id closed loop.

Real incident 2026-08-17: a truncated douyin sec_user_id (copied from
truncated output) produced a silent empty enumeration.  These tests pin
the loud rejection and the machine-to-machine path.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.service import ResourceService


class _RecordingProvider:
    def __init__(self) -> None:
        self.creator_calls: list[tuple[str, str, int]] = []

    def search(self, search_tasks, limit):
        return [], []

    def search_creator(self, platform, creator_id, limit, cancel_event=None):
        self.creator_calls.append((platform, creator_id, limit))
        return [], []


class _NoopSpawner:
    def submit(self, job_id, spawn):  # noqa: ANN001
        pass

    def is_pending(self, job_id):  # noqa: ANN001
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


def _service(root: Path) -> ResourceService:
    return ResourceService(
        settings=Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=1,
        ),
        search_provider=_RecordingProvider(),
        job_runner=_NoopSpawner(),
    )


def _request_creator_id(service: ResourceService, job_id: str) -> str:
    import json

    request = json.loads(
        (service.settings.jobs_dir / job_id / "request.json").read_text(encoding="utf-8")
    )
    return request["creator_id"]


class CreatorIdGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.service = _service(self.root)

    def tearDown(self) -> None:
        self.service.shutdown()
        self._tmp.cleanup()

    def test_truncated_douyin_id_rejected_loudly(self) -> None:
        # the exact truncated value from the 2026-08-17 incident
        with self.assertRaises(DomainError) as ctx:
            self.service.batch_collect(
                "douyin",
                mode="creator_full",
                creator_id="MS4wLjABAAAA0JOY3ZvG349SJEpdMn",
            )
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        self.assertIn("疑似不完整", ctx.exception.message)

    def test_wrong_prefix_douyin_rejected(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.browse_creator("douyin", "MS4wLjXx12345")
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)
        self.assertIn("MS4wLjAB", ctx.exception.message)

    def test_non_numeric_bilibili_rejected(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            self.service.batch_collect(
                "bilibili", mode="creator_full", creator_id="abc123"
            )
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)

    def test_full_douyin_id_accepted(self) -> None:
        full = "MS4wLjABAAAA0JOY3ZvG349SJEpdMnka-6PQ7ZqfOQjoVGnv7X7rcasA97VQsEw6380VFNYKNMsK"
        result = self.service.batch_collect("douyin", mode="creator_full", creator_id=full)
        self.assertTrue(result["job_id"].startswith("job_"))
        self.assertEqual(full, _request_creator_id(self.service, result["job_id"]))

    def test_resource_id_closed_loop(self) -> None:
        # register a candidate with the full creator id
        resource_id = "res_" + "2" * 32
        full = "MS4wLjABAAAA0JOY3ZvG349SJEpdMnka-6PQ7ZqfOQjoVGnv7X7rcasA97VQsEw6380VFNYKNMsK"
        self.service._resources[resource_id] = {
            "resource_id": resource_id,
            "platform": "douyin",
            "title": "候选作品",
            "source_url": "https://www.douyin.com/video/123",
            "resource_type": "video",
            "metadata": {"creator_sec_uid": full},
        }
        result = self.service.batch_collect(
            "douyin", mode="creator_full", creator_id=resource_id
        )
        self.assertTrue(result["job_id"].startswith("job_"))
        self.assertEqual(full, _request_creator_id(self.service, result["job_id"]))

    def test_resource_without_creator_rejected(self) -> None:
        resource_id = "res_" + "3" * 32
        self.service._resources[resource_id] = {
            "resource_id": resource_id,
            "platform": "douyin",
            "title": "无作者",
            "source_url": "https://www.douyin.com/video/456",
            "resource_type": "video",
            "metadata": {},
        }
        with self.assertRaises(DomainError) as ctx:
            self.service.batch_collect(
                "douyin", mode="creator_full", creator_id=resource_id
            )
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
