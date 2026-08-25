"""Offline regression tests for the active SmartEdu download contract."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters import smartedu_download as sd
from education_resource_mcp.adapters.smartedu_download import (
    SmartEduDownloader,
    _SmartEduHttpClient,
    _detail_api_url,
    _find_files,
    _resolve_content,
    _select_course_files,
    _smartedu_file_key,
    _smartedu_representation_id,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadBatchResult, DownloadResult
from education_resource_mcp.errors import DomainError


PUBLIC_ADDRESS = "93.184.216.34"
DETAIL_HOST = "s-file-1.ykt.cbern.com.cn"
FILE_HOST = "r1-ndr.ykt.cbern.com.cn"


def public_resolver(hostname: str, port: int):
    return (PUBLIC_ADDRESS,)


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        jobs_dir=root / "jobs",
        library_dir=root / "library",
        max_workers=2,
    )


class _SessionStore:
    def __init__(self, token: str = "") -> None:
        self.token = token

    def get_session_data(self, platform: str) -> dict:
        if not self.token:
            return {}
        return {"tokens": {"accessToken": self.token}}


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.url = url
        self.status = status
        self.headers = headers or {"Content-Type": "application/octet-stream"}
        self._offset = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self.body) - self._offset
        value = self.body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _Transport:
    def __init__(self, handler) -> None:  # type: ignore[no-untyped-def]
        self.handler = handler
        self.requests = []

    def __call__(self, request, timeout=None):  # type: ignore[no-untyped-def]
        self.requests.append((request, timeout))
        return self.handler(request)


def _json_response(payload: object, url: str, *, status: int = 200) -> _Response:
    return _Response(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        url=url,
        status=status,
        headers={"Content-Type": "application/json"},
    )


def _item(
    item_id: str,
    path: str,
    fmt: str,
    flag: str,
    *,
    size: int = 16,
    title: str = "课程资源",
) -> dict:
    return {
        "id": item_id,
        "ti_storage": f"https://{FILE_HOST}{path}?accessToken=secret-token",
        "ti_format": fmt,
        "ti_file_flag": flag,
        "ti_size": size,
        "title": title,
    }


def _course_detail(*, include_mp4: bool = True, include_m3u8: bool = True) -> dict:
    items: list[dict] = []
    if include_m3u8:
        items.append(
            _item(
                "video-hls",
                "/course/video.m3u8",
                "m3u8",
                "href-720p-m3u8",
                title="课程视频 HLS",
            )
        )
    if include_mp4:
        items.append(
            _item(
                "video-mp4",
                "/course/video.mp4",
                "mp4",
                "href-720p-mp4",
                title="课程视频",
            )
        )
    items.extend(
        [
            _item(
                "handout-1",
                "/course/handout.pdf",
                "pdf",
                "source",
                title="课程讲义",
            ),
            _item(
                "audio-1",
                "/course/audio.mp3",
                "mp3",
                "source",
                title="课程音频",
            ),
        ]
    )
    return {
        "relations": {
            "course_resource": [
                {
                    "id": "lesson-1",
                    "global_title": "课程资源",
                    "ti_items": items,
                }
            ]
        }
    }


def _document_detail() -> dict:
    return {
        "global_title": "英语教材",
        "ti_items": [
            _item(
                "book-docx",
                "/book/book.docx",
                "docx",
                "source",
                size=8,
                title="教材文档",
            ),
            _item(
                "book-pdf",
                "/book/book.pdf",
                "pdf",
                "source",
                size=16,
                title="教材 PDF",
            ),
        ],
    }


def _valid_bytes(fmt: str) -> bytes:
    return {
        "pdf": b"%PDF-1.7\nfixture",
        "mp4": b"\x00\x00\x00\x18ftypmp42fixture",
        "mp3": b"ID3fixture",
        "m4a": b"\x00\x00\x00\x18ftypM4A fixture",
    }[fmt]


_HLS_PLAIN = (
    b"#EXTM3U\n"
    b"#EXT-X-VERSION:3\n"
    b"#EXTINF:4.0,\n"
    b"seg0.ts\n"
    b"#EXTINF:4.0,\n"
    b"seg1.ts\n"
    b"#EXT-X-ENDLIST\n"
)

_AES_KEY = bytes(range(16))
_AES_IV = bytes.fromhex("00000000000000000000000000000001")
_AES_PLAIN = b"0123456789abcdef" * 4
_HLS_AES = (
    b"#EXTM3U\n"
    b"#EXT-X-KEY:METHOD=AES-128,URI=\"secret.key\",IV=0x00000000000000000000000000000001\n"
    b"#EXTINF:4.0,\n"
    b"seg0.ts\n"
    b"#EXTINF:4.0,\n"
    b"seg1.ts\n"
    b"#EXT-X-ENDLIST\n"
)


class _FakeFfmpegResult:
    returncode = 0
    stderr = b""


def _fake_ffmpeg_capture(captured: dict) -> "type":
    """subprocess.run stub: record the remux input, write a valid MP4."""

    def run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        captured["ts"] = Path(cmd[5]).read_bytes()
        Path(cmd[-1]).write_bytes(_valid_bytes("mp4"))
        return _FakeFfmpegResult()

    return run  # type: ignore[return-value]


def _batch_parts(value: object) -> tuple[list[DownloadResult], list[object]]:
    if isinstance(value, DownloadBatchResult):
        return list(value.results), list(value.failures)
    if isinstance(value, DownloadResult):
        return [value], []
    raise AssertionError(f"unexpected SmartEdu result: {type(value)!r}")


class SmartEduBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = _settings(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _download(
        self,
        detail: dict,
        *,
        planned_container: str,
        source_url: str = "https://basic.smartedu.cn/qualityCourse?courseId=course-1",
        audio: list[dict] | None = None,
        invalid_formats: set[str] | None = None,
        failure_formats: set[str] | None = None,
        cancel_on_format: str | None = None,
        cancel_event: threading.Event | None = None,
        extra_bodies: dict[str, bytes] | None = None,
        file_key: str = "",
    ) -> tuple[object, _Transport]:
        invalid_formats = invalid_formats or set()
        failure_formats = failure_formats or set()
        cancel_event = cancel_event or threading.Event()
        content_id, content_type = _resolve_content(source_url)
        detail_url = _detail_api_url(content_id, content_type, source_url)

        def handler(request):  # type: ignore[no-untyped-def]
            url = request.full_url
            if url == detail_url:
                return _json_response(detail, url)
            if "relation_audios" in url:
                return _json_response(audio or [], url)
            suffix = Path(url.split("?", 1)[0]).suffix.lstrip(".")
            if cancel_on_format == suffix:
                cancel_event.set()
                raise DomainError("JOB_CANCELLED", "cancelled")
            if suffix in failure_formats:
                raise DomainError(
                    "DOWNLOAD_FAILED",
                    "upstream failed at https://evil.test/private?token=secret-token",
                    retryable=True,
                )
            if suffix in invalid_formats:
                body = b"<html>login</html>"
            else:
                # 注意不能写成 .get(suffix, _valid_bytes(suffix))：默认值会被
                # 无条件求值，未知后缀直接 KeyError。
                body = (extra_bodies or {}).get(suffix)
                if body is None:
                    body = _valid_bytes(suffix)
            return _Response(body, url=url)

        transport = _Transport(handler)
        downloader = SmartEduDownloader(
            _SessionStore("test-token"),
            self.settings,
            resolver=public_resolver,
            transport=transport,
        )  # type: ignore[arg-type]
        resource = {
            "resource_id": "res_smartedu_fixture_0001",
            "source_url": source_url,
            "title": "固定夹具资源",
            "platform": "smartedu",
        }
        if file_key:
            resource["metadata"] = {"platform_signals": {"file_key": file_key}}
        candidates = _find_files(detail)
        primary = next(
            (
                candidate
                for candidate in _select_course_files(candidates)
                if (
                    _smartedu_file_key(content_id, candidate) == file_key
                    if file_key
                    else str(candidate.get("format") or "").casefold()
                    == planned_container
                )
            ),
            {"item_key": "missing", "format": planned_container},
        )
        resource["_planned_representation"] = {
            "representation_id": _smartedu_representation_id(resource, primary),
            "container": planned_container,
        }
        return (
            downloader.download(resource, "job-1", "direct", cancel_event),
            transport,
        )

    def test_course_prefers_direct_mp4_and_keeps_ordered_companions(self) -> None:
        raw, transport = self._download(_course_detail(), planned_container="mp4")
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual(["primary", "attachment", "companion"], [item.role for item in results])
        self.assertEqual([True, False, False], [item.required for item in results])
        self.assertEqual("video/mp4", results[0].media_type)
        requested = [request.full_url for request, _timeout in transport.requests]
        self.assertFalse(any(".m3u8" in url for url in requested))

    def test_course_file_resource_downloads_only_selected_attachment(self) -> None:
        detail = _course_detail()
        handout = next(
            item for item in _find_files(detail) if item["format"] == "pdf"
        )
        file_key = _smartedu_file_key("course-1", handout)

        raw, transport = self._download(
            detail,
            planned_container="pdf",
            file_key=file_key,
        )
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual(1, len(results))
        self.assertEqual("primary", results[0].role)
        requested = [request.full_url for request, _timeout in transport.requests]
        self.assertTrue(any("handout.pdf" in url for url in requested))
        self.assertFalse(any("video.mp4" in url or "audio.mp3" in url for url in requested))

    def test_only_m3u8_does_not_match_confirmed_mp4(self) -> None:
        with self.assertRaises(DomainError) as context:
            self._download(
                _course_detail(include_mp4=False),
                planned_container="mp4",
            )
        self.assertEqual("CONTENT_VALIDATION_FAILED", context.exception.code)
        self.assertFalse((self.settings.jobs_dir / "job-1").exists())

    def test_course_m3u8_primary_materializes_mp4(self) -> None:
        captured: dict = {}
        with mock.patch.object(sd.shutil, "which", return_value="ffmpeg"), \
                mock.patch.object(
                    sd.subprocess, "run", side_effect=_fake_ffmpeg_capture(captured)
                ):
            raw, transport = self._download(
                _course_detail(include_mp4=False),
                planned_container="m3u8",
                extra_bodies={"m3u8": _HLS_PLAIN, "ts": b"TSSEGMENT0PAYLOAD"},
            )
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual(["primary", "attachment", "companion"], [item.role for item in results])
        self.assertEqual([True, False, False], [item.required for item in results])
        self.assertEqual("video/mp4", results[0].media_type)
        self.assertTrue(results[0].filename.endswith(".mp4"))
        requested = [request.full_url for request, _timeout in transport.requests]
        self.assertTrue(any(".m3u8" in url for url in requested))
        self.assertEqual(2, sum(".ts" in url for url in requested))
        self.assertEqual(b"TSSEGMENT0PAYLOAD" * 2, captured["ts"])

    def test_course_m3u8_aes128_segments_are_decrypted(self) -> None:
        from Crypto.Cipher import AES

        cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_IV)
        encrypted = cipher.encrypt(_AES_PLAIN + bytes([16]) * 16)
        captured: dict = {}
        with mock.patch.object(sd.shutil, "which", return_value="ffmpeg"), \
                mock.patch.object(
                    sd.subprocess, "run", side_effect=_fake_ffmpeg_capture(captured)
                ):
            raw, _transport = self._download(
                _course_detail(include_mp4=False),
                planned_container="m3u8",
                extra_bodies={"m3u8": _HLS_AES, "ts": encrypted, "key": _AES_KEY},
            )
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual("video/mp4", results[0].media_type)
        self.assertEqual(_AES_PLAIN * 2, captured["ts"])

    def test_course_m3u8_without_ffmpeg_fails_fast(self) -> None:
        with mock.patch.object(sd.shutil, "which", return_value=None):
            with self.assertRaises(DomainError) as context:
                self._download(
                    _course_detail(include_mp4=False),
                    planned_container="m3u8",
                    extra_bodies={"m3u8": _HLS_PLAIN, "ts": b"TSSEGMENT0PAYLOAD"},
                )
        self.assertEqual("DOWNLOAD_FAILED", context.exception.code)
        self.assertIn("ffmpeg", context.exception.message)
        self.assertFalse((self.settings.jobs_dir / "job-1").exists())

    def test_companion_failure_is_partial_and_redacted(self) -> None:
        raw, _ = self._download(
            _course_detail(),
            planned_container="mp4",
            failure_formats={"pdf"},
        )
        results, failures = _batch_parts(raw)

        self.assertEqual(2, len(results))
        self.assertEqual(1, len(failures))
        failure = failures[0]
        self.assertEqual("DOWNLOAD_FAILED", failure.code)
        self.assertEqual("attachment", failure.role)
        serialized = json.dumps(failure.to_dict(), ensure_ascii=False)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_invalid_primary_signature_is_rejected_and_removed(self) -> None:
        raw, _ = self._download(
            _course_detail(),
            planned_container="mp4",
            invalid_formats={"mp4"},
        )
        results, failures = _batch_parts(raw)

        self.assertFalse(any(item.role == "primary" for item in results))
        primary_failure = next(item for item in failures if item.role == "primary")
        self.assertEqual("CONTENT_VALIDATION_FAILED", primary_failure.code)
        self.assertFalse((self.settings.jobs_dir / "job-1" / "课程视频.mp4").exists())

    def test_textbook_pdf_is_primary_and_relation_audio_is_companion(self) -> None:
        audio = [
            {
                "id": "relation-audio-1",
                "global_title": "教材听力",
                "ti_items": [
                    _item(
                        "audio-1",
                        "/book/audio.mp3",
                        "mp3",
                        "href",
                        title="听力音频",
                    )
                ],
            }
        ]
        raw, _ = self._download(
            _document_detail(),
            source_url=(
                "https://basic.smartedu.cn/tchMaterial/detail?"
                "contentType=assets_document&contentId=book-1"
            ),
            planned_container="pdf",
            audio=audio,
        )
        results, failures = _batch_parts(raw)

        self.assertEqual([], failures)
        self.assertEqual(2, len(results))
        self.assertEqual("primary", results[0].role)
        self.assertEqual("application/pdf", results[0].media_type)
        self.assertEqual("companion", results[1].role)
        self.assertEqual("relation_audios", results[1].metadata["relation_key"])

    def test_find_files_preserves_facts_and_redacts_metadata(self) -> None:
        detail = _course_detail()
        first = _find_files(detail)
        second = _find_files(detail)

        self.assertEqual([0, 1, 2, 3], [item["source_order"] for item in first])
        self.assertEqual([item["item_key"] for item in first], [item["item_key"] for item in second])
        self.assertEqual("course_resource", first[0]["relation_key"])
        self.assertEqual("m3u8", first[0]["format"])
        metadata = json.dumps([item["metadata"] for item in first], ensure_ascii=False)
        self.assertNotIn("https://", metadata)
        self.assertNotIn("secret-token", metadata)

    def test_cancel_aborts_whole_acquisition_and_cleans_prior_results(self) -> None:
        cancel_event = threading.Event()
        with self.assertRaises(DomainError) as context:
            self._download(
                _course_detail(),
                planned_container="mp4",
                cancel_on_format="pdf",
                cancel_event=cancel_event,
            )
        self.assertEqual("JOB_CANCELLED", context.exception.code)
        self.assertFalse(any((self.settings.jobs_dir / "job-1").glob("*")))

    def test_unapproved_storage_host_is_blocked_before_request(self) -> None:
        detail = _document_detail()
        detail["ti_items"][1]["ti_storage"] = "https://evil.test/book.pdf"
        with self.assertRaises(DomainError) as context:
            self._download(detail, planned_container="pdf")
        self.assertEqual("NETWORK_BLOCKED", context.exception.code)


class SmartEduHttpSecurityTests(unittest.TestCase):
    def test_redirect_to_unapproved_host_is_blocked_without_second_request(self) -> None:
        initial = f"https://{FILE_HOST}/book.pdf?accessToken=secret-token"
        transport = _Transport(
            lambda request: _Response(
                b"",
                url=request.full_url,
                status=302,
                headers={"Location": "https://evil.test/book.pdf"},
            )
        )
        client = _SmartEduHttpClient(resolver=public_resolver, transport=transport)

        with self.assertRaises(DomainError) as context:
            client.open(
                __import__("urllib.request", fromlist=["Request"]).Request(
                    initial, headers={"x-nd-auth": 'MAC id="secret",nonce="0",mac="0"'}
                ),
                timeout=1,
            )
        self.assertEqual("REDIRECT_BLOCKED", context.exception.code)
        self.assertEqual(1, len(transport.requests))

    def test_implicit_redirect_is_blocked(self) -> None:
        initial = f"https://{FILE_HOST}/book.pdf"
        transport = _Transport(
            lambda _request: _Response(
                _valid_bytes("pdf"),
                url="https://r2-ndr.ykt.cbern.com.cn/book.pdf",
            )
        )
        client = _SmartEduHttpClient(resolver=public_resolver, transport=transport)

        with self.assertRaises(DomainError) as context:
            client.open(
                __import__("urllib.request", fromlist=["Request"]).Request(initial),
                timeout=1,
            )
        self.assertEqual("REDIRECT_BLOCKED", context.exception.code)


class SmartEduHlsRoutingTests(unittest.TestCase):
    def test_inspector_maps_m3u8_to_video_representation(self) -> None:
        from education_resource_mcp.adapters.inspect_smartedu import SmartEduInspector

        shape = SmartEduInspector._representation_shape({"format": "m3u8"})
        self.assertEqual(("video", "m3u8", "video/mp4"), shape)

    def test_m3u8_representation_routes_to_smartedu_provider(self) -> None:
        from education_resource_mcp.acquisition import AcquisitionRouter, ProviderRegistration
        from education_resource_mcp.acquisition.models import AcquisitionStrategy
        from education_resource_mcp.acquisition.planner import AcquisitionPlanner

        router = AcquisitionRouter(
            (
                ProviderRegistration(
                    provider_id="smartedu-resource",
                    provider=object(),
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                ),
            )
        )
        route = AcquisitionPlanner(router).route(
            {
                "platform": "smartedu",
                "resource_type": "course",
                "source_url": "https://basic.smartedu.cn/syncClassroom/classActivity?activityId=1",
            },
            {
                "resolved_resource": {
                    "representations": [
                        {
                            "representation_id": "repr_1",
                            "scope": "primary_resource",
                            "kind": "video",
                            "role": "primary",
                            "container": "m3u8",
                            "materializable": True,
                        }
                    ]
                }
            },
        )
        self.assertEqual("smartedu-resource", route["provider_id"])
        self.assertEqual("m3u8", route["container"])


if __name__ == "__main__":
    unittest.main()
