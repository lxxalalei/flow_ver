from __future__ import annotations

import json
import unittest

from education_resource_mcp.adapters.inspect_annas_archive import AnnasArchiveInspector
from education_resource_mcp.adapters.inspect_nlc import NlcInspector
from education_resource_mcp.adapters.inspect_ximalaya import XimalayaInspector


PUBLIC_ADDRESS = "93.184.216.34"


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        final_url: str,
    ) -> None:
        self.status = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.body = body or "<html><head><title>公开详情</title></head><body>detail</body></html>".encode()
        self.offset = 0
        self.final_url = final_url
        self.read_calls = 0
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        self.read_calls += 1
        if amount < 0:
            amount = len(self.body) - self.offset
        value = self.body[self.offset : self.offset + amount]
        self.offset += len(value)
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


def resource(platform: str, source_url: str, **metadata) -> dict:
    return {
        "resource_id": "res_" + "a" * 16,
        "platform": platform,
        "title": "公开教育资源",
        "source_url": source_url,
        "resource_type": "other",
        "metadata": metadata,
    }


def make_inspector(cls, transport: QueueTransport):
    return cls(resolver=public_resolver, transport=transport, timeout=0.25)


class PlatformInspectorCatalogTests(unittest.TestCase):
    def test_nlc_enrichment_and_book_representation(self) -> None:
        transport = QueueTransport(
            FakeResponse(final_url="https://www.nlc.cn/catalog/42")
        )
        candidate = resource(
            "nlc",
            "https://find.nlc.cn/search/showDocDetails?docId=42",
            author="国家图书馆编",
            publisher="教育出版社",
            isbn="9780306406157",
            publication_year=2024,
            edition="第 2 版",
            call_number="G624.3/42",
        )

        mapped = make_inspector(NlcInspector, transport).inspect(candidate).to_mapping()
        resolved = mapped["resolved_resource"]

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("book", resolved["resource_type"])
        self.assertEqual("nlc", mapped["inspection"]["inspector_id"])
        self.assertEqual("platform_bounded_get", mapped["inspection"]["method"])
        self.assertEqual("9780306406157", resolved["metadata"]["isbn"])
        self.assertEqual("国家图书馆编", resolved["creator"])
        self.assertEqual("G624.3/42", resolved["metadata"]["call_number"])
        self.assertIn("webpage", {item["kind"] for item in resolved["representations"]})

    def test_ximalaya_enrichment_has_audio_representation_and_landing_page(self) -> None:
        transport = QueueTransport(
            FakeResponse(final_url="https://www.ximalaya.com/album/7788")
        )
        candidate = resource(
            "ximalaya",
            "https://www.ximalaya.com/album/7788",
            author="科学主播",
            duration_seconds=321,
            tracks=12,
            play_count=9001,
        )

        mapped = make_inspector(XimalayaInspector, transport).inspect(candidate).to_mapping()
        resolved = mapped["resolved_resource"]
        representations = resolved["representations"]

        self.assertEqual("audio", resolved["resource_type"])
        self.assertEqual("科学主播", resolved["creator"])
        self.assertEqual("7788", resolved["metadata"]["album_id"])
        self.assertEqual(321, resolved["metadata"]["duration_seconds"])
        self.assertEqual(12, resolved["metadata"]["track_count"])
        self.assertEqual(9001, resolved["metadata"]["play_count"])
        self.assertEqual("audio", representations[0]["kind"])
        self.assertEqual("representation", representations[0]["scope"])
        self.assertEqual("companion", representations[0]["role"])
        self.assertFalse(representations[0]["materializable"])
        self.assertEqual("webpage", representations[1]["kind"])
        self.assertEqual("landing_page", representations[1]["scope"])
        self.assertEqual("landing", representations[1]["role"])
        self.assertEqual("ximalaya", mapped["inspection"]["inspector_id"])

    def test_annas_archive_is_libgen_backed_and_requires_valid_md5(self) -> None:
        md5 = "ABCDEF0123456789ABCDEF0123456789"
        transport = QueueTransport(
            FakeResponse(final_url="https://libgen.test/book/42")
        )
        candidate = resource(
            "annas-archive",
            "https://libgen.test/book/42",
            platform_signals={
                "md5": md5,
                "isbn": "9780306406157",
                "author": "公开作者",
                "publisher": "公开出版社",
                "year": 2023,
                "extension": "pdf",
                "size_bytes": 2048,
                "language": "en",
            },
        )

        mapped = make_inspector(AnnasArchiveInspector, transport).inspect(candidate).to_mapping()
        resolved = mapped["resolved_resource"]
        representation = resolved["representations"][0]

        self.assertEqual("resolved", mapped["resolution_status"])
        self.assertEqual("book", resolved["resource_type"])
        self.assertEqual(md5.casefold(), resolved["metadata"]["md5"])
        self.assertEqual(2048, resolved["metadata"]["size_bytes"])
        self.assertEqual("document", representation["kind"])
        self.assertEqual("pdf", representation["container"])
        self.assertIn("Libgen", representation["rights_hint"])
        self.assertFalse(representation["materializable"])
        self.assertEqual("annas_archive", mapped["inspection"]["inspector_id"])

    def test_annas_archive_invalid_md5_is_blocked_without_network(self) -> None:
        transport = QueueTransport()
        candidate = resource("annas-archive", "https://libgen.test/book/42")
        candidate["metadata"] = {"md5": "not-a-valid-md5"}

        mapped = make_inspector(AnnasArchiveInspector, transport).inspect(candidate).to_mapping()
        self.assertEqual("unresolved", mapped["resolution_status"])
        self.assertEqual("policy_blocked", mapped["resolved_resource"]["availability"]["status"])
        self.assertEqual("PLATFORM_VALIDATION_BLOCKED", mapped["failures"][0]["code"])
        self.assertEqual("annas-archive", mapped["failures"][0]["platform"])
        self.assertEqual([], transport.requests)

    def test_nlc_and_ximalaya_wrong_hosts_are_blocked_before_transport(self) -> None:
        cases = (
            (NlcInspector, "nlc", "https://www.nlc.cn.evil.test/item"),
            (NlcInspector, "nlc", "https://example.com.evil/item"),
            (XimalayaInspector, "ximalaya", "https://www.ximalaya.com.evil.test/album/1"),
            (XimalayaInspector, "ximalaya", "https://example.com/album/1"),
        )
        for inspector_class, platform, source_url in cases:
            with self.subTest(source_url=source_url):
                transport = QueueTransport()
                mapped = make_inspector(inspector_class, transport).inspect(
                    resource(platform, source_url)
                ).to_mapping()
                self.assertEqual("policy_blocked", mapped["resolved_resource"]["availability"]["status"])
                self.assertEqual("PLATFORM_POLICY_BLOCKED", mapped["failures"][0]["code"])
                self.assertEqual(platform, mapped["failures"][0]["platform"])
                self.assertEqual([], transport.requests)

    def test_platform_host_policy_is_applied_to_redirect_hops(self) -> None:
        response = FakeResponse(
            status=302,
            headers={"Location": "https://public.example/redirected"},
            final_url="https://www.nlc.cn/catalog/1",
        )
        transport = QueueTransport(response)
        mapped = make_inspector(NlcInspector, transport).inspect(
            resource("nlc", "https://www.nlc.cn/catalog/1")
        ).to_mapping()

        self.assertEqual("policy_blocked", mapped["resolved_resource"]["availability"]["status"])
        self.assertEqual("PLATFORM_POLICY_BLOCKED", mapped["failures"][0]["code"])
        self.assertEqual(1, len(transport.requests))

    def test_auth_and_not_found_statuses_are_preserved(self) -> None:
        cases = (
            (NlcInspector, "nlc", "https://www.nlc.cn/catalog/1", {}),
            (XimalayaInspector, "ximalaya", "https://www.ximalaya.com/album/1", {}),
            (
                AnnasArchiveInspector,
                "annas-archive",
                "https://libgen.test/book/1",
                {"md5": "0123456789abcdef0123456789abcdef"},
            ),
        )
        for status in (401, 404):
            for inspector_class, platform, source_url, metadata in cases:
                with self.subTest(status=status, platform=platform):
                    transport = QueueTransport(
                        FakeResponse(status=status, final_url=source_url)
                    )
                    mapped = make_inspector(inspector_class, transport).inspect(
                        resource(platform, source_url, **metadata)
                    ).to_mapping()
                    expected = "auth_required" if status == 401 else "unavailable"
                    self.assertEqual(expected, mapped["resolved_resource"]["availability"]["status"])
                    self.assertEqual(platform, mapped["failures"][0]["platform"])
                    self.assertEqual(
                        "platform_bounded_get", mapped["inspection"]["method"]
                    )

    def test_output_has_no_locator_bytes_headers_or_secret(self) -> None:
        candidate = resource(
            "nlc",
            "https://www.nlc.cn/catalog/1?token=private-token",
            author="公开作者",
            headers={"Authorization": "Bearer private-token"},
            cookie="private-cookie",
            local_path="/private/secret.pdf",
        )
        transport = QueueTransport(
            FakeResponse(final_url="https://www.nlc.cn/catalog/1")
        )
        mapped = make_inspector(NlcInspector, transport).inspect(candidate).to_mapping()
        encoded = json.dumps(mapped, ensure_ascii=False, sort_keys=True)

        for secret in ("private-token", "private-cookie", "/private/secret.pdf"):
            self.assertNotIn(secret, encoded)
        self.assertNotIn("source_url", encoded)
        self.assertNotIn("headers", encoded)
        self.assertNotIn("cookie", encoded)
        self.assertNotIn("token", encoded.casefold())

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(
                        key.casefold(),
                        {"url", "uri", "href", "path", "headers", "cookie", "token", "bytes"},
                    )
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
