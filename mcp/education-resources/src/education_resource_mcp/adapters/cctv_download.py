"""CCTV video downloader backed by the local cctv-dl binary.

cctv-dl (CCTVVideoDownloader) is the confirmed mechanical route for column
episode listing and MP4 delivery, including h5e stream handling for most
content. The standalone WASM decrypt path used by the source project for
2021-era deterministic h5e failures is intentionally NOT integrated; such
failures are reported honestly with a manual-path hint instead of a silent
fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..config import Settings
from ..downloader import DownloadResult
from ..errors import DomainError
from ..policy import ensure_within_root
from ..sessions import SessionStore

DEFAULT_CCTV_DL_EXE = Path(
    r"C:\Users\admin\projects\mediacrawler\downloads\cctv\cctv-dl-bin"
    r"\cctv-dl\bin\cctv-dl.exe"
)
DOWNLOAD_TIMEOUT_SECONDS = 3600
LIST_TIMEOUT_SECONDS = 300
HEALTH_ERROR_THRESHOLD = 100
MAX_ATTEMPTS = 3
THREADS = "8"
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

        raise DomainError(
            "DOWNLOAD_FAILED",
            f"央视视频下载失败：{last_reason}。2021 年老视频存在已知 h5e 确定性解密"
            "缺陷时 cctv-dl 会稳定失败；本 MCP 未集成 WASM 备用解密，需人工处理",
            retryable=False,
        )


__all__ = [
    "CctvVideoDownloader",
    "DEFAULT_CCTV_DL_EXE",
    "ffmpeg_error_count",
    "resolve_cctv_dl_exe",
    "run_cctv_dl_list",
]
