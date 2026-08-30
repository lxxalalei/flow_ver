"""Download one Z-Library book through the user's authenticated EAPI quota."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import mimetypes
from pathlib import Path
import re
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..policy import PolicyError, ensure_within_root, validate_public_http_url
from ..sessions import SessionStore
from .zlibrary_client import (
    ZLIBRARY_COOKIE_DOMAINS,
    ZlibraryAuthRequired,
    ZlibraryClient,
    ZlibraryError,
    ZlibraryLimitReached,
    ZlibraryNotFound,
    ZlibraryUnavailable,
    resource_identity,
)


_EXT_TO_MEDIA = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
    "azw3": "application/x-mobi8-ebook",
    "djvu": "image/vnd.djvu",
    "txt": "text/plain",
}


def _platform_signals(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = resource.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    signals = metadata.get("platform_signals")
    return signals if isinstance(signals, Mapping) else {}


def _safe_filename(resource: Mapping[str, Any], book_id: str) -> str:
    signals = _platform_signals(resource)
    extension = str(signals.get("format") or signals.get("extension") or "").strip()
    extension = extension.lstrip(".").casefold()
    if re.fullmatch(r"[0-9a-z][0-9a-z.+_-]{0,15}", extension) is None:
        extension = ""
    title = re.sub(
        r"[^0-9A-Za-z\u4e00-\u9fff._-]+",
        "-",
        str(resource.get("title") or f"zlibrary-{book_id}"),
    ).strip("-._")[:100]
    title = title or f"zlibrary-{book_id}"
    return f"{title}.{extension}" if extension else title


def _credential_root(domain: str) -> str:
    for root in ZLIBRARY_COOKIE_DOMAINS:
        if domain == root or domain.endswith(f".{root}"):
            return root
    return domain


class _CredentialSafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, credential_root: str) -> None:
        super().__init__()
        self.credential_root = credential_root

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urljoin(req.full_url, newurl)
        try:
            validate_public_http_url(target)
        except PolicyError as exc:
            raise DomainError("REDIRECT_BLOCKED", str(exc)) from exc
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected is None:
            return None
        host = (urlsplit(target).hostname or "").casefold().rstrip(".")
        if not (
            host == self.credential_root
            or host.endswith(f".{self.credential_root}")
        ):
            redirected.remove_header("Cookie")
            redirected.unredirected_hdrs.pop("Cookie", None)
        return redirected


class ZlibraryDownloader:
    def __init__(
        self,
        session_store: SessionStore,
        settings: Settings,
        *,
        client: ZlibraryClient | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or ZlibraryClient(
            session_store, timeout=float(settings.download_timeout_seconds)
        )

    def download(
        self,
        resource: Mapping[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        if strategy != "direct":
            raise DomainError("INVALID_ARGUMENT", "Z-Library 图书只支持 direct 获取")
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        identity = resource_identity(resource)
        if identity is None:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "Z-Library 资源缺少合法 book_id 或 book_hash",
                retryable=False,
            )
        book_id, book_hash = identity
        try:
            download_url, credentials = self.client.get_download_url(book_id, book_hash)
        except ZlibraryAuthRequired as exc:
            raise DomainError("AUTH_REQUIRED", str(exc), retryable=False) from exc
        except ZlibraryLimitReached as exc:
            raise DomainError("RATE_LIMITED", str(exc), retryable=True) from exc
        except ZlibraryNotFound as exc:
            raise DomainError("RESOURCE_NOT_FOUND", str(exc), retryable=False) from exc
        except ZlibraryUnavailable as exc:
            raise DomainError("PLATFORM_UNAVAILABLE", str(exc), retryable=True) from exc
        except ZlibraryError as exc:
            raise DomainError("DOWNLOAD_FAILED", str(exc), retryable=False) from exc

        try:
            validate_public_http_url(download_url)
        except PolicyError as exc:
            raise DomainError("NETWORK_BLOCKED", str(exc), retryable=False) from exc

        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)
        temporary = job_dir / "payload.part"
        request = Request(
            download_url,
            headers={
                "User-Agent": "EducationResourceMCP/0.4",
                "Accept": "application/octet-stream,*/*;q=0.8",
                "Cookie": credentials.cookie_header,
            },
        )
        opener = build_opener(
            _CredentialSafeRedirectHandler(_credential_root(credentials.domain))
        )
        size = 0
        media_type = "application/octet-stream"
        declared_size: int | None = None
        try:
            with opener.open(
                request, timeout=float(self.settings.download_timeout_seconds) * 3
            ) as response:
                media_type = response.headers.get_content_type() or media_type
                try:
                    declared_size = int(response.headers.get("Content-Length") or "")
                except ValueError:
                    declared_size = None
                with temporary.open("wb") as handle:
                    while True:
                        if cancel_event.is_set():
                            raise DomainError("JOB_CANCELLED", "下载已取消")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        size += len(chunk)
        except DomainError:
            temporary.unlink(missing_ok=True)
            raise
        except HTTPError as exc:
            temporary.unlink(missing_ok=True)
            if exc.code in (401, 403):
                raise DomainError("AUTH_REQUIRED", "Z-Library 下载登录态已失效") from exc
            if exc.code == 429:
                raise DomainError("RATE_LIMITED", "Z-Library 下载额度已用尽", retryable=True) from exc
            raise DomainError(
                "DOWNLOAD_FAILED", f"Z-Library 下载 HTTP {exc.code}", retryable=True
            ) from exc
        except (OSError, URLError) as exc:
            temporary.unlink(missing_ok=True)
            raise DomainError(
                "DOWNLOAD_FAILED", f"Z-Library 下载失败：{exc}", retryable=True
            ) from exc

        if size == 0:
            temporary.unlink(missing_ok=True)
            raise DomainError("CONTENT_VALIDATION_FAILED", "Z-Library 下载内容为空")
        if declared_size is not None and size != declared_size:
            temporary.unlink(missing_ok=True)
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                f"Z-Library 下载不完整：{size}/{declared_size} 字节",
                retryable=True,
            )
        extension = Path(_safe_filename(resource, book_id)).suffix.lstrip(".").casefold()
        if media_type in {"text/html", "application/json"} and extension not in {
            "html", "htm", "txt"
        }:
            temporary.unlink(missing_ok=True)
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "Z-Library 返回了网页或错误响应，而不是图书文件",
                retryable=True,
            )
        filename = _safe_filename(resource, book_id)
        destination = job_dir / filename
        index = 2
        while destination.exists():
            stem, suffix = Path(filename).stem, Path(filename).suffix
            destination = job_dir / f"{stem} ({index}){suffix}"
            index += 1
        ensure_within_root(destination, self.settings.jobs_dir)
        temporary.replace(destination)

        sha = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                sha.update(chunk)
        if media_type == "application/octet-stream":
            media_type = _EXT_TO_MEDIA.get(extension) or mimetypes.guess_type(filename)[0] or media_type
        return DownloadResult(
            destination,
            size,
            media_type,
            sha.hexdigest(),
            destination.name,
        )


__all__ = ["ZlibraryDownloader"]
