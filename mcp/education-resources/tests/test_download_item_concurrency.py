"""Focused orchestration tests for concurrent JobItem execution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

from education_resource_mcp.errors import DomainError
from education_resource_mcp.service import ResourceService


class _Store:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.job = {
            "job_id": "job_concurrency",
            "flow_id": "flow_concurrency",
            "status": "queued",
        }
        self.final_status: str | None = None

    def get_job(self, _job_id: str) -> dict[str, object]:
        return dict(self.job)

    def get_job_items(self, _job_id: str) -> list[dict[str, object]]:
        return list(self.items)

    def start_job_execution(self, _job_id: str) -> None:
        self.job["status"] = "running"

    def update_job_progress(self, _job_id: str, _progress: int) -> None:
        if self.job["status"] == "cancelling":
            raise ValueError("job_cancelling")

    def finalize_job_success(self, _job_id: str) -> None:
        self.job["status"] = "succeeded"
        self.final_status = "succeeded"

    def finalize_job_failure(
        self,
        _job_id: str,
        *,
        failure_code: str,
        failure_message: str,
        retriable: bool,
    ) -> None:
        del failure_message, retriable
        self.job["status"] = "failed"
        self.final_status = failure_code

    def finalize_job_cancellation(self, _job_id: str, **_kwargs: object) -> None:
        self.job["status"] = "cancelled"
        self.final_status = "cancelled"

    def audit(self, *_args: object, **_kwargs: object) -> None:
        return None


class _ProbeService(ResourceService):
    def __init__(
        self,
        items: list[dict[str, object]],
        runner,
        *,
        limits: dict[str, int] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.settings = SimpleNamespace(
            max_workers=max_workers,
            jobs_dir=Path.cwd(),
        )
        self.store = _Store(items)
        self._item_runner = runner
        self._limits = limits or {}
        self.progress: list[int] = []

    def _provider_max_concurrent_items(self, item: dict[str, object]) -> int:
        return self._limits.get(str(item["provider_id"]), 1)

    def _run_download_item(
        self,
        job: dict[str, object],
        job_id: str,
        item: dict[str, object],
        cancel_event: threading.Event,
    ) -> tuple[bool, bool, DomainError | None]:
        return self._item_runner(job, job_id, item, cancel_event)

    def _update_download_job_progress(self, job_id: str, progress: int) -> None:
        super()._update_download_job_progress(job_id, progress)
        self.progress.append(progress)


def _item(resource_id: str, provider_id: str) -> dict[str, object]:
    return {
        "resource_id": resource_id,
        "provider_id": provider_id,
        "provider_version": "1.0.0",
    }


class DownloadItemConcurrencyTests(unittest.TestCase):
    def test_different_providers_enter_concurrently(self) -> None:
        barrier = threading.Barrier(2, timeout=2)

        def runner(_job, _job_id, _item_value, _cancel_event):
            barrier.wait()
            return True, False, None

        service = _ProbeService(
            [_item("res_a", "provider-a"), _item("res_b", "provider-b")],
            runner,
            max_workers=2,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(service.store.final_status, "succeeded")
        self.assertEqual(service.progress[-1], 100)

    def test_same_provider_defaults_to_one_item(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def runner(_job, _job_id, item, _cancel_event):
            if item["resource_id"] == "res_a":
                first_started.set()
                release_first.wait(timeout=2)
            else:
                second_started.set()
            return True, False, None

        service = _ProbeService(
            [_item("res_a", "provider-a"), _item("res_b", "provider-a")],
            runner,
            max_workers=2,
        )
        worker = threading.Thread(
            target=service._run_download_job,
            args=("job_concurrency", threading.Event()),
        )
        worker.start()
        self.assertTrue(first_started.wait(timeout=2))
        self.assertFalse(second_started.wait(timeout=0.2))
        release_first.set()
        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(service.store.final_status, "succeeded")

    def test_provider_can_opt_into_two_items(self) -> None:
        barrier = threading.Barrier(2, timeout=2)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def runner(_job, _job_id, _item_value, _cancel_event):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                barrier.wait()
                return True, False, None
            finally:
                with lock:
                    active -= 1

        service = _ProbeService(
            [_item("res_a", "provider-a"), _item("res_b", "provider-a")],
            runner,
            limits={"provider-a": 2},
            max_workers=2,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(max_active, 2)
        self.assertEqual(service.store.final_status, "succeeded")

    def test_waiting_same_provider_does_not_starve_other_provider(self) -> None:
        a_started = threading.Event()
        b_started = threading.Event()
        release_a = threading.Event()
        a2_started = threading.Event()

        def runner(_job, _job_id, item, _cancel_event):
            resource_id = str(item["resource_id"])
            if resource_id == "res_a1":
                a_started.set()
                self.assertTrue(b_started.wait(timeout=2))
                release_a.wait(timeout=2)
            elif resource_id == "res_a2":
                a2_started.set()
            else:
                b_started.set()
                release_a.set()
            return True, False, None

        service = _ProbeService(
            [
                _item("res_a1", "provider-a"),
                _item("res_a2", "provider-a"),
                _item("res_b", "provider-b"),
            ],
            runner,
            max_workers=2,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertTrue(a_started.is_set())
        self.assertTrue(b_started.is_set())
        self.assertTrue(a2_started.is_set())
        self.assertEqual(service.store.final_status, "succeeded")

    def test_ordinary_failure_does_not_block_success(self) -> None:
        def runner(_job, _job_id, item, _cancel_event):
            if item["resource_id"] == "res_fail":
                return False, True, None
            return True, False, None

        service = _ProbeService(
            [_item("res_fail", "provider-a"), _item("res_ok", "provider-b")],
            runner,
            max_workers=2,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(service.store.final_status, "succeeded")
        self.assertEqual(service.progress[-1], 100)

    def test_persisted_cancellation_wakes_parallel_items(self) -> None:
        entered = threading.Barrier(3, timeout=2)
        cancel_event = threading.Event()

        def runner(_job, _job_id, _item_value, item_cancel_event):
            entered.wait()
            item_cancel_event.wait(timeout=2)
            raise DomainError("JOB_CANCELLED", "任务已取消")

        service = _ProbeService(
            [_item("res_a", "provider-a"), _item("res_b", "provider-b")],
            runner,
            max_workers=2,
        )
        worker = threading.Thread(
            target=service._run_download_job,
            args=("job_concurrency", cancel_event),
        )
        worker.start()
        entered.wait()
        service.store.job["status"] = "cancelling"
        cancel_event.set()
        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(service.store.final_status, "cancelled")

    def test_job_level_abort_keeps_fatal_semantics(self) -> None:
        release = threading.Barrier(2, timeout=2)

        def runner(_job, _job_id, item, _cancel_event):
            release.wait()
            if item["resource_id"] == "res_abort":
                return False, True, DomainError("POLICY_DENIED", "blocked")
            return True, False, None

        service = _ProbeService(
            [_item("res_abort", "provider-a"), _item("res_ok", "provider-b")],
            runner,
            max_workers=2,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(service.store.final_status, "POLICY_DENIED")


if __name__ == "__main__":
    unittest.main()
