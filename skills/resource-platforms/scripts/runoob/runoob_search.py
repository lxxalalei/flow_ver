#!/usr/bin/env python3
"""Search public Runoob programming tutorials."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from shared.http_client import urlopen_with_fallback


BASE_URL = "https://www.runoob.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def request_text(query: str, timeout: float) -> str:
    url = BASE_URL + "/?" + urllib.parse.urlencode({"s": query})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with urlopen_with_fallback(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() if response.headers else None
        return raw.decode(charset or "utf-8", errors="replace")


def normalize_url(value: str) -> str:
    url = urllib.parse.urljoin(BASE_URL + "/", html.unescape(value.strip()))
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in {"runoob.com", "www.runoob.com"}:
        return ""
    return urllib.parse.urlunsplit(("https", "www.runoob.com", parsed.path, parsed.query, ""))


def resource_type(source_url: str, title: str) -> str:
    lowered = (source_url + " " + title).lower()
    if "/quiz/" in lowered or "测验" in title:
        return "编程测验"
    if "/w3cnote/" in lowered:
        return "编程文章"
    if "实例" in title or "example" in lowered:
        return "编程实例"
    return "编程教程"


def parse_results(page: str, max_results: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    blocks = re.split(r'<div\s+class=["\']archive-list-item["\'][^>]*>', page, flags=re.I)[1:]
    for block in blocks:
        link = re.search(
            r'<h2\b[^>]*>\s*<a\b([^>]*)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>',
            block,
            re.I | re.S,
        )
        if not link:
            continue
        source_url = normalize_url(link.group(2))
        title = clean_text(link.group(4))
        if not source_url or not title or source_url in seen:
            continue
        seen.add(source_url)
        attrs = link.group(1) + link.group(3)
        source_id_match = re.search(r"push_runoob_search\((\d+)\)", attrs)
        source_id = source_id_match.group(1) if source_id_match else hashlib.sha1(source_url.encode()).hexdigest()[:16]
        description_match = re.search(r"<p\b[^>]*>(.*?)</p>", block, re.I | re.S)
        description = clean_text(description_match.group(1))[:500] if description_match else ""
        result: dict[str, Any] = {
            "resource_id": f"runoob:{source_id}",
            "platform": "runoob",
            "title": title,
            "source_url": source_url,
            "type": resource_type(source_url, title),
            "platform_signals": {"rank": len(results) + 1},
            "raw_metadata": {
                "source_id": source_id,
                "search_method": "runoob-wordpress-search",
            },
        }
        if description:
            result["description"] = description
        results.append(result)
        if len(results) >= max_results:
            break
    return results


def search(query: str, max_results: int, timeout: float) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        results = parse_results(request_text(query, timeout), max_results)
    except TimeoutError as exc:
        errors.append({"error_code": "NETWORK_TIMEOUT", "message": str(exc), "retryable": True})
    except urllib.error.HTTPError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": f"HTTP {exc.code}", "retryable": exc.code >= 500})
    except urllib.error.URLError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": str(exc.reason), "retryable": True})
    except Exception as exc:
        errors.append({"error_code": "SEARCH_EXECUTION_FAILED", "message": str(exc), "retryable": True})

    document: dict[str, Any] = {
        "query": query,
        "search_method": "runoob-wordpress-search",
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
    parser = argparse.ArgumentParser(description="Search public Runoob tutorials.")
    sub = parser.add_subparsers(dest="cmd")
    command = sub.add_parser("search", help="search Runoob")
    command.add_argument("query")
    command.add_argument("--max", type=int, default=10)
    command.add_argument("--timeout", type=float, default=20)
    command.add_argument("-o", "--output", default=None)
    args = parser.parse_args()
    if args.cmd != "search":
        parser.print_help()
        return 2
    document = search(args.query, max(1, min(args.max, 20)), max(1.0, args.timeout))
    write_output(document, args.output)
    return 0 if document["results"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
