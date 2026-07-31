#!/usr/bin/env python3
"""Search Douyin videos through the signed web search API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from douyin_dl import RiskControlError, SignatureExpiredError, _engine


class SearchError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def has_runtime_auth() -> bool:
    return bool(os.environ.get("DOUYIN_COOKIE") or os.environ.get("DOUYIN_COOKIE_FILE"))


def normalize_video(video: dict[str, Any]) -> dict[str, Any] | None:
    video_id = str(video.get("video_id") or "").strip()
    title = str(video.get("title") or "").strip()
    url = str(video.get("url") or "").strip()
    if not video_id or not title or not url:
        return None
    result: dict[str, Any] = {
        "resource_id": video_id,
        "source_platform": "douyin",
        "title": title,
        "source_url": url,
        "resource_type": "视频",
    }
    if video.get("author"):
        result["provider"] = video["author"]
    if video.get("duration") is not None:
        result["duration"] = video["duration"]
    stats = video.get("stats") or {}
    signals = {
        "views": stats.get("play"),
        "likes": stats.get("like"),
    }
    signals = {key: value for key, value in signals.items() if value is not None}
    if signals:
        result["platform_signals"] = signals
    return result


async def search_async(query: str, max_results: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    offset = 0
    while len(output) < max_results:
        count = min(15, max_results - len(output))
        try:
            videos, next_offset, has_more = await _engine.fetch_search(query, offset=offset, count=count)
        except ModuleNotFoundError as exc:
            raise SearchError("SYSTEM_DEPENDENCY_MISSING", f"缺少抖音搜索依赖: {exc.name}", False) from exc
        except RiskControlError as exc:
            if exc.code == 2483:
                raise SearchError("AUTH_REQUIRED", "抖音搜索需要有效登录 Cookie", False) from exc
            raise SearchError("SEARCH_BLOCKED", str(exc), True) from exc
        except SignatureExpiredError as exc:
            raise SearchError("SEARCH_BLOCKED", str(exc), True) from exc
        for video in videos:
            normalized = normalize_video(video)
            if normalized:
                output.append(normalized)
        if not has_more or not videos:
            break
        offset = next_offset
    return output[:max_results]


def main() -> int:
    parser = argparse.ArgumentParser(description="搜索抖音视频")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("search")
    command.add_argument("query")
    command.add_argument("--max", dest="max_results", type=int, default=20)
    command.add_argument("-o", "--output")
    args = parser.parse_args()
    if not has_runtime_auth():
        error = {"error_code": "AUTH_REQUIRED", "message": "需要 DOUYIN_COOKIE 或 DOUYIN_COOKIE_FILE", "retryable": False}
        results: list[dict[str, Any]] = []
        exit_code = 1
    else:
        try:
            results = asyncio.run(search_async(args.query, max(1, min(args.max_results, 100))))
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
