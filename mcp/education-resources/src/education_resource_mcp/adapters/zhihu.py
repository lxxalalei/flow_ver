"""Zhihu search adapter.

Three-tier fallback strategy:
  1. Zhihu search API (cookie must contain ``z_c0`` + ``d_c0``)
  2. HTML page scraping (no auth required, lower quality)
  3. Search-engine ``site:zhihu.com`` fallback (Bing → Baidu)

Cookies are pulled from ``SessionStore`` at search time.  When the API
cookie is incomplete the adapter degrades gracefully to the HTML path
without raising ``AUTH_REQUIRED``.

Ported from ``legacy/.../zhihu/zhihu_search.py``.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


SEARCH_API = "https://www.zhihu.com/api/v4/search_v3"
SEARCH_PAGE_URL = "https://www.zhihu.com/search"
ZHIHU_BASE = "https://www.zhihu.com"
ZHIHU_ZHUANLAN_BASE = "https://zhuanlan.zhihu.com"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Zhihu object type → resource type.
TYPE_MAP = {
    "content": "文章",
    "article": "文章",
    "answer": "问答",
    "question": "问答",
    "topic": "话题",
}


def _strip_html(text: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def _missing_cookie_keys(cookie: str) -> list[str]:
    """Return auth cookie keys that are absent from *cookie*."""
    return [
        key
        for key in ("z_c0", "d_c0")
        if not re.search(rf"(?:^|;\s*){re.escape(key)}=", cookie)
    ]


def _public_zhihu_url(obj_type: str, obj: dict[str, Any], resource_id: str) -> str:
    """Construct a public, openable URL from a Zhihu API object."""
    if obj_type == "answer":
        question = obj.get("question") if isinstance(obj.get("question"), dict) else {}
        qid = question.get("id") or ""
        return f"{ZHIHU_BASE}/question/{qid}/answer/{resource_id}" if qid else ""
    if obj_type == "article":
        if resource_id:
            return f"{ZHIHU_ZHUANLAN_BASE}/p/{resource_id}"
        raw_url = str(obj.get("url") or "")
        return raw_url.replace("https://api.zhihu.com/articles/", f"{ZHIHU_ZHUANLAN_BASE}/p/")
    if obj_type == "question":
        return f"{ZHIHU_BASE}/question/{resource_id}" if resource_id else ""
    raw_url = str(obj.get("url") or "")
    return raw_url.replace("https://api.zhihu.com/articles/", f"{ZHIHU_ZHUANLAN_BASE}/p/")


# ---------------------------------------------------------------------------
# HTML parsing for fallback path
# ---------------------------------------------------------------------------

class _ZhihuSearchParser(HTMLParser):
    """Extract card links + titles from Zhihu's search results HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._capture_title = False
        self._current_title = ""
        self._current_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        href = attr_map.get("href") or ""
        cls = attr_map.get("class") or ""

        if tag == "a" and ("Card" in cls or "SearchResult" in cls or "ContentItem" in cls):
            self._capture_title = True
            self._current_title = ""
            self._current_url = href
        elif tag == "a" and href and ("/question/" in href or "/p/" in href):
            if not self._capture_title:
                self._capture_title = True
                self._current_title = ""
                self._current_url = href

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current_title += data

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "a":
            title = self._current_title.strip()
            url = self._current_url
            if title and url and len(title) > 4:
                if url.startswith("/"):
                    url = ZHIHU_BASE + url
                self.results.append({"title": title, "url": url})
            self._capture_title = False


