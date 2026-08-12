"""Targeted tests for the Ximalaya track-verification inspector."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from education_resource_mcp.adapters.inspect_ximalaya import XimalayaInspector  # noqa: E402
from education_resource_mcp.inspection import InspectionResult  # noqa: E402
import hashlib  # noqa: E402


def _repr_id(seed: str) -> str:
    return "repr_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _base_result(*, resource_type: str = "audio") -> InspectionResult:
    """A minimal 'resolved' result that the inspector will enrich."""

    return InspectionResult(
        resolution_status="resolved",
        resolved_resource={
            "title": "测试专辑",
            "resource_type": resource_type,
            "availability": {"status": "unknown"},
            "representations": [
                {
                    "representation_id": _repr_id("base-webpage"),
                    "kind": "webpage",
                    "container": "html",
                    "scope": "primary_resource",
                    "role": "primary",
                    "technical_availability": "unknown",
                    "materializable": False,
                }
            ],
            "metadata": {},
        },
        inspection={
            "inspector_id": "ximalaya",
            "version": "1.0.0",
            "method": "platform_bounded_get",
            "cache_status": "miss",
            "inspected_at": "2026-08-12T00:00:00Z",
            "warnings": [],
        },
    )


class XimalayaTrackInspectorTests(unittest.TestCase):
    def _inspector(self, verify_func=None):
        return XimalayaInspector(
            track_verify_func=verify_func,
        )

    def _track_resource(self, **overrides):
        base = {
            "resource_id": "r1",
            "platform": "ximalaya",
            "source_url": "https://www.ximalaya.com/sound/123456",
            "title": "测试曲目",
        }
        base.update(overrides)
        return base

    def _album_resource(self, **overrides):
        base = {
            "resource_id": "r2",
            "platform": "ximalaya",
            "source_url": "https://www.ximalaya.com/album/654321",
            "title": "测试专辑",
        }
        base.update(overrides)
        return base

    def test_track_url_produces_materializable_primary(self) -> None:
        def verify(track_id, cookie):
            assert track_id == "123456"
            return {"title": "测试曲目", "container": "m4a", "file_size": 1024000}

        inspector = self._inspector(verify)
        result = inspector._enrich(self._track_resource(), _base_result())
        payload = result.to_mapping()
        resolved = payload["resolved_resource"]

        self.assertEqual("available", resolved["availability"]["status"])
        reps = resolved["representations"]
        primary = [r for r in reps if r.get("role") == "primary" and r.get("kind") == "audio"]
        self.assertEqual(1, len(primary))
        self.assertTrue(primary[0]["materializable"])
        self.assertEqual("m4a", primary[0]["container"])
        self.assertEqual("available", primary[0]["technical_availability"])
        self.assertEqual("primary_resource", primary[0]["scope"])
        self.assertEqual(1024000, primary[0].get("size_bytes"))
        self.assertEqual("123456", resolved.get("metadata", {}).get("track_id"))

    def test_album_url_without_track_stays_non_materializable(self) -> None:
        """Album-only candidates must not silently become a track."""

        def verify(track_id, cookie):
            self.fail("should not verify — no track_id for album URL")

        inspector = self._inspector(verify)
        result = inspector._enrich(self._album_resource(), _base_result())
        payload = result.to_mapping()
        resolved = payload["resolved_resource"]

        audio = [r for r in resolved["representations"] if r.get("kind") == "audio"]
        self.assertEqual(1, len(audio))
        self.assertFalse(audio[0]["materializable"])
        self.assertNotEqual("primary_resource", audio[0].get("scope"))

    def test_verify_failure_falls_back_to_non_materializable(self) -> None:
        def verify(track_id, cookie):
            return None  # API failure or VIP-only

        inspector = self._inspector(verify)
        result = inspector._enrich(self._track_resource(), _base_result())
        payload = result.to_mapping()
        resolved = payload["resolved_resource"]

        audio = [r for r in resolved["representations"] if r.get("kind") == "audio"]
        self.assertEqual(1, len(audio))
        self.assertFalse(audio[0]["materializable"])

    def test_result_does_not_leak_download_url(self) -> None:
        def verify(track_id, cookie):
            return {"title": "t", "container": "mp3", "file_size": 0}

        inspector = self._inspector(verify)
        import json

        payload = inspector._enrich(self._track_resource(), _base_result()).to_mapping()
        text = json.dumps(payload, ensure_ascii=False)
        # The verify func returns no URL; ensure none leaked.
        self.assertNotIn("http://audio", text)
        self.assertNotIn("playUrlList", text)


if __name__ == "__main__":
    unittest.main()
