#!/usr/bin/env python3
"""CCTV search script.

Searches CCTV's public search JSON endpoint and emits standard candidate JSON.
First version focuses on public video results; it does not download media.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

for path in (Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent.parent.parent):
    sys.path.insert(0, str(path))

from shared.http_client import urlopen_with_fallback
from shared.logger import getLogger


log = getLogger("cctv")

SEARCH_API = "https://search.cctv.com/ifsearch.php"
SEARCH_PAGE = "https://search.cctv.com/search.php"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class SearchError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_duration(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _normalize_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return "https://" + url.removeprefix("http://")
    return url


def _fetch_page(keyword: str, page: int, page_size: int, core: str, channel: str = "") -> dict[str, Any]:
    params = {
        "page": str(page),
        "qtext": keyword,
        "sort": "relevance",
        "pageSize": str(page_size),
        "type": core,
        "datepid": "1",
        "channel": channel,
        "vtime": "-1",
    }
    url = f"{SEARCH_API}?{urllib.parse.urlencode(params)}"
    referer = f"{SEARCH_PAGE}?{urllib.parse.urlencode({'type': core, 'qtext': keyword})}"
    headers = {
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Referer": referer,
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_with_fallback(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise SearchError("SEARCH_BLOCKED", f"CCTV 搜索被拦截: HTTP {exc.code}", True) from exc
        raise SearchError("SEARCH_EXECUTION_FAILED", f"CCTV 搜索 HTTP {exc.code}", exc.code >= 500) from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise SearchError("NETWORK_TIMEOUT", f"CCTV 搜索请求失败: {exc}", True) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", f"CCTV 搜索响应不是 JSON: {exc}", False) from exc
    if not isinstance(data, dict):
        raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", "CCTV 搜索响应根节点不是 object", False)
    return data


def _item_to_candidate(item: dict[str, Any], rank: int, total: int | None) -> dict[str, Any] | None:
    video_id = str(item.get("id") or "").strip()
    title = _clean_text(item.get("all_title") or item.get("title"))
    source_url = _normalize_url(item.get("urllink"))
    if not video_id or not title or not source_url:
        return None

    channel = _clean_text(item.get("channel"))
    thumbnail_url = _normalize_url(item.get("imglink"))
    duration_seconds = item.get("durations")
    duration = _format_duration(duration_seconds)
    publish_time = _clean_text(item.get("uploadtime"))
    description_parts = []
    if channel:
        description_parts.append(f"频道: {channel}")
    if duration:
        description_parts.append(f"时长: {duration}")
    if publish_time:
        description_parts.append(f"发布时间: {publish_time}")

    return {
        "resource_id": video_id,
        "title": title,
        "source_url": source_url,
        "source_platform": "cctv",
        "source": "cctv-video",
        "source_name": "央视网",
        "snippet": "；".join(description_parts),
        "format": "mp4",
        "resource_type": "视频",
        "provider": channel,
        "downloadable": False,
        "requires_auth": False,
        "metadata_confidence": 0.85,
        "duration": duration_seconds,
        "publish_time": publish_time,
        "thumbnail_url": thumbnail_url,
        "total_results": total,
        "platform_signals": {
            "rank": rank,
        },
        "raw": {
            "video_id": video_id,
        },
    }


def search(keyword: str, max_results: int = 20, core: str = "video", channel: str = "") -> list[dict[str, Any]]:
    if core not in {"video", "audio"}:
        raise SearchError("SEARCH_EXECUTION_FAILED", f"CCTV 暂不支持搜索类型: {core}", False)

    log.info("CCTV 搜索: kw='%s' max=%d type=%s", keyword, max_results, core)
    page_size = max(1, min(max_results, 20))
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    page = 1
    total_pages = 1
    total: int | None = None

    while len(candidates) < max_results and page <= total_pages:
        data = _fetch_page(keyword, page=page, page_size=page_size, core=core, channel=channel)
        total = data.get("total") if isinstance(data.get("total"), int) else total
        try:
            total_pages = min(int(data.get("totalpage") or 1), 50)
        except (TypeError, ValueError):
            total_pages = 1
        items = data.get("list") or []
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            rank = len(candidates) + 1
            candidate = _item_to_candidate(item, rank=rank, total=total)
            if candidate is None:
                continue
            source_url = candidate["source_url"]
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            candidates.append(candidate)
            if len(candidates) >= max_results:
                break
        page += 1
        if len(candidates) < max_results and page <= total_pages:
            time.sleep(0.3)

    log.info("CCTV 搜索返回 %d 条候选", len(candidates))
    return candidates[:max_results]


def output_candidates(
    results: list[dict[str, Any]],
    keyword: str,
    output_file: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "cctv-video",
        "query": keyword,
        "searched_at": datetime.now().isoformat(),
        "total": len(results),
        "candidates": results,
        "error": error,
    }
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        log.info("候选列表已保存: %s (%d 条)", output_file, len(results))
    else:
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="CCTV 搜索脚本")
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="搜索央视网公开音视频")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument("--max", type=int, default=20, help="最大返回数（默认 20）")
    s.add_argument("--type", default="video", choices=["video", "audio"], help="搜索类型（默认 video）")
    s.add_argument("--channel", default="", help="频道过滤（可选，如 CCTV-10科教频道）")
    s.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    if args.cmd == "search":
        try:
            results = search(args.keyword, max_results=args.max, core=args.type, channel=args.channel)
            error = None
        except SearchError as exc:
            results = []
            error = {"error_code": exc.code, "message": str(exc), "retryable": exc.retryable}
        output_candidates(results, args.keyword, args.output, error)
        return 1 if error else 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
