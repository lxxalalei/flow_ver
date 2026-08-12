from __future__ import annotations

import json
import unittest

from education_resource_mcp.adapters.inspect_bilibili import BilibiliInspector
from education_resource_mcp.adapters.inspect_smartedu import SmartEduInspector
from education_resource_mcp.adapters.smartedu_download import (
    _detail_api_url,
    _resolve_content,
)
from education_resource_mcp.adapters.inspect_zhihu import ZhihuInspector


PUBLIC_ADDRESS = "93.184.216.34"
PUBLIC_HTML = """
<!doctype html><html lang="zh-CN"><head>
  <title>公开教育详情</title>
  <meta name="description" content="公开详情页">
  <meta name="author" content="页面作者">
</head><body><main>public detail</main></body></html>
""".encode("utf-8")


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = PUBLIC_HTML,
        final_url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.body = body
        self.final_url = final_url
        self._offset = 0
        self.read_calls = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        self.read_calls += 1
        if amount < 0:
            amount = len(self.body) - self._offset
        value = self.body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def geturl(self) -> str:
        return self.final_url

    def close(self) -> None:
        self.closed = True


class QueueTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


def public_resolver(hostname: str, port: int):
    return (PUBLIC_ADDRESS,)


def resource(
    *,
    platform: str,
    source_url: str,
    resource_type: str = "article",
    metadata: dict | None = None,
) -> dict:
    return {
        "resource_id": "res_" + "a" * 16,
        "platform": platform,
        "title": "候选资源",
        "source_url": source_url,
        "resource_type": resource_type,
        "metadata": metadata or {},
    }


def inspect_with(inspector_type, candidate: dict, response: FakeResponse):
    transport = QueueTransport(response)
    inspector = inspector_type(
        resolver=public_resolver,
        transport=transport,
        timeout=0.25,
    )
    return inspector.inspect(candidate).to_mapping(), transport


class PlatformInspectorMediaTests(unittest.TestCase):
    @staticmethod
    def _smartedu_detail_url(source_url: str) -> str:
        content_id, content_type = _resolve_content(source_url)
        return _detail_api_url(content_id, content_type, source_url)

    def test_bilibili_enriches_allowlisted_metadata_without_synthetic_primary(self) -> None:
        candidate = resource(
            platform="bilibili",
            source_url="https://www.bilibili.com/video/BV1public",
            resource_type="video",
            metadata={
                "bvid": "BV1public",
                "duration_seconds": 321,
                "play_count": 9876,
                "published_at": "2025-01-02T03:04:05Z",
                "author": "科学课堂",
                "unlisted_value": "must not be copied",
            },
        )
        mapped, transport = inspect_with(
            BilibiliInspector,
            candidate,
            FakeResponse(final_url=candidate["source_url"]),
        )

        self.assertEqual(1, len(transport.requests))
        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("bilibili", mapped["inspection"]["inspector_id"])
        self.assertEqual("platform_bounded_get", mapped["inspection"]["method"])
        metadata = mapped["resolved_resource"]["metadata"]
        self.assertEqual("BV1public", metadata["bvid"])
        self.assertEqual(321, metadata["duration_seconds"])
        self.assertEqual(9876, metadata["play_count"])
        self.assertEqual("科学课堂", metadata["author"])
        self.assertNotIn("unlisted_value", metadata)
        representations = mapped["resolved_resource"]["representations"]
        self.assertTrue(any(item["kind"] == "webpage" and item["role"] == "landing" for item in representations))
        self.assertTrue(
            any(
                item["kind"] == "video"
                and item["scope"] == "representation"
                and item["role"] == "companion"
                and item["materializable"] is False
                for item in representations
            )
        )

    def test_zhihu_enriches_ids_and_keeps_article_as_webpage(self) -> None:
        candidate = resource(
            platform="zhihu",
            source_url="https://www.zhihu.com/question/123/answer/456",
            metadata={
                "answer_id": "456",
                "question_id": "123",
                "published_at": "2024-05-06T00:00:00Z",
                "vote_count": 42,
                "author": "回答者",
            },
        )
        mapped, _ = inspect_with(
            ZhihuInspector,
            candidate,
            FakeResponse(final_url=candidate["source_url"]),
        )

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("zhihu", mapped["inspection"]["inspector_id"])
        metadata = mapped["resolved_resource"]["metadata"]
        self.assertEqual("456", metadata["answer_id"])
        self.assertEqual("123", metadata["question_id"])
        self.assertEqual(42, metadata["vote_count"])
        self.assertEqual("回答者", metadata["author"])
        self.assertTrue(
            any(item["kind"] == "webpage" for item in mapped["resolved_resource"]["representations"])
        )

    @staticmethod
    def _smartedu_detail(*items: dict) -> bytes:
        return json.dumps(
            {
                "relations": {
                    "course_resource": [
                        {"id": "lesson-1", "global_title": "课程资源", "ti_items": list(items)}
                    ]
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _smartedu_item(item_id: str, url: str, fmt: str, *, size: int = 16) -> dict:
        return {
            "id": item_id,
            "ti_storage": url,
            "ti_format": fmt,
            "ti_file_flag": "source",
            "ti_size": size,
            "title": "平台主文件",
        }

    def test_smartedu_pdf_detail_produces_concrete_primary_without_locators(self) -> None:
        candidate = resource(
            platform="smartedu",
            source_url="https://basic.smartedu.cn/tchMaterial/detail?contentId=native-9",
            resource_type="document",
            metadata={
                "content_id": "native-9",
                "resource_id": "native-resource-9",
                "grade": "三年级",
                "subject": "科学",
                "resource_format": "pdf",
                "provider": "国家中小学智慧教育平台",
            },
        )
        detail_transport = QueueTransport(
            FakeResponse(
                final_url=self._smartedu_detail_url(candidate["source_url"]),
                headers={"Content-Type": "application/json"},
                body=self._smartedu_detail(
                    self._smartedu_item(
                        "book-pdf",
                        "https://r1-ndr.ykt.cbern.com.cn/book.pdf?accessToken=private-token",
                        "pdf",
                        size=1024,
                    )
                ),
            )
        )
        page_transport = QueueTransport(FakeResponse(final_url=candidate["source_url"]))
        inspector = SmartEduInspector(
            resolver=public_resolver,
            transport=page_transport,
            detail_transport=detail_transport,
            timeout=0.25,
        )
        mapped = inspector.inspect(candidate).to_mapping()

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("platform_detail_api", mapped["inspection"]["method"])
        metadata = mapped["resolved_resource"]["metadata"]
        self.assertEqual("native-resource-9", metadata["resource_id"])
        self.assertEqual("三年级", metadata["grade"])
        representations = mapped["resolved_resource"]["representations"]
        primary = next(item for item in representations if item["role"] == "primary")
        self.assertEqual("document", primary["kind"])
        self.assertEqual("pdf", primary["container"])
        self.assertEqual("primary_resource", primary["scope"])
        self.assertEqual("available", primary["technical_availability"])
        self.assertTrue(primary["materializable"])
        self.assertEqual(1024, primary["size_bytes"])
        encoded = json.dumps(mapped, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("https://r1-ndr.ykt.cbern.com.cn", encoded)
        self.assertNotIn("private-token", encoded)
        self.assertNotIn("ti_storage", encoded)

    def test_smartedu_course_detail_prefers_direct_mp4_and_keeps_landing(self) -> None:
        candidate = resource(
            platform="smartedu",
            source_url="https://basic.smartedu.cn/qualityCourse?courseId=course-9",
            resource_type="course",
            metadata={"course_id": "course-9", "provider": "SmartEdu"},
        )
        detail_transport = QueueTransport(
            FakeResponse(
                final_url=self._smartedu_detail_url(candidate["source_url"]),
                headers={"Content-Type": "application/json"},
                body=self._smartedu_detail(
                    self._smartedu_item(
                        "video-1",
                        "https://r1-ndr.ykt.cbern.com.cn/video.m3u8?accessToken=private-token",
                        "m3u8",
                    ),
                    self._smartedu_item(
                        "video-2",
                        "https://r1-ndr.ykt.cbern.com.cn/video.mp4?accessToken=private-token",
                        "mp4",
                    ),
                    self._smartedu_item(
                        "handout-1",
                        "https://r1-ndr.ykt.cbern.com.cn/handout.pdf?accessToken=private-token",
                        "pdf",
                    ),
                ),
            )
        )
        page_transport = QueueTransport(FakeResponse(final_url=candidate["source_url"]))
        mapped = SmartEduInspector(
            resolver=public_resolver,
            transport=page_transport,
            detail_transport=detail_transport,
            timeout=0.25,
        ).inspect(candidate).to_mapping()

        representations = mapped["resolved_resource"]["representations"]
        primary = next(item for item in representations if item["role"] == "primary")
        self.assertEqual("video", primary["kind"])
        self.assertEqual("mp4", primary["container"])
        self.assertEqual("video/mp4", primary["mime_type"])
        self.assertTrue(primary["materializable"])
        self.assertTrue(
            any(
                item["kind"] == "webpage"
                and item["scope"] == "landing_page"
                and item["role"] == "landing"
                for item in representations
            )
        )

    def test_smartedu_detail_auth_failure_never_produces_primary(self) -> None:
        candidate = resource(
            platform="smartedu",
            source_url="https://basic.smartedu.cn/qualityCourse?courseId=course-auth",
            resource_type="course",
        )
        detail_transport = QueueTransport(
            FakeResponse(
                status=403,
                final_url=self._smartedu_detail_url(candidate["source_url"]),
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
        )
        mapped = SmartEduInspector(
            resolver=public_resolver,
            transport=QueueTransport(FakeResponse(final_url=candidate["source_url"])),
            detail_transport=detail_transport,
            timeout=0.25,
        ).inspect(candidate).to_mapping()

        self.assertEqual("partial", mapped["resolution_status"])
        self.assertEqual("auth_required", mapped["resolved_resource"]["availability"]["status"])
        self.assertEqual("AUTH_REQUIRED", mapped["failures"][0]["code"])
        self.assertFalse(
            any(item.get("role") == "primary" for item in mapped["resolved_resource"]["representations"])
        )

    def test_wrong_host_is_policy_blocked_without_a_request(self) -> None:
        cases = (
            (BilibiliInspector, "bilibili", "https://bilibili.com.evil.test/video/1"),
            (ZhihuInspector, "zhihu", "https://zhihu.com.evil.test/question/1"),
            (SmartEduInspector, "smartedu", "https://smartedu.cn.evil.test/course/1"),
        )
        for inspector_type, platform, source_url in cases:
            with self.subTest(platform=platform):
                mapped, transport = inspect_with(
                    inspector_type,
                    resource(platform=platform, source_url=source_url),
                    FakeResponse(final_url=source_url),
                )
                self.assertEqual([], transport.requests)
                self.assertEqual("unresolved", mapped["resolution_status"])
                self.assertEqual(
                    "policy_blocked",
                    mapped["resolved_resource"]["availability"]["status"],
                )
                self.assertEqual("NETWORK_BLOCKED", mapped["failures"][0]["code"])
                self.assertEqual(platform, mapped["failures"][0]["platform"])

    def test_auth_statuses_are_preserved_for_each_platform(self) -> None:
        cases = (
            (BilibiliInspector, "bilibili", "https://www.bilibili.com/video/BV1auth"),
            (ZhihuInspector, "zhihu", "https://www.zhihu.com/question/1"),
            (SmartEduInspector, "smartedu", "https://basic.smartedu.cn/course/1"),
        )
        for status in (401, 403):
            for inspector_type, platform, source_url in cases:
                with self.subTest(status=status, platform=platform):
                    mapped, transport = inspect_with(
                        inspector_type,
                        resource(platform=platform, source_url=source_url),
                        FakeResponse(status=status, final_url=source_url),
                    )
                    self.assertEqual(1, len(transport.requests))
                    self.assertEqual("unresolved", mapped["resolution_status"])
                    self.assertEqual(
                        "auth_required",
                        mapped["resolved_resource"]["availability"]["status"],
                    )
                    self.assertEqual("AUTH_REQUIRED", mapped["failures"][0]["code"])
                    self.assertEqual(platform, mapped["failures"][0]["platform"])
                    self.assertNotEqual("resolved", mapped["resolution_status"])

    def test_partial_status_is_not_wrapped_as_resolved(self) -> None:
        candidate = resource(
            platform="bilibili",
            source_url="https://www.bilibili.com/video/BV1partial",
            resource_type="video",
        )
        mapped, _ = inspect_with(
            BilibiliInspector,
            candidate,
            FakeResponse(
                final_url=candidate["source_url"],
                headers={"Content-Type": "application/pdf"},
                body=PUBLIC_HTML,
            ),
        )
        self.assertEqual("partial", mapped["resolution_status"])
        self.assertNotEqual("resolved", mapped["resolution_status"])
        self.assertEqual("bilibili", mapped["failures"][0]["platform"])

    def test_result_has_no_secret_or_locator_fields(self) -> None:
        candidate = resource(
            platform="zhihu",
            source_url="https://www.zhihu.com/question/1?token=private",
            metadata={
                "article_id": "article-1",
                "cookie": "session=private",
                "token": "private-token",
                "headers": "Authorization: Bearer private",
                "author": "公开作者",
            },
        )
        mapped, _ = inspect_with(
            ZhihuInspector,
            candidate,
            FakeResponse(final_url=candidate["source_url"]),
        )
        encoded = json.dumps(mapped, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private", encoded)
        self.assertNotIn(candidate["source_url"], encoded)
        self.assertNotIn("cookie", encoded.casefold())
        self.assertNotIn("token", encoded.casefold())
        self.assertNotIn("headers", encoded.casefold())
        self.assertNotIn("locator", encoded.casefold())

        def walk_keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key.casefold()
                    yield from walk_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk_keys(child)

        self.assertNotIn("url", list(walk_keys(mapped)))
        self.assertNotIn("path", list(walk_keys(mapped)))
        self.assertNotIn("locator", list(walk_keys(mapped)))
        self.assertNotIn("bytes", list(walk_keys(mapped)))


if __name__ == "__main__":
    unittest.main()
