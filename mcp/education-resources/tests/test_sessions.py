"""Tests for the platform session store."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from education_resource_mcp.sessions import (
    SessionStore,
    PLATFORM_REGISTRY,
    _smartedu_auth_headers,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class SessionStoreTests(unittest.TestCase):
    def _store(self, data_dir: Path) -> SessionStore:
        return SessionStore(data_dir)

    def test_missing_platform_returns_missing_status(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            statuses = store.get_status(["bilibili"])
        self.assertEqual(statuses[0].status, "missing")
        self.assertEqual(statuses[0].platform, "bilibili")

    def test_save_and_read_back_status(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            result = store.save("bilibili", {"cookies": [{"name": "SESSDATA", "value": "abc"}]})
            self.assertEqual(result["status"], "valid")

            statuses = store.get_status(["bilibili"])
            self.assertEqual(statuses[0].status, "valid")
            self.assertIsNotNone(statuses[0].captured_at)

    def test_expired_session_reports_expired(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            past = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
            store.save("zhihu", {"cookies": []}, expires_at=past)

            statuses = store.get_status(["zhihu"])
            self.assertEqual(statuses[0].status, "expired")

    def test_get_session_data_returns_none_for_expired(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            past = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
            store.save("bilibili", {"cookies": [{"name": "k", "value": "v"}]}, expires_at=past)

            self.assertIsNone(store.get_session_data("bilibili"))

    def test_get_session_data_returns_data_for_valid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            store.save("bilibili", {"cookies": [{"name": "k", "value": "v"}]})

            data = store.get_session_data("bilibili")
            self.assertIsNotNone(data)
            self.assertEqual(data["cookies"][0]["name"], "k")

    def test_delete_removes_session(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            store.save("bilibili", {"cookies": []})
            result = store.delete("bilibili")
            self.assertTrue(result["deleted"])

            statuses = store.get_status(["bilibili"])
            self.assertEqual(statuses[0].status, "missing")

    def test_batch_status_for_multiple_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            store.save("bilibili", {"cookies": []})
            # zhihu not saved

            statuses = store.get_status(["bilibili", "zhihu"])
            by_platform = {s.platform: s.status for s in statuses}
            self.assertEqual(by_platform["bilibili"], "valid")
            self.assertEqual(by_platform["zhihu"], "missing")

    def test_all_known_platforms_when_no_filter(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            statuses = store.get_status()
            platform_ids = {s.platform for s in statuses}
            self.assertEqual(platform_ids, set(PLATFORM_REGISTRY))

    def test_unknown_platform_raises_on_save(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d))
            with self.assertRaises(ValueError):
                store.save("unknown_platform", {"cookies": []})


class SessionValidateTests(unittest.TestCase):
    """Active probe validation — HTTP is mocked, no real network."""

    _BILI_COOKIES = {"cookies": [{"name": "SESSDATA", "value": "abc"}, {"name": "jct", "value": "x"}]}

    def test_bilibili_logged_in_reports_valid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("bilibili", self._BILI_COOKIES)
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies",
                return_value=(200, '{"data":{"isLogin":true}}'),
            ) as mock_probe:
                result = store.validate("bilibili")
        self.assertEqual(result["probe_status"], "valid")
        mock_probe.assert_called_once()
        # cookie header built from stored session_data
        self.assertIn("SESSDATA=abc", mock_probe.call_args.args[1])

    def test_bilibili_logged_out_reports_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("bilibili", self._BILI_COOKIES)
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies",
                return_value=(200, '{"data":{"isLogin":false}}'),
            ):
                result = store.validate("bilibili")
        self.assertEqual(result["probe_status"], "invalid")

    def test_zhihu_ok_by_2xx_default_check(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("zhihu", {"cookies": [{"name": "z_c0", "value": "tok"}]})
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies",
                return_value=(200, '{"id":"abc"}'),
            ):
                result = store.validate("zhihu")
        self.assertEqual(result["probe_status"], "valid")

    def test_zhihu_unauthorized_reports_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("zhihu", {"cookies": [{"name": "z_c0", "value": "tok"}]})
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies",
                return_value=(401, ""),
            ):
                result = store.validate("zhihu")
        self.assertEqual(result["probe_status"], "invalid")

    def test_missing_session_reports_missing_without_probing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies"
            ) as mock_probe:
                result = store.validate("bilibili")
        self.assertEqual(result["probe_status"], "missing")
        mock_probe.assert_not_called()

    def test_platform_without_probe_url_reports_no_probe(self) -> None:
        # weibo requires auth but has no probe_url configured
        self.assertIsNone(PLATFORM_REGISTRY["weibo"].probe_url)
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("weibo", {"cookies": [{"name": "SUB", "value": "s"}]})
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies"
            ) as mock_probe:
                result = store.validate("weibo")
        self.assertEqual(result["probe_status"], "no_probe")
        mock_probe.assert_not_called()

    def test_no_auth_platform_reports_no_probe(self) -> None:
        # annas-archive is registered as auth_kind="none" (no login)
        self.assertEqual(PLATFORM_REGISTRY["annas-archive"].auth_kind, "none")
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies"
            ) as mock_probe:
                result = store.validate("annas-archive")
        self.assertEqual(result["probe_status"], "no_probe")
        mock_probe.assert_not_called()

    def test_network_error_reports_probe_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("bilibili", self._BILI_COOKIES)
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies",
                side_effect=URLError("connection refused"),
            ):
                result = store.validate("bilibili")
        self.assertEqual(result["probe_status"], "probe_error")

    def test_expired_session_reports_invalid_without_probing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            past = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
            store.save("bilibili", self._BILI_COOKIES, expires_at=past)
            with patch(
                "education_resource_mcp.sessions.probe_with_cookies"
            ) as mock_probe:
                result = store.validate("bilibili")
        self.assertEqual(result["probe_status"], "invalid")
        mock_probe.assert_not_called()

    def test_unknown_platform_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            with self.assertRaises(ValueError):
                store.validate("not_a_platform")

    # -- token-type platforms (smartedu) -------------------------------

    def test_smartedu_auth_headers_builds_bearer(self) -> None:
        h = _smartedu_auth_headers(
            {"tokens": {"accessToken": "TOK"}, "headers": {"x-nd-auth": "X1"}}
        )
        self.assertEqual(h["Authorization"], "Bearer TOK")
        self.assertEqual(h["accessToken"], "TOK")
        self.assertEqual(h["x-nd-auth"], "X1")

    def test_smartedu_auth_headers_empty_when_no_token(self) -> None:
        h = _smartedu_auth_headers({"headers": {"x-nd-auth": "X1"}})
        self.assertNotIn("Authorization", h)
        self.assertNotIn("accessToken", h)

    def test_token_session_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("smartedu", {"tokens": {"accessToken": "TOK"}, "headers": {"x-nd-auth": "X1"}})
            data = store.get_session_data("smartedu")
        self.assertEqual(data["tokens"]["accessToken"], "TOK")

    def test_validate_smartedu_without_probe_is_no_probe(self) -> None:
        self.assertIsNone(PLATFORM_REGISTRY["smartedu"].probe_url)
        self.assertEqual(PLATFORM_REGISTRY["smartedu"].auth_kind, "token")
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("smartedu", {"tokens": {"accessToken": "TOK"}})
            with patch("education_resource_mcp.sessions.probe_with_headers") as mock_probe:
                result = store.validate("smartedu")
        self.assertEqual(result["probe_status"], "no_probe")
        mock_probe.assert_not_called()

    def test_validate_token_platform_probes_with_auth_headers(self) -> None:
        cfg = PLATFORM_REGISTRY["smartedu"]
        probed = dataclasses.replace(cfg, probe_url="https://example.test/smartedu/me")
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("smartedu", {"tokens": {"accessToken": "TOK"}})
            with patch.dict(PLATFORM_REGISTRY, {"smartedu": probed}):
                with patch(
                    "education_resource_mcp.sessions.probe_with_headers",
                    return_value=(200, '{"name":"u"}'),
                ) as mock_probe:
                    result = store.validate("smartedu")
        self.assertEqual(result["probe_status"], "valid")
        sent_headers = mock_probe.call_args.args[1]
        self.assertEqual(sent_headers["Authorization"], "Bearer TOK")
        self.assertEqual(sent_headers["accessToken"], "TOK")

    def test_validate_token_platform_rejected_when_401(self) -> None:
        cfg = PLATFORM_REGISTRY["smartedu"]
        probed = dataclasses.replace(cfg, probe_url="https://example.test/smartedu/me")
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            store.save("smartedu", {"tokens": {"accessToken": "TOK"}})
            with patch.dict(PLATFORM_REGISTRY, {"smartedu": probed}):
                with patch(
                    "education_resource_mcp.sessions.probe_with_headers",
                    return_value=(401, ""),
                ):
                    result = store.validate("smartedu")
        self.assertEqual(result["probe_status"], "invalid")


if __name__ == "__main__":
    unittest.main()
