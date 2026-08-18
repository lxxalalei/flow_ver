"""Known URL import must preserve active platform identity."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import InspectionResult, InspectionRouter
from education_resource_mcp.service import ResourceService


class _ProbeInspector:
    def __init__(self, platform_id: str, seen: list[str]) -> None:
        self.platform_id = platform_id
        self.seen = seen

    def inspect(self, resource: dict) -> InspectionResult:
        self.seen.append(str(resource.get("platform")))
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": f"{self.platform_id} imported resource",
                "resource_type": "video" if self.platform_id == "bilibili" else "article",
                "availability": {"status": "available"},
                "representations": [],
                "metadata": {},
            },
            inspection={},
            failures=[],
        )


class _NoopSpawner:
    def submit(self, job_id, spawn):
        pass

    def is_pending(self, job_id):
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


class ImportUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.seen: list[str] = []
        router = InspectionRouter(
            tuple(
                _ProbeInspector(platform, self.seen)
                for platform in ("generic", "bilibili", "zhihu", "smartedu")
            )
        )
        self.service = ResourceService(
            settings=Settings(
                data_dir=root,
                jobs_dir=root / "jobs",
                library_dir=root / "library",
                max_workers=1,
            ),
            inspection_router=router,
            job_runner=_NoopSpawner(),
        )

    def tearDown(self) -> None:
        self.service.shutdown()
        self.temp.cleanup()

    def test_known_platform_urls_route_to_specialized_inspector(self) -> None:
        cases = {
            "https://www.bilibili.com/video/BV1xx411c7mD": "bilibili",
            "https://www.zhihu.com/question/1/answer/2": "zhihu",
            "https://basic.smartedu.cn/tchMaterial/detail?contentId=abc": "smartedu",
            "https://example.org/some/article": "generic",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                result = self.service.import_url(url)
                resource = self.service._get_resource(result["resource_id"])
                self.assertEqual(expected, resource["platform"])
                self.assertEqual(expected, self.seen[-1])

    def test_invalid_url_rejected_loudly(self) -> None:
        for bad in ("", "not-a-url", "ftp://example.org/x", "javascript:alert(1)"):
            with self.assertRaises(DomainError) as ctx:
                self.service.import_url(bad)
            self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
