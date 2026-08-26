from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from education_resource_mcp.acquisition.planner import DEFAULT_PROVIDER_SPECS
from education_resource_mcp.adapters.inspect_zjer import ZjerInspector
from education_resource_mcp.adapters.zjer import ZjerSearchAdapter, fetch_course_detail
from education_resource_mcp.adapters.zjer_download import ZjerVideoDownloader
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError


def _settings(tmp_path: Path | None = None):
    root = tmp_path or Path(".")
    return SimpleNamespace(
        search_timeout_seconds=5,
        download_timeout_seconds=10,
        jobs_dir=root / "jobs",
    )


def _detail_data(signature: str = "fresh-signature") -> dict:
    return {
        "id": 34941,
        "uuid": "f25610ea-7d31-4e81-9e4b-d610579b060a",
        "cateName": "聂卫平围棋道场名师课堂",
        "description": "围棋启蒙阶段教学",
        "teacherOrgName": "北京弈友围棋文化传播有限责任公司",
        "courseInfoList": [
            {
                "id": 187893,
                "uuid": "fbeaf21b-cec4-48d7-a014-edf9dff9fd13",
                "courseCateId": 34941,
                "courseCateUuid": "f25610ea-7d31-4e81-9e4b-d610579b060a",
                "videoId": 181840,
                "videoSecond": 595,
                "courseName": "第1课 围棋的起源、规则与气",
                "m3u8List": [
                    {
                        "videoId": 181840,
                        "videoUrl": "//wkfile.zjer.cn/output/demo/video.m3u8?Expires=1786814798&OSSAccessKeyId=demo&Signature=ignored",
                        "videoSecond": 595,
                        "videoSize": 78556176,
                        "bitrate": 1055,
                        "definition": "标清",
                        "format": "m3u8",
                        "height": 540,
                        "width": 960,
                    }
                ],
                "mp4List": [
                    {
                        "videoId": 181840,
                        "videoName": "第1课时",
                        "uuid": "3b64a74f-54b2-41ff-bcb6-e9a79e83e8d8",
                        "videoUrl": f"//wkfile.zjer.cn/output/demo/video.mp4?Expires=1786814798&OSSAccessKeyId=demo&Signature={signature}",
                        "videoSecond": 595,
                        "videoSize": 72781124,
                        "bitrate": 978,
                        "definition": "标清",
                        "format": "mp4",
                        "height": 540,
                        "width": 960,
                    }
                ],
            }
        ],
    }


def _resource() -> dict:
    return {
        "resource_id": "res_1234567890abcdefghij",
        "platform": "zjer",
        "title": "聂卫平围棋道场名师课堂｜第1课 围棋的起源、规则与气",
        "source_url": "https://k.zjer.cn/api/s/c/courseAfter/34941?id=34941&shareId=&videoId=181840",
        "resource_type": "video",
        "metadata": {
            "platform_signals": {
                "course_cate_id": 34941,
                "course_info_id": 187893,
                "video_id": 181840,
                "course_cate_uuid": "f25610ea-7d31-4e81-9e4b-d610579b060a",
                "course_info_uuid": "fbeaf21b-cec4-48d7-a014-edf9dff9fd13",
            }
        },
    }


def test_zjer_direct_course_lookup_expands_lessons_without_signed_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "education_resource_mcp.adapters.zjer.fetch_course_detail",
        lambda course_cate_id, **kwargs: _detail_data(),
    )
    adapter = ZjerSearchAdapter(object(), _settings())

    resources, error = adapter.search("34941", 10)

    assert error is None
    assert len(resources) == 1
    resource = resources[0]
    assert resource["platform"] == "zjer"
    assert resource["title"] == "聂卫平围棋道场名师课堂｜第1课 围棋的起源、规则与气"
    serialized = json.dumps(resource, ensure_ascii=False)
    assert "Signature=" not in serialized
    assert "OSSAccessKeyId=" not in serialized
    assert "Expires=" not in serialized
    signals = resource["metadata"]["platform_signals"]
    assert signals["course_cate_id"] == 34941
    assert signals["course_info_id"] == 187893
    assert signals["video_id"] == 181840
    assert signals["video_size_bytes"] == 72781124
    assert signals["height"] == 540
    assert signals["width"] == 960