def _extract_from_engine_html(html_text: str, max_results: int) -> list[dict[str, Any]]:
    """Extract zhihu.com links from a Bing/Baidu search results HTML page."""
    block_pattern = re.compile(
        r'<(?:li|div)[^>]*class="[^"]*(?:b_algo|result c-container)[^"]*"[^>]*>(.*?)</(?:li|div)>',
        re.IGNORECASE | re.DOTALL,
    )
    link_pattern = re.compile(
        r'href="(https?://(?:www\.|zhuanlan\.)?zhihu\.com/(?:question|p)/[^"&?]+)"',
        re.IGNORECASE,
    )

    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for block_match in block_pattern.finditer(html_text):
        block = block_match.group(1)
        link_match = link_pattern.search(block)
        if not link_match:
            continue
        raw_url = link_match.group(1)
        clean_url = raw_url.split("&")[0].rstrip("/")
        if clean_url in seen:
            continue
        seen.add(clean_url)

        block_text = re.sub(r"<[^>]+>", "\n", block)
        block_text = block_text.replace("&ensp;", " ").replace("&#0183;", "·")
        block_text = block_text.replace("&amp;", "&").replace("&nbsp;", " ")
        block_text = block_text.replace("&lt;", "<").replace("&gt;", ">")
        lines = [ln.strip() for ln in block_text.split("\n") if ln.strip() and len(ln.strip()) > 4]

        title_parts: list[str] = []
        for ln in lines:
            if "zhihu.com" in ln:
                continue
            if re.match(r"^\d{4}年\d{1,2}月", ln):
                break
            title_parts.append(ln)
            if len("".join(title_parts)) >= 8:
                break
        title = "".join(title_parts)[:120]

        snippet = ""
        for ln in lines[len(title_parts):]:
            if len(ln) > 15 and "zhihu.com" not in ln:
                snippet = ln[:200]
                break

        resource_id = clean_url.rstrip("/").rsplit("/", 1)[-1]
        is_answer = "/question/" in clean_url
        candidates.append(
            make_resource(
                platform="zhihu",
                title=title or f"知乎{'问答' if is_answer else '文章'} {resource_id}",
                source_url=clean_url,
                resource_type="问答" if is_answer else "文章",
                summary=snippet or None,
                language="zh",
                download_feasibility="中",
            )
        )
        if len(candidates) >= max_results:
            break
    return candidates


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ZhihuSearchAdapter:
    """Search Zhihu Q&A and articles with three-tier fallback."""

    platform_id = "zhihu"
    descriptor = descriptor_for_platform("zhihu")

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    # -- path 1: API -----------------------------------------------------

    def _search_via_api(
        self, query: str, cookie: str, limit: int
    ) -> list[dict[str, Any]]:
        headers: dict[str, str] = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.zhihu.com/",
            "x-requested-with": "fetch",
            "Cookie": cookie,
        }
        results: list[dict[str, Any]] = []
        offset = 0
        page_limit = min(limit, 20)

        while len(results) < limit:
            params = urlencode({
                "t": "general",
                "q": query,
                "correction": "1",
                "offset": str(offset),
                "limit": str(page_limit),
                "show_all_topics": "0",
                "search_source": "Filter",
                "type": "content",
            })
            url = f"{SEARCH_API}?{params}"
            request = Request(url, headers=headers)
            try:
                with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                    if getattr(resp, "status", 200) != 200:
                        break
                    raw = resp.read().decode("utf-8", errors="replace")
                    data = json.loads(raw)
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise _ZhihuError("AUTH_REQUIRED", f"知乎搜索认证无效或已过期: HTTP {exc.code}", False)
                if exc.code == 429:
                    raise _ZhihuError("RATE_LIMITED", "知乎搜索触发频率限制", True)
                break
            except (TimeoutError, URLError, json.JSONDecodeError, ValueError):
                break

            items = data.get("data") or []
            if not items:
                break

            for item in items:
                obj = item.get("object") or item
                if not isinstance(obj, dict):
                    continue
                resource = self._parse_api_item(obj, item)
                if resource:
                    results.append(resource)
                    if len(results) >= limit:
                        break

            paging = data.get("paging") or {}
            if paging.get("is_end", True):
                break
            offset += page_limit

        return results

    @staticmethod
    def _parse_api_item(obj: dict[str, Any], raw_item: dict[str, Any]) -> dict[str, Any] | None:
        obj_type = str(obj.get("type") or raw_item.get("type") or "").lower()
        resource_id = str(obj.get("id") or "")
        title = _strip_html(
            obj.get("title")
            or (raw_item.get("highlight", {}) or {}).get("title")
            or obj.get("name")
            or ""
        )
        source_url = _public_zhihu_url(obj_type, obj, resource_id)
        if not source_url or not title:
            return None

        snippet_raw = (
            (raw_item.get("highlight", {}) or {}).get("content")
            or obj.get("excerpt")
            or ""
        )
        snippet = _strip_html(snippet_raw)[:200]
        resource_type = TYPE_MAP.get(obj_type, "文章")
        author = ""
        if isinstance(obj.get("author"), dict):
            author = obj["author"].get("name", "")

        return make_resource(
            platform="zhihu",
            title=title,
            source_url=source_url,
            resource_type=resource_type,
            summary=snippet or None,
            author=author or None,
            language="zh",
            download_feasibility="中",
        )

    # -- path 2: HTML ----------------------------------------------------

    def _search_via_html(self, query: str, cookie: str, limit: int) -> list[dict[str, Any]]:
        headers: dict[str, str] = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.zhihu.com/",
        }
        if cookie:
            headers["Cookie"] = cookie

        url = f"{SEARCH_PAGE_URL}?{urlencode({'q': query, 'type': 'content'})}"
        request = Request(url, headers=headers)
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return []

        parser = _ZhihuSearchParser()
        try:
            parser.feed(html_text)
        except Exception:
            pass

        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for item in parser.results[:limit]:
            url_clean = item["url"].split("?")[0]
            if url_clean in seen:
                continue
            seen.add(url_clean)
            resource_id = url_clean.rstrip("/").rsplit("/", 1)[-1]
            results.append(
                make_resource(
                    platform="zhihu",
                    title=item["title"],
                    source_url=url_clean,
                    resource_type="问答" if "/question/" in url_clean else "文章",
                    language="zh",
                    download_feasibility="中",
                )
            )
        return results

    # -- path 3: search engine -------------------------------------------

    def _search_via_engine(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search ``site:zhihu.com`` via Bing then Baidu."""
        for engine in ("bing", "baidu"):
            if engine == "bing":
                url = f"https://www.bing.com/search?q={quote(f'{query} site:zhihu.com')}&count={min(limit * 2, 30)}"
            else:
                url = f"https://www.baidu.com/s?wd={quote(f'{query} site:zhihu.com')}&rn={min(limit * 2, 30)}"
            headers = {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            try:
                request = Request(url, headers=headers)
                with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                    html_text = resp.read().decode("utf-8", errors="replace")
            except Exception:
                continue
            candidates = _extract_from_engine_html(html_text, limit)
            if candidates:
                return candidates
        return []

    # -- public API ------------------------------------------------------

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        session_data = self.session_store.get_session_data("zhihu")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""

        # Path 1: API (needs z_c0 + d_c0).
        if cookie and not _missing_cookie_keys(cookie):
            try:
                results = self._search_via_api(query, cookie, limit)
            except _ZhihuError as exc:
                # If auth is rejected, don't try HTML — it won't help.
                return [], exc.to_dict()
            if results:
                return results, None

        # Path 2: HTML fallback.
        results = self._search_via_html(query, cookie, limit)
        if results:
            return results, None

        # Path 3: search-engine fallback.
        results = self._search_via_engine(query, limit)
        if results:
            return results, None

        # All paths exhausted.
        if session_data is None:
            return [], adapter_error("AUTH_REQUIRED", "知乎 session 未配置，且搜索引擎兜底无结果", False)
        return [], adapter_error("PARTIAL_FAILURE", "知乎搜索三级降级均无结果", False)

class _ZhihuError(Exception):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
