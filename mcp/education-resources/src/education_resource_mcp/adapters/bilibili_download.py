"""Bilibili video downloader.

Resolves the actual video stream URL via the playurl API (WBI-signed) and
downloads DASH video+audio, merging them into a single .mp4 with ffmpeg.

Reuses the WBI signing algorithm and HTTP helpers from the search adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..sessions import SessionStore
from ..policy import PolicyError, ensure_within_root
from .http_client import urlopen_with_fallback
from .wbi import wbi_sign

# Console-subsystem children (ffmpeg) must not pop a visible console window
# when the MCP server runs under a hidden gateway parent on Windows.
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
PLAYURL_URL = "https://api.bilibili.com/x/player/wbi/playurl"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
)

_BV_RE = re.compile(r"BV[A-Za-z0-9]{10}")


def _request_json(url: str, cookie: str = "") -> dict[str, Any]:
    headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, headers=headers)
    with urlopen_with_fallback(request, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _stream_download(
    url: str, dest: Path, cookie: str, cancel_event: threading.Event
) -> int:
    """Download a single stream to *dest*, return byte count."""
    request = Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Cookie": cookie,
    })
    digest_written = 0
    with urlopen_with_fallback(request, timeout=60) as response:
        with dest.open("wb") as f:
            while True:
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                digest_written += len(chunk)
                f.write(chunk)
    return digest_written


class BilibiliDownloader:
    """Download Bilibili videos via the WBI-signed playurl API.

    Downloads DASH video and audio streams, then merges them into a
    single .mp4 file using ffmpeg.  Cookie is optional but recommended
    for higher quality.
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
        title = str(resource.get("title") or "bilibili_video")
        bv_match = _BV_RE.search(url)
        if not bv_match:
            raise DomainError("DOWNLOAD_FAILED", f"无法从 URL 解析 BV 号: {url}")
        bvid = bv_match.group(0)

        # Cookie (optional)
        session_data = self.session_store.get_session_data("bilibili")
        cookie = SessionStore._cookie_header(session_data) if session_data else ""

        # 1. Get WBI keys
        nav = _request_json(NAV_URL, cookie)
        wbi = (nav.get("data") or {}).get("wbi_img") or {}
        img_key = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
        sub_key = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
        if not img_key or not sub_key:
            raise DomainError("DOWNLOAD_FAILED", "B站未返回 WBI 密钥", retryable=True)

        # 2. Get cid
        view = _request_json(f"{VIEW_URL}?bvid={bvid}", cookie)
        if view.get("code") != 0:
            raise DomainError("DOWNLOAD_FAILED", f"获取视频信息失败: {view.get('message')}", retryable=False)
        view_data = view.get("data") or {}
        cid = view_data.get("cid")
        page_title = str(view_data.get("title") or title)[:80]
        if not cid:
            raise DomainError("DOWNLOAD_FAILED", "视频缺少 cid")

        # 3. Get playurl (DASH)
        params = wbi_sign(
            {"bvid": bvid, "cid": str(cid), "qn": "80", "fnval": "16", "fourk": "1"},
            img_key, sub_key,
        )
        play = _request_json(f"{PLAYURL_URL}?{urlencode(params)}", cookie)
        if play.get("code") != 0:
            raise DomainError("DOWNLOAD_FAILED", f"playurl 失败: {play.get('message')}", retryable=True)

        play_data = play.get("data") or {}
        dash = play_data.get("dash")
        if not dash:
            raise DomainError("DOWNLOAD_FAILED", "视频不支持的格式（非 DASH）", retryable=False)

        videos = sorted(
            [v for v in (dash.get("video") or []) if v.get("baseUrl") or v.get("base_url")],
            key=lambda v: int(v.get("bandwidth") or v.get("id") or 0),
        )
        audios = sorted(
            [a for a in (dash.get("audio") or []) if a.get("baseUrl") or a.get("base_url")],
            key=lambda a: int(a.get("bandwidth") or 0),
        )
        if not videos:
            raise DomainError("DOWNLOAD_FAILED", "无可用视频流")

        def _stream_url(s: dict) -> str:
            return str(s.get("baseUrl") or s.get("base_url") or "")

        video_url = _stream_url(videos[-1])
        audio_url = _stream_url(audios[-1]) if audios else ""

        # 4. Download streams
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        safe_title = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", page_title).strip("-._")[:80] or "video"
        v_tmp = job_dir / f".{safe_title}_video.m4s"
        a_tmp = job_dir / f".{safe_title}_audio.m4s" if audio_url else None
        output = job_dir / f"{safe_title}.mp4"
        ensure_within_root(output, self.settings.jobs_dir)

        try:
            _stream_download(video_url, v_tmp, cookie, cancel_event)
            a_size = 0
            if a_tmp and audio_url:
                a_size = _stream_download(audio_url, a_tmp, cookie, cancel_event)
        except DomainError:
            v_tmp.unlink(missing_ok=True)
            if a_tmp:
                a_tmp.unlink(missing_ok=True)
            raise

        # 5. Merge with ffmpeg
        cmd = ["ffmpeg", "-y", "-i", str(v_tmp), "-i", str(v_tmp)]
        if a_tmp and a_size > 0:
            cmd = ["ffmpeg", "-y", "-i", str(v_tmp), "-i", str(a_tmp),
                   "-c", "copy", "-movflags", "+faststart", str(output)]
        else:
            cmd = ["ffmpeg", "-y", "-i", str(v_tmp), "-c", "copy",
                   "-movflags", "+faststart", str(output)]

        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=120,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if result.returncode != 0:
                raise DomainError(
                    "DOWNLOAD_FAILED",
                    f"ffmpeg 合并失败: {result.stderr.decode('utf-8', 'replace')[:200]}",
                    retryable=False,
                )
        except FileNotFoundError:
            raise DomainError("DOWNLOAD_FAILED", "ffmpeg 未安装，无法合并视频", retryable=False)
        finally:
            v_tmp.unlink(missing_ok=True)
            if a_tmp:
                a_tmp.unlink(missing_ok=True)

        # Compute sha256 of merged file
        sha = hashlib.sha256()
        with output.open("rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                sha.update(chunk)
        final_size = output.stat().st_size

        return DownloadResult(output, final_size, "video/mp4", sha.hexdigest(), output.name)
