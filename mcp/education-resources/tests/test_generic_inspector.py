from __future__ import annotations

import json
import unittest

from education_resource_mcp.adapters.inspect_generic import (
    GenericWebInspector,
    INSPECTION_MAX_BYTES,
)


PUBLIC_ADDRESS = "93.184.216.34"


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        final_url: str | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._offset = 0
        self._chunks = list(chunks) if chunks is not None else None
        self._final_url = final_url
        self.read_calls = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        self.read_calls += 1
        if self._chunks is not None:
            return self._chunks.pop(0) if self._chunks else b""
        if amount < 0:
            amount = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def geturl(self) -> str:
        return self._final_url or "https://public.test/resource"

    def close(self) -> None:
        self.closed = True


class QueueTransport:
    def __init__(self, *responses: FakeResponse, error: BaseException | None = None) -> None:
        self.responses = list(responses)
        self.error = error
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


def public_resolver(hostname: str, port: int):
    if hostname in {"public.test", "redirect.test", "evil.test"}:
        return (PUBLIC_ADDRESS,)
    return (PUBLIC_ADDRESS,)


def resource(**overrides):
    value = {
        "resource_id": "res_" + "a" * 16,
        "platform": "generic",
        "title": "检索到的资源",
        "source_url": "https://public.test/resource",
        "resource_type": "article",
        "metadata": {},
    }
    value.update(overrides)
    return value


def inspector(transport: QueueTransport, **kwargs) -> GenericWebInspector:
    return GenericWebInspector(
        resolver=public_resolver,
        transport=transport,
        timeout=0.25,
        **kwargs,
    )


