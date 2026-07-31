"""Small in-process job runner for local stdio development."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import Callable


JobCallable = Callable[[threading.Event], None]


class JobRunner:
    def __init__(self, max_workers: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="education-resource-job"
        )
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._futures: dict[str, Future[None]] = {}

    def submit(self, job_id: str, function: JobCallable) -> None:
        event = threading.Event()
        with self._lock:
            if job_id in self._futures:
                return
            self._cancel_events[job_id] = event
            future = self._executor.submit(function, event)
            self._futures[job_id] = future
            future.add_done_callback(lambda _: self._forget(job_id))

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is None:
                return False
            event.set()
            return True

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(job_id, None)
            self._futures.pop(job_id, None)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
