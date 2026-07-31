#!/usr/bin/env python3
"""Search Kepu China public article and video results."""

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


BASE_URL = "https://www.kepuchina.cn"
SEARCH_URL = BASE_URL + "/search/index?search={query}&search_type=0"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


class SearchBlockedError(RuntimeError):
    """The site returned an anti-bot or verification page."""


def request_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": BASE_URL + "/",
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


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def html_attr(tag: str, name: str) -> str:
    match = re.search(rf'\b{name}\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))', tag, re.I)
    return html.unescape(match.group(2) or match.group(3) or match.group(4) or "").strip() if match else ""


def absolute_url(href: str) -> str:
    href = html.unescape(href.strip()).replace("\\/", "/")
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return BASE_URL + href
    return urllib.parse.urljoin(BASE_URL + "/", href)


def is_kepuchina_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    return host == "www.kepuchina.cn"


def is_blocked_page(page: str) -> bool:
    lowered = page.lower()
    if "sl_item" in lowered or "articleinfo" in lowered:
        return False
    return any(marker in lowered for marker in ("captcha", "verify you are human", "安全验证", "验证码"))


def split_result_blocks(page: str) -> list[str]:
    parts = re.split(r'<div\s+class=["\']sl_item\s+clearfix["\'][^>]*>', page, flags=re.I)
    return parts[1:] if len(parts) > 1 else []


def extract_first(pattern: str, text: str, flags: int = re.I | re.S) -> str:
    match = re.search(pattern, text, flags)
    return match.group(1) if match else ""


def parse_query(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(url)
    return {key: values[-1] for key, values in urllib.parse.parse_qs(parsed.query).items() if values}


def normalize_kind(label: str, classify: str) -> str:
    if label:
        if "视频" in label:
            return "科普视频"
        if "专题" in label:
            return "科普专题"
    if classify == "2":
        return "科普视频"
    return "科普文章"


def block_to_candidate(block: str, query: str, rank: int) -> dict[str, Any] | None:
    href = extract_first(r'<h2\s+class=["\']st_name["\'][^>]*>.*?<a\b[^>]*href=["\']([^"\']+)["\']', block)
    if not href:
        href = extract_first(r'<a\b[^>]*href=["\']([^"\']*articleinfo[^"\']+)["\']', block)
    source_url = absolute_url(href) if href else ""
    if not source_url or not is_kepuchina_url(source_url):
        return None

    title = clean_text(extract_first(r'<h2\s+class=["\']st_name["\'][^>]*>.*?<a\b[^>]*>(.*?)</a>', block))
    if not title:
        title = clean_text(extract_first(r'<a\b[^>]*href=["\'][^"\']*articleinfo[^"\']+["\'][^>]*>(.*?)</a>', block))
    if not title:
        return None

    label = clean_text(extract_first(r'<span\s+class=["\']st_type["\'][^>]*>(.*?)</span>', block))
    description = clean_text(extract_first(r'<div\s+class=["\']desc\s+ell["\'][^>]*>(.*?)</div>', block))[:300]
    source = clean_text(extract_first(r'<span\s+class=["\']st_source\s+ell["\'][^>]*>(.*?)</span>', block))
    publish_time = clean_text(extract_first(r'<span\s+class=["\']st_time["\'][^>]*>(.*?)</span>', block))

    image_url = ""
    img_tag = extract_first(r'(<img\b[^>]*>)', block)
    if img_tag:
        image_url = absolute_url(html_attr(img_tag, "src"))

    keywords = [
        clean_text(match.group(1))
        for match in re.finditer(r'<a\s+class=["\']ell["\'][^>]*>(.*?)</a>', block, re.I | re.S)
        if clean_text(match.group(1))
    ]
    params = parse_query(source_url)
    ar_id = params.get("ar_id", "")
    classify = params.get("classify", "")
    business_type = params.get("business_type", "")
    if not ar_id:
        return None

    return {
        "resource_id": f"kepu:kepuchina:{ar_id}",
        "platform": "kepu",
        "title": title,
        "source_url": source_url,
        "type": normalize_kind(label, classify),
        "description": description,
        "author": source,
        "publish_time": publish_time,
        "thumbnail_url": image_url,
        "platform_signals": {"rank": rank, "engine": "kepuchina"},
        "raw_metadata": {
            "site": "kepuchina.cn",
            "ar_id": ar_id,
            "query": query,
            "rank": rank,
            "search_method": "kepuchina-search-page",
            "classify": classify,
            "business_type": business_type,
            "keywords": ", ".join(keywords[:8]),
        },
    }


def parse_results(page: str, query: str, max_results: int) -> list[dict[str, Any]]:
    if is_blocked_page(page):
        raise SearchBlockedError("Kepu China returned a verification page")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in split_result_blocks(page):
        candidate = block_to_candidate(block, query, len(results) + 1)
        if not candidate:
            continue
        rid = candidate["resource_id"]
        if rid in seen:
            continue
        seen.add(rid)
        results.append(candidate)
        if len(results) >= max_results:
            break
    return results


def search(query: str, max_results: int, timeout: float) -> dict[str, Any]:
    url = SEARCH_URL.format(query=urllib.parse.quote(query))
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        page = request_text(url, timeout)
        results = parse_results(page, query, max_results)
    except SearchBlockedError as exc:
        errors.append({"error_code": "SEARCH_BLOCKED", "message": str(exc), "retryable": True})
    except TimeoutError as exc:
        errors.append({"error_code": "NETWORK_TIMEOUT", "message": str(exc), "retryable": True})
    except urllib.error.HTTPError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": f"HTTP {exc.code}", "retryable": exc.code >= 500})
    except Exception as exc:
        errors.append({"error_code": "SEARCH_EXECUTION_FAILED", "message": str(exc), "retryable": True})

    if not results and not errors:
        errors.append({
            "error_code": "SEARCH_NO_RESULTS",
            "message": "Kepu China returned no parseable search results",
            "retryable": True,
        })

    document: dict[str, Any] = {
        "query": query,
        "search_method": "kepuchina-search-page",
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
    parser = argparse.ArgumentParser(description="Search Kepu China public resources.")
    sub = parser.add_subparsers(dest="cmd")
    command = sub.add_parser("search", help="search Kepu China")
    command.add_argument("query")
    command.add_argument("--max", type=int, default=10)
    command.add_argument("--timeout", type=float, default=20)
    command.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    if args.cmd != "search":
        parser.print_help()
        return 2

    document = search(args.query, max(1, min(args.max, 50)), max(1.0, args.timeout))
    write_output(document, args.output)
    return 0 if document["results"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
