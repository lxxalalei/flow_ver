"""Bounded inspection of public generic HTTP resources.

This adapter intentionally keeps the network boundary private.  It follows
only a small, explicitly bounded redirect chain, validates every URL with the
shared public-network policy, and returns metadata that has already passed the
inspection core's locator/secret boundary.  The transport and DNS resolver
are injectable so tests never need to access the network.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
import json
import re
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..inspection import (
    INSPECTOR_VERSION,
    InspectionResult,
    build_default_inspection,
    build_representation_authority,
    source_fingerprint,
)
from ..policy import Resolver, PolicyViolation, system_resolver, validate_public_http_url


INSPECTOR_ID = "generic"
MAX_BYTES = 1024 * 1024
INSPECTION_MAX_BYTES = MAX_BYTES
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_REDIRECTS = 5
READ_CHUNK_SIZE = 64 * 1024

_HTTP_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_HTML_MIME_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_MIME_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$", re.IGNORECASE)
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")
_RESOURCE_ID_RE = re.compile(r"^res_[A-Za-z0-9_-]{16,64}$")


class _Response(Protocol):
    status: int
    headers: Any

    def read(self, amount: int = -1) -> bytes:
        ...

    def geturl(self) -> str:
        ...


class _Transport(Protocol):
    def __call__(self, request: Request, timeout: float) -> _Response:
        ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Leave redirect responses for the inspector's explicit policy loop."""

    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        return None


@dataclass(frozen=True, slots=True)
class _FormatSpec:
    kind: str
    mime_type: str | None
    container: str | None
    name: str


@dataclass(frozen=True, slots=True)
class _HTMLMetadata:
    title: str | None = None
    description: str | None = None
    author: str | None = None
    language: str | None = None
    published_date: str | None = None


