"""Bounded, non-authenticated HTTP fetch primitives for web materialization.

This module is deliberately separate from the public inspection and download
layers.  It owns only the network boundary needed by a static web
materializer:

* validate the initial URL, every explicit redirect target, and every final
  response URL with the shared public-network policy;
* use a transport that does not follow redirects implicitly;
* read responses incrementally with a hard byte limit and cancellation checks;
* validate the small set of HTML and image formats that the first static
  materializer supports.

No cookies, authorization headers, browser state, or access-control bypasses
are accepted here.  Callers receive an internal :class:`FetchResult`; this
module must not be used to put response bodies or URLs in an MCP result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
import socket
import threading
from types import MappingProxyType
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..errors import DomainError
from ..policy import (
    PolicyViolation,
    Resolver,
    system_resolver,
    validate_public_http_url,
)


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
# Compatibility names for acquisition adapters that use the shorter policy
# vocabulary.
MAX_BYTES = DEFAULT_MAX_BYTES
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = DEFAULT_TIMEOUT_SECONDS
READ_CHUNK_SIZE = 64 * 1024

HTTP_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
HTML_MIME_TYPES = frozenset({"text/html", "application/xhtml+xml"})
IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)
SVG_MIME_TYPE = "image/svg+xml"
_MIME_RE = re.compile(
    r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$", re.IGNORECASE
)
_HTML_MAGIC_RE = re.compile(
    r"^\s*(?:<!doctype\s+html\b|<html(?:\s|>)|<head(?:\s|>)|"
    r"<body(?:\s|>)|<title(?:\s|>)|<article(?:\s|>)|<main(?:\s|>))",
    re.IGNORECASE,
)
_XML_DECLARATION_RE = re.compile(r"^\s*<\?xml\b[^>]*\?>", re.IGNORECASE)


# These values are intentionally kept stable.  They are internal failure
# categories, but the acquisition router uses them to decide whether a page
# is retryable, needs user authorization, or should be materialized as a gap.
FETCH_NETWORK_BLOCKED = "NETWORK_BLOCKED"
FETCH_REDIRECT_BLOCKED = "REDIRECT_BLOCKED"
FETCH_TOO_MANY_REDIRECTS = "TOO_MANY_REDIRECTS"
FETCH_AUTH_REQUIRED = "AUTH_REQUIRED"
FETCH_RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
FETCH_RATE_LIMITED = "RATE_LIMITED"
FETCH_PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE"
FETCH_HTTP_STATUS = "HTTP_STATUS_UNSUPPORTED"
FETCH_TIMEOUT = "FETCH_TIMEOUT"
FETCH_TRANSPORT_FAILED = "FETCH_TRANSPORT_FAILED"
FETCH_TOO_LARGE = "DOWNLOAD_TOO_LARGE"
FETCH_CANCELLED = "JOB_CANCELLED"
FETCH_CONTENT_INVALID = "CONTENT_VALIDATION_FAILED"


class FetchError(DomainError):
    """A stable internal error raised by :class:`BoundedWebFetcher`.

    ``DomainError`` is used as the base so the existing asynchronous job
    runner can handle this error without an adapter-specific exception path.
    The ``details`` mapping contains bounded, non-secret facts only; it never
    includes a URL, response body, request headers, or an exception string.
    """

    @property
    def failure(self) -> "FetchFailure":
        return FetchFailure(
            code=self.code,
            message=self.message,
            retriable=self.retryable,
            details=MappingProxyType(dict(self.details)),
        )


# A descriptive alias for callers that prefer the network-specific name.
WebFetchError = FetchError


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """Serializable internal failure data without sensitive context."""

    code: str
    message: str
    retriable: bool = False
    details: Mapping[str, Any] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ImageFormat:
    """The image container confirmed by its byte signature."""

    name: str
    media_type: str
    extension: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A bounded response kept inside the acquisition process."""

    url: str
    status: int
    media_type: str | None
    body: bytes
    headers: Mapping[str, str]
    redirect_count: int = 0

    @property
    def final_url(self) -> str:
        return self.url

    @property
    def content_type(self) -> str | None:
        return self.media_type

    @property
    def mime_type(self) -> str | None:
        return self.media_type


