#!/usr/bin/env python3
"""Search Baidu Wenku public result metadata.

This helper only discovers public search candidates from wenku.baidu.com. It
does not download documents, bypass paywalls, or claim that a document is free
or complete.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SEARCH_URL = "https://wenku.baidu.com/search?word={query}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
WENKU_HOST = "wenku.baidu.com"
DOC_URL_PATTERN = re.compile(
    r"https?://wenku\.baidu\.com/(?:view|aggs|ndview)/(?:[A-Za-z0-9_-]+/)?"
    r"([0-9a-fA-F]{16,})"
)


class SearchBlockedError(RuntimeError):
    """Baidu returned a verification or anti-bot page."""


def request_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": "https://wenku.baidu.com/",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        is_cert_error = isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc)
        if not is_cert_error:
            raise
        response = urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context())
    with response:
        status = getattr(response, "status", 200)
        if status >= 400:
            raise urllib.error.HTTPError(url, status, f"HTTP {status}", response.headers, None)
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def is_blocked_page(page: str) -> bool:
    lowered = page.lower()
    if "wenku.baidu.com/view/" in lowered or '"pcsearch"' in lowered:
        return False
    return any(marker in lowered for marker in (
        "百度安全验证",
        "安全验证",
        "verify.baidu.com",
        "captcha",
        "verify you are human",
    ))


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return compact_cjk_spacing(value)


def compact_cjk_spacing(value: str) -> str:
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"(?<=[）》】])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"\s+([，。！？；：、）》】])", r"\1", value)
    value = re.sub(r"([（《【])\s+", r"\1", value)
    value = re.sub(r"\s+(:)", r"\1", value)
    return value.strip()


def normalize_url(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    url = html.unescape(raw.strip()).replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = "https://wenku.baidu.com" + url
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if parsed.scheme not in {"http", "https"} or host != WENKU_HOST:
        return ""
    # Drop ranking/tracking query parameters. The document path is stable.
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, "", ""))


def extract_doc_id(url: str, fallback: Any = "") -> str:
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    match = DOC_URL_PATTERN.search(url)
    return match.group(1) if match else ""


def extract_json_assignment(page: str, assignment_pattern: str) -> Any:
    match = re.search(assignment_pattern, page)
    if not match:
        return None
    start = match.end()
    while start < len(page) and page[start].isspace():
        start += 1
    if start >= len(page) or page[start] not in "{[":
        return None

    opening = page[start]
    closing = "}" if opening == "{" else "]"
    stack = [closing]
    in_string = False
    escape = False
    quote = ""

    for index in range(start + 1, len(page)):
        char = page[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            quote = char
            continue
        if char in "{[":
            stack.append("}" if char == "{" else "]")
            continue
        if char in "}]":
            if not stack or char != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return json.loads(page[start:index + 1])
    return None


def iter_nested(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_nested(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_nested(child)


def pc_search_items(page_data: Any) -> list[dict[str, Any]]:
    if not isinstance(page_data, dict):
        return []
    paths = [
        ("sulaData", "__sula_prefetchData", "items", "PCSearch", "result", "items"),
        ("__sula_prefetchData", "items", "PCSearch", "result", "items"),
        ("prefetchData", "items", "PCSearch", "result", "items"),
    ]
    for path in paths:
        current: Any = page_data
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if isinstance(current, list):
            return [item for item in current if isinstance(item, dict)]

    discovered: list[dict[str, Any]] = []
    for node in iter_nested(page_data):
        if node.get("sceneID") == "PCSearch" and isinstance(node.get("data"), dict):
            discovered.append(node)
    return discovered


def parse_page_data(page: str) -> Any:
    for pattern in (
        r"window\.pageData\s*=\s*",
        r"prefetchData\s*:\s*",
    ):
        try:
            parsed = extract_json_assignment(page, pattern)
        except json.JSONDecodeError:
            parsed = None
        if parsed:
            return parsed
    return None


def file_type_label(value: Any) -> str:
    mapping = {
        1: "doc",
        2: "ppt",
        3: "xls",
        4: "pdf",
        5: "txt",
        6: "ppt",
    }
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return ""
    return mapping.get(numeric, "")


def item_to_candidate(item: dict[str, Any], query: str, rank: int) -> dict[str, Any] | None:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    if not data:
        return None

    source_url = normalize_url(data.get("url"))
    title = clean_text(data.get("title"))
    doc_id = extract_doc_id(source_url, item.get("ctjParams", {}).get("sulaResourceID") if isinstance(item.get("ctjParams"), dict) else "")
    if not source_url or not title or not doc_id:
        return None

    description = clean_text(data.get("content"))[:300]
    covers = data.get("covers")
    thumbnail_url = normalize_cover(covers[0]) if isinstance(covers, list) and covers else ""
    file_type = file_type_label(data.get("fileType"))

    raw_metadata = {
        "doc_id": doc_id,
        "query": query,
        "rank": rank,
        "search_method": "baiduwenku-search-page",
        "file_type": file_type or data.get("fileType"),
        "page_num": data.get("pageNum"),
        "sell_type": data.get("sellType"),
        "quality_score": data.get("qualityScore"),
        "download_count": data.get("downloadCount"),
        "source_id": item.get("sourceID"),
        "baiduwenku_scene": item.get("sceneID"),
    }

    candidate: dict[str, Any] = {
        "resource_id": f"baiduwenku:{doc_id}",
        "platform": "baiduwenku",
        "title": title,
        "source_url": source_url,
        "type": "文档",
        "platform_signals": {"rank": rank},
        "raw_metadata": {key: value for key, value in raw_metadata.items() if value not in (None, "")},
    }
    if description:
        candidate["description"] = description
    if thumbnail_url:
        candidate["thumbnail_url"] = thumbnail_url
    if data.get("viewCount") is not None:
        candidate["platform_signals"]["views"] = data.get("viewCount")
    return candidate


def normalize_cover(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    url = html.unescape(raw.strip()).replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("http://", "https://")) else ""


def fallback_link_candidates(page: str, query: str, max_results: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rank, match in enumerate(re.finditer(r"https?:\\?/\\?/wenku\.baidu\.com\\?/view\\?/[^\"'<>\\]+", page), 1):
        url = normalize_url(match.group(0))
        doc_id = extract_doc_id(url)
        if not url or not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        results.append({
            "resource_id": f"baiduwenku:{doc_id}",
            "platform": "baiduwenku",
            "title": f"百度文库文档 {doc_id[:8]}",
            "source_url": url,
            "type": "文档",
            "platform_signals": {"rank": len(results) + 1},
            "raw_metadata": {
                "doc_id": doc_id,
                "query": query,
                "rank": len(results) + 1,
                "search_method": "baiduwenku-link-fallback",
            },
        })
        if len(results) >= max_results:
            break
    return results


def parse_results(page: str, query: str, max_results: int) -> list[dict[str, Any]]:
    if is_blocked_page(page):
        raise SearchBlockedError("Baidu Wenku returned a verification page")

    page_data = parse_page_data(page)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in pc_search_items(page_data):
        candidate = item_to_candidate(item, query, len(candidates) + 1)
        if not candidate:
            continue
        doc_id = candidate["resource_id"]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        candidates.append(candidate)
        if len(candidates) >= max_results:
            break

    if candidates:
        return candidates
    return fallback_link_candidates(page, query, max_results)


def search(query: str, max_results: int, timeout: float) -> dict[str, Any]:
    url = SEARCH_URL.format(query=urllib.parse.quote(query))
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        page = request_text(url, timeout)
        results = parse_results(page, query, max_results)
    except SearchBlockedError as exc:
        errors.append({"error_code": "SEARCH_BLOCKED", "message": str(exc), "retryable": True})
    except TimeoutError as exc:
        errors.append({"error_code": "NETWORK_TIMEOUT", "message": str(exc), "retryable": True})
    except urllib.error.HTTPError as exc:
        retryable = exc.code in {403, 408, 429, 500, 502, 503, 504}
        code = "SEARCH_BLOCKED" if exc.code in {403, 429} else "NETWORK_ERROR"
        errors.append({"error_code": code, "message": f"HTTP {exc.code}", "retryable": retryable})
    except Exception as exc:
        errors.append({"error_code": "SEARCH_EXECUTION_FAILED", "message": str(exc), "retryable": True})

    if not results and not errors:
        errors.append({
            "error_code": "SEARCH_NO_RESULTS",
            "message": "Baidu Wenku returned no parseable search results",
            "retryable": True,
        })

    document: dict[str, Any] = {
        "query": query,
        "search_method": "baiduwenku-search-page",
        "results": results,
        "errors": errors,
        "searched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if errors and not results:
        document["error"] = errors[0]
    return document


def write_output(document: dict[str, Any], output: str | None) -> None:
    text = json.dumps(document, ensure_ascii=False, indent=2)
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Baidu Wenku public document results.")
    sub = parser.add_subparsers(dest="cmd")
    command = sub.add_parser("search", help="search Baidu Wenku")
    command.add_argument("query")
    command.add_argument("--max", type=int, default=10)
    command.add_argument("--timeout", type=float, default=20)
    command.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    if args.cmd != "search":
        parser.print_help()
        return 2

    document = search(
        query=args.query,
        max_results=max(1, min(args.max, 50)),
        timeout=max(1.0, args.timeout),
    )
    write_output(document, args.output)
    return 0 if document["results"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
