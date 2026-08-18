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





def _mock_html_response(html: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = html.encode("utf-8")
    resp.status = status
    resp.headers = {"Content-Type": "text/html"}
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(url: str, code: int = 404) -> HTTPError:
    import io
    from urllib.error import HTTPError

    return HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))

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


class ShugeDetailLinkSearchTests(unittest.TestCase):
    """Detail-page / short-link queries resolve to a storage title search."""

    DETAIL_HTML = (
        "<html><head><title>五经类语 &#8211; 书格</title></head>"
        "<body></body></html>"
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = _settings(Path(self._tmp.name))
        self.store = SessionStore(Path(self._tmp.name))
        self.adapter = ShugeSearchAdapter(self.store, self.settings)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _search_body() -> dict:
        return {
            "code": 200,
            "message": "success",
            "data": {
                "content": [
                    {
                        "parent": "/书格网站资源/哲学经学",
                        "name": "五经类语.八卷.明梁宇乔撰.清康熙时期果亲王府钞本.pdf",
                        "is_dir": False,
                        "size": 696093426,
                    }
                ]
            },
        }

    def _assert_detail_link_flow(self, link: str, expected_detail_url: str | None = None) -> None:
        if expected_detail_url is None:
            expected_detail_url = link
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            side_effect=[
                _mock_html_response(self.DETAIL_HTML),
                _mock_response(self._search_body()),
            ],
        ) as mocked:
            resources, err = self.adapter.search(link, 10)
        self.assertIsNone(err)
        self.assertEqual(len(resources), 1)
        item = resources[0]
        self.assertTrue(item["source_url"].startswith(BASE_URL + "/d/"))
        signals = item["metadata"]["platform_signals"]
        self.assertEqual(signals["detail_url"], expected_detail_url)
        self.assertEqual(
            signals["file_path"],
            "/书格网站资源/哲学经学/五经类语.八卷.明梁宇乔撰.清康熙时期果亲王府钞本.pdf",
        )
        # First call fetches the detail page; second searches storage by title.
        self.assertEqual(mocked.call_args_list[0][0][0].full_url, expected_detail_url)
        payload = json.loads(mocked.call_args_list[1][0][0].data)
        self.assertEqual(payload["keywords"], "五经类语")

    def test_detail_url_flow(self) -> None:
        self._assert_detail_link_flow("https://www.shuge.org/view/wu_jing_lei_yu/")

    def test_detail_url_without_scheme_or_slash(self) -> None:
        self._assert_detail_link_flow(
            "shuge.org/view/wu_jing_lei_yu",
            expected_detail_url="https://shuge.org/view/wu_jing_lei_yu",
        )

    def test_short_url_flow(self) -> None:
        self._assert_detail_link_flow("https://s.shuge.org/wjlycb")

    def test_keyword_query_never_fetches_page(self) -> None:
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            return_value=_mock_response(self._search_body()),
        ) as mocked:
            resources, err = self.adapter.search("五经类语", 10)
        self.assertIsNone(err)
        self.assertEqual(len(resources), 1)
        self.assertEqual(mocked.call_count, 1)

    def test_title_variant_extraction(self) -> None:
        variants = [
            "五经类语 &#8211; 书格",
            "五经类语 – 书格",
            "五经类语 - 书格",
            "五经类语 ｜ 书格",
            "五经类语",
        ]
        for title in variants:
            with self.subTest(title=title):
                html_text = f"<html><head><title>{title}</title></head><body></body></html>"
                with patch(
                    "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
                    side_effect=[
                        _mock_html_response(html_text),
                        _mock_response(self._search_body()),
                    ],
                ) as mocked:
                    resources, err = self.adapter.search(
                        "https://www.shuge.org/view/wu_jing_lei_yu/", 10
                    )
                self.assertIsNone(err)
                self.assertEqual(len(resources), 1)
                payload = json.loads(mocked.call_args_list[1][0][0].data)
                self.assertEqual(payload["keywords"], "五经类语")

    def test_detail_page_network_error_is_retryable(self) -> None:
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            side_effect=URLError("boom"),
        ):
            resources, err = self.adapter.search(
                "https://www.shuge.org/view/x/", 5
            )
        self.assertEqual(resources, [])
        self.assertEqual(err["code"], "PARTIAL_FAILURE")
        self.assertTrue(err["retryable"])

    def test_detail_page_http_error_not_retryable(self) -> None:
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            side_effect=_http_error("https://www.shuge.org/view/x/", 404),
        ):
            resources, err = self.adapter.search(
                "https://www.shuge.org/view/x/", 5
            )
        self.assertEqual(resources, [])
        self.assertEqual(err["code"], "PARTIAL_FAILURE")
        self.assertFalse(err["retryable"])

    def test_detail_page_homepage_title_rejected(self) -> None:
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            return_value=_mock_html_response(
                "<html><head><title>书格 &#8211; 书格</title></head></html>"
            ),
        ):
            resources, err = self.adapter.search("https://s.shuge.org/unknown", 5)
        self.assertEqual(resources, [])
        self.assertEqual(err["code"], "PARTIAL_FAILURE")
        self.assertFalse(err["retryable"])

    def test_detail_page_missing_title_structured(self) -> None:
        with patch(
            "education_resource_mcp.adapters.shuge.urlopen_with_fallback",
            return_value=_mock_html_response("<html><body>no title</body></html>"),
        ):
            resources, err = self.adapter.search(
                "https://www.shuge.org/view/x/", 5
            )
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