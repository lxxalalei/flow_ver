from __future__ import annotations

import json
import unittest

from education_resource_mcp.adapters.inspect_bilibili import BilibiliInspector
from education_resource_mcp.adapters.inspect_smartedu import SmartEduInspector
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

    def test_smartedu_keeps_native_resource_id_without_synthetic_primary(self) -> None:
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
        mapped, _ = inspect_with(
            SmartEduInspector,
            candidate,
            FakeResponse(final_url=candidate["source_url"]),
        )

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("smartedu", mapped["inspection"]["inspector_id"])
        metadata = mapped["resolved_resource"]["metadata"]
        self.assertEqual("native-resource-9", metadata["resource_id"])
        self.assertNotEqual(candidate["resource_id"], metadata["resource_id"])
        self.assertEqual("三年级", metadata["grade"])
        self.assertEqual("科学", metadata["subject"])
        self.assertEqual("国家中小学智慧教育平台", metadata["provider"])
        self.assertTrue(
            any(
                item["kind"] == "document"
                and item["scope"] == "representation"
                and item["role"] == "companion"
                and item["mime_type"] == "application/pdf"
                and item["materializable"] is False
                for item in mapped["resolved_resource"]["representations"]
            )
        )

    def test_smartedu_course_uses_non_primary_course_webpage_representation(self) -> None:
        candidate = resource(
            platform="smartedu",
            source_url="https://basic.smartedu.cn/qualityCourse?courseId=course-9",
            resource_type="course",
            metadata={"course_id": "course-9", "provider": "SmartEdu"},
        )
        mapped, _ = inspect_with(
            SmartEduInspector,
            candidate,
            FakeResponse(final_url=candidate["source_url"]),
        )
        self.assertTrue(
            any(
                item["kind"] == "webpage"
                and item["container"] == "course"
                and item["scope"] == "representation"
                and item["role"] == "companion"
                and item["materializable"] is False
                for item in mapped["resolved_resource"]["representations"]
            )
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
