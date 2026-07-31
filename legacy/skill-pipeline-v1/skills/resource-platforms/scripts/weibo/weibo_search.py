#!/usr/bin/env python3
"""Search Weibo posts through the authenticated web API."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SEARCH_URL = "https://weibo.com/ajax/searchall"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
)


class SearchError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def runtime_cookie() -> str:
    cookie = os.environ.get("WEIBO_COOKIE", "").strip()
    if not cookie:
        cookie_file = os.environ.get("WEIBO_COOKIE_FILE", "").strip()
        if cookie_file:
            path = Path(cookie_file).expanduser()
            if not path.is_file():
                raise SearchError("AUTH_REQUIRED", "WEIBO_COOKIE_FILE 不存在", False)
            cookie = path.read_text(encoding="utf-8-sig").strip()
    if not cookie or "SUB=" not in cookie:
        raise SearchError("AUTH_REQUIRED", "微博搜索需要包含 SUB 的 WEIBO_COOKIE 或 WEIBO_COOKIE_FILE", False)
    return cookie


def headers(cookie: str) -> dict[str, str]:
    result = {
        "User-Agent": USER_AGENT,
        "Referer": "https://weibo.com/",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
    }
    match = re.search(r"XSRF-TOKEN=([^;]+)", cookie)
    if match:
        result["X-XSRF-TOKEN"] = match.group(1)
    return result


def request_page(query: str, page: int, cookie: str, timeout: int) -> dict[str, Any]:
    params = urllib.parse.urlencode({"q": query, "page": page, "count": 10})
    request = urllib.request.Request(f"{SEARCH_URL}?{params}", headers=headers(cookie))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SearchError("AUTH_REQUIRED", f"微博 Cookie 无效或已过期: HTTP {exc.code}", False) from exc
        if exc.code in (418, 429):
            raise SearchError("SEARCH_BLOCKED", f"微博搜索触发访问限制: HTTP {exc.code}", True) from exc
        raise SearchError("SEARCH_EXECUTION_FAILED", f"微博搜索返回 HTTP {exc.code}", exc.code >= 500) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise SearchError("NETWORK_TIMEOUT", f"微博搜索请求失败: {exc}", True) from exc
    if "json" not in content_type.lower():
        raise SearchError("AUTH_REQUIRED", "微博搜索返回登录页或非 JSON 响应", False)
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", "微博搜索响应不是有效 JSON", False) from exc
    if not isinstance(value, dict):
        raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", "微博搜索响应根节点不是 object", False)
    if value.get("ok") == -100:
        raise SearchError("AUTH_REQUIRED", "微博 Cookie 无效或已过期", False)
    if value.get("ok") != 1:
        raise SearchError("SEARCH_EXECUTION_FAILED", f"微博搜索 API ok={value.get('ok')}", False)
    return value


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_post(post: dict[str, Any]) -> dict[str, Any] | None:
    mid = str(post.get("id") or post.get("mid") or post.get("note_id") or "").strip()
    text = clean_text(post.get("text_raw") or post.get("text") or post.get("note"))
    if not mid or not text:
        return None
    user = post.get("user") if isinstance(post.get("user"), dict) else {}
    uid = str(user.get("id") or "")
    bid = str(post.get("bid") or "")
    source_url = f"https://weibo.com/{uid}/{bid}" if uid and bid else f"https://weibo.com/detail/{mid}"
    page_info = post.get("page_info") if isinstance(post.get("page_info"), dict) else {}
    is_video = page_info.get("type") == "video" or bool(post.get("video"))
    result: dict[str, Any] = {
        "resource_id": mid,
        "source_platform": "weibo",
        "title": text[:80],
        "source_url": source_url,
        "resource_type": "视频" if is_video else "图文",
        "description": text[:300],
    }
    if user.get("screen_name"):
        result["provider"] = user["screen_name"]
    if post.get("created_at"):
        result["publish_time"] = post["created_at"]
    signals = {
        "likes": post.get("attitudes_count"),
        "comments": post.get("comments_count"),
        "shares": post.get("reposts_count"),
    }
    signals = {key: value for key, value in signals.items() if value is not None}
    if signals:
        result["platform_signals"] = signals
    result["raw_metadata"] = {"mid": mid, **({"bid": bid} if bid else {})}
    return result


def search(query: str, max_results: int, timeout: int = 15) -> list[dict[str, Any]]:
    cookie = runtime_cookie()
    output: list[dict[str, Any]] = []
    page = 1
    while len(output) < max_results:
        value = request_page(query, page, cookie, timeout)
        data = value.get("data") or {}
        posts = data.get("notes") or data.get("statuses") or []
        if not posts:
            break
        for post in posts:
            normalized = normalize_post(post) if isinstance(post, dict) else None
            if normalized:
                output.append(normalized)
                if len(output) >= max_results:
                    break
        if len(posts) < 10:
            break
        page += 1
        time.sleep(1)
    return output[:max_results]


def main() -> int:
    parser = argparse.ArgumentParser(description="搜索微博内容")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("search")
    command.add_argument("query")
    command.add_argument("--max", dest="max_results", type=int, default=20)
    command.add_argument("--timeout", type=int, default=15)
    command.add_argument("-o", "--output")
    args = parser.parse_args()
    try:
        results = search(args.query, max(1, min(args.max_results, 100)), max(1, args.timeout))
        error = None
        exit_code = 0
    except SearchError as exc:
        results = []
        error = {"error_code": exc.code, "message": str(exc), "retryable": exc.retryable}
        exit_code = 1
    document = {"results": results, "error": error}
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
