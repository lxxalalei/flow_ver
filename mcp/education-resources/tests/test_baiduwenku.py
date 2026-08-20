"""Focused tests for the current public Baidu Wenku search page."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from education_resource_mcp.adapters.baiduwenku import BaiduwenkuSearchAdapter
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


def _settings(root: Path) -> Settings:
    return Settings(data_dir=root, jobs_dir=root / "jobs")


def _response(page: str):
    response = MagicMock()
    response.read.return_value = page.encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


MOBILE_PAGE = r'''<script>window.pageData = {
  "initData": {
    "docList": [
      {
        "resourceType": 1,
        "docInfo": {
          "url": "https://wenku.baidu.com/view/abc123def456.html",
          "title": "五年级<em>分数练习题</em> - 百度文库",
          "content": "分数的意义与计算 &amp; 配套答案",
          "typeStr": "doc",
          "pageNum": 8,
          "downloadCount": 3,
          "createTime": 1766997724
        }
      },
      {
        "resourceType": 1,
        "docInfo": {
          "url": "https://wenku.baidu.com/view/second789.html",
          "title": "第二份练习题",
          "content": "第二份摘要"
        }
      }
    ]
  }
};</script>'''


class BaiduwenkuSearchAdapterTests(unittest.TestCase):
    def test_mobile_page_returns_normalized_documents_and_honors_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = BaiduwenkuSearchAdapter(SessionStore(root), _settings(root))
            with patch(
                "education_resource_mcp.adapters.baiduwenku.urlopen_with_fallback",
                return_value=_response(MOBILE_PAGE),
            ) as mocked:
                results, error = adapter.search("五年级分数", 1)

        self.assertIsNone(error)
        self.assertEqual(1, len(results))
        self.assertEqual("五年级分数练习题 - 百度文库", results[0]["title"])
        self.assertEqual(
            "https://wenku.baidu.com/view/abc123def456.html",
            results[0]["source_url"],
        )
        self.assertEqual("分数的意义与计算 & 配套答案", results[0]["summary"])
        self.assertEqual(8, results[0]["metadata"]["platform_signals"]["page_num"])
        kwargs = mocked.call_args.kwargs
        self.assertEqual(frozenset({403}), kwargs["curl_on_status"])
        request = mocked.call_args.args[0]
        self.assertIn("Mobile", request.get_header("User-agent"))

    def test_empty_known_doc_list_is_a_successful_empty_search(self) -> None:
        page = '<script>window.pageData = {"initData":{"docList":[]}};</script>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = BaiduwenkuSearchAdapter(SessionStore(root), _settings(root))
            with patch(
                "education_resource_mcp.adapters.baiduwenku.urlopen_with_fallback",
                return_value=_response(page),
            ):
                results, error = adapter.search("不存在的词", 5)
        self.assertEqual([], results)
        self.assertIsNone(error)

    def test_unknown_page_shape_reports_parse_failure(self) -> None:
        page = '<script>window.pageData = {"page":"aiUnion"};</script>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = BaiduwenkuSearchAdapter(SessionStore(root), _settings(root))
            with patch(
                "education_resource_mcp.adapters.baiduwenku.urlopen_with_fallback",
                return_value=_response(page),
            ):
                results, error = adapter.search("五年级分数", 5)
        self.assertEqual([], results)
        self.assertEqual("PARSE_FORMAT_NOT_SUPPORTED", error["code"])
        self.assertTrue(error["retryable"])


if __name__ == "__main__":
    unittest.main()
