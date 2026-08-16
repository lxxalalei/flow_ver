"""File-backed job state shared by the MCP process and detached workers.

``jobs/<job_id>/job.json`` is the single authority for one download job.  The
worker owns that file while it is alive; the parent process only rewrites it
before spawning a worker, or after proving the worker process is dead.  A
``cancel.flag`` file next to it carries the cancel intent across processes.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DomainError

JOB_ID_PATTERN = re.compile(r"^job_[0-9a-f]{32}$")
CANCEL_FLAG_NAME = "cancel.flag"
JOB_STATE_NAME = "job.json"
TERMINAL_STATUSES = frozenset(
    {"succeeded", "partial", "failed", "cancelled", "interrupted"}
)
# A freshly queued job may not have a worker pid yet (worker takes a second
# or two to boot and claim the file); do not declare it interrupted until the
# state has been untouched for at least this long.
SPAWN_GRACE_SECONDS = 30


def state_age_seconds(data: dict[str, Any]) -> float:
    try:
        updated = datetime.fromisoformat(str(data.get("updated_at")))
    except (TypeError, ValueError):
        return float("inf")
    now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return max(0.0, (now - updated).total_seconds())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_dir(jobs_root: Path, job_id: str) -> Path:
    """Return the job directory, rejecting anything that is not a real job id."""

    if not JOB_ID_PATTERN.match(str(job_id or "")):
        raise DomainError("INVALID_ARGUMENT", "非法 job_id")
    return jobs_root / job_id


def read_job(directory: Path) -> dict[str, Any]:
    path = directory / JOB_STATE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DomainError("JOB_NOT_FOUND", "任务不存在") from None
    except OSError as exc:
        raise DomainError("JOB_STATE_INVALID", f"任务状态文件不可读: {exc}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DomainError("JOB_STATE_INVALID", f"任务状态文件损坏: {exc}") from None
    if not isinstance(data, dict) or not data.get("job_id"):
        raise DomainError("JOB_STATE_INVALID", "任务状态文件结构无效")
    return data


def write_job(directory: Path, data: dict[str, Any]) -> None:
    """Atomically rewrite job.json (tmp file + replace)."""

    payload = dict(data)
    payload["updated_at"] = utc_now_iso()
    tmp = directory / f"{JOB_STATE_NAME}.tmp"
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, directory / JOB_STATE_NAME)


def read_request(directory: Path) -> dict[str, Any]:
    try:
        data = json.loads(
            (directory / "request.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        raise DomainError("JOB_NOT_FOUND", "任务请求文件不存在") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise DomainError("JOB_STATE_INVALID", f"任务请求文件无效: {exc}") from None
    if not isinstance(data, dict):
        raise DomainError("JOB_STATE_INVALID", "任务请求文件结构无效")
    return data


def write_request(directory: Path, data: dict[str, Any]) -> None:
    (directory / "request.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def process_alive(pid: Any) -> bool:
    """Best-effort liveness check with the stdlib only.

    For worker processes spawned by this package (same user) OpenProcess
    access is expected; a bare False means the pid is gone.
    """

    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid_int
        )
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process(pid: int) -> None:
    """Force-kill a stuck worker; used only as the cancel fallback."""

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


class FileCancelEvent(threading.Event):
    """threading.Event that also honours the on-disk cancel flag.

    The whole acquisition chain checks ``cancel_event.is_set()`` at its
    checkpoints, so overriding ``is_set`` is the only seam needed for a
    detached worker to observe cancels written by another process.
    """

    def __init__(self, flag_path: Path) -> None:
        super().__init__()
        self._flag_path = flag_path

    def is_set(self) -> bool:
        return super().is_set() or self._flag_path.exists()
