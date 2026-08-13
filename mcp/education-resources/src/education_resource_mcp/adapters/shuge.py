"""Shuge (书格) public open-storage search adapter.

Uses the public OpenList API of the full-site public storage server
(https://shuge.hanjihebi.com, "书格网站资源" tree).  The site declares its
content as public-domain classical texts; no auth is required and files are
served as direct downloads through the ``/d/`` streaming endpoint.

The adapter intentionally does not scrape the WordPress site, short links
(s.shuge.org) or third-party cloud-drive links; only files present in the
public OpenList tree are returned.

In addition to plain keyword queries, ``search`` accepts Shuge detail-page
URLs (``shuge.org/view/<slug>``) and short links (``s.shuge.org/<code>``):
the adapter fetches the page, extracts the book title, then looks that title
up in the public storage tree.  Only ``*.shuge.org`` hosts may be fetched
(SSRF guard); the site's own cloud-drive distribution channel stays out of
scope.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


BASE_URL = "https://shuge.hanjihebi.com"
SEARCH_ROOT = "/书格网站资源"
SEARCH_API = "/api/fs/search"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Detail pages live under /view/<slug> on www.shuge.org; short links live on
# s.shuge.org.  Both patterns accept an optional scheme, optional subdomains
# under shuge.org, and an optional trailing slash.  Anything else is treated
# as an ordinary keyword query.
_DETAIL_URL_PATTERN = re.compile(
    r"^(?:https?://)?(?:[A-Za-z0-9-]+\.)*shuge\.org/view/[A-Za-z0-9_./-]+/?$"
)
_SHORT_URL_PATTERN = re.compile(r"^(?:https?://)?s\.shuge\.org/[A-Za-z0-9_.-]+/?$")
# WordPress titles look like "五经类语 – 书格" (em/en dash, hyphen, bar).
_SITE_TITLE_SUFFIX = re.compile(r"[\s\u00a0]*[\u2014\u2013\-|｜]\s*书格\s*$")


class ShugeSearchAdapter:
    """Search the public Shuge OpenList storage via its JSON search API."""

    platform_id = "shuge"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        normalized = query.strip()
        if self._is_detail_link(normalized):
            return self._search_via_detail_page(normalized, limit)
        return self._search_storage(normalized, limit)

    @staticmethod
    def _is_detail_link(query: str) -> bool:
        return bool(
            _DETAIL_URL_PATTERN.match(query) or _SHORT_URL_PATTERN.match(query)
        )

    @staticmethod
    def _normalize_detail_url(url: str) -> str:
        if not re.match(r"^https?://", url):
            return "https://" + url
        return url

    def _search_via_detail_page(
        self, url: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        url = self._normalize_detail_url(url)
        request = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urlopen_with_fallback(
                request,
                timeout=self.timeout,
                # www.shuge.org is behind Cloudflare bot fingerprinting; a
                # urllib TLS fingerprint can be 403-blocked while curl works.
                curl_on_status=frozenset({403}),
            ) as resp:
                raw = resp.read()
        except HTTPError as exc:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"书格详情页不可用：HTTP {exc.code}",
                False,
            )
        except Exception as exc:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"书格详情页访问失败：{type(exc).__name__}: {exc}",
                True,
            )
        title = self._extract_title(raw.decode("utf-8", "replace"))
        if not title:
            return [], adapter_error(
                "PARTIAL_FAILURE", "无法从书格详情页提取书名", False
            )
        resources, err = self._search_storage(title, limit)
        if err is not None:
            return resources, err
        for resource in resources:
            signals = resource.setdefault("metadata", {}).setdefault(
                "platform_signals", {}
            )
            signals["detail_url"] = url
        return resources, None

    @staticmethod
    def _extract_title(html_text: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
        if match is None:
            return ""
        title = _html.unescape(match.group(1)).strip()
        title = _SITE_TITLE_SUFFIX.sub("", title).strip()
        if not title or title == "书格":
            # Home page or a redirect back to it: not a usable detail title.
            return ""
        return title

    def _search_storage(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        payload = {
            "parent": SEARCH_ROOT,
            "keywords": query,
            "scope": 2,  # recursive within parent
            "page": 1,
            "per_page": min(limit, 50),
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            BASE_URL + SEARCH_API,
            data=body,
            headers={
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except Exception as exc:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"书格存储搜索失败：{type(exc).__name__}: {exc}",
                True,
            )
        try:
            parsed = json.loads(raw)
        except ValueError:
            return [], adapter_error(
                "PARTIAL_FAILURE", "书格存储搜索返回非 JSON 响应", True
            )
        if not isinstance(parsed, dict) or parsed.get("code") != 200:
            message = str(parsed.get("message") or "书格存储搜索失败")[:200]
            return [], adapter_error("PARTIAL_FAILURE", message, False)
        items = (parsed.get("data") or {}).get("content") or []
        if not isinstance(items, list):
            return [], adapter_error("PARTIAL_FAILURE", "书格存储搜索响应结构异常", False)

        resources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or item.get("is_dir"):
                continue
            name = str(item.get("name") or "").strip()
            parent = str(item.get("parent") or "").strip()
            if not name or not parent:
                continue
            file_path = f"{parent.rstrip('/')}/{name}"
            if file_path in seen:
                continue
            seen.add(file_path)
            source_url = BASE_URL + "/d/" + quote(file_path.lstrip("/"), safe="/")
            size = item.get("size")
            resources.append(
                make_resource(
                    platform="shuge",
                    title=name,
                    source_url=source_url,
                    resource_type="古籍",
                    summary=f"书格公开存储文件（{file_path}）",
                    platform_signals={
                        "file_path": file_path,
                        "file_name": name,
                        "size_bytes": size if isinstance(size, int) and size >= 0 else None,
                    },
                )
            )
        return resources, None
