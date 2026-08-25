"""Content-aware design context and controlled offline HTML rendering."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import html as html_module
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .acquisition.web_materializer import _reader_base_css
from .errors import DomainError
from .job_state import TERMINAL_STATUSES, write_job
from .policy import ensure_within_root


_EXCERPT_CHARS = 1600
_OUTLINE_ITEMS = 16
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAIN_OPEN_RE = re.compile(
    r'<main\b[^>]*\bid=["\']content["\'][^>]*>',
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

_TYPE_SYSTEMS = {
    "editorial": (
        '"Songti SC", "Noto Serif SC", "Source Han Serif SC", '
        'STSong, Georgia, serif',
        '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif',
    ),
    "humanist": (
        '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif',
        '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif',
    ),
    "technical": (
        '"Avenir Next", "Segoe UI", "Noto Sans SC", system-ui, sans-serif',
        '"Segoe UI", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif',
    ),
    "rounded": (
        '"Arial Rounded MT Bold", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
        '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif',
    ),
    "classical": (
        '"Kaiti SC", KaiTi, "STKaiti", "Noto Serif SC", serif',
        '"Songti SC", "Noto Serif SC", STSong, SimSun, serif',
    ),
}
_LAYOUT_WIDTHS = {
    "focused": "42rem",
    "standard": "52rem",
    "wide": "66rem",
    "visual": "76rem",
}
_DENSITY = {
    "compact": ("1.72", ".82rem", "1.6rem"),
    "comfortable": ("1.88", "1rem", "2.2rem"),
    "spacious": ("2.02", "1.18rem", "3rem"),
}
_ENUMS = {
    "treatment": frozenset({"utilitarian", "editorial"}),
    "type_system": frozenset(_TYPE_SYSTEMS),
    "layout": frozenset(_LAYOUT_WIDTHS),
    "hero": frozenset({"understated", "editorial", "banner", "poster"}),
    "section_style": frozenset({"plain", "ruled", "banded", "cards"}),
    "image_style": frozenset({"natural", "framed", "full_bleed", "gallery"}),
    "density": frozenset(_DENSITY),
    "signature": frozenset({"accent_rule", "corner_mark", "side_rail", "none"}),
}
_PALETTE_KEYS = (
    "background",
    "surface",
    "text",
    "muted",
    "accent",
    "accent_soft",
    "border",
)


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DomainError("FILE_NOT_FOUND", f"HTML 设计所需的 {label} 不存在") from None
    except OSError as exc:
        raise DomainError("JOB_STATE_INVALID", f"HTML 设计无法读取 {label}: {exc}") from None


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path, label))
    except json.JSONDecodeError as exc:
        raise DomainError("JOB_STATE_INVALID", f"HTML 设计所需的 {label} 无效: {exc}") from None
    if not isinstance(value, dict):
        raise DomainError("JOB_STATE_INVALID", f"HTML 设计所需的 {label} 结构无效")
    return value


def _web_files(directory: Path, job: Mapping[str, Any]) -> tuple[Path, Path, Path]:
    status = str(job.get("status") or "")
    if status not in TERMINAL_STATUSES or status not in {"succeeded", "partial"}:
        raise DomainError("JOB_NOT_FINISHED", "HTML 设计只接受已完成并产生网页文件的 Download Job")
    filenames = [str(item.get("filename") or "") for item in job.get("files") or []]
    if filenames.count("index.html") != 1 or filenames.count("metadata.json") != 1:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "HTML 设计只支持恰好包含一个网页产物的 Download Job",
        )
    paths = tuple(
        ensure_within_root(directory / name, directory)
        for name in ("index.html", "content.md", "metadata.json")
    )
    index_path, markdown_path, metadata_path = paths
    metadata = _read_json(metadata_path, "metadata.json")
    if metadata.get("schema_version") != "web-materialization-v2":
        raise DomainError("FEATURE_NOT_SUPPORTED", "该 Job 不是可设计的 Generic Web 清洗结果")
    _read_text(index_path, "index.html")
    _read_text(markdown_path, "content.md")
    return index_path, markdown_path, metadata_path


def _main_fragment(document: str) -> str:
    match = _MAIN_OPEN_RE.search(document)
    if match is None:
        raise DomainError("CONTENT_VALIDATION_FAILED", "index.html 缺少可设计的正文区域")
    end = document.casefold().rfind("</main>")
    if end < match.end():
        raise DomainError("CONTENT_VALIDATION_FAILED", "index.html 的正文区域没有正确闭合")
    return document[match.end():end]


def design_context(directory: Path, job: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded semantic/structural brief without returning the full page."""

    index_path, markdown_path, metadata_path = _web_files(directory, job)
    markdown = _read_text(markdown_path, "content.md")
    metadata = _read_json(metadata_path, "metadata.json")
    document = _read_text(index_path, "index.html")
    fragment = _main_fragment(document)
    soup = BeautifulSoup(fragment, "html.parser")
    plain = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    excerpt = plain[:_EXCERPT_CHARS]
    outline: list[dict[str, Any]] = []
    outline_total = 0
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match is None:
            continue
        outline_total += 1
        if len(outline) < _OUTLINE_ITEMS:
            outline.append({"level": len(match.group(1)), "text": match.group(2)[:160]})
    file_item = next(
        item for item in job.get("files") or [] if item.get("filename") == "index.html"
    )
    source_url = str(metadata.get("source_url") or file_item.get("source_url") or "")
    title = str(file_item.get("title") or "").strip()
    if not title:
        title_tag = BeautifulSoup(document, "html.parser").find("title")
        title = title_tag.get_text(strip=True) if title_tag else "教育资源"
    return {
        "job_id": str(job.get("job_id") or ""),
        "title": title,
        "source_url": source_url,
        "source_domain": urlsplit(source_url).hostname or "",
        "excerpt": excerpt,
        "excerpt_chars": len(excerpt),
        "content_chars": len(plain),
        "excerpt_truncated": len(plain) > len(excerpt),
        "outline": outline,
        "outline_total": outline_total,
        "outline_truncated": outline_total > len(outline),
        "structure": {
            "headings": len(soup.find_all(re.compile(r"^h[1-6]$"))),
            "paragraphs": len(soup.find_all("p")),
            "images": len(soup.find_all("img")),
            "tables": len(soup.find_all("table")),
            "code_blocks": len(soup.find_all("pre")),
            "blockquotes": len(soup.find_all("blockquote")),
            "lists": len(soup.find_all(["ul", "ol"])),
        },
        "constraints": {
            "content_must_remain_complete": True,
            "offline_self_contained": True,
            "scripts_allowed": False,
            "remote_assets_allowed": False,
        },
        "untrusted_content": True,
    }


