#!/usr/bin/env python3
"""Search the public web through Qianfan and public search pages, then URL-deduplicate results."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .http_client import urlopen_with_fallback


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
ALLOWED_ENGINES = {"qianfan", "duckduckgo", "bing", "baidu"}
QIANFAN_WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
QIANFAN_QUERY_UNITS_LIMIT = 72


class SearchEngineError(RuntimeError):
    """An engine failure with a stable Stage 3 error code."""

    def __init__(self, error_code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class SearchBlockedError(SearchEngineError):
    """The engine returned a verification or anti-bot page instead of results."""

    def __init__(self, message: str) -> None:
        super().__init__("SEARCH_BLOCKED", message, True)


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _truncate_qianfan_query(value: str) -> str:
    """Respect Qianfan's documented 72-unit limit (a Han character counts as 2)."""

    units = 0
    output: list[str] = []
    for char in value.strip():
        char_units = 2 if "\u4e00" <= char <= "\u9fff" else 1
        if units + char_units > QIANFAN_QUERY_UNITS_LIMIT:
            break
        output.append(char)
        units += char_units
    return "".join(output).strip()


def _qianfan_query_and_sites(query: str) -> tuple[str, list[str]]:
    """Translate generic `site:` syntax into Qianfan's native domain filter."""

    sites: list[str] = []
    for raw_scope in re.findall(r"(?:^|\s)site:([^\s]+)", query, flags=re.I):
        candidate = raw_scope.strip().strip("\"'“”‘’.,;；")
        parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
        if parsed.hostname:
            sites.append(parsed.hostname.lower())
    plain_query = re.sub(r"(?:^|\s)site:[^\s]+", " ", query, flags=re.I)
    return _truncate_qianfan_query(plain_query) or _truncate_qianfan_query(query), list(dict.fromkeys(sites))


def _canonical_url(value: str, *, allow_baidu: bool = False) -> str:
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
    if parsed.netloc.endswith(("bing.com", "microsoft.com", "duckduckgo.com")):
        return ""
    if parsed.netloc.endswith("baidu.com") and not allow_baidu:
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
    with urlopen_with_fallback(request, timeout=timeout) as response:
        return response.read(), response.headers.get_content_charset() or "utf-8"


def _fetch(url: str, timeout: float, cookie: str = "") -> str:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, headers=headers)
    body, charset = _open_url(request, timeout)
    return body.decode(charset, errors="replace")


