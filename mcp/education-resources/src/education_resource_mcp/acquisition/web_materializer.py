"""Static web materialization with source preservation and mature extraction.

The fetch layer owns network policy. This module saves the fetched HTML response
unchanged as ``source.html``, uses Trafilatura to derive readable content, then
renders the cleaned HTML inside one stable offline-friendly Reader template.
Extraction is a derivative view: failure to extract readable text does not erase
or truncate the successfully fetched source snapshot.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timezone
from dataclasses import dataclass
import hashlib
import html as html_module
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from trafilatura import extract as trafilatura_extract

from ..errors import DomainError
from ..policy import ensure_within_root
from .models import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
)
from .web_fetch import BoundedWebFetcher, FetchResult


MAX_HTML_BYTES = 8 * 1024 * 1024
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_HTTP_SCHEMES = frozenset({"http", "https"})
_READER_THEME = "Simple.css"
_READER_THEME_VERSION = "2.3.7"
_READER_TEMPLATE = "clean-reader-v2"
_IMAGE_FETCH_ATTEMPTS = 3
_VENDOR_DIR = Path(__file__).with_name("vendor")
_READER_OVERRIDES = """
/* ===== tokens: classic Chinese book-page reading =====
   Light = rice-paper ground, ink text, ochre/seal accents.
   Dark  = midnight ink ground, warm paper-text, amber accents.
   Components reference tokens only — never literals inside media blocks. */
:root {
  --paper: #FBF6EC;
  --paper-deep: #F4ECDB;
  --ink: #2B2723;
  --ink-soft: #6E6454;
  --seal: #A63A2B;
  --seal-text: #FBF6EC;
  --rule: #E0D5BC;
  --code-bg: #F2EADA;
  --bg: var(--paper);
  --text: var(--ink);
  --text-light: var(--ink-soft);
  --border: var(--rule);
  --accent-bg: var(--paper-deep);
  --accent: var(--seal);
  --link: #8A4B26;
  --sans-font: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC", system-ui, sans-serif;
  --serif-font: "Songti SC", "Noto Serif SC", "Source Han Serif SC", STSong, SimSun, Georgia, serif;
  --mono-font: Consolas, "Cascadia Code", "Noto Sans Mono CJK SC", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #1B1916;
    --paper-deep: #252119;
    --ink: #E8E0CF;
    --ink-soft: #A79E8A;
    --seal: #C96A52;
    --seal-text: #1B1916;
    --rule: #3B352A;
    --code-bg: #272218;
    --bg: var(--paper);
    --text: var(--ink);
    --text-light: var(--ink-soft);
    --border: var(--rule);
    --accent-bg: var(--paper-deep);
    --accent: var(--seal);
    --link: #C9A06B;
  }
}

/* ===== page ===== */
body {
  grid-template-columns: 1fr min(38em, calc(100% - 3rem)) 1fr;
  font-family: var(--serif-font);
  font-size: 18px;
  line-height: 1.95;
  background: var(--bg);
  color: var(--text);
}

/* ===== source bar ===== */
body > header.reader-bar {
  background: var(--paper-deep);
  border-bottom: 1px solid var(--rule);
  padding: .9rem 0;
}
.reader-meta {
  align-items: center;
  display: flex;
  gap: .8rem;
  margin: 0 auto;
  max-width: 38em;
  min-width: 0;
  padding: 0 1.5rem;
}
.reader-badge {
  align-items: center;
  background: var(--seal);
  color: var(--seal-text);
  display: inline-flex;
  font-family: var(--sans-font);
  font-size: .78rem;
  font-weight: 700;
  gap: .35rem;
  letter-spacing: .14em;
  line-height: 1;
  padding: .38rem .6rem;
  white-space: nowrap;
}
.reader-badge::before {
  content: "文";
  font-family: var(--serif-font);
  font-size: .85rem;
  font-weight: 400;
}
.reader-domain {
  color: var(--text-light);
  font-family: var(--sans-font);
  font-size: .82rem;
  letter-spacing: .04em;
  overflow-wrap: anywhere;
}
.reader-source-link {
  color: var(--link);
  font-family: var(--sans-font);
  font-size: .82rem;
  margin-inline-start: auto;
  text-decoration: none;
  white-space: nowrap;
}
.reader-source-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

