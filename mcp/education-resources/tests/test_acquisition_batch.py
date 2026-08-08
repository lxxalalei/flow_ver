from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (  # noqa: E402
    AcquisitionRequest,
    AcquisitionRouter,
    AcquisitionStrategy,
    DownloadBatchResult,
    DownloadItemFailure,
    DownloadResult,
)


def _result(path: Path, *, role: str | None = None, item_key: str | None = None, required: bool | None = None) -> DownloadResult:
    payload = path.read_bytes()
    return DownloadResult(
        path,
        len(payload),
        "application/octet-stream",
        hashlib.sha256(payload).hexdigest(),
        path.name,
        role=role,
        item_key=item_key,
        required=required,
        metadata={"kind": role or "legacy", "source_url": "https://private.invalid/file"},
    )


class _Provider:
    def __init__(self, root: Path, raw) -> None:
        self.root = root
        self.raw = raw
        self.calls = 0

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        self.calls += 1
        return self.raw


class AcquisitionBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.resource = {
            "resource_id": "generic:batch-resource",
            "platform": "generic",
            "title": "多资产资源",
            "resource_type": "course",
            "source_url": "https://example.com/resource",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _request(self, *, cancel_event: threading.Event | None = None) -> AcquisitionRequest:
        return AcquisitionRequest(
            "job-batch-001",
            self.resource,
            AcquisitionStrategy.DIRECT_FILE,
            max_bytes=4096,
            cancel_event=cancel_event or threading.Event(),
            jobs_root=self.root,
        )

