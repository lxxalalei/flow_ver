#!/usr/bin/env python3
"""Search and parse public NLC Yuewen ebook listings."""

from __future__ import annotations

import html
import math
import re
import urllib.parse
from typing import Any, Callable


YUEWEN_BASE_URL = "http://read.nlc.cn"
YUEWEN_SEARCH_URL = f"{YUEWEN_BASE_URL}/yuewen/index"
PAGE_SIZE = 15


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def extract_attribute(attributes: str, name: str) -> str:
    match = re.search(
        rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1",
        attributes,
        re.I | re.S,
    )
    return html.unescape(match.group(2)).strip() if match else ""


def extract_class_text(block: str, class_name: str) -> str:
    match = re.search(
        rf"<(?P<tag>[a-z0-9]+)\b[^>]*\bclass\s*=\s*([\"'])[^\"']*\b{re.escape(class_name)}\b[^\"']*\2[^>]*>"
        rf"(?P<body>.*?)</(?P=tag)\s*>",
        block,
        re.I | re.S,
    )
    return clean_text(match.group("body")) if match else ""


def yuewen_search_url(query: str, page_no: int = 1) -> str:
    params = {"title": query}
    if page_no > 1:
        params["pageNo"] = str(page_no)
    return YUEWEN_SEARCH_URL + "?" + urllib.parse.urlencode(params)


def parse_yuewen_page(
    page: str,
    start_rank: int = 1,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in re.finditer(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", page, re.I | re.S):
        attributes = anchor.group("attrs")
        classes = extract_attribute(attributes, "class").split()
        if "book" not in classes:
            continue
        href = extract_attribute(attributes, "href")
        identity = re.search(r"(?:^|/)yuewen/detail\?[^#]*\bid=(\d+)", href, re.I)
        if not identity:
            continue
        yuewen_id = identity.group(1)
        if yuewen_id in seen:
            continue
        block = anchor.group("body")
        title = extract_class_text(block, "tt")
        if not title:
            continue
        author_block = re.search(
            r"<(?P<tag>[a-z0-9]+)\b[^>]*\bclass\s*=\s*([\"'])[^\"']*\btxt1\b[^\"']*\2[^>]*>"
            r"(?P<body>.*?)</(?P=tag)\s*>",
            block,
            re.I | re.S,
        )
        author_html = author_block.group("body") if author_block else ""
        category = extract_class_text(author_html, "lab")
        author = clean_text(re.sub(r"<i\b[^>]*>.*?</i\s*>", " ", author_html, flags=re.I | re.S))
        description = extract_class_text(block, "txt2")
        image = re.search(r"<img\b(?P<attrs>[^>]*)>", block, re.I | re.S)
        thumbnail_url = extract_attribute(image.group("attrs"), "src") if image else ""
        if thumbnail_url:
            thumbnail_url = urllib.parse.urljoin(YUEWEN_BASE_URL + "/", thumbnail_url)
        result: dict[str, Any] = {
            "resource_id": f"nlc:yuewen:{yuewen_id}",
            "platform": "nlc",
            "title": title,
            "source_url": f"{YUEWEN_BASE_URL}/yuewen/detail?id={yuewen_id}",
            "type": "电子书",
            "is_free": True,
            "language": "zh-CN",
            "download_feasibility": "中",
            "platform_signals": {"rank": start_rank + len(results)},
            "raw_metadata": {
                "scope": "digital",
                "source_id": yuewen_id,
                "classify": category,
            },
        }
        for key, value in (
            ("author", author),
            ("description", description),
            ("thumbnail_url", thumbnail_url),
        ):
            if value:
                result[key] = value
        result["raw_metadata"] = {
            key: value for key, value in result["raw_metadata"].items() if value
        }
        seen.add(yuewen_id)
        results.append(result)
        if max_results is not None and len(results) >= max_results:
            break
    return results


def search_yuewen(
    query: str,
    max_results: int,
    timeout: float,
    request_text: Callable[[str, float, str], str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_pages = min(8, max(1, math.ceil(max_results / PAGE_SIZE)))
    for page_no in range(1, max_pages + 1):
        page = request_text(
            yuewen_search_url(query, page_no),
            timeout,
            "text/html,application/xhtml+xml",
        )
        page_results = parse_yuewen_page(page, len(results) + 1)
        if not page_results:
            break
        added = 0
        for item in page_results:
            if item["resource_id"] in seen:
                continue
            seen.add(item["resource_id"])
            results.append(item)
            added += 1
            if len(results) >= max_results:
                return results
        if added == 0 or len(page_results) < PAGE_SIZE:
            break
    return results
