"""CCTV video downloader: highest quality first, native handling only.

Plain streams are fetched directly (direct MP4 or HLS segments + ffmpeg mux).
H5E streams are fetched as ordered TS segments, concatenated while still
encrypted, then decrypted once with one stream-wide ``cctv_h5e.Session`` before
ffmpeg remux. Stream type never outranks picture quality.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..policy import ensure_within_root
from ..sessions import SessionStore
from .cctv_hls import (
    resolve_hls_uri,
    select_highest_bandwidth_variant,
    select_highest_quality_variant,
)
from .http_client import urlopen_with_fallback

LOGGER = logging.getLogger(__name__)

HEALTH_ERROR_THRESHOLD = 100
_H5E_DOWNLOAD_THREADS = 12
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_NUMERIC_M3U8_RE = re.compile(r"(?:^|/)(\d{3,5})\.m3u8(?:$|[?#])", re.IGNORECASE)

Quality = tuple[int | None, int | None]


def _safe_title(title: str) -> str:
    cleaned = _ILLEGAL_FILENAME_RE.sub("_", title).strip(" ._")
    return cleaned[:120] or "cctv_video"


def _run_with_cancel(
    cmd: list[str],
    *,
    timeout: float,
    cancel_event: Any = None,
) -> tuple[int, str, str]:
    """Run a subprocess while staying responsive to job cancellation."""

    import tempfile

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(cmd, stdout=stdout_file, stderr=stderr_file)
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                raise DomainError("JOB_CANCELLED", "下载已取消")
            if time.monotonic() > deadline:
                proc.kill()
                raise DomainError("DOWNLOAD_FAILED", "子进程执行超时", retryable=True)
            time.sleep(0.5)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", "replace")
        stderr = stderr_file.read().decode("utf-8", "replace")
    return proc.returncode, stdout or "", stderr or ""


def ffmpeg_error_count(mp4: Path) -> int | None:
    """Full-decode health check; error-line count, None when ffmpeg is absent."""

    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "null", os.devnull],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return len([line for line in proc.stderr.splitlines() if line.strip()])


def _download_stream_url(
    url: str,
    destination: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> None:
    destination.unlink(missing_ok=True)
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Referer": "https://tv.cctv.com/",
        },
    )
    try:
        with urlopen_with_fallback(request, timeout=timeout) as resp:
            with destination.open("wb") as out:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise DomainError("JOB_CANCELLED", "下载已取消")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _http_fetch_bytes(
    url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> bytes | None:
    """Retrying GET for one CCTV/HLS resource."""

    for attempt in range(4):
        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
                "Referer": "https://tv.cctv.com/",
            },
        )
        try:
            with urlopen_with_fallback(request, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            if attempt >= 3:
                return None
            time.sleep(1 + attempt)
    return None


def _hls_segments(playlist_text: str, playlist_url: str) -> list[str]:
    segments: list[str] = []
    for line in playlist_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        segments.append(resolve_hls_uri(playlist_url, line))
    return segments


def _fetch_playlist(
    playlist_url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
    error_prefix: str,
) -> tuple[str, str]:
    """Fetch a media playlist, resolving a master to its highest-quality variant."""

    body = _http_fetch_bytes(playlist_url, timeout=timeout, cancel_event=cancel_event)
    if body is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"{error_prefix}播放列表获取失败（{playlist_url[:120]}）",
            retryable=True,
        )
    text = body.decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" not in text:
        return playlist_url, text

    variant = select_highest_bandwidth_variant(text)
    if variant is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"{error_prefix}master 播放列表没有可识别的质量变体",
            retryable=True,
        )
    media_url = resolve_hls_uri(playlist_url, variant)
    body = _http_fetch_bytes(media_url, timeout=timeout, cancel_event=cancel_event)
    if body is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"{error_prefix}变体播放列表获取失败（{media_url[:120]}）",
            retryable=True,
        )
    return media_url, body.decode("utf-8", "replace")


def _remux_to_mp4(
    source_ts: Path,
    destination_mp4: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            "ffmpeg 未安装，无法将视频封装为 MP4",
            retryable=False,
        )
    code, _, stderr = _run_with_cancel(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_ts),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(destination_mp4),
        ],
        timeout=timeout,
        cancel_event=cancel_event,
    )
    if code != 0 or not destination_mp4.is_file():
        destination_mp4.unlink(missing_ok=True)
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"ffmpeg 封装失败：{stderr.strip()[-200:]}",
            retryable=True,
        )


def download_stream_native(
    url: str,
    title: str,
    job_dir: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> Path:
    """Download a plain CCTV stream (direct MP4 or HLS) to an MP4 file."""

    if url.startswith("http") and (".m3u8" in url or ".m3u" in url):
        media_url, text = _fetch_playlist(
            url,
            timeout=timeout,
            cancel_event=cancel_event,
            error_prefix="央视网 HLS ",
        )
        segment_urls = _hls_segments(text, media_url)
        if not segment_urls:
            raise DomainError("DOWNLOAD_FAILED", "央视网 HLS 没有分片列表", retryable=True)
        work_dir = job_dir / f"{title}_hls"
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            full_ts = work_dir / "full.ts"
            with full_ts.open("wb") as out:
                for index, segment_url in enumerate(segment_urls):
                    if cancel_event is not None and cancel_event.is_set():
                        raise DomainError("JOB_CANCELLED", "下载已取消")
                    data = _http_fetch_bytes(
                        segment_url, timeout=timeout, cancel_event=cancel_event
                    )
                    if data is None:
                        raise DomainError(
                            "DOWNLOAD_FAILED",
                            f"HLS 分片下载失败（{index + 1}/{len(segment_urls)}）",
                            retryable=True,
                        )
                    out.write(data)
            mp4 = job_dir / f"{title}.mp4"
            _remux_to_mp4(full_ts, mp4, timeout=timeout, cancel_event=cancel_event)
            return mp4
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    mp4 = job_dir / f"{title}.mp4"
    _download_stream_url(url, mp4, timeout=timeout, cancel_event=cancel_event)
    return mp4


def _fetch_media_m3u8(
    m3u8_url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> tuple[str, list[str]]:
    """Fetch an H5E media playlist, selecting its highest-quality variant."""

    media_url, text = _fetch_playlist(
        m3u8_url,
        timeout=timeout,
        cancel_event=cancel_event,
        error_prefix="h5e ",
    )
    segment_names = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not segment_names:
        raise DomainError(
            "DOWNLOAD_FAILED",
            "h5e m3u8 没有分片列表",
            retryable=True,
        )
    return media_url, segment_names


def _resource_h5e_url(resource: Mapping[str, Any]) -> str:
    metadata = resource.get("metadata")
    signals = (
        metadata.get("platform_signals") if isinstance(metadata, Mapping) else None
    ) or {}
    url = str(signals.get("h5e_url") or "").strip()
    return url if url.startswith("http") else ""


def download_h5e_native(
    resource: Mapping[str, Any],
    guid: str,
    title: str,
    job_dir: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
    h5e_url: str | None = None,
) -> Path:
    """Download and decrypt one H5E stream with one stream-wide Session."""

    m3u8_url = str(h5e_url or "").strip() or _resource_h5e_url(resource)
    if not m3u8_url.startswith("http"):
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "央视 H5E 下载缺少真实视频流地址",
            retryable=False,
        )

    t0 = time.monotonic()
    m3u8_url, segment_names = _fetch_media_m3u8(
        m3u8_url, timeout=timeout, cancel_event=cancel_event
    )
    work_dir = job_dir / f"{guid}_native_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        encrypted_dir = work_dir / "enc"
        encrypted_dir.mkdir(parents=True, exist_ok=True)

        def download_segment(index: int) -> bool:
            target = encrypted_dir / f"seg_{index:05d}.ts"
            if target.exists() and target.stat().st_size > 0:
                return True
            data = _http_fetch_bytes(
                resolve_hls_uri(m3u8_url, segment_names[index]),
                timeout=timeout,
                cancel_event=cancel_event,
            )
            if data is None:
                return False
            target.write_bytes(data)
            return True

        ok_count = 0
        with ThreadPoolExecutor(max_workers=_H5E_DOWNLOAD_THREADS) as pool:
            futures = [pool.submit(download_segment, i) for i in range(len(segment_names))]
            for future in as_completed(futures):
                if future.result():
                    ok_count += 1
        if ok_count < len(segment_names):
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"h5e 分片下载 {ok_count}/{len(segment_names)} 失败",
                retryable=True,
            )
        LOGGER.info(
            "cctv native: %d encrypted segments downloaded in %.1fs",
            len(segment_names),
            time.monotonic() - t0,
        )

        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")

        encrypted_ts = work_dir / "encrypted.ts"
        with encrypted_ts.open("wb") as out:
            for index in range(len(segment_names)):
                segment = encrypted_dir / f"seg_{index:05d}.ts"
                if not segment.is_file() or segment.stat().st_size == 0:
                    raise DomainError(
                        "DOWNLOAD_FAILED",
                        f"h5e 分片 {index} 缺失",
                        retryable=True,
                    )
                with segment.open("rb") as source:
                    shutil.copyfileobj(source, out)

        from .cctv_h5e import decrypt_ts

        t1 = time.monotonic()
        encrypted_bytes = encrypted_ts.read_bytes()
        plain_bytes, nal_count = decrypt_ts(encrypted_bytes)
        if nal_count <= 0:
            raise DomainError(
                "DOWNLOAD_FAILED",
                "h5e 原生解密未处理任何视频 NAL",
                retryable=True,
            )
        if len(plain_bytes) != len(encrypted_bytes):
            raise DomainError(
                "DOWNLOAD_FAILED",
                "h5e 原生解密异常改变了 TS 总长度",
                retryable=False,
            )
        decrypted_ts = work_dir / "decrypted.ts"
        decrypted_ts.write_bytes(plain_bytes)
        LOGGER.info(
            "cctv native: decrypted full TS (%d NALs) in %.1fs",
            nal_count,
            time.monotonic() - t1,
        )

        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")

        t2 = time.monotonic()
        mp4 = job_dir / f"{title}.mp4"
        _remux_to_mp4(decrypted_ts, mp4, timeout=timeout, cancel_event=cancel_event)
        LOGGER.info(
            "cctv native: mux in %.1fs (total %.1fs)",
            time.monotonic() - t2,
            time.monotonic() - t0,
        )
        return mp4
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _bandwidth_hint_from_url(url: str) -> int | None:
    """Read only explicit media bitrate hints; ``maxbr`` is not actual quality."""

    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        query = {}
    for key in ("br", "bandwidth"):
        values = query.get(key) or []
        if not values:
            continue
        try:
            value = int(values[0])
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value * 1000 if value < 100000 else value

    match = _NUMERIC_M3U8_RE.search(url)
    if match is None:
        return None
    value = int(match.group(1))
    return value * 1000 if value < 100000 else value


def _probe_stream_quality(
    url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> Quality:
    """Read one candidate playlist and return its best available quality facts."""

    body = _http_fetch_bytes(url, timeout=timeout, cancel_event=cancel_event)
    if body is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"无法探测候选流画质（{url[:120]}）",
            retryable=True,
        )
    text = body.decode("utf-8", "replace")
    selected = select_highest_quality_variant(text)
    if selected is not None:
        pixels, bandwidth = selected[1]
        return (pixels or None, bandwidth or None)
    return (None, _bandwidth_hint_from_url(url))


def _compare_quality(left: Quality, right: Quality) -> int | None:
    """Compare qualities; return 1/-1/0, or None when facts cannot prove order."""

    left_pixels, left_bandwidth = left
    right_pixels, right_bandwidth = right

    if left_pixels is not None or right_pixels is not None:
        if left_pixels is None or right_pixels is None:
            return None
        if left_pixels != right_pixels:
            return 1 if left_pixels > right_pixels else -1
        if left_bandwidth is None or right_bandwidth is None:
            return 0 if left_bandwidth == right_bandwidth else None
        if left_bandwidth == right_bandwidth:
            return 0
        return 1 if left_bandwidth > right_bandwidth else -1

    if left_bandwidth is None or right_bandwidth is None:
        return None
    if left_bandwidth == right_bandwidth:
        return 0
    return 1 if left_bandwidth > right_bandwidth else -1


def _select_best_stream(
    manifest: Mapping[str, Any],
    *,
    timeout: float,
    cancel_event: Any = None,
) -> tuple[str, str, Quality | None]:
    """Choose the video's highest-quality downloadable clear/H5E stream.

    Encryption type is not a ranking signal. Equal quality prefers clear because
    it avoids unnecessary decryption. When two real candidates cannot be
    compared from server facts, fail instead of guessing or silently degrading.
    """

    clear_url = str(manifest.get("hls_url") or "").strip()
    h5e_url = str(manifest.get("h5e_url") or "").strip()
    available: list[tuple[str, str]] = []
    if clear_url.startswith("http"):
        available.append(("clear", clear_url))
    if h5e_url.startswith("http"):
        available.append(("h5e", h5e_url))

    if not available:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "央视视频详情未提供可用 clear/H5E 流地址",
            retryable=False,
        )
    if len(available) == 1:
        kind, url = available[0]
        return kind, url, None

    clear_quality = _probe_stream_quality(
        clear_url, timeout=timeout, cancel_event=cancel_event
    )
    h5e_quality = _probe_stream_quality(
        h5e_url, timeout=timeout, cancel_event=cancel_event
    )
    comparison = _compare_quality(clear_quality, h5e_quality)
    if comparison is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            "同时存在 clear/H5E 流，但服务端信息不足以确认哪一个画质更高；"
            "为避免静默降质，本次不猜测",
            retryable=True,
        )
    if comparison >= 0:
        return "clear", clear_url, clear_quality
    return "h5e", h5e_url, h5e_quality


def _download_result(
    mp4: Path,
    *,
    guid: str,
    stream_type: str,
    health_errors: int,
) -> DownloadResult:
    byte_size = mp4.stat().st_size
    digest = hashlib.sha256()
    with mp4.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return DownloadResult(
        mp4,
        byte_size,
        "video/mp4",
        digest.hexdigest(),
        mp4.name,
        metadata={
            "guid": guid,
            "route": "native",
            "stream_type": stream_type,
            "health_errors": health_errors,
            "attempts": 1,
        },
    )


class CctvVideoDownloader:
    """Download one CCTV episode at the highest quality exposed by the server."""

    def __init__(
        self,
        session_store: SessionStore,
        settings: Settings,
        *,
        health_checker: Callable[[Path], int | None] | None = None,
        video_info_func: Callable[..., dict[str, Any] | None] | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = float(settings.download_timeout_seconds)
        self._health_checker = health_checker or ffmpeg_error_count
        self._video_info_func = video_info_func

    def download(
        self,
        resource: Mapping[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: Any,
    ) -> DownloadResult:
        if strategy != "direct":
            raise DomainError("INVALID_ARGUMENT", "央视视频只支持 direct 获取")
        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")

        metadata = resource.get("metadata")
        signals = (
            metadata.get("platform_signals") if isinstance(metadata, Mapping) else None
        ) or {}
        guid = str(signals.get("guid") or "").strip()
        title = _safe_title(str(resource.get("title") or "").strip() or guid)

        if not re.fullmatch(r"[0-9a-f]{32}", guid):
            from .cctv import resolve_episode

            resolved = resolve_episode(
                str(resource.get("source_url") or ""), timeout=self.timeout
            )
            if resolved is not None:
                guid = resolved["guid"]
                if not str(resource.get("title") or "").strip():
                    title = _safe_title(resolved["title"])
        if not re.fullmatch(r"[0-9a-f]{32}", guid):
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "央视视频缺少有效 32 位 guid，且无法从页面解析",
                retryable=False,
            )

        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        from .cctv import video_info

        manifest = (
            self._video_info_func(guid, timeout=self.timeout)
            if self._video_info_func is not None
            else video_info(guid, timeout=self.timeout)
        ) or {}
        selected_type, selected_url, quality = _select_best_stream(
            manifest,
            timeout=self.timeout,
            cancel_event=cancel_event,
        )
        LOGGER.info(
            "cctv selected highest stream: type=%s quality=%s url=%s",
            selected_type,
            quality,
            selected_url[:160],
        )

        try:
            if selected_type == "h5e":
                mp4 = download_h5e_native(
                    resource,
                    guid,
                    title,
                    job_dir,
                    timeout=self.timeout,
                    cancel_event=cancel_event,
                    h5e_url=selected_url,
                )
            else:
                mp4 = download_stream_native(
                    selected_url,
                    title,
                    job_dir,
                    timeout=self.timeout,
                    cancel_event=cancel_event,
                )
        except DomainError as exc:
            if exc.code == "JOB_CANCELLED":
                raise
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"央视最高画质 {selected_type} 流下载失败：{exc.message}。"
                "不自动改下更低画质或切换到其他流",
                retryable=exc.retryable,
            ) from exc
        except Exception as exc:
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"央视最高画质 {selected_type} 流下载异常："
                f"{type(exc).__name__}: {exc}。不自动降质",
                retryable=True,
            ) from exc

        health_errors = self._health_checker(mp4)
        if health_errors is None:
            mp4.unlink(missing_ok=True)
            raise DomainError(
                "DOWNLOAD_FAILED",
                "央视最高画质产物无法完成 ffmpeg 全解码体检；不自动降质",
                retryable=False,
            )
        if health_errors > HEALTH_ERROR_THRESHOLD:
            mp4.unlink(missing_ok=True)
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"央视最高画质产物体检失败（{health_errors} 错 > "
                f"{HEALTH_ERROR_THRESHOLD}）；不自动降质",
                retryable=False,
            )

        return _download_result(
            mp4,
            guid=guid,
            stream_type=selected_type,
            health_errors=health_errors,
        )


__all__ = [
    "CctvVideoDownloader",
    "download_h5e_native",
    "download_stream_native",
    "ffmpeg_error_count",
]
