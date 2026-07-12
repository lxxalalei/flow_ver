#!/usr/bin/env python3
"""网易公开课搜索脚本 — 基于 HTML 解析实现关键词搜索，输出标准 candidate JSON。

搜索策略：
  网易公开课搜索结果页为服务端渲染 HTML，直接 requests 抓取并解析。
  无需登录/Cookie/签名/浏览器，纯 HTTP。

搜索入口：
  https://open.163.com/newview/search/{关键词}

输出由 adapter 归一化，接口见 resource-platforms/references/search-interface.md：
  resource_id / title / source_url / platform 为必填字段。

用法:
  python open163_search.py search "小学数学" --max 20 -o candidates.json
  python open163_search.py search "科普纪录片" --max 15
  python open163_search.py search "TED" --max 10

依赖:
  - 无需第三方库（标准库 urllib + html.parser）
  - 无需浏览器
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

for path in (Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent.parent.parent):
    sys.path.insert(0, str(path))

from shared.logger import getLogger
from shared.http_client import urlopen_with_fallback

log = getLogger("open163")

# ========== 配置 ==========

# 搜索结果页 URL 模板
SEARCH_URL_TEMPLATE = "https://open.163.com/newview/search/{keyword}"

# 课程详情页 URL 前缀
COURSE_URL_PREFIX = "https://open.163.com/newview/movie/free?pid="

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 播放量数字解析正则（如 "101万次播放" → 1010000）
PLAY_COUNT_PATTERN = re.compile(r"([\d.]+)\s*(万|亿)?\s*次?播放")

# 课时数正则（如 "111课时" → 111）
LESSON_COUNT_PATTERN = re.compile(r"(\d+)\s*课时")

# 儿童内容主题推断关键词
CHILD_SUBJECT_KEYWORDS = {
    "数学": ["数学", "算术", "几何", "代数", "奥数", "思维训练"],
    "语文": ["语文", "拼音", "识字", "汉字", "阅读理解", "作文"],
    "英语": ["英语", "英文", "单词", "口语", "自然拼读", "启蒙"],
    "科学": ["科学", "物理", "化学", "生物", "实验", "科普", "百科"],
    "历史": ["历史", "中国史", "世界史", "历史人物"],
    "艺术": ["美术", "音乐", "绘画", "钢琴", "舞蹈", "书法"],
    "国学": ["国学", "古诗", "诗词", "论语", "三字经", "弟子规", "弟子规"],
    "通识": ["TED", "公开课", "名校", "哈佛", "耶鲁", "纪录片", "哲学"],
}
# ==========================


class Open163SearchParser(HTMLParser):
    """从网易公开课搜索结果页 HTML 中提取课程信息。

    网易公开课搜索结果页结构（服务端渲染）：
    - 每个课程结果是一个 <a> 标签，href 指向 /newview/movie/free?pid=XXX
    - <a> 内含 <img>（封面图）
    - <a> 后紧跟课程标题文本和描述
    - 课时数和播放量在后续文本中
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, Any]] = []
        self._current_item: dict[str, Any] | None = None
        self._in_course_link = False
        self._in_title = False
        self._title_buffer = ""
        self._desc_buffer = ""
        self._capture_text = False
        self._seen_pids: set[str] = set()
        self._total_count: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        href = attr_map.get("href") or ""
        cls = attr_map.get("class") or ""
        src = attr_map.get("src") or ""
        data_pid = attr_map.get("data-pid") or ""

        # 提取搜索总数
        # 格式: 共找到 656 条
        # 在纯文本中处理，这里不直接提取

        # 课程链接：<a href="/newview/movie/free?pid=XXX">
        if tag == "a" and "/newview/movie/free" in href:
            pid = _extract_pid(href)
            if pid and pid not in self._seen_pids:
                self._current_item = {
                    "pid": pid,
                    "url": _normalize_url(href),
                    "cover_url": "",
                    "title": "",
                    "description": "",
                    "lessons": None,
                    "play_count": None,
                    "is_paid": False,
                }
                self._seen_pids.add(pid)
                self._in_course_link = True
                self._in_title = True
                self._title_buffer = ""

        # 封面图
        if tag == "img" and self._in_course_link:
            if src:
                if self._current_item is not None:
                    self._current_item["cover_url"] = src
            alt = attr_map.get("alt") or ""
            if alt and self._current_item and not self._current_item.get("title"):
                self._title_buffer = alt

        # 标题可能是 <h3> 或直接在 <a> 的 title 属性中
        if tag in ("h3", "h4", "p") and self._in_course_link:
            cls = attr_map.get("class") or ""
            if "title" in cls or "name" in cls:
                self._in_title = True
                self._title_buffer = ""

        # 付费标记
        if tag == "span" or tag == "div":
            cls = attr_map.get("class") or ""
            if "pay" in cls.lower() or "vip" in cls.lower():
                if self._current_item is not None:
                    self._current_item["is_paid"] = True

    def handle_data(self, data: str) -> None:
        if self._in_course_link and self._current_item is not None:
            text = data.strip()
            if not text:
                return

            # 提取课时数
            lesson_match = LESSON_COUNT_PATTERN.search(text)
            if lesson_match:
                self._current_item["lessons"] = int(lesson_match.group(1))

            # 提取播放量
            play_match = PLAY_COUNT_PATTERN.search(text)
            if play_match:
                self._current_item["play_count"] = _parse_play_count(text)

            # 提取标题/描述文本（高亮标记用 _ 包围，如 _小学_ _数学_）
            if self._in_title:
                self._title_buffer += text

            # 累积描述
            if "视频合集" in text or "课时" in text or "播放" in text:
                self._desc_buffer += " " + text

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_course_link:
            self._in_title = False
            # 标题清理
            if self._current_item is not None and self._title_buffer:
                title = self._clean_title(self._title_buffer)
                self._current_item["title"] = title

        # 课程块结束（遇到 </li> 或 </div> 时提交）
        if tag in ("li", "div") and self._in_course_link and self._current_item:
            # 检查是否还有未处理的标题
            if not self._current_item.get("title") and self._title_buffer:
                self._current_item["title"] = self._clean_title(self._title_buffer)

            # 如果标题为空，尝试从 alt 中获取
            if not self._current_item.get("title"):
                # 标记为需要后续处理
                pass

            if self._current_item.get("title") or self._current_item.get("pid"):
                self.results.append(self._current_item)
            self._current_item = None
            self._in_course_link = False
            self._title_buffer = ""
            self._desc_buffer = ""

    def _clean_title(self, raw: str) -> str:
        """清理标题文本，移除高亮标记和多余空白。"""
        # 网易公开课用 _ 斜体标记高亮词
        cleaned = raw.replace("_", "")
        # 合并空白
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned


