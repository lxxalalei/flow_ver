"""Baidu Wenku (百度文库) search adapter.

Fetches the search results page and extracts embedded pageData JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


SEARCH_URL = "https://wenku.baidu.com/search?word={query}"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


class BaiduwenkuSearchAdapter:
    platform_id = "baiduwenku"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = SEARCH_URL.format(query=quote(query))
        request = Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"百度文库搜索失败：{type(exc).__name__}: {exc}", True)

        # Extract embedded pageData JSON containing search results.
        items = self._extract_search_items(page)
        resources: list[dict[str, Any]] = []
        for item in items:
            title = _clean(item.get("title"))
            doc_id = str(item.get("docId") or "").strip()
            if not title or not doc_id:
                continue
            doc_url = f"https://wenku.baidu.com/view/{doc_id}.html"
            resources.append(make_resource(
                platform="baiduwenku",
                title=title,
                source_url=doc_url,
                resource_type="文档",
                summary=_clean(item.get("abstract") or item.get("desc"))[:300] or None,
                platform_signals={
                    "doc_type": item.get("doc_type"),
                    "page_num": item.get("page_num"),
                    "download_count": item.get("download_count"),
                    "upload_time": item.get("upload_time"),
                    "is_vip": item.get("is_vip"),
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None

    @staticmethod
    def _extract_search_items(page: str) -> list[dict[str, Any]]:
        """Extract search result items from the embedded pageData JSON."""
        match = re.search(r"window\.pageData\s*=\s*", page)
        if not match:
            return []
        start = match.end()
        while start < len(page) and page[start].isspace():
            start += 1
        if start >= len(page) or page[start] not in "{[":
            return []
        try:
            data = _extract_json(page, start)
        except (json.JSONDecodeError, ValueError):
            return []
        if not data:
            return []
        # Navigate to the actual search result documents.
        # Path: sulaData.__sula_prefetchData.items.PCSearch.result.docList
        try:
            result = (
                data["sulaData"]["__sula_prefetchData"]["items"]
                ["PCSearch"]["result"]["docList"]
            )
            if isinstance(result, list):
                return [d for d in result if isinstance(d, dict)]
        except (KeyError, TypeError):
            pass
        # Fallback: recursive search, skipping known non-result sections.
        return _find_items(data)


def _extract_json(page: str, start: int) -> Any:
    opening = page[start]
    closing = "}" if opening == "{" else "]"
    stack = [closing]
    in_str = False
    esc = False
    quote = ""
    for i in range(start + 1, len(page)):
        ch = page[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in {'"', "'"}:
            in_str = True
            quote = ch
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and ch == stack[-1]:
                stack.pop()
                if not stack:
                    return json.loads(page[start:i + 1])
    return None


def _find_items(data: Any) -> list[dict[str, Any]]:
    """Recursively search for docList items, skipping ad/recommendation cards."""
    _SKIP_KEYS = {"membershipCards", "recCards", "hotDocs", "ads", "adCards"}
    if isinstance(data, dict):
        for path in (("docList",), ("items",)):
            current = data.get(path[0])
            if isinstance(current, list) and current and all(
                isinstance(i, dict) and i.get("docId") for i in current
            ):
                return current
        for k, v in data.items():
            if k in _SKIP_KEYS:
                continue
            found = _find_items(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_items(item)
            if found:
                return found
    return []
