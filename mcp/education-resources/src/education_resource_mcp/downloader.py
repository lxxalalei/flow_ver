"""Controlled public HTTP downloader used by asynchronous jobs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
import mimetypes
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import Settings
from .errors import DomainError
from .policy import PolicyError, ensure_within_root, validate_public_http_url


_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "api_key",
        "auth",
        "cookie",
        "credential",
        "credentials",
        "file",
        "filename",
        "password",
        "path",
        "secret",
        "source_url",
        "request_headers",
        "response_body",
        "headers",
        "token",
        "url",
    }
)
_URL_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_CREDENTIAL_TEXT = re.compile(
    r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"
    r"\b(?:authorization|cookie|password|secret|token)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_PATH_TEXT = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s\"'<>]+)")


def _redact_text(value: str) -> str:
    """Remove credentials, URLs, and local paths without truncating the message."""

    text = str(value).replace("\x00", " ").strip()
    text = _URL_TEXT.sub("[redacted-url]", text)
    text = _CREDENTIAL_TEXT.sub("[redacted-credential]", text)
    text = _PATH_TEXT.sub("[redacted-path]", text)
    return text or "download item failed"


def _json_safe(value: Any) -> Any:
    """Normalize provider facts to JSON-safe values without arbitrary size limits."""

    if value is None or isinstance(value, (str, bool, int)):
        return _redact_text(value) if isinstance(value, str) else value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("provider metadata contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("provider metadata keys must be strings")
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized_key in _SENSITIVE_KEYS or set(normalized_key.split("_")) & {
                "authorization",
                "auth",
                "cookie",
                "credential",
                "password",
                "path",
                "file",
                "filename",
                "destination",
                "url",
                "uri",
                "secret",
                "token",
            }:
                continue
            normalized[key] = _json_safe(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError(f"provider metadata contains unsupported value {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _safe_metadata(value: Mapping[str, Any] | None, *, label: str) -> Mapping[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    frozen = _freeze_json(_json_safe(value))
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return frozen


def _safe_fact(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{label} must not contain control characters")
    return value


@dataclass(frozen=True, slots=True, init=False)
class DownloadResult:
    """One server-created file returned by a download provider.

    Existing providers may keep the historical five-positional-argument form
    ``DownloadResult(path, size, media_type, sha256, filename)``. New providers
    do not need to calculate a digest and can pass ``filename=...`` directly.
    """

    path: Path
    byte_size: int
    media_type: str
    filename: str
    sha256: str | None
    role: str | None
    required: bool | None
    item_key: str | None
    metadata: Mapping[str, Any]

    def __init__(
        self,
        path: Path,
        byte_size: int,
        media_type: str,
        sha256: str | None = None,
        filename: str = "",
        *,
        role: str | None = None,
        required: bool | None = None,
        item_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "byte_size", byte_size)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "sha256", sha256 or None)
        object.__setattr__(self, "filename", filename)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "item_key", item_key)
        object.__setattr__(self, "metadata", metadata or {})
        self.__post_init__()

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("download result path must be pathlib.Path")
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise TypeError("download result byte_size must be an integer")
        if self.byte_size < 0:
            raise ValueError("download result byte_size must not be negative")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise ValueError("download result media_type must be non-empty")
        if self.sha256 is not None and (
            not isinstance(self.sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256)
        ):
            raise ValueError("download result sha256 must be a hexadecimal digest")
        if not isinstance(self.filename, str) or not self.filename.strip():
            raise ValueError("download result filename must be non-empty")
        object.__setattr__(
            self,
            "role",
            _safe_fact(self.role, label="download result role"),
        )
        if self.required is not None and not isinstance(self.required, bool):
            raise TypeError("download result required must be a boolean")
        object.__setattr__(
            self,
            "item_key",
            _safe_fact(self.item_key, label="download result item_key"),
        )
        object.__setattr__(
            self,
            "metadata",
            _safe_metadata(self.metadata, label="download result metadata"),
        )

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        """Return a JSON-safe view; paths are opt-in for local diagnostics."""

        filename = str(self.filename).replace("\\", "/").rsplit("/", 1)[-1]
        result: dict[str, Any] = {
            "byte_size": self.byte_size,
            "filename": filename,
            "item_key": self.item_key,
            "media_type": str(self.media_type).strip(),
            "metadata": _thaw_json(self.metadata),
            "required": self.required,
            "role": self.role,
        }
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if include_path:
            result["path"] = str(self.path)
        return result


@dataclass(frozen=True, slots=True)
class DownloadItemFailure:
    """Failure for one provider item without carrying paths or credentials."""

    item_key: str
    code: str
    message: str
    role: str | None = None
    required: bool | None = None
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _safe_fact(self.item_key, label="download item failure item_key")
        if not isinstance(self.code, str) or not re.fullmatch(
            r"[A-Z][A-Z0-9_.-]{0,63}", self.code
        ):
            raise ValueError("download item failure code must be a stable uppercase code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("download item failure message must be non-empty")
        object.__setattr__(
            self,
            "role",
            _safe_fact(self.role, label="download item failure role"),
        )
        if self.required is not None and not isinstance(self.required, bool):
            raise TypeError("download item failure required must be a boolean")
        if not isinstance(self.retryable, bool):
            raise TypeError("download item failure retryable must be a boolean")
        object.__setattr__(self, "message", _redact_text(self.message))
        object.__setattr__(
            self,
            "details",
            _safe_metadata(self.details, label="download item failure details"),
        )
        object.__setattr__(
            self,
            "metadata",
            _safe_metadata(self.metadata, label="download item failure metadata"),
        )

    @property
    def retriable(self) -> bool:
        """Compatibility spelling used by the web-fetch internal models."""

        return self.retryable

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "item_key": self.item_key,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": _thaw_json(self.details),
        }
        if self.role is not None:
            result["role"] = self.role
        if self.required is not None:
            result["required"] = self.required
        if self.metadata:
            result["metadata"] = _thaw_json(self.metadata)
        return result


@dataclass(frozen=True, slots=True, init=False)
class DownloadBatchResult:
    """Enriched ordered download envelope for one selected resource."""

    results: tuple[DownloadResult, ...]
    failures: tuple[DownloadItemFailure, ...]

    def __init__(
        self,
        results: Sequence[DownloadResult] | None = None,
        failures: Sequence[DownloadItemFailure] | None = None,
        *,
        items: Sequence[DownloadResult] | None = None,
        item_failures: Sequence[DownloadItemFailure] | None = None,
    ) -> None:
        if results is not None and items is not None and tuple(results) != tuple(items):
            raise ValueError("download batch results/items disagree")
        if failures is not None and item_failures is not None and tuple(failures) != tuple(item_failures):
            raise ValueError("download batch failures/item_failures disagree")
        normalized_results = tuple(results if results is not None else (items or ()))
        normalized_failures = tuple(
            failures if failures is not None else (item_failures or ())
        )
        if any(not isinstance(item, DownloadResult) for item in normalized_results):
            raise TypeError("download batch results must contain DownloadResult values")
        if any(not isinstance(item, DownloadItemFailure) for item in normalized_failures):
            raise TypeError(
                "download batch failures must contain DownloadItemFailure values"
            )
        object.__setattr__(self, "results", normalized_results)
        object.__setattr__(self, "failures", normalized_failures)

    @property
    def items(self) -> tuple[DownloadResult, ...]:
        return self.results

    @property
    def item_failures(self) -> tuple[DownloadItemFailure, ...]:
        return self.failures

    @property
    def completion(self) -> str:
        return "partial" if self.failures else "complete"

    @property
    def ok(self) -> bool:
        return bool(self.results)

    def to_dict(self) -> dict[str, Any]:
        """Return the ordered envelope without paths or provider secrets."""

        return {
            "failures": [item.to_dict() for item in self.failures],
            "results": [item.to_dict() for item in self.results],
        }


class DownloadProvider(Protocol):
    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult | list[DownloadResult] | DownloadBatchResult:
        """Download one or more files for *resource*."""
        ...


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urljoin(req.full_url, newurl)
        try:
            validate_public_http_url(target)
        except PolicyError as exc:
            raise DomainError("REDIRECT_BLOCKED", str(exc)) from exc
        return super().redirect_request(req, fp, code, msg, headers, target)


def _safe_filename(title: str, url: str, media_type: str, strategy: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", title).strip("-._")
    cleaned = cleaned[:80] or "resource"
    if strategy == "webpage":
        suffix = ".html"
    else:
        suffix = Path(urlsplit(url).path).suffix.lower()[:10]
        if not suffix:
            suffix = mimetypes.guess_extension(media_type.split(";", 1)[0].strip()) or ".bin"
    if not cleaned.lower().endswith(suffix.lower()):
        cleaned += suffix
    return cleaned


def _available_destination(path: Path) -> Path:
    """Return a non-existing sibling path instead of overwriting another resource."""

    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


class PublicHttpDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        url = str(resource["source_url"])
        try:
            validate_public_http_url(url)
        except PolicyError as exc:
            raise DomainError("NETWORK_BLOCKED", str(exc)) from exc
        if strategy not in {"webpage", "direct"}:
            raise DomainError("INVALID_ARGUMENT", "首版只支持 webpage 或 direct 下载策略")

        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)
        temporary = job_dir / "payload.part"
        request = Request(
            url,
            headers={
                "User-Agent": "EducationResourceMCP/0.1 (+local OpenClaw development)",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            },
        )
        opener = build_opener(_SafeRedirectHandler())
        media_type = "application/octet-stream"
        # Throttled mirrors (e.g. Anna's Archive slow links) cut connections
        # mid-transfer; read-to-EOF alone then reports a truncated file as
        # success. Resume with Range requests and verify Content-Length.
        max_attempts = 6
        byte_size = 0
        expected_total: int | None = None
        try:
            for attempt in range(max_attempts):
                headers = {
                    "User-Agent": "EducationResourceMCP/0.1 (+local OpenClaw development)",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                }
                if byte_size > 0:
                    headers["Range"] = f"bytes={byte_size}-"
                request = Request(url, headers=headers)
                resumed = False
                try:
                    with opener.open(
                        request, timeout=self.settings.download_timeout_seconds
                    ) as response:
                        final_url = response.geturl()
                        try:
                            validate_public_http_url(final_url)
                        except PolicyError as exc:
                            raise DomainError("REDIRECT_BLOCKED", str(exc)) from exc
                        media_type = (
                            response.headers.get_content_type()
                            or "application/octet-stream"
                        )
                        content_range = response.headers.get("Content-Range")
                        if response.status == 206 or content_range:
                            resumed = True
                        elif byte_size > 0:
                            # server ignored Range; restart from scratch
                            byte_size = 0
                        try:
                            declared = int(response.headers.get("Content-Length") or "")
                        except ValueError:
                            declared = None
                        if declared is not None:
                            expected_total = (
                                byte_size + declared if resumed else declared
                            )
                        mode = "ab" if resumed else "wb"
                        with temporary.open(mode) as handle:
                            while True:
                                if cancel_event.is_set():
                                    raise DomainError("JOB_CANCELLED", "下载已取消")
                                chunk = response.read(64 * 1024)
                                if not chunk:
                                    break
                                byte_size += len(chunk)
                                handle.write(chunk)
                except DomainError:
                    raise
                except Exception as exc:
                    # stalled/reset connection with partial payload: retry
                    # with Range if attempts remain, else fail honestly
                    if attempt < max_attempts - 1 and byte_size > 0:
                        continue
                    raise DomainError(
                        "DOWNLOAD_FAILED",
                        f"下载失败：{type(exc).__name__}: {exc}",
                        retryable=True,
                    ) from exc
                if expected_total is None or byte_size >= expected_total:
                    break
            else:
                raise DomainError(
                    "DOWNLOAD_FAILED",
                    f"下载多次被中断且未能续传完整（{byte_size}/{expected_total} 字节）",
                    retryable=True,
                )
            if expected_total is not None and byte_size != expected_total:
                temporary.unlink(missing_ok=True)
                raise DomainError(
                    "CONTENT_VALIDATION_FAILED",
                    f"下载不完整：{byte_size}/{expected_total} 字节（连接提前结束）",
                    retryable=True,
                )
        except DomainError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"下载失败：{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc

        if byte_size == 0:
            temporary.unlink(missing_ok=True)
            raise DomainError("CONTENT_VALIDATION_FAILED", "下载内容为空")
        filename = _safe_filename(str(resource["title"]), url, media_type, strategy)
        destination = _available_destination(job_dir / filename)
        ensure_within_root(destination, self.settings.jobs_dir)
        temporary.replace(destination)
        return DownloadResult(
            destination,
            byte_size,
            media_type,
            filename=destination.name,
        )
