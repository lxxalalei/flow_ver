"""Anna's Archive book downloader (Libgen-backed).

Downloads books anonymously from Libgen mirrors. md5 identifiers match
Anna's Archive. Supports mirror failover and cancellation.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..policy import ensure_within_root
from ..sessions import SessionStore
from .libgen_client import LibgenError, _MD5_RE, create_libgen_client


_EXT_TO_MEDIA = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
    "djvu": "image/vnd.djvu",
    "azw3": "application/x-mobi8-ebook",
    "txt": "text/plain",
}


class AnnasArchiveDownloader:
    """Download books from Libgen mirrors (anonymous, no account)."""

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.settings = settings
        self._client = create_libgen_client(float(settings.download_timeout_seconds))

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        # Extract md5 from platform_signals or source_url
        signals = (resource.get("metadata") or {}).get("platform_signals") or {}
        md5 = signals.get("md5", "")
        if not md5:
            url = str(resource.get("source_url") or "")
            m = _MD5_RE.search(url)
            md5 = m.group(0) if m else ""
        if not md5:
            raise DomainError("DOWNLOAD_FAILED", "无法从资源中提取 md5", retryable=False)

        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        try:
            result = self._client.download(
                md5, job_dir, cancel_event=cancel_event,
            )
        except LibgenError as exc:
            msg = str(exc)
            if "CANCELLED" in msg:
                raise DomainError("JOB_CANCELLED", "下载已取消") from exc
            raise DomainError(
                "DOWNLOAD_FAILED", f"Libgen 下载失败: {exc}", retryable=True
            ) from exc

        ensure_within_root(result.path, self.settings.jobs_dir)

        # SHA-256
        sha = hashlib.sha256()
        with result.path.open("rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                sha.update(chunk)

        ext = result.path.suffix.lstrip(".").lower()
        media_type = _EXT_TO_MEDIA.get(ext, "application/octet-stream")

        return DownloadResult(
            result.path, result.size_bytes, media_type, sha.hexdigest(), result.filename
        )
