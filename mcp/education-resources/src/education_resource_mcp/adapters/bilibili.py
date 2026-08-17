"""Bilibili video search adapter.

Uses Bilibili's public WBI-signed web APIs. Keyword search is bounded by the
caller; batch enumeration can stream pages until the platform reports the end.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback
from .wbi import wbi_sign


NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
CREATOR_URL = "https://api.bilibili.com/x/space/wbi/arc/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
)
_SPACE_MID_RE = re.compile(r"https?://space\.bilibili\.com/(\d+)")


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


def _parse_mid(creator_id: str) -> str:
    value = str(creator_id or "").strip()
    match = _SPACE_MID_RE.match(value)
    return match.group(1) if match else value


class BilibiliSearchAdapter:
    """Search Bilibili videos through the WBI-signed web API."""

    platform_id = "bilibili"
    descriptor = descriptor_for_platform("bilibili")

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)
        self._nav_logged_in: bool | None = None
        self._wbi_cache: tuple[float, str, str] | None = None

    _WBI_CACHE_SECONDS = 600.0

    def _session_check(self, cookie: str) -> dict[str, Any] | None:
        """Return AUTH_REQUIRED when a stored session has gone dead."""

        if not cookie:
            return None
        try:
            self._wbi_keys(cookie)
        except _AdapterError:
            return None
        if self._nav_logged_in is False:
            return adapter_error(
                "AUTH_REQUIRED",
                "B站登录态已失效，请重新登录（session-login-flow）后再搜索",
                False,
            )
        return None

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
        if self._wbi_cache is not None:
            checked_at, img_key, sub_key = self._wbi_cache
            if time.monotonic() - checked_at < self._WBI_CACHE_SECONDS:
                return img_key, sub_key
        nav = self._request_json(
            NAV_URL, referer="https://www.bilibili.com/", cookie=cookie
        )
        data = nav.get("data") or {}
        self._nav_logged_in = bool(data.get("isLogin"))
        wbi = data.get("wbi_img") or {}
        img_url = str(wbi.get("img_url") or "")
        sub_url = str(wbi.get("sub_url") or "")
        if not img_url or not sub_url:
            raise _AdapterError("PARTIAL_FAILURE", "B站未返回 WBI 密钥", True)
        img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]
        self._wbi_cache = (time.monotonic(), img_key, sub_key)
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
            creator_mid=str(item["mid"]) if item.get("mid") else None,
            published_at=published_at,
            download_feasibility="中",
            platform_signals=signals or None,
        )

    def iter_search(
        self,
        query: str,
        *,
        pubtime_begin_s: int = 0,
        pubtime_end_s: int = 0,
        cancel_event: Any = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield keyword results page by page until Bilibili reports the end."""

        session_data = self.session_store.get_session_data("bilibili")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""
        auth_error = self._session_check(cookie)
        if auth_error:
            raise _AdapterError(
                str(auth_error.get("code") or "AUTH_REQUIRED"),
                str(auth_error.get("message") or "B站登录态不可用"),
                bool(auth_error.get("retryable")),
            )
        img_key, sub_key = self._wbi_keys(cookie)
        page = 1
        page_size = 50
        referer = f"https://search.bilibili.com/all?keyword={quote(query)}"

        while True:
            if cancel_event is not None and cancel_event.is_set():
                break
            payload: dict[str, Any] = {
                "keyword": query,
                "page": page,
                "page_size": page_size,
                "search_type": "video",
                "order": "totalrank",
            }
            if pubtime_begin_s:
                payload["pubtime_begin_s"] = pubtime_begin_s
            if pubtime_end_s:
                payload["pubtime_end_s"] = pubtime_end_s
            params = wbi_sign(payload, img_key, sub_key)
            response = self._request_json(
                f"{SEARCH_URL}?{urlencode(params)}", referer=referer, cookie=cookie
            )
            code = response.get("code")
            if code != 0:
                message = str(response.get("message") or "B站搜索失败")
                if code in (-101, -111):
                    raise _AdapterError("AUTH_REQUIRED", message, False)
                if code in (-412, -352):
                    raise _AdapterError("NETWORK_BLOCKED", message, True)
                raise _AdapterError("PARTIAL_FAILURE", f"B站 API {code}: {message}", False)

            items = ((response.get("data") or {}).get("result") or [])
            if not items:
                break
            for item in items:
                if isinstance(item, dict):
                    normalized = self._normalize_item(item)
                    if normalized:
                        yield normalized
            if len(items) < page_size:
                break
            page += 1

    def search(
        self,
        query: str,
        limit: int,
        *,
        pubtime_begin_s: int = 0,
        pubtime_end_s: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        results: list[dict[str, Any]] = []
        try:
            for resource in self.iter_search(
                query,
                pubtime_begin_s=pubtime_begin_s,
                pubtime_end_s=pubtime_end_s,
            ):
                results.append(resource)
                if len(results) >= limit:
                    break
        except _AdapterError as exc:
            return results, exc.to_dict()
        return results, None

    def iter_creator(
        self, creator_id: str, *, cancel_event: Any = None
    ) -> Iterator[dict[str, Any]]:
        """Yield a creator's videos until the space API reports the end."""

        mid = _parse_mid(creator_id)
        session_data = self.session_store.get_session_data("bilibili")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""
        auth_error = self._session_check(cookie)
        if auth_error:
            raise _AdapterError(
                str(auth_error.get("code") or "AUTH_REQUIRED"),
                str(auth_error.get("message") or "B站登录态不可用"),
                bool(auth_error.get("retryable")),
            )
        img_key, sub_key = self._wbi_keys(cookie)
        pn = 1
        page_size = 30

        while True:
            if cancel_event is not None and cancel_event.is_set():
                break
            params = wbi_sign(
                {
                    "mid": mid,
                    "pn": pn,
                    "ps": page_size,
                    "order": "pubdate",
                    "search_type": "video",
                },
                img_key,
                sub_key,
            )
            response = self._request_json(
                f"{CREATOR_URL}?{urlencode(params)}",
                referer=f"https://space.bilibili.com/{mid}/video",
                cookie=cookie,
            )
            code = response.get("code")
            if code not in (None, 0):
                raise _AdapterError(
                    "PARTIAL_FAILURE",
                    f"B站 creator API {code}: {response.get('message', '')}",
                    False,
                )
            vlist = ((response.get("data") or {}).get("list") or {}).get("vlist") or []
            if not vlist:
                break
            for raw in vlist:
                item = raw
                if "created" in item and "pubdate" not in item:
                    item = {**item, "pubdate": item["created"]}
                normalized = self._normalize_item(item)
                if not normalized:
                    continue
                author_mid = str(
                    (normalized.get("metadata") or {}).get("creator_mid") or ""
                )
                if author_mid and author_mid != mid:
                    continue
                yield normalized
            if len(vlist) < page_size:
                break
            pn += 1

    def search_creator(
        self, creator_id: str, limit: int, cancel_event: Any = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        results: list[dict[str, Any]] = []
        try:
            for resource in self.iter_creator(creator_id, cancel_event=cancel_event):
                results.append(resource)
                if len(results) >= limit:
                    break
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
