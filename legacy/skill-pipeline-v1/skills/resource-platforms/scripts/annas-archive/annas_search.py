#!/usr/bin/env python3
"""Anna's Archive search script — searches books and articles via public web scraping.

Anna's Archive (https://annas-archive.org) is a comprehensive document repository.
This script scrapes the search results page (no API key needed for search) and
returns normalized candidate JSON.

Two search modes:
  - book:     Search books by title, author, or topic
  - article:  Search articles by DOI or keywords

Output is normalized to the platform-search interface:
  resource_id / title / source_url / platform are required fields.

Usage:
  python annas_search.py search "machine learning python" --max 20 -o candidates.json
  python annas_search.py search "古诗注释赏析" --core book --max 15
  python annas_search.py search "10.1038/nature12345" --core article --max 10

Dependencies:
  - httpx (optional; falls back to urllib)
  - No login required for search
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.logger import getLogger

log = getLogger("annas-archive")

# ========== Configuration ==========

# Default mirror (can be overridden by ANNAS_BASE_URL env var)
# annas-archive.org has SSL issues in some environments; .gl mirror is more reliable
DEFAULT_BASE_URL = "annas-archive.gl"

# Search paths
BOOK_SEARCH_PATH = "/search?q="
ARTICLE_SEARCH_PATH = "/search?index=articles&q="

# User agent
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Request timeout
REQUEST_TIMEOUT = 30

# ====================================


def _get_base_url() -> str:
    """Get the Anna's Archive base URL from env or default."""
    base = os.environ.get("ANNAS_BASE_URL", "").strip()
    if not base:
        base = DEFAULT_BASE_URL
    # Remove protocol prefix if present
    base = base.replace("https://", "").replace("http://", "").rstrip("/")
    return base


def _build_headers() -> dict[str, str]:
    """Build HTTP request headers."""
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    }
    return headers


