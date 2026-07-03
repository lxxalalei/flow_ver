#!/usr/bin/env python3
"""知乎内容下载器 — 获取知乎问答/文章内容，导出为 Markdown。

支持两种内容类型：
  - 问答页面 (zhihu.com/question/{qid})：提取问题标题 + 高赞回答正文
  - 专栏文章 (zhihu.com/p/{id})：提取文章正文

认证策略：
  - 可选传入 Cookie（z_c0），有 Cookie 可获取更多内容
  - 无 Cookie 也可获取部分公开内容
  - 支持 httpx 和 urllib 两种 HTTP 后端

用法:
  python zhihu_dl.py download "https://www.zhihu.com/question/123456789" -o ./downloads/
  python zhihu_dl.py download "https://zhuanlan.zhihu.com/p/12345678" -o ./downloads/
  python zhihu_dl.py download "https://www.zhihu.com/question/123/answer/456" --cookie "z_c0=xxxx" -o ./

依赖:
  - httpx（可选，有则用，无则降级 urllib）
  - shared/utils.py, shared/logger.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.utils import safe_filename
from shared.logger import getLogger

log = getLogger("zhihu")

# ========== 配置 ==========
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

API_ANSWER = "https://www.zhihu.com/api/v4/answers/{answer_id}"
API_QUESTION_ANSWERS = "https://www.zhihu.com/api/v4/questions/{question_id}/answers"
API_ARTICLE = "https://www.zhihu.com/api/v4/articles/{article_id}"
# ==========================


def _get_headers(cookie: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.zhihu.com/",
    }
    cookie = cookie or os.environ.get("ZHIHU_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _get_api_headers(cookie: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.zhihu.com/",
    }
    cookie = cookie or os.environ.get("ZHIHU_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
        m = re.search(r"z_c0=([^;]+)", cookie)
        if m:
            headers["Authorization"] = f"Bearer {m.group(1)}"
    return headers


# ─── HTTP 后端 ─────────────────────────────────────────────

def _fetch_html(url: str, cookie: str | None = None, timeout: int = 20) -> str:
    """获取页面 HTML。优先用 httpx，降级 urllib。"""
    headers = _get_headers(cookie)
    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")
            return resp.text
    except ImportError:
        pass

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_json(url: str, cookie: str | None = None, timeout: int = 15) -> dict[str, Any]:
    """获取 API JSON 响应。"""
    headers = _get_api_headers(cookie)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ─── URL 解析 ──────────────────────────────────────────────

def parse_url(url: str) -> dict[str, Any]:
    """解析知乎 URL，返回类型和 ID。

    返回 {"type": "question"|"answer"|"article", "question_id"?: str, "answer_id"?: str, "article_id"?: str}
    """
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    path = parsed.path

    # 问答 answer: /question/{qid}/answer/{aid}
    m = re.search(r"/question/(\d+)/answer/(\d+)", path)
    if m:
        return {"type": "answer", "question_id": m.group(1), "answer_id": m.group(2)}

    # 问题: /question/{qid}
    m = re.search(r"/question/(\d+)", path)
    if m:
        return {"type": "question", "question_id": m.group(1)}

    # 专栏文章: /p/{id} 或 zhuanlan.zhihu.com/p/{id}
    m = re.search(r"/p/(\d+)", path)
    if m:
        return {"type": "article", "article_id": m.group(1)}

    # API 端点直调
    if "/api/v4/answers/" in url:
        m = re.search(r"/answers/(\d+)", url)
        if m:
            return {"type": "answer", "answer_id": m.group(1)}
    if "/api/v4/articles/" in url:
        m = re.search(r"/articles/(\d+)", url)
        if m:
            return {"type": "article", "article_id": m.group(1)}

    raise ValueError(f"无法识别的知乎 URL: {url}")


# ─── HTML → Markdown ───────────────────────────────────────

class _ZhihuMarkdownExtractor(HTMLParser):
    """从知乎页面 HTML 中提取问题标题和回答正文，转为 Markdown。

    知乎页面使用 SSR + 水合，关键数据在 <script id="js-initialData"> 中，
    以及 meta 标签和 .RichContent 等正文容器中。
    """

    SKIP_TAGS = {"script", "style", "nav", "svg", "form", "button"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._title = ""
        self._in_title = False
        self._in_rich = False
        self._list_stack: list[str] = []
        self._pre_depth = 0
        self._link_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        cls = attr_map.get("class") or ""

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self._parts.append("\n\n")
        elif tag == "br":
            self._parts.append("\n")
        elif tag in {"strong", "b"}:
            self._parts.append("**")
        elif tag in {"em", "i"}:
            self._parts.append("*")
        elif tag == "a":
            self._link_href = attr_map.get("href") or ""
            self._parts.append("[")
        elif tag == "img":
            alt = attr_map.get("alt") or ""
            src = attr_map.get("src") or attr_map.get("data-original") or ""
            self._parts.append(f"![{alt}]({src})")
        elif tag == "ul":
            self._list_stack.append("ul")
            self._parts.append("\n")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._parts.append("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self._list_stack) - 1)
            self._parts.append(f"\n{indent}- ")
        elif tag == "pre":
            self._pre_depth += 1
            self._parts.append("\n```\n")
        elif tag == "code" and not self._pre_depth:
            self._parts.append("`")
        elif tag == "blockquote":
            self._parts.append("\n> ")
        elif tag == "hr":
            self._parts.append("\n\n---\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3", "p", "li"}:
            self._parts.append("\n")
        elif tag in {"strong", "b"}:
            self._parts.append("**")
        elif tag in {"em", "i"}:
            self._parts.append("*")
        elif tag == "a":
            self._parts.append(f"]({self._link_href})" if self._link_href else "]")
            self._link_href = None
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
            self._parts.append("\n")
        elif tag == "pre":
            if self._pre_depth:
                self._pre_depth -= 1
            self._parts.append("\n```\n")
        elif tag == "code" and not self._pre_depth:
            self._parts.append("`")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title = data.strip()
        if self._pre_depth:
            self._parts.append(data)
        else:
            self._parts.append(re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html: str) -> tuple[str, str]:
    """从 HTML 提取标题和正文 Markdown。返回 (title, body_md)。"""
    parser = _ZhihuMarkdownExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    body = parser.markdown()

    # 提取标题：优先 meta og:title
    title = ""
    m = re.search(r'<meta\s+(?:[^>]*?\s+)?property="og:title"\s+content="([^"]*)"', html, re.IGNORECASE)
    if m:
        title = m.group(1)
    if not title:
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            title = m.group(1).strip().split(" - ")[0]
    title = re.sub(r"\s*-?\s*知乎\s*$", "", title).strip() or parser._title or "知乎内容"

    return title, body


# ─── 通过 API 获取内容（优先） ──────────────────────────────

def fetch_answer_via_api(answer_id: str, cookie: str | None = None) -> dict[str, Any] | None:
    """通过知乎 API 获取单个回答的完整内容。"""
    url = (
        API_ANSWER.format(answer_id=answer_id)
        + "?include=content,excerpt,is_collapsed,comment_count,voteup_count"
    )
    try:
        data = _fetch_json(url, cookie=cookie)
        content_html = data.get("content") or ""
        question = data.get("question") or {}
        author = data.get("author") or {}
        return {
            "title": question.get("title", f"知乎回答 {answer_id}"),
            "author": author.get("name", ""),
            "voteup_count": data.get("voteup_count", 0),
            "comment_count": data.get("comment_count", 0),
            "content_html": content_html,
            "excerpt": data.get("excerpt", ""),
            "source_url": f"https://www.zhihu.com/question/{question.get('id', '')}/answer/{answer_id}",
        }
    except Exception as exc:
        log.warning("API 获取回答失败: %s", exc)
        return None


def fetch_article_via_api(article_id: str, cookie: str | None = None) -> dict[str, Any] | None:
    """通过知乎 API 获取专栏文章内容。"""
    url = API_ARTICLE.format(article_id=article_id) + "?include=content"
    try:
        data = _fetch_json(url, cookie=cookie)
        content_html = data.get("content") or ""
        author = data.get("author") or ""
        title = data.get("title") or f"知乎专栏 {article_id}"
        return {
            "title": title,
            "author": author,
            "voteup_count": data.get("voteup_count", 0),
            "comment_count": data.get("comment_count", 0),
            "content_html": content_html,
            "excerpt": data.get("excerpt", data.get("title_image", "")),
            "source_url": f"https://zhuanlan.zhihu.com/p/{article_id}",
        }
    except Exception as exc:
        log.warning("API 获取文章失败: %s", exc)
        return None


def fetch_question_answers(question_id: str, cookie: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """获取问题下的高赞回答列表。"""
    url = (
        API_QUESTION_ANSWERS.format(question_id=question_id)
        + f"?include=content,excerpt,voteup_count,comment_count&limit={limit}&sort_by=default"
    )
    try:
        data = _fetch_json(url, cookie=cookie)
        answers: list[dict[str, Any]] = []
        for ans in data.get("data") or []:
            answers.append(
                {
                    "title": (ans.get("question") or {}).get("title", ""),
                    "author": (ans.get("author") or {}).get("name", ""),
                    "voteup_count": ans.get("voteup_count", 0),
                    "comment_count": ans.get("comment_count", 0),
                    "content_html": ans.get("content") or "",
                    "excerpt": ans.get("excerpt", ""),
                    "answer_id": str(ans.get("id", "")),
                }
            )
        return answers
    except Exception as exc:
        log.warning("API 获取问题回答列表失败: %s", exc)
        return []


# ─── Markdown 生成 ─────────────────────────────────────────

def answer_to_markdown(answer_data: dict[str, Any]) -> str:
    """将回答数据转为 Markdown。"""
    title = answer_data.get("title") or "知乎回答"
    author = answer_data.get("author", "")
    voteup = answer_data.get("voteup_count", 0)

    # 提取 HTML 正文 → Markdown
    content_html = answer_data.get("content_html") or answer_data.get("excerpt") or ""
    _, body_md = html_to_markdown(f"<div>{content_html}</div>")

    lines = [f"# {title}", ""]
    meta_parts = []
    if author:
        meta_parts.append(f"作者: @{author}")
    if voteup:
        meta_parts.append(f"赞同: {voteup}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))
        lines.append("")
    lines.append("---")
    lines.append("")
    if body_md:
        lines.append(body_md)
    else:
        lines.append("(内容为空，可能需要登录查看)")
    lines.append("")
    lines.append(f"> 来源: {answer_data.get('source_url', '')}")

    return "\n".join(lines)


def question_to_markdown(question_id: str, answers: list[dict[str, Any]], page_title: str) -> str:
    """将问题及多个回答合并为一个 Markdown 文件。"""
    lines = [f"# {page_title}", ""]

    if not answers:
        lines.append("(未获取到回答内容，可能需要登录查看)")
        lines.append("")
        lines.append(f"> 来源: https://www.zhihu.com/question/{question_id}")
        return "\n".join(lines)

    for i, ans in enumerate(answers, 1):
        lines.append(f"## 回答 {i} — @{ans.get('author', '匿名')}")
        meta_parts = []
        if ans.get("voteup_count"):
            meta_parts.append(f"赞同: {ans['voteup_count']}")
        if meta_parts:
            lines.append(f"*{' | '.join(meta_parts)}*")
        lines.append("")

        content_html = ans.get("content_html") or ans.get("excerpt") or ""
        _, body_md = html_to_markdown(f"<div>{content_html}</div>")
        if body_md:
            lines.append(body_md)
        else:
            lines.append("(内容为空)")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(f"> 来源: https://www.zhihu.com/question/{question_id}")
    return "\n".join(lines)


# ─── 下载入口 ──────────────────────────────────────────────

def download(url: str, output_dir: str, cookie: str | None = None) -> dict[str, Any]:
    """下载知乎内容并导出为 Markdown。

    返回标准下载结果（未来接口见 resource-downloader/references/platform-download-contract.md）。
    """
    parsed = parse_url(url)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    content_type = parsed["type"]

    if content_type == "article":
        # 专栏文章
        article_id = parsed["article_id"]
        log.info("下载专栏文章: %s", article_id)

        # 优先 API
        data = fetch_article_via_api(article_id, cookie=cookie)
        if data and data.get("content_html"):
            md = answer_to_markdown(data)
            title = data["title"]
        else:
            # 降级页面抓取
            page_url = f"https://zhuanlan.zhihu.com/p/{article_id}"
            html = _fetch_html(page_url, cookie=cookie)
            title, md = html_to_markdown(html)

    elif content_type == "answer":
        # 单个回答
        answer_id = parsed["answer_id"]
        log.info("下载回答: %s", answer_id)

        data = fetch_answer_via_api(answer_id, cookie=cookie)
        if data and data.get("content_html"):
            md = answer_to_markdown(data)
            title = data["title"]
        else:
            page_url = f"https://www.zhihu.com/question/{parsed.get('question_id', '')}/answer/{answer_id}"
            html = _fetch_html(page_url, cookie=cookie)
            title, md = html_to_markdown(html)

    elif content_type == "question":
        # 问题页（获取问题标题 + 前几个高赞回答）
        question_id = parsed["question_id"]
        log.info("下载问题页: %s", question_id)

        answers = fetch_question_answers(question_id, cookie=cookie, limit=5)
        if answers:
            page_title = answers[0].get("title") or f"知乎问题 {question_id}"
            md = question_to_markdown(question_id, answers, page_title)
            title = page_title
        else:
            # 降级页面抓取
            page_url = f"https://www.zhihu.com/question/{question_id}"
            html = _fetch_html(page_url, cookie=cookie)
            title, md = html_to_markdown(html)
            if not md:
                md = f"(未获取到回答内容，请检查页面链接或提供 Cookie)\n\n> 来源: {page_url}"
    else:
        raise ValueError(f"不支持的内容类型: {content_type}")

    # 保存
    safe_title = safe_filename(title, limit=60)
    dest = output_dir / f"{safe_title}.md"
    dest.write_text(md, encoding="utf-8")

    log.info("已保存: %s (%d chars)", dest.name, len(md))

    return {
        "status": "downloaded",
        "local_path": str(dest),
        "format": "md",
        "title": title,
        "source_url": url,
        "source_platform": "zhihu",
        "note": None,
    }


# ─── CLI ───────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="知乎内容下载器（导出 Markdown）")
    sub = parser.add_subparsers(dest="cmd")

    dl = sub.add_parser("download", help="下载知乎内容并导出 Markdown")
    dl.add_argument("url", help="知乎问答/文章 URL")
    dl.add_argument("-o", "--output", default=".", help="输出目录")
    dl.add_argument("--cookie", default=None, help="知乎 Cookie（含 z_c0，可选）")
    dl.add_argument("--cdp", default=None, help="CDP URL（可选，本平台通常不需要）")

    args = parser.parse_args()

    if args.cmd == "download":
        result = download(args.url, args.output, cookie=args.cookie)
        log.info("%s", result['title'])
        log.info("  %s", result['local_path'])
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
