"""Targeted hermetic tests for the Bilibili DASH-verification inspector.

The landing-page fetch goes through an injected fake transport so the suite
never touches bilibili.com live (Bilibili IP risk controls intermittently
return 412, which would otherwise decide the suite's green/red state).
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from education_resource_mcp.adapters.inspect_bilibili import BilibiliInspector  # noqa: E402


def _page_body(title: str = "测试视频") -> bytes:
    return (
        "<!doctype html><html lang=\"zh-CN\"><head>"
        "<meta charset=\"utf-8\">"
        f"<title>{title}</title>"
        "<meta name=\"description\" content=\"测试\">"
        "</head><body><p>内容</p></body></html>"
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, *, status: int = 200, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = headers
        self._body = body
        self._offset = 0

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def geturl(self) -> str:
        return "https://www.bilibili.com/video/BV1xx411c7mD"

    def close(self) -> None:
        pass


class QueueTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


def _page_response() -> FakeResponse:
    return FakeResponse(
        headers={"Content-Type": "text/html; charset=utf-8"},
        body=_page_body(),
    )


class BilibiliInspectorTests(unittest.TestCase):
    def _inspector(self, verify_func=None, transport=None):
        return BilibiliInspector(
            playurl_verify_func=verify_func,
            transport=transport,
        )

    def _resource(self, **overrides):
        base = {
            "resource_id": "r1",
            "platform": "bilibili",
            "source_url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "title": "测试视频",
            "metadata": {"bvid": "BV1xx411c7mD"},
        }
        base.update(overrides)
        return base

    def test_verified_dash_produces_materializable_primary(self) -> None:
        def verify(bvid, cookie):
            assert bvid == "BV1xx411c7mD"
            return {"title": "测试视频"}

        inspector = self._inspector(verify, QueueTransport(_page_response()))
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        self.assertEqual("resolved", payload["resolution_status"])
        resolved = payload["resolved_resource"]
        self.assertEqual("available", resolved["availability"]["status"])
        primaries = [
            r for r in resolved["representations"]
            if r.get("role") == "primary" and r.get("kind") == "video"
        ]
        self.assertEqual(1, len(primaries))
        self.assertTrue(primaries[0]["materializable"])
        self.assertEqual("mp4", primaries[0]["container"])
        self.assertEqual("primary_resource", primaries[0]["scope"])
        self.assertEqual("available", primaries[0]["technical_availability"])

    def test_verify_failure_falls_back_to_non_materializable(self) -> None:
        def verify(bvid, cookie):
            return None  # DASH not available or API failure

        inspector = self._inspector(verify, QueueTransport(_page_response()))
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        videos = [
            r for r in payload["resolved_resource"]["representations"]
            if r.get("kind") == "video"
        ]
        # No materializable primary; at most a non-materializable companion
        for v in videos:
            if v.get("role") == "primary":
                self.assertFalse(v["materializable"])

    def test_result_does_not_leak_stream_url(self) -> None:
        def verify(bvid, cookie):
            return {"title": "t"}

        inspector = self._inspector(verify, QueueTransport(_page_response()))

        import json

        payload = inspector.inspect(self._resource()).to_mapping()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("baseUrl", text)
        self.assertNotIn("playUrlList", text)


if __name__ == "__main__":
    unittest.main()
