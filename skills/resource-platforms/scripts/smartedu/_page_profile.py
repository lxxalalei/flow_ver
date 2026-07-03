#!/usr/bin/env python3
"""SmartEdu 页面 HTML/JS 结构线索分析。

Phase 3E 从 smartedu_resources.py 拆出的页面分析模块：从页面 HTML/JS 中提取
SmartEdu 接口、详情 ID、资源链接和页面类型线索。纯分析逻辑，不含候选生成；
smartedu_resources.py 的 page-profile 命令通过 import 复用。
"""

from __future__ import annotations

import re
import urllib.parse

from _auth_http import request_text
from _text_utils import RESOURCE_EXTENSIONS, absolute_url, norm, resource_extension


# 用于识别 SmartEdu 接口 URL 的关键词（页面 JS 中出现的接口路径线索）。
SMARTEDU_API_TERMS = ["api", "resources", "resource", "librarylist", "details", "search", "aggregate", "combine", "ndrv2", "catalog", "course", "lesson", "content"]


def extract_smartedu_api_hints(html_text: str, base_url: str) -> list[str]:
    hints: list[str] = []
    patterns = [
        r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+",
        r"['\"]((?:/|//)[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{3,240})['\"]",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html_text):
            value = match.group(1) if match.lastindex else match.group(0)
            cleaned = absolute_url(base_url, value)
            if any(term in cleaned.lower() for term in SMARTEDU_API_TERMS):
                hints.append(cleaned)
    return list(dict.fromkeys(hints))[:80]


def extract_script_sources(html_text: str, base_url: str) -> list[str]:
    scripts: list[str] = []
    for match in re.finditer(r"""<script[^>]+src=["']([^"']+)["']""", html_text, re.I):
        scripts.append(absolute_url(base_url, match.group(1)))
    return list(dict.fromkeys(scripts))[:80]


def fetch_script_texts(script_urls: list[str], access_token: str | None, cookie: str | None, extra_headers: dict[str, str], timeout: int, limit: int) -> tuple[str, list[dict[str, str]]]:
    parts: list[str] = []
    failures: list[dict[str, str]] = []
    for url in script_urls[:limit]:
        try:
            parts.append(request_text(url, access_token=access_token, timeout=timeout, cookie=cookie, extra_headers=extra_headers))
        except Exception as exc:
            failures.append({"url": url, "error": str(exc)})
    return "\n".join(parts), failures


def extract_detail_hints(html_text: str, base_url: str) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for match in re.finditer(r"(?:contentId|resourceId|resource_id|content_id|courseId)[=:]['\"]?([A-Za-z0-9_-]{6,})", html_text):
        hints.append({"resource_id": match.group(1), "source": "inline-id"})
    for match in re.finditer(r"https?://basic\.smartedu\.cn/([^/]+)/detail\?([^'\"\s<>]+)", html_text):
        query = urllib.parse.parse_qs(match.group(2))
        resource_id = (query.get("contentId") or query.get("id") or [""])[0]
        hints.append(
            {
                "resource_id": resource_id,
                "catalog": match.group(1),
                "source": match.group(0),
            }
        )
    for match in re.finditer(r"['\"]((?:/[^'\"]+)?/detail\?[^'\"]+)['\"]", html_text):
        url = absolute_url(base_url, match.group(1))
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        resource_id = (query.get("contentId") or query.get("id") or [""])[0]
        catalog = (query.get("catalogType") or [""])[0]
        hints.append({"resource_id": resource_id, "catalog": catalog, "source": url})
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in hints:
        key = "|".join([norm(item.get("resource_id")), norm(item.get("catalog")), norm(item.get("source"))])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:80]


def extract_resource_link_hints(html_text: str, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in re.finditer(r"""(?:href|src)=["']([^"']+)["']""", html_text, re.I):
        url = absolute_url(base_url, match.group(1))
        ext = resource_extension(url)
        if ext in RESOURCE_EXTENSIONS:
            links.append({"url": url, "format": ext})
    return list({item["url"]: item for item in links}.values())[:80]


def infer_page_type(html_text: str, url: str, api_hints: list[str], detail_hints: list[dict[str, str]], resource_links: list[dict[str, str]]) -> str:
    lower = f"{html_text[:5000]} {url}".lower()
    if "/detail" in url or detail_hints:
        return "detail_or_detail_capable_page"
    if "librarylist" in lower:
        return "catalog_config_page"
    if api_hints and ("root" in lower or "webpack" in lower or "chunk" in lower):
        return "spa_route_page"
    if resource_links:
        return "static_resource_page"
    if any(term in lower for term in ["search", "resources", "catalog"]):
        return "resource_listing_or_search_page"
    return "unknown"
