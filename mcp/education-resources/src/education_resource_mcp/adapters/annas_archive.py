"""Anna's Archive search adapter.

Scrapes the public search results page. No auth required.
Uses the default mirror annas-archive.gl; override via ANNAS_BASE_URL env var.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import quote
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


DEFAULT_BASE = "annas-archive.gl"
SEARCH_PATH = "/search?q="
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


class AnnasArchiveSearchAdapter:
    platform_id = "annas-archive"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)
        self.base_url = os.environ.get("ANNAS_BASE_URL", "").strip() or DEFAULT_BASE

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = f"https://{self.base_url}{SEARCH_PATH}{quote(query)}"
        request = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"Anna's Archive 搜索失败：{type(exc).__name__}: {exc}", True)

        # Extract md5 links with surrounding titles
        md5_pattern = re.compile(r'href="/md5/([a-f0-9]{32})"', re.I)
        resources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in md5_pattern.finditer(page):
            md5 = match.group(1)
            if md5 in seen:
                continue
            seen.add(md5)
            # Look for title in surrounding context
            start = max(0, match.start() - 200)
            end = min(len(page), match.end() + 500)
            block = page[start:end]
            title_match = re.search(
                rf'/md5/{re.escape(md5)}"[^>]*>(.*?)</', block, re.I | re.S,
            )
            title = _clean(title_match.group(1)) if title_match else f"Document {md5[:8]}"
            if not title:
                title = f"Document {md5[:8]}"
            source_url = f"https://{self.base_url}/md5/{md5}"
            # Try to extract format/size/lang from context
            fmt = re.search(r"\.(pdf|epub|mobi|txt|djvu|azw3)", block, re.I)
            resources.append(make_resource(
                platform="annas-archive",
                title=title,
                source_url=source_url,
                resource_type="图书",
                summary=None,
                platform_signals={
                    "md5": md5,
                    "format": fmt.group(1).lower() if fmt else None,
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
