"""Bounded spawner for detached download workers (0056).

Jobs used to run as threads of the MCP process and died with it.  Now each
job is a detached worker process (see ``job_worker.spawn_worker``); this
module only keeps at most ``max_workers`` of them alive and defers the rest,
preserving the queueing semantics of the former in-process executor.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

SpawnFn = Callable[[], "subprocess.Popen | None"]


def spawn_worker(directory: Path) -> subprocess.Popen:
    """Spawn a worker that outlives this process.

    stdio points only at ``worker.log`` and stdin is closed, so there is no
    pipe back to the parent: the MCP process can die without touching the
    worker.  CREATE_BREAKAWAY_FROM_JOB detaches from a gateway job object
    when allowed; if breakaway is denied we still spawn (a job object that
    kills children would be caught by the gateway-restart acceptance test).
    """

    log_handle = open(directory / "worker.log", "ab", buffering=0)
    command = [
        sys.executable, "-m", "education_resource_mcp.job_worker", str(directory)
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        try:
            return subprocess.Popen(command, creationflags=base | breakaway, **kwargs)
        except PermissionError:
            return subprocess.Popen(command, creationflags=base, **kwargs)
    return subprocess.Popen(command, start_new_session=True, **kwargs)


class JobSpawner:
    """Queue jobs and spawn detached workers, at most ``max_workers`` alive."""

    def __init__(self, max_workers: int) -> None:
        self._max = max(1, int(max_workers))
        self._queue: queue.Queue[tuple[str, SpawnFn]] = queue.Queue()
        self._queued: set[str] = set()
        self._live: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="education-resource-job-spawner", daemon=True
        )
        self._thread.start()

    def submit(self, job_id: str, spawn: SpawnFn) -> None:
        with self._lock:
            self._queued.add(job_id)
        self._queue.put((job_id, spawn))

    def is_pending(self, job_id: str) -> bool:
        """True while the job is queued or its worker is alive (this process)."""

        with self._lock:
            if job_id in self._queued:
                return True
            popen = self._live.get(job_id)
            return popen is not None and popen.poll() is None

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                self._live = {
                    job_id: popen
                    for job_id, popen in self._live.items()
                    if popen.poll() is None
                }
                full = len(self._live) >= self._max
            if full:
                self._stop.wait(0.2)
                continue
            try:
                job_id, spawn = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                self._queued.discard(job_id)
            try:
                popen = spawn()
            except Exception:  # noqa: BLE001 - one bad spawn must not kill the loop
                LOGGER.exception("spawning worker for job %s failed", job_id)
                continue
            if popen is None:
                continue  # spawn fn decided the job never started
            with self._lock:
                self._live[job_id] = popen

    def shutdown(self, wait: bool = True) -> None:
        """Stop queueing new work; already-running workers stay detached."""

        self._stop.set()
        if wait and self._thread.is_alive():
            self._thread.join(timeout=2.0)
