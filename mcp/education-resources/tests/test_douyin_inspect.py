"""Targeted tests for the Douyin detail-API inspector."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from education_resource_mcp.adapters.inspect_douyin import DouyinInspector  # noqa: E402


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self, n: int | None = None) -> bytes:
        if n is None:
            return self._body
        result = self._body[:n]
        return result

    def close(self) -> None:
        pass


class _FakeSessionStore:
    def __init__(self, cookie: str | None = "sid=fake") -> None:
        self._cookie = cookie

    def get_session_data(self, platform: str):
        if self._cookie is None:
            return None
        return {"cookies": [{"name": "sid", "value": "fake"}]}


def _detail_body(aweme_id: str = "7123456789", *, has_video: bool = True) -> str:
    import json

    detail: dict = {
        "aweme_detail": {
            "aweme_id": aweme_id,
            "desc": "测试视频",
            "author": {"nickname": "测试作者"},
            "statistics": {"play_count": 1000, "digg_count": 200, "comment_count": 50},
        }
    }
    if has_video:
        detail["aweme_detail"]["video"] = {
            "play_addr": {"url_list": ["https://v.douyin.com/video.mp4"]}
        }
    return json.dumps(detail)


class DouyinInspectorTests(unittest.TestCase):
    def _resource(self, **overrides):
        base = {
            "resource_id": "res_1",
            "platform": "douyin",
            "source_url": "https://www.douyin.com/video/7123456789",
            "title": "测试视频",
        }
        base.update(overrides)
        return base

    def test_concrete_mp4_primary_when_detail_available(self) -> None:
        inspector = DouyinInspector(
            session_store=_FakeSessionStore(),
            detail_transport=lambda req: _FakeResponse(_detail_body()),
            sign_func=lambda qs, ua: "fake_a_bogus",
        )
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        self.assertEqual("resolved", payload["resolution_status"])
        resolved = payload["resolved_resource"]
        self.assertEqual("available", resolved["availability"]["status"])
        self.assertEqual("video", resolved["resource_type"])
        reps = resolved["representations"]
        self.assertEqual(1, len(reps))
        primary = reps[0]
        self.assertEqual("video", primary["kind"])
        self.assertEqual("mp4", primary["container"])
        self.assertEqual("primary_resource", primary["scope"])
        self.assertEqual("primary", primary["role"])
        self.assertEqual("available", primary["technical_availability"])
        self.assertTrue(primary["materializable"])
        self.assertEqual("video/mp4", primary["mime_type"])

    def test_auth_required_without_session(self) -> None:
        inspector = DouyinInspector(
            session_store=_FakeSessionStore(cookie=None),
            detail_transport=lambda req: _FakeResponse(_detail_body()),
            sign_func=lambda qs, ua: "fake_a_bogus",
        )
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        self.assertEqual("partial", payload["resolution_status"])
        self.assertEqual(
            "auth_required",
            payload["resolved_resource"]["availability"]["status"],
        )
        self.assertEqual("AUTH_REQUIRED", payload["failures"][0]["code"])

    def test_sign_failure_is_structured(self) -> None:
        from education_resource_mcp.adapters.douyin import _AdapterError

        def fail_sign(qs, ua):
            raise _AdapterError("SIGN_FAILED", "系统未安装 Node.js", False)

        inspector = DouyinInspector(
            session_store=_FakeSessionStore(),
            detail_transport=lambda req: _FakeResponse(_detail_body()),
            sign_func=fail_sign,
        )
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        self.assertEqual("partial", payload["resolution_status"])
        self.assertEqual("SIGN_FAILED", payload["failures"][0]["code"])

    def test_no_video_url_means_not_materializable(self) -> None:
        inspector = DouyinInspector(
            session_store=_FakeSessionStore(),
            detail_transport=lambda req: _FakeResponse(_detail_body(has_video=False)),
            sign_func=lambda qs, ua: "fake_a_bogus",
        )
        result = inspector.inspect(self._resource())
        payload = result.to_mapping()

        self.assertEqual("partial", payload["resolution_status"])
        self.assertEqual("CONTENT_VALIDATION_FAILED", payload["failures"][0]["code"])
        self.assertEqual([], payload["resolved_resource"]["representations"])

    def test_invalid_aweme_url_rejected(self) -> None:
        inspector = DouyinInspector(
            session_store=_FakeSessionStore(),
            detail_transport=lambda req: _FakeResponse(_detail_body()),
            sign_func=lambda qs, ua: "fake_a_bogus",
        )
        result = inspector.inspect(
            self._resource(source_url="https://www.douyin.com/not-a-video")
        )
        payload = result.to_mapping()

        self.assertEqual("CONTENT_VALIDATION_FAILED", payload["failures"][0]["code"])

    def test_result_contains_no_download_url(self) -> None:
        """The public result must not leak the dynamic video stream URL."""

        inspector = DouyinInspector(
            session_store=_FakeSessionStore(),
            detail_transport=lambda req: _FakeResponse(_detail_body()),
            sign_func=lambda qs, ua: "fake_a_bogus",
        )
        import json

        payload = inspector.inspect(self._resource()).to_mapping()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("v.douyin.com/video.mp4", text)
        self.assertNotIn("url_list", text)


if __name__ == "__main__":
    unittest.main()