def _qianfan_error_message(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return _clean_text(body.decode("utf-8", errors="replace"))[:300] or "千帆搜索请求失败"
    if isinstance(payload, dict):
        return _clean_text(payload.get("message") or payload.get("error_message"))[:300] or "千帆搜索请求失败"
    return "千帆搜索请求失败"


def _qianfan_error(code: Any, message: str) -> SearchEngineError:
    lowered = message.lower()
    if str(code) in {"401", "403", "216003"} or any(
        marker in lowered for marker in ("authentication", "authorization", "apikey", "api key", "token")
    ):
        return SearchEngineError("AUTH_REQUIRED", "百度千帆 API Key 缺失、无效或已失效", False)
    if str(code) == "429":
        return SearchEngineError("SEARCH_RATE_LIMITED", "百度千帆搜索请求过于频繁", True)
    if str(code).startswith("5"):
        return SearchEngineError("NETWORK_REMOTE_ERROR", f"百度千帆搜索服务暂时不可用: {message}", True)
    return SearchEngineError("SEARCH_EXECUTION_FAILED", f"百度千帆搜索失败: {message}", False)


def search_qianfan(query: str, limit: int, timeout: float, api_key: str) -> list[dict[str, Any]]:
    if not api_key:
        raise SearchEngineError("AUTH_REQUIRED", "缺少 QIANFAN_API_KEY", False)

    compact_query, sites = _qianfan_query_and_sites(query)
    if not compact_query:
        raise SearchEngineError("SEARCH_EXECUTION_FAILED", "千帆搜索词为空", False)
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": compact_query}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": min(max(limit, 1), 50)}],
    }
    if sites:
        payload["search_filter"] = {"match": {"site": sites}}
    request = Request(
        QIANFAN_WEB_SEARCH_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-Appbuilder-Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        body, charset = _open_url(request, timeout)
    except HTTPError as exc:
        raise _qianfan_error(exc.code, _qianfan_error_message(exc.read())) from exc
    except (OSError, TimeoutError, URLError) as exc:
        raise SearchEngineError("NETWORK_REQUEST_FAILED", f"百度千帆请求失败: {type(exc).__name__}", True) from exc
    try:
        response = json.loads(body.decode(charset, errors="replace"))
    except json.JSONDecodeError as exc:
        raise SearchEngineError("PARSE_FORMAT_NOT_SUPPORTED", "百度千帆返回的不是 JSON", False) from exc
    if not isinstance(response, dict):
        raise SearchEngineError("PARSE_FORMAT_NOT_SUPPORTED", "百度千帆返回结构不是 object", False)
    code = response.get("code")
    if code not in (None, "", 0, "0"):
        raise _qianfan_error(code, _clean_text(response.get("message")) or "未知错误")

    results: list[dict[str, Any]] = []
    references = response.get("references")
    if not isinstance(references, list):
        return results
    for reference in references:
        if not isinstance(reference, dict) or reference.get("type") not in (None, "web"):
            continue
        title = _clean_text(reference.get("title"))
        url = _canonical_url(str(reference.get("url") or ""), allow_baidu=True)
        snippet = _clean_text(reference.get("snippet") or reference.get("content"))
        if not title or not url:
            continue
        result = _make_result(title, url, snippet, "qianfan", len(results) + 1, query)
        published_at = _clean_text(reference.get("date"))
        if published_at:
            result["publish_time"] = published_at
        results.append(result)
        if len(results) >= limit:
            break
    return results


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
    errors: list[dict[str, Any]] = []
    per_engine_limit = max(limit, 1)
    qianfan_api_key = os.environ.get("QIANFAN_API_KEY", "").strip()
    skipped_engines = [engine for engine in engines if engine == "qianfan" and not qianfan_api_key]
    active_engines = [engine for engine in engines if engine not in skipped_engines]
    if not active_engines:
        return {
            "platform": "generic",
            "query": query,
            "search_method": "",
            "total_found": 0,
            "returned_count": 0,
            "results": [],
            "errors": [{
                "engine": "qianfan",
                "error_code": "AUTH_REQUIRED",
                "message": "缺少 QIANFAN_API_KEY",
                "retryable": False,
            }],
            "skipped_engines": skipped_engines,
        }
    endpoints = {
        "duckduckgo": (
            f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}",
            parse_duckduckgo_lite_results,
        ),
        "baidu": (f"https://www.baidu.com/s?wd={quote_plus(query)}&rn={per_engine_limit}", parse_baidu_results),
    }

    def run_engine(engine: str) -> tuple[str, list[dict[str, Any]]]:
        if engine == "qianfan":
            return engine, search_qianfan(query, per_engine_limit, timeout, qianfan_api_key)
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
    with ThreadPoolExecutor(max_workers=len(active_engines)) as executor:
        futures = {executor.submit(run_engine, engine): engine for engine in active_engines}
        for future in as_completed(futures):
            engine = futures[future]
            try:
                _, engine_results = future.result()
                completed[engine] = engine_results
            except SearchEngineError as exc:
                errors.append({
                    "engine": engine,
                    "error_code": exc.error_code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                })
            except (OSError, TimeoutError, URLError) as exc:
                errors.append({
                    "engine": engine,
                    "error_code": "NETWORK_REQUEST_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                    "retryable": True,
                })
            except Exception as exc:  # Engine failures are isolated.
                errors.append({
                    "engine": engine,
                    "error_code": "SEARCH_EXECUTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                    "retryable": False,
                })

    # Merge in the requested engine order so concurrency does not make output unstable.
    for engine in active_engines:
        engine_results = completed.get(engine, [])
        for item in engine_results:
            canonical = _canonical_url(item["source_url"], allow_baidu=engine == "qianfan")
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            item["source_url"] = canonical
            if len(merged) < limit:
                merged.append(item)
    return {
        "platform": "generic",
        "query": query,
        "search_method": "+".join(active_engines),
        "total_found": len(merged),
        "returned_count": len(merged),
        "results": merged,
        "errors": errors,
        "skipped_engines": skipped_engines,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="使用千帆、DuckDuckGo、Bing 或百度搜索公开网页")
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
        parser.error(f"--engines 只支持 qianfan,duckduckgo,bing,baidu，收到: {sorted(unknown) or engines}")
    result = search(args.query, engines, max(1, min(args.max_results, 100)), max(1.0, args.timeout))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
