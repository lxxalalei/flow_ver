"""Yixi (一席) talk search adapter.

Calls the public search API directly, then resolves the current highest
available public MP4 through Yixi's play-detail API. No auth required.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


BASE_URL = "https://www.yixi.tv"
SEARCH_URL = BASE_URL + "/v3/api/h5/search/new/v2/"
PLAY_DETAIL_URL = BASE_URL + "/v3/api/h5/play_detail/"
AUTHCODE = "$yf&cpup8d%@s2h%"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_yixi_media_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().rstrip(".")
    return (
        parsed.scheme.casefold() == "https"
        and bool(host)
        and (host == "yixi.tv" or host.endswith(".yixi.tv"))
    )


class YixiSearchAdapter:
    platform_id = "yixi"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def _play_detail(self, speech_id: int) -> dict[str, Any] | None:
        params = urlencode(
            {
                "video_type": "0",
                "video_id": str(speech_id),
                "album_id": "0",
                "_": str(int(time.time() * 1000)),
            }
        )
        request = Request(
            f"{PLAY_DETAIL_URL}?{params}",
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
        except Exception:
            return None
        if not isinstance(data, dict) or data.get("error_code") != 0:
            return None
        inner = data.get("data")
        if not isinstance(inner, dict):
            return None
        base_items = inner.get("base_items")
        return base_items if isinstance(base_items, dict) else None

    @staticmethod
    def _best_video(base_items: dict[str, Any] | None) -> tuple[str, str | None]:
        if not isinstance(base_items, dict):
            return "", None
        variants = base_items.get("video_url")
        if not isinstance(variants, list):
            return "", _clean(base_items.get("video_duration")) or None
        available: list[tuple[int, str]] = []
        for item in variants:
            if not isinstance(item, dict):
                continue
            url = _clean(item.get("video_url"))
            if not _is_yixi_media_url(url):
                continue
            raw_type = item.get("type")
            quality = raw_type if isinstance(raw_type, int) and not isinstance(raw_type, bool) else 0
            available.append((quality, url))
        if not available:
            return "", _clean(base_items.get("video_duration")) or None
        available.sort(key=lambda item: item[0], reverse=True)
        return available[0][1], _clean(base_items.get("video_duration")) or None

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
            if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0 or not title:
                continue

            base_items = self._play_detail(item_id)
            direct_video_url, video_duration = self._best_video(base_items)
            # Keep discovery useful even if a detail lookup is temporarily
            # unavailable. Such a candidate can still be shown, but it will
            # not become a materializable video until a later search resolves
            # a concrete public media URL.
            source_url = direct_video_url or f"{BASE_URL}/speech/detail?id={item_id}"
            speaker = item.get("speaker") if isinstance(item.get("speaker"), dict) else {}
            resources.append(make_resource(
                platform="yixi",
                title=title,
                source_url=source_url,
                resource_type="视频",
                summary=_clean(item.get("intro"))[:400] or None,
                author=_clean(speaker.get("name")) or None,
                platform_signals={
                    "speech_id": item_id,
                    "play_count": item.get("play_count"),
                    "cover_url": _clean(item.get("video_cover")) or None,
                    "video_duration": video_duration,
                    "direct_video": bool(direct_video_url),
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
