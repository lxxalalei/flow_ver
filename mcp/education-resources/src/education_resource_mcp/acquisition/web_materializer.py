"""Static web-page materialization into a safe, portable resource bundle.

The materializer is intentionally HTTP-client agnostic. A bounded fetcher is
injected by the acquisition layer, so redirect, DNS, timeout, and response
limits remain owned by one network policy implementation. This module owns
the second half of the boundary: same-origin image selection, Block IR
rendering, server-controlled output paths, and deterministic packaging.

The user-facing primary artifact is a standalone sanitized HTML document.
Markdown, metadata, downloaded images, and a deterministic ZIP remain job
artifacts so later extraction work can evolve without changing the archive
contract.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import html as html_module
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin, urlsplit
import zipfile

from ..errors import DomainError
from ..policy import ensure_within_root
from .models import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
)
from .web_fetch import BoundedWebFetcher, FetchResult, ImageFormat
from .web_blocks import (
    BlockExtractionError,
    BlockIR,
    BlockLimits,
    block_to_mapping,
    extract_block_ir,
)


MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_IMAGE_COUNT = 32
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_HTTP_SCHEMES = frozenset({"http", "https"})
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/gif": (b"GIF8", ".gif"),
    "image/webp": (b"RIFF", ".webp"),
}
_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
}


@dataclass(frozen=True, slots=True)
class MaterializerConfig:
    """Bounds for static extraction and output packaging."""

    max_html_bytes: int = MAX_HTML_BYTES
    max_image_count: int = MAX_IMAGE_COUNT
    max_images: int | None = None
    max_image_bytes: int = MAX_IMAGE_BYTES
    max_total_image_bytes: int = MAX_TOTAL_IMAGE_BYTES
    max_dom_nodes: int = 50_000
    max_dom_depth: int = 128
    max_text_chars: int = 1_000_000
    max_blocks: int = 4_096

    def __post_init__(self) -> None:
        effective_images = self.max_image_count if self.max_images is None else self.max_images
        if effective_images <= 0:
            raise ValueError("max_image_count must be positive")
        object.__setattr__(self, "max_image_count", int(effective_images))
        for name in (
            "max_html_bytes",
            "max_image_bytes",
            "max_total_image_bytes",
            "max_dom_nodes",
            "max_dom_depth",
            "max_text_chars",
            "max_blocks",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")


WebMaterializerConfig = MaterializerConfig


@dataclass(frozen=True, slots=True)
class _ResponseView:
    body: bytes
    url: str
    media_type: str
    status: int


@dataclass(frozen=True, slots=True)
class _ImageAsset:
    relative_path: str
    media_type: str
    data: bytes


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _resource_from_request(request: Any) -> Any:
    resource = _value(request, "resource")
    if resource is None:
        resource = _value(request, "resource_record")
    return resource if resource is not None else {}


def _config_value(config: Any, settings: Any, names: tuple[str, ...], default: Any) -> Any:
    for source in (config, settings):
        if source is None:
            continue
        for name in names:
            value = _value(source, name)
            if value is not None:
                return value
    return default


def _make_config(config: Any, settings: Any) -> MaterializerConfig:
    if config is None and settings is None:
        return MaterializerConfig()
    return MaterializerConfig(
        max_html_bytes=int(
            _config_value(config, settings, ("max_html_bytes", "web_max_html_bytes"), MAX_HTML_BYTES)
        ),
        max_image_count=int(
            _config_value(
                config,
                settings,
                ("max_image_count", "max_images", "web_max_images"),
                MAX_IMAGE_COUNT,
            )
        ),
        max_image_bytes=int(
            _config_value(config, settings, ("max_image_bytes", "web_max_image_bytes"), MAX_IMAGE_BYTES)
        ),
        max_total_image_bytes=int(
            _config_value(
                config,
                settings,
                ("max_total_image_bytes", "web_max_total_image_bytes"),
                MAX_TOTAL_IMAGE_BYTES,
            )
        ),
        max_dom_nodes=int(
            _config_value(config, settings, ("max_dom_nodes", "web_max_dom_nodes"), 50_000)
        ),
        max_dom_depth=int(
            _config_value(config, settings, ("max_dom_depth", "web_max_dom_depth"), 128)
        ),
        max_text_chars=int(
            _config_value(config, settings, ("max_text_chars", "web_max_text_chars"), 1_000_000)
        ),
        max_blocks=int(
            _config_value(config, settings, ("max_blocks", "web_max_blocks"), 4_096)
        ),
    )


def _safe_http_url(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise DomainError("NETWORK_BLOCKED", f"{label} 不是有效的 HTTP(S) 地址")
    if any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value):
        raise DomainError("NETWORK_BLOCKED", f"{label} 包含非法字符")
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


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(_safe_http_url(value, label="地址"))
    assert parsed.hostname is not None
    try:
        host = parsed.hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise DomainError("NETWORK_BLOCKED", "地址主机名无效") from exc
    default_port = 443 if parsed.scheme.casefold() == "https" else 80
    return parsed.scheme.casefold(), host, parsed.port or default_port


def _relative_path(path: Path, root: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise DomainError("POLICY_DENIED", "物化输出路径越过任务目录") from exc
    value = relative.as_posix()
    if not value or value.startswith("/") or ".." in value.split("/"):
        raise DomainError("POLICY_DENIED", "物化输出包含非法相对路径")
    return value


def _response_view(response: FetchResult, requested_url: str, max_bytes: int) -> _ResponseView:
    if not isinstance(response, FetchResult):
        raise DomainError("CONTENT_VALIDATION_FAILED", "fetcher 返回了无效的 FetchResult")
    payload = response.body
    if not isinstance(payload, bytes):
        raise DomainError("CONTENT_VALIDATION_FAILED", "fetcher 返回了无效的响应内容")
    if len(payload) > max_bytes:
        raise DomainError("DOWNLOAD_TOO_LARGE", "响应超过物化大小上限")
    return _ResponseView(
        body=payload,
        url=_safe_http_url(response.final_url or requested_url, label="最终地址"),
        media_type=str(response.media_type or "").split(";", 1)[0].strip().casefold(),
        status=int(response.status),
    )


def _is_html_response(response: _ResponseView) -> bool:
    if response.media_type in {"text/html", "application/xhtml+xml", "text/plain", ""}:
        return True
    if response.media_type == "application/octet-stream":
        sample = response.body[:512].lstrip().casefold()
        return sample.startswith((b"<!doctype html", b"<html", b"<body", b"<article"))
    return False


def _normalise_media_type(value: Any) -> str:
    candidate = str(value or "").split(";", 1)[0].strip().casefold()
    return _MIME_ALIASES.get(candidate, candidate)


def _image_signature(data: bytes, declared: str) -> tuple[str, str] | None:
    mime = _normalise_media_type(declared)
    if mime == "image/svg+xml" or mime == "image/x-icon":
        return None
    if mime in _ALLOWED_IMAGE_TYPES:
        signature, suffix = _ALLOWED_IMAGE_TYPES[mime]
        if mime == "image/webp":
            if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
                return None
        elif not data.startswith(signature):
            return None
        return mime, suffix
    for candidate, (signature, suffix) in _ALLOWED_IMAGE_TYPES.items():
        if candidate == "image/webp":
            if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                return candidate, suffix
        elif data.startswith(signature):
            return candidate, suffix
    return None


def _escape_text(value: str) -> str:
    return html_module.escape(value, quote=False)


def _markdown_text(value: str) -> str:
    value = html_module.escape(value, quote=False)
    value = value.replace("\\", "\\\\")
    value = value.replace("`", "\\`")
    return value


def _markdown_cell(value: str) -> str:
    return _markdown_text(value).replace("|", "\\|").replace("\n", " ")


def _code_fence(value: str) -> str:
    runs = [len(match.group(0)) for match in re.finditer(r"`+", value)]
    return "`" * max(3, (max(runs) + 1) if runs else 3)


def render_markdown(ir: BlockIR, image_paths: Mapping[int, str] | None = None) -> str:
    """Render only the safe IR as deterministic Markdown."""

    paths = image_paths or {}
    output: list[str] = []
    for index, block in enumerate(ir.blocks):
        if block.kind == "heading":
            output.append(f"{'#' * block.level} {_markdown_text(block.text)}")
        elif block.kind == "paragraph":
            output.append(_markdown_text(block.text))
        elif block.kind == "list":
            for item_index, item in enumerate(block.items, start=1):
                marker = f"{item_index}." if block.ordered else "-"
                output.append(f"{marker} {_markdown_text(item)}")
        elif block.kind == "quote":
            lines = block.text.splitlines() or [block.text]
            output.extend(f"> {_markdown_text(line)}" for line in lines)
        elif block.kind == "code":
            fence = _code_fence(block.text)
            language = re.sub(r"[^A-Za-z0-9_+-]", "", block.language)[:32]
            output.append(f"{fence}{language}\n{_markdown_text(block.text)}\n{fence}")
        elif block.kind == "table":
            rows = [tuple(_markdown_cell(cell) for cell in row) for row in block.rows]
            if rows:
                width = max(len(row) for row in rows)
                padded = [row + ("",) * (width - len(row)) for row in rows]
                output.append("| " + " | ".join(padded[0]) + " |")
                output.append("| " + " | ".join("---" for _ in range(width)) + " |")
                output.extend("| " + " | ".join(row) + " |" for row in padded[1:])
        elif block.kind == "image":
            path = paths.get(index)
            if path:
                output.append(f"![{_markdown_text(block.alt)}]({path})")
            else:
                output.append("[图片未能安全加载]")
        elif block.kind == "linebreak":
            output.append("  ")
        elif block.kind == "placeholder":
            output.append(f"[{_markdown_text(block.text)}]")
    return "\n\n".join(output).rstrip() + "\n"


def _html_attrs(**values: str) -> str:
    return " ".join(
        f'{name}="{html_module.escape(value, quote=True)}"'
        for name, value in values.items()
        if value
    )


def render_sanitized_html(ir: BlockIR, image_paths: Mapping[int, str] | None = None) -> str:
    """Render a fresh HTML document with no source markup or active content."""

    paths = image_paths or {}
    body: list[str] = []
    for index, block in enumerate(ir.blocks):
        if block.kind == "heading":
            body.append(f"<h{block.level}>{_escape_text(block.text)}</h{block.level}>")
        elif block.kind == "paragraph":
            body.append(f"<p>{_escape_text(block.text)}</p>")
        elif block.kind == "list":
            tag = "ol" if block.ordered else "ul"
            items = "".join(f"<li>{_escape_text(item)}</li>" for item in block.items)
            body.append(f"<{tag}>{items}</{tag}>")
        elif block.kind == "quote":
            body.append(f"<blockquote>{_escape_text(block.text).replace(chr(10), '<br>')}</blockquote>")
        elif block.kind == "code":
            language = re.sub(r"[^A-Za-z0-9_+-]", "", block.language)[:32]
            class_attr = f' class="language-{html_module.escape(language, quote=True)}"' if language else ""
            body.append(f"<pre><code{class_attr}>{_escape_text(block.text)}</code></pre>")
        elif block.kind == "table":
            if block.rows:
                rows = list(block.rows)
                head = rows[0]
                head_html = "".join(f"<th>{_escape_text(cell)}</th>" for cell in head)
                rest_html = "".join(
                    "<tr>" + "".join(f"<td>{_escape_text(cell)}</td>" for cell in row) + "</tr>"
                    for row in rows[1:]
                )
                body.append(f"<table><thead><tr>{head_html}</tr></thead><tbody>{rest_html}</tbody></table>")
        elif block.kind == "image":
            path = paths.get(index)
            if path:
                attrs = _html_attrs(src=path, alt=block.alt)
                body.append(f"<figure><img {attrs} loading=\"lazy\"></figure>")
            else:
                body.append("<p class=\"placeholder\">图片未能安全加载</p>")
        elif block.kind == "linebreak":
            body.append("<br>")
        elif block.kind == "placeholder":
            body.append(f"<p class=\"placeholder\">{_escape_text(block.text)}</p>")
    title = _escape_text(ir.title or "教育资源")
    csp = "default-src 'none'; img-src 'self' data:; style-src 'none'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f'  <meta http-equiv="Content-Security-Policy" content="{html_module.escape(csp, quote=True)}">\n'
        f"  <title>{title}</title>\n"
        "</head>\n"
        "<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_output(path: Path, data: bytes, job_dir: Path) -> None:
    ensure_within_root(path, job_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _check_cancel(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DomainError("JOB_CANCELLED", "任务已取消")


def _zip_bytes(
    files: Mapping[str, bytes], *, cancel_event: Any = None
) -> bytes:
    """Create a byte-for-byte deterministic ZIP from relative bundle files."""

    from io import BytesIO

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
            if not name or name.startswith("/") or ".." in name.split("/"):
                raise DomainError("POLICY_DENIED", "ZIP 条目包含非法相对路径")
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _artifact(
    *,
    request: Any,
    index: int,
    path: Path,
    byte_size: int,
    media_type: str,
    sha256: str,
    filename: str,
    role: str,
    primary: bool,
) -> Artifact:
    artifact_seed = f"{request.job_id}:{filename}:{index}".encode("utf-8")
    return Artifact(
        artifact_id=f"artifact_{hashlib.sha256(artifact_seed).hexdigest()[:24]}_{index:03d}",
        role=role,  # type: ignore[arg-type]
        path=path.resolve(),
        filename=filename,
        byte_size=byte_size,
        media_type=media_type,
        sha256=sha256,
        primary=primary,
    )


class WebMaterializer:
    """Materialize a statically fetchable web page into portable artifacts."""

    def __init__(
        self,
        fetcher: BoundedWebFetcher | None = None,
        settings: Any = None,
        config: Any = None,
    ) -> None:
        self.fetcher = fetcher
        self.settings = settings
        self.config = _make_config(config, settings)
        self.timeout_seconds = float(
            _value(settings, "download_timeout_seconds", 30) if settings is not None else 30
        )

    def __call__(self, request: Any) -> Any:
        return self.acquire(request)

    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult:
        return self.acquire(request)

    def _fetcher_for(self, max_bytes: int) -> BoundedWebFetcher | Any:
        if self.fetcher is not None:
            return self.fetcher
        return BoundedWebFetcher(
            timeout_seconds=self.timeout_seconds,
            max_bytes=min(self.config.max_html_bytes, max_bytes),
        )

    def _fetch_html(self, url: str, *, max_bytes: int, cancel_event: Any) -> FetchResult:
        fetcher = self._fetcher_for(max_bytes)
        if hasattr(fetcher, "fetch_html"):
            return fetcher.fetch_html(url, cancel_event=cancel_event)
        if hasattr(fetcher, "fetch"):
            return fetcher.fetch(
                url,
                accept="text/html,application/xhtml+xml",
                cancel_event=cancel_event,
            )
        raise DomainError("WEB_FETCH_UNAVAILABLE", "静态物化 fetcher 不支持 HTML 获取")

    def _fetch_image(
        self,
        url: str,
        *,
        max_bytes: int,
        cancel_event: Any,
    ) -> tuple[FetchResult, ImageFormat | None]:
        fetcher = self._fetcher_for(max_bytes)
        if hasattr(fetcher, "fetch_image"):
            return fetcher.fetch_image(url, cancel_event=cancel_event)
        if hasattr(fetcher, "fetch"):
            return (
                fetcher.fetch(
                    url,
                    accept="image/jpeg,image/png,image/gif,image/webp",
                    cancel_event=cancel_event,
                ),
                None,
            )
        raise DomainError("WEB_FETCH_UNAVAILABLE", "静态物化 fetcher 不支持图片获取")

    def acquire(self, request: Any) -> AcquisitionResult:
        """Fetch and materialize one server-authored request using ``jobs_root/job_id`` only."""

        cancel_event = request.cancel_event
        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "任务已取消")
        job_id = request.job_id
        jobs_root = request.jobs_root.resolve()
        if not _JOB_ID_RE.fullmatch(job_id):
            raise DomainError("INVALID_ARGUMENT", "任务 ID 无效")
        job_dir = ensure_within_root(jobs_root / job_id, jobs_root)
        job_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = ensure_within_root(job_dir / "assets", job_dir)
        assets_dir.mkdir(parents=True, exist_ok=True)

        resource = request.mutable_resource()
        source_url = resource.get("source_url")
        source_url = _safe_http_url(source_url, label="资源来源")
        page_response_raw = self._fetch_html(
            source_url,
            max_bytes=self.config.max_html_bytes,
            cancel_event=cancel_event,
        )
        page_response = _response_view(
            page_response_raw,
            source_url,
            self.config.max_html_bytes,
        )
        if page_response.status in {401, 403}:
            raise DomainError("AUTH_REQUIRED", "网页需要授权才能物化")
        if page_response.status in {404, 410}:
            raise DomainError("RESOURCE_NOT_FOUND", "网页资源不存在")
        if page_response.status >= 400:
            raise DomainError("WEB_FETCH_FAILED", "网页请求失败", retryable=page_response.status >= 500)
        if not _is_html_response(page_response):
            raise DomainError("CONTENT_VALIDATION_FAILED", "资源响应不是可物化的 HTML")
        page_origin = _origin(page_response.url)
        resource_title = resource.get("title") or ""
        limits = BlockLimits(
            max_html_bytes=self.config.max_html_bytes,
            max_dom_nodes=self.config.max_dom_nodes,
            max_depth=self.config.max_dom_depth,
            max_text_chars=self.config.max_text_chars,
            max_blocks=self.config.max_blocks,
        )
        try:
            ir = extract_block_ir(
                page_response.body,
                source_url=page_response.url,
                title=str(resource_title or ""),
                limits=limits,
            )
        except BlockExtractionError as exc:
            raise DomainError("CONTENT_VALIDATION_FAILED", str(exc)) from exc

        _check_cancel(cancel_event)
        image_paths: dict[int, str] = {}
        image_assets: dict[str, _ImageAsset] = {}
        image_cache: dict[str, str | None] = {}
        warnings = list(ir.warnings)
        total_image_bytes = 0
        unique_images = 0
        for block_index, block in enumerate(ir.blocks):
            if block.kind != "image":
                continue
            if cancel_event is not None and cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "任务已取消")
            reference = block.url
            if not reference:
                warnings.append("image_missing_reference")
                image_cache["#missing"] = None
                continue
            try:
                image_url = urljoin(page_response.url, reference)
                if _origin(image_url) != page_origin:
                    raise DomainError("NETWORK_BLOCKED", "图片不是网页同源资源")
            except (DomainError, ValueError):
                warnings.append("image_cross_origin_or_invalid")
                image_cache[reference] = None
                continue
            if image_url in image_cache:
                local_path = image_cache[image_url]
                if local_path:
                    image_paths[block_index] = local_path
                continue
            if unique_images >= self.config.max_image_count:
                warnings.append("image_count_limit")
                image_cache[image_url] = None
                continue
            unique_images += 1
            try:
                image_raw, image_format = self._fetch_image(
                    image_url,
                    max_bytes=self.config.max_image_bytes,
                    cancel_event=cancel_event,
                )
                image_response = _response_view(
                    image_raw,
                    image_url,
                    self.config.max_image_bytes,
                )
                if image_response.status in {401, 403}:
                    raise DomainError("AUTH_REQUIRED", "图片需要授权")
                if image_response.status >= 400:
                    raise DomainError("WEB_FETCH_FAILED", "图片请求失败")
                if _origin(image_response.url) != page_origin:
                    raise DomainError("NETWORK_BLOCKED", "图片重定向到非同源地址")
                detected = (
                    (image_format.media_type, image_format.extension)
                    if image_format is not None
                    else _image_signature(image_response.body, image_response.media_type)
                )
                if detected is None:
                    raise DomainError("CONTENT_VALIDATION_FAILED", "图片格式未通过校验")
                media_type, suffix = detected
                if total_image_bytes + len(image_response.body) > self.config.max_total_image_bytes:
                    raise DomainError("DOWNLOAD_TOO_LARGE", "图片总大小超过物化上限")
                digest = _sha256(image_response.body)
                relative_path = f"assets/image-{digest[:24]}{suffix}"
                image_assets.setdefault(
                    relative_path,
                    _ImageAsset(relative_path, media_type, image_response.body),
                )
                total_image_bytes += len(image_response.body)
                image_cache[image_url] = relative_path
                image_paths[block_index] = relative_path
            except DomainError as exc:
                if exc.code == "JOB_CANCELLED" or (cancel_event is not None and cancel_event.is_set()):
                    raise
                warnings.append("image_fetch_failed")
                image_cache[image_url] = None
            except Exception:
                warnings.append("image_fetch_failed")
                image_cache[image_url] = None

        _check_cancel(cancel_event)
        embedded_image_sources: dict[int, str] = {}
        for block_index, relative_path in image_paths.items():
            asset = image_assets.get(relative_path)
            if asset is None:
                continue
            encoded = base64.b64encode(asset.data).decode("ascii")
            embedded_image_sources[block_index] = (
                f"data:{asset.media_type};base64,{encoded}"
            )

        markdown = render_markdown(ir, image_paths)
        sanitized_html = render_sanitized_html(ir, embedded_image_sources)
        _check_cancel(cancel_event)
        metadata_blocks: list[dict[str, object]] = []
        for block_index, block in enumerate(ir.blocks):
            block_metadata = block_to_mapping(block)
            if block.kind == "image":
                block_metadata.pop("url", None)
                block_metadata["asset"] = image_paths.get(block_index)
            metadata_blocks.append(block_metadata)
        metadata: dict[str, Any] = {
            "schema_version": "web-materialization-v1",
            "title": ir.title,
            "source_url": page_response.url,
            "media_type": "text/html",
            "block_count": len(ir.blocks),
            "image_count": len(image_assets),
            "truncated": ir.truncated,
            "warnings": sorted(set(warnings)),
            "blocks": metadata_blocks,
            "assets": sorted(image_assets),
        }
        metadata_bytes = (
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"
        ).encode("utf-8")
        package_files: dict[str, bytes] = {
            "index.html": sanitized_html.encode("utf-8"),
            "content.md": markdown.encode("utf-8"),
            "metadata.json": metadata_bytes,
        }
        for relative_path, asset in image_assets.items():
            package_files[relative_path] = asset.data
        zip_data = _zip_bytes(package_files, cancel_event=cancel_event)
        zip_path = ensure_within_root(job_dir / "webbundle.zip", job_dir)
        try:
            for relative_path, data in package_files.items():
                _check_cancel(cancel_event)
                output_path = ensure_within_root(job_dir / relative_path, job_dir)
                _relative_path(output_path, job_dir)
                _write_output(output_path, data, job_dir)
            _check_cancel(cancel_event)
            _write_output(zip_path, zip_data, job_dir)

            artifact_specs: list[tuple[Path, str, str, bool]] = [
                (job_dir / "index.html", "text/html", "primary", True),
                (zip_path, "application/zip", "bundle", False),
                (job_dir / "content.md", "text/markdown", "markdown", False),
                (job_dir / "metadata.json", "application/json", "metadata", False),
            ]
            artifact_specs.extend(
                (job_dir / relative_path, asset.media_type, "image", False)
                for relative_path, asset in sorted(image_assets.items())
            )
            artifacts: list[Artifact] = []
            for index, (path, media_type, role, primary) in enumerate(artifact_specs):
                _check_cancel(cancel_event)
                data = path.read_bytes()
                artifacts.append(
                    _artifact(
                        request=request,
                        index=index,
                        path=path.resolve(),
                        byte_size=len(data),
                        media_type=media_type,
                        sha256=_sha256(data),
                        filename=_relative_path(path, job_dir),
                        role=role,
                        primary=primary,
                    )
                )
        except Exception:
            self._cleanup(job_dir, (*package_files.keys(), "webbundle.zip"))
            raise
        bundle = ArtifactBundle(tuple(artifacts))
        return AcquisitionResult.success(
            AcquisitionStrategy.WEB_MATERIALIZE,
            bundle,
            warnings=tuple(sorted(set(warnings))),
            metadata={"provider": "static_web"},
        )

    @staticmethod
    def _cleanup(job_dir: Path, relative_paths: Any) -> None:
        for relative_path in relative_paths:
            path = job_dir / str(relative_path)
            try:
                ensure_within_root(path, job_dir)
            except Exception:
                continue
            path.unlink(missing_ok=True)


__all__ = [
    "MAX_HTML_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_COUNT",
    "MAX_TOTAL_IMAGE_BYTES",
    "MaterializerConfig",
    "WebMaterializer",
    "WebMaterializerConfig",
    "render_markdown",
    "render_sanitized_html",
]