def _fetch_page(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """Fetch an HTML page and return its content.
    
    Uses a permissive SSL context since some Anna's Archive mirrors
    have certificate issues in certain environments.
    """
    headers = _build_headers()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def _clean_text(value: str) -> str:
    """Clean HTML tags and normalize whitespace."""
    if not value:
        return ""
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_book_results(page_html: str, query: str, max_results: int) -> list[dict[str, Any]]:
    """Parse book search results from Anna's Archive HTML page.
    
    Anna's Archive search results have a structured layout with each result
    containing title, author, format, size, and language info.
    """
    results: list[dict[str, Any]] = []
    
    # Anna's Archive uses <div class="link-box"> or similar structures for results
    # The exact selectors may vary; we try multiple patterns
    
    # Pattern 1: Each result is in a container with data attributes
    result_blocks = re.findall(
        r'<div[^>]*class="[^"]*(?:link-box|result|search-result-item)[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*(?:link-box|result|search-result-item)|$)',
        page_html,
        re.I | re.S,
    )
    
    if not result_blocks:
        # Pattern 2: Look for <a> tags with href containing /md5/
        md5_links = re.findall(
            r'<a[^>]+href="/md5/([a-f0-9]{32})"[^>]*>(.*?)</a>',
            page_html,
            re.I | re.S,
        )
        for md5, content in md5_links:
            title = _clean_text(content)
            if not title:
                continue
            results.append(_make_book_result(md5, title, "", query))
            if len(results) >= max_results:
                return results
    
    if not result_blocks:
        # Pattern 3: Broader search for md5 links anywhere
        md5_pattern = re.findall(
            r'href="/md5/([a-f0-9]{32})"',
            page_html,
            re.I,
        )
        # Find titles near these md5 links
        for md5 in md5_pattern:
            # Try to extract a title from nearby content
            title_pattern = re.search(
                rf'/md5/{re.escape(md5)}"[^>]*>([^<]+)',
                page_html,
                re.I,
            )
            title = ""
            if title_pattern:
                title = _clean_text(title_pattern.group(1))
            if not title:
                title = f"Document {md5[:8]}"
            results.append(_make_book_result(md5, title, "", query))
            if len(results) >= max_results:
                return results
    
    for block in result_blocks:
        if len(results) >= max_results:
            break
        
        # Extract MD5 hash from the block
        md5_match = re.search(r'/md5/([a-f0-9]{32})', block, re.I)
        if not md5_match:
            continue
        md5 = md5_match.group(1)
        
        # Extract title
        title_match = re.search(r'<(?:a|h[1-6])[^>]*>(.*?)</(?:a|h[1-6])>', block, re.I | re.S)
        title = _clean_text(title_match.group(1)) if title_match else f"Document {md5[:8]}"
        
        # Extract additional info
        author = _extract_field(block, ["author", "作者"])
        lang = _extract_field(block, ["language", "语言", "lang"])
        file_format = _extract_field(block, ["format", "格式", "ext"])
        file_size = _extract_field(block, ["size", "大小"])
        
        results.append(_make_book_result(md5, title, author, query, lang, file_format, file_size))
    
    return results


def _extract_field(block: str, field_names: list[str]) -> str:
    """Extract a field value from HTML block by looking for field name labels."""
    for name in field_names:
        pattern = re.search(
            rf'{name}\s*[:：]\s*</?\w*[^>]*>\s*([^<]+)',
            block,
            re.I,
        )
        if pattern:
            return _clean_text(pattern.group(1))
    return ""


def _make_book_result(
    md5: str,
    title: str,
    author: str,
    query: str,
    lang: str = "",
    file_format: str = "",
    file_size: str = "",
) -> dict[str, Any]:
    """Create a normalized book result."""
    base_url = _get_base_url()
    source_url = f"https://{base_url}/md5/{md5}"
    resource_id = f"annas-archive:{md5}"
    
    # Determine resource type
    ext = file_format.lower().strip(".") if file_format else ""
    if ext in ("pdf",):
        resource_type = "PDF文档"
    elif ext in ("epub",):
        resource_type = "EPUB文档"
    elif ext in ("mobi", "azw3"):
        resource_type = "电子书"
    elif ext in ("doc", "docx"):
        resource_type = "Word文档"
    elif ext in ("ppt", "pptx"):
        resource_type = "PPT课件"
    else:
        resource_type = "文档"
    
    # Build description
    desc_parts = []
    if author:
        desc_parts.append(f"作者: {author}")
    if lang:
        desc_parts.append(f"语言: {lang}")
    if file_format:
        desc_parts.append(f"格式: {file_format}")
    if file_size:
        desc_parts.append(f"大小: {file_size}")
    description = " | ".join(desc_parts) if desc_parts else ""
    
    result: dict[str, Any] = {
        "resource_id": resource_id,
        "platform": "annas-archive",
        "title": title,
        "source_url": source_url,
        "type": resource_type,
        "author": author or None,
        "description": description or None,
        "language": lang or None,
        "is_free": True,
        "download_feasibility": "中",
        "platform_signals": {},
        "raw_metadata": {
            "md5": md5,
            "file_format": file_format or None,
            "file_size": file_size or None,
            "query": query,
        },
    }
    
    # Remove None values
    result = {k: v for k, v in result.items() if v is not None}
    return result


def _parse_article_results(page_html: str, query: str, max_results: int) -> list[dict[str, Any]]:
    """Parse article search results from Anna's Archive HTML page."""
    results: list[dict[str, Any]] = []
    
    # Article results typically have DOI-based links
    # Look for article entries with DOI references
    article_blocks = re.findall(
        r'<div[^>]*class="[^"]*(?:link-box|result|search-result-item)[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*(?:link-box|result|search-result-item)|$)',
        page_html,
        re.I | re.S,
    )
    
    if not article_blocks:
        # Try to find DOI-based links
        doi_links = re.findall(
            r'href="/articles/([^"]+)"[^>]*>(.*?)</a>',
            page_html,
            re.I | re.S,
        )
        for doi, content in doi_links:
            title = _clean_text(content)
            if not title:
                title = f"Article {doi[:30]}"
            results.append(_make_article_result(doi, title, query))
            if len(results) >= max_results:
                return results
    
    for block in article_blocks:
        if len(results) >= max_results:
            break
        
        # Extract DOI
        doi_match = re.search(r'/articles/(10\.\d+/[^\s"\'<>]+)', block, re.I)
        if not doi_match:
            # Try md5 for articles too
            doi_match = re.search(r'/md5/([a-f0-9]{32})', block, re.I)
            if doi_match:
                doi = doi_match.group(1)
            else:
                continue
        else:
            doi = doi_match.group(1)
        
        # Extract title
        title_match = re.search(r'<(?:a|h[1-6])[^>]*>(.*?)</(?:a|h[1-6])>', block, re.I | re.S)
        title = _clean_text(title_match.group(1)) if title_match else f"Article {doi[:30]}"
        
        author = _extract_field(block, ["author", "作者"])
        journal = _extract_field(block, ["journal", "期刊"])
        
        results.append(_make_article_result(doi, title, query, author, journal))
    
    return results


def _make_article_result(
    doi: str,
    title: str,
    query: str,
    author: str = "",
    journal: str = "",
) -> dict[str, Any]:
    """Create a normalized article result."""
    base_url = _get_base_url()
    source_url = f"https://{base_url}/articles/{doi}"
    resource_id_raw = hashlib.sha256(doi.encode()).hexdigest()[:16]
    resource_id = f"annas-archive:{resource_id_raw}"
    
    desc_parts = []
    if author:
        desc_parts.append(f"作者: {author}")
    if journal:
        desc_parts.append(f"期刊: {journal}")
    description = " | ".join(desc_parts) if desc_parts else ""
    
    result: dict[str, Any] = {
        "resource_id": resource_id,
        "platform": "annas-archive",
        "title": title,
        "source_url": source_url,
        "type": "学术文章",
        "author": author or None,
        "description": description or None,
        "is_free": True,
        "download_feasibility": "中",
        "platform_signals": {},
        "raw_metadata": {
            "doi": doi,
            "query": query,
        },
    }
    
    result = {k: v for k, v in result.items() if v is not None}
    return result


def _check_blocked(page_html: str) -> bool:
    """Check if the response is a block/captcha page."""
    lowered = page_html.lower()
    blocked_markers = [
        "captcha",
        "cloudflare",
        "access denied",
        "rate limit",
        "too many requests",
        "ddos protection",
        "验证码",
        "访问被拒",
    ]
    return any(marker in lowered for marker in blocked_markers)


def search(
    query: str,
    core: str = "book",
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """Search Anna's Archive for books or articles.
    
    Args:
        query: Search query string
        core: Search type - 'book' or 'article'
        max_results: Maximum number of results
        
    Returns:
        List of normalized candidate dictionaries
    """
    base_url = _get_base_url()
    
    if core == "article":
        search_path = ARTICLE_SEARCH_PATH
    else:
        search_path = BOOK_SEARCH_PATH
    
    encoded_query = urllib.parse.quote(query)
    url = f"https://{base_url}{search_path}{encoded_query}"
    
    log.info("Anna's Archive search: core=%s query='%s' url=%s", core, query, url)
    
    try:
        page_html = _fetch_page(url)
    except Exception as exc:
        log.error("Anna's Archive request failed: %s", exc)
        return []
    
    # Check for blocked access
    if _check_blocked(page_html):
        log.warning("Anna's Archive returned a block/captcha page")
        return []
    
    # Check for empty results
    if "no results" in page_html.lower() or "没有找到" in page_html:
        log.info("Anna's Archive returned no results for query: %s", query)
        return []
    
    # Parse results
    if core == "article":
        results = _parse_article_results(page_html, query, max_results)
    else:
        results = _parse_book_results(page_html, query, max_results)
    
    log.info("Anna's Archive search returned %d results (core=%s)", len(results), core)
    return results[:max_results]


# ─── Output ────────────────────────────────


def output_results(
    results: list[dict[str, Any]],
    query: str,
    core: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Format results as standard candidate JSON output."""
    data: dict[str, Any] = {
        "platform": "annas-archive",
        "query": query,
        "core": core,
        "searched_at": datetime.now().isoformat(),
        "total_found": len(results),
        "returned_count": len(results),
        "results": results,
        "errors": [],
    }
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        log.info("Results saved to: %s (%d items)", output_file, len(results))
    else:
        print(output)
    return data


# ─── CLI ───────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Anna's Archive search — search books and articles"
    )
    sub = parser.add_subparsers(dest="cmd")
    
    s = sub.add_parser("search", help="Search Anna's Archive")
    s.add_argument("query", help="Search query")
    s.add_argument(
        "--core",
        choices=["book", "article"],
        default="book",
        help="Search type: book (default) or article",
    )
    s.add_argument("--max", type=int, default=20, help="Max results (default: 20)")
    s.add_argument("-o", "--output", default=None, help="Output JSON file path")
    
    args = parser.parse_args()
    
    if args.cmd == "search":
        results = search(
            args.query,
            core=args.core,
            max_results=max(1, min(args.max, 100)),
        )
        output_results(results, args.query, args.core, args.output)
        return 0
    
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
