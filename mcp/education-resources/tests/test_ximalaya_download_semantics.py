"""Semantic guard tests for Ximalaya downloads."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from education_resource_mcp.adapters.ximalaya_download import XimalayaDownloader
from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.sessions import SessionStore


class XimalayaDownloadSemanticTests(unittest.TestCase):
    def test_album_is_not_silently_downloaded_as_first_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloader = XimalayaDownloader(
                SessionStore(root),
                Settings(
                    data_dir=root,
                    jobs_dir=root / "jobs",
                    library_dir=root / "library",
                    max_workers=1,
                ),
            )
            with self.assertRaises(DomainError) as ctx:
                downloader.download(
                    {
                        "platform": "ximalaya",
                        "title": "album",
                        "source_url": "https://www.ximalaya.com/album/123",
                        "resource_type": "album",
                    },
                    "job_test",
                    "direct",
                    threading.Event(),
                )

        self.assertEqual("FEATURE_NOT_SUPPORTED", ctx.exception.code)

    def test_unrecognized_numeric_url_is_not_guessed_as_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloader = XimalayaDownloader(
                SessionStore(root),
                Settings(
                    data_dir=root,
                    jobs_dir=root / "jobs",
                    library_dir=root / "library",
                    max_workers=1,
                ),
            )
            with self.assertRaises(DomainError) as ctx:
                downloader.download(
                    {
                        "platform": "ximalaya",
                        "title": "unknown",
                        "source_url": "https://www.ximalaya.com/other/456",
                        "resource_type": "other",
                    },
                    "job_test",
                    "direct",
                    threading.Event(),
                )

        self.assertEqual("FEATURE_NOT_SUPPORTED", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
