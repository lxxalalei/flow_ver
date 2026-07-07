#!/usr/bin/env python3
"""Search the public web through Bing and Baidu, then URL-deduplicate results."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
import os
import re
import ssl
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
ALLOWED_ENGINES = {"duckduckgo", "bing", "baidu"}
GENERIC_QUERY_WORDS = {
    "儿童", "孩子", "小孩", "小朋友", "学生", "小学生", "青少年",
    "学习", "资料", "资源", "素材", "内容", "适合", "了解", "推荐",
    "入门", "免费", "大全",
}


class SearchBlockedError(RuntimeError):
    """The engine returned a verification or anti-bot page instead of results."""


def _clean_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _specific_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for part in re.split(r"[\s,，;；]+", query):
        part = part.strip().strip("\"'“”‘’")
        if not part or re.match(r"^(site|filetype):", part, re.I):
            continue
        term = part
        for word in sorted(GENERIC_QUERY_WORDS, key=len, reverse=True):
            term = term.replace(word, "")
        term = re.sub(r"[^\w\u4e00-\u9fff-]+", "", term).strip("-_")
        if len(term) >= 2 and term not in GENERIC_QUERY_WORDS:
            terms.append(term.lower())
    return list(dict.fromkeys(terms))


def _matches_query_terms(item: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return True
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("title", "description", "source_url")
    ).lower()
    return any(term in haystack for term in terms)


def _canonical_url(value: str) -> str:
    value = html.unescape(value).strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        decoded = unquote(target)
        if decoded.startswith(("http://", "https://")):
            value = decoded
            parsed = urlparse(value)
    if parsed.netloc.endswith("bing.com") and parsed.path == "/ck/a":
        target = parse_qs(parsed.query).get("u", [""])[0]
        if target.startswith("a1"):
            # Bing may encode the target after the a1 marker. Leave undecodable
            # links unchanged rather than inventing a destination.
            target = target[2:]
        decoded = unquote(target)
        if decoded.startswith(("http://", "https://")):
            value = decoded
            parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.netloc.endswith(("baidu.com", "bing.com", "microsoft.com", "duckduckgo.com")):
        return ""
    return parsed._replace(fragment="").geturl()


def _make_result(title: str, url: str, snippet: str, engine: str, rank: int, query: str) -> dict[str, Any]:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return {
        "resource_id": f"generic:{key}",
        "platform_resource_id": key,
        "platform": "generic",
        "title": title,
        "source_url": url,
        "type": "网页",
        "description": snippet or None,
        "author": None,
        "duration": None,
        "publish_time": None,
        "is_free": None,
        "language": None,
        "thumbnail_url": None,
        "download_feasibility": "低",
        "platform_signals": {"engine": engine, "rank": rank},
        "raw_metadata": {"query": query},
    }


def parse_bing_results(page: str, query: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    blocks = re.findall(r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>(.*?)</li>', page, re.I | re.S)
    for block in blocks:
        match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not match:
            continue
        url = _canonical_url(match.group(1))
        title = _clean_text(match.group(2))
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.I | re.S)
        snippet = _clean_text(snippet_match.group(1)) if snippet_match else ""
        if url and title:
            results.append(_make_result(title, url, snippet, "bing", len(results) + 1, query))
        if len(results) >= limit:
            break
    return results


def parse_bing_rss(page: str, query: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(page)
    except ET.ParseError:
        return results
    for item in root.findall("./channel/item"):
        title = _clean_text(item.findtext("title") or "")
        url = _canonical_url(item.findtext("link") or "")
        snippet = _clean_text(item.findtext("description") or "")
        if title and url:
            results.append(_make_result(title, url, snippet, "bing", len(results) + 1, query))
        if len(results) >= limit:
            break
    return results


def parse_baidu_results(page: str, query: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    blocks = re.findall(
        r'(<div[^>]+(?:class="[^"]*\bresult(?:-opus)?\b[^"]*"|tpl="se_com_default")[^>]*>.*?</div>\s*</div>)',
        page,
        re.I | re.S,
    )
    for block in blocks:
        heading = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.I | re.S)
        if not heading:
            continue
        anchor = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', heading.group(1), re.I | re.S)
        if not anchor:
            continue
        direct = re.search(r'\b(?:mu|data-landurl)="([^"]+)"', block, re.I)
        url = _canonical_url(direct.group(1) if direct else anchor.group(1))
        title = _clean_text(anchor.group(2))
        snippet_match = re.search(
            r'<(?:div|span)[^>]+class="[^"]*(?:c-abstract|content-right_8Zs40|cos-row)[^"]*"[^>]*>(.*?)</(?:div|span)>',
            block,
            re.I | re.S,
        )
        snippet = _clean_text(snippet_match.group(1)) if snippet_match else ""
        if url and title:
            results.append(_make_result(title, url, snippet, "baidu", len(results) + 1, query))
        if len(results) >= limit:
            break
    return results


def parse_duckduckgo_lite_results(page: str, query: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    matches = list(re.finditer(
        r"<a(?=[^>]*class=['\"]result-link['\"])[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
        page,
        re.I | re.S,
    ))
    for index, match in enumerate(matches):
        url = _canonical_url(match.group(1))
        title = _clean_text(match.group(2))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page)
        block = page[match.end():end]
        snippet_match = re.search(
            r"<td[^>]+class=['\"]result-snippet['\"][^>]*>(.*?)</td>",
            block,
            re.I | re.S,
        )
        snippet = _clean_text(snippet_match.group(1)) if snippet_match else ""
        if url and title:
            results.append(_make_result(title, url, snippet, "duckduckgo", len(results) + 1, query))
        if len(results) >= limit:
            break
    return results


def _open_url(request: Request, timeout: float) -> tuple[bytes, str]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get_content_charset() or "utf-8"
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError):
            # Some managed Windows images ship a broken CA bundle for Python.
            # Retry public search pages without certificate verification so the
            # adapter can still produce candidates; Stage 3 stores only links.
            context = ssl._create_unverified_context()
            with urlopen(request, timeout=timeout, context=context) as response:
                return response.read(), response.headers.get_content_charset() or "utf-8"
        raise


def _fetch(url: str, timeout: float, cookie: str = "") -> str:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, headers=headers)
    body, charset = _open_url(request, timeout)
    return body.decode(charset, errors="replace")


def _raise_if_blocked(page: str, engine: str) -> None:
    lowered = page.lower()
    markers = {
        "baidu": ("百度安全验证", "网络不给力，请稍后重试", "wappass.baidu.com/static/captcha"),
        "bing": ('class="captcha"', "our systems have detected unusual traffic", "verify you are human"),
        "duckduckgo": ("anomaly detected", "captcha", "unfortunately, bots"),
    }
    if any(marker.lower() in lowered for marker in markers[engine]):
        raise SearchBlockedError(f"{engine} 返回安全验证页面")


def search(query: str, engines: list[str], limit: int, timeout: float) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[dict[str, str]] = []
    query_terms = _specific_query_terms(query)
    per_engine_limit = max(limit, 1)
    endpoints = {
        "duckduckgo": (
            f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}",
            parse_duckduckgo_lite_results,
        ),
        "baidu": (f"https://www.baidu.com/s?wd={quote_plus(query)}&rn={per_engine_limit}", parse_baidu_results),
    }
    def run_engine(engine: str) -> tuple[str, list[dict[str, Any]]]:
        if engine == "bing":
            cookie = os.environ.get("BING_COOKIE", "") or "SRCHHPGUSR=SRCHLANG=zh-Hans"
            rss_url = f"https://cn.bing.com/search?format=rss&q={quote_plus(query)}&count={per_engine_limit}"
            rss_page = _fetch(rss_url, timeout, cookie)
            _raise_if_blocked(rss_page, engine)
            rss_results = parse_bing_rss(rss_page, query, per_engine_limit)
            if rss_results:
                return engine, rss_results
            html_url = (
                f"https://cn.bing.com/search?q={quote_plus(query)}"
                f"&count={per_engine_limit}&setlang=zh-hans&cc=CN"
            )
            page = _fetch(html_url, timeout, cookie)
            _raise_if_blocked(page, engine)
            return engine, parse_bing_results(page, query, per_engine_limit)
        url, parser = endpoints[engine]
        cookie = os.environ.get(f"{engine.upper()}_COOKIE", "")
        page = _fetch(url, timeout, cookie)
        _raise_if_blocked(page, engine)
        return engine, parser(page, query, per_engine_limit)

    completed: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=len(engines)) as executor:
        futures = {executor.submit(run_engine, engine): engine for engine in engines}
        for future in as_completed(futures):
            engine = futures[future]
            try:
                _, engine_results = future.result()
                completed[engine] = engine_results
            except Exception as exc:  # Engine failures are isolated.
                errors.append({"engine": engine, "message": f"{type(exc).__name__}: {exc}"})

    # Merge in the requested engine order so concurrency does not make output unstable.
    for engine in engines:
        engine_results = completed.get(engine, [])
        for item in engine_results:
            if not _matches_query_terms(item, query_terms):
                continue
            canonical = _canonical_url(item["source_url"])
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            item["source_url"] = canonical
            if len(merged) < limit:
                merged.append(item)
    return {
        "platform": "generic",
        "query": query,
        "search_method": "+".join(engines),
        "total_found": len(merged),
        "returned_count": len(merged),
        "results": merged,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="使用 DuckDuckGo、Bing 或百度搜索公开网页")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("search")
    command.add_argument("query")
    command.add_argument("--max", type=int, default=20, dest="max_results")
    command.add_argument("--engines", default="duckduckgo,bing")
    command.add_argument("--timeout", type=float, default=10.0)
    command.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    engines = list(dict.fromkeys(part.strip().lower() for part in args.engines.split(",") if part.strip()))
    unknown = set(engines) - ALLOWED_ENGINES
    if unknown or not engines:
        parser.error(f"--engines 只支持 duckduckgo,bing,baidu，收到: {sorted(unknown) or engines}")
    result = search(args.query, engines, max(1, min(args.max_results, 100)), max(1.0, args.timeout))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