# ``FetchedResponse`` is convenient for materializer code and preserves a
# readable name without creating a second result shape.
FetchedResponse = FetchResult
FetchResponse = FetchResult


class ResponseLike(Protocol):
    headers: Any

    def read(self, amount: int = -1) -> bytes:
        ...

    def close(self) -> None:
        ...


class Transport(Protocol):
    def __call__(self, request: Request, timeout: float) -> ResponseLike:
        ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Keep redirect responses visible to the explicit policy loop."""

    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        return None


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


def _normalise_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.split(";", 1)[0].strip().casefold()
    if not candidate or _MIME_RE.fullmatch(candidate) is None:
        return None
    return candidate


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
    if isinstance(value, str) and value:
        return value
    return fallback


def _close(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _same_resource_url(left: str, right: str) -> bool:
    """Compare response URLs while ignoring a harmless URL fragment."""

    try:
        first = urlsplit(left)
        second = urlsplit(right)
    except ValueError:
        return left == right
    return urlunsplit((first.scheme, first.netloc, first.path, first.query, "")) == urlunsplit(
        (second.scheme, second.netloc, second.path, second.query, "")
    )


def image_format_from_magic(body: bytes | bytearray | memoryview) -> ImageFormat | None:
    """Return a supported image format from its magic bytes, if any.

    SVG deliberately has no result here.  It is text/XML rather than one of
    the bounded raster containers accepted by the first materializer.
    """

    if not isinstance(body, (bytes, bytearray, memoryview)):
        return None
    sample = bytes(body)
    if sample.startswith(b"\xff\xd8\xff"):
        return ImageFormat("jpeg", "image/jpeg", ".jpg")
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return ImageFormat("png", "image/png", ".png")
    if sample.startswith((b"GIF87a", b"GIF89a")):
        return ImageFormat("gif", "image/gif", ".gif")
    if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP":
        return ImageFormat("webp", "image/webp", ".webp")
    return None


# Readable aliases for callers and tests.
detect_image_format = image_format_from_magic
sniff_image_format = image_format_from_magic


def _html_magic_matches(body: bytes) -> bool:
    sample = body[:8192].decode("utf-8", errors="replace")
    sample = sample.lstrip("\ufeff")
    if _XML_DECLARATION_RE.match(sample):
        sample = sample[_XML_DECLARATION_RE.match(sample).end() :]
    return _HTML_MAGIC_RE.match(sample) is not None


def validate_html_payload(body: bytes, media_type: str | None) -> str:
    """Validate HTML MIME and a minimal HTML byte signature.

    The return value is the normalized MIME type so materializers can retain
    the verified representation without reimplementing the check.
    """

    if not isinstance(body, bytes) or not body:
        raise FetchError(FETCH_CONTENT_INVALID, "HTML 响应内容为空")
    normalized = _normalise_media_type(media_type)
    if normalized not in HTML_MIME_TYPES:
        raise FetchError(
            FETCH_CONTENT_INVALID,
            "HTML 响应媒体类型无效",
            details={"expected": "text/html 或 application/xhtml+xml"},
        )
    if not _html_magic_matches(body):
        raise FetchError(
            FETCH_CONTENT_INVALID,
            "HTML 响应未通过基本内容特征校验",
            details={"media_type": normalized},
        )
    return normalized


# Alias that reads naturally alongside ``validate_image_payload``.
validate_html_content = validate_html_payload


def validate_image_payload(
    body: bytes, media_type: str | None
) -> ImageFormat:
    """Validate a supported raster image MIME/magic pair.

    JPEG, PNG, GIF, and WebP are accepted only when their declared MIME type
    exactly matches their magic bytes.  SVG is explicitly rejected even when
    a caller tries to treat it as generic image content.
    """

    if not isinstance(body, bytes) or not body:
        raise FetchError(FETCH_CONTENT_INVALID, "图片响应内容为空")
    normalized = _normalise_media_type(media_type)
    if normalized == SVG_MIME_TYPE:
        raise FetchError(
            FETCH_CONTENT_INVALID,
            "不支持 SVG 图片",
            details={"media_type": SVG_MIME_TYPE},
        )
    if normalized not in IMAGE_MIME_TYPES:
        raise FetchError(
            FETCH_CONTENT_INVALID,
            "图片响应媒体类型不受支持",
            details={"expected": "image/jpeg、image/png、image/gif 或 image/webp"},
        )
    detected = image_format_from_magic(body)
    if detected is None:
        raise FetchError(
            FETCH_CONTENT_INVALID,
            "图片响应未通过内容特征校验",
            details={"media_type": normalized},
        )
    if detected.media_type != normalized:
        raise FetchError(
            FETCH_CONTENT_INVALID,
            "图片媒体类型与内容特征不一致",
            details={"declared": normalized, "detected": detected.media_type},
        )
    return detected


validate_image_content = validate_image_payload


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, socket.timeout)) or exc.__class__.__name__.casefold() in {
        "timeouterror",
        "sockettimeout",
    }


class BoundedWebFetcher:
    """Fetch public HTTP(S) resources with explicit redirect and size bounds."""

    def __init__(
        self,
        resolver: Resolver = system_resolver,
        transport: Any | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        timeout_seconds: float | None = None,
    ) -> None:
        effective_timeout = timeout if timeout_seconds is None else timeout_seconds
        if isinstance(effective_timeout, bool) or not isinstance(
            effective_timeout, (int, float)
        ):
            raise ValueError("timeout must be numeric")
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if (
            isinstance(max_redirects, bool)
            or not isinstance(max_redirects, int)
            or max_redirects < 0
            or max_redirects > MAX_REDIRECTS
        ):
            raise ValueError(f"max_redirects must be between 0 and {MAX_REDIRECTS}")

        self.resolver = resolver or system_resolver
        self.timeout = float(effective_timeout)
        self.max_bytes = min(max_bytes, DEFAULT_MAX_BYTES)
        self.max_redirects = max_redirects
        self.transport = transport
        self.opener = build_opener(_NoRedirectHandler())

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
    def _validate_url(url: str, *, redirect: bool, resolver: Resolver) -> None:
        try:
            validate_public_http_url(url, resolver=resolver)
        except PolicyViolation as exc:
            code = FETCH_REDIRECT_BLOCKED if redirect else FETCH_NETWORK_BLOCKED
            raise FetchError(
                code,
                "重定向地址未通过主机策略"
                if redirect
                else "请求地址未通过主机策略",
                details={"policy_code": exc.code},
            ) from exc

    @staticmethod
    def _check_cancel(cancel_event: Any | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise FetchError(FETCH_CANCELLED, "采集已取消")

    def _read_bounded(self, response: Any, cancel_event: Any | None) -> bytes:
        declared = _header(response, "Content-Length")
        declared_size: int | None = None
        if declared is not None:
            candidate = declared.strip()
            if not re.fullmatch(r"\d+", candidate):
                raise FetchError(FETCH_CONTENT_INVALID, "响应大小声明无效")
            declared_size = int(candidate)
            if declared_size > self.max_bytes:
                raise FetchError(
                    FETCH_TOO_LARGE,
                    "资源声明大小超过采集上限",
                    details={"max_bytes": self.max_bytes},
                )

        chunks: list[bytes] = []
        total = 0
        while True:
            self._check_cancel(cancel_event)
            amount = min(READ_CHUNK_SIZE, self.max_bytes - total + 1)
            if amount <= 0:
                raise FetchError(
                    FETCH_TOO_LARGE,
                    "资源实际大小超过采集上限",
                    details={"max_bytes": self.max_bytes},
                )
            try:
                chunk = response.read(amount)
            except Exception as exc:
                if _is_timeout(exc):
                    raise FetchError(
                        FETCH_TIMEOUT, "采集请求超时", retryable=True
                    ) from exc
                raise FetchError(
                    FETCH_TRANSPORT_FAILED, "读取采集响应失败", retryable=True
                ) from exc
            if chunk is None:
                raise FetchError(FETCH_CONTENT_INVALID, "响应内容格式无效")
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise FetchError(FETCH_CONTENT_INVALID, "响应内容格式无效")
            chunk_bytes = bytes(chunk)
            if not chunk_bytes:
                break
            if len(chunk_bytes) > self.max_bytes - total:
                raise FetchError(
                    FETCH_TOO_LARGE,
                    "资源实际大小超过采集上限",
                    details={"max_bytes": self.max_bytes},
                )
            total += len(chunk_bytes)
            chunks.append(chunk_bytes)
        if declared_size is not None and declared_size != total:
            raise FetchError(
                FETCH_CONTENT_INVALID,
                "响应大小声明与实际内容不一致",
            )
        return b"".join(chunks)

    @staticmethod
    def _safe_headers(response: Any) -> Mapping[str, str]:
        """Copy only non-sensitive response metadata needed by materializers."""

        copied: dict[str, str] = {}
        for name in ("Content-Type", "Content-Length", "ETag", "Last-Modified"):
            value = _header(response, name)
            if value is not None:
                copied[name] = value
        return MappingProxyType(copied)

    def fetch(
        self,
        url: str,
        *,
        accept: str = "*/*",
        cancel_event: Any | None = None,
    ) -> FetchResult:
        """Fetch one response, following at most five validated redirects."""

        self._check_cancel(cancel_event)
        self._validate_url(url, redirect=False, resolver=self.resolver)
        current_url = url
        redirects = 0

        while True:
            self._check_cancel(cancel_event)
            request = Request(
                current_url,
                method="GET",
                headers={
                    "Accept": accept,
                    "Accept-Encoding": "identity",
                    "User-Agent": "EducationResourceMCP/0.1 (+bounded static fetch)",
                },
            )
            response: Any | None = None
            try:
                try:
                    response = self._request(request)
                except HTTPError as exc:
                    # urllib exposes HTTP error statuses as a response-like
                    # object.  Handle them through the same stable status map.
                    response = exc
                except Exception as exc:
                    if _is_timeout(exc):
                        raise FetchError(
                            FETCH_TIMEOUT, "采集请求超时", retryable=True
                        ) from exc
                    raise FetchError(
                        FETCH_TRANSPORT_FAILED, "采集请求失败", retryable=True
                    ) from exc

                final_url = _response_url(response, current_url)
                self._validate_url(
                    final_url,
                    redirect=not _same_resource_url(final_url, current_url),
                    resolver=self.resolver,
                )
                status = _response_status(response)

                # A non-redirect response whose URL changed means the
                # injected transport followed a redirect itself.  Reject it
                # rather than losing the opportunity to validate each hop.
                if status not in HTTP_REDIRECT_STATUSES and not _same_resource_url(
                    final_url, current_url
                ):
                    raise FetchError(
                        FETCH_REDIRECT_BLOCKED,
                        "传输层不得自动跟随重定向",
                        details={"reason": "implicit_redirect"},
                    )

                if status in HTTP_REDIRECT_STATUSES:
                    location = _header(response, "Location")
                    if location is None or not location.strip():
                        raise FetchError(
                            FETCH_REDIRECT_BLOCKED,
                            "响应缺少有效重定向地址",
                        )
                    target_url = urljoin(current_url, location)
                    self._validate_url(
                        target_url, redirect=True, resolver=self.resolver
                    )
                    if redirects >= self.max_redirects:
                        raise FetchError(
                            FETCH_TOO_MANY_REDIRECTS,
                            "重定向次数超过采集上限",
                            details={"max_redirects": self.max_redirects},
                        )
                    redirects += 1
                    current_url = target_url
                    continue

                if status in (401, 403):
                    raise FetchError(
                        FETCH_AUTH_REQUIRED,
                        "资源需要授权才能采集",
                    )
                if status in (404, 410):
                    raise FetchError(
                        FETCH_RESOURCE_NOT_FOUND,
                        "资源当前不可用",
                    )
                if status in (408, 429):
                    raise FetchError(
                        FETCH_RATE_LIMITED,
                        "远程服务暂时不可用",
                        retryable=True,
                        details={"status": status},
                    )
                if status >= 500:
                    raise FetchError(
                        FETCH_PLATFORM_UNAVAILABLE,
                        "远程服务暂时不可用",
                        retryable=True,
                        details={"status": status},
                    )
                if status < 200 or status >= 300:
                    raise FetchError(
                        FETCH_HTTP_STATUS,
                        "远程响应状态不支持采集",
                        details={"status": status},
                    )

                body = self._read_bounded(response, cancel_event)
                self._check_cancel(cancel_event)
                media_type = _normalise_media_type(
                    _header(response, "Content-Type")
                )
                return FetchResult(
                    url=final_url,
                    status=status,
                    media_type=media_type,
                    body=body,
                    headers=self._safe_headers(response),
                    redirect_count=redirects,
                )
            finally:
                _close(response)

    def fetch_html(
        self, url: str, *, cancel_event: Any | None = None
    ) -> FetchResult:
        """Fetch and strictly validate one HTML/XHTML response."""

        result = self.fetch(
            url,
            accept="text/html,application/xhtml+xml",
            cancel_event=cancel_event,
        )
        validate_html_payload(result.body, result.media_type)
        return result

    def fetch_image(
        self, url: str, *, cancel_event: Any | None = None
    ) -> tuple[FetchResult, ImageFormat]:
        """Fetch and strictly validate one supported raster image."""

        result = self.fetch(
            url,
            accept="image/jpeg,image/png,image/gif,image/webp",
            cancel_event=cancel_event,
        )
        image_format = validate_image_payload(result.body, result.media_type)
        return result, image_format


# Short aliases keep the primitive easy to discover while retaining one
# implementation and one error/result shape.
WebFetcher = BoundedWebFetcher
StaticWebFetcher = BoundedWebFetcher


__all__ = [
    "BoundedWebFetcher",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_BYTES",
    "MAX_REDIRECTS",
    "FETCH_AUTH_REQUIRED",
    "FETCH_CANCELLED",
    "FETCH_CONTENT_INVALID",
    "FETCH_HTTP_STATUS",
    "FETCH_NETWORK_BLOCKED",
    "FETCH_PLATFORM_UNAVAILABLE",
    "FETCH_RATE_LIMITED",
    "FETCH_REDIRECT_BLOCKED",
    "FETCH_RESOURCE_NOT_FOUND",
    "FETCH_TIMEOUT",
    "FETCH_TOO_LARGE",
    "FETCH_TOO_MANY_REDIRECTS",
    "FETCH_TRANSPORT_FAILED",
    "FetchError",
    "FetchFailure",
    "FetchResult",
    "FetchResponse",
    "FetchedResponse",
    "HTML_MIME_TYPES",
    "IMAGE_MIME_TYPES",
    "ImageFormat",
    "StaticWebFetcher",
    "WebFetchError",
    "WebFetcher",
    "detect_image_format",
    "image_format_from_magic",
    "sniff_image_format",
    "validate_html_content",
    "validate_html_payload",
    "validate_image_content",
    "validate_image_payload",
]
