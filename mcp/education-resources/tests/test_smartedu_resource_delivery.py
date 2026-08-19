"""Regression tests for resource-level multi-file delivery semantics."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition.models import AcquisitionStrategy
from education_resource_mcp.acquisition.planner import (
    AcquisitionPlanner,
    AcquisitionPlanningError,
)
from education_resource_mcp.acquisition.router import (
    AcquisitionRouter,
    ProviderRegistration,
)
from education_resource_mcp.adapters.inspect_smartedu import SmartEduInspector
from education_resource_mcp.adapters.smartedu_download import (
    _detail_api_url,
    _resolve_content,
)


PUBLIC_ADDRESS = "93.184.216.34"


def public_resolver(hostname: str, port: int):
    return (PUBLIC_ADDRESS,)


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
        self.offset = 0

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self.body) - self.offset
        value = self.body[self.offset : self.offset + amount]
        self.offset += len(value)
        return value

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        pass


class _Transport:
    def __init__(self, handler) -> None:  # type: ignore[no-untyped-def]
        self.handler = handler
        self.requests = []

    def __call__(self, request, timeout=None):  # type: ignore[no-untyped-def]
        self.requests.append((request, timeout))
        return self.handler(request)


def _item(item_id: str, filename: str, fmt: str, flag: str = "source") -> dict:
    return {
        "id": item_id,
        "ti_storage": (
            f"https://r1-ndr.ykt.cbern.com.cn/course/{filename}"
            "?accessToken=private-token"
        ),
        "ti_format": fmt,
        "ti_file_flag": flag,
        "ti_size": 1024,
        "title": filename,
    }


def _course_detail() -> dict:
    return {
        "relations": {
            "course_resource": [
                {
                    "id": "lesson-1",
                    "global_title": "课程资源",
                    "ti_items": [
                        _item("video-hls", "lesson.m3u8", "m3u8"),
                        _item("video-mp4", "lesson.mp4", "mp4"),
                        _item("handout", "handout.pdf", "pdf"),
                        _item("audio", "audio.mp3", "mp3"),
                    ],
                }
            ]
        }
    }


def _candidate() -> dict:
    return {
        "resource_id": "res_" + "a" * 32,
        "platform": "smartedu",
        "title": "一堂包含视频和资料的课程",
        "source_url": "https://basic.smartedu.cn/qualityCourse?courseId=course-1",
        "resource_type": "course",
        "metadata": {"course_id": "course-1"},
    }


def _inspect() -> tuple[dict, dict]:
    candidate = _candidate()
    content_id, content_type = _resolve_content(candidate["source_url"])
    detail_url = _detail_api_url(content_id, content_type, candidate["source_url"])
    detail_body = json.dumps(_course_detail(), ensure_ascii=False).encode("utf-8")

    page_transport = _Transport(
        lambda request: _Response(
            b"<html><head><title>course</title></head><body>landing</body></html>",
            url=request.full_url,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
    )
    detail_transport = _Transport(
        lambda request: _Response(
            detail_body,
            url=detail_url,
            headers={"Content-Type": "application/json"},
        )
    )
    inspector = SmartEduInspector(
        resolver=public_resolver,
        transport=page_transport,
        detail_transport=detail_transport,
        timeout=0.25,
    )
    return candidate, inspector.inspect(candidate).to_mapping()


class SmartEduResourceDeliveryTests(unittest.TestCase):
    def test_course_inspect_exposes_primary_and_natural_companions(self) -> None:
        _candidate_value, mapped = _inspect()
        resolved = mapped["resolved_resource"]
        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("course", resolved["resource_type"])

        concrete = [
            item
            for item in resolved["representations"]
            if item.get("kind") != "webpage"
        ]
        self.assertEqual(
            [("video", "mp4", "primary", "primary_resource"),
             ("document", "pdf", "attachment", "representation"),
             ("audio", "mp3", "companion", "representation")],
            [
                (item["kind"], item["container"], item["role"], item["scope"])
                for item in concrete
            ],
        )
        self.assertFalse(any(item.get("container") == "m3u8" for item in concrete))
        self.assertTrue(
            any(
                item.get("kind") == "webpage"
                and item.get("role") == "landing"
                and item.get("scope") == "landing_page"
                for item in resolved["representations"]
            )
        )

        encoded = json.dumps(mapped, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private-token", encoded)
        self.assertNotIn("r1-ndr.ykt.cbern.com.cn", encoded)

    def test_original_routes_once_even_when_resource_has_multiple_files(self) -> None:
        candidate, mapped = _inspect()
        router = AcquisitionRouter(
            [
                ProviderRegistration(
                    provider_id="smartedu-resource",
                    provider=object(),
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                )
            ]
        )
        route = AcquisitionPlanner(router).route(
            candidate,
            mapped,
            preferred_container="original",
        )
        self.assertEqual("smartedu-resource", route["provider_id"])
        self.assertEqual("primary_resource", route["scope"])
        self.assertEqual("mp4", route["container"])

    def test_explicit_missing_primary_format_is_not_silently_ignored(self) -> None:
        candidate, mapped = _inspect()
        router = AcquisitionRouter(
            [
                ProviderRegistration(
                    provider_id="smartedu-resource",
                    provider=object(),
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                )
            ]
        )
        with self.assertRaises(AcquisitionPlanningError) as context:
            AcquisitionPlanner(router).route(
                candidate,
                mapped,
                preferred_container="pdf",
            )
        self.assertEqual("REPRESENTATION_UNAVAILABLE", context.exception.code)


if __name__ == "__main__":
    unittest.main()
