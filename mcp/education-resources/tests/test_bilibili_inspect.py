"""Targeted tests for the Bilibili DASH-verification inspector."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from education_resource_mcp.adapters.inspect_bilibili import BilibiliInspector  # noqa: E402


class BilibiliInspectorTests(unittest.TestCase):
    def _inspector(self, verify_func=None):
        return BilibiliInspector(playurl_verify_func=verify_func)

    def _resource(self, **overrides):
        base = {
            "resource_id": "r1",
            "platform": "bilibili",
            "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "title": "测试视频",
            "metadata": {"bvid": "BV1xx411c7mD"},
        }
        base.update(overrides)
        return base

    def test_verified_dash_produces_materializable_primary(self) -> None:
        def verify(bvid, cookie):
            assert bvid == "BV1xx411c7mD"
            return {"title": "测试视频"}

        inspector = self._inspector(verify)
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        self.assertEqual("resolved", payload["resolution_status"])
        resolved = payload["resolved_resource"]
        self.assertEqual("available", resolved["availability"]["status"])
        primaries = [
            r for r in resolved["representations"]
            if r.get("role") == "primary" and r.get("kind") == "video"
        ]
        self.assertEqual(1, len(primaries))
        self.assertTrue(primaries[0]["materializable"])
        self.assertEqual("mp4", primaries[0]["container"])
        self.assertEqual("primary_resource", primaries[0]["scope"])
        self.assertEqual("available", primaries[0]["technical_availability"])

    def test_verify_failure_falls_back_to_non_materializable(self) -> None:
        def verify(bvid, cookie):
            return None  # DASH not available or API failure

        inspector = self._inspector(verify)
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        videos = [
            r for r in payload["resolved_resource"]["representations"]
            if r.get("kind") == "video"
        ]
        # No materializable primary; at most a non-materializable companion
        for v in videos:
            if v.get("role") == "primary":
                self.assertFalse(v["materializable"])

    def test_result_does_not_leak_stream_url(self) -> None:
        def verify(bvid, cookie):
            return {"title": "t"}

        inspector = self._inspector(verify)
        import json

        payload = inspector.inspect(self._resource()).to_mapping()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("baseUrl", text)
        self.assertNotIn("playUrlList", text)


if __name__ == "__main__":
    unittest.main()
