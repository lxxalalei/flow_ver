#!/usr/bin/env python3
"""Search China National Library catalog and website resources."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from shared.http_client import urlopen_with_fallback
from yuewen_search import search_yuewen


CATALOG_SEARCH_URL = "http://find.nlc.cn/search/doSearch"
CATALOG_DETAIL_URL = "http://find.nlc.cn/search/showDocDetails"
SITE_SEARCH_URL = "https://www.nlc.cn/search-api/elasticsearch/document/onSiteQuery"
SITE_BASE_URL = "https://www.nlc.cn"
HOLDING_SOURCES = {"ucs01", "ucs09"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def request_text(url: str, timeout: float, accept: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with urlopen_with_fallback(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() if response.headers else None
        return raw.decode(charset or "utf-8", errors="replace")


def extract(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    return clean_text(match.group(1)) if match else ""


def catalog_url(query: str, page_no: int) -> str:
    params = {
        "query": query,
        "secQuery": "",
        "actualQuery": query,
        "searchType": "2",
        "docType": "全部",
        "isGroup": "isGroup",
        "targetFieldLog": "全部字段",
        "fromHome": "true",
        "pageNo": str(page_no),
    }
    return CATALOG_SEARCH_URL + "?" + urllib.parse.urlencode(params)


def detail_url(doc_id: str, data_source: str, query: str) -> str:
    return CATALOG_DETAIL_URL + "?" + urllib.parse.urlencode(
        {"docId": doc_id, "dataSource": data_source, "query": query}
    )


def parse_catalog_page(page: str, query: str, start_rank: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    blocks = re.split(r'<div\s+class=["\']article_item["\'][^>]*>', page, flags=re.I)[1:]
    for block in blocks:
        identity = re.search(
            r"makeDetailUrl\(this,\s*['\"]/search/showDocDetails\?['\"],\s*['\"]([^'\"]+)['\"],\s*['\"]([^'\"]+)['\"]",
            block,
            re.I,
        )
        if not identity:
            continue
        doc_id, data_source = identity.group(1).strip(), identity.group(2).strip()
        if data_source not in HOLDING_SOURCES:
            continue
        title = extract(r'<div\s+class=["\']book_name["\'][^>]*>.*?<a\b[^>]*>(.*?)</a>', block)
        if not title:
            continue
        document_type = extract(r"文献类型\s*[：:]\s*<span\s+class=[\"']book_val[\"'][^>]*>(.*?)</span>", block)
        author = extract(r"著者\s*[：:]\s*<span\s+class=[\"']book_val[\"'][^>]*>(.*?)</span>", block)
        publish_time = extract(r"出版年份\s*[：:]\s*<span\s+class=[\"']book_val[\"'][^>]*>(.*?)</span>", block)
        publisher = extract(r"出版社\s*<span\s+class=[\"']book_val[\"'][^>]*>(.*?)</span>", block)
        source_database = extract(r"来源数据库\s*[：:]\s*<span\s+class=[\"']book_val[\"'][^>]*>(.*?)</span>", block)
        thumbnail_url = extract(r'<img\s+class=["\']book_img["\'][^>]*\bsrc=["\']([^"\']+)["\']', block)
        if thumbnail_url.startswith("/"):
            thumbnail_url = urllib.parse.urljoin(CATALOG_SEARCH_URL, thumbnail_url)
        if thumbnail_url.endswith("/pictures/0.jpg"):
            thumbnail_url = ""
        result: dict[str, Any] = {
            "resource_id": f"nlc:{data_source}:{doc_id}",
            "platform": "nlc",
            "title": title,
            "source_url": detail_url(doc_id, data_source, query),
            "download_feasibility": "低",
            "platform_signals": {"rank": start_rank + len(results)},
            "raw_metadata": {
                "scope": "catalog",
                "doc_id": doc_id,
                "data_source": data_source,
                "source_database": source_database,
                "publisher": publisher,
                "document_type": document_type,
            },
        }
        for key, value in (
            ("type", document_type),
            ("author", author),
            ("publish_time", publish_time),
            ("thumbnail_url", thumbnail_url),
        ):
            if value:
                result[key] = value
        result["raw_metadata"] = {
            key: value for key, value in result["raw_metadata"].items() if value
        }
        results.append(result)
    return results


def search_catalog(query: str, max_results: int, timeout: float) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_pages = min(6, max(1, math.ceil(max_results / 10)))
    for page_no in range(1, max_pages + 1):
        page = request_text(catalog_url(query, page_no), timeout, "text/html,application/xhtml+xml")
        page_results = parse_catalog_page(page, query, len(results) + 1)
        if not page_results:
            break
        for item in page_results:
            if item["resource_id"] in seen:
                continue
            seen.add(item["resource_id"])
            results.append(item)
            if len(results) >= max_results:
                return results
    return results


def site_url(query: str, max_results: int) -> str:
    params = {
        "keywords": query,
        "columnId": "",
        "year": "",
        "pageNum": "1",
        "pageSize": str(max_results),
    }
    return SITE_SEARCH_URL + "?" + urllib.parse.urlencode(params)


def search_site(query: str, max_results: int, timeout: float) -> list[dict[str, Any]]:
    raw = json.loads(request_text(site_url(query, max_results), timeout, "application/json"))
    if raw.get("code") != 200 or not isinstance(raw.get("data"), dict):
        raise ValueError(str(raw.get("msg") or "NLC site search returned an invalid response"))
    items = raw["data"].get("data") or []
    results: list[dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        title = clean_text(item.get("title"))
        path = item.get("outLinkUrl") or item.get("filePath") or ""
        if not title or not path:
            continue
        source_url = urllib.parse.urljoin(SITE_BASE_URL + "/", str(path))
        result: dict[str, Any] = {
            "resource_id": f"nlc:site:{item['id']}",
            "platform": "nlc",
            "title": title,
            "source_url": source_url,
            "type": "国家图书馆网站内容",
            "platform_signals": {"rank": rank},
            "raw_metadata": {
                "scope": "site",
                "source_id": str(item["id"]),
                "file_path": str(item.get("filePath") or ""),
            },
        }
        description = clean_text(item.get("summary"))
        if description:
            result["description"] = description
        results.append(result)
    return results


def search(query: str, scope: str, max_results: int, timeout: float) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        if scope == "site":
            results = search_site(query, max_results, timeout)
        elif scope in {"digital", "ebook"}:
            results = search_yuewen(query, max_results, timeout, request_text)
        else:
            results = search_catalog(query, max_results, timeout)
    except TimeoutError as exc:
        errors.append({"error_code": "NETWORK_TIMEOUT", "message": str(exc), "retryable": True})
    except urllib.error.HTTPError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": f"HTTP {exc.code}", "retryable": exc.code >= 500})
    except urllib.error.URLError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": str(exc.reason), "retryable": True})
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append({"error_code": "PARSE_FORMAT_NOT_SUPPORTED", "message": str(exc), "retryable": False})
    except Exception as exc:
        errors.append({"error_code": "SEARCH_EXECUTION_FAILED", "message": str(exc), "retryable": True})

    document: dict[str, Any] = {
        "query": query,
        "scope": scope,
        "search_method": f"nlc-{scope}",
        "results": results,
        "errors": errors,
        "searched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if errors and not results:
        document["error"] = errors[0]
    return document


def write_output(document: dict[str, Any], output: str | None) -> None:
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    else:
        sys.stdout.buffer.write(content.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Search China National Library resources.")
    sub = parser.add_subparsers(dest="cmd")
    command = sub.add_parser("search", help="search NLC")
    command.add_argument("query")
    command.add_argument(
        "--scope",
        choices=("catalog", "site", "digital", "ebook"),
        default="catalog",
    )
    command.add_argument("--max", type=int, default=10)
    command.add_argument("--timeout", type=float, default=20)
    command.add_argument("-o", "--output", default=None)
    args = parser.parse_args()
    if args.cmd != "search":
        parser.print_help()
        return 2
    document = search(args.query, args.scope, max(1, min(args.max, 50)), max(1.0, args.timeout))
    write_output(document, args.output)
    return 0 if document["results"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