    def _files(self, names: list[str]) -> list[Path]:
        paths = []
        for name in names:
            path = self.root / "job-batch-001" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode("utf-8"))
            paths.append(path)
        return paths

    def test_old_single_and_list_keep_five_argument_compatibility(self) -> None:
        primary, attachment = self._files(["legacy.bin", "legacy-extra.bin"])
        single = AcquisitionRouter(_Provider(self.root, _result(primary))).acquire(self._request())
        self.assertTrue(single.ok)
        self.assertEqual(single.bundle.primary.role, "primary")  # type: ignore[union-attr]

        old_list = AcquisitionRouter(
            _Provider(self.root, [_result(primary), _result(attachment)])
        ).acquire(self._request())
        self.assertTrue(old_list.ok)
        artifacts = old_list.bundle.artifacts  # type: ignore[union-attr]
        self.assertEqual([item.role for item in artifacts], ["primary", "attachment"])
        self.assertEqual([item.filename for item in artifacts], ["legacy.bin", "legacy-extra.bin"])

    def test_video_audio_book_course_roles_are_preserved_in_order(self) -> None:
        cases = {
            "video": [("video.mp4", "primary"), ("captions.vtt", "subtitle"), ("cover.jpg", "cover")],
            "audio": [("audio.mp3", "primary"), ("transcript.txt", "transcript"), ("cover.jpg", "cover")],
            "book": [("book.epub", "primary"), ("book.json", "metadata"), ("notes.pdf", "attachment")],
            "course": [("lesson.mp4", "primary"), ("worksheet.pdf", "companion"), ("teacher.json", "metadata")],
        }
        for resource_type, specs in cases.items():
            with self.subTest(resource_type=resource_type):
                self.resource["resource_type"] = resource_type
                paths = self._files([name for name, _role in specs])
                values = [
                    _result(path, role=role, item_key=f"{resource_type}:{role}", required=role == "primary")
                    for path, (_name, role) in zip(paths, specs)
                ]
                result = AcquisitionRouter(
                    _Provider(self.root, DownloadBatchResult(values, ()))
                ).acquire(self._request())
                self.assertTrue(result.ok)
                self.assertEqual(result.completion, "complete")
                self.assertEqual(
                    [item.role for item in result.bundle.artifacts],  # type: ignore[union-attr]
                    [role for _name, role in specs],
                )
                self.assertEqual(
                    [item.required for item in result.bundle.artifacts],  # type: ignore[union-attr]
                    [role == "primary" for _name, role in specs],
                )

    def test_partial_batch_retains_item_failure_and_redacts_sensitive_details(self) -> None:
        primary, attachment = self._files(["course.mp4", "worksheet.pdf"])
        failure = DownloadItemFailure(
            "course:subtitle",
            "DOWNLOAD_FAILED",
            "fetch https://secret.example/x from /private/secret with token=abc",
            role="subtitle",
            required=True,
            details={
                "url": "https://secret.example/x",
                "path": "/private/secret/file.vtt",
                "token": "abc",
                "attempt": 2,
            },
        )
        raw = DownloadBatchResult(
            [_result(primary, role="primary", item_key="course:primary", required=True),
             _result(attachment, role="attachment", item_key="course:attachment")],
            [failure],
        )
        result = AcquisitionRouter(_Provider(self.root, raw)).acquire(self._request())
        self.assertTrue(result.ok)
        self.assertEqual(result.completion, "partial")
        self.assertEqual(len(result.item_failures), 1)
        self.assertEqual(result.item_failures[0].item_key, "course:subtitle")
        self.assertEqual(result.item_failures[0].role, "subtitle")
        rendered = result.to_json()
        self.assertNotIn("https://secret.example", rendered)
        self.assertNotIn("/private/secret", rendered)
        self.assertNotIn("abc", rendered)
        self.assertIn("course:subtitle", rendered)

    def test_primary_failure_is_not_ok_and_auth_policy_cancel_do_not_fallback(self) -> None:
        attachment, = self._files(["attachment.pdf"])
        for code in ("AUTH_REQUIRED", "POLICY_DENIED", "JOB_CANCELLED"):
            with self.subTest(code=code):
                primary_failure = DownloadItemFailure(
                    "course:primary", code, "item failed", role="primary", required=True
                )
                platform = _Provider(
                    self.root,
                    DownloadBatchResult([_result(attachment, role="attachment", item_key="course:attachment")], [primary_failure]),
                )
                direct = _Provider(self.root, _result(attachment))
                router = AcquisitionRouter(
                    direct,
                    platform_providers={"generic": platform},
                )
                result = router.acquire(self._request())
                self.assertFalse(result.ok)
                self.assertEqual(result.failure.code, code)  # type: ignore[union-attr]
                self.assertEqual(len(result.item_failures), 1)
                self.assertEqual(direct.calls, 0)

    def test_role_invariants_and_duplicate_item_keys_are_rejected(self) -> None:
        first, second = self._files(["one.bin", "two.bin"])
        cases = [
            DownloadBatchResult(
                [_result(first, role="primary", item_key="one"), _result(second, role="primary", item_key="two")],
                (),
            ),
            DownloadBatchResult(
                [_result(first, role="attachment", item_key="one"), _result(second, role="subtitle", item_key="two")],
                (),
            ),
            DownloadBatchResult(
                [_result(first, role="bundle", item_key="legacy-bundle")],
                (),
            ),
            DownloadBatchResult(
                [_result(first, role="primary", item_key="same"), _result(second, role="attachment", item_key="same")],
                (),
            ),
        ]
        for raw in cases:
            result = AcquisitionRouter(_Provider(self.root, raw)).acquire(self._request())
            self.assertFalse(result.ok)
            self.assertEqual(result.failure.code, "ACQUISITION_OUTPUT_INVALID")  # type: ignore[union-attr]

    def test_batch_is_bounded_ordered_and_json_safe(self) -> None:
        path, = self._files(["ordered.bin"])
        value = _result(path, role="primary", item_key="ordered")
        with self.assertRaises(ValueError):
            DownloadBatchResult([value] * 51, ())
        batch = DownloadBatchResult([value], [])
        self.assertEqual(batch.results[0].item_key, "ordered")
        payload = json.loads(batch.to_json())
        self.assertEqual(payload["results"][0]["item_key"], "ordered")
        self.assertNotIn("path", payload["results"][0])
        self.assertNotIn(str(self.root), batch.to_json())

    def test_cancelled_request_does_not_call_provider(self) -> None:
        cancel = threading.Event()
        cancel.set()
        provider = _Provider(self.root, None)
        result = AcquisitionRouter(provider).acquire(self._request(cancel_event=cancel))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "JOB_CANCELLED")  # type: ignore[union-attr]
        self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