def _extract_pid(url: str) -> str:
    """从 URL 中提取 pid 参数。"""
    match = re.search(r"pid=([A-Za-z0-9]+)", url)
    return match.group(1) if match else ""


def _normalize_url(url: str) -> str:
    """将相对 URL 规范化为完整 https URL。"""
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://open.163.com" + url
    return url


def _parse_play_count(text: str) -> int:
    """解析播放量文本，如 '101万次播放' → 1010000。"""
    match = PLAY_COUNT_PATTERN.search(text)
    if not match:
        return 0
    num = float(match.group(1))
    unit = match.group(2)
    if unit == "万":
        num *= 10000
    elif unit == "亿":
        num *= 100000000
    return int(num)


def _infer_subject(title: str, description: str) -> str:
    """根据标题和描述推断学科主题。"""
    combined = f"{title} {description}".lower()

    for subject, keywords in CHILD_SUBJECT_KEYWORDS.items():
        if any(kw.lower() in combined for kw in keywords):
            return subject

    return "通识"


def _estimate_quality(
    play_count: int | None,
    lessons: int | None,
    is_paid: bool,
) -> tuple[int, str]:
    """估算平台质量分（0-100）和等级（S/A/B/C）。

    网易公开课无评分系统，主要依据播放量和课时数。
    """
    q_score = 55  # 基础分

    # 播放量加分
    if play_count:
        if play_count > 1_000_000:  # 百万播放
            q_score += 20
        elif play_count > 100_000:
            q_score += 15
        elif play_count > 10_000:
            q_score += 10
        elif play_count > 1000:
            q_score += 5

    # 课时数加分（内容完整性）
    if lessons:
        if lessons >= 50:
            q_score += 10
        elif lessons >= 20:
            q_score += 7
        elif lessons >= 10:
            q_score += 5
        elif lessons >= 3:
            q_score += 3

    # 免费加分
    if not is_paid:
        q_score += 5

    q_score = max(0, min(100, q_score))

    if q_score >= 85:
        level = "S"
    elif q_score >= 70:
        level = "A"
    elif q_score >= 55:
        level = "B"
    else:
        level = "C"

    return q_score, level


