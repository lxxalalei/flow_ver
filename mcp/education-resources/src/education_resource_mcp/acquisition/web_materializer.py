"""Static web materialization with source preservation and mature extraction.

The fetch layer owns network policy. This module saves the fetched HTML response
unchanged as ``source.html`` and then uses Trafilatura to derive readable HTML
and Markdown. Extraction is a derivative view: failure to extract readable text
does not erase or truncate the successfully fetched source snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import html as html_module
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
import zipfile

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


def _zip_bytes(files: Mapping[str, bytes], *, cancel_event: Any = None) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(files):
            _check_cancel(cancel_event)
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _readable_document(fragment: str, *, title: str, source_url: str) -> str:
    """Return Trafilatura's complete HTML document, or a small fallback page."""

    extracted = fragment.strip()
    if extracted:
        if extracted.casefold().startswith("<html"):
            return f"<!doctype html>\n{extracted}\n"
        return f"{extracted}\n"

    safe_title = html_module.escape(title or "教育资源", quote=False)
    safe_url = html_module.escape(source_url, quote=True)
    body = (
        "<p>正文抽取未得到可读内容；原始 HTML 已完整保存为 "
        "<code>source.html</code>。</p>"
        f'<p>来源：<a href="{safe_url}">{safe_url}</a></p>'
    )
    csp = (
        "default-src 'none'; img-src http: https: data:; style-src 'none'; "
        "script-src 'none'; object-src 'none'; frame-src 'none'; "
        "base-uri 'none'; form-action 'none'"
    )
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f'<meta http-equiv="Content-Security-Policy" content="{html_module.escape(csp, quote=True)}">\n'
        f"<title>{safe_title}</title>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
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
        self.fetcher = fetcher
        self.settings = settings
        self.config = config or MaterializerConfig()
        self.timeout_seconds = float(
            _value(settings, "download_timeout_seconds", 30) if settings is not None else 30
        )

    def __call__(self, request: Any) -> Any:
        return self.acquire(request)

    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult:
        return self.acquire(request)

    def _fetch_html(self, url: str, cancel_event: Any) -> FetchResult:
        fetcher = self.fetcher or BoundedWebFetcher(
            timeout_seconds=self.timeout_seconds,
            max_bytes=self.config.max_html_bytes,
        )
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

        title = str(resource.get("title") or "教育资源")
        if not markdown.strip():
            markdown = (
                f"# {title}\n\n"
                "正文抽取未得到可读内容；原始 HTML 已保存为 `source.html`。\n\n"
                f"来源：{response.url}\n"
            )
        readable = _readable_document(
            readable_fragment,
            title=title,
            source_url=response.url,
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
        files["webbundle.zip"] = _zip_bytes(files, cancel_event=cancel_event)

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
            ("webbundle.zip", "application/zip", "bundle", False),
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
            },
            completion="complete" if extraction_status == "succeeded" else "partial",
        )


__all__ = [
    "MAX_HTML_BYTES",
    "MaterializerConfig",
    "WebMaterializer",
    "WebMaterializerConfig",
]
