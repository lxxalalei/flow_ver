"""CCTV video downloader: fully native Python (0069), WASM kept as fallback.

Native route (M2): plain streams are fetched directly (direct MP4 or HLS
segments + ffmpeg mux); h5e streams are fetched as segments and decrypted
in parallel worker processes by the ported ``cctv_h5e`` module. The official
WASM worker remains only as a fallback until real-world comparison proves the
native decryptor end to end. The m3u8 prefers the per-video ``h5e_url`` from
``getHttpVideoInfo``; the fixed ``H5E_BASE`` template is only a fallback.
"""

from __future__ import annotations

import hashlib
import json
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
from urllib.parse import urlsplit
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadResult

LOGGER = logging.getLogger(__name__)
from ..errors import DomainError
from ..policy import ensure_within_root
from ..sessions import SessionStore
from .http_client import urlopen_with_fallback

# Vendored inside this package (MIT, github.com/xiaoxi-ij478/cctv-h5e-decrypt);
# node_modules is regenerated with `npm ci` there.
DEFAULT_H5E_PROJ = (
    Path(__file__).resolve().parent.parent / "vendor" / "cctv-h5e"
)
# Fixed h5e m3u8 template used only when the per-video h5e_url is unavailable.
# Its generality is unconfirmed; CCTV_H5E_BASE can override it.
DEFAULT_H5E_BASE = "https://dh5ws01.v.cntv.cn/asp/h5e/hls/2000/0303000a/3/default"
DOWNLOAD_TIMEOUT_SECONDS = 3600
HEALTH_ERROR_THRESHOLD = 100
WASM_TIMEOUT_SECONDS = 2 * 3600
_WASM_DL_THREADS = 12
_WASM_PARALLEL = 4
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


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
    """Run a subprocess while staying responsive to job cancellation.

    Output is redirected to temp files instead of PIPE: a child that floods
    stderr (e.g. ffmpeg decoding a corrupt stream) would otherwise block on a
    full pipe buffer while the poll loop never drains it (PIPE deadlock).
    ``cwd`` matters for the node/tsx WASM worker — tsx resolves from the
    vendored project's node_modules, never from the caller's directory.
    """

    import tempfile

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=cwd,
        )
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                raise DomainError("JOB_CANCELLED", "下载已取消")
            if time.monotonic() > deadline:
                proc.kill()
                raise DomainError(
                    "DOWNLOAD_FAILED", "子进程执行超时", retryable=True
                )
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
            [
                "ffmpeg", "-v", "error", "-i", str(mp4),
                "-f", "null", os.devnull,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return len([line for line in proc.stderr.splitlines() if line.strip()])


def _unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    for index in range(2, 1000):
        candidate = destination.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    return destination


def _download_stream_url(
    url: str,
    destination: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> None:
    """Stream one direct media URL (plain MP4) into ``destination``."""

    destination.unlink(missing_ok=True)
    request = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://tv.cctv.com/",
    })
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


def _hls_segments(playlist_text: str, base_url: str) -> list[str]:
    segments: list[str] = []
    for line in playlist_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        segment = line if line.startswith("http") else f"{base_url}/{line}"
        segments.append(segment)
    return segments