def _estimate_feasibility(is_paid: bool) -> str:
    """估算下载可行性。网易公开课视频为 m3u8 流，可下载。"""
    if is_paid:
        return "低"
    return "高"


def search_via_html(
    keyword: str,
    max_results: int = 20,
    cookie: str | None = None,
) -> list[dict[str, Any]]:
    """通过抓取网易公开课搜索结果页 HTML 并用正则解析。

    网易公开课搜索 URL: https://open.163.com/newview/search/{keyword}
    结果为服务端渲染，每个课程块结构：
      <a href="/newview/movie/free?pid=XXX">
        <img src="封面URL" alt="标题">
      </a>
      标题文本（含高亮 _xxx_）
      N课时
      N万次播放

    用正则按 pid 分块提取，能同时捕获封面/标题/课时/播放量。
    """
    encoded_keyword = urllib.parse.quote(keyword)
    url = SEARCH_URL_TEMPLATE.format(keyword=encoded_keyword)

    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://open.163.com/",
    }
    cookie = cookie or os.environ.get("OPEN163_COOKIE")
    if cookie:
        headers["Cookie"] = cookie

    log.info("搜索: kw='%s' url=%s", keyword, url)

    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_with_fallback(req, timeout=20) as resp:
            if resp.status != 200:
                log.warning("搜索页返回 HTTP %d", resp.status)
                return []
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("搜索页请求失败: %s", exc)
        return []

    # 先用正则提取搜索总数
    total_count = None
    total_match = re.search(r"共找到\s*\**\s*(\d+)\s*\**\s*条", html)
    if total_match:
        total_count = int(total_match.group(1))
        log.info("搜索总数: %d", total_count)

    # 用 pid 分块正则提取每个课程的完整信息块
    # 每个 pid 块从 <a href="...pid=XXX"> 开始，到下一个 pid 或页面尾部
    raw_results = _extract_courses_by_blocks(html)
    log.info("正则分块提取到 %d 条原始结果", len(raw_results))

    # 转换为标准 candidate
    candidates: list[dict[str, Any]] = []
    seen_pids: set[str] = set()

    for raw in raw_results:
        pid = raw.get("pid", "")
        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        title = raw.get("title", "").strip()
        if not title:
            title = f"网易公开课课程 {pid}"

        description = raw.get("description", "").strip()
        play_count = raw.get("play_count")
        lessons = raw.get("lessons")
        is_paid = raw.get("is_paid", False)
        cover_url = raw.get("cover_url", "")
        source_url = raw.get("url") or f"{COURSE_URL_PREFIX}{pid}"

        subject = _infer_subject(title, description)
        # 平台原生质量信号；最终评分由 resource-selector 统一完成。
        quality_score, quality_level = _estimate_quality(play_count, lessons, is_paid)
        download_feasibility = _estimate_feasibility(is_paid)

        candidate = {
            "resource_id": pid,
            "title": title,
            "source_url": source_url,
            "source_platform": "open163",
            "source": "open163-video",
            "source_name": "网易公开课",
            "snippet": description[:300] if description else "",
            "format": "mp4",
            "resource_type": "视频",
            "subject": subject,
            "provider": "",
            "downloadable": not is_paid,
            "requires_auth": False,
            "metadata_confidence": 0.8,
            # 扩展字段
            "is_paid": is_paid,
            "play_count": play_count,
            "lessons_count": lessons,
            "cover_url": cover_url,
            "total_results": total_count,
            # platform-search-contract 字段
            "platform_signals": {
                "views": play_count,
                "lessons": lessons,
                "native_score": quality_score,
                "native_level": quality_level,
            },
            "download_feasibility": download_feasibility,
            "raw": {"pid": pid},
        }
        candidates.append(candidate)

        if len(candidates) >= max_results:
            break

    log.info("搜索完成，返回 %d 条候选", len(candidates))
    return candidates


