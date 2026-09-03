"""Douyin risk-control pacing: 403 classification, backoff, page pacing.

No live network; backoff waits are shrunk to near-zero via the class
attributes exposed for exactly this purpose (mirrors the bilibili suite).
"""

from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.error import HTTPError

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters import douyin as douyin_mod
from education_resource_mcp.adapters.douyin import (
    DouyinSearchAdapter,
    _AdapterError,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


class _FakeHTTPResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.headers = {"Content-Type": content_type}
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _http_error(code: int, body: bytes = b"") -> HTTPError:
    return HTTPError("https://www.douyin.com/x", code, "err", {}, io.BytesIO(body))


def _aweme(aweme_id: str, title: str) -> dict:
    return {
        "aweme_id": aweme_id,
        "desc": title,
        "author": {"nickname": "creator", "sec_uid": "sec_user_1"},
        "statistics": {},
        "create_time": 1700000000,
    }


class DouyinRiskPacingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        settings = Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=1,
        )
        store = SessionStore(root)
        store.save(
            "douyin",
            {"cookies": [{"name": "sessionid", "value": "abc", "domain": ".douyin.com"}]},
        )
        self.adapter = DouyinSearchAdapter(store, settings)
        self.adapter._BACKOFF_WAITS = (0.01, 0.02)
        self.adapter._BACKOFF_BUDGET_SECONDS = 1.0
        self.adapter._PAGE_PACE_SECONDS = 0.0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _patch_sleep(self) -> tuple[list[float], object]:
        sleeps: list[float] = []
        original_sleep = time.sleep
        time.sleep = lambda sec: sleeps.append(sec)  # type: ignore[assignment]
        return sleeps, original_sleep

    def test_argus_403_is_not_retried(self) -> None:
        calls: list[str] = []
        body = b"Blocked by ArgusSecurityPlugin Uifid Not Found"

        def fake_open(_request: object, timeout: float) -> _FakeHTTPResponse:
            del timeout
            calls.append("call")
            raise _http_error(403, body)

        with mock.patch.object(douyin_mod, "urlopen_with_fallback", fake_open):
            with self.assertRaises(_AdapterError) as ctx:
                self.adapter._request_json("https://www.douyin.com/x", "cookie")
        self.assertEqual("NETWORK_BLOCKED", ctx.exception.code)
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("Argus", ctx.exception.message)
        self.assertEqual(1, len(calls))

    def test_plain_403_retries_with_backoff_then_succeeds(self) -> None:
        calls: list[str] = []
        sleeps, original_sleep = self._patch_sleep()
        try:

            def fake_open(_request: object, timeout: float) -> _FakeHTTPResponse:
                del timeout
                calls.append("call")
                if len(calls) < 3:
                    raise _http_error(403)
                return _FakeHTTPResponse(b'{"status_code": 0}')

            with mock.patch.object(douyin_mod, "urlopen_with_fallback", fake_open):
                result = self.adapter._request_json(
                    "https://www.douyin.com/x", "cookie"
                )
        finally:
            time.sleep = original_sleep  # type: ignore[assignment]
        self.assertEqual({"status_code": 0}, result)
        self.assertEqual(3, len(calls))
        self.assertEqual([0.01, 0.02], sleeps)

    def test_401_is_auth_required_without_retry(self) -> None:
        calls: list[str] = []

        def fake_open(_request: object, timeout: float) -> _FakeHTTPResponse:
            del timeout
            calls.append("call")
            raise _http_error(401)

        with mock.patch.object(douyin_mod, "urlopen_with_fallback", fake_open):
            with self.assertRaises(_AdapterError) as ctx:
                self.adapter._request_json("https://www.douyin.com/x", "cookie")
        self.assertEqual("AUTH_REQUIRED", ctx.exception.code)
        self.assertEqual(1, len(calls))

    def test_non_json_body_raises_retryable_netblock(self) -> None:
        calls: list[str] = []
        sleeps, original_sleep = self._patch_sleep()
        try:

            def fake_open(_request: object, timeout: float) -> _FakeHTTPResponse:
                del timeout
                calls.append("call")
                return _FakeHTTPResponse(b"not json", content_type="text/html")

            with mock.patch.object(douyin_mod, "urlopen_with_fallback", fake_open):
                with self.assertRaises(_AdapterError) as ctx:
                    self.adapter._request_json("https://www.douyin.com/x", "cookie")
        finally:
            time.sleep = original_sleep  # type: ignore[assignment]
        self.assertEqual("NETWORK_BLOCKED", ctx.exception.code)
        self.assertTrue(ctx.exception.retryable)
        # retryable blocks go through backoff before giving up
        self.assertGreater(len(calls), 1)

    def test_persistent_plain_403_gives_up_within_budget(self) -> None:
        calls: list[str] = []
        sleeps, original_sleep = self._patch_sleep()
        try:

            def fake_open(_request: object, timeout: float) -> _FakeHTTPResponse:
                del timeout
                calls.append("call")
                raise _http_error(403)

            with mock.patch.object(douyin_mod, "urlopen_with_fallback", fake_open):
                with self.assertRaises(_AdapterError) as ctx:
                    self.adapter._request_json(
                        "https://www.douyin.com/x", "cookie"
                    )
        finally:
            time.sleep = original_sleep  # type: ignore[assignment]
        self.assertEqual("NETWORK_BLOCKED", ctx.exception.code)
        self.assertLess(len(calls), 100)
        self.assertGreater(len(calls), 1)

    def test_creator_pages_are_paced(self) -> None:
        pages = [
            {"aweme_list": [_aweme(str(i), f"v{i}") for i in range(1, 19)],
             "has_more": 1, "max_cursor": 100},
            {"aweme_list": [_aweme("19", "v19")], "has_more": 0, "max_cursor": 200},
        ]
        self.adapter._PAGE_PACE_SECONDS = 0.05
        sleeps, original_sleep = self._patch_sleep()
        try:
            self.adapter._request_json_once = lambda url, cookie, referer=None: pages.pop(0)  # type: ignore[method-assign]
            with mock.patch.object(douyin_mod, "sign_a_bogus", return_value="sig"):
                resources = list(
                    self.adapter.iter_creator("https://www.douyin.com/user/abc")
                )
        finally:
            time.sleep = original_sleep  # type: ignore[assignment]
        self.assertEqual(19, len(resources))
        # exactly one pacing sleep between the two pages
        self.assertEqual([0.05], [s for s in sleeps if s == 0.05])


if __name__ == "__main__":
    unittest.main()
