from __future__ import annotations

import json
from types import SimpleNamespace

from education_resource_mcp.acquisition.planner import DEFAULT_PROVIDER_SPECS
from education_resource_mcp.adapters.inspect_yixi import YixiInspector
from education_resource_mcp.adapters.yixi import YixiSearchAdapter


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def _settings():
    return SimpleNamespace(search_timeout_seconds=5)


def _search_payload() -> dict:
    return {
        "data": {
            "items": [
                {
                    "id": 1435,
                    "title": "教育就是生长",
                    "intro": "别焦虑了",
                    "play_count": "1736次观看",
                    "video_cover": "https://aliimg.yixi.tv/almond/cover.jpg",
                    "speaker": {"name": "周国平"},
                }
            ]
        }
    }


def _play_detail_payload() -> dict:
    return {
        "error_code": 0,
        "error_msg": "成功",
        "data": {
            "base_items": {
                "id": 1435,
                "title": "教育就是生长",
                "video_duration": "30:08",
                "video_url": [
                    {
                        "type": 1,
                        "type_name": "标清",
                        "video_url": "https://alicdn.yixi.tv/1785913020293-2.mp4",
                    },
                    {
                        "type": 2,
                        "type_name": "高清",
                        "video_url": "https://alicdn.yixi.tv/1785913020293-3.mp4",
                    },
                    {"type": 3, "type_name": "超清", "video_url": ""},
                ],
            }
        },
    }


def test_yixi_search_resolves_highest_available_public_mp4(monkeypatch) -> None:
    responses = iter([_Response(_search_payload()), _Response(_play_detail_payload())])

    def fake_urlopen(request, timeout):
        return next(responses)

    monkeypatch.setattr(
        "education_resource_mcp.adapters.yixi.urlopen_with_fallback",
        fake_urlopen,
    )

    adapter = YixiSearchAdapter(object(), _settings())
    resources, error = adapter.search("教育就是生长", 10)

    assert error is None
    assert len(resources) == 1
    resource = resources[0]
    assert resource["platform"] == "yixi"
    assert resource["source_url"] == "https://alicdn.yixi.tv/1785913020293-3.mp4"
    signals = resource["metadata"]["platform_signals"]
    assert signals["speech_id"] == 1435
    assert signals["video_duration"] == "30:08"
    assert signals["direct_video"] is True


def test_yixi_search_keeps_candidate_when_play_detail_has_no_video(monkeypatch) -> None:
    empty_detail = {
        "error_code": 0,
        "data": {"base_items": {"id": 1435, "video_url": []}},
    }
    responses = iter([_Response(_search_payload()), _Response(empty_detail)])

    def fake_urlopen(request, timeout):
        return next(responses)

    monkeypatch.setattr(
        "education_resource_mcp.adapters.yixi.urlopen_with_fallback",
        fake_urlopen,
    )

    adapter = YixiSearchAdapter(object(), _settings())
    resources, error = adapter.search("教育就是生长", 10)

    assert error is None
    assert len(resources) == 1
    resource = resources[0]
    assert resource["source_url"] == "https://www.yixi.tv/speech/detail?id=1435"
    assert resource["metadata"]["platform_signals"]["direct_video"] is False


def test_yixi_inspector_requires_server_speech_id_and_direct_video() -> None:
    inspector = YixiInspector(timeout_seconds=5)

    missing_id = inspector.inspect(
        {
            "platform": "yixi",
            "source_url": "https://alicdn.yixi.tv/video.mp4",
            "metadata": {"platform_signals": {"direct_video": True}},
        }
    ).to_mapping()
    assert missing_id["resolution_status"] == "unresolved"
    assert missing_id["failures"][0]["code"] == "PLATFORM_VALIDATION_BLOCKED"

    unresolved_media = inspector.inspect(
        {
            "platform": "yixi",
            "source_url": "https://www.yixi.tv/speech/detail?id=1435",
            "metadata": {
                "platform_signals": {"speech_id": 1435, "direct_video": False}
            },
        }
    ).to_mapping()
    assert unresolved_media["resolution_status"] == "unresolved"
    assert unresolved_media["failures"][0]["code"] == "PLATFORM_VALIDATION_BLOCKED"


def test_yixi_video_routes_to_generic_direct() -> None:
    matches = [
        spec
        for spec in DEFAULT_PROVIDER_SPECS
        if spec.platform_id == "yixi"
        and spec.scope == "primary_resource"
        and spec.representation_kind == "video"
        and "mp4" in spec.containers
    ]

    assert len(matches) == 1
    assert matches[0].provider_id == "generic-direct"
