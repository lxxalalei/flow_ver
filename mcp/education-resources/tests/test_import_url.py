"""resource_import_url: host-side URL discovery bridged into the MCP pipeline."""

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
from education_resource_mcp.inspection import InspectionResult, InspectionRouter
from education_resource_mcp.service import ResourceService


class _PageInspector:
    """Offline inspector that fetches nothing and reports a static page."""

    platform_id = "generic"

    def inspect(self, resource: dict) -> InspectionResult:
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": "外部发现的页面标题",
                "resource_type": "article",
                "availability": {"status": "available"},
                "representations": [
                    {
                        "representation_id": "repr_page",
                        "scope": "primary_resource",
                        "kind": "webpage",
                        "container": "html",
                        "role": "primary",
                        "materializable": True,
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection={},
            failures=[],
        )


class _NoopSpawner:
    def submit(self, job_id, spawn):  # noqa: ANN001
        pass

    def is_pending(self, job_id):  # noqa: ANN001
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass


class ImportUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        router = InspectionRouter((_PageInspector(),))
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
        self._tmp.cleanup()

    def test_import_returns_handle_with_inspection(self) -> None:
        result = self.service.import_url("https://example.org/some/article")
        self.assertTrue(result["resource_id"].startswith("res_"))
        self.assertEqual("available", result["resource"]["availability"]["status"])
        (rep,) = result["resource"]["representations"]
        self.assertEqual("webpage", rep["kind"])
        self.assertTrue(rep["materializable"])
        # title backfilled from inspection
        self.assertEqual("外部发现的页面标题", result["resource"]["title"])

    def test_imported_handle_is_usable(self) -> None:
        result = self.service.import_url("https://example.org/a")
        resource = self.service._get_resource(result["resource_id"])
        self.assertEqual("https://example.org/a", resource["source_url"])

    def test_invalid_url_rejected_loudly(self) -> None:
        for bad in ("", "not-a-url", "ftp://example.org/x", "javascript:alert(1)"):
            with self.assertRaises(DomainError) as ctx:
                self.service.import_url(bad)
            self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
