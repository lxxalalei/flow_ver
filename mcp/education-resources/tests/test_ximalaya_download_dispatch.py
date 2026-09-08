"""Ximalaya audio download-dispatch routing.

Album expand emits sound items with resource_type="track"; fresh Inspect of a
sound URL resolves the same object as resource_type="audio". Both must route
to the ximalaya-audio handler - a regression from the acquisition refactor
that required resource_type == "audio" only (CAPABILITY_NOT_DECLARED).
"""

from __future__ import annotations

import unittest

from education_resource_mcp.acquisition.download_dispatch import (
    DownloadDispatchError,
    select_download_handler,
)


def _resolution(container: str = "m4a") -> dict:
    return {
        "resolved_resource": {
            "representations": [
                {
                    "representation_id": "rep-ximalaya-audio",
                    "kind": "audio",
                    "container": container,
                    "role": "primary",
                    "scope": "primary_resource",
                    "technical_availability": "available",
                    "materializable": True,
                }
            ]
        }
    }


class XimalayaDownloadDispatchTests(unittest.TestCase):
    def test_expand_track_item_routes_to_ximalaya_audio(self) -> None:
        # resource_type="track" is what ximalaya album expansion emits.
        result = select_download_handler(
            {"platform": "ximalaya", "resource_type": "track"},
            _resolution(),
            preferred_container="original",
            handlers={"ximalaya-audio": object()},
        )
        self.assertEqual("direct_file", result["strategy"])
        self.assertEqual("ximalaya-audio", result["provider_id"])
        self.assertEqual("primary_resource", result["scope"])

    def test_inspected_audio_item_still_routes(self) -> None:
        result = select_download_handler(
            {"platform": "ximalaya", "resource_type": "audio"},
            _resolution(),
            preferred_container="original",
            handlers={"ximalaya-audio": object()},
        )
        self.assertEqual("direct_file", result["strategy"])
        self.assertEqual("ximalaya-audio", result["provider_id"])

    def test_non_audio_kind_does_not_declare_ximalaya_downloader(self) -> None:
        with self.assertRaises(DownloadDispatchError) as ctx:
            select_download_handler(
                {"platform": "ximalaya", "resource_type": "track"},
                _resolution(container="pdf"),
                preferred_container="original",
                handlers={},
            )
        self.assertEqual("CAPABILITY_NOT_DECLARED", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
