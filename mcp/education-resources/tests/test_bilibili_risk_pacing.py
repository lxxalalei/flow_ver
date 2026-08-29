"""Bilibili risk-control pacing: page pacing and NETWORK_BLOCKED backoff.

No live network; backoff waits are shrunk to near-zero via the class
attributes exposed for exactly this purpose.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters.bilibili import (
    BilibiliSearchAdapter,
    _AdapterError,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


def _archive(index: int, *, mid: str = "2142762") -> dict:
    return {
        "bvid": f"BV1TEST{index:04d}",
        "title": f"视频 {index}",
        "desc": f"简介 {index}",
        "pubdate": 1700000000 + index,
        "owner": {"mid": int(mid), "name": "测试UP"},
        "stat": {"view": 100 + index},
    }


def _creator_page(archives: list[dict]) -> dict:
    return {"code": 0, "data": {"list": {"vlist": archives}}}


class BilibiliRiskPacingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        settings = Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=1,
        )
        self.adapter = BilibiliSearchAdapter(SessionStore(root), settings)
        self.adapter._BACKOFF_WAITS = (0.01, 0.02)
        self.adapter._BACKOFF_BUDGET_SECONDS = 1.0
        self.adapter._PAGE_PACE_SECONDS = 0.0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_netblock_retries_with_backoff_then_succeeds(self) -> None:
        calls = []
        sleeps = []

        def fake_once(url: str, *, referer: str, cookie: str) -> dict:
            del referer, cookie
            calls.append(url)
            if len(calls) < 3:
                raise _AdapterError("NETWORK_BLOCKED", "B站请求触发 HTTP 412 风控", True)
            return {"code": 0, "data": {"ok": True}}

        self.adapter._request_json_once = fake_once  # type: ignore[method-assign]
        original_sleep = time.sleep
        try:
            time.sleep = lambda sec: sleeps.append(sec)  # type: ignore[assignment]
            result = self.adapter._request_json(
                "https://api.example/x", referer="https://space.bilibili.com/1", cookie=""
            )
        finally:
            time.sleep = original_sleep  # type: ignore[assignment]

        self.assertEqual({"code": 0, "data": {"ok": True}}, result)
        self.assertEqual(3, len(calls))
        self.assertEqual([0.01, 0.02], sleeps)

    def test_non_netblock_error_propagates_immediately(self) -> None:
        calls = []

        def fake_once(url: str, *, referer: str, cookie: str) -> dict:
            del url, referer, cookie
            calls.append(1)
            raise _AdapterError("AUTH_REQUIRED", "登录态不可用", False)

        self.adapter._request_json_once = fake_once  # type: ignore[method-assign]
        with self.assertRaises(_AdapterError) as ctx:
            self.adapter._request_json(
                "https://api.example/x", referer="https://space.bilibili.com/1", cookie=""
            )
        self.assertEqual("AUTH_REQUIRED", ctx.exception.code)
        self.assertEqual(1, len(calls))

    def test_persistent_netblock_gives_up_within_budget(self) -> None:
        calls = []
        sleeps = []

        def fake_once(url: str, *, referer: str, cookie: str) -> dict:
            del url, referer, cookie
            calls.append(1)
            raise _AdapterError("NETWORK_BLOCKED", "B站请求触发 HTTP 412 风控", True)

        self.adapter._request_json_once = fake_once  # type: ignore[method-assign]
        original_sleep = time.sleep
        try:
            time.sleep = lambda sec: sleeps.append(sec)  # type: ignore[assignment]
            with self.assertRaises(_AdapterError) as ctx:
                self.adapter._request_json(
                    "https://api.example/x", referer="https://space.bilibili.com/1", cookie=""
                )
        finally:
            time.sleep = original_sleep  # type: ignore[assignment]

        self.assertEqual("NETWORK_BLOCKED", ctx.exception.code)
        # Budget 1.0s with waits 0.01/0.02 -> bounded attempts, not infinite.
        self.assertLess(len(calls), 100)
        self.assertGreater(len(calls), 1)

    def test_creator_uses_paced_smaller_pages(self) -> None:
        calls: list[str] = []
        from urllib.parse import parse_qs, urlparse

        def fake_request(url: str, *, referer: str, cookie: str) -> dict:
            del referer, cookie
            calls.append(url)
            query = parse_qs(urlparse(url).query)
            page = int(query["pn"][0])
            if page == 1:
                return _creator_page([_archive(i) for i in range(1, 21)])
            return _creator_page([_archive(21)])

        self.adapter._request_json = fake_request  # type: ignore[method-assign]
        self.adapter._wbi_keys = lambda cookie: ("a" * 32, "b" * 32)  # type: ignore[method-assign]
        resources = list(self.adapter.iter_creator("https://space.bilibili.com/2142762"))

        self.assertEqual(21, len(resources))
        self.assertEqual(2, len(calls))
        first_query = parse_qs(urlparse(calls[0]).query)
        self.assertEqual(["20"], first_query["ps"])


if __name__ == "__main__":
    unittest.main()
