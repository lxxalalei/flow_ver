"""CCTV video downloader: highest quality first, then stream-specific handling.

Plain streams are fetched directly (direct MP4 or HLS segments + ffmpeg mux).
H5E streams are fetched as ordered TS segments, concatenated while still
encrypted, then decrypted once with one stream-wide ``cctv_h5e.Session`` before
ffmpeg remux. The static WASM worker remains a same-stream fallback for H5E
until the native path is ready to remove it.
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

DEFAULT_H5E_PROJ = (
    Path(__file__).resolve().parent.parent / "vendor" / "cctv-h5e" / "runtime"
)
DEFAULT_H5E_BASE = "https://dh5ws01.v.cntv.cn/asp/h5e/hls/2000/0303000a/3/default"
DOWNLOAD_TIMEOUT_SECONDS = 3600
HEALTH_ERROR_THRESHOLD = 100
WASM_TIMEOUT_SECONDS = 2 * 3600
_WASM_DL_THREADS = 12
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
    cwd: Path | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess while staying responsive to job cancellation."""

    import tempfile

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(cmd, stdout=stdout_file, stderr=stderr_file, cwd=cwd)
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

    t0 = time.monotonic()
    m3u8_url = h5e_url or resolve_wasm_m3u8(resource, guid)
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
        with ThreadPoolExecutor(max_workers=_WASM_DL_THREADS) as pool:
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


