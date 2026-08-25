"""CCTV video downloader backed by the local cctv-dl binary, with a WASM
fallback for 2021-era videos whose h5e stream cctv-dl decrypts incorrectly.

cctv-dl (CCTVVideoDownloader) is the confirmed fast route for column episode
listing and MP4 delivery. Older videos (2021 and before) are a known
deterministic failure: cctv-dl produces a corrupt/garble stream. The verified
fallback (used in the source project for exactly this case) runs the official
WASM worker: this module downloads the h5e segments in Python, decrypts them
in parallel groups through ``node --import tsx`` against ``h5e_proj``, muxes
with ffmpeg and applies the same decode health gate. The m3u8 prefers the
per-video ``h5e_url`` from ``getHttpVideoInfo``; the fixed ``H5E_BASE``
template is only a fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..policy import ensure_within_root
from ..sessions import SessionStore
from .http_client import urlopen_with_fallback

DEFAULT_CCTV_DL_EXE = Path(
    r"C:\Users\admin\projects\mediacrawler\downloads\cctv\cctv-dl-bin"
    r"\cctv-dl\bin\cctv-dl.exe"
)
DEFAULT_H5E_PROJ = Path(r"C:\Users\admin\projects\mediacrawler\h5e_proj")
# Fixed h5e m3u8 template used only when the per-video h5e_url is unavailable.
# Its generality is unconfirmed; CCTV_H5E_BASE can override it.
DEFAULT_H5E_BASE = "https://dh5ws01.v.cntv.cn/asp/h5e/hls/2000/0303000a/3/default"
DOWNLOAD_TIMEOUT_SECONDS = 3600
LIST_TIMEOUT_SECONDS = 300
HEALTH_ERROR_THRESHOLD = 100
MAX_ATTEMPTS = 3
THREADS = "8"
WASM_TIMEOUT_SECONDS = 2 * 3600
_WASM_DL_THREADS = 12
_WASM_PARALLEL = 4
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def resolve_cctv_dl_exe() -> Path:
    """Locate the cctv-dl binary: ``CCTV_DL_EXE`` env override first."""

    configured = os.environ.get("CCTV_DL_EXE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(DEFAULT_CCTV_DL_EXE)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    raise DomainError(
        "PROVIDER_UNAVAILABLE",
        "未找到 cctv-dl 可执行文件。请设置环境变量 CCTV_DL_EXE 指向 cctv-dl.exe"
        "（CCTVVideoDownloader 发行包 bin 目录）",
        retryable=False,
    )


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

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            proc.kill()
            raise DomainError("JOB_CANCELLED", "下载已取消")
        if time.monotonic() > deadline:
            proc.kill()
            raise DomainError(
                "DOWNLOAD_FAILED", "cctv-dl 执行超时", retryable=True
            )
        time.sleep(0.5)
    stdout, stderr = proc.communicate()
    return proc.returncode, stdout or "", stderr or ""


def _parse_download_complete(stdout: str) -> tuple[bool, int, int]:
    """Interpret cctv-dl's download_complete event; (ok, failed, total)."""

    for line in stdout.splitlines():
        if "download_complete" not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            match = re.search(r'"failed":(\d+),"total":(\d+)', line)
            if match:
                failed, total = int(match.group(1)), int(match.group(2))
                return failed == 0, failed, total
            continue
        if str(event.get("event") or "") == "download_complete":
            try:
                failed = int(event.get("failed") or 0)
                total = int(event.get("total") or 0)
            except (TypeError, ValueError):
                continue
            return failed == 0, failed, total
    return False, -1, -1


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


