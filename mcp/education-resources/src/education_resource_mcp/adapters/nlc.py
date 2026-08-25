"""NLC (中国国家图书馆) catalog search adapter.

Searches the public catalog at find.nlc.cn. No auth required.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


CATALOG_SEARCH_URL = "http://find.nlc.cn/search/doSearch"
CATALOG_DETAIL_URL = "http://find.nlc.cn/search/showDocDetails"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


def _extract(pattern: str, block: str) -> str:
    m = re.search(pattern, block, re.I | re.S)
    return _clean(m.group(1)) if m else ""


class NlcSearchAdapter:
    platform_id = "nlc"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        params = urlencode({
            "query": query,
            "secQuery": "",
            "actualQuery": query,
            "searchType": "2",
            "docType": "全部",
            "isGroup": "isGroup",
            "targetFieldLog": "全部字段",
            "fromHome": "true",
            "pageNo": "1",
        })
        url = f"{CATALOG_SEARCH_URL}?{params}"
        request = Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": CATALOG_SEARCH_URL,
        })
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                page = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"国家图书馆搜索失败：{type(exc).__name__}: {exc}", True)

        blocks = re.split(r'<div\s+class=["\']article_item["\'][^>]*>', page, flags=re.I)[1:]
        resources: list[dict[str, Any]] = []
        for block in blocks:
            identity = re.search(
                r"makeDetailUrl\([^)]*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]",
                block, re.I,
            )
            if not identity:
                continue
            doc_id = identity.group(1).strip()
            data_source = identity.group(2).strip()
            title = _extract(r'<div\s+class=["\']book_name["\'][^>]*>.*?<a\b[^>]*>(.*?)</a>', block)
            if not title:
                continue
            detail_url = f"{CATALOG_DETAIL_URL}?{urlencode({'docId': doc_id, 'dataSource': data_source, 'query': query})}"
            author = _extract(r"著者[：:]<span[^>]*>(.*?)</span>", block)
            pub_year = _extract(r"出版年份[：:]<span[^>]*>(.*?)</span>", block)
            doc_type = _extract(r"文献类型[：:]<span[^>]*>(.*?)</span>", block)
            publisher = _extract(r"出版社[^：:]*<span[^>]*>(.*?)</span>", block)
            resources.append(make_resource(
                platform="nlc",
                title=title,
                source_url=detail_url,
                resource_type="图书",
                summary=f"文献类型: {doc_type}；著者: {author}；出版年份: {pub_year}" if doc_type or author or pub_year else None,
                author=author or None,
                platform_signals={
                    "doc_type": doc_type or None,
                    "publish_year": pub_year or None,
                    "publisher": publisher or None,
                    "data_source": data_source,
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None
