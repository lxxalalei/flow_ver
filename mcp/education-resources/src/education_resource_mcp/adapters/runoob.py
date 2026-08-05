"""Runoob (菜鸟教程) search adapter.

Scrapes the WordPress search page. No auth required.
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


BASE_URL = "https://www.runoob.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


class RunoobSearchAdapter:
    platform_id = "runoob"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = f"{BASE_URL}/?{urlencode({'s': query})}"
        request = Request(url, headers={"User-Agent": UA})
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"菜鸟教程搜索失败：{type(exc).__name__}: {exc}", True)

        blocks = re.split(r'<div\s+class=["\']archive-list-item["\'][^>]*>', page, flags=re.I)[1:]
        resources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for block in blocks:
            link = re.search(
                r'<h2\b[^>]*>\s*<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                block, re.I | re.S,
            )
            if not link:
                continue
            raw_url = html_mod.unescape(link.group(1).strip())
            title = _clean(link.group(2))
            if not title:
                continue
            parsed = urlsplit(raw_url)
            if parsed.hostname not in {"runoob.com", "www.runoob.com"}:
                continue
            source_url = urlunsplit(("https", "www.runoob.com", parsed.path, parsed.query, ""))
            if source_url in seen:
                continue
            seen.add(source_url)
            desc_match = re.search(r"<p\b[^>]*>(.*?)</p>", block, re.I | re.S)
            desc = _clean(desc_match.group(1))[:400] if desc_match else ""
            resources.append(make_resource(
                platform="runoob",
                title=title,
                source_url=source_url,
                resource_type="文章",
                summary=desc or None,
            ))
            if len(resources) >= limit:
                break
        return resources, None
