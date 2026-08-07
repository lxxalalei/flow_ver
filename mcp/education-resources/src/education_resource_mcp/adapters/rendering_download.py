"""Rendering downloader for web-page resources.

Web-page resources whose actual content is rendered by JavaScript (articles,
lecture pages, interactive pages) cannot be captured by a plain HTTP GET — the
response body is an empty HTML shell.  :class:`RenderingDownloader` replaces
that path by driving a short-lived headless Chrome through CDP and saving the
fully rendered page as a standard visual-archive file: MHTML by default, with
optional PDF and full-page PNG.

It implements the same :class:`~education_resource_mcp.downloader.DownloadProvider`
contract as the platform downloaders, so it plugs into the existing
``Flow -> Plan -> Job -> Asset`` pipeline unchanged.  The downloaded file flows
through the ordinary job/asset/archive bookkeeping and safety checks.
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Any

from ..cdp_renderer import CDPRenderer
from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..policy import PolicyError, ensure_within_root, validate_public_http_url
from ..sessions import SessionStore


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", title).strip("-._")
    return cleaned[:80] or "page"


class RenderingDownloader:
    """Render a web page into a standard visual-archive file via CDP."""

    def __init__(
        self,
        settings: Settings,
        *,
        session_store: SessionStore | None = None,
        renderer: CDPRenderer | None = None,
    ) -> None:
        self.settings = settings
        self.session_store = session_store
        self.renderer = renderer or CDPRenderer()

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        if strategy != "webpage":
            raise DomainError(
                "INVALID_ARGUMENT", "RenderingDownloader 只处理 webpage 策略"
            )
        url = str(resource["source_url"])
        try:
            validate_public_http_url(url)
        except PolicyError as exc:
            raise DomainError("NETWORK_BLOCKED", str(exc)) from exc

        # Which visual formats to produce.  Default to MHTML; the resource may
        # carry an explicit preference (pdf / png) chosen by the user flow.
        formats = self._resolved_formats(resource)
        cookies = self._session_cookies(resource)

        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        produced = self.renderer.render(
            url,
            job_dir,
            formats=formats,
            max_bytes=max_bytes,
            cancel_event=cancel_event,
            cookies=cookies,
        )
        if not produced:
            raise DomainError("CONTENT_VALIDATION_FAILED", "渲染没有产生任何文件")

        # Defense in depth: re-check every produced file against the size cap
        # even though the renderer already enforces it, because the produced
        # paths are untrusted from this adapter's perspective.
        for path, _media_type, _suffix, _desc in produced:
            if path.stat().st_size > max_bytes:
                raise DomainError(
                    "DOWNLOAD_TOO_LARGE",
                    "渲染结果超过大小上限",
                    details={"max_bytes": max_bytes, "byte_size": path.stat().st_size},
                )

        # Prefer MHTML as the primary asset; fall back to the first produced.
        primary = next(
            (item for item in produced if item[2] == ".mhtml"), produced[0]
        )
        path, media_type, _suffix, _desc = primary
        byte_size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        filename = f"{_safe_title(str(resource.get('title') or 'page'))}{_suffix}"
        destination = job_dir / filename
        ensure_within_root(destination, self.settings.jobs_dir)
        # The renderer already wrote ``page.mhtml``; rename it to the final name.
        if destination != path:
            if destination.exists():
                destination.unlink()
            path.replace(destination)
        return DownloadResult(
            destination, byte_size, media_type, sha256, filename
        )

    def _resolved_formats(self, resource: dict[str, Any]) -> set[str]:
        preferred = str(resource.get("preferred_container") or resource.get("format") or "")
        mapping = {
            "html": {"mhtml"},
            "text": {"mhtml"},
            "pdf": {"mhtml", "pdf"},
            "png": {"mhtml", "png"},
        }
        return mapping.get(preferred, {"mhtml"})

    def _session_cookies(self, resource: dict[str, Any]) -> str:
        if self.session_store is None:
            return ""
        platform = str(resource.get("platform") or "")
        if not platform:
            return ""
        session_data = self.session_store.get_session_data(platform)
        if not session_data:
            return ""
        return SessionStore._cookie_header(session_data)
