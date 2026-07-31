"""Controlled public HTTP downloader used by asynchronous jobs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import re
import threading
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import Settings
from .errors import DomainError
from .policy import PolicyError, ensure_within_root, validate_public_http_url


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    byte_size: int
    media_type: str
    sha256: str
    filename: str


class DownloadProvider(Protocol):
    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult: ...


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


class PublicHttpDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
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
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with opener.open(request, timeout=self.settings.download_timeout_seconds) as response:
                final_url = response.geturl()
                try:
                    validate_public_http_url(final_url)
                except PolicyError as exc:
                    raise DomainError("REDIRECT_BLOCKED", str(exc)) from exc
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise DomainError(
                        "DOWNLOAD_TOO_LARGE",
                        "资源声明大小超过下载上限",
                        details={"declared_bytes": int(declared), "max_bytes": max_bytes},
                    )
                media_type = response.headers.get_content_type() or "application/octet-stream"
                with temporary.open("wb") as handle:
                    while True:
                        if cancel_event.is_set():
                            raise DomainError("JOB_CANCELLED", "下载已取消")
                        chunk = response.read(min(64 * 1024, max_bytes - byte_size + 1))
                        if not chunk:
                            break
                        byte_size += len(chunk)
                        if byte_size > max_bytes:
                            raise DomainError(
                                "DOWNLOAD_TOO_LARGE",
                                "资源实际大小超过下载上限",
                                details={"max_bytes": max_bytes},
                            )
                        digest.update(chunk)
                        handle.write(chunk)
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
        destination = job_dir / filename
        ensure_within_root(destination, self.settings.jobs_dir)
        temporary.replace(destination)
        return DownloadResult(destination, byte_size, media_type, digest.hexdigest(), filename)
