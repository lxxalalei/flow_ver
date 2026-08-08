"""Bounded Block IR extraction for static web materialization.

The extractor intentionally does not preserve the source DOM.  It accepts a
bounded HTML document, removes active/noisy nodes, and produces a small
internal representation from which the materializer can render both Markdown
and HTML.  Keeping the IR independent from lxml is important: no untrusted
HTML node, attribute, URL, or event handler is ever handed to a renderer.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
import re
from typing import Literal

from lxml import etree


BlockKind = Literal[
    "heading",
    "paragraph",
    "list",
    "quote",
    "code",
    "table",
    "image",
    "linebreak",
    "placeholder",
]


DEFAULT_MAX_HTML_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_DOM_NODES = 50_000
DEFAULT_MAX_DOM_DEPTH = 128
DEFAULT_MAX_TEXT_CHARS = 1_000_000
DEFAULT_MAX_BLOCKS = 4_096
DEFAULT_MAX_TABLE_ROWS = 128
DEFAULT_MAX_TABLE_COLUMNS = 32
DEFAULT_MAX_LIST_ITEMS = 512
DEFAULT_MAX_CODE_CHARS = 200_000
DEFAULT_MAX_IMAGE_BLOCKS = 64


class BlockExtractionError(ValueError):
    """Raised when a document cannot be parsed within the safety bounds."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BlockLimits:
    """Hard limits used while converting a source document to Block IR."""

    max_html_bytes: int = DEFAULT_MAX_HTML_BYTES
    max_dom_nodes: int = DEFAULT_MAX_DOM_NODES
    max_depth: int = DEFAULT_MAX_DOM_DEPTH
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    max_blocks: int = DEFAULT_MAX_BLOCKS
    max_table_rows: int = DEFAULT_MAX_TABLE_ROWS
    max_table_columns: int = DEFAULT_MAX_TABLE_COLUMNS
    max_list_items: int = DEFAULT_MAX_LIST_ITEMS
    max_code_chars: int = DEFAULT_MAX_CODE_CHARS
    max_image_blocks: int = DEFAULT_MAX_IMAGE_BLOCKS

    def __post_init__(self) -> None:
        for name in (
            "max_html_bytes",
            "max_dom_nodes",
            "max_depth",
            "max_text_chars",
            "max_blocks",
            "max_table_rows",
            "max_table_columns",
            "max_list_items",
            "max_code_chars",
            "max_image_blocks",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class Block:
    """One safe, renderer-neutral content block.

    Only ``image.url`` is a locator, and it is never rendered directly.  The
    materializer resolves and fetches it under the same-origin policy before
    assigning a local ``assets/`` name.  All other fields are plain text or
    bounded tables/lists.
    """

    kind: BlockKind
    text: str = ""
    level: int = 0
    ordered: bool = False
    items: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    url: str | None = None
    alt: str = ""
    language: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {
            "heading",
            "paragraph",
            "list",
            "quote",
            "code",
            "table",
            "image",
            "linebreak",
            "placeholder",
        }:
            raise ValueError(f"unsupported block kind: {self.kind}")
        if self.kind == "heading" and not 1 <= int(self.level) <= 6:
            raise ValueError("heading level must be between 1 and 6")
        if self.kind == "image" and self.url is not None and not isinstance(self.url, str):
            raise ValueError("image url must be text")


@dataclass(frozen=True, slots=True)
class BlockIR:
    """Immutable extraction result consumed by the web materializer."""

    blocks: tuple[Block, ...]
    title: str = ""
    truncated: bool = False
    warnings: tuple[str, ...] = ()
    source_url: str = ""

    @property
    def image_count(self) -> int:
        return sum(1 for block in self.blocks if block.kind == "image")

    @property
    def text_chars(self) -> int:
        total = 0
        for block in self.blocks:
            total += len(block.text)
            total += sum(len(item) for item in block.items)
            total += sum(len(cell) for row in block.rows for cell in row)
            total += len(block.alt)
        return total


# These are deliberately conservative.  In particular, SVG and canvas are
# not treated as images because they can carry active content or enormous DOMs.
_DROP_TAGS = frozenset(
    {
        "script",
        "style",
        "iframe",
        "frame",
        "frameset",
        "form",
        "object",
        "embed",
        "applet",
        "noscript",
        "template",
        "svg",
        "canvas",
        "video",
        "audio",
        "source",
        "track",
        "input",
        "button",
        "select",
        "textarea",
    }
)
_NOISE_TAGS = frozenset({"nav", "aside", "footer", "menu", "dialog"})
_NOISE_NAME_RE = re.compile(
    r"(?:^|[-_\s])(?:nav|menu|sidebar|breadcrumb|cookie|consent|advert|ads?|promo|"
    r"share|social|comment|comments|related|recommend|pagination|login|register|"
    r"toolbar|topbar|popup|modal)(?:$|[-_\s])",
    re.IGNORECASE,
)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "div",
        "dl",
        "dt",
        "dd",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
_HEADING_TAGS = {f"h{number}" for number in range(1, 7)}
_ALLOWED_IMAGE_SCHEMES = frozenset({"http", "https"})


def _tag(node: etree._Element) -> str:
    raw = node.tag
    if not isinstance(raw, str):
        return ""
    return raw.rsplit("}", 1)[-1].casefold()


def _clean_text(value: str, *, preserve_newlines: bool = False) -> str:
    value = value.replace("\xa0", " ").replace("\u200b", "")
    if preserve_newlines:
        value = re.sub(r"[ \t\f\v]+", " ", value)
        value = re.sub(r"\n[ \t]+", "\n", value)
        return value.strip()
    return re.sub(r"\s+", " ", value).strip()


def _node_text(node: etree._Element, *, preserve_newlines: bool = False) -> str:
    pieces: list[str] = []
    for value in node.itertext():
        if isinstance(value, str):
            pieces.append(value)
    return _clean_text("".join(pieces), preserve_newlines=preserve_newlines)


def _safe_image_reference(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 4096:
        return None
    # Keep relative references for the materializer to resolve, but discard
    # schemes that can never be safely materialized as a remote image.
    if candidate.casefold().startswith(("data:", "javascript:", "vbscript:", "file:")):
        return None
    if any(ord(char) < 0x20 for char in candidate):
        return None
    return candidate


def _image_reference(node: etree._Element) -> str | None:
    for attribute in ("src", "data-src", "data-original", "data-lazy-src"):
        reference = _safe_image_reference(node.get(attribute))
        if reference:
            return reference
    srcset = node.get("srcset") or node.get("data-srcset")
    if isinstance(srcset, str):
        # The first candidate is deterministic and is enough for a bounded
        # offline bundle.  Width descriptors are ignored deliberately.
        first = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
        return _safe_image_reference(first)
    return None


def _noise_node(node: etree._Element) -> bool:
    tag = _tag(node)
    if tag in _DROP_TAGS or tag in _NOISE_TAGS:
        return True
    role = (node.get("role") or "").casefold().strip()
    if role in {"navigation", "banner", "contentinfo", "complementary", "dialog"}:
        return True
    if (node.get("aria-hidden") or "").casefold() == "true":
        return True
    marker = " ".join(
        part
        for part in (node.get("id") or "", node.get("class") or "")
        if part
    )
    return bool(marker and _NOISE_NAME_RE.search(marker))


def _walk_elements(node: etree._Element) -> Iterator[etree._Element]:
    yield node
    for child in node:
        if isinstance(child.tag, str):
            yield from _walk_elements(child)


def _measure_dom(root: etree._Element, limits: BlockLimits) -> None:
    count = 0
    stack: list[tuple[etree._Element, int]] = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > limits.max_dom_nodes:
            raise BlockExtractionError("DOM_LIMIT", "HTML DOM 节点数量超过上限")
        if depth > limits.max_depth:
            raise BlockExtractionError("DOM_DEPTH_LIMIT", "HTML DOM 深度超过上限")
        for child in reversed(node):
            if isinstance(child.tag, str):
                stack.append((child, depth + 1))


def _remove_noise(root: etree._Element) -> None:
    # Snapshot the walk before mutation so lxml iterator invalidation cannot
    # skip a sibling.  The source tree is private and never rendered directly.
    for node in list(_walk_elements(root)):
        if node is root or not _noise_node(node):
            continue
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)


def _content_candidate_score(node: etree._Element) -> tuple[int, int, int]:
    text = _node_text(node)
    headings = sum(1 for child in node.iter() if _tag(child) in _HEADING_TAGS)
    paragraphs = sum(1 for child in node.iter() if _tag(child) in {"p", "li"})
    return (min(len(text), 1_000_000), headings, paragraphs)


def _select_content_root(root: etree._Element) -> etree._Element:
    candidates = [
        node
        for node in _walk_elements(root)
        if _tag(node) in {"article", "main"}
    ]
    if candidates:
        return max(candidates, key=_content_candidate_score)
    for node in _walk_elements(root):
        if _tag(node) == "body":
            return node
    return root


def _first_title(root: etree._Element) -> str:
    for node in _walk_elements(root):
        if _tag(node) == "title":
            title = _node_text(node)
            if title:
                return title[:512]
    for node in _walk_elements(root):
        if _tag(node) == "h1":
            title = _node_text(node)
            if title:
                return title[:512]
    return ""


def _has_structural_child(node: etree._Element) -> bool:
    return any(_tag(child) in _BLOCK_TAGS for child in node)


def _inline_text(node: etree._Element, *, skip_lists: bool = True) -> str:
    pieces: list[str] = []

    def visit(current: etree._Element) -> None:
        current_tag = _tag(current)
        if skip_lists and current_tag in {"ul", "ol"}:
            return
        if current.text:
            pieces.append(current.text)
        for child in current:
            if isinstance(child.tag, str):
                if _tag(child) == "br":
                    pieces.append("\n")
                else:
                    visit(child)
            if child.tail:
                pieces.append(child.tail)

    visit(node)
    return _clean_text("".join(pieces), preserve_newlines=True)


class _BlockBuilder:
    def __init__(self, limits: BlockLimits) -> None:
        self.limits = limits
        self.blocks: list[Block] = []
        self.text_chars = 0
        self.truncated = False
        self._placeholder_added = False

    def _cost(self, block: Block) -> int:
        return (
            len(block.text)
            + len(block.alt)
            + sum(len(item) for item in block.items)
            + sum(len(cell) for row in block.rows for cell in row)
        )

    def add(self, block: Block) -> None:
        if len(self.blocks) >= self.limits.max_blocks:
            self.truncated = True
            return
        cost = self._cost(block)
        remaining = self.limits.max_text_chars - self.text_chars
        if cost > remaining:
            self.truncated = True
            if block.kind in {"heading", "paragraph", "quote", "code", "placeholder"}:
                clipped = block.text[: max(0, remaining)]
                if clipped:
                    block = replace(block, text=clipped)
                    cost = self._cost(block)
                else:
                    return
            elif block.kind == "list":
                items: list[str] = []
                left = max(0, remaining)
                for item in block.items:
                    if left <= 0:
                        break
                    clipped = item[:left]
                    items.append(clipped)
                    left -= len(clipped)
                if not items:
                    return
                block = replace(block, items=tuple(items))
                cost = self._cost(block)
            elif block.kind == "table":
                rows: list[tuple[str, ...]] = []
                left = max(0, remaining)
                for row in block.rows:
                    if left <= 0:
                        break
                    clipped_row: list[str] = []
                    for cell in row:
                        clipped = cell[:left]
                        clipped_row.append(clipped)
                        left -= len(clipped)
                    rows.append(tuple(clipped_row))
                if not rows:
                    return
                block = replace(block, rows=tuple(rows))
                cost = self._cost(block)
            else:
                # Image and linebreak blocks carry no unbounded text.  They
                # are still useful after the text budget is full.
                cost = 0
        self.blocks.append(block)
        self.text_chars += cost

    def placeholder(self, message: str) -> None:
        if self._placeholder_added:
            return
        self._placeholder_added = True
        marker = Block(kind="placeholder", text=_clean_text(message)[:256])
        if len(self.blocks) >= self.limits.max_blocks:
            # Preserve the hard block bound while ensuring callers can see
            # that content was intentionally truncated.
            if self.blocks:
                self.text_chars -= self._cost(self.blocks[-1])
                self.blocks[-1] = marker
                self.text_chars += self._cost(marker)
            return
        self.add(marker)


def _emit_inline_container(node: etree._Element, builder: _BlockBuilder) -> None:
    text_parts: list[str] = []

    def flush() -> None:
        text = _clean_text("".join(text_parts))
        if text:
            builder.add(Block(kind="paragraph", text=text))
        text_parts.clear()

    def visit(current: etree._Element) -> None:
        if current.text:
            text_parts.append(current.text)
        for child in current:
            child_tag = _tag(child)
            if child_tag == "img":
                flush()
                reference = _image_reference(child)
                alt = _clean_text(child.get("alt") or "")[:512]
                builder.add(Block(kind="image", url=reference, alt=alt))
            elif child_tag == "br":
                flush()
                builder.add(Block(kind="linebreak"))
            elif child_tag in _DROP_TAGS:
                pass
            elif child_tag in {"ul", "ol", "table", "pre", "blockquote"}:
                flush()
                _emit_node(child, builder)
            else:
                visit(child)
            if child.tail:
                text_parts.append(child.tail)

    visit(node)
    flush()


def _emit_list(node: etree._Element, builder: _BlockBuilder, limits: BlockLimits) -> None:
    items: list[str] = []
    for child in node:
        if _tag(child) != "li":
            continue
        text = _inline_text(child)
        if text:
            items.append(text[:limits.max_text_chars])
        if len(items) >= limits.max_list_items:
            builder.truncated = True
            break
    if items:
        builder.add(Block(kind="list", ordered=_tag(node) == "ol", items=tuple(items)))


def _emit_table(node: etree._Element, builder: _BlockBuilder, limits: BlockLimits) -> None:
    rows: list[tuple[str, ...]] = []
    for row_node in node.iter():
        if _tag(row_node) != "tr":
            continue
        cells: list[str] = []
        for cell in row_node:
            if _tag(cell) not in {"th", "td"}:
                continue
            cells.append(_inline_text(cell, skip_lists=False)[:limits.max_text_chars])
            if len(cells) >= limits.max_table_columns:
                builder.truncated = True
                break
        if cells:
            rows.append(tuple(cells))
        if len(rows) >= limits.max_table_rows:
            builder.truncated = True
            break
    if rows:
        builder.add(Block(kind="table", rows=tuple(rows)))


def _emit_node(node: etree._Element, builder: _BlockBuilder) -> None:
    tag = _tag(node)
    if not tag or _noise_node(node):
        return
    if tag in _HEADING_TAGS:
        text = _inline_text(node)
        if text:
            builder.add(Block(kind="heading", level=int(tag[1]), text=text[:4096]))
        return
    if tag == "pre":
        code = _node_text(node, preserve_newlines=True)
        code = code[: builder.limits.max_code_chars]
        if len(code) >= builder.limits.max_code_chars:
            builder.truncated = True
        if code:
            language = ""
            marker = " ".join(
                part for part in ((node.get("class") or ""), (node.get("data-language") or "")) if part
            )
            match = re.search(r"(?:language|lang)[-_ ]([A-Za-z0-9_+-]{1,32})", marker, re.IGNORECASE)
            if match:
                language = match.group(1).casefold()
            builder.add(Block(kind="code", text=code, language=language))
        return
    if tag == "blockquote":
        text = _inline_text(node, skip_lists=False)
        if text:
            builder.add(Block(kind="quote", text=text[:builder.limits.max_text_chars]))
        return
    if tag in {"ul", "ol"}:
        _emit_list(node, builder, builder.limits)
        return
    if tag == "table":
        _emit_table(node, builder, builder.limits)
        return
    if tag == "img":
        builder.add(
            Block(
                kind="image",
                url=_image_reference(node),
                alt=_clean_text(node.get("alt") or "")[:512],
            )
        )
        return
    if tag in {"br", "hr"}:
        builder.add(Block(kind="linebreak"))
        return
    if tag in {"p", "figcaption", "address", "dt", "dd"}:
        _emit_inline_container(node, builder)
        return
    if _has_structural_child(node):
        if node.text and _clean_text(node.text):
            builder.add(Block(kind="paragraph", text=_clean_text(node.text)))
        for child in node:
            _emit_node(child, builder)
            if child.tail and _clean_text(child.tail):
                builder.add(Block(kind="paragraph", text=_clean_text(child.tail)))
        return
    _emit_inline_container(node, builder)


def _html_parser() -> etree.HTMLParser:
    """Create the strict non-networking parser across supported lxml builds.

    Some lxml releases expose ``resolve_entities`` only on ``XMLParser`` and
    reject that keyword for ``HTMLParser``.  HTMLParser does not resolve
    external entities in that configuration, so retain the explicit keyword
    where the runtime supports it and use the equivalent safe fallback where
    it does not.
    """

    try:
        return etree.HTMLParser(
            no_network=True,
            resolve_entities=False,
            huge_tree=False,
            recover=True,
            remove_comments=True,
        )
    except TypeError as exc:
        if "resolve_entities" not in str(exc):
            raise
        return etree.HTMLParser(
            no_network=True,
            huge_tree=False,
            recover=True,
            remove_comments=True,
        )


def extract_block_ir(
    html: str | bytes,
    *,
    source_url: str = "",
    title: str = "",
    limits: BlockLimits | None = None,
) -> BlockIR:
    """Parse *html* into bounded, renderer-neutral Block IR.

    The parser is explicitly non-networking and does not resolve entities.
    Text and block limits truncate with a placeholder; DOM and byte limits are
    rejected before extraction because continuing would make resource use
    unpredictable.
    """

    effective_limits = limits or BlockLimits()
    if isinstance(html, str):
        raw = html.encode("utf-8", "replace")
    elif isinstance(html, bytes):
        raw = html
    else:
        raise BlockExtractionError("INVALID_HTML", "HTML 必须是文本或字节")
    if len(raw) > effective_limits.max_html_bytes:
        raise BlockExtractionError("HTML_LIMIT", "HTML 响应超过大小上限")
    if not raw.strip():
        raise BlockExtractionError("EMPTY_HTML", "HTML 响应为空")

    parser = _html_parser()
    try:
        root = etree.fromstring(raw, parser=parser)
    except (etree.XMLSyntaxError, ValueError, TypeError) as exc:
        raise BlockExtractionError("INVALID_HTML", "HTML 解析失败") from exc
    if root is None or not isinstance(root.tag, str):
        raise BlockExtractionError("INVALID_HTML", "HTML 文档没有根节点")
    _measure_dom(root, effective_limits)
    _remove_noise(root)
    content_root = _select_content_root(root)
    builder = _BlockBuilder(effective_limits)
    _emit_node(content_root, builder)
    if not builder.blocks:
        builder.placeholder("页面没有提取到可读正文")
    if builder.truncated:
        builder.placeholder("内容因安全上限被截断")

    resolved_title = _clean_text(title)[:512] if title else _first_title(root)
    warnings: list[str] = []
    if builder.truncated:
        warnings.append("content_truncated")
    return BlockIR(
        blocks=tuple(builder.blocks),
        title=resolved_title,
        truncated=builder.truncated,
        warnings=tuple(warnings),
        source_url=source_url,
    )


# Short aliases make the extractor convenient for unit tests and for the
# materializer without creating a second parsing implementation.
extract_blocks = extract_block_ir
build_block_ir = extract_block_ir


def block_to_mapping(block: Block) -> dict[str, object]:
    """Return a JSON-friendly diagnostic view of one block."""

    result: dict[str, object] = {"kind": block.kind}
    if block.text:
        result["text"] = block.text
    if block.level:
        result["level"] = block.level
    if block.items:
        result["items"] = list(block.items)
    if block.rows:
        result["rows"] = [list(row) for row in block.rows]
    if block.kind == "list":
        result["ordered"] = block.ordered
    if block.kind == "image":
        result["url"] = block.url
        result["alt"] = block.alt
    if block.language:
        result["language"] = block.language
    return result


__all__ = [
    "Block",
    "BlockExtractionError",
    "BlockIR",
    "BlockKind",
    "BlockLimits",
    "DEFAULT_MAX_BLOCKS",
    "DEFAULT_MAX_DOM_DEPTH",
    "DEFAULT_MAX_DOM_NODES",
    "DEFAULT_MAX_HTML_BYTES",
    "DEFAULT_MAX_IMAGE_BLOCKS",
    "DEFAULT_MAX_TEXT_CHARS",
    "build_block_ir",
    "block_to_mapping",
    "extract_block_ir",
    "extract_blocks",
]
