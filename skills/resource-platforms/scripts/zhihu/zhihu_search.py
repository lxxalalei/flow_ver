#!/usr/bin/env python3
"""知乎搜索脚本 — 基于知乎搜索 API 实现关键词搜索，输出标准 candidate JSON。

搜索策略（双路径）：
  1. 优先用知乎搜索 API（Cookie 需要同时包含 z_c0 和 d_c0）
  2. 无认证信息时降级为通用 HTTP 页面抓取 + 解析，返回有限结果

输出由 adapter 归一化，接口见 resource-platforms/references/search-interface.md：
  resource_id / title / source_url / platform 为必填字段。

用法:
  python zhihu_search.py search "三年级数学学习方法" --max 20 -o candidates.json
  python zhihu_search.py search "小学英语启蒙" --cookie "z_c0=...; d_c0=..." --max 20
  python zhihu_search.py search "科普 为什么天空是蓝色的" --max 15

依赖:
  - httpx（可选，有则用；无则降级 urllib）
  - 无需浏览器
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.logger import getLogger
from shared.http_client import urlopen_with_fallback

log = getLogger("zhihu")

# ========== 配置 ==========
SEARCH_API = "https://www.zhihu.com/api/v4/search_v3"
SEARCH_PAGE_URL = "https://www.zhihu.com/search"
ZHIHU_BASE = "https://www.zhihu.com"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 搜索类型映射：知乎 search_type → 标准资源类型
TYPE_MAP = {
    "content": "文章",
    "article": "文章",
    "answer": "问答",
    "question": "问答",
    "topic": "话题",
}
# ==========================


class SearchError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def runtime_cookie(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    direct = os.environ.get("ZHIHU_COOKIE", "").strip()
    if direct:
        return direct
    cookie_file = os.environ.get("ZHIHU_COOKIE_FILE", "").strip()
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8-sig").strip()
    return None


def missing_cookie_keys(cookie: str | None) -> list[str]:
    value = cookie or ""
    return [
        key
        for key in ("z_c0", "d_c0")
        if not re.search(rf"(?:^|;\s*){re.escape(key)}=", value)
    ]


def _get_auth_headers(cookie: str | None) -> dict[str, str]:
    """构建带认证的请求头。"""
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.zhihu.com/",
        "x-requested-with": "fetch",
    }
    if cookie:
        headers["Cookie"] = cookie
    elif os.environ.get("ZHIHU_COOKIE"):
        headers["Cookie"] = os.environ["ZHIHU_COOKIE"]
    return headers


def search_via_api(
    keyword: str,
    cookie: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """通过知乎搜索 API 搜索。Cookie 必须同时包含 z_c0 和 d_c0。"""
    cookie = runtime_cookie(cookie)
    missing = missing_cookie_keys(cookie)
    if missing:
        raise SearchError(
            "AUTH_REQUIRED",
            f"知乎 Cookie 缺少必要字段: {', '.join(missing)}",
            False,
        )
    headers = _get_auth_headers(cookie)

    candidates: list[dict[str, Any]] = []
    offset = 0
    limit = min(max_results, 20)
    search_type = "content"

    while len(candidates) < max_results:
        params = {
            "t": "general",
            "q": keyword,
            "correction": "1",
            "offset": str(offset),
            "limit": str(limit),
            "show_all_topics": "0",
            "search_source": "Filter",
            "type": search_type,
        }
        url = f"{SEARCH_API}?{urllib.parse.urlencode(params)}"
        log.info("搜索 API 调用: offset=%d limit=%d", offset, limit)

        try:
            req = urllib.request.Request(url, headers=headers)
            with urlopen_with_fallback(req, timeout=15) as resp:
                if resp.status != 200:
                    log.warning("搜索 API 返回 HTTP %d", resp.status)
                    break
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SearchError("AUTH_REQUIRED", f"知乎搜索认证无效或已过期: HTTP {exc.code}", False) from exc
            if exc.code == 429:
                raise SearchError("SEARCH_BLOCKED", "知乎搜索触发频率限制", True) from exc
            raise SearchError("SEARCH_EXECUTION_FAILED", f"知乎搜索 API 返回 HTTP {exc.code}", exc.code >= 500) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise SearchError("NETWORK_TIMEOUT", f"知乎搜索 API 请求失败: {exc}", True) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise SearchError("PARSE_FORMAT_NOT_SUPPORTED", f"知乎搜索响应解析失败: {exc}", False) from exc
        except Exception as exc:
            log.error("搜索 API 请求失败: %s", exc)
            break

        items = data.get("data") or []
        if not items:
            log.info("搜索 API 无更多结果")
            break

        for item in items:
            obj = item.get("object") or item
            cand = _parse_search_item(obj, item)
            if cand:
                candidates.append(cand)
                if len(candidates) >= max_results:
                    break

        # 分页
        paging = data.get("paging") or {}
        is_end = paging.get("is_end", True)
        if is_end:
            break
        offset += limit

    log.info("搜索 API 返回 %d 条候选", len(candidates))
    return candidates[:max_results]


def _parse_search_item(obj: dict[str, Any], raw_item: dict[str, Any]) -> dict[str, Any] | None:
    """解析单条搜索结果为标准 candidate。"""
    obj_type = str(obj.get("type") or raw_item.get("type") or "").lower()
    resource_id = str(obj.get("id") or "")

    # 构建标题
    title = (
        obj.get("title")
        or raw_item.get("highlight", {}).get("title")
        or obj.get("name")
        or "无标题"
    )
    # 清理 HTML 高亮标签
    title = re.sub(r"<[^>]+>", "", title).strip()

    # 构建 URL
    source_url = ""
    if obj_type == "answer":
        qid = obj.get("question", {}).get("id") or ""
        source_url = f"{ZHIHU_BASE}/question/{qid}/answer/{resource_id}" if qid else ""
    elif obj_type == "article":
        source_url = obj.get("url") or f"{ZHIHU_BASE}/p/{resource_id}"
    elif obj_type == "question":
        source_url = f"{ZHIHU_BASE}/question/{resource_id}"
    else:
        source_url = obj.get("url") or ""

    if not source_url or not title:
        return None

    # 摘要
    snippet_raw = (
        raw_item.get("highlight", {}).get("content")
        or obj.get("excerpt")
        or obj.get("content")
        or ""
    )
    snippet = re.sub(r"<[^>]+>", "", snippet_raw).strip()[:200]

    resource_type = TYPE_MAP.get(obj_type, "文章")
    author = obj.get("author", {}).get("name", "") if isinstance(obj.get("author"), dict) else ""

    return {
        "resource_id": resource_id or source_url,
        "title": title,
        "source_url": source_url,
        "source_platform": "zhihu",
        "source": "zhihu-content",
        "source_name": "知乎",
        "snippet": snippet,
        "format": "md",
        "resource_type": resource_type,
        "provider": author,
        "downloadable": True,
        "requires_auth": False,
        "metadata_confidence": 0.6,
        "raw": {"type": obj_type, **{k: v for k, v in obj.items() if k != "content"}},
    }


# ─── 降级方案：页面抓取 ───────────────────────────────────────

class _ZhihuSearchParser(HTMLParser):
    """从知乎搜索结果页 HTML 中提取链接和标题（降级方案）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_card = False
        self._current_title = ""
        self._current_url = ""
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        href = attr_map.get("href") or ""
        cls = attr_map.get("class") or ""

        # 知乎搜索结果页的卡片标题链接
        if tag == "a" and ("Card" in cls or "SearchResult" in cls or "ContentItem" in cls):
            self._in_card = True
            self._capture_title = True
            self._current_title = ""
            self._current_url = href
        elif tag == "a" and href and ("/question/" in href or "/p/" in href):
            if not self._in_card:
                self._in_card = True
                self._capture_title = True
                self._current_title = ""
                self._current_url = href

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._current_title += data

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "a":
            title = self._current_title.strip()
            url = self._current_url
            if title and url and len(title) > 4:
                if url.startswith("/"):
                    url = ZHIHU_BASE + url
                self.results.append({"title": title, "url": url})
            self._capture_title = False
            self._in_card = False