def _extract_courses_by_blocks(html: str) -> list[dict[str, Any]]:
    """按 pid 分块提取课程信息。

    策略：找到所有 pid 出现的位置，以每个 pid 链接为锚点，
    截取该链接到下一个 pid 链接之间的 HTML 片段，
    在片段中提取标题/封面/课时/播放量。
    """
    results: list[dict[str, Any]] = []
    seen_pids: set[str] = set()

    # 找到所有 pid 链接位置
    pid_pattern = re.compile(r'href="[^"]*pid=([A-Za-z0-9]+)"', re.IGNORECASE)
    pid_matches = list(pid_pattern.finditer(html))

    if not pid_matches:
        log.warning("未找到任何课程 pid 链接")
        return results

    for i, match in enumerate(pid_matches):
        pid = match.group(1)
        if pid in seen_pids:
            continue

        # 块范围：当前链接到下一个链接
        block_start = max(0, match.start() - 100)
        if i + 1 < len(pid_matches):
            block_end = pid_matches[i + 1].start()
        else:
            block_end = min(len(html), match.start() + 800)

        block = html[block_start:block_end]

        # 提取封面图 + alt 标题
        cover_url = ""
        title = ""
        img_match = re.search(
            r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"', block, re.IGNORECASE
        )
        if img_match:
            cover_url = img_match.group(1)
            title = img_match.group(2)
        else:
            img_match2 = re.search(
                r'<img[^>]*alt="([^"]*)"[^>]*src="([^"]+)"', block, re.IGNORECASE
            )
            if img_match2:
                title = img_match2.group(1)
                cover_url = img_match2.group(2)

        # 如果 img alt 没有标题，尝试从 a 标签的 title 属性提取
        if not title:
            title_match = re.search(r'title="([^"]+)"', block[:300], re.IGNORECASE)
            if title_match:
                title = title_match.group(1)

        # 清理标题中的高亮标记
        title = _clean_highlight(title)

        # 如果标题依然为空，尝试从块文本提取（去掉 HTML 标签后的前几行）
        if not title:
            text_block = re.sub(r"<[^>]+>", "\n", block)
            text_lines = [l.strip() for l in text_block.split("\n") if l.strip() and len(l.strip()) > 3]
            for line in text_lines[:5]:
                line = _clean_highlight(line)
                if line and "open.163.com" not in line and "课时" not in line and "播放" not in line:
                    title = line
                    break

        # 提取课时数
        lessons = None
        lesson_match = LESSON_COUNT_PATTERN.search(block)
        if lesson_match:
            lessons = int(lesson_match.group(1))

        # 提取播放量
        play_count = None
        play_match = PLAY_COUNT_PATTERN.search(block)
        if play_match:
            play_count = _parse_play_count(block)

        # 判断付费
        is_paid = bool(re.search(r"付\s*费|VIP|会员专享", block, re.IGNORECASE))

        # 构建描述
        text_block = re.sub(r"<[^>]+>", " ", block)
        text_block = re.sub(r"\s+", " ", text_block).strip()
        description = _clean_highlight(text_block)[:300]

        source_url = f"{COURSE_URL_PREFIX}{pid}"

        results.append({
            "pid": pid,
            "url": source_url,
            "title": title,
            "cover_url": cover_url,
            "description": description,
            "lessons": lessons,
            "play_count": play_count,
            "is_paid": is_paid,
        })
        seen_pids.add(pid)

    return results


