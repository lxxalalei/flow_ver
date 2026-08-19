"""Focused tests for the unified minimal SessionStore."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from education_resource_mcp.sessions import SessionError, SessionStore


class UnifiedSessionStoreTests(unittest.TestCase):
    def test_cookie_capture_keeps_only_platform_domain(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            result = store.save(
                "bilibili",
                {
                    "cookies": [
                        {"name": "ignore", "value": "x", "domain": ".example.com"},
                        {"name": "SESSDATA", "value": "abc", "domain": ".bilibili.com"},
                    ]
                },
            )
            self.assertEqual(result["status"], "stored")
            data = store.get_session_data("bilibili")
            self.assertEqual(["SESSDATA"], [item["name"] for item in data["cookies"]])

    def test_broad_smartedu_storage_is_filtered_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            huge_irrelevant = {f"irrelevant-{i}": "x" * 2048 for i in range(700)}
            huge_irrelevant["accessToken"] = "TOKEN"
            result = store.save(
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": huge_irrelevant,
                },
            )
            self.assertEqual(result["stored_credential_count"], 1)
            self.assertEqual(
                {"tokens": {"accessToken": "TOKEN"}},
                store.get_session_data("smartedu"),
            )

    def test_smartedu_double_wrapped_token_is_extracted(self) -> None:
        # 真实页面里 ND_UC_AUTH-...&token 的值是 {"value": "{...}"}：
        # access_token 在第二层 JSON 字符串内部，只解一层拿不到。
        inner = json.dumps(
            {
                "source_token_account_type": "passport-xedu",
                "access_token": "INNER-TOKEN",
                "x-nd-auth": "mac-credentials",
            }
        )
        wrapped = json.dumps({"value": inner})
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            result = store.save(
                "smartedu",
                {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {
                        "ND_UC_AUTH-7b15f2a8&ncet-xedu&token": wrapped
                    },
                },
            )
            self.assertEqual("stored", result["status"])
            self.assertEqual(
                {"tokens": {"accessToken": "INNER-TOKEN", "x-nd-auth": "mac-credentials"}},
                store.get_session_data("smartedu"),
            )

    def test_douyin_keeps_cookie_and_xmst_only(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save(
                "douyin",
                {
                    "cookies": [
                        {"name": "sid", "value": "v", "domain": ".douyin.com"}
                    ],
                    "storage_origin": "https://www.douyin.com",
                    "local_storage": {"xmst": "MS", "unrelated": "discard"},
                },
            )
            data = store.get_session_data("douyin")
            self.assertEqual("MS", data["local_storage"]["xmst"])
            self.assertNotIn("unrelated", data["local_storage"])

    def test_public_platform_never_requests_login(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            status = store.get_status(["annas-archive"])[0]
            self.assertEqual(status.status, "not_required")
            guide = store.login_guide("annas-archive")
            self.assertFalse(guide["requires_login"])
            self.assertEqual([], guide["steps"])

    def test_wrong_domain_cookie_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            with self.assertRaises(SessionError) as ctx:
                store.save(
                    "bilibili",
                    {"cookies": [{"name": "x", "value": "y", "domain": ".example.com"}]},
                )
            self.assertEqual("SESSION_EMPTY", ctx.exception.code)

    def test_bilibili_probe_uses_stored_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save(
                "bilibili",
                {"cookies": [{"name": "SESSDATA", "value": "abc", "domain": ".bilibili.com"}]},
            )
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies",
                return_value=(200, '{"data":{"isLogin":true}}'),
            ) as probe:
                result = store.validate("bilibili")
            self.assertEqual("valid", result["probe_status"])
            self.assertIn("SESSDATA=abc", probe.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
