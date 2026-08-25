"""WeChat (微信公众号) search adapter.

Searches WeChat articles via Sogou Weixin. Returns AUTH_REQUIRED
when no session cookie is available — Sogou requires cookies for
reliable access and blocks anonymous scraping.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


SOGOU_SEARCH_URL = "https://weixin.sogou.com/weixin"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    value = html.unescape(str(text or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value)).strip()


class WechatSearchAdapter:
    platform_id = "wechat"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        session_data = self.session_store.get_session_data("wechat")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://weixin.sogou.com/",
        }
        if cookie:
            headers["Cookie"] = cookie

        params = urlencode({"type": "2", "query": query, "ie": "utf8"})
        url = f"{SOGOU_SEARCH_URL}?{params}"
        request = Request(url, headers=headers)
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"微信搜索失败：{type(exc).__name__}: {exc}", True)

        # Sogou may return anti-bot page without cookie
        if "antispider" in page or "用户您好" in page:
            return [], adapter_error("AUTH_REQUIRED", "搜狗微信触发反爬，需要有效 Cookie", False)

        resources: list[dict[str, Any]] = []
        blocks = re.split(r'<div\s+class=["\']txt-box["\'][^>]*>', page, flags=re.I)[1:]
        for block in blocks:
            title_link = re.search(
                r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                block, re.I | re.S,
            )
            if not title_link:
                continue
            href = html.unescape(title_link.group(1).strip())
            # Sogou uses /link?url= redirect links; keep as-is
            if href.startswith("/"):
                href = urljoin("https://weixin.sogou.com", href)
            title = _clean(title_link.group(2))
            if not title:
                continue
            summary_match = re.search(
                r'<p\b[^>]*class=["\']txt-info["\'][^>]*>(.*?)</p>',
                block, re.I | re.S,
            )
            summary = _clean(summary_match.group(1))[:300] if summary_match else None
            account_match = re.search(
                r'<a\b[^>]*class=["\']account["\'][^>]*>(.*?)</a>',
                block, re.I | re.S,
            )
            account = _clean(account_match.group(1)) if account_match else None
            resources.append(make_resource(
                platform="wechat",
                title=title,
                source_url=href,
                resource_type="文章",
                summary=summary,
                author=account,
            ))
            if len(resources) >= limit:
                break
        return resources, None