def test_zjer_login_gate_402_maps_to_auth_required(monkeypatch) -> None:
    monkeypatch.setattr(
        "education_resource_mcp.adapters.zjer._default_transport",
        lambda request, timeout: _JsonResponse({"code": "402", "msg": "登录不存在，请重新登录"}),
    )
    with pytest.raises(DomainError) as exc:
        fetch_course_detail(34941, timeout=5)
    assert exc.value.code == "AUTH_REQUIRED"
    assert exc.value.retryable is False


def test_zjer_search_sends_saved_session_cookie(monkeypatch) -> None:
    seen = {}

    class _Store:
        def get_session_data(self, platform):
            return {"platform": platform, "cookies": {"SESSDATA": "abc"}}

        def _cookie_header(self, data):
            return "SESSDATA=abc"

    monkeypatch.setattr(
        "education_resource_mcp.adapters.zjer.fetch_course_detail",
        lambda course_cate_id, **kwargs: _capture(seen, kwargs),
    )
    adapter = ZjerSearchAdapter(_Store(), _settings())
    adapter.search("34941", 10)
    assert seen.get("cookie") == "SESSDATA=abc"


def _capture(seen, kwargs) -> dict:
    seen["cookie"] = kwargs.get("cookie", "")
    return {"cateName": "x", "lessons": [], "uuid": "u"}


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_zjer_keyword_search_is_not_claimed_before_native_api_is_known() -> None:
    adapter = ZjerSearchAdapter(object(), _settings())

    resources, error = adapter.search("一次函数", 10)

    assert resources == []
    assert error is not None
    assert error["code"] == "FEATURE_NOT_SUPPORTED"
    assert error["retryable"] is False


def test_zjer_inspector_confirms_mp4_without_leaking_locator() -> None:
    inspector = ZjerInspector(
        timeout_seconds=5,
        detail_fetcher=lambda course_cate_id, **kwargs: _detail_data(),
    )

    payload = inspector.inspect(_resource()).to_mapping()

    assert payload["resolution_status"] == "resolved"
    resolved = payload["resolved_resource"]
    assert resolved["availability"] == {"status": "available"}
    assert resolved["resource_type"] == "video"
    assert len(resolved["representations"]) == 1
    representation = resolved["representations"][0]
    assert representation["kind"] == "video"
    assert representation["container"] == "mp4"
    assert representation["mime_type"] == "video/mp4"
    assert representation["materializable"] is True
    assert representation["size_bytes"] == 72781124
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "Signature=" not in serialized
    assert "OSSAccessKeyId=" not in serialized
    assert "wkfile.zjer.cn" not in serialized


def test_zjer_downloader_refreshes_signed_mp4_at_start() -> None:
    seen: dict[str, str] = {}

    class DirectDownloader:
        def download(self, resource, job_id, strategy, cancel_event):
            seen["url"] = resource["source_url"]
            return DownloadResult(
                Path("video.mp4"),
                1,
                "video/mp4",
                "0" * 64,
                "video.mp4",
            )

    downloader = ZjerVideoDownloader(
        object(),
        _settings(),
        detail_fetcher=lambda course_cate_id, **kwargs: _detail_data("new-signature"),
        direct_downloader=DirectDownloader(),
    )
    resource = _resource()

    result = downloader.download(resource, "job_test", "direct", SimpleNamespace(is_set=lambda: False))

    assert isinstance(result, DownloadResult)
    assert "Signature=new-signature" in seen["url"]
    assert seen["url"].startswith("https://wkfile.zjer.cn/")
    assert resource["source_url"].startswith("https://k.zjer.cn/api/s/c/courseAfter/34941")


def test_zjer_video_has_exact_provider_spec() -> None:
    matches = [
        spec
        for spec in DEFAULT_PROVIDER_SPECS
        if spec.platform_id == "zjer"
        and spec.scope == "primary_resource"
        and spec.representation_kind == "video"
        and "mp4" in spec.containers
    ]

    assert len(matches) == 1
    assert matches[0].provider_id == "zjer-video"