class _HTMLMetadataParser(HTMLParser):
    """Collect a small allow-list of HTML metadata without retaining markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.html_language: str | None = None
        self._in_title = False
        self._jsonld_depth = 0
        self._jsonld_parts: list[str] = []
        self.jsonld_documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        values = {key.casefold(): value for key, value in attrs if key}
        if normalized_tag == "title":
            self._in_title = True
        elif normalized_tag == "html":
            self.html_language = values.get("lang")
        elif normalized_tag == "meta":
            key = values.get("name") or values.get("property") or values.get("itemprop")
            content = values.get("content")
            if key and content is not None and len(self.meta) < 32:
                normalized_key = key.casefold().strip()
                if normalized_key and normalized_key not in self.meta:
                    self.meta[normalized_key] = content
        elif normalized_tag == "script":
            script_type = (values.get("type") or "").casefold().split(";", 1)[0].strip()
            if script_type == "application/ld+json":
                self._jsonld_depth += 1
                self._jsonld_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "title":
            self._in_title = False
        elif normalized_tag == "script" and self._jsonld_depth:
            document = _parse_jsonld("".join(self._jsonld_parts))
            if document is not None and len(self.jsonld_documents) < 8:
                self.jsonld_documents.append(document)
            self._jsonld_depth -= 1
            self._jsonld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title_parts) < 128:
            self.title_parts.append(data[:512])
        if self._jsonld_depth and sum(map(len, self._jsonld_parts)) < 256 * 1024:
            self._jsonld_parts.append(data[:16 * 1024])


def _parse_jsonld(value: str) -> Any:
    candidate = value.strip()
    if not candidate or len(candidate) > 256 * 1024:
        return None
    try:
        return json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _safe_text(value: Any, maximum: int) -> str | None:
    """Return only a short scalar that is safe for the public result."""

    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not text or len(text) > maximum:
        return None
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        return None
    lowered = text.casefold()
    if re.search(r"\b(?:https?|ftp|file|data|javascript):", lowered):
        return None
    if re.match(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)", text):
        return None
    if lowered.startswith(("bearer ", "basic ")):
        return None
    return text


def _safe_language(value: Any) -> str | None:
    text = _safe_text(value, 35)
    if text is None or _LANGUAGE_RE.fullmatch(text) is None:
        return None
    return text.replace("_", "-")


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:
        value = None
    if value is None:
        try:
            for key, candidate in headers.items():
                if str(key).casefold() == name.casefold():
                    value = candidate
                    break
        except Exception:
            value = None
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _response_status(response: Any) -> int:
    raw = getattr(response, "status", None)
    if raw is None:
        raw = getattr(response, "code", None)
    if raw is None:
        return 200
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _response_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return value
    value = getattr(response, "url", None)
    return value if isinstance(value, str) and value else fallback


def _normalise_mime(value: str | None) -> tuple[str | None, str | None]:
    if value is None or not value.strip():
        return None, "MIME_MISSING"
    candidate = value.split(";", 1)[0].strip().casefold()
    if len(candidate) > 127 or _MIME_RE.fullmatch(candidate) is None:
        return None, "MIME_INVALID"
    return candidate, None


def _container_from_mime(mime_type: str | None) -> str | None:
    if not mime_type or "/" not in mime_type:
        return None
    known = {
        "text/html": "html",
        "application/xhtml+xml": "xhtml",
        "application/pdf": "pdf",
        "application/epub+zip": "epub",
        "application/zip": "zip",
        "application/msword": "doc",
        "application/rtf": "rtf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "text/plain": "txt",
        "text/csv": "csv",
        "text/vtt": "vtt",
        "image/jpeg": "jpeg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/flac": "flac",
        "video/mp4": "mp4",
        "video/webm": "webm",
    }
    if mime_type in known:
        return known[mime_type]
    candidate = mime_type.split("/", 1)[1]
    candidate = re.sub(r"[^A-Za-z0-9._+-]", "", candidate)[:64]
    return candidate or None


def _spec_from_mime(mime_type: str | None) -> _FormatSpec | None:
    if not mime_type:
        return None
    if mime_type in _HTML_MIME_TYPES:
        return _FormatSpec("webpage", mime_type, _container_from_mime(mime_type), "html")
    if mime_type.startswith("video/"):
        return _FormatSpec("video", mime_type, _container_from_mime(mime_type), "video")
    if mime_type.startswith("audio/"):
        return _FormatSpec("audio", mime_type, _container_from_mime(mime_type), "audio")
    if mime_type.startswith("image/"):
        return _FormatSpec("image", mime_type, _container_from_mime(mime_type), "image")
    if mime_type in {"text/vtt", "application/ttml+xml", "application/x-subrip"}:
        return _FormatSpec("subtitle", mime_type, _container_from_mime(mime_type), "subtitle")
    if mime_type.startswith("text/") or mime_type in {
        "application/pdf",
        "application/epub+zip",
        "application/zip",
        "application/msword",
        "application/rtf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return _FormatSpec("document", mime_type, _container_from_mime(mime_type), "document")
    return _FormatSpec("other", mime_type, _container_from_mime(mime_type), "other")


def _spec_from_magic(body: bytes) -> _FormatSpec | None:
    sample = body[:8192]
    if sample.startswith(b"%PDF-"):
        return _FormatSpec("document", "application/pdf", "pdf", "pdf")
    if sample.startswith(b"PK\x03\x04"):
        return _FormatSpec("document", "application/zip", "zip", "zip")
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return _FormatSpec("image", "image/png", "png", "png")
    if sample.startswith(b"\xff\xd8\xff"):
        return _FormatSpec("image", "image/jpeg", "jpeg", "jpeg")
    if sample.startswith((b"GIF87a", b"GIF89a")):
        return _FormatSpec("image", "image/gif", "gif", "gif")
    if sample.startswith(b"RIFF") and sample[8:12] == b"WEBP":
        return _FormatSpec("image", "image/webp", "webp", "webp")
    if sample.startswith(b"RIFF") and sample[8:12] == b"WAVE":
        return _FormatSpec("audio", "audio/wav", "wav", "wav")
    if sample.startswith(b"ID3") or (
        len(sample) >= 2 and sample[0] == 0xFF and (sample[1] & 0xE0) == 0xE0
    ):
        return _FormatSpec("audio", "audio/mpeg", "mp3", "mp3")
    if sample.startswith(b"OggS"):
        return _FormatSpec("audio", "audio/ogg", "ogg", "ogg")
    if sample.startswith(b"fLaC"):
        return _FormatSpec("audio", "audio/flac", "flac", "flac")
    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        return _FormatSpec("video", "video/mp4", "mp4", "mp4")
    if sample.startswith(b"\x1a\x45\xdf\xa3"):
        return _FormatSpec("video", "video/webm", "webm", "webm")
    text_sample = sample.decode("utf-8", errors="replace")
    if re.match(r"\s*(?:<!doctype\s+html\b|<html(?:\s|>)|<head(?:\s|>)|<body(?:\s|>)|<title(?:\s|>))", text_sample, re.IGNORECASE):
        return _FormatSpec("webpage", "text/html", "html", "html")
    return None


def _spec_conflicts(declared: _FormatSpec | None, detected: _FormatSpec | None) -> bool:
    if declared is None or detected is None or declared.kind == "other":
        return False
    if declared.kind != detected.kind:
        return True
    if detected.mime_type == "application/zip" and declared.mime_type in {
        "application/zip",
        "application/epub+zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return False
    if declared.mime_type and detected.mime_type and declared.mime_type != detected.mime_type:
        return True
    return False


def _jsonld_scalar(value: Any, *, author: bool = False) -> str | None:
    if isinstance(value, str):
        return value
    if author and isinstance(value, Mapping):
        for key in ("name", "alternateName"):
            if key in value:
                return _jsonld_scalar(value[key])
    if author and isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found = _jsonld_scalar(item, author=True)
            if found:
                return found
    return None


def _walk_jsonld(value: Any, keys: tuple[str, ...], *, author: bool = False) -> str | None:
    if isinstance(value, Mapping):
        for key in keys:
            if key in value:
                found = _jsonld_scalar(value[key], author=author)
                if found:
                    return found
        for child in value.values():
            found = _walk_jsonld(child, keys, author=author)
            if found:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found = _walk_jsonld(child, keys, author=author)
            if found:
                return found
    return None


def _extract_html_metadata(body: bytes) -> _HTMLMetadata:
    parser = _HTMLMetadataParser()
    try:
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
    except Exception:
        # Malformed HTML should not turn an otherwise bounded response into a
        # raw parser exception.  The resource fallback remains available.
        pass

    meta = parser.meta
    title = "".join(parser.title_parts)
    description = (
        meta.get("description")
        or meta.get("og:description")
        or meta.get("twitter:description")
    )
    author = meta.get("author") or meta.get("article:author") or meta.get("citation_author")
    language = parser.html_language or meta.get("language") or meta.get("inlanguage")
    published_date = (
        meta.get("article:published_time")
        or meta.get("datepublished")
        or meta.get("date")
        or meta.get("datepublished")
    )

    for document in parser.jsonld_documents:
        title = title or _walk_jsonld(document, ("headline", "name", "title")) or ""
        description = description or _walk_jsonld(document, ("description", "abstract"))
        author = author or _walk_jsonld(document, ("author", "creator"), author=True)
        language = language or _walk_jsonld(document, ("inLanguage", "language"))
        published_date = published_date or _walk_jsonld(
            document, ("datePublished", "dateCreated", "uploadDate")
        )

    return _HTMLMetadata(
        title=_safe_text(title, 512),
        description=_safe_text(description, 4000),
        author=_safe_text(author, 256),
        language=_safe_language(language),
        published_date=_safe_text(published_date, 256),
    )


def _resource_value(resource: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in resource and resource[key] is not None:
            return resource[key]
    metadata = resource.get("metadata")
    if isinstance(metadata, Mapping):
        for key in keys:
            if key in metadata and metadata[key] is not None:
                return metadata[key]
    return None


def _resource_type(resource: Mapping[str, Any], default: str) -> str:
    value = _resource_value(resource, "resource_type", "type")
    if isinstance(value, str):
        candidate = value.casefold().strip()
        aliases = {
            "文章": "article",
            "网页": "article",
            "帖子": "article",
            "问答": "article",
            "图书": "book",
            "书": "book",
            "文档": "document",
            "资料": "document",
            "视频": "video",
            "音频": "audio",
            "课程": "course",
            "数据集": "dataset",
        }
        candidate = aliases.get(candidate, candidate)
        if candidate in {"article", "book", "document", "video", "audio", "course", "dataset", "other"}:
            return candidate
    return default


def _resource_id(resource: Mapping[str, Any]) -> str | None:
    value = resource.get("resource_id")
    if isinstance(value, str) and _RESOURCE_ID_RE.fullmatch(value):
        return value
    return None


class GenericWebInspector:
    """Inspect one public HTTP resource with a bounded synchronous GET."""

    platform_id = "generic"
    inspector_id = INSPECTOR_ID
    version = INSPECTOR_VERSION
    # Runtime capability inventory is derived from this implementation fact,
    # not from the retrieval catalog. Platform wrappers inherit the same
    # bounded scope set and may add non-primary companion representations.
    supported_scopes = ("primary_resource", "representation", "landing_page", "metadata")

    def __init__(
        self,
        resolver: Resolver = system_resolver,
        transport: Callable[..., Any] | None = None,
        opener: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        if transport is not None and opener is not None:
            raise ValueError("transport and opener are mutually exclusive")
        effective_timeout = timeout if timeout_seconds is None else timeout_seconds
        if isinstance(effective_timeout, bool) or not isinstance(effective_timeout, (int, float)):
            raise ValueError("timeout must be numeric")
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or max_redirects < 0:
            raise ValueError("max_redirects must be non-negative")
        self.resolver = resolver or system_resolver
        self.timeout = float(effective_timeout)
        self.max_bytes = min(max_bytes, MAX_BYTES)
        self.max_redirects = max_redirects
        self.transport = transport
        self.opener = opener or build_opener(_NoRedirectHandler())

    def _request(self, request: Request) -> Any:
        target = self.transport if self.transport is not None else self.opener
        method = getattr(target, "open", None)
        if callable(method):
            try:
                return method(request, timeout=self.timeout)
            except TypeError:
                return method(request, self.timeout)
        if not callable(target):
            raise TypeError("transport is not callable")
        try:
            return target(request, timeout=self.timeout)
        except TypeError:
            try:
                return target(request, self.timeout)
            except TypeError:
                return target(request)

    @staticmethod
    def _close(response: Any) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _failure(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        retriable: bool,
    ) -> dict[str, Any]:
        failure: dict[str, Any] = {
            "platform": self.platform_id,
            "code": code,
            "message": message,
            "retriable": bool(retriable),
        }
        resource_id = _resource_id(resource)
        if resource_id is not None:
            failure["resource_id"] = resource_id
        return failure

    def _result(
        self,
        resource: Mapping[str, Any],
        *,
        resolution_status: str,
        availability: str,
        representation: dict[str, Any] | None = None,
        title: str | None = None,
        summary: str | None = None,
        creator: str | None = None,
        language: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        failures: Sequence[Mapping[str, Any]] = (),
        warnings: Sequence[str] = (),
    ) -> InspectionResult:
        fallback_kind = representation.get("kind") if representation else "other"
        default_type = {
            "webpage": "article",
            "document": "document",
            "video": "video",
            "audio": "audio",
            "image": "other",
            "subtitle": "document",
            "other": "other",
        }.get(fallback_kind, "other")
        safe_title = _safe_text(title, 512) or _safe_text(
            _resource_value(resource, "title", "name"), 512
        ) or "未命名资源"
        resolved: dict[str, Any] = {
            "title": safe_title,
            "resource_type": _resource_type(resource, default_type),
            "availability": {"status": availability},
            "representations": [],
            "metadata": {},
        }
        safe_summary = _safe_text(summary, 4000)
        if safe_summary:
            resolved["summary"] = safe_summary
        safe_creator = _safe_text(creator, 256)
        if safe_creator:
            resolved["creator"] = safe_creator
        safe_language = _safe_language(language)
        if safe_language:
            resolved["language"] = safe_language

        safe_metadata: dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
                continue
            if isinstance(value, bool):
                safe_metadata[key] = value
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                safe_metadata[key] = value
            elif isinstance(value, float) and value == value and abs(value) != float("inf"):
                safe_metadata[key] = value
            elif isinstance(value, str):
                safe_value = _safe_text(value, 1024)
                if safe_value:
                    safe_metadata[key] = safe_value
        resolved["metadata"] = safe_metadata

        inspection = build_default_inspection(
            self.inspector_id,
            method="bounded_get",
            cache_status="miss",
            warnings=list(warnings)[:32],
            version=self.version,
        )
        if representation is not None:
            rep = dict(representation)
            try:
                fingerprint = source_fingerprint(resource)
            except Exception:
                source = resource.get("source_url")
                source_text = source if isinstance(source, str) else ""
                fingerprint = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            seed = f"{fingerprint}:{rep.get('kind', 'other')}:{rep.get('mime_type', '')}"
            rep.setdefault("representation_id", "repr_" + hashlib.sha256(seed.encode()).hexdigest()[:32])
            # Every adapter result carries explicit capability scope and
            # bounded evidence.  Legacy role/materializable fields remain in
            # the envelope for old consumers but are never used to infer a
            # primary resource when the authority fields disagree.
            scope = rep.get("scope")
            role = rep.get("role")
            if isinstance(scope, str) and isinstance(role, str):
                authority = build_representation_authority(
                    resource,
                    scope=scope,
                    role=role,
                    technical_availability=str(
                        rep.get("technical_availability") or availability
                    ),
                    source=str(rep.get("evidence", {}).get("source") or "inspection")
                    if isinstance(rep.get("evidence"), Mapping)
                    else "inspection",
                    observed_at=inspection["inspected_at"],
                )
                rep.update(authority)
            resolved["representations"] = [rep]
        return InspectionResult(
            resolution_status=resolution_status,
            resolved_resource=resolved,
            inspection=inspection,
            failures=list(failures)[:32],
        )

    def _error_result(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        retriable: bool,
        *,
        availability: str = "unknown",
        warnings: Sequence[str] = (),
    ) -> InspectionResult:
        return self._result(
            resource,
            resolution_status="unresolved",
            availability=availability,
            failures=[self._failure(resource, code, message, retriable)],
            warnings=warnings,
        )

    def _read_bounded(self, response: Any) -> tuple[bytes | None, dict[str, Any] | None]:
        declared = _header(response, "Content-Length")
        declared_size: int | None = None
        declared_error: dict[str, Any] | None = None
        if declared is not None:
            candidate = declared.strip()
            if re.fullmatch(r"\d+", candidate) is None:
                declared_error = {
                    "code": "CONTENT_VALIDATION_FAILED",
                    "message": "响应大小声明无效",
                    "retriable": False,
                }
            else:
                try:
                    declared_size = int(candidate)
                except ValueError:
                    declared_error = {
                        "code": "CONTENT_VALIDATION_FAILED",
                        "message": "响应大小声明无效",
                        "retriable": False,
                    }
                if declared_size is not None and declared_size > self.max_bytes:
                    return None, {
                        "code": "DOWNLOAD_TOO_LARGE",
                        "message": "资源声明大小超过检查上限",
                        "retriable": False,
                    }

        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                amount = min(READ_CHUNK_SIZE, self.max_bytes - total + 1)
                chunk = response.read(amount)
                if chunk is None or chunk == b"":
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    return None, {
                        "code": "CONTENT_VALIDATION_FAILED",
                        "message": "响应内容格式无效",
                        "retriable": False,
                    }
                if len(chunk) > self.max_bytes - total:
                    return None, {
                        "code": "DOWNLOAD_TOO_LARGE",
                        "message": "资源实际大小超过检查上限",
                        "retriable": False,
                    }
                chunk_bytes = bytes(chunk)
                total += len(chunk_bytes)
                chunks.append(chunk_bytes)
        except Exception as exc:
            if _is_timeout(exc):
                return None, {
                    "code": "PARTIAL_FAILURE",
                    "message": "检查请求超时",
                    "retriable": True,
                }
            return None, {
                "code": "PARTIAL_FAILURE",
                "message": "检查请求失败",
                "retriable": True,
            }

        result_error = declared_error
        if declared_size is not None and declared_size != total:
            result_error = {
                "code": "CONTENT_VALIDATION_FAILED",
                "message": "响应大小声明与实际内容不一致",
                "retriable": False,
            }
        return b"".join(chunks), result_error

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        try:
            return self._inspect(resource)
        except Exception:
            # The adapter boundary must not expose parser, resolver, or
            # transport exception text.  Keep this fallback deliberately
            # boring and let the inspection core validate the envelope.
            safe_resource = resource if isinstance(resource, Mapping) else {}
            try:
                return self._error_result(
                    safe_resource,
                    "PARTIAL_FAILURE",
                    "检查请求失败",
                    True,
                )
            except Exception:
                return self._result(
                    {},
                    resolution_status="unresolved",
                    availability="unknown",
                    failures=[
                        {
                            "platform": self.platform_id,
                            "code": "PARTIAL_FAILURE",
                            "message": "检查请求失败",
                            "retriable": True,
                        }
                    ],
                )

    def _inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        """Return a bounded, locator-free inspection result."""

        if not isinstance(resource, Mapping):
            return self._error_result({}, "INVALID_ARGUMENT", "资源记录无效", False)

        source_url = resource.get("source_url")
        if not isinstance(source_url, str) or not source_url:
            return self._error_result(resource, "INVALID_ARGUMENT", "资源缺少有效来源", False)

        try:
            validate_public_http_url(source_url, resolver=self.resolver)
        except PolicyViolation:
            return self._error_result(
                resource,
                "NETWORK_BLOCKED",
                "请求地址未通过公共网络安全策略",
                False,
                availability="policy_blocked",
            )

        current_url = source_url
        redirects = 0
        response: Any | None = None
        while True:
            request = Request(
                current_url,
                method="GET",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                    "User-Agent": "EducationResourceMCP/0.1 (+bounded inspection)",
                },
            )
            try:
                response = self._request(request)
            except HTTPError as exc:
                response = exc
            except Exception as exc:
                return self._error_result(
                    resource,
                    "PARTIAL_FAILURE",
                    "检查请求超时" if _is_timeout(exc) else "检查请求失败",
                    True,
                )

            final_url = _response_url(response, current_url)
            try:
                validate_public_http_url(final_url, resolver=self.resolver)
            except PolicyViolation:
                self._close(response)
                return self._error_result(
                    resource,
                    "REDIRECT_BLOCKED",
                    "最终地址未通过公共网络安全策略",
                    False,
                    availability="policy_blocked",
                )

            status = _response_status(response)
            if status in _HTTP_REDIRECT_STATUSES:
                location = _header(response, "Location")
                self._close(response)
                if redirects >= self.max_redirects:
                    return self._error_result(
                        resource,
                        "REDIRECT_BLOCKED",
                        "重定向次数超过检查上限",
                        False,
                    )
                if location is None or not location.strip():
                    return self._error_result(
                        resource,
                        "REDIRECT_BLOCKED",
                        "响应缺少有效重定向地址",
                        False,
                    )
                target_url = urljoin(current_url, location)
                try:
                    validate_public_http_url(target_url, resolver=self.resolver)
                except PolicyViolation:
                    return self._error_result(
                        resource,
                        "REDIRECT_BLOCKED",
                        "重定向地址未通过公共网络安全策略",
                        False,
                        availability="policy_blocked",
                    )
                current_url = target_url
                redirects += 1
                continue
            break

        assert response is not None
        try:
            if status in (401, 403):
                return self._error_result(
                    resource,
                    "AUTH_REQUIRED",
                    "资源需要授权才能检查",
                    False,
                    availability="auth_required",
                )
            if status in (404, 410):
                return self._error_result(
                    resource,
                    "RESOURCE_NOT_FOUND",
                    "资源当前不可用",
                    False,
                    availability="unavailable",
                )
            if status in (408, 429) or status >= 500:
                return self._error_result(
                    resource,
                    "RATE_LIMITED" if status == 429 else "PLATFORM_UNAVAILABLE",
                    "远程服务暂时不可用",
                    True,
                )
            if status < 200 or status >= 300:
                return self._error_result(
                    resource,
                    "PARTIAL_FAILURE",
                    "远程响应状态不支持检查",
                    False,
                )

            body, read_error = self._read_bounded(response)
            if body is None:
                assert read_error is not None
                return self._error_result(
                    resource,
                    str(read_error["code"]),
                    str(read_error["message"]),
                    bool(read_error["retriable"]),
                )
            if not body.strip():
                return self._error_result(
                    resource,
                    "CONTENT_VALIDATION_FAILED",
                    "响应内容为空",
                    False,
                )

            mime_type, mime_error = _normalise_mime(_header(response, "Content-Type"))
            declared_spec = _spec_from_mime(mime_type)
            detected_spec = _spec_from_magic(body)
            failures: list[dict[str, Any]] = []
            warnings: list[str] = []
            if mime_error is not None:
                failures.append(
                    self._failure(resource, "CONTENT_VALIDATION_FAILED", "响应媒体类型无效", False)
                )
            if read_error is not None:
                failures.append(
                    self._failure(
                        resource,
                        str(read_error["code"]),
                        str(read_error["message"]),
                        bool(read_error["retriable"]),
                    )
                )

            if _spec_conflicts(declared_spec, detected_spec):
                warnings.append("响应媒体类型与内容格式不一致")
                failures.append(
                    self._failure(
                        resource,
                        "CONTENT_VALIDATION_FAILED",
                        "响应媒体类型与内容格式不一致",
                        False,
                    )
                )

            if declared_spec is not None and declared_spec.kind not in {"other", "webpage"} and detected_spec is None:
                warnings.append("文件格式未能通过内容特征确认")
                failures.append(
                    self._failure(
                        resource,
                        "CONTENT_VALIDATION_FAILED",
                        "文件格式未能通过内容特征确认",
                        False,
                    )
                )

            selected_spec = declared_spec or detected_spec
            if declared_spec is None or declared_spec.kind == "other":
                selected_spec = detected_spec or declared_spec
            if selected_spec is None:
                selected_spec = _FormatSpec("other", mime_type, _container_from_mime(mime_type), "other")

            is_html = selected_spec.kind == "webpage"
            html_metadata = _extract_html_metadata(body) if is_html else _HTMLMetadata()
            fallback_summary = _resource_value(resource, "summary", "description")
            fallback_creator = _resource_value(resource, "creator", "author")
            fallback_language = _resource_value(resource, "language")
            summary = html_metadata.description or _safe_text(fallback_summary, 4000)
            creator = html_metadata.author or _safe_text(fallback_creator, 256)
            language = html_metadata.language or _safe_language(fallback_language)
            published_date = html_metadata.published_date or _safe_text(
                _resource_value(resource, "published_at", "published_date", "date_published"),
                256,
            )

            representation_mime = selected_spec.mime_type or mime_type
            format_conflict = _spec_conflicts(declared_spec, detected_spec)
            concrete_evidence = (
                detected_spec is not None
                and detected_spec.kind != "webpage"
                and not format_conflict
                and mime_error is None
                and read_error is None
            )
            page_evidence = (
                selected_spec.kind == "webpage"
                and not format_conflict
                and mime_error is None
                and read_error is None
            )
            if concrete_evidence:
                scope = "primary_resource"
                role = "primary"
                materializable = True
                technical_availability = "available"
            elif page_evidence:
                scope = "landing_page"
                role = "landing"
                # A successfully inspected public HTML response is concrete
                # landing-page evidence.  It can be materialized by the exact
                # web-materializer capability while remaining a landing page;
                # this never upgrades it to a primary resource.
                materializable = True
                technical_availability = "available" if not failures else "unknown"
            else:
                # A declared file MIME without a matching magic signature, a
                # MIME/magic conflict, or an unclassified body is only a
                # representation fact.  It must not become a primary plan.
                scope = "representation"
                role = "attachment"
                materializable = False
                technical_availability = "unknown"
            representation: dict[str, Any] = {
                "kind": selected_spec.kind,
                "container": selected_spec.container,
                "mime_type": representation_mime,
                "scope": scope,
                "role": role,
                "technical_availability": technical_availability,
                "size_bytes": len(body),
                "materializable": materializable,
            }
            if language:
                representation["language"] = language
            representation = {key: value for key, value in representation.items() if value is not None}
            metadata: dict[str, Any] = {
                "detected_format": selected_spec.name,
            }
            if published_date:
                metadata["published_date"] = published_date
            if language:
                metadata["language_source"] = language
            if mime_type:
                metadata["declared_mime"] = mime_type

            partial = bool(failures)
            return self._result(
                resource,
                resolution_status="partial" if partial else "resolved",
                availability="unknown" if partial else "available",
                representation=representation,
                title=html_metadata.title,
                summary=summary,
                creator=creator,
                language=language,
                metadata=metadata,
                failures=failures,
                warnings=warnings,
            )
        finally:
            self._close(response)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, (TimeoutError, socket.timeout))
    return False


__all__ = [
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "GenericWebInspector",
    "INSPECTION_MAX_BYTES",
    "INSPECTOR_ID",
    "MAX_BYTES",
]