def run_cctv_dl_list(
    column_url: str,
    *,
    cancel_event: Any = None,
    runner: Callable[..., tuple[int, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """List column episodes via ``cctv-dl --json list`` (video events)."""

    exe = resolve_cctv_dl_exe()
    code, stdout, stderr = (runner or _run_with_cancel)(
        [str(exe), "--json", "list", column_url],
        timeout=LIST_TIMEOUT_SECONDS,
        cancel_event=cancel_event,
    )
    if code not in (0, 1, 3):
        raise DomainError(
            "PARTIAL_FAILURE",
            f"cctv-dl 栏目列举失败 rc={code}: {stderr.strip()[-300:]}",
            retryable=True,
        )
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "video":
            events.append(event)
    return events


def _newest_mp4(directory: Path) -> Path | None:
    mp4s = [
        path for path in directory.glob("*.mp4")
        if path.is_file() and path.stat().st_size > 0
    ]
    if not mp4s:
        return None
    return max(mp4s, key=lambda path: path.stat().st_mtime)


def _unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    for index in range(2, 1000):
        candidate = destination.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    return destination


def resolve_h5e_proj() -> Path:
    """Locate the WASM worker project: ``CCTV_H5E_PROJ`` env override first."""

    configured = os.environ.get("CCTV_H5E_PROJ", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(DEFAULT_H5E_PROJ)
    for candidate in candidates:
        try:
            if candidate.is_dir() and (candidate / "src" / "cli" / "main.ts").is_file():
                return candidate
        except OSError:
            continue
    raise DomainError(
        "PROVIDER_UNAVAILABLE",
        "未找到 h5e_proj（官方 WASM 解密工程，含 src/cli/main.ts）。"
        "请设置环境变量 CCTV_H5E_PROJ 指向该工程目录",
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
    m3u8_url = resolve_wasm_m3u8(resource, guid)

    body = _http_fetch_bytes(m3u8_url, timeout=timeout, cancel_event=cancel_event)
    if body is None:
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"WASM 降级失败：h5e m3u8 获取失败（{m3u8_url[:120]}）",
            retryable=True,
        )
    segment_names = [
        line.strip()
        for line in body.decode("utf-8", "replace").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not segment_names:
        raise DomainError(
            "DOWNLOAD_FAILED",
            "WASM 降级失败：h5e m3u8 没有分片列表",
            retryable=True,
        )
    base_url = m3u8_url.rsplit("/", 1)[0]

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

        # 2) decrypt in parallel groups (equal-length transforms, order fixed)
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

        # 3) concatenate groups in order, then mux with ffmpeg
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
        exe_resolver: Callable[[], Path] = resolve_cctv_dl_exe,
        runner: Callable[..., tuple[int, str, str]] | None = None,
        health_checker: Callable[[Path], int | None] | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = float(settings.download_timeout_seconds)
        self._exe_resolver = exe_resolver
        self._runner = runner or _run_with_cancel
        self._health_checker = health_checker or ffmpeg_error_count

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

        if not guid:
            from .cctv import resolve_episode

            resolved = resolve_episode(
                str(resource.get("source_url") or ""), timeout=self.timeout
            )
            if resolved is not None:
                guid = resolved["guid"]
                if not str(resource.get("title") or "").strip():
                    title = _safe_title(resolved["title"])
        if not guid:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "央视视频缺少 guid，且无法从页面解析",
                retryable=False,
            )

        exe = self._exe_resolver()
        job_dir = self.settings.jobs_dir / job_id
        work_dir = job_dir / "cctv-dl"
        work_dir.mkdir(parents=True, exist_ok=True)
        ensure_within_root(job_dir, self.settings.jobs_dir)

        quality = os.environ.get("CCTV_QUALITY", "0").strip() or "0"
        last_reason = "未执行"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "下载已取消")
            for stale in work_dir.glob("*.mp4"):
                stale.unlink(missing_ok=True)
            code, stdout, stderr = self._runner(
                [
                    str(exe), "--json", "download",
                    "--guid", guid,
                    "--title", title,
                    "--output", str(work_dir),
                    "--quality", quality,
                    "--threads", THREADS,
                    "--mp4",
                ],
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            ok, failed, total = _parse_download_complete(stdout)
            if not ok:
                last_reason = (
                    f"cctv-dl 未成功完成 (rc={code}, failed={failed}/{total}): "
                    f"{stderr.strip()[-200:]}"
                )
                continue
            mp4 = _newest_mp4(work_dir)
            if mp4 is None:
                last_reason = "cctv-dl 报告完成但没有产出 mp4"
                continue
            errors = self._health_checker(mp4)
            if errors is not None and errors > HEALTH_ERROR_THRESHOLD:
                last_reason = f"解码体检 {errors} 错 > {HEALTH_ERROR_THRESHOLD}"
                mp4.unlink(missing_ok=True)
                continue

            destination = _unique_destination(job_dir / f"{title}.mp4")
            ensure_within_root(destination, self.settings.jobs_dir)
            mp4.replace(destination)
            byte_size = destination.stat().st_size
            digest = hashlib.sha256()
            with destination.open("rb") as handle:
                for chunk in iter(lambda: handle.read(64 * 1024), b""):
                    digest.update(chunk)
            return DownloadResult(
                destination,
                byte_size,
                "video/mp4",
                digest.hexdigest(),
                destination.name,
                metadata={
                    "guid": guid,
                    "health_errors": errors,
                    "attempts": attempt,
                },
            )

        # ---- WASM fallback: 2021-era videos have a deterministic cctv-dl
        #      decryption defect (garble); the official worker re-decrypts. ----
        if cancel_event is not None and cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        wasm_mp4 = download_wasm(
            resource,
            guid,
            title,
            job_dir,
            timeout=self.timeout,
            cancel_event=cancel_event,
        )
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
                    "attempts": MAX_ATTEMPTS,
                },
            )
        wasm_mp4.unlink(missing_ok=True)
        raise DomainError(
            "DOWNLOAD_FAILED",
            f"央视视频下载失败：cctv-dl 确定性失败（{last_reason}）后，WASM 降级"
            f"体检失败（{wasm_errors} 错 > {HEALTH_ERROR_THRESHOLD}）。"
            "该视频可能加密形态特殊，需人工处理",
            retryable=False,
        )


__all__ = [
    "CctvVideoDownloader",
    "DEFAULT_CCTV_DL_EXE",
    "download_wasm",
    "ffmpeg_error_count",
    "resolve_cctv_dl_exe",
    "resolve_h5e_proj",
    "resolve_wasm_m3u8",
    "run_cctv_dl_list",
]
