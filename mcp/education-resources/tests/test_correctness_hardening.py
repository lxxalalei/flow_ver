"""Focused regressions for 0073 correctness hardening."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from education_resource_mcp.acquisition.models import AcquisitionRequest, AcquisitionStrategy
from education_resource_mcp.acquisition.download_dispatch import dispatch_download
from education_resource_mcp.adapters.smartedu_resource import (
    _bounded_text,
    _find_files,
    _smartedu_file_key,
    _smartedu_file_key_from_resource,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import (
    DownloadBatchResult,
    DownloadItemFailure,
    DownloadResult,
    _available_destination,
)


class _DirectProvider:
    def __init__(self, path: Path) -> None:
        self.path = path

    def download(self, resource, job_id, strategy, cancel_event):  # type: ignore[no-untyped-def]
        return DownloadResult(
            self.path,
            self.path.stat().st_size,
            "application/pdf",
            filename=self.path.name,
        )


class DownloadCorrectnessTests(unittest.TestCase):
    def test_artifact_identity_includes_resource(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "first.pdf"
            second = root / "second.pdf"
            first.write_bytes(b"%PDF-first")
            second.write_bytes(b"%PDF-second")
            def run(resource_id: str, provider_id: str, provider: object):
                return dispatch_download(
                    {provider_id: provider},
                    AcquisitionRequest(
                        resource={"resource_id": resource_id}, provider_id=provider_id,
                        job_id="job_" + "a" * 32, strategy=AcquisitionStrategy.DIRECT_FILE,
                        scope="primary_resource", representation_id="repr",
                        cancel_event=threading.Event(), jobs_root=root,
                    ),
                )
            one = run("res_one", "provider-first", _DirectProvider(first))
            two = run("res_two", "provider-second", _DirectProvider(second))


        self.assertNotEqual(
            one.bundle.artifacts[0].artifact_id,
            two.bundle.artifacts[0].artifact_id,
        )
        self.assertIn("res_one", one.bundle.artifacts[0].artifact_id)
        self.assertIn("res_two", two.bundle.artifacts[0].artifact_id)

    def test_same_name_gets_distinct_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = root / "教学设计.pdf"
            original.write_bytes(b"first")
            second = _available_destination(original)
            second.write_bytes(b"second")
            third = _available_destination(original)

            self.assertEqual("教学设计 (2).pdf", second.name)
            self.assertEqual("教学设计 (3).pdf", third.name)
            self.assertEqual(b"first", original.read_bytes())
            self.assertEqual(b"second", second.read_bytes())

    def test_download_result_no_longer_requires_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "file.pdf"
            path.write_bytes(b"%PDF-test")
            result = DownloadResult(
                path,
                path.stat().st_size,
                "application/pdf",
                filename=path.name,
            )
        self.assertIsNone(result.sha256)
        self.assertNotIn("sha256", result.to_dict())

    def test_batch_and_metadata_have_no_arbitrary_small_bounds(self) -> None:
        failures = tuple(
            DownloadItemFailure(
                item_key=f"item-{index}",
                code="DOWNLOAD_FAILED",
                message="x" * 700,
                metadata={
                    "nested": {"a": {"b": {"c": {"d": {"e": index}}}}},
                    **{f"field_{field}": field for field in range(80)},
                },
            )
            for index in range(60)
        )
        batch = DownloadBatchResult(failures=failures)
        self.assertEqual(60, len(batch.failures))
        self.assertEqual(700, len(batch.failures[0].message))
        self.assertEqual(80, len([key for key in batch.failures[0].metadata if key.startswith("field_")]))


class SmartEduFactTests(unittest.TestCase):
    def test_provider_text_is_not_silently_truncated(self) -> None:
        text = "课程标题" * 100
        self.assertEqual(text, _bounded_text(text, 12))

    def test_file_identity_is_transparent_and_accepts_native_unicode_ids(self) -> None:
        detail = {
            "relations": {
                "课程资源": [
                    {
                        "id": "课件组/一",
                        "ti_items": [
                            {
                                "id": "讲义：甲",
                                "ti_storage": "https://r1-ndr.ykt.cbern.com.cn/file.pdf",
                                "ti_format": "pdf",
                                "title": "讲义",
                            }
                        ],
                    }
                ]
            }
        }
        candidate = _find_files(detail)[0]
        key = _smartedu_file_key("课程-一", candidate)
        resource = {"metadata": {"platform_signals": {"file_key": key}}}

        self.assertTrue(key.startswith("smartedu-file:v1:"))
        self.assertNotRegex(key, r"smartedu-file:[0-9a-f]{32}$")
        self.assertEqual(key, _smartedu_file_key_from_resource(resource))


if __name__ == "__main__":
    unittest.main()
