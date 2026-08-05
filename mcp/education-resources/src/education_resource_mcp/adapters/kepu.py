"""Kepu China (科普中国) search adapter.

Scrapes the public search results page. No auth required.
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any
from urllib.parse import quote, urljoin
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


BASE_URL = "https://www.kepuchina.cn"
SEARCH_URL = BASE_URL + "/search/index?search={query}&search_type=0"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return html_mod.unescape(text).strip()


def _first(pattern: str, block: str) -> str:
    m = re.search(pattern, block, re.I | re.S)
    return m.group(1) if m else ""


class KepuSearchAdapter:
    platform_id = "kepu"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = SEARCH_URL.format(query=quote(query))
        request = Request(url, headers={"User-Agent": UA, "Referer": BASE_URL + "/"})
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"科普中国搜索失败：{type(exc).__name__}: {exc}", True)

        blocks = re.split(r'<div\s+class=["\']sl_item\s+clearfix["\'][^>]*>', page, flags=re.I)[1:]
        resources: list[dict[str, Any]] = []
        for block in blocks:
            href = _first(r'<a\b[^>]*href=["\']([^"\']*articleinfo[^"\']+)["\']', block)
            if not href:
                href = _first(r'<h2[^>]*>.*?<a\b[^>]*href=["\']([^"\']+)["\']', block)
            if not href:
                continue
            source_url = urljoin(BASE_URL + "/", html_mod.unescape(href.strip()))
            title = _clean(_first(r'<h2[^>]*>.*?<a\b[^>]*>(.*?)</a>', block))
            if not title:
                continue
            desc = _clean(_first(r'<div\s+class=["\']desc\s+ell["\'][^>]*>(.*?)</div>', block))[:300]
            resources.append(make_resource(
                platform="kepu",
                title=title,
                source_url=source_url,
                resource_type="文章",
                summary=desc or None,
            ))
            if len(resources) >= limit:
                break
        return resources, None