def _remux_to_mp4(
    source_ts: Path,
    destination_mp4: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> None:
    """ffmpeg remux TS -> MP4 (copy codecs, faststart)."""

    if shutil.which("ffmpeg") is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            "ffmpeg 未安装，无法将视频封装为 MP4",
            retryable=False,
        )
    code, _, stderr = _run_with_cancel(
        ["ffmpeg", "-y", "-i", str(source_ts), "-c", "copy",
         "-movflags", "+faststart", str(destination_mp4)],
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
    """Download a plain CCTV stream (direct MP4 or HLS) to an MP4 file.

    HLS playlists are fetched, segments downloaded and concatenated, then
    remuxed with ffmpeg. Direct media URLs are streamed as-is.
    """

    if url.startswith("http") and (".m3u8" in url or ".m3u" in url):
        text = _http_fetch_bytes(url, timeout=timeout, cancel_event=cancel_event)
        if text is None:
            raise DomainError(
                "DOWNLOAD_FAILED",
                "央视网 HLS 播放列表获取失败",
                retryable=True,
            )
        if "#EXT-X-STREAM-INF" in text.decode("utf-8", "replace"):
            raise DomainError(
                "FEATURE_NOT_SUPPORTED",
                "央视网多码率 HLS 主列表暂不支持自动选变体",
                retryable=False,
            )
        base_url = url.rsplit("/", 1)[0]
        segment_urls = _hls_segments(text.decode("utf-8", "replace"), base_url)
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
            import shutil as _shutil

            _shutil.rmtree(work_dir, ignore_errors=True)

    mp4 = job_dir / f"{title}.mp4"
    _download_stream_url(url, mp4, timeout=timeout, cancel_event=cancel_event)
    return mp4


def _decrypt_segment(work: tuple[str, str]) -> int:
    """Multiprocessing target: decrypt one h5e TS segment in place."""

    from .cctv_h5e import decrypt_ts

    source_path, target_path = work
    with open(source_path, "rb") as handle:
        encrypted = handle.read()
    plain, nal_count = decrypt_ts(encrypted)
    with open(target_path, "wb") as handle:
        handle.write(plain)
    return nal_count


def _fetch_media_m3u8(
    m3u8_url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> tuple[str, list[str]]:
    """Fetch an h5e m3u8, resolving a master playlist to its 2000 variant.

    Returns (media_url, segment_names). Raises DomainError on fetch failure.
    """

    body = _http_fetch_bytes(m3u8_url, timeout=timeout, cancel_event=cancel_event)
    if body is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"h5e m3u8 获取失败（{m3u8_url[:120]}）",
            retryable=True,
        )
    text = body.decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" in text:
        variant = next(
            (
                line.strip()
                for line in text.splitlines()
                if line.strip() and not line.startswith("#")
            ),
            None,
        )
        if variant is None:
            raise DomainError(
                "DOWNLOAD_FAILED",
                "h5e master 播放列表没有变体",
                retryable=True,
            )
        # h5e_url carries query params (main.m3u8?maxbr=2048&...) — strip them
        # before deriving the base; variants may be absolute paths.
        base = m3u8_url.split("?", 1)[0].rsplit("/", 1)[0]
        if variant.startswith("/"):
            parsed = urlsplit(m3u8_url)
            m3u8_url = f"{parsed.scheme}://{parsed.netloc}{variant}"
        elif variant.startswith("http"):
            m3u8_url = variant
        else:
            m3u8_url = f"{base}/{variant}"
        body = _http_fetch_bytes(m3u8_url, timeout=timeout, cancel_event=cancel_event)
        if body is None:
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"h5e 变体 m3u8 获取失败（{m3u8_url[:120]}）",
                retryable=True,
            )
        text = body.decode("utf-8", "replace")
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
    return m3u8_url, segment_names


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
    """Download + decrypt an h5e stream natively (no external runtime).

    Segments are fetched concurrently, decrypted in parallel worker processes
    (each segment is an independent equal-length TEA/type transform), joined
    in order and remuxed with ffmpeg. ``h5e_url`` (from getHttpVideoInfo)
    takes precedence over the resource signals / template.
    """

    t0 = time.monotonic()
    m3u8_url = h5e_url or resolve_wasm_m3u8(resource, guid)
    m3u8_url, segment_names = _fetch_media_m3u8(
        m3u8_url, timeout=timeout, cancel_event=cancel_event
    )
    base_url = m3u8_url.split("?", 1)[0].rsplit("/", 1)[0]
    work_dir = job_dir / f"{guid}_native_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        encrypted_dir = work_dir / "enc"
        decrypted_dir = work_dir / "dec"
        encrypted_dir.mkdir(parents=True, exist_ok=True)
        decrypted_dir.mkdir(parents=True, exist_ok=True)

        # 1) concurrent segment download
        def download_segment(index: int) -> bool:
            target = encrypted_dir / f"seg_{index:05d}.ts"
            if target.exists() and target.stat().st_size > 0:
                return True
            data = _http_fetch_bytes(
                f"{base_url}/{segment_names[index]}",
                timeout=timeout,
                cancel_event=cancel_event,
            )
            if data is None:
                return False
            target.write_bytes(data)
            return True

        ok_count = 0
        with ThreadPoolExecutor(max_workers=_WASM_DL_THREADS) as pool:
            futures = [
                pool.submit(download_segment, i) for i in range(len(segment_names))
            ]
            for future in as_completed(futures):
                if future.result():
                    ok_count += 1
        if ok_count < len(segment_names):
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"h5e 分片下载 {ok_count}/{len(segment_names)} 失败",
                retryable=True,
            )
        LOGGER.info("cctv native: %d segments downloaded in %.1fs", len(segment_names), time.monotonic() - t0)

        # 2) parallel native decryption (each segment independent)
        from concurrent.futures import ProcessPoolExecutor

        t1 = time.monotonic()
        work_items = [
            (
                str(encrypted_dir / f"seg_{i:05d}.ts"),
                str(decrypted_dir / f"seg_{i:05d}.ts"),
            )
            for i in range(len(segment_names))
        ]
        workers = max(1, min(os.cpu_count() or 4, 8))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            nal_counts = list(pool.map(_decrypt_segment, work_items))
        LOGGER.info("cctv native: decrypt %d segments in %.1fs", len(segment_names), time.monotonic() - t1)

        # 3) join in order and remux
        t2 = time.monotonic()
        full_ts = work_dir / "full.ts"
        with full_ts.open("wb") as out:
            for i in range(len(segment_names)):
                decrypted = decrypted_dir / f"seg_{i:05d}.ts"
                if not decrypted.exists() or decrypted.stat().st_size == 0:
                    raise DomainError(
                        "DOWNLOAD_FAILED",
                        f"h5e 分片 {i} 解密失败（NAL={nal_counts[i]}）",
                        retryable=True,
                    )
                out.write(decrypted.read_bytes())
        mp4 = job_dir / f"{title}.mp4"
        _remux_to_mp4(full_ts, mp4, timeout=timeout, cancel_event=cancel_event)
        LOGGER.info("cctv native: mux+health in %.1fs (total %.1fs)", time.monotonic() - t2, time.monotonic() - t0)
        return mp4
    finally:
        import shutil as _shutil

        _shutil.rmtree(work_dir, ignore_errors=True)