def search_via_html(
    keyword: str,
    cookie: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """降级方案：抓取知乎搜索结果页面 HTML 并解析。

    无 API 认证时使用。准确率较低，仅作为兜底。
    """
    cookie = runtime_cookie(cookie)
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.zhihu.com/",
    }
    if cookie:
        headers["Cookie"] = cookie

    url = f"{SEARCH_PAGE_URL}?{urllib.parse.urlencode({'q': keyword, 'type': 'content'})}"
    log.info("降级搜索: 抓取搜索页 %s", url)

    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_with_fallback(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("页面抓取失败: %s", exc)
        return []

    parser = _ZhihuSearchParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in parser.results[:max_results]:
        url = item["url"].split("?")[0]  # 去掉查询参数
        if url in seen_urls:
            continue
        seen_urls.add(url)
        resource_id = url.rstrip("/").rsplit("/", 1)[-1]
        candidates.append(
            {
                "resource_id": resource_id,
                "title": item["title"],
                "source_url": url,
                "source_platform": "zhihu",
                "source": "zhihu-content",
                "source_name": "知乎",
                "snippet": "",
                "format": "md",
                "resource_type": "问答" if "/question/" in url else "文章",
                "provider": "",
                "downloadable": True,
                "requires_auth": False,
                "metadata_confidence": 0.3,
                "raw": {"search_method": "html_fallback"},
            }
        )
    log.info("降级搜索返回 %d 条候选", len(candidates))
    return candidates


def search_via_websearch(keyword: str, max_results: int = 20) -> list[dict[str, Any]]:
    """降级方案：通过通用搜索引擎搜索 site:zhihu.com。

    这是最后的兜底路径——当 API 认证缺失、页面抓取被 403 时，
    通过通用搜索引擎间接发现知乎内容。

    策略：先尝试 Bing（反爬宽松），无结果则尝试百度。
    """
    log.info("WebSearch 兜底: '%s'", keyword)

    # 尝试 Bing
    candidates = _search_via_bing(keyword, max_results)
    if candidates:
        return candidates

    # Bing 无结果，尝试百度
    log.info("Bing 无知乎结果，尝试百度...")
    candidates = _search_via_baidu(keyword, max_results)
    return candidates


def _search_via_bing(keyword: str, max_results: int) -> list[dict[str, Any]]:
    """通过 Bing 搜索 site:zhihu.com。"""
    query = f"{keyword} site:zhihu.com"
    url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}&count={min(max_results * 2, 30)}"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_with_fallback(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("Bing 搜索失败: %s", exc)
        return []

    return _extract_candidates_from_search_html(html, max_results)


