"""Detached download worker.

Usage::

    python -m education_resource_mcp.job_worker <job_dir>

The parent process writes ``request.json`` plus a queued ``job.json`` into the
job directory and then spawns this module detached (see ``jobs.spawn_worker``).
While alive the worker owns ``job.json`` and updates progress after each
resource. Everything it prints lands in ``worker.log`` next to the job state.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
from typing import Any

from .acquisition.planner import AcquisitionPlanningError
from .errors import DomainError
from .job_state import (
    CANCEL_FLAG_NAME,
    FileCancelEvent,
    read_job,
    read_request,
    write_job,
)
from .service import ResourceService

LOGGER = logging.getLogger(__name__)


def run(directory: Path) -> int:
    request = read_request(directory)
    if str(request.get("kind") or "") == "batch_collect":
        from .batch import run_batch_collect

        return run_batch_collect(directory)
    job_id = str(request["job_id"])
    resources = list(request.get("resources") or [])
    preferred_container = str(request.get("preferred_container") or "original")
    cancel = FileCancelEvent(directory / CANCEL_FLAG_NAME)

    write_job(
        directory,
        {**read_job(directory), "status": "running", "pid": os.getpid()},
    )

    service = ResourceService(recover_jobs=False)
    files: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    completed = 0
    crashed: str | None = None
    try:
        for resource in resources:
            if cancel.is_set():
                break
            try:
                files.extend(
                    service.download_resource(
                        job_id, resource, preferred_container, cancel
                    )
                )
            except (DomainError, AcquisitionPlanningError) as exc:
                failures.append(
                    {
                        "resource_id": resource.get("resource_id"),
                        "code": str(getattr(exc, "code", "DOWNLOAD_FAILED")),
                        "message": str(getattr(exc, "message", str(exc))),
                        "retryable": bool(getattr(exc, "retryable", False)),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - record and keep going
                LOGGER.exception("download failed for one resource")
                failures.append(
                    {
                        "resource_id": resource.get("resource_id"),
                        "code": "DOWNLOAD_FAILED",
                        "message": f"{type(exc).__name__}: {exc}",
                        "retryable": False,
                    }
                )
            completed += 1
            write_job(
                directory,
                {
                    **read_job(directory),
                    "status": "running",
                    "pid": os.getpid(),
                    "completed": completed,
                    "files": files,
                    "failures": failures,
                },
            )
    except Exception as exc:  # noqa: BLE001 - never leave a running status behind
        LOGGER.exception("job worker crashed")
        crashed = f"{type(exc).__name__}: {exc}"

    if crashed:
        failures.append(
            {
                "resource_id": None,
                "code": "WORKER_CRASHED",
                "message": crashed,
                "retryable": True,
            }
        )
    final = (
        "cancelled"
        if cancel.is_set()
        else ("partial" if files and failures else "succeeded" if files else "failed")
    )
    write_job(
        directory,
        {
            **read_job(directory),
            "status": final,
            "pid": os.getpid(),
            "completed": completed,
            "files": files,
            "failures": failures,
        },
    )
    LOGGER.info("job %s finished: %s", job_id, final)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: python -m education_resource_mcp.job_worker <job_dir>",
            file=sys.stderr,
        )
        return 2
    return run(Path(args[0]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