def _short_text(spec: Mapping[str, Any], key: str, limit: int, *, required: bool = True) -> str:
    value = str(spec.get(key) or "").strip()
    if required and not value:
        raise DomainError("INVALID_ARGUMENT", f"HTML DesignSpec 缺少 {key}")
    if len(value) > limit:
        raise DomainError("INVALID_ARGUMENT", f"HTML DesignSpec 的 {key} 过长")
    return value


def _relative_luminance(color: str) -> float:
    values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _validate_palette_contrast(name: str, palette: Mapping[str, str]) -> None:
    pairs = (
        ("text", "background", 4.5),
        ("text", "surface", 4.5),
        ("text", "accent_soft", 4.5),
        ("muted", "background", 3.0),
        ("muted", "surface", 3.0),
        ("accent", "background", 4.5),
        ("accent", "surface", 4.5),
    )
    for foreground, background, minimum in pairs:
        ratio = _contrast(palette[foreground], palette[background])
        if ratio < minimum:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"{name} 的 {foreground}/{background} 对比度 {ratio:.2f} 低于 {minimum:.1f}",
            )


def normalize_design_spec(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise DomainError("INVALID_ARGUMENT", "design_spec 必须是对象")
    allowed = {
        "theme_name", "subject", "audience", "page_purpose", "rationale", "treatment",
        "light_palette", "dark_palette",
        "type_system", "layout", "hero", "section_style", "image_style", "density",
        "signature",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DomainError("INVALID_ARGUMENT", f"HTML DesignSpec 含未知字段：{unknown}")
    palettes: dict[str, dict[str, str]] = {}
    for palette_name in ("light_palette", "dark_palette"):
        palette_raw = raw.get(palette_name)
        if not isinstance(palette_raw, Mapping):
            raise DomainError("INVALID_ARGUMENT", f"HTML DesignSpec 缺少 {palette_name}")
        if set(palette_raw) != set(_PALETTE_KEYS):
            raise DomainError(
                "INVALID_ARGUMENT",
                f"{palette_name} 必须且只能包含：{list(_PALETTE_KEYS)}",
            )
        palette = {key: str(palette_raw[key]).strip() for key in _PALETTE_KEYS}
        for key, value in palette.items():
            if not _HEX_COLOR_RE.fullmatch(value):
                raise DomainError(
                    "INVALID_ARGUMENT",
                    f"{palette_name}.{key} 必须是六位十六进制颜色",
                )
        _validate_palette_contrast(palette_name, palette)
        palettes[palette_name] = palette
    normalized = {
        "theme_name": _short_text(raw, "theme_name", 80),
        "subject": _short_text(raw, "subject", 160),
        "audience": _short_text(raw, "audience", 160),
        "page_purpose": _short_text(raw, "page_purpose", 240),
        "rationale": _short_text(raw, "rationale", 600),
        "light_palette": palettes["light_palette"],
        "dark_palette": palettes["dark_palette"],
    }
    defaults = {
        "treatment": "utilitarian",
        "type_system": "humanist",
        "layout": "standard",
        "hero": "editorial",
        "section_style": "plain",
        "image_style": "natural",
        "density": "comfortable",
        "signature": "accent_rule",
    }
    for key, default in defaults.items():
        value = str(raw.get(key) or default).strip()
        if value not in _ENUMS[key]:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"HTML DesignSpec 的 {key} 无效，可用值：{sorted(_ENUMS[key])}",
            )
        normalized[key] = value
    return normalized


def _adaptive_css(spec: Mapping[str, Any]) -> str:
    light_palette = spec["light_palette"]
    dark_palette = spec["dark_palette"]
    display_font, body_font = _TYPE_SYSTEMS[str(spec["type_system"])]
    width = _LAYOUT_WIDTHS[str(spec["layout"])]
    line_height, paragraph_gap, section_gap = _DENSITY[str(spec["density"])]
    light_variables = "\n".join(
        f"  --design-{key.replace('_', '-')}: {value};"
        for key, value in light_palette.items()
    )
    dark_variables = "\n".join(
        f"  --design-{key.replace('_', '-')}: {value};"
        for key, value in dark_palette.items()
    )
    return f"""
/* Adaptive Reader: controlled DesignSpec; content is preserved verbatim. */
:root {{
{light_variables}
  --design-width: {width};
  --design-display: {display_font};
  --design-body: {body_font};
  --bg: var(--design-background);
  --accent-bg: var(--design-accent-soft);
  --text: var(--design-text);
  --text-light: var(--design-muted);
  --border: var(--design-border);
  --accent: var(--design-accent);
}}
:root[data-theme="light"] {{
{light_variables}
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{dark_variables}
  }}
}}
:root[data-theme="dark"] {{
{dark_variables}
}}
* {{ box-sizing: border-box; }}
body {{
  display: block;
  margin: 0;
  background: var(--design-background);
  color: var(--design-text);
  font-family: var(--design-body);
  font-size: 18px;
  line-height: {line_height};
}}
.reader-bar {{
  background: var(--design-surface);
  border-bottom: 1px solid var(--design-border);
  padding: .85rem max(1rem, calc((100vw - var(--design-width)) / 2));
}}
.reader-meta {{ align-items: center; display: flex; gap: .8rem; margin: 0; max-width: none; padding: 0; }}
.reader-badge {{
  background: var(--design-accent); color: var(--design-background); display: inline-flex;
  font-size: .75rem; font-weight: 750; letter-spacing: .08em; padding: .36rem .58rem;
}}
.reader-domain {{ color: var(--design-muted); font-size: .82rem; overflow-wrap: anywhere; }}
.reader-source-link {{ color: var(--design-accent); font-size: .82rem; margin-inline-start: auto; }}
.reader-main {{ margin: 0 auto; max-width: var(--design-width); padding: 3.2rem 1.4rem 1rem; }}
.reader-main h1, .reader-main h2, .reader-main h3, .reader-main h4 {{
  color: var(--design-text); font-family: var(--design-display); line-height: 1.25; text-wrap: balance;
}}
.reader-main h1 {{ font-size: clamp(2.1rem, 6vw, 4.7rem); letter-spacing: -.035em; margin: 0 0 2.4rem; }}
.reader-main h2 {{ font-size: clamp(1.45rem, 3vw, 2.25rem); margin-top: {section_gap}; }}
.reader-main h3 {{ font-size: 1.2rem; margin-top: 2rem; }}
.reader-main p {{ margin: {paragraph_gap} 0; }}
.reader-main p, .reader-main li, .reader-main blockquote {{ max-width: 68ch; }}
.reader-main a {{ color: var(--design-accent); text-decoration-thickness: .08em; text-underline-offset: .18em; }}
.reader-main blockquote {{
  background: var(--design-accent-soft); border-left: 4px solid var(--design-accent);
  color: var(--design-text); margin: 1.8rem 0; padding: 1rem 1.3rem;
}}
.reader-main pre, .reader-main code {{ font-family: Consolas, "Cascadia Code", monospace; }}
.reader-main pre {{ background: var(--design-surface); border: 1px solid var(--design-border); overflow-x: auto; padding: 1.1rem; }}
.reader-main :not(pre) > code {{ background: var(--design-accent-soft); padding: .12em .36em; }}
.reader-main table {{ border-collapse: collapse; display: block; max-width: 100%; overflow-x: auto; }}
.reader-main th {{ background: var(--design-surface); }}
.reader-main th, .reader-main td {{ border: 1px solid var(--design-border); padding: .65rem .8rem; }}
.reader-main img {{ display: block; height: auto; margin: 2rem auto; max-width: 100%; }}
.reader-footer {{ border-top: 1px solid var(--design-border); color: var(--design-muted); margin: 3rem auto 0; max-width: var(--design-width); padding: 1rem 1.4rem 2.5rem; }}
.reader-footer p {{ margin: 0; max-width: none; padding: 0; }}
body[data-hero="understated"] .reader-main h1 {{ font-size: clamp(1.9rem, 4vw, 3rem); }}
body[data-hero="banner"] .reader-main h1 {{ background: var(--design-accent); color: var(--design-background); margin-inline: -1.4rem; padding: 1.6rem 1.4rem; }}
body[data-hero="poster"] .reader-main h1 {{ border-bottom: .22em solid var(--design-accent); padding-bottom: .55em; text-transform: none; }}
body[data-section="ruled"] .reader-main h2 {{ border-bottom: 1px solid var(--design-border); padding-bottom: .45rem; }}
body[data-section="banded"] .reader-main h2 {{ background: var(--design-accent-soft); margin-inline: -.8rem; padding: .55rem .8rem; }}
body[data-section="cards"] .reader-main section {{ background: var(--design-surface); border: 1px solid var(--design-border); padding: 1.3rem; }}
body[data-image="framed"] .reader-main img {{ border: 1px solid var(--design-border); box-shadow: 0 14px 38px rgb(0 0 0 / 14%); padding: .45rem; }}
body[data-image="full_bleed"] .reader-main img {{ margin-inline: 50%; max-width: min(100vw - 2rem, 76rem); transform: translateX(-50%); width: max-content; }}
body[data-image="gallery"] .reader-main figure {{ background: var(--design-surface); border: 1px solid var(--design-border); padding: 1rem; }}
body[data-signature="accent_rule"] .reader-main h1::after {{ background: var(--design-accent); content: ""; display: block; height: 4px; margin-top: .65em; width: 4.5rem; }}
body[data-signature="corner_mark"] .reader-main {{ border-top: 10px solid var(--design-accent); }}
body[data-signature="side_rail"] .reader-main {{ border-left: 3px solid var(--design-accent); }}
:focus-visible {{ outline: 3px solid var(--design-accent); outline-offset: 3px; }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; }} }}
@media (width <= 720px) {{
  body {{ font-size: 16.5px; }}
  .reader-main {{ padding: 2rem .9rem .5rem; }}
  .reader-domain {{ display: none; }}
  body[data-hero="banner"] .reader-main h1 {{ margin-inline: -.9rem; padding-inline: .9rem; }}
  body[data-signature="side_rail"] .reader-main {{ border-left: 0; }}
}}
@media print {{
  .reader-bar {{ background: transparent; padding-inline: 0; }}
  .reader-source-link {{ display: none; }}
  .reader-main, .reader-footer {{ max-width: none; padding-inline: 0; }}
}}
""".strip()


def _document(fragment: str, context: Mapping[str, Any], spec: Mapping[str, Any]) -> str:
    title = html_module.escape(str(context.get("title") or "教育资源"), quote=False)
    source_url = str(context.get("source_url") or "")
    safe_url = html_module.escape(source_url, quote=True)
    domain = html_module.escape(str(context.get("source_domain") or ""), quote=False)
    safe_theme = html_module.escape(str(spec["theme_name"]), quote=False)
    attrs = " ".join(
        f'data-{key.replace("_style", "")}="{html_module.escape(str(spec[key]), quote=True)}"'
        for key in ("treatment", "hero", "section_style", "image_style", "signature")
    )
    csp = (
        "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
        "script-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"
    )
    return (
        '<!doctype html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{html_module.escape(csp, quote=True)}">\n'
        f"<title>{title}</title>\n<!-- Adaptive Reader v1; full cleaned content preserved. -->\n<style>\n"
        f"{_reader_base_css()}{_adaptive_css(spec)}\n</style>\n</head>\n"
        f"<body {attrs}>\n<header class=\"reader-bar\"><div class=\"reader-meta\">"
        f'<span class="reader-badge">{safe_theme}</span><span class="reader-domain">{domain}</span>'
        f'<a class="reader-source-link" href="{safe_url}">原网页</a></div></header>\n'
        f'<main class="reader-main" id="content">{fragment}</main>\n'
        '<footer class="reader-footer"><p>依据清洗正文生成的自包含离线阅读页 · '
        '原始响应与 Markdown 保存在同一资源任务中</p></footer>\n</body>\n</html>\n'
    )


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".design.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def render_design(
    directory: Path,
    job: Mapping[str, Any],
    raw_spec: Mapping[str, Any],
) -> dict[str, Any]:
    """Render a validated DesignSpec while preserving the full cleaned body."""

    index_path, _markdown_path, metadata_path = _web_files(directory, job)
    before_index = index_path.read_bytes()
    before_metadata = metadata_path.read_bytes()
    original_document = before_index.decode("utf-8")
    fragment = _main_fragment(original_document)
    spec = normalize_design_spec(raw_spec)
    context = design_context(directory, job)
    rendered = _document(fragment, context, spec)
    if _main_fragment(rendered) != fragment:
        raise DomainError("CONTENT_VALIDATION_FAILED", "HTML 设计渲染未完整保留清洗正文")
    try:
        metadata = json.loads(before_metadata.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("JOB_STATE_INVALID", f"metadata.json 无效: {exc}") from None
    designed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    metadata.update(
        {
            "reader_template": "adaptive-reader-v1",
            "reader_theme": spec["theme_name"],
            "html_design": spec,
            "designed_at": designed_at,
        }
    )
    metadata_bytes = (
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        _atomic_write(index_path, rendered.encode("utf-8"))
        _atomic_write(metadata_path, metadata_bytes)
        current = dict(job)
        files = []
        for raw in current.get("files") or []:
            item = dict(raw)
            if item.get("filename") == "index.html":
                item.update({"path": str(index_path), "size_bytes": index_path.stat().st_size})
            elif item.get("filename") == "metadata.json":
                item.update({"path": str(metadata_path), "size_bytes": metadata_path.stat().st_size})
            files.append(item)
        current["files"] = files
        summary = dict(current.get("summary") or {})
        summary["html_design"] = {
            "reader_template": "adaptive-reader-v1",
            "theme_name": spec["theme_name"],
            "designed_at": designed_at,
            "content_preserved": True,
        }
        current["summary"] = summary
        write_job(directory, current)
    except Exception:
        _atomic_write(index_path, before_index)
        _atomic_write(metadata_path, before_metadata)
        raise
    return {
        "job_id": str(job.get("job_id") or ""),
        "status": str(job.get("status") or ""),
        "reader_template": "adaptive-reader-v1",
        "theme_name": spec["theme_name"],
        "designed_at": designed_at,
        "content_preserved": True,
        "file": {
            "filename": "index.html",
            "path": str(index_path),
            "media_type": "text/html",
            "size_bytes": index_path.stat().st_size,
        },
    }


__all__ = ["design_context", "normalize_design_spec", "render_design"]