def _search_via_baidu(keyword: str, max_results: int) -> list[dict[str, Any]]:
    """通过百度搜索 site:zhihu.com。"""
    query = f"{keyword} site:zhihu.com"
    url = f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}&rn={min(max_results * 2, 30)}"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_with_fallback(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("百度搜索失败: %s", exc)
        return []

    return _extract_candidates_from_search_html(html, max_results)


def _extract_candidates_from_search_html(html: str, max_results: int) -> list[dict[str, Any]]:
    """从搜索引擎结果 HTML 中提取知乎链接并构建 candidate 列表。

    支持多种搜索引擎结果页的 HTML 结构（Bing/Baidu 等）。
    """
    # 搜索结果块（Bing 用 b_algo，百度用 result c-container）
    block_pattern = re.compile(
        r'<(?:li|div)[^>]*class="[^"]*(?:b_algo|result c-container)[^"]*"[^>]*>(.*?)</(?:li|div)>',
        re.IGNORECASE | re.DOTALL,
    )
    link_pattern = re.compile(
        r'href="(https?://(?:www\.|zhuanlan\.)?zhihu\.com/(?:question|p)/[^"&?]+)"',
        re.IGNORECASE,
    )

    seen_urls: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for block_match in block_pattern.finditer(html):
        block = block_match.group(1)
        link_match = link_pattern.search(block)
        if not link_match:
            continue

        raw_url = link_match.group(1)
        clean_url = raw_url.split("&")[0].rstrip("/")
        if clean_url in seen_urls:
            continue
        seen_urls.add(clean_url)

        # 从整个 block 中提取标题文本
        block_text = re.sub(r"<[^>]+>", "\n", block)
        block_text = block_text.replace("&ensp;", " ").replace("&#0183;", "·").replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
        lines = [l.strip() for l in block_text.split("\n") if l.strip() and len(l.strip()) > 4]

        # 标题：合并前几行（遇到日期模式停止）
        title_parts: list[str] = []
        for line in lines:
            if "zhihu.com" in line:
                continue
            if re.match(r"^\d{4}年\d{1,2}月", line):
                break
            title_parts.append(line)
            if len("".join(title_parts)) >= 8:
                break
        title = "".join(title_parts)[:120]

        # 提取摘要
        snippet = ""
        for line in lines[len(title_parts):]:
            if len(line) > 15 and "zhihu.com" not in line:
                snippet = line[:200]
                break

        resource_id = clean_url.rstrip("/").rsplit("/", 1)[-1]
        is_answer = "/question/" in clean_url

        candidates.append({
            "resource_id": resource_id,
            "title": title or f"知乎{'问答' if is_answer else '文章'} {resource_id}",
            "source_url": clean_url,
            "source_platform": "zhihu",
            "source": "zhihu-content",
            "source_name": "知乎",
            "snippet": snippet,
            "format": "md",
            "resource_type": "问答" if is_answer else "文章",
            "provider": "",
            "downloadable": True,
            "requires_auth": False,
            "metadata_confidence": 0.4,
            "raw": {"search_method": "search_engine_fallback"},
        })
        if len(candidates) >= max_results:
            break

    log.info("搜索引擎兜底返回 %d 条知乎候选", len(candidates))
    return candidates