class GenericWebInspectorTests(unittest.TestCase):
    def test_html_enrichment_uses_safe_metadata_and_fallbacks(self) -> None:
        body = """
        <!doctype html><html lang="zh-CN"><head>
          <title>太阳系入门</title>
          <meta name="description" content="一篇介绍行星的文章">
          <meta name="author" content="科学小组">
          <script type="application/ld+json">
            {"@type":"Article","datePublished":"2024-06-01","headline":"太阳系入门"}
          </script>
        </head><body><p>内容</p></body></html>
        """.encode("utf-8")
        response = FakeResponse(
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=body,
        )
        result = inspector(QueueTransport(response)).inspect(resource())
        mapped = result.to_mapping()

        self.assertEqual("resolved", mapped["resolution_status"])
        resolved = mapped["resolved_resource"]
        self.assertEqual("太阳系入门", resolved["title"])
        self.assertEqual("一篇介绍行星的文章", resolved["summary"])
        self.assertEqual("科学小组", resolved["creator"])
        self.assertEqual("zh-CN", resolved["language"])
        self.assertEqual("2024-06-01", resolved["metadata"]["published_date"])
        representation = resolved["representations"][0]
        self.assertEqual("webpage", representation["kind"])
        self.assertEqual("landing_page", representation["scope"])
        self.assertEqual("landing", representation["role"])
        self.assertTrue(representation["materializable"])
        self.assertEqual("inspection", representation["evidence"]["source"])
        self.assertEqual("bounded_get", mapped["inspection"]["method"])
        self.assertEqual("generic", mapped["inspection"]["inspector_id"])

    def test_pdf_file_is_classified_by_mime_and_magic(self) -> None:
        body = b"%PDF-1.7\nexample\n%%EOF"
        response = FakeResponse(
            headers={"Content-Type": "application/pdf", "Content-Length": str(len(body))},
            body=body,
        )
        result = inspector(QueueTransport(response)).inspect(
            resource(resource_type="document", title="资料 PDF")
        )
        mapped = result.to_mapping()
        representation = mapped["resolved_resource"]["representations"][0]

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("document", representation["kind"])
        self.assertEqual("application/pdf", representation["mime_type"])
        self.assertEqual("pdf", representation["container"])
        self.assertEqual("primary_resource", representation["scope"])
        self.assertEqual("primary", representation["role"])
        self.assertTrue(representation["materializable"])
        self.assertEqual("available", representation["technical_availability"])
        self.assertEqual(len(body), representation["size_bytes"])
        self.assertEqual(len(body), representation["size_bytes"])

    def test_declared_file_mime_without_magic_is_not_primary(self) -> None:
        body = b"this is not a verified PDF"
        response = FakeResponse(
            headers={"Content-Type": "application/pdf"},
            body=body,
        )
        mapped = inspector(QueueTransport(response)).inspect(
            resource(resource_type="document")
        ).to_mapping()
        representation = mapped["resolved_resource"]["representations"][0]

        self.assertNotEqual("primary_resource", representation["scope"])
        self.assertNotEqual("primary", representation["role"])
        self.assertFalse(representation["materializable"])
        self.assertEqual("unknown", representation["technical_availability"])

    def test_mime_magic_conflict_is_not_primary(self) -> None:
        body = b"%PDF-1.7\nnot actually the declared image"
        response = FakeResponse(
            headers={"Content-Type": "image/png"},
            body=body,
        )
        mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()
        representation = mapped["resolved_resource"]["representations"][0]

        self.assertEqual("partial", mapped["resolution_status"])
        self.assertNotEqual("primary_resource", representation["scope"])
        self.assertNotEqual("primary", representation["role"])
        self.assertFalse(representation["materializable"])

    def test_declared_file_size_does_not_block_inspection(self) -> None:
        body = b"%PDF-1.7\npreview"
        response = FakeResponse(
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(INSPECTION_MAX_BYTES * 10),
            },
            body=body,
        )
        mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual([], mapped["failures"])
        self.assertGreater(response.read_calls, 0)
        self.assertEqual(
            INSPECTION_MAX_BYTES * 10,
            mapped["resolved_resource"]["representations"][0]["size_bytes"],
        )

    def test_large_stream_is_classified_from_bounded_preview(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "application/pdf"},
            chunks=[b"%PDF-1.7\n" + b"x" * INSPECTION_MAX_BYTES],
        )
        mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual([], mapped["failures"])

    def test_initial_private_url_is_policy_blocked(self) -> None:
        transport = QueueTransport()
        mapped = inspector(transport).inspect(
            resource(source_url="http://127.0.0.1/private")
        ).to_mapping()

        self.assertEqual("policy_blocked", mapped["resolved_resource"]["availability"]["status"])
        self.assertEqual("NETWORK_BLOCKED", mapped["failures"][0]["code"])
        self.assertEqual([], transport.requests)

    def test_malicious_redirect_is_validated_before_following(self) -> None:
        first = FakeResponse(
            status=302,
            headers={"Location": "http://127.0.0.1/metadata"},
            final_url="https://public.test/resource",
        )
        transport = QueueTransport(first)
        mapped = inspector(transport).inspect(resource()).to_mapping()

        self.assertEqual("policy_blocked", mapped["resolved_resource"]["availability"]["status"])
        self.assertEqual("REDIRECT_BLOCKED", mapped["failures"][0]["code"])
        self.assertEqual(1, len(transport.requests))

    def test_auth_statuses_are_not_retried(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status):
                response = FakeResponse(status=status)
                mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()
                self.assertEqual(
                    "auth_required",
                    mapped["resolved_resource"]["availability"]["status"],
                )
                self.assertEqual("AUTH_REQUIRED", mapped["failures"][0]["code"])
                self.assertFalse(mapped["failures"][0]["retriable"])

    def test_not_found_statuses_are_unavailable(self) -> None:
        for status in (404, 410):
            with self.subTest(status=status):
                response = FakeResponse(status=status)
                mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()
                self.assertEqual(
                    "unavailable",
                    mapped["resolved_resource"]["availability"]["status"],
                )
                self.assertEqual("RESOURCE_NOT_FOUND", mapped["failures"][0]["code"])

    def test_retryable_http_and_timeout_failures_are_retriable(self) -> None:
        for status in (429, 500):
            with self.subTest(status=status):
                response = FakeResponse(status=status)
                mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()
                self.assertEqual(
                    "RATE_LIMITED" if status == 429 else "PLATFORM_UNAVAILABLE",
                    mapped["failures"][0]["code"],
                )
                self.assertTrue(mapped["failures"][0]["retriable"])

        mapped = inspector(QueueTransport(error=TimeoutError())).inspect(resource()).to_mapping()
        self.assertEqual("PARTIAL_FAILURE", mapped["failures"][0]["code"])
        self.assertTrue(mapped["failures"][0]["retriable"])

    def test_mime_magic_conflict_is_partial_with_warning(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "application/pdf"},
            body=b"<html><head><title>not a pdf</title></head><body>x</body></html>",
        )
        mapped = inspector(QueueTransport(response)).inspect(resource()).to_mapping()

        self.assertEqual("partial", mapped["resolution_status"])
        self.assertIn("响应媒体类型与内容格式不一致", mapped["inspection"]["warnings"])
        self.assertEqual("CONTENT_VALIDATION_FAILED", mapped["failures"][0]["code"])

    def test_result_contains_no_locator_headers_bytes_or_body(self) -> None:
        source_url = "https://public.test/private.pdf?token=secret"
        response = FakeResponse(
            headers={"Content-Type": "application/pdf"},
            body=b"%PDF-1.7\nprivate bytes",
        )
        mapped = inspector(QueueTransport(response)).inspect(
            resource(source_url=source_url)
        ).to_mapping()
        encoded = json.dumps(mapped, ensure_ascii=False, sort_keys=True)

        self.assertNotIn(source_url, encoded)
        self.assertNotIn("private bytes", encoded)

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(key.casefold(), {"url", "uri", "href", "path", "headers", "bytes"})
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)
            else:
                yield value

        for value in walk(mapped):
            self.assertFalse(isinstance(value, (bytes, bytearray, memoryview)))


if __name__ == "__main__":
    unittest.main()
