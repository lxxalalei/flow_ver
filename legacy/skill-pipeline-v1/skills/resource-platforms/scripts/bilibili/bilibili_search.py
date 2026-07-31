#!/usr/bin/env python3
"""Search Bilibili videos through the public WBI web API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.http_client import urlopen_with_fallback

from wbi_sign import wbi_sign


NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
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
    direct = os.environ.get("BILIBILI_COOKIE", "").strip()
    if direct:
        return direct
    cookie_file = os.environ.get("BILIBILI_COOKIE_FILE", "").strip()
    if not cookie_file:
        return ""
    path = Path(cookie_file).expanduser()
    if not path.is_file():
        raise SearchError("AUTH_REQUIRED", "BILIBILI_COOKIE_FILE 不存在", False)
    return path.read_text(encoding="utf-8-sig").strip()


def request_json(url: str, *, referer: str, cookie: str, timeout: int) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    try:
        with urlopen_with_fallback(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 412:
            raise SearchError("SEARCH_BLOCKED", "B站搜索触发 HTTP 412 风控", True) from exc
        if exc.code in (401, 403):
            raise SearchError("AUTH_REQUIRED", f"B站搜索返回 HTTP {exc.code}", False) from exc
        raise SearchError("SEARCH_EXECUTION_FAILED", f"B站搜索返回 HTTP {exc.code}", exc.code >= 500) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise SearchError("NETWORK_TIMEOUT", f"B站搜索请求失败: {exc}", True) from exc
    if "json" not in content_type.lower():
        raise SearchError("SEARCH_BLOCKED", "B站搜索返回非 JSON 响应", True)
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", "B站搜索响应不是有效 JSON", False) from exc
    if not isinstance(value, dict):
        raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", "B站搜索响应根节点不是 object", False)
    return value


def wbi_keys(cookie: str, timeout: int) -> tuple[str, str]:
    nav = request_json(NAV_URL, referer="https://www.bilibili.com/", cookie=cookie, timeout=timeout)
    data = nav.get("data") or {}
    wbi = data.get("wbi_img") or {}
    img_url = str(wbi.get("img_url") or "")
    sub_url = str(wbi.get("sub_url") or "")
    if not img_url or not sub_url:
        raise SearchError("SEARCH_EXECUTION_FAILED", "B站未返回 WBI 密钥", True)
    img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]
    return img_key, sub_key


def count_value(value: Any) -> int | str | None:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text or text == "--":
        return None
    try:
        return int(text)
    except ValueError:
        return text


def normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    bvid = str(item.get("bvid") or "").strip()
    title = re.sub(r"<[^>]+>", "", str(item.get("title") or "")).strip()
    if not bvid or not title:
        return None
    resource: dict[str, Any] = {
        "resource_id": bvid,
        "source_platform": "bilibili",
        "title": title,
        "source_url": f"https://www.bilibili.com/video/{bvid}",
        "resource_type": "视频",
    }
    optional = {
        "description": re.sub(r"<[^>]+>", "", str(item.get("description") or "")).strip(),
        "provider": item.get("author"),
        "duration": item.get("duration"),
        "cover_url": (
            f"https:{item['pic']}" if str(item.get("pic") or "").startswith("//") else item.get("pic")
        ),
    }
    resource.update({key: value for key, value in optional.items() if value not in (None, "")})
    pubdate = item.get("pubdate")
    if isinstance(pubdate, (int, float)) and pubdate > 0:
        resource["publish_time"] = datetime.fromtimestamp(pubdate).astimezone().isoformat()
    signals = {
        "views": count_value(item.get("play")),
        "comments": count_value(item.get("video_review")),
        "favorites": count_value(item.get("favorites")),
    }
    signals = {key: value for key, value in signals.items() if value is not None}
    if signals:
        resource["platform_signals"] = signals
    return resource


def search(query: str, max_results: int, timeout: int = 15) -> list[dict[str, Any]]:
    cookie = runtime_cookie()
    img_key, sub_key = wbi_keys(cookie, timeout)
    results: list[dict[str, Any]] = []
    page = 1
    while len(results) < max_results:
        page_size = min(50, max_results - len(results))
        params = wbi_sign(
            {
                "keyword": query,
                "page": page,
                "page_size": page_size,
                "search_type": "video",
                "order": "totalrank",
            },
            img_key,
            sub_key,
        )
        url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
        referer = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(query)}"
        response = request_json(url, referer=referer, cookie=cookie, timeout=timeout)
        if response.get("code") != 0:
            code = response.get("code")
            message = str(response.get("message") or "B站搜索失败")
            if code in (-101, -111):
                raise SearchError("AUTH_REQUIRED", message, False)
            if code in (-412, -352):
                raise SearchError("SEARCH_BLOCKED", message, True)
            raise SearchError("SEARCH_EXECUTION_FAILED", f"B站 API {code}: {message}", False)
        items = ((response.get("data") or {}).get("result") or [])
        if not items:
            break
        for item in items:
            normalized = normalize_item(item) if isinstance(item, dict) else None
            if normalized:
                results.append(normalized)
                if len(results) >= max_results:
                    break
        if len(items) < page_size:
            break
        page += 1
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="搜索 B站视频")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("search")
    command.add_argument("query")
    command.add_argument("--max", dest="max_results", type=int, default=20)
    command.add_argument("--timeout", type=int, default=15)
    command.add_argument("-o", "--output")
    args = parser.parse_args()
    try:
        results = search(args.query, max(1, min(args.max_results, 100)), max(1, args.timeout))
        document = {"results": results, "error": None}
        exit_code = 0
    except SearchError as exc:
        document = {
            "results": [],
            "error": {"error_code": exc.code, "message": str(exc), "retryable": exc.retryable},
        }
        exit_code = 1
    output = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
