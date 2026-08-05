"""Weibo (微博) search adapter.

Calls the public ajax/searchall JSON API with cookie auth.
Cookie is pulled from SessionStore at search time; without a valid
session the adapter returns AUTH_REQUIRED.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


SEARCH_URL = "https://weibo.com/ajax/searchall"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


class WeiboSearchAdapter:
    platform_id = "weibo"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        session_data = self.session_store.get_session_data("weibo")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""
        if not cookie:
            return [], adapter_error("AUTH_REQUIRED", "微博搜索需要登录 Cookie", False)

        params = urlencode({"q": query, "page": "1", "count": str(min(limit, 10))})
        request = Request(f"{SEARCH_URL}?{params}", headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Cookie": cookie,
            "Referer": "https://weibo.com/",
        })
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"微博搜索失败：{type(exc).__name__}: {exc}", True)

        posts = (data.get("data") or {}).get("notes") or (data.get("data") or {}).get("statuses") or []
        resources: list[dict[str, Any]] = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            text = _clean(post.get("text") or post.get("title"))
            bid = str(post.get("id") or post.get("bid") or "").strip()
            if not text or not bid:
                continue
            source_url = f"https://weibo.com/detail/{bid}"
            user = post.get("user") if isinstance(post.get("user"), dict) else {}
            resources.append(make_resource(
                platform="weibo",
                title=text[:200],
                source_url=source_url,
                resource_type="文章",
                author=_clean(user.get("screen_name")) or None,
                platform_signals={
                    "is_verified": bool(user.get("verified")),
                    "reposts": post.get("reposts_count"),
                    "comments": post.get("comments_count"),
                    "likes": post.get("attitudes_count"),
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
