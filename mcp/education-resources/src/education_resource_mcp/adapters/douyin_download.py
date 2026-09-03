"""Douyin video downloader.

Resolves the actual video stream URL via the detail API (a_bogus-signed)
and downloads the complete .mp4 in a single stream — no ffmpeg merge needed
(Douyin serves a single muxed file, unlike Bilibili's split DASH).

The a_bogus signature, device parameters and user agent are shared with
``douyin.py`` — the downloader imports them rather than duplicating.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..sessions import SessionStore
from ..policy import ensure_within_root
from .douyin import (
    USER_AGENT,
    _AdapterError as _DouyinAdapterError,
    _AWEME_ID_RE,
    _COMMON_PARAMS,
    sign_a_bogus,
)
from .http_client import urlopen_with_fallback


DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"


def _request_json(url: str, cookie: str) -> dict[str, Any]:
    """Fetch the signed detail JSON, retrying once on risk-control blocks."""

    import time

    for attempt in range(2):
        try:
            return _request_json_once(url, cookie)
        except DomainError as exc:
            if not exc.retryable or attempt > 0:
                raise
            time.sleep(3.0)
    raise DomainError("DOWNLOAD_FAILED", "抖音详情请求失败", retryable=True)


def _request_json_once(url: str, cookie: str) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, headers=headers)
    try:
        with urlopen_with_fallback(request, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code == 403:
            # Risk control, not a broken login; retrying later often passes.
            raise DomainError("NETWORK_BLOCKED", "抖音详情被风控拦截（HTTP 403）", retryable=True)
        raise DomainError("DOWNLOAD_FAILED", f"抖音详情 API HTTP {exc.code}", retryable=exc.code >= 500)
    except (TimeoutError, URLError) as exc:
        raise DomainError("DOWNLOAD_FAILED", f"抖音详情请求失败: {type(exc).__name__}", retryable=True)
    if not body or body == "blocked":
        raise DomainError("DOWNLOAD_FAILED", "抖音详情被拦截", retryable=True)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise DomainError("DOWNLOAD_FAILED", "抖音详情响应不是有效 JSON", retryable=False)


def _extract_video_url(aweme_detail: dict[str, Any]) -> str:
    """Extract the best video download URL from aweme_detail (mirrors MediaCrawler)."""
    video = aweme_detail.get("video") or {}
    for key in ("play_addr_h264", "play_addr_256", "play_addr"):
        urls = (video.get(key) or {}).get("url_list") or []
        if urls:
            return str(urls[-1])
    return ""


def _stream_download(
    url: str, dest: Path, cookie: str,
    cancel_event: threading.Event,
    max_retries: int = 3,
) -> int:
    """Stream-download with automatic retry on transient network errors.

    Retries up to *max_retries* times with exponential backoff (1s, 2s).
    Partial files are deleted before each retry.  Business exceptions
    JOB_CANCELLED propagates immediately without retry.
    """
    import time
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        try:
            written = 0
            headers = {"User-Agent": USER_AGENT, "Referer": "https://www.douyin.com/"}
            if cookie:
                headers["Cookie"] = cookie
            request = Request(url, headers=headers)
            with urlopen_with_fallback(request, timeout=120) as response:
                with dest.open("wb") as f:
                    while True:
                        if cancel_event.is_set():
                            raise DomainError("JOB_CANCELLED", "下载已取消")
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        f.write(chunk)
            return written
        except DomainError:
            raise
        except Exception as exc:
            last_exc = exc
            dest.unlink(missing_ok=True)
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                for _ in range(wait):
                    if cancel_event.is_set():
                        raise DomainError("JOB_CANCELLED", "下载已取消")
                    time.sleep(1)
    raise DomainError(
        "DOWNLOAD_FAILED",
        f"下载失败（重试 {max_retries} 次后仍失败）: {type(last_exc).__name__}: {last_exc}",
        retryable=True,
    )


class DouyinDownloader:
    """Download Douyin videos via the a_bogus-signed detail API.

    Unlike Bilibili (split DASH), Douyin serves a single muxed .mp4 — no
    ffmpeg merge step is needed.
    """

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.settings = settings

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        url = str(resource["source_url"])
        title = str(resource.get("title") or "douyin_video")
        match = _AWEME_ID_RE.search(url)
        if not match:
            raise DomainError("DOWNLOAD_FAILED", f"无法从 URL 解析 aweme_id: {url}", retryable=False)
        aweme_id = match.group(1)

        session_data = self.session_store.get_session_data("douyin")
        if not session_data:
            raise DomainError("AUTH_REQUIRED", "未保存抖音登录态，请先登录", retryable=False)
        cookie = SessionStore._cookie_header(session_data)

        # 1. Build signed detail request
        params = {**_COMMON_PARAMS, "aweme_id": aweme_id}
        query_string = urlencode(params)
        try:
            params["a_bogus"] = sign_a_bogus(query_string, USER_AGENT)
        except _DouyinAdapterError as exc:
            raise DomainError("DOWNLOAD_FAILED", exc.message, retryable=exc.retryable)

        # 2. Fetch detail
        detail = _request_json(f"{DETAIL_URL}?{urlencode(params)}", cookie)
        aweme_detail = detail.get("aweme_detail") or {}
        if not aweme_detail:
            raise DomainError("DOWNLOAD_FAILED", "抖音详情 API 未返回 aweme_detail", retryable=True)

        # 3. Extract video URL
        video_url = _extract_video_url(aweme_detail)
        if not video_url:
            raise DomainError("DOWNLOAD_FAILED", "视频无可用下载地址", retryable=False)

        # 4. Download
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        page_title = str(aweme_detail.get("desc") or title)[:80]
        safe_title = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", page_title).strip("-._")[:80] or f"douyin_{aweme_id}"
        output = job_dir / f"{safe_title}.mp4"
        ensure_within_root(output, self.settings.jobs_dir)

        tmp = output.with_suffix(".tmp")
        try:
            byte_size = _stream_download(video_url, tmp, cookie, cancel_event)
            tmp.rename(output)
        except DomainError:
            tmp.unlink(missing_ok=True)
            raise

        # 5. SHA-256
        sha = hashlib.sha256()
        with output.open("rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                sha.update(chunk)

        return DownloadResult(output, byte_size, "video/mp4", sha.hexdigest(), output.name)
