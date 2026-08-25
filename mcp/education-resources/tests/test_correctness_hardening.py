"""Focused regressions for 0073 correctness hardening."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from education_resource_mcp.acquisition.models import AcquisitionRequest, AcquisitionStrategy
from education_resource_mcp.acquisition.router import AcquisitionRouter, ProviderRegistration
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
from education_resource_mcp.search import MultiPlatformSearchProvider


class _GenericProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[list[dict], int]] = []
        self.fail = fail

    def search(self, tasks, limit):  # type: ignore[no-untyped-def]
        self.calls.append((tasks, limit))
        if self.fail:
            raise RuntimeError("generic exploded")
        query = tasks[0]["queries"][0]["query"]
        return (
            [
                {
                    "platform": "generic",
                    "title": query,
                    "source_url": "https://example.com/generic",
                    "resource_type": "网页",
                    "metadata": {},
                }
            ],
            [
                {
                    "platform": "generic",
                    "status": "succeeded",
                    "query_runs": [
                        {
                            "query": query,
                            "candidate_count": 1,
                            "failure_count": 0,
                        }
                    ],
                }
            ],
        )


class _Adapter:
    platform_id = "bilibili"

    def search(self, query: str, limit: int):
        return (
            [
                {
                    "platform": "bilibili",
                    "title": query,
                    "source_url": "https://www.bilibili.com/video/BV1example",
                    "resource_type": "视频",
                    "metadata": {},
                }
            ],
            None,
        )


class SearchCorrectnessTests(unittest.TestCase):
    def _provider(self, root: Path, generic: _GenericProvider) -> MultiPlatformSearchProvider:
        settings = Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=2,
        )
        with patch.object(MultiPlatformSearchProvider, "_register_default_adapters"):
            provider = MultiPlatformSearchProvider(settings, object(), generic)
        provider.register_adapter(_Adapter())
        return provider

    def test_mixed_search_keeps_generic_query_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            generic = _GenericProvider()
            provider = self._provider(Path(raw), generic)
            resources, runs = provider.search(
                [
                    {
                        "platform": "generic",
                        "queries": [{"query": "火山形成 原理"}],
                    },
                    {
                        "platform": "bilibili",
                        "queries": [{"query": "火山喷发 动画"}],
                    },
                ],
                8,
            )

        self.assertEqual(
            "火山形成 原理",
            generic.calls[0][0][0]["queries"][0]["query"],
        )
        self.assertEqual(["generic", "bilibili"], [run["platform"] for run in runs])
        self.assertEqual(2, len(resources))

    def test_generic_failure_reports_its_own_query(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            generic = _GenericProvider(fail=True)
            provider = self._provider(Path(raw), generic)
            _resources, runs = provider.search(
                [
                    {
                        "platform": "generic",
                        "queries": [{"query": "通用网页查询"}],
                    },
                    {
                        "platform": "bilibili",
                        "queries": [{"query": "视频查询"}],
                    },
                ],
                8,
            )

        generic_run = next(run for run in runs if run["platform"] == "generic")
        self.assertEqual("通用网页查询", generic_run["query_runs"][0]["query"])

    def test_adapter_no_longer_requires_descriptor_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            provider = self._provider(Path(raw), _GenericProvider())
        self.assertIn("bilibili", provider._adapters)


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
            router = AcquisitionRouter(
                [
                    ProviderRegistration(
                        "provider-first",
                        _DirectProvider(first),
                        (AcquisitionStrategy.DIRECT_FILE,),
                        ("primary_resource",),
                    ),
                    ProviderRegistration(
                        "provider-second",
                        _DirectProvider(second),
                        (AcquisitionStrategy.DIRECT_FILE,),
                        ("primary_resource",),
                    ),
                ]
            )
            common = {
                "job_id": "job_" + "a" * 32,
                "strategy": AcquisitionStrategy.DIRECT_FILE,
                "scope": "primary_resource",
                "representation_id": "repr",
                "cancel_event": threading.Event(),
                "jobs_root": root,
            }
            one = router.acquire(
                AcquisitionRequest(
                    resource={"resource_id": "res_one"},
                    provider_id="provider-first",
                    **common,
                )
            )
            two = router.acquire(
                AcquisitionRequest(
                    resource={"resource_id": "res_two"},
                    provider_id="provider-second",
                    **common,
                )
            )

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
