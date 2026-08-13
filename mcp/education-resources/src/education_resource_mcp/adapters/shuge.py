"""Shuge (书格) public open-storage search adapter.

Uses the public OpenList API of the full-site public storage server
(https://shuge.hanjihebi.com, "书格网站资源" tree).  The site declares its
content as public-domain classical texts; no auth is required and files are
served as direct downloads through the ``/d/`` streaming endpoint.

The adapter intentionally does not scrape the WordPress site, short links
(s.shuge.org) or third-party cloud-drive links; only files present in the
public OpenList tree are returned.
"""

from __future__ import annotations

import json
from typing import Any
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


class ShugeSearchAdapter:
    """Search the public Shuge OpenList storage via its JSON search API."""

    platform_id = "shuge"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(
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