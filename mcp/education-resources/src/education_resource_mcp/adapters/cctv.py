"""CCTV (央视网) video search adapter.

Calls the public ifsearch.php JSON API directly.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


SEARCH_API = "https://search.cctv.com/ifsearch.php"
SEARCH_PAGE = "https://search.cctv.com/search.php"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


class CctvSearchAdapter:
    platform_id = "cctv"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        params = urlencode({
            "page": "1",
            "qtext": query,
            "sort": "relevance",
            "pageSize": str(min(limit, 20)),
            "type": "video",
            "datepid": "1",
            "channel": "",
            "vtime": "-1",
        })
        url = f"{SEARCH_API}?{params}"
        request = Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*",
            "Referer": f"{SEARCH_PAGE}?{urlencode({'type': 'video', 'qtext': query})}",
        })
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"央视网搜索失败：{type(exc).__name__}: {exc}", True)

        items = data.get("list") or []
        resources: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "").strip()
            title = _clean(item.get("all_title") or item.get("title"))
            source_url = _clean(item.get("urllink"))
            if not video_id or not title or not source_url:
                continue
            if not source_url.startswith("http"):
                source_url = urljoin("https://tv.cctv.com", source_url)
            desc_parts = []
            channel = _clean(item.get("channel"))
            if channel:
                desc_parts.append(f"频道: {channel}")
            pub_time = _clean(item.get("uploadtime"))
            if pub_time:
                desc_parts.append(f"发布: {pub_time}")
            resources.append(make_resource(
                platform="cctv",
                title=title,
                source_url=source_url,
                resource_type="视频",
                summary="；".join(desc_parts) or None,
                author=channel or None,
                platform_signals={
                    "duration": item.get("durations"),
                    "publish_time": pub_time or None,
                    "thumbnail": _clean(item.get("imglink")) or None,
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
