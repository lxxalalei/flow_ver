"""Yixi (一席) talk search adapter.

Calls the public search API directly. No auth required.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


BASE_URL = "https://www.yixi.tv"
SEARCH_URL = BASE_URL + "/v3/api/h5/search/new/v2/"
AUTHCODE = "$yf&cpup8d%@s2h%"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class YixiSearchAdapter:
    platform_id = "yixi"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        params = urlencode({
            "keyword": query,
            "search_type": "1",
            "action": "1",
            "_": str(int(time.time() * 1000)),
        })
        request = Request(
            f"{SEARCH_URL}?{params}",
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": BASE_URL + "/",
                "authcode": AUTHCODE,
            },
        )
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"一席搜索失败：{type(exc).__name__}: {exc}", True)

        items = []
        if isinstance(data, dict):
            # Response shape: {"data": {"items": [...]}}
            inner = data.get("data")
            if isinstance(inner, dict):
                items = inner.get("items") or inner.get("list") or []
            elif isinstance(inner, list):
                items = inner
            elif isinstance(data.get("list"), list):
                items = data["list"]
        resources: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            title = _clean(item.get("title"))
            if item_id is None or not title:
                continue
            source_url = f"{BASE_URL}/speech/detail?id={item_id}"
            speaker = item.get("speaker") if isinstance(item.get("speaker"), dict) else {}
            resources.append(make_resource(
                platform="yixi",
                title=title,
                source_url=source_url,
                resource_type="视频",
                summary=_clean(item.get("intro"))[:400] or None,
                author=_clean(speaker.get("name")) or None,
                platform_signals={
                    "play_count": item.get("play_count"),
                    "cover_url": _clean(item.get("video_cover")) or None,
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
