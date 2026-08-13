"""Tests for resource_flow_list — flow discovery after context loss."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from education_resource_mcp.service import ResourceService  # noqa: E402


def _settings(data_dir: Path):
    from education_resource_mcp.config import Settings

    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
    )


class FlowListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self.temp.name))
        self.svc = ResourceService(settings=self.settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _start(self, topic: str) -> str:
        import hashlib
        short = hashlib.sha256(topic.encode()).hexdigest()[:16]
        result = self.svc.flow_start(f"key.{short}.123456", {"goal": {"topic": topic}})
        return result["flow_id"]

    def test_empty_database_returns_empty_list(self) -> None:
        result = self.svc.flow_list()
        self.assertEqual(0, result["count"])
        self.assertEqual([], result["flows"])

    def test_lists_flows_ordered_by_updated_desc(self) -> None:
        flow_a = self._start("数学练习")
        flow_b = self._start("唐诗音频")
        flow_c = self._start("英语启蒙")

        result = self.svc.flow_list()
        ids = [f["flow_id"] for f in result["flows"]]

        self.assertEqual(3, result["count"])
        # Most recently created/updated first
        self.assertEqual([flow_c, flow_b, flow_a], ids)

    def test_each_flow_has_query_and_status(self) -> None:
        self._start("Python入门")

        result = self.svc.flow_list()
        flow = result["flows"][0]
        self.assertEqual("Python入门", flow["query"])
        self.assertIn("status", flow)
        self.assertIn("created_at", flow)
        self.assertIn("updated_at", flow)

    def test_limit_caps_results(self) -> None:
        for i in range(5):
            self._start(f"topic-{i}")

        result = self.svc.flow_list(limit=3)
        self.assertEqual(3, result["count"])
        self.assertEqual(3, len(result["flows"]))

    def test_invalid_limit_defaults_to_20(self) -> None:
        self._start("topic")
        # limit=0 or negative should not crash
        result = self.svc.flow_list(limit=0)
        self.assertEqual(1, result["count"])


if __name__ == "__main__":
    unittest.main()