def resolve_h5e_proj() -> Path:
    """Locate the static WASM runtime bundle."""

    candidates: list[Path] = []
    configured = os.environ.get("CCTV_H5E_PROJ", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.append(DEFAULT_H5E_PROJ)
    for candidate in candidates:
        try:
            if (
                candidate.is_dir()
                and (candidate / "main.js").is_file()
                and (candidate / "worker.js").is_file()
            ):
                return candidate
        except OSError:
            continue
    raise DomainError(
        "PROVIDER_UNAVAILABLE",
        "未找到 CCTV H5E 静态运行包（需要 main.js 和 worker.js）；"
        "请修复 education-resources 安装，或用环境变量 CCTV_H5E_PROJ 指向"
        "完整 bundle 目录",
        retryable=False,
    )


def resolve_wasm_m3u8(resource: Mapping[str, Any], guid: str) -> str:
    """Prefer a per-video h5e_url, otherwise retain the legacy template."""

    metadata = resource.get("metadata")
    signals = (
        metadata.get("platform_signals") if isinstance(metadata, Mapping) else None
    ) or {}
    h5e_url = str(signals.get("h5e_url") or "").strip()
    if h5e_url.startswith("http"):
        return h5e_url
    base = os.environ.get("CCTV_H5E_BASE", "").strip() or DEFAULT_H5E_BASE
    return f"{base.rstrip('/')}/{guid}/2000.m3u8"


def _http_fetch_bytes(
    url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> bytes | None:
    """Retrying GET for one HLS resource."""

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


def _bandwidth_hint_from_url(url: str) -> int | None:
    """Use explicit server URL hints only when a media playlist has no master."""

    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        query = {}
    for key in ("maxbr", "br", "bandwidth"):
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
    """Compare two stream qualities; return 1/-1/0, or None when unknowable."""

    left_pixels, left_bandwidth = left
    right_pixels, right_bandwidth = right

    if left_pixels is not None and right_pixels is not None:
        if left_pixels != right_pixels:
            return 1 if left_pixels > right_pixels else -1
        if left_bandwidth is not None and right_bandwidth is not None:
            if left_bandwidth == right_bandwidth:
                return 0
            return 1 if left_bandwidth > right_bandwidth else -1
        return None

    if left_bandwidth is not None and right_bandwidth is not None:
        if left_bandwidth != right_bandwidth:
            return 1 if left_bandwidth > right_bandwidth else -1
        if left_pixels is not None and right_pixels is None:
            return 1
        if right_pixels is not None and left_pixels is None:
            return -1
        return 0

    return None


def _select_best_stream(
    manifest: Mapping[str, Any],
    *,
    timeout: float,
    cancel_event: Any = None,
) -> tuple[str, str, Quality | None]:
    """Choose the video's highest-quality downloadable clear/H5E stream.

    Encryption type is not a ranking signal. When quality is equal, clear wins
    because it avoids unnecessary decryption. If two real candidates exist but
    their quality cannot be compared, fail rather than silently pick or degrade.
    """

    clear_url = str(manifest.get("hls_url") or "").strip()
    h5e_url = str(manifest.get("h5e_url") or "").strip()
    candidates = [
        ("clear", clear_url) if clear_url.startswith("http") else None,
        ("h5e", h5e_url) if h5e_url.startswith("http") else None,
    ]
    available = [item for item in candidates if item is not None]
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


def _wasm_decrypt_group(
    h5e_proj: Path,
    segment_names: list[str],
    output_ts: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> bool:
    """Decrypt one ordered local playlist through one WASM worker Session."""

    group_m3u8 = output_ts.with_suffix(".m3u8")
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:10"]
    lines.extend(segment_names)
    group_m3u8.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    code, _, _ = _run_with_cancel(
        [
            "node",
            str(h5e_proj / "main.js"),
            "--local-m3u8",
            str(group_m3u8),
            str(output_ts),
        ],
        timeout=timeout,
        cancel_event=cancel_event,
        cwd=h5e_proj,
    )
    return code == 0 and output_ts.is_file() and output_ts.stat().st_size > 0


def download_wasm(
    resource: Mapping[str, Any],
    guid: str,
    title: str,
    job_dir: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
    h5e_url: str | None = None,
) -> Path:
    """Download + decrypt + mux via one stream-wide static WASM Session."""

    if shutil.which("node") is None:
        raise DomainError(
            "PROVIDER_UNAVAILABLE",
            "WASM 降级需要 node 运行时（官方 worker 解密），当前 PATH 无 node",
            retryable=False,
        )
    h5e_proj = resolve_h5e_proj()
    m3u8_url = h5e_url or resolve_wasm_m3u8(resource, guid)
    m3u8_url, segment_names = _fetch_media_m3u8(
        m3u8_url, timeout=timeout, cancel_event=cancel_event
    )

    work_dir = job_dir / f"{guid}_wasmwork"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        def download_segment(index: int) -> bool:
            segment_file = work_dir / f"seg_{index:05d}.ts"
            if segment_file.exists() and segment_file.stat().st_size > 0:
                return True
            data = _http_fetch_bytes(
                resolve_hls_uri(m3u8_url, segment_names[index]),
                timeout=timeout,
                cancel_event=cancel_event,
            )
            if data is None:
                return False
            segment_file.write_bytes(data)
            return True

        t0 = time.monotonic()
        ok_count = 0
        with ThreadPoolExecutor(max_workers=_WASM_DL_THREADS) as pool:
            futures = [pool.submit(download_segment, i) for i in range(len(segment_names))]
            for future in as_completed(futures):
                if future.result():
                    ok_count += 1
        if ok_count < len(segment_names):
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"WASM 降级失败：分片下载 {ok_count}/{len(segment_names)}",
                retryable=True,
            )
        LOGGER.info(
            "cctv wasm: %d segments downloaded in %.1fs",
            len(segment_names),
            time.monotonic() - t0,
        )

        t1 = time.monotonic()
        ordered_segments = [f"seg_{index:05d}.ts" for index in range(len(segment_names))]
        full_ts = work_dir / "full.ts"
        ok = _wasm_decrypt_group(
            h5e_proj,
            ordered_segments,
            full_ts,
            timeout=WASM_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if not ok:
            raise DomainError(
                "DOWNLOAD_FAILED",
                "WASM 降级失败：完整 H5E stream 解密失败",
                retryable=True,
            )
        LOGGER.info(
            "cctv wasm: one stream-wide Session decrypted in %.1fs",
            time.monotonic() - t1,
        )

        t2 = time.monotonic()
        mp4 = job_dir / f"{title}.mp4"
        _remux_to_mp4(
            full_ts,
            mp4,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        LOGGER.info(
            "cctv wasm: mux in %.1fs (total %.1fs)",
            time.monotonic() - t2,
            time.monotonic() - t0,
        )
        return mp4
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _download_result(
    mp4: Path,
    *,
    guid: str,
    route: str,
    stream_type: str,
    health_errors: int | None,
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
            "route": route,
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
        video_info_func: Callable[[str, float], dict[str, Any] | None] | None = None,
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

        native_mp4: Path | None = None
        native_reason = ""
        selected_type = ""
        selected_url = ""
        hls_h5e = ""

        try:
            manifest = (
                self._video_info_func(guid, timeout=self.timeout)
                if self._video_info_func is not None
                else video_info(guid, timeout=self.timeout)
            )
            manifest = manifest or {}
            hls_h5e = str(manifest.get("h5e_url") or "").strip()
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

            if selected_type == "h5e":
                native_mp4 = download_h5e_native(
                    resource,
                    guid,
                    title,
                    job_dir,
                    timeout=self.timeout,
                    cancel_event=cancel_event,
                    h5e_url=selected_url,
                )
            else:
                native_mp4 = download_stream_native(
                    selected_url,
                    title,
                    job_dir,
                    timeout=self.timeout,
                    cancel_event=cancel_event,
                )
        except DomainError as exc:
            if exc.code == "JOB_CANCELLED":
                raise
            native_reason = f"自研下载失败：{exc.code}: {exc.message}"
        except Exception as exc:
            native_reason = f"自研下载异常：{type(exc).__name__}: {exc}"

        if native_mp4 is not None:
            native_errors = self._health_checker(native_mp4)
            if native_errors is not None and native_errors <= HEALTH_ERROR_THRESHOLD:
                return _download_result(
                    native_mp4,
                    guid=guid,
                    route="native",
                    stream_type=selected_type or "unknown",
                    health_errors=native_errors,
                )
            native_mp4.unlink(missing_ok=True)
            native_reason = f"自研产物体检失败（{native_errors} 错）"

        if selected_type == "clear":
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"央视最高画质 clear 流下载失败：{native_reason or '未知错误'}。"
                "为避免静默降质，不自动改下更低画质或切到其他流",
                retryable=False,
            )

        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")

        try:
            wasm_mp4 = download_wasm(
                resource,
                guid,
                title,
                job_dir,
                timeout=self.timeout,
                cancel_event=cancel_event,
                h5e_url=(
                    selected_url
                    if selected_type == "h5e" and selected_url.startswith("http")
                    else hls_h5e if hls_h5e.startswith("http") else None
                ),
            )
        except DomainError as exc:
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"央视视频下载失败：{native_reason or '自研路径未尝试'}；"
                f"WASM 降级失败（{exc.message}）",
                retryable=False,
            ) from exc

        wasm_errors = self._health_checker(wasm_mp4)
        if wasm_errors is None or wasm_errors <= HEALTH_ERROR_THRESHOLD:
            return _download_result(
                wasm_mp4,
                guid=guid,
                route="wasm",
                stream_type="h5e",
                health_errors=wasm_errors,
            )
        wasm_mp4.unlink(missing_ok=True)
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"央视视频下载失败：{native_reason or '自研路径未尝试'}；WASM 降级"
            f"体检失败（{wasm_errors} 错 > {HEALTH_ERROR_THRESHOLD}）。"
            "该视频可能加密形态特殊，需人工处理",
            retryable=False,
        )


__all__ = [
    "CctvVideoDownloader",
    "download_h5e_native",
    "download_stream_native",
    "download_wasm",
    "ffmpeg_error_count",
    "resolve_h5e_proj",
    "resolve_wasm_m3u8",
]