/* ===== body ===== */
.reader-main {
  min-width: 0;
  padding-top: 2.4rem;
}
.reader-main article {
  border: 0;
  margin: 0;
  padding: 0;
}
.reader-main section {
  border: 0;
  margin: 2.6rem 0;
  padding: 0;
}
.reader-main h1:first-child {
  margin-top: .2rem;
}
.reader-main h1,
.reader-main h2,
.reader-main h3,
.reader-main h4 {
  font-family: var(--serif-font);
  font-weight: 700;
  letter-spacing: .03em;
  line-height: 1.45;
  text-wrap: balance;
}
.reader-main h1 {
  font-size: 1.7rem;
  padding-bottom: .7rem;
  position: relative;
}
.reader-main h1::after {
  background: var(--seal);
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  top: 100%;
  width: 3.2rem;
}
.reader-main h2 {
  font-size: 1.3rem;
  margin-top: 2.4rem;
}
.reader-main h3 {
  font-size: 1.12rem;
}
.reader-main p {
  margin: 1.05em 0;
}
.reader-main a {
  color: var(--link);
  overflow-wrap: anywhere;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.reader-main img {
  border-radius: 2px;
  box-shadow: 0 8px 28px rgb(0 0 0 / 14%);
  display: block;
  margin: 1.9rem auto;
  max-width: 100%;
}
.reader-main blockquote {
  border-left: 3px solid var(--seal);
  color: var(--text-light);
  font-style: normal;
  margin: 1.4rem 0;
  padding: .1rem 1.1rem;
}
.reader-main code,
.reader-footer code {
  background: var(--code-bg);
  border-radius: 3px;
  font-family: var(--mono-font);
  font-size: .88em;
  padding: .12em .4em;
}
.reader-main pre {
  background: var(--code-bg);
  border: 1px solid var(--rule);
  border-radius: 4px;
  font-family: var(--mono-font);
  font-size: .88em;
  line-height: 1.7;
  overflow-x: auto;
  padding: 1rem 1.1rem;
}
.reader-main pre code {
  background: transparent;
  padding: 0;
}
.reader-main table {
  display: block;
  font-family: var(--sans-font);
  font-size: .92em;
  max-width: 100%;
  overflow-x: auto;
}
.reader-main th {
  background: var(--paper-deep);
  font-weight: 700;
}
.reader-image-missing {
  background: var(--paper-deep);
  border: 1px dashed var(--rule);
  color: var(--text-light);
  display: block;
  font-family: var(--sans-font);
  font-size: .88rem;
  margin: 1.75rem 0;
  padding: .9rem 1.1rem;
  text-align: center;
}
.reader-empty {
  background: var(--paper-deep);
  border: 1px solid var(--rule);
  border-radius: 4px;
  padding: 1.1rem 1.3rem;
}

/* ===== footer ===== */
.reader-footer {
  border-top: 1px solid var(--rule);
  margin-top: 3.2rem;
  padding-top: 1.1rem;
}
.reader-footer p {
  color: var(--text-light);
  font-family: var(--sans-font);
  font-size: .82rem;
  margin: .35rem auto;
  max-width: 38em;
  padding: 0 1.5rem;
}

@media (prefers-color-scheme: dark) {
  .reader-main img { box-shadow: 0 6px 24px rgb(0 0 0 / 45%); }
}
@media only screen and (width <= 720px) {
  body {
    grid-template-columns: 1fr min(38em, calc(100% - 1.4rem)) 1fr;
    font-size: 16.5px;
    line-height: 1.85;
  }
  .reader-meta, .reader-footer p { padding: 0 .7rem; }
  .reader-domain { display: none; }
  .reader-main { padding-top: 1.6rem; }
}
@media print {
  body > header.reader-bar {
    background: transparent;
    border-bottom: 1px solid #bbb;
    padding: 0 0 .6rem;
  }
  .reader-source-link { display: none; }
  .reader-main { padding-top: .6rem; }
}
""".strip()


@dataclass(frozen=True, slots=True)
class MaterializerConfig:
    """Real fetch bound for one HTML response, not a model-reading budget."""

    max_html_bytes: int = MAX_HTML_BYTES

    def __post_init__(self) -> None:
        if int(self.max_html_bytes) <= 0:
            raise ValueError("max_html_bytes must be positive")


WebMaterializerConfig = MaterializerConfig


@dataclass(frozen=True, slots=True)
class _ResponseView:
    body: bytes
    url: str
    media_type: str
    status: int
    redirect_count: int


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _safe_http_url(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise DomainError("NETWORK_BLOCKED", f"{label} 不是有效的 HTTP(S) 地址")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise DomainError("NETWORK_BLOCKED", f"{label} 不是有效的 HTTP(S) 地址") from exc
    if parsed.scheme.casefold() not in _HTTP_SCHEMES or not hostname or parsed.username or parsed.password:
        raise DomainError("NETWORK_BLOCKED", f"{label} 未通过 HTTP(S) 地址策略")
    if port is not None and not 1 <= port <= 65535:
        raise DomainError("NETWORK_BLOCKED", f"{label} 端口无效")
    return value


def _response_view(response: FetchResult, requested_url: str, max_bytes: int) -> _ResponseView:
    if not isinstance(response, FetchResult) or not isinstance(response.body, bytes):
        raise DomainError("CONTENT_VALIDATION_FAILED", "fetcher 返回了无效响应")
    if len(response.body) > max_bytes:
        raise DomainError("DOWNLOAD_TOO_LARGE", "网页响应超过配置的获取上限")
    return _ResponseView(
        body=response.body,
        url=_safe_http_url(response.final_url or requested_url, label="最终地址"),
        media_type=str(response.media_type or "").split(";", 1)[0].strip().casefold(),
        status=int(response.status),
        redirect_count=int(getattr(response, "redirect_count", 0) or 0),
    )


def _is_html_response(response: _ResponseView) -> bool:
    if response.media_type in {"text/html", "application/xhtml+xml", "text/plain", ""}:
        return True
    if response.media_type == "application/octet-stream":
        sample = response.body[:512].lstrip().casefold()
        return sample.startswith((b"<!doctype html", b"<html", b"<body", b"<article", b"<main"))
    return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes, root: Path) -> None:
    ensure_within_root(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _check_cancel(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DomainError("JOB_CANCELLED", "任务已取消")


def _reader_css() -> str:
    """Load the vendored MIT theme and keep its license inside generated HTML."""

    try:
        base_css = (_VENDOR_DIR / "simple.min.css").read_text(encoding="utf-8")
        license_text = (_VENDOR_DIR / "SIMPLE_CSS_LICENSE.txt").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DomainError("WEB_TEMPLATE_UNAVAILABLE", "网页 Reader 主题文件缺失") from exc
    notice = (
        f"/* Reader base theme: {_READER_THEME} {_READER_THEME_VERSION}\n"
        f"{license_text}\n*/"
    )
    return f"{notice}\n{base_css}\n{_READER_OVERRIDES}\n"


def _cleaned_body(fragment: str) -> str:
    """Take Trafilatura's cleaned body while discarding its document wrapper."""

    extracted = fragment.strip()
    if not extracted:
        return ""
    soup = BeautifulSoup(extracted, "html.parser")
    container = soup.body if soup.body is not None else soup
    return "".join(str(node) for node in container.contents).strip()


def _image_data_url(body: bytes, media_type: str) -> str:
    payload = base64.b64encode(body).decode("ascii")
    return f"data:{media_type};base64,{payload}"


def _wait_before_image_retry(delay: float, cancel_event: Any) -> None:
    deadline = time.monotonic() + delay
    while True:
        _check_cancel(cancel_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _fetch_image_data_url(
    fetcher: Any,
    source_url: str,
    cancel_event: Any,
) -> tuple[str | None, int]:
    fetch_image = getattr(fetcher, "fetch_image", None)
    if not callable(fetch_image):
        return None, 0
    attempts = 0
    for attempt in range(_IMAGE_FETCH_ATTEMPTS):
        attempts += 1
        try:
            response, image_format = fetch_image(
                source_url,
                cancel_event=cancel_event,
            )
            return _image_data_url(response.body, image_format.media_type), attempts
        except DomainError as exc:
            if exc.code == "JOB_CANCELLED":
                raise
            if not exc.retryable or attempt + 1 >= _IMAGE_FETCH_ATTEMPTS:
                return None, attempts
            _wait_before_image_retry(0.5 * (2**attempt), cancel_event)
    return None, attempts


def _embed_reader_images(
    fragment: str,
    *,
    source_url: str,
    fetcher: Any,
    cancel_event: Any,
) -> tuple[str, int, int, int]:
    """Embed cleaned raster images and remove every remote responsive source."""

    extracted = fragment.strip()
    if not extracted:
        return "", 0, 0, 0
    soup = BeautifulSoup(extracted, "html.parser")
    cache: dict[str, str | None] = {}
    embedded = 0
    failed = 0
    requests = 0

    # A remote ``source`` can override the embedded ``img`` inside ``picture``.
    # Trafilatura has already selected the readable body, so retain the fallback
    # image and remove alternate network candidates.
    for source in soup.find_all("source"):
        source.decompose()

    for image in list(soup.find_all("img")):
        _check_cancel(cancel_event)
        raw_source = next(
            (
                str(image.get(name) or "").strip()
                for name in ("src", "data-src", "data-original")
                if str(image.get(name) or "").strip()
            ),
            "",
        )
        for name in ("srcset", "data-src", "data-srcset", "data-original"):
            image.attrs.pop(name, None)

        if raw_source.casefold().startswith(
            (
                "data:image/jpeg;base64,",
                "data:image/png;base64,",
                "data:image/gif;base64,",
                "data:image/webp;base64,",
            )
        ):
            image["src"] = raw_source
            embedded += 1
            continue

        resolved = urljoin(source_url, raw_source) if raw_source else ""
        if resolved not in cache:
            data_url, attempts = _fetch_image_data_url(
                fetcher,
                resolved,
                cancel_event,
            )
            requests += attempts
            cache[resolved] = data_url

        data_url = cache[resolved]
        if data_url is not None:
            image["src"] = data_url
            embedded += 1
            continue

        failed += 1
        placeholder = soup.new_tag("span")
        placeholder["class"] = "reader-image-missing"
        alt = str(image.get("alt") or "").strip()
        placeholder.string = f"图片未能离线保存{f'：{alt}' if alt else ''}"
        image.replace_with(placeholder)

    container = soup.body if soup.body is not None else soup
    return (
        "".join(str(node) for node in container.contents).strip(),
        embedded,
        failed,
        requests,
    )


def _readable_document(
    fragment: str,
    *,
    title: str,
    source_url: str,
    generated_at: str = "",
) -> str:
    """Render cleaned Trafilatura HTML inside the stable Reader shell."""

    safe_title = html_module.escape(title or "教育资源", quote=False)
    safe_url = html_module.escape(source_url, quote=True)
    hostname = urlsplit(source_url).hostname or source_url
    safe_hostname = html_module.escape(hostname, quote=False)
    safe_generated = html_module.escape(generated_at, quote=False)
    content = _cleaned_body(fragment)
    if not content:
        content = (
            '<div class="reader-empty">'
            "<p>正文抽取未得到可读内容；原始 HTML 已完整保存为 "
            "<code>source.html</code>。</p>"
            f'<p>来源：<a href="{safe_url}">{safe_url}</a></p>'
            "</div>"
        )
    csp = (
        "default-src 'none'; img-src 'self' data:; "
        "style-src 'unsafe-inline'; script-src 'none'; object-src 'none'; "
        "frame-src 'none'; base-uri 'none'; form-action 'none'"
    )
    return (
        '<!doctype html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{html_module.escape(csp, quote=True)}">\n'
        f"<title>{safe_title}</title>\n"
        "<!--\n"
        f"  来源: {safe_url}\n"
        f"  生成: {safe_generated}\n"
        f"  模板: {_READER_TEMPLATE} ({_READER_THEME} {_READER_THEME_VERSION})\n"
        "  本文件为自包含离线阅读页；原始响应见同目录 source.html。\n"
        "-->\n"
        "<style>\n"
        f"{_reader_css()}"
        "</style>\n"
        "</head>\n<body>\n"
        '<header class="reader-bar">\n'
        '<div class="reader-meta">\n'
        '<span class="reader-badge">网页资料</span>\n'
        f'<span class="reader-domain">{safe_hostname}</span>\n'
        f'<a class="reader-source-link" href="{safe_url}">原网页</a>\n'
        "</div>\n</header>\n"
        '<main class="reader-main" id="content">\n'
        f"{content}\n"
        "</main>\n"
        '<footer class="reader-footer">\n'
        "<p>由网页正文清洗结果生成 · 本文件可离线独立打开 · 原始响应保存在 "
        "<code>source.html</code></p>\n"
        "</footer>\n"
        "</body>\n</html>\n"
    )


def _artifact(
    request: Any,
    index: int,
    path: Path,
    media_type: str,
    role: str,
    primary: bool,
) -> Artifact:
    data = path.read_bytes()
    filename = path.name
    seed = f"{request.job_id}:{filename}:{index}".encode("utf-8")
    return Artifact(
        artifact_id=f"artifact_{hashlib.sha256(seed).hexdigest()[:24]}_{index:03d}",
        role=role,
        path=path.resolve(),
        filename=filename,
        byte_size=len(data),
        media_type=media_type,
        sha256=_sha256(data),
        primary=primary,
    )


class WebMaterializer:
    """Save fetched HTML first, then derive readable views with Trafilatura."""

    def __init__(
        self,
        fetcher: BoundedWebFetcher | None = None,
        settings: Any = None,
        config: MaterializerConfig | None = None,
    ) -> None:
        self.settings = settings
        self.config = config or MaterializerConfig()
        self.timeout_seconds = float(
            _value(settings, "download_timeout_seconds", 30) if settings is not None else 30
        )
        self.fetcher = fetcher or BoundedWebFetcher(
            timeout_seconds=self.timeout_seconds,
            max_bytes=self.config.max_html_bytes,
        )

    def __call__(self, request: Any) -> Any:
        return self.acquire(request)

    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult:
        return self.acquire(request)

    def _fetch_html(self, url: str, cancel_event: Any) -> FetchResult:
        fetcher = self.fetcher
        if hasattr(fetcher, "fetch_html"):
            return fetcher.fetch_html(url, cancel_event=cancel_event)
        if hasattr(fetcher, "fetch"):
            return fetcher.fetch(
                url,
                accept="text/html,application/xhtml+xml",
                cancel_event=cancel_event,
            )
        raise DomainError("WEB_FETCH_UNAVAILABLE", "网页 fetcher 不支持 HTML 获取")

    def acquire(self, request: Any) -> AcquisitionResult:
        cancel_event = request.cancel_event
        _check_cancel(cancel_event)
        if not _JOB_ID_RE.fullmatch(request.job_id):
            raise DomainError("INVALID_ARGUMENT", "任务 ID 无效")
        jobs_root = request.jobs_root.resolve()
        job_dir = ensure_within_root(jobs_root / request.job_id, jobs_root)
        job_dir.mkdir(parents=True, exist_ok=True)

        resource = request.mutable_resource()
        source_url = _safe_http_url(resource.get("source_url"), label="资源来源")
        response = _response_view(
            self._fetch_html(source_url, cancel_event),
            source_url,
            self.config.max_html_bytes,
        )
        if response.status in {401, 403}:
            raise DomainError("AUTH_REQUIRED", "网页需要授权才能获取")
        if response.status in {404, 410}:
            raise DomainError("RESOURCE_NOT_FOUND", "网页资源不存在")
        if response.status >= 400:
            raise DomainError(
                "WEB_FETCH_FAILED",
                f"网页请求失败：HTTP {response.status}",
                retryable=response.status >= 500,
            )
        if not _is_html_response(response):
            raise DomainError("CONTENT_VALIDATION_FAILED", "资源响应不是 HTML")

        _check_cancel(cancel_event)
        warnings: list[str] = []
        extraction_status = "succeeded"
        try:
            markdown = trafilatura_extract(
                response.body,
                url=response.url,
                output_format="markdown",
                include_comments=False,
                include_tables=True,
                include_images=True,
                include_links=True,
            ) or ""
            readable_fragment = trafilatura_extract(
                response.body,
                url=response.url,
                output_format="html",
                include_comments=False,
                include_tables=True,
                include_images=True,
                include_links=True,
            ) or ""
        except Exception:
            markdown = ""
            readable_fragment = ""
            extraction_status = "source_only"
            warnings.append("content_extraction_failed")
        if not markdown.strip() and not readable_fragment.strip():
            extraction_status = "source_only"
            if "content_extraction_failed" not in warnings:
                warnings.append("content_extraction_empty")

        readable_fragment, embedded_images, failed_images, image_fetches = (
            _embed_reader_images(
                readable_fragment,
                source_url=response.url,
                fetcher=self.fetcher,
                cancel_event=cancel_event,
            )
        )
        if failed_images:
            warnings.append("image_embedding_incomplete")

        title = str(resource.get("title") or "教育资源")
        if not markdown.strip():
            markdown = (
                f"# {title}\n\n"
                "正文抽取未得到可读内容；原始 HTML 已保存为 `source.html`。\n\n"
                f"来源：{response.url}\n"
            )
        generated_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        readable = _readable_document(
            readable_fragment,
            title=title,
            source_url=response.url,
            generated_at=generated_at,
        )
        metadata = {
            "schema_version": "web-materialization-v2",
            "source_url": response.url,
            "source_snapshot": "source.html",
            "source_bytes": len(response.body),
            "source_media_type": response.media_type or "text/html",
            "http_status": response.status,
            "redirect_count": response.redirect_count,
            "extractor": "trafilatura",
            "extraction_status": extraction_status,
            "reader_template": _READER_TEMPLATE,
            "reader_theme": f"{_READER_THEME} {_READER_THEME_VERSION}",
            "reader_css_embedded": True,
            "reader_images_embedded": failed_images == 0,
            "embedded_image_count": embedded_images,
            "failed_image_count": failed_images,
            "image_fetch_count": image_fetches,
            "links_requested": True,
            "images_requested": True,
            "warnings": warnings,
        }
        files = {
            "source.html": response.body,
            "index.html": readable.encode("utf-8"),
            "content.md": markdown.encode("utf-8"),
            "metadata.json": (
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
        }

        try:
            for filename, data in files.items():
                _check_cancel(cancel_event)
                _write(job_dir / filename, data, job_dir)
        except Exception:
            for filename in files:
                (job_dir / filename).unlink(missing_ok=True)
            raise

        specs = [
            ("index.html", "text/html", "primary", True),
            ("source.html", "text/html", "attachment", False),
            ("content.md", "text/markdown", "markdown", False),
            ("metadata.json", "application/json", "metadata", False),
        ]
        artifacts = tuple(
            _artifact(request, index, job_dir / filename, media_type, role, primary)
            for index, (filename, media_type, role, primary) in enumerate(specs)
        )
        return AcquisitionResult.success(
            AcquisitionStrategy.WEB_MATERIALIZE,
            ArtifactBundle(artifacts),
            warnings=tuple(warnings),
            metadata={
                "provider": "static_web",
                "extractor": "trafilatura",
                "source_snapshot": "source.html",
                "extraction_status": extraction_status,
                "reader_template": _READER_TEMPLATE,
                "reader_theme": f"{_READER_THEME} {_READER_THEME_VERSION}",
                "reader_images_embedded": failed_images == 0,
                "embedded_image_count": embedded_images,
                "failed_image_count": failed_images,
            },
            completion=(
                "complete"
                if extraction_status == "succeeded" and failed_images == 0
                else "partial"
            ),
        )


__all__ = [
    "MAX_HTML_BYTES",
    "MaterializerConfig",
    "WebMaterializer",
    "WebMaterializerConfig",
]
