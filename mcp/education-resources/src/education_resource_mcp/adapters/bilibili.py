"""Bilibili video search adapter.

Uses Bilibili's public WBI-signed web search API.  Auth is cookie-based
— the adapter pulls stored cookies from ``SessionStore`` at search time.
Without a valid session the adapter returns ``AUTH_REQUIRED``.

Ported from ``legacy/.../bilibili/bilibili_search.py``.  All HTTP uses
the shared ``urlopen_with_fallback`` helper (with Windows curl fallback).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback
from .wbi import wbi_sign


NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
CREATOR_URL = "https://api.bilibili.com/x/space/wbi/arc/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
)


def _strip_html(text: Any) -> str:
    """Remove HTML tags and collapse whitespace (B站 wraps keywords in <em>)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


def _count_value(value: Any) -> int | str | None:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text or text == "--":
        return None
    try:
        return int(text)
    except ValueError:
        return text


class BilibiliSearchAdapter:
    """Search Bilibili videos through the WBI-signed web API."""

    platform_id = "bilibili"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    # -- internal helpers ------------------------------------------------

    def _request_json(
        self, url: str, *, referer: str, cookie: str
    ) -> dict[str, Any]:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
        }
        if cookie:
            headers["Cookie"] = cookie
        request = Request(url, headers=headers)
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code == 412:
                raise _AdapterError("NETWORK_BLOCKED", "B站搜索触发 HTTP 412 风控", True)
            if exc.code in (401, 403):
                raise _AdapterError("AUTH_REQUIRED", f"B站搜索返回 HTTP {exc.code}", False)
            raise _AdapterError(
                "PARTIAL_FAILURE", f"B站搜索返回 HTTP {exc.code}", exc.code >= 500
            )
        except (TimeoutError, URLError) as exc:
            raise _AdapterError("PARTIAL_FAILURE", f"B站搜索请求失败: {type(exc).__name__}", True)

        if "json" not in content_type.lower():
            raise _AdapterError("NETWORK_BLOCKED", "B站搜索返回非 JSON 响应（可能触发风控）", True)
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            raise _AdapterError("PARTIAL_FAILURE", "B站搜索响应不是有效 JSON", False)
        if not isinstance(value, dict):
            raise _AdapterError("PARTIAL_FAILURE", "B站搜索响应根节点不是 object", False)
        return value

    def _wbi_keys(self, cookie: str) -> tuple[str, str]:
        nav = self._request_json(
            NAV_URL, referer="https://www.bilibili.com/", cookie=cookie
        )
        data = nav.get("data") or {}
        wbi = data.get("wbi_img") or {}
        img_url = str(wbi.get("img_url") or "")
        sub_url = str(wbi.get("sub_url") or "")
        if not img_url or not sub_url:
            raise _AdapterError("PARTIAL_FAILURE", "B站未返回 WBI 密钥", True)
        img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]
        return img_key, sub_key

    @staticmethod
    def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
        bvid = str(item.get("bvid") or "").strip()
        title = _strip_html(item.get("title"))
        if not bvid or not title:
            return None

        signals: dict[str, Any] = {}
        for key, raw in (
            ("views", item.get("play")),
            ("comments", item.get("video_review")),
            ("favorites", item.get("favorites")),
        ):
            val = _count_value(raw)
            if val is not None:
                signals[key] = val

        description = _strip_html(item.get("description"))
        pic = str(item.get("pic") or "")
        if pic.startswith("//"):
            pic = f"https:{pic}"

        pubdate = item.get("pubdate")
        published_at: str | None = None
        if isinstance(pubdate, (int, float)) and pubdate > 0:
            published_at = datetime.fromtimestamp(pubdate).astimezone().isoformat()

        return make_resource(
            platform="bilibili",
            title=title,
            source_url=f"https://www.bilibili.com/video/{bvid}",
            resource_type="视频",
            summary=description or None,
            author=item.get("author"),
            published_at=published_at,
            download_feasibility="中",
            platform_signals=signals or None,
        )

    # -- public API ------------------------------------------------------

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        # Cookie is optional — B站 search works without login, but having
        # a session may improve personalization and avoid rate limits.
        session_data = self.session_store.get_session_data("bilibili")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""

        try:
            img_key, sub_key = self._wbi_keys(cookie)
        except _AdapterError as exc:
            return [], exc.to_dict()

        results: list[dict[str, Any]] = []
        page = 1
        referer = f"https://search.bilibili.com/all?keyword={quote(query)}"

        try:
            while len(results) < limit:
                page_size = min(50, limit - len(results))
                params = wbi_sign(
                    {
                        "keyword": query,
                        "page": page,
                        "page_size": page_size,
                        "search_type": "video",
                        "order": "totalrank",
                    },
                    img_key,
                    sub_key,
                )
                url = f"{SEARCH_URL}?{urlencode(params)}"
                response = self._request_json(url, referer=referer, cookie=cookie)

                code = response.get("code")
                if code != 0:
                    message = str(response.get("message") or "B站搜索失败")
                    if code in (-101, -111):
                        return [], adapter_error("AUTH_REQUIRED", message, False)
                    if code in (-412, -352):
                        return [], adapter_error("NETWORK_BLOCKED", message, True)
                    return [], adapter_error("PARTIAL_FAILURE", f"B站 API {code}: {message}", False)

                items = ((response.get("data") or {}).get("result") or [])
                if not items:
                    break
                for item in items:
                    if isinstance(item, dict):
                        normalized = self._normalize_item(item)
                        if normalized:
                            results.append(normalized)
                            if len(results) >= limit:
                                break
                if len(items) < page_size:
                    break
                page += 1
        except _AdapterError as exc:
            # If we already have partial results, return them with the error.
            return results, exc.to_dict()

        return results, None


    def search_creator(
        self, creator_id: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        session_data = self.session_store.get_session_data("bilibili")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""
        try:
            img_key, sub_key = self._wbi_keys(cookie)
        except _AdapterError as exc:
            return [], exc.to_dict()
        results: list[dict[str, Any]] = []
        pn = 1
        try:
            while len(results) < limit:
                ps = min(30, limit - len(results))
                params = wbi_sign(
                    {"mid": creator_id, "pn": pn, "ps": ps,
                     "order": "pubdate", "search_type": "video"},
                    img_key, sub_key)
                url = f"{CREATOR_URL}?{urlencode(params)}"
                response = self._request_json(
                    url, referer=f"https://space.bilibili.com/{creator_id}/video", cookie=cookie)
                code = response.get("code")
                if code not in (None, 0):
                    return [], adapter_error(
                        "PARTIAL_FAILURE", f"B站 creator API {code}: {response.get('message', '')}", False)
                vlist = ((response.get("data") or {}).get("list") or {}).get("vlist") or []
                if not vlist:
                    break
                for item in vlist:
                    if "created" in item and "pubdate" not in item:
                        item = {**item, "pubdate": item["created"]}
                    normalized = self._normalize_item(item)
                    if normalized:
                        results.append(normalized)
                        if len(results) >= limit:
                            break
                if len(vlist) < ps:
                    break
                pn += 1
        except _AdapterError as exc:
            return results, exc.to_dict()
        return results, None


class _AdapterError(Exception):
    """Internal error carrying a stable code + retryable flag."""

    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
