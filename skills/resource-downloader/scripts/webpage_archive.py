#!/usr/bin/env python3
"""Archive a public HTML page using only the Python standard library."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request

from http_client import urlopen_with_fallback


_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_NOISE_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "input",
    "select",
    "textarea",
}
_NOISE_TOKENS = re.compile(
    r"(?:^|[-_\s])(?:nav|navbar|navigation|menu|sidebar|footer|header|"
    r"breadcrumb|advert|advertisement|ads?|banner|social|share|sharing|"
    r"related|recommend|comment|discussion|pagination|pager|copyright|"
    r"cookie|modal|popup|toolbar|login|signup)(?:$|[-_\s])",
    re.IGNORECASE,
)
_CONTENT_TOKENS = re.compile(
    r"(?:^|[-_\s])(?:article|post|entry|story|news|main|page|document|"
    r"content|body|text|detail)(?:$|[-_\s])",
    re.IGNORECASE,
)
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}
_CONTAINER_TAGS = {"article", "body", "div", "main", "section"}
_HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}


class ArchiveSizeLimitError(ValueError):
    """Raised when a response is larger than the configured byte limit."""


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: _Node | None = None
    children: list[_Node | str] = field(default_factory=list)

    def attr(self, name: str) -> str:
        return self.attrs.get(name, "")


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self._stack = [self.root]

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        node = _Node(
            tag.lower(),
            {name.lower(): value or "" for name, value in attrs},
            self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def archive_webpage(
    source_url: str,
    output_dir: str | os.PathLike[str],
    timeout_seconds: float = 15,
    max_bytes: int = 5_000_000,
) -> dict:
    """Fetch a page and save source.html, content.md, and metadata.json."""
    _validate_inputs(source_url, timeout_seconds, max_bytes)
    raw_html, response_metadata = _fetch(source_url, timeout_seconds, max_bytes)
    html_text, encoding = _decode_html(raw_html, response_metadata["charset"])
    parser = _TreeParser()
    parser.feed(html_text)
    parser.close()

    title = _extract_title(parser.root)
    base_url = _extract_base_url(parser.root, response_metadata["final_url"])
    content_root, strategy = _select_content_root(parser.root)
    links: list[dict[str, str]] = []
    markdown_body = _render_markdown(content_root, base_url, links, title)
    markdown = _compose_markdown(title, markdown_body)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    source_path = output_path / "source.html"
    content_path = output_path / "content.md"
    metadata_path = output_path / "metadata.json"

    metadata = {
        "source_url": source_url,
        "final_url": response_metadata["final_url"],
        "title": title,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status_code": response_metadata["status_code"],
        "content_type": response_metadata["content_type"],
        "encoding": encoding,
        "source_bytes": len(raw_html),
        "content_characters": len(markdown),
        "extraction_strategy": strategy,
        "links": links,
        "files": {
            "source_html": str(source_path.resolve()),
            "content_markdown": str(content_path.resolve()),
            "metadata_json": str(metadata_path.resolve()),
        },
    }

    _atomic_write(source_path, raw_html)
    _atomic_write(content_path, markdown.encode("utf-8"))
    _atomic_write(
        metadata_path,
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return metadata


def _validate_inputs(source_url: str, timeout_seconds: float, max_bytes: int) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")


def _fetch(source_url: str, timeout_seconds: float, max_bytes: int) -> tuple[bytes, dict]:
    request = Request(
        source_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; collector-flow-web-archive/1.0)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    with urlopen_with_fallback(request, timeout=timeout_seconds) as response:
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > max_bytes:
                raise ArchiveSizeLimitError(
                    f"response exceeds max_bytes ({max_bytes})"
                )

        chunks = []
        bytes_read = 0
        while True:
            chunk = response.read(min(65_536, max_bytes + 1 - bytes_read))
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                raise ArchiveSizeLimitError(
                    f"response exceeds max_bytes ({max_bytes})"
                )

        content_type_header = response.headers.get("Content-Type", "")
        return b"".join(chunks), {
            "final_url": response.geturl(),
            "status_code": getattr(response, "status", None),
            "content_type": content_type_header.split(";", 1)[0].strip().lower(),
            "charset": _header_charset(response.headers, content_type_header),
        }


def _header_charset(headers: object, content_type_header: str) -> str:
    getter = getattr(headers, "get_content_charset", None)
    if callable(getter):
        charset = getter()
        if charset:
            return charset
    match = re.search(r"charset\s*=\s*['\"]?([^;'\"\s]+)", content_type_header, re.I)
    return match.group(1) if match else ""


def _decode_html(raw_html: bytes, declared_charset: str) -> tuple[str, str]:
    prefix = raw_html[:4096]
    meta_match = re.search(
        br"<meta\b[^>]*charset\s*=\s*['\"]?\s*([a-zA-Z0-9._-]+)",
        prefix,
        re.IGNORECASE,
    )
    candidates = [declared_charset]
    if raw_html.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    if meta_match:
        candidates.append(meta_match.group(1).decode("ascii", errors="ignore"))
    candidates.extend(["utf-8", "gb18030", "latin-1"])

    seen = set()
    for encoding in candidates:
        normalized = encoding.strip().lower() if encoding else ""
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            return raw_html.decode(normalized), normalized
        except (LookupError, UnicodeDecodeError):
            continue
    return raw_html.decode("utf-8", errors="replace"), "utf-8-replace"


def _walk(node: _Node) -> Iterable[_Node]:
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child)


def _is_noise(node: _Node) -> bool:
    if node.tag in _NOISE_TAGS:
        return True
    if node.attr("hidden") or node.attr("aria-hidden").lower() == "true":
        return True
    style = re.sub(r"\s+", "", node.attr("style").lower())
    if "display:none" in style or "visibility:hidden" in style:
        return True
    marker = " ".join((node.attr("id"), node.attr("class"), node.attr("role")))
    return bool(_NOISE_TOKENS.search(marker))


def _plain_text(node: _Node, skip_noise: bool = True) -> str:
    pieces: list[str] = []

    def collect(current: _Node | str) -> None:
        if isinstance(current, str):
            pieces.append(current)
            return
        if current.tag == "img" or (skip_noise and _is_noise(current)):
            return
        for child in current.children:
            collect(child)

    collect(node)
    return _normalize_space("".join(pieces))


def _extract_title(root: _Node) -> str:
    for node in _walk(root):
        if node.tag != "meta":
            continue
        key = (node.attr("property") or node.attr("name")).lower()
        if key in {"og:title", "twitter:title"} and node.attr("content").strip():
            return _normalize_space(node.attr("content"))
    for tag in ("h1", "title", "h2"):
        for node in _walk(root):
            if node.tag == tag and not _has_noise_ancestor(node):
                title = _plain_text(node, skip_noise=False)
                if title:
                    return title
    return ""


def _has_noise_ancestor(node: _Node) -> bool:
    current = node.parent
    while current is not None:
        if _is_noise(current):
            return True
        current = current.parent
    return False


def _extract_base_url(root: _Node, final_url: str) -> str:
    for node in _walk(root):
        if node.tag == "base" and node.attr("href"):
            return urljoin(final_url, node.attr("href"))
    return final_url


def _select_content_root(root: _Node) -> tuple[_Node, str]:
    candidates = []
    body = None
    for node in _walk(root):
        if node.tag == "body":
            body = node
        if node.tag not in _CONTAINER_TAGS or _is_noise(node):
            continue
        text = _plain_text(node)
        if not text:
            continue
        link_text = "".join(
            _plain_text(descendant)
            for descendant in _walk(node)
            if descendant is not node and descendant.tag == "a" and not _is_noise(descendant)
        )
        link_ratio = len(link_text) / max(len(text), 1)
        marker = " ".join((node.attr("id"), node.attr("class")))
        semantic_bonus = 0
        strategy = "density"
        if node.tag == "article":
            semantic_bonus = 8_000
            strategy = "article"
        elif node.tag == "main" or node.attr("role").lower() == "main":
            semantic_bonus = 7_000
            strategy = "main"
        elif _CONTENT_TOKENS.search(marker):
            semantic_bonus = 4_000
            strategy = "content-marker"
        elif node.tag == "body":
            semantic_bonus = -1_000
            strategy = "body-fallback"
        block_count = sum(
            1
            for descendant in _walk(node)
            if descendant.tag in {"p", "li", *list(_HEADING_TAGS)}
            and not _is_noise(descendant)
        )
        score = semantic_bonus + min(len(text), 20_000) + block_count * 60
        score -= int(link_ratio * 8_000)
        candidates.append((score, len(text), node, strategy))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, node, strategy = candidates[0]
        return node, strategy
    return body or root, "document-fallback"


def _render_markdown(
    root: _Node,
    base_url: str,
    links: list[dict[str, str]],
    page_title: str,
) -> str:
    blocks: list[str] = []

    def render_container(node: _Node) -> None:
        inline_buffer: list[str] = []

        def flush_inline() -> None:
            text = _normalize_space("".join(inline_buffer))
            inline_buffer.clear()
            if text:
                blocks.append(text)

        for child in node.children:
            if isinstance(child, str):
                inline_buffer.append(child)
                continue
            if _is_noise(child) or child.tag == "img":
                continue
            if child.tag in _HEADING_TAGS:
                flush_inline()
                text = _render_inline(child, base_url, links)
                if text and _normalize_key(text) != _normalize_key(page_title):
                    blocks.append(f"{'#' * _HEADING_TAGS[child.tag]} {text}")
            elif child.tag == "p":
                flush_inline()
                text = _render_inline(child, base_url, links)
                if text:
                    blocks.append(text)
            elif child.tag in {"ul", "ol"}:
                flush_inline()
                rendered = _render_list(child, base_url, links)
                if rendered:
                    blocks.append(rendered)
            elif child.tag == "blockquote":
                flush_inline()
                text = _render_inline(child, base_url, links)
                if text:
                    blocks.append("\n".join(f"> {line}" for line in text.splitlines()))
            elif child.tag == "pre":
                flush_inline()
                text = _plain_text(child, skip_noise=False).strip()
                if text:
                    blocks.append(f"```\n{text}\n```")
            elif child.tag == "hr":
                flush_inline()
                blocks.append("---")
            elif _has_block_children(child):
                flush_inline()
                render_container(child)
            else:
                inline_buffer.append(_render_inline(child, base_url, links))
        flush_inline()

    if root.tag in _HEADING_TAGS or root.tag in {"p", "ul", "ol", "blockquote", "pre"}:
        wrapper = _Node("div", {}, children=[root])
        render_container(wrapper)
    else:
        render_container(root)
    return "\n\n".join(block.strip() for block in blocks if block.strip())


def _has_block_children(node: _Node) -> bool:
    return any(
        isinstance(child, _Node) and child.tag in _BLOCK_TAGS for child in node.children
    )


def _render_inline(
    node: _Node,
    base_url: str,
    links: list[dict[str, str]],
    skip_lists: bool = False,
) -> str:
    pieces: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            pieces.append(child)
            continue
        if _is_noise(child) or child.tag == "img" or (skip_lists and child.tag in {"ul", "ol"}):
            continue
        if child.tag == "a":
            text = _render_inline(child, base_url, links) or child.attr("href")
            href = child.attr("href").strip()
            if href and not href.lower().startswith(("javascript:", "data:")):
                target = urljoin(base_url, href)
                pieces.append(f"[{text}]({target})")
                link = {"text": _normalize_space(text), "url": target}
                if link not in links:
                    links.append(link)
            else:
                pieces.append(text)
        elif child.tag in {"strong", "b"}:
            text = _render_inline(child, base_url, links)
            pieces.append(f"**{text}**" if text else "")
        elif child.tag in {"em", "i"}:
            text = _render_inline(child, base_url, links)
            pieces.append(f"*{text}*" if text else "")
        elif child.tag == "code":
            text = _plain_text(child, skip_noise=False)
            pieces.append(f"`{text}`" if text else "")
        elif child.tag == "br":
            pieces.append("\n")
        else:
            pieces.append(_render_inline(child, base_url, links, skip_lists=skip_lists))
    return _normalize_space("".join(pieces))


def _render_list(
    node: _Node,
    base_url: str,
    links: list[dict[str, str]],
    depth: int = 0,
) -> str:
    lines: list[str] = []
    items = [
        child
        for child in node.children
        if isinstance(child, _Node) and child.tag == "li" and not _is_noise(child)
    ]
    for index, item in enumerate(items, start=1):
        prefix = f"{index}. " if node.tag == "ol" else "- "
        text = _render_inline(item, base_url, links, skip_lists=True)
        if text:
            lines.append(f"{'  ' * depth}{prefix}{text}")
        for child in item.children:
            if isinstance(child, _Node) and child.tag in {"ul", "ol"}:
                nested = _render_list(child, base_url, links, depth + 1)
                if nested:
                    lines.append(nested)
    return "\n".join(lines)


def _compose_markdown(title: str, body: str) -> str:
    sections = []
    if title:
        sections.append(f"# {title}")
    if body:
        sections.append(body)
    return "\n\n".join(sections).rstrip() + "\n"


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_key(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).casefold()


def _atomic_write(path: Path, data: bytes) -> None:
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary_path.open("wb") as handle:
            handle.write(data)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


__all__ = ["ArchiveSizeLimitError", "archive_webpage"]
