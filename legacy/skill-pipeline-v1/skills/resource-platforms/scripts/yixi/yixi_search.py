#!/usr/bin/env python3
"""Search public Yixi talks and related video programs."""

from __future__ import annotations

import argparse
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


BASE_URL = "https://www.yixi.tv"
SEARCH_URL = BASE_URL + "/v3/api/h5/search/new/v2/"
AUTHCODE = "$yf&cpup8d%@s2h%"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
PROGRAM_TYPES = {
    0: ("一席演讲", "speech"),
    2: ("一席枝桠", "zhiya"),
    4: ("一席记录", "record"),
    10: ("一席花絮", "huaxu"),
    12: ("一席枝桠", "zhiya"),
}


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def parse_count(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = clean_text(value).replace(",", "")
    match = re.search(r"([\d.]+)\s*(万|亿)?", text)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2) == "万":
        number *= 10_000
    elif match.group(2) == "亿":
        number *= 100_000_000
    return int(number)


def request_json(query: str, timeout: float) -> dict[str, Any]:
    params = {
        "keyword": query,
        "search_type": "1",
        "action": "1",
        "_": str(int(time.time() * 1000)),
    }
    request = urllib.request.Request(
        SEARCH_URL + "?" + urllib.parse.urlencode(params),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": BASE_URL + "/",
            "authcode": AUTHCODE,
        },
    )
    with urlopen_with_fallback(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def detail_url(item: dict[str, Any], video_type: int) -> str:
    item_id = str(item.get("id") or "")
    if video_type == 0:
        return BASE_URL + "/speech/detail?" + urllib.parse.urlencode({"id": item_id})
    if video_type == 4:
        return BASE_URL + "/record/detail?" + urllib.parse.urlencode({"id": item_id})
    if video_type == 10:
        return BASE_URL + "/speech/detail?" + urllib.parse.urlencode(
            {"id": item_id, "videotype": "10"}
        )
    series_id = str(item.get("zhiya_id") or item_id)
    episode_id = str(item.get("video_id") or item_id)
    return BASE_URL + "/zhiya/detail?" + urllib.parse.urlencode(
        {"id": series_id, "episodeId": episode_id}
    )


def normalize_item(item: Any, rank: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    try:
        video_type = int(item.get("video_type"))
    except (TypeError, ValueError):
        return None
    program = PROGRAM_TYPES.get(video_type)
    title = clean_text(item.get("title"))
    if program is None or not title or item.get("id") is None:
        return None
    episode_id = str(item.get("video_id") or item.get("id"))
    speaker = item.get("speaker") if isinstance(item.get("speaker"), dict) else {}
    result: dict[str, Any] = {
        "resource_id": f"yixi:{video_type}:{episode_id}",
        "platform": "yixi",
        "title": title,
        "source_url": detail_url(item, video_type),
        "type": program[0],
        "download_feasibility": "低",
        "platform_signals": {"rank": rank},
        "raw_metadata": {
            "video_id": episode_id,
            "category_id": str(video_type),
            "source_id": str(item.get("zhiya_id") or item.get("id")),
            "search_method": "yixi-public-api",
        },
    }
    for key, value in (
        ("description", clean_text(item.get("intro"))),
        ("author", clean_text(speaker.get("name"))),
        ("thumbnail_url", clean_text(item.get("video_cover"))),
    ):
        if value:
            result[key] = value
    views = parse_count(item.get("play_count"))
    if views is not None:
        result["platform_signals"]["views"] = views
    return result


def search(query: str, max_results: int, timeout: float) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        raw = request_json(query, timeout)
        if raw.get("error_code") not in (0, "0", 200, "200"):
            raise ValueError(str(raw.get("error_msg") or "Yixi search returned an invalid response"))
        items = raw.get("data", {}).get("items", []) if isinstance(raw.get("data"), dict) else []
        seen: set[str] = set()
        for item in items:
            candidate = normalize_item(item, len(results) + 1)
            if candidate is None or candidate["resource_id"] in seen:
                continue
            seen.add(candidate["resource_id"])
            results.append(candidate)
            if len(results) >= max_results:
                break
    except TimeoutError as exc:
        errors.append({"error_code": "NETWORK_TIMEOUT", "message": str(exc), "retryable": True})
    except urllib.error.HTTPError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": f"HTTP {exc.code}", "retryable": exc.code >= 500})
    except urllib.error.URLError as exc:
        errors.append({"error_code": "NETWORK_ERROR", "message": str(exc.reason), "retryable": True})
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append({"error_code": "PARSE_FORMAT_NOT_SUPPORTED", "message": str(exc), "retryable": False})
    except Exception as exc:
        errors.append({"error_code": "SEARCH_EXECUTION_FAILED", "message": str(exc), "retryable": True})

    document: dict[str, Any] = {
        "query": query,
        "search_method": "yixi-public-api",
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
    parser = argparse.ArgumentParser(description="Search public Yixi videos.")
    sub = parser.add_subparsers(dest="cmd")
    command = sub.add_parser("search", help="search Yixi")
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
