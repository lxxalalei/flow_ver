"""Tests for the Shuge (书格) public-storage search adapter and inspector."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from education_resource_mcp.adapters.shuge import BASE_URL, SEARCH_ROOT, ShugeSearchAdapter
from education_resource_mcp.adapters.inspect_shuge import ShugeInspector
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
    )


def _mock_response(body: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.status = status
    resp.headers = {"Content-Type": "application/json"}
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class ShugeSearchAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self._tmp.name))
        self.store = SessionStore(Path(self._tmp.name))
        self.adapter = ShugeSearchAdapter(self.store, self.settings)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_search_parses_openlist_response(self) -> None:
        body = {
            "code": 200,
            "message": "success",
            "data": {
                "content": [
                    {
                        "parent": "/书格网站资源/诗词文集",
                        "name": "宋词三百首.清末民初.朱祖谋编.pdf",
                        "is_dir": False,
                        "size": 196172153,
                    },
                    {"parent": "/书格网站资源", "name": "诗词文集", "is_dir": True, "size": 0},
                ]
            },
        }
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            return_value=_mock_response(body),
        ) as mocked:
            resources, err = self.adapter.search("宋词三百首", 10)

        self.assertIsNone(err)
        self.assertEqual(len(resources), 1)
        item = resources[0]
        self.assertEqual(item["platform"], "shuge")
        self.assertEqual(item["title"], "宋词三百首.清末民初.朱祖谋编.pdf")
        self.assertTrue(item["source_url"].startswith(BASE_URL + "/d/"))
        signals = item["metadata"]["platform_signals"]
        self.assertEqual(
            signals["file_path"], "/书格网站资源/诗词文集/宋词三百首.清末民初.朱祖谋编.pdf"
        )
        self.assertEqual(signals["size_bytes"], 196172153)
        payload = json.loads(mocked.call_args[0][0].data)
        self.assertEqual(payload["parent"], SEARCH_ROOT)
        self.assertEqual(payload["scope"], 2)

    def test_search_api_error_is_structured(self) -> None:
        body = {"code": 403, "message": "forbidden", "data": None}
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            return_value=_mock_response(body),
        ):
            resources, err = self.adapter.search("x", 5)
        self.assertEqual(resources, [])
        self.assertEqual(err["code"], "PARTIAL_FAILURE")
        self.assertFalse(err["retryable"])

    def test_search_network_error_is_retryable(self) -> None:
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            side_effect=URLError("boom"),
        ):
            resources, err = self.adapter.search("x", 5)
        self.assertEqual(resources, [])
        self.assertEqual(err["code"], "PARTIAL_FAILURE")
        self.assertTrue(err["retryable"])

    def test_search_invalid_json(self) -> None:
        resp = MagicMock()
        resp.read.return_value = b"<html>not json</html>"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            return_value=resp,
        ):
            resources, err = self.adapter.search("x", 5)
        self.assertEqual(resources, [])
        self.assertEqual(err["code"], "PARTIAL_FAILURE")


class ShugeInspectorTests(unittest.TestCase):
    def test_missing_file_path_is_blocked(self) -> None:
        inspector = ShugeInspector()
        result = inspector.inspect(
            {
                "platform": "shuge",
                "title": "x.pdf",
                "source_url": f"{BASE_URL}/d/x.pdf",
                "metadata": {"platform_signals": {}},
            }
        )
        mapping = result.to_mapping()
        self.assertEqual(mapping["resolution_status"], "unresolved")
        self.assertEqual(mapping["resolved_resource"]["availability"]["status"], "policy_blocked")
        codes = [f["code"] for f in mapping["failures"]]
        self.assertIn("PLATFORM_VALIDATION_BLOCKED", codes)

    def test_valid_file_path_passes_gate_to_generic(self) -> None:
        inspector = ShugeInspector()
        resource = {
            "platform": "shuge",
            "title": "x.pdf",
            "source_url": f"{BASE_URL}/d/x.pdf",
            "metadata": {
                "platform_signals": {"file_path": "/书格网站资源/x.pdf", "size_bytes": 100}
            },
        }
        with patch(
            "education_resource_mcp.adapters.inspect_generic.GenericWebInspector._request"
        ) as mocked:
            mocked.side_effect = ValueError("network down")
            result = inspector.inspect(resource)
        mapping = result.to_mapping()
        # transport failure must surface as a structured result, not a
        # platform-validation block.
        codes = [f["code"] for f in mapping["failures"]]
        self.assertNotIn("PLATFORM_VALIDATION_BLOCKED", codes)