def _clean_highlight(text: str) -> str:
    """清理网易公开课搜索结果中的高亮标记。

    网易公开课用 <em> 或下划线 _xxx_ 标记搜索词高亮。
    """
    if not text:
        return ""
    # 清理 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 清理下划线高亮标记
    text = text.replace("_", "")
    # 合并空白
    text = re.sub(r"\s+", " ", text).strip()
    # 清理 HTML 实体
    text = text.replace("&ensp;", " ").replace("&amp;", "&")
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    return text


def _regex_fallback(html: str) -> list[dict[str, Any]]:
    """正则兜底方案：当 HTMLParser 提取不足时使用。

    网易公开课搜索结果的课程链接格式：
    <a href="https://open.163.com/newview/movie/free?pid=XXX" title="课程标题">
    或
    <a href="/newview/movie/free?pid=XXX">
      <img src="封面URL" alt="标题">
    """
    results: list[dict[str, Any]] = []
    seen_pids: set[str] = set()

    # 匹配课程链接 + 标题/封面
    # 模式1: <a ... href="...pid=XXX" ... title="标题">
    pattern1 = re.compile(
        r'<a[^>]*href="[^"]*pid=([A-Za-z0-9]+)"[^>]*?(?:title="([^"]*)")?[^>]*>',
        re.IGNORECASE,
    )
    # 匹配 img alt 作为标题来源
    img_pattern = re.compile(
        r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"', re.IGNORECASE
    )

    for match in pattern1.finditer(html):
        pid = match.group(1)
        if pid in seen_pids:
            continue

        # 查找该链接附近的 img 标签
        start = max(0, match.start() - 200)
        end = min(len(html), match.end() + 500)
        context = html[start:end]

        title = match.group(2) or ""
        cover_url = ""

        # 从上下文中找封面图
        img_match = img_pattern.search(context)
        if img_match:
            cover_url = img_match.group(1)
            if not title:
                title = img_match.group(2)

        # 从上下文中找课时数和播放量
        lessons = None
        play_count = None

        lesson_match = LESSON_COUNT_PATTERN.search(context)
        if lesson_match:
            lessons = int(lesson_match.group(1))

        play_match = PLAY_COUNT_PATTERN.search(context)
        if play_match:
            play_count = _parse_play_count(context)

        # 判断付费
        is_paid = "付费" in context or "VIP" in context.upper()

        if title:
            title = title.replace("_", "").strip()

        results.append({
            "pid": pid,
            "url": f"{COURSE_URL_PREFIX}{pid}",
            "title": title,
            "cover_url": cover_url,
            "description": "",
            "lessons": lessons,
            "play_count": play_count,
            "is_paid": is_paid,
        })
        seen_pids.add(pid)

    return results


def search(
    keyword: str,
    max_results: int = 20,
    cookie: str | None = None,
) -> list[dict[str, Any]]:
    """主搜索入口。

    网易公开课搜索为单次 HTML 请求，无需分页（单页返回所有结果）。
    """
    log.info("网易公开课搜索: kw='%s' max=%d", keyword, max_results)

    candidates = search_via_html(keyword, max_results=max_results, cookie=cookie)

    if not candidates:
        log.warning("搜索无结果")

    return candidates


def output_candidates(
    results: list[dict[str, Any]],
    keyword: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """格式化为标准 candidate JSON 输出。"""
    data: dict[str, Any] = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "open163-video",
        "query": keyword,
        "searched_at": datetime.now().isoformat(),
        "total": len(results),
        "candidates": results,
    }
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(output + "\n", encoding="utf-8")
        log.info("候选列表已保存: %s (%d 条)", output_file, len(results))
    else:
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
    return data


# ─── CLI ─────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="网易公开课搜索脚本 — 搜索课程，输出标准 candidate JSON"
    )
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="搜索网易公开课")
    s.add_argument("keyword", help="搜索关键词")
    s.add_argument("--cookie", default=None, help="网易公开课 Cookie（可选）")
    s.add_argument("--max", type=int, default=20, help="最大返回数（默认 20）")
    s.add_argument("-o", "--output", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    if args.cmd == "search":
        results = search(
            args.keyword,
            max_results=args.max,
            cookie=args.cookie,
        )
        output_candidates(results, args.keyword, args.output)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