def resolve_h5e_proj() -> Path:
    """Locate the WASM worker project: the package-internal vendor first,
    ``CCTV_H5E_PROJ`` as an override."""

    candidates: list[Path] = []
    configured = os.environ.get("CCTV_H5E_PROJ", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.append(DEFAULT_H5E_PROJ)
    for candidate in candidates:
        try:
            if candidate.is_dir() and (candidate / "src" / "cli" / "main.ts").is_file():
                return candidate
        except OSError:
            continue
    raise DomainError(
        "PROVIDER_UNAVAILABLE",
        "未找到 h5e 解密工程（含 src/cli/main.ts）。包内 vendor 目录缺失或未安装"
        "依赖：请运行 `cd mcp/education-resources/vendor/cctv-h5e && npm ci`；"
        "或用环境变量 CCTV_H5E_PROJ 指向其他安装",
        retryable=False,
    )


def resolve_wasm_m3u8(resource: Mapping[str, Any], guid: str) -> str:
    """Prefer the per-video h5e_url from getHttpVideoInfo, else the template."""

    metadata = resource.get("metadata")
    signals = (
        metadata.get("platform_signals")
        if isinstance(metadata, Mapping)
        else None
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
    """Retrying GET for one h5e segment (returns None after repeated failure)."""

    for attempt in range(4):
        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        request = Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Referer": "https://tv.cctv.com/",
        })
        try:
            with urlopen_with_fallback(request, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            if attempt >= 3:
                return None
            time.sleep(1 + attempt)
    return None


def _wasm_decrypt_group(
    h5e_proj: Path,
    segment_names: list[str],
    output_ts: Path,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> bool:
    """Decrypt one group of segments through the official WASM worker."""

    group_m3u8 = output_ts.with_suffix(".m3u8")
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:10"]
    lines.extend(segment_names)
    # newline='\n' keeps segment names free of \r on Windows.
    group_m3u8.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    code, _, stderr = _run_with_cancel(
        [
            "node", "--import", "tsx", "src/cli/main.ts", "--local-m3u8",
            str(group_m3u8), str(output_ts),
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
    """Download + decrypt + mux via the official WASM worker; returns MP4 path.

    Raises DomainError with a truthful reason on any stage failure.
    """

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
    base_url = m3u8_url.split("?", 1)[0].rsplit("/", 1)[0]

    work_dir = job_dir / f"{guid}_wasmwork"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        # 1) download all segments concurrently
        def download_segment(index: int) -> bool:
            segment_file = work_dir / f"seg_{index:05d}.ts"
            if segment_file.exists() and segment_file.stat().st_size > 0:
                return True
            data = _http_fetch_bytes(
                f"{base_url}/{segment_names[index]}",
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
        LOGGER.info("cctv wasm: %d segments downloaded in %.1fs", len(segment_names), time.monotonic() - t0)

        # 2) decrypt in parallel groups (equal-length transforms, order fixed)
        t1 = time.monotonic()
        group_count = max(1, min(_WASM_PARALLEL, len(segment_names)))
        groups = [
            [f"seg_{i:05d}.ts" for i in range(g, len(segment_names), group_count)]
            for g in range(group_count)
        ]
        group_ts = [work_dir / f"group_{g}.ts" for g in range(group_count)]

        with ThreadPoolExecutor(max_workers=group_count) as pool:
            futures = {
                pool.submit(
                    _wasm_decrypt_group,
                    h5e_proj,
                    groups[g],
                    group_ts[g],
                    timeout=WASM_TIMEOUT_SECONDS,
                    cancel_event=cancel_event,
                ): g
                for g in range(group_count)
            }
            results = {}
            for future in as_completed(futures):
                g = futures[future]
                results[g] = future.result()
        if not all(results.get(g) for g in range(group_count)):
            failed = sum(1 for g in range(group_count) if not results.get(g))
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"WASM 降级失败：解密 {failed}/{group_count} 组失败",
                retryable=True,
            )
        LOGGER.info("cctv wasm: %d groups decrypted in %.1fs", group_count, time.monotonic() - t1)

        # 3) concatenate groups in order, then mux with ffmpeg
        t2 = time.monotonic()
        full_ts = work_dir / "full.ts"
        with full_ts.open("wb") as out:
            for g in range(group_count):
                out.write(group_ts[g].read_bytes())
        mp4 = job_dir / f"{title}.mp4"
        code, _, stderr = _run_with_cancel(
            ["ffmpeg", "-y", "-i", str(full_ts), "-c", "copy",
             "-movflags", "+faststart", str(mp4)],
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if code != 0 or not mp4.is_file():
            raise DomainError(
                "DOWNLOAD_FAILED",
                f"WASM 降级失败：ffmpeg 封装失败（{stderr.strip()[-200:]}）",
                retryable=True,
            )
        LOGGER.info("cctv wasm: mux in %.1fs (total %.1fs)", time.monotonic() - t2, time.monotonic() - t0)
        return mp4
    finally:
        import shutil as _shutil

        _shutil.rmtree(work_dir, ignore_errors=True)


class CctvVideoDownloader:
    """Download one CCTV episode to an MP4 inside the job directory."""

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
            metadata.get("platform_signals")
            if isinstance(metadata, Mapping)
            else None
        ) or {}
        guid = str(signals.get("guid") or "").strip()
        title = _safe_title(str(resource.get("title") or "").strip() or guid)

        # Search results carry a VIDE/VIDA page token (14-16 chars), not the
        # real 32-hex guid that getHttpVideoInfo/cctv download need. Resolve
        # the page whenever the guid is not a full 32-hex value.
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

        # ---- native route first (0069 M2): plain stream or h5e decrypt ----
        from .cctv import video_info  # local import: cctv imports cctv_download

        native_mp4: Path | None = None
        native_reason = ""
        hls_h5e = ""
        try:
            manifest = (
                self._video_info_func(guid, timeout=self.timeout)
                if self._video_info_func is not None
                else video_info(guid, timeout=self.timeout)
            )
            hls_h5e = str((manifest or {}).get("h5e_url") or "").strip()
            if hls_h5e.startswith("http"):
                native_mp4 = download_h5e_native(
                    resource, guid, title, job_dir,
                    timeout=self.timeout, cancel_event=cancel_event,
                    h5e_url=hls_h5e,
                )
            else:
                stream_url = str((manifest or {}).get("hls_url") or "").strip()
                if not stream_url.startswith("http"):
                    stream_url = resolve_wasm_m3u8(resource, guid)
                    # hls_url missing: try the plain h5e-less m3u8 only if it
                    # actually exists; otherwise report the manifest gap.
                    probe = _http_fetch_bytes(
                        stream_url, timeout=self.timeout, cancel_event=cancel_event
                    )
                    if probe is None:
                        raise DomainError(
                            "CONTENT_VALIDATION_FAILED",
                            "央视视频详情未提供可用流地址",
                            retryable=False,
                        )
                native_mp4 = download_stream_native(
                    stream_url, title, job_dir,
                    timeout=self.timeout, cancel_event=cancel_event,
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
                byte_size = native_mp4.stat().st_size
                digest = hashlib.sha256()
                with native_mp4.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        digest.update(chunk)
                return DownloadResult(
                    native_mp4,
                    byte_size,
                    "video/mp4",
                    digest.hexdigest(),
                    native_mp4.name,
                    metadata={
                        "guid": guid,
                        "route": "native",
                        "health_errors": native_errors,
                        "attempts": 1,
                    },
                )
            native_mp4.unlink(missing_ok=True)
            native_reason = f"自研产物体检失败（{native_errors} 错）"

        # ---- WASM fallback: last resort for h5e streams the native path
        #      cannot decrypt (kept until real-world comparison in M3). ----
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
                h5e_url=hls_h5e if hls_h5e.startswith("http") else None,
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
            byte_size = wasm_mp4.stat().st_size
            digest = hashlib.sha256()
            with wasm_mp4.open("rb") as handle:
                for chunk in iter(lambda: handle.read(64 * 1024), b""):
                    digest.update(chunk)
            return DownloadResult(
                wasm_mp4,
                byte_size,
                "video/mp4",
                digest.hexdigest(),
                wasm_mp4.name,
                metadata={
                    "guid": guid,
                    "route": "wasm",
                    "health_errors": wasm_errors,
                    "attempts": 1,
                },
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
