"""Focused orchestration tests for exact-Provider batch dispatch."""

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
        max_workers: int = 4,
    ) -> None:
        self.settings = SimpleNamespace(
            max_workers=max_workers,
            jobs_dir=Path.cwd(),
        )
        self.store = _Store(items)
        self._item_runner = runner
        self.progress: list[int] = []

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
    def test_large_same_provider_job_uses_one_batch_worker(self) -> None:
        thread_ids: set[int] = set()
        seen: list[str] = []

        def runner(_job, _job_id, item, _cancel_event):
            thread_ids.add(threading.get_ident())
            seen.append(str(item["resource_id"]))
            return True, False, None

        items = [_item(f"res_{index}", "provider-a") for index in range(500)]
        service = _ProbeService(items, runner, max_workers=1)
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(len(thread_ids), 1)
        self.assertEqual(len(seen), 500)
        self.assertEqual(service.store.final_status, "succeeded")
        self.assertEqual(service.progress[-1], 100)

    def test_different_providers_run_as_independent_batches(self) -> None:
        barrier = threading.Barrier(2, timeout=2)
        thread_ids: set[int] = set()
        lock = threading.Lock()

        def runner(_job, _job_id, _item_value, _cancel_event):
            with lock:
                thread_ids.add(threading.get_ident())
            barrier.wait()
            return True, False, None

        # settings.max_workers belongs to JobRunner/search; it is not a
        # cross-platform download concurrency policy.
        service = _ProbeService(
            [_item("res_a", "provider-a"), _item("res_b", "provider-b")],
            runner,
            max_workers=1,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(len(thread_ids), 2)
        self.assertEqual(service.store.final_status, "succeeded")
        self.assertEqual(service.progress[-1], 100)

    def test_ordinary_failure_does_not_block_later_item_in_same_batch(self) -> None:
        seen: list[str] = []

        def runner(_job, _job_id, item, _cancel_event):
            resource_id = str(item["resource_id"])
            seen.append(resource_id)
            if resource_id == "res_fail":
                return False, True, None
            return True, False, None

        service = _ProbeService(
            [_item("res_fail", "provider-a"), _item("res_ok", "provider-a")],
            runner,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(seen, ["res_fail", "res_ok"])
        self.assertEqual(service.store.final_status, "succeeded")
        self.assertEqual(service.progress[-1], 100)

    def test_persisted_cancellation_stops_provider_batch(self) -> None:
        entered = threading.Event()
        cancel_event = threading.Event()
        seen: list[str] = []

        def runner(_job, _job_id, item, item_cancel_event):
            seen.append(str(item["resource_id"]))
            entered.set()
            item_cancel_event.wait(timeout=2)
            raise DomainError("JOB_CANCELLED", "任务已取消")

        service = _ProbeService(
            [_item("res_a", "provider-a"), _item("res_b", "provider-a")],
            runner,
        )
        worker = threading.Thread(
            target=service._run_download_job,
            args=("job_concurrency", cancel_event),
        )
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        service.store.job["status"] = "cancelling"
        cancel_event.set()
        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(seen, ["res_a"])
        self.assertEqual(service.store.final_status, "cancelled")

    def test_job_level_abort_stops_remaining_items(self) -> None:
        seen: list[str] = []

        def runner(_job, _job_id, item, _cancel_event):
            resource_id = str(item["resource_id"])
            seen.append(resource_id)
            if resource_id == "res_abort":
                return False, True, DomainError("POLICY_DENIED", "blocked")
            return True, False, None

        service = _ProbeService(
            [_item("res_abort", "provider-a"), _item("res_not_started", "provider-a")],
            runner,
        )
        service._run_download_job("job_concurrency", threading.Event())

        self.assertEqual(seen, ["res_abort"])
        self.assertEqual(service.store.final_status, "POLICY_DENIED")


if __name__ == "__main__":
    unittest.main()