def search(
    keyword: str,
    cookie: str | None = None,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """主搜索入口：三级降级 — API → 页面抓取 → 搜索引擎兜底。"""
    log.info("知乎搜索: '%s' (max=%d)", keyword, max_results)

    # 路径 1：API 搜索（需认证）
    candidates = search_via_api(keyword, cookie=cookie, max_results=max_results)
    if candidates:
        return candidates

    # 路径 2：降级页面抓取
    log.info("API 无结果或无认证，降级页面抓取...")
    candidates = search_via_html(keyword, cookie=cookie, max_results=max_results)
    if candidates:
        return candidates

    # 路径 3：搜索引擎兜底（Bing site:zhihu.com）
    log.info("页面抓取失败，降级搜索引擎兜底...")
    candidates = search_via_websearch(keyword, max_results=max_results)
    return candidates


def output_candidates(
    results: list[dict[str, Any]],
    keyword: str,
    output_file: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """格式化为标准 candidate JSON 输出。"""
    data = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "zhihu-content",
        "query": keyword,
        "searched_at": datetime.now().isoformat(),
        "candidates": results,
        "error": error,
    }
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        log.info("候选列表已保存: %s", output_file)
    else:
        print(output)
    return data


# ─── CLI ───────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="知乎搜索脚本")
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="搜索知乎问答/文章")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument("--cookie", default=None, help="知乎 Cookie（必须包含 z_c0 和 d_c0）")
    s.add_argument("--max", type=int, default=20, help="最大返回数（默认 20）")
    s.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    if args.cmd == "search":
        cookie = runtime_cookie(args.cookie)
        try:
            results = search(
                args.keyword,
                cookie=cookie,
                max_results=args.max,
            )
            error = None
            missing = missing_cookie_keys(cookie)
            if not results and missing:
                error = {
                    "error_code": "AUTH_REQUIRED",
                    "message": f"知乎 Cookie 缺少必要字段: {', '.join(missing)}",
                    "retryable": False,
                }
        except SearchError as exc:
            results = []
            error = {"error_code": exc.code, "message": str(exc), "retryable": exc.retryable}
        output_candidates(results, args.keyword, args.output, error)
        return 1 if error else 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
