"""Ximalaya (喜马拉雅) audio search adapter.

Calls the public revision/search API directly. No auth required, no
fallback paths. If the API fails the adapter returns a structured error.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


SEARCH_URL = "https://www.ximalaya.com/revision/search"
ALBUM_URL = "https://www.ximalaya.com/album/"
TRACK_URL = "https://www.ximalaya.com/sound/"
COVER_CDN = "https:"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _strip_html(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


class XimalayaSearchAdapter:
    """Search Ximalaya albums via the public revision/search API."""

    platform_id = "ximalaya"
    descriptor = descriptor_for_platform("ximalaya")

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        params = urlencode({
            "core": "album",
            "kw": query,
            "page": "1",
            "rows": str(min(limit, 30)),
            "condition": "relation",
            "device": "web",
            "spellchecker": "true",
        })
        url = f"{SEARCH_URL}?{params}"
        request = Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.ximalaya.com/",
        })
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"喜马拉雅搜索请求失败：{type(exc).__name__}: {exc}",
                retryable=True,
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                "喜马拉雅搜索响应解析失败",
                retryable=True,
            )

        if data.get("ret") != 200:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"喜马拉雅搜索返回错误：ret={data.get('ret')}, msg={data.get('msg')}",
                retryable=True,
            )

        try:
            docs = data["data"]["result"]["response"]["docs"] or []
        except (KeyError, TypeError):
            return [], adapter_error(
                "PARTIAL_FAILURE",
                "喜马拉雅搜索响应结构异常",
                retryable=True,
            )

        resources: list[dict[str, Any]] = []
        for doc in docs:
            resource = self._parse_doc(doc)
            if resource:
                resources.append(resource)
        return resources[:limit], None

    @staticmethod
    def _parse_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
        resource_id = str(doc.get("id") or "").strip()
        if not resource_id:
            return None

        title = _strip_html(doc.get("title") or doc.get("richTitle"))
        if not title:
            return None

        source_url = f"{ALBUM_URL}{resource_id}"

        summary = _strip_html(doc.get("intro") or doc.get("custom_title"))[:400] or None

        author = _strip_html(doc.get("nickname")) or None

        cover = doc.get("cover_path") or ""
        if cover and not cover.startswith("http"):
            cover = COVER_CDN + cover

        play_count = doc.get("play")
        if isinstance(play_count, str):
            try:
                play_count = int(play_count)
            except ValueError:
                play_count = None

        return make_resource(
            platform="ximalaya",
            title=title,
            source_url=source_url,
            resource_type="音频",
            summary=summary,
            author=author,
            platform_signals={
                "play_count": play_count,
                "tracks": doc.get("tracks"),
                "score": doc.get("score"),
                "is_verified": bool(doc.get("is_v")),
                "is_paid": bool(doc.get("is_paid")),
                "is_finished": doc.get("is_finished"),
                "category": doc.get("category_title"),
                "cover_url": cover or None,
            },
        )
