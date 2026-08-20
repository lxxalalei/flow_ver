"""Focused tests for WeChat search result normalization."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from education_resource_mcp.adapters.wechat import WechatSearchAdapter
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


SEARCH_PAGE = """
<div class="txt-box">
  <a href="/link?url=token&amp;type=2&amp;query=%E5%AE%B6%E5%BA%AD">家庭教育&ldquo;十百千&rdquo;行动</a>
  <p class="txt-info">家校共育&amp;润心同行</p>
  <a class="account">教育&amp;成长</a>
</div>
<div class="txt-box">
  <a href="/link?url=second&amp;type=2">第二条</a>
</div>
"""


class WechatSearchAdapterTests(unittest.TestCase):
    def test_search_unescapes_text_and_redirect_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = WechatSearchAdapter(SessionStore(root), _settings(root))
            with patch(
                "education_resource_mcp.adapters.wechat.urlopen_with_fallback",
                return_value=_response(SEARCH_PAGE),
            ):
                results, error = adapter.search("家庭教育", 1)

        self.assertIsNone(error)
        self.assertEqual(1, len(results))
        self.assertEqual('家庭教育“十百千”行动', results[0]["title"])
        self.assertEqual("家校共育&润心同行", results[0]["summary"])
        self.assertEqual("教育&成长", results[0]["metadata"]["author"])
        self.assertEqual(
            "https://weixin.sogou.com/link?url=token&type=2&query=%E5%AE%B6%E5%BA%AD",
            results[0]["source_url"],
        )
        self.assertNotIn("&amp;", results[0]["source_url"])

    def test_antispider_page_still_requires_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = WechatSearchAdapter(SessionStore(root), _settings(root))
            with patch(
                "education_resource_mcp.adapters.wechat.urlopen_with_fallback",
                return_value=_response("<html>antispider</html>"),
            ):
                results, error = adapter.search("家庭教育", 3)

        self.assertEqual([], results)
        self.assertEqual("AUTH_REQUIRED", error["code"])
        self.assertFalse(error["retryable"])


if __name__ == "__main__":
    unittest.main()
