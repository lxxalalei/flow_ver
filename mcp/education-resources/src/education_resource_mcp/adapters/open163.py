"""Open163 (网易公开课) search adapter.

Scrapes the server-rendered search results page. No auth required.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urljoin
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


SEARCH_URL = "https://open.163.com/newview/search/{keyword}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


class Open163SearchAdapter:
    platform_id = "open163"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = SEARCH_URL.format(keyword=quote(query))
        request = Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://open.163.com/",
        })
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"网易公开课搜索失败：{type(exc).__name__}: {exc}", True)

        # Extract course blocks by pid links
        pid_pattern = re.compile(r'href=["\'][^"\']*[?&]pid=(\w+)["\']', re.I)
        resources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in pid_pattern.finditer(page):
            pid = match.group(1)
            if pid in seen:
                continue
            seen.add(pid)
            # Find surrounding context for title
            start = max(0, match.start() - 500)
            end = min(len(page), match.end() + 500)
            block = page[start:end]
            source_url = f"https://open.163.com/newview/movie/free?pid={pid}"
            title_match = re.search(r'<img\b[^>]*\balt=["\']([^"\']+)["\']', block, re.I)
            title = _clean(title_match.group(1)) if title_match else ""
            if not title:
                title_match = re.search(r'pid=' + re.escape(pid) + r'[^>]*>(.*?)<', block, re.I | re.S)
                title = _clean(title_match.group(1)) if title_match else pid
            play_match = re.search(r"([\d.]+)\s*万?次播放", block)
            lessons_match = re.search(r"(\d+)\s*课时", block)
            resources.append(make_resource(
                platform="open163",
                title=title,
                source_url=source_url,
                resource_type="课程",
                summary=None,
                platform_signals={
                    "play_count": play_match.group(0) if play_match else None,
                    "lessons": int(lessons_match.group(1)) if lessons_match else None,
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
