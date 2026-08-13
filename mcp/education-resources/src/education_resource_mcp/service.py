"""Education-resource domain service with bounded JobItem concurrency.

The unchanged service implementation lives in ``_service_core``.  This module
only overrides Download Job execution so the concurrency change stays isolated
from Search, Inspect, Archive, Session, and public MCP contracts.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import threading
from typing import Any

from ._service_core import *  # noqa: F401,F403
from ._service_core import (
    ACQUISITION_ABORT_CODES,
    PERSISTED_ASSET_ROLES,
    PUBLIC_JOB_FAILURE_CODES,
    AcquisitionRequest,
    AcquisitionStrategy,
    DomainError,
    PolicyError,
    ResourceService as _BaseResourceService,
    _provider_resource,
    ensure_within_root,
    new_id,
)


class ResourceService(_BaseResourceService):
    """Core domain service plus fair exact-Provider JobItem scheduling."""

    def _provider_max_concurrent_items(self, item: dict[str, Any]) -> int:
        key = (
            str(item["provider_id"]),
            str(item["provider_version"]),
        )
        registration = self.acquisition_router.provider_registry.get(key)
        if registration is None:
            raise DomainError(
                "PLAN_BINDING_CONFLICT",
                "任务执行项绑定的 Provider 未部署",
                details={"provider_id": key[0], "provider_version": key[1]},
            )
        value = getattr(registration.provider, "max_concurrent_items", 1)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise DomainError(
                "INTERNAL_ERROR",
                "Provider 的 max_concurrent_items 配置无效",
                details={"provider_id": key[0], "provider_version": key[1]},
            )
        return value

    def _run_download_item(
        self,
        job: dict[str, Any],
        job_id: str,
        item: dict[str, Any],
        cancel_event: threading.Event,
    ) -> tuple[bool, bool, DomainError | None]:
        resource_id = str(item["resource_id"])
        self._raise_for_cancel_event(job_id, cancel_event)
        self.store.start_acquisition_outcome(
            job_id,
            resource_id,
            metadata={"attempt": 1},
        )
        representation = item.get("representation")
        if not isinstance(representation, dict):
            raise DomainError(
                "PLAN_BINDING_CONFLICT",
                "任务执行项缺少已确认的资源表示",
                details={"resource_id": resource_id},
            )
        selected_container = representation.get("selected_container")
        if not isinstance(selected_container, str) or not selected_container:
            raise DomainError(
                "PLAN_BINDING_CONFLICT",
                "任务执行项缺少已确认的容器",
                details={"resource_id": resource_id},
            )
        request = AcquisitionRequest(
            job_id=job_id,
            resource=_provider_resource(item, selected_container),
            strategy=item["strategy"],
            provider_id=item["provider_id"],
            provider_version=item["provider_version"],
            planned_scope=item["planned_scope"],
            representation_id=item["representation_id"],
            preferred_container=selected_container,
            cancel_event=cancel_event,
            jobs_root=self.settings.jobs_dir.resolve(),
        )
        acquisition = self.acquisition_router.acquire(request)

        expected_actual = (
            str(item["planned_scope"]),
            str(item["strategy"]),
            str(item["provider_id"]),
            str(item["provider_version"]),
        )
        observed_actual = (
            acquisition.actual_scope,
            acquisition.strategy.kind,
            acquisition.provider_id,
            acquisition.provider_version,
        )
        has_actual_provider_facts = any(
            value is not None
            for value in (
                acquisition.actual_scope,
                acquisition.provider_id,
                acquisition.provider_version,
            )
        )
        if has_actual_provider_facts and observed_actual != expected_actual:
            raise DomainError(
                "PLAN_BINDING_CONFLICT",
                "获取结果与 JobItem 的 Provider 路线不一致",
                details={"resource_id": resource_id},
            )
        actual_for_outcome = (
            expected_actual
            if observed_actual == expected_actual
            else (None, None, None, None)
        )

        if not acquisition.ok or acquisition.bundle is None:
            failure = acquisition.failure
            failure_code = failure.code if failure is not None else "DOWNLOAD_FAILED"
            failure_message = (
                failure.message if failure is not None else "获取任务没有产生可用结果"
            )
            failure_retryable = bool(failure.retryable) if failure is not None else False
            failure_details = dict(failure.details) if failure is not None else {}
            if failure_code == "JOB_CANCELLED":
                if self._job_cancellation_is_persisted(job_id):
                    raise DomainError("JOB_CANCELLED", "任务已取消")
                self.store.audit(
                    str(job["flow_id"]),
                    "download.provider_cancel_rejected",
                    job_id,
                    {
                        "resource_id": resource_id,
                        "provider_id": str(item["provider_id"]),
                    },
                )
                failure_code = "DOWNLOAD_FAILED"
                failure_message = "资源获取提供方异常终止"
                failure_retryable = False
                failure_details = {}
            self._raise_for_cancel_event(job_id, cancel_event)
            self.store.persist_failed_asset_bundle(
                job_id,
                resource_id,
                failure={
                    "code": failure_code,
                    "message": failure_message,
                    "retriable": failure_retryable,
                    "details": failure_details,
                    "item_position": 0,
                    "item_role": "primary",
                },
            )
            self.store.complete_acquisition_outcome(
                job_id,
                resource_id,
                status="failed",
                actual_scope=actual_for_outcome[0],
                actual_strategy=actual_for_outcome[1],
                actual_provider_id=actual_for_outcome[2],
                actual_provider_version=actual_for_outcome[3],
                failure_code=failure_code,
                failure_message=failure_message,
                retriable=failure_retryable,
                metadata={"item_failure_count": 1},
            )
            abort = None
            if failure_code in ACQUISITION_ABORT_CODES:
                abort = DomainError(
                    failure_code,
                    failure_message,
                    retryable=failure_retryable,
                    details=failure_details,
                )
            return False, True, abort

        if observed_actual != expected_actual:
            raise DomainError(
                "PLAN_BINDING_CONFLICT",
                "成功获取缺少与 JobItem 一致的实际 Provider 路线",
                details={"resource_id": resource_id},
            )

        artifacts = acquisition.bundle.artifacts
        if acquisition.strategy is AcquisitionStrategy.WEB_MATERIALIZE:
            primary = acquisition.bundle.primary
            artifacts = (primary,) if primary is not None else ()
        item_specs: list[dict[str, Any]] = []
        for position, artifact in enumerate(artifacts):
            try:
                ensure_within_root(artifact.path.resolve(), self.settings.jobs_dir)
            except PolicyError as exc:
                raise DomainError("POLICY_DENIED", str(exc)) from exc
            if not artifact.path.is_file():
                raise DomainError("CONTENT_VALIDATION_FAILED", "获取器没有产生受控文件")
            artifact_data = artifact.to_dict(include_path=False)
            role = "primary" if artifact.primary else str(artifact.role)
            if role not in PERSISTED_ASSET_ROLES:
                role = "attachment"
            metadata = dict(artifact_data.get("metadata") or {})
            if artifact.item_key:
                metadata["item_key"] = artifact.item_key
            item_specs.append(
                {
                    "position": position,
                    "role": role,
                    "status": "ready",
                    "required": bool(artifact.required or artifact.primary),
                    "metadata": metadata,
                    "local_path": str(artifact.path.resolve()),
                    "byte_size": artifact.byte_size,
                    "media_type": artifact.media_type,
                    "sha256": artifact.sha256,
                    "filename": artifact.filename,
                }
            )

        failure_specs: list[dict[str, Any]] = []
        for failure in acquisition.item_failures:
            position = len(item_specs)
            role = failure.role or "attachment"
            if role not in PERSISTED_ASSET_ROLES or role == "primary":
                role = "attachment"
            metadata = dict(failure.metadata)
            metadata["item_key"] = failure.item_key
            item_specs.append(
                {
                    "position": position,
                    "role": role,
                    "status": "failed",
                    "required": bool(failure.required),
                    "metadata": metadata,
                }
            )
            failure_specs.append(
                {
                    "code": failure.code,
                    "message": failure.message,
                    "retriable": failure.retryable,
                    "details": dict(failure.details),
                    "item_position": position,
                    "item_role": role,
                }
            )
        if not any(
            spec["role"] == "primary" and spec["status"] == "ready"
            for spec in item_specs
        ):
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "获取任务没有产生可持久化的 primary 资产",
            )

        bundle_completion = (
            "partial"
            if failure_specs or acquisition.completion == "partial"
            else "complete"
        )
        bundle = self.store.persist_asset_bundle(
            job_id,
            resource_id,
            item_specs=item_specs,
            failures=failure_specs,
            completion=bundle_completion,
        )
        bundle_asset_ids = [
            str(bundle_item["asset_id"])
            for bundle_item in bundle.get("items", [])
            if isinstance(bundle_item, dict)
            and bundle_item.get("status") == "ready"
            and isinstance(bundle_item.get("asset"), dict)
            and bundle_item["asset"].get("asset_id")
        ]
        if not bundle_asset_ids:
            raise DomainError("CONTENT_VALIDATION_FAILED", "资产包没有保存可用资产")
        self.store.complete_acquisition_outcome(
            job_id,
            resource_id,
            status="partial" if bundle_completion == "partial" else "succeeded",
            actual_scope=expected_actual[0],
            actual_strategy=expected_actual[1],
            actual_provider_id=expected_actual[2],
            actual_provider_version=expected_actual[3],
            bundle_id=str(bundle["bundle_id"]),
            asset_ids=bundle_asset_ids,
            metadata={
                "completion": bundle_completion,
                "item_failure_count": len(failure_specs),
            },
        )
        return True, bundle_completion == "partial", None

    def _run_download_job(self, job_id: str, cancel_event: threading.Event) -> None:
        """Run JobItems within global and Downloader-declared concurrency bounds."""

        job = self.store.get_job(job_id)
        if job is None:
            return
        try:
            self._raise_for_cancel_event(job_id, cancel_event)
            self._start_download_job_execution(job_id)
            job_items = self.store.get_job_items(job_id)

            usable_primary_count = 0
            processed_count = 0
            saw_partial = False
            total_items = len(job_items)
            if total_items == 0:
                self._finalize_download_job_failure(
                    job_id,
                    failure_code="DOWNLOAD_FAILED",
                    failure_message="下载计划没有可执行资源项",
                    retriable=False,
                )
                return

            provider_items: dict[tuple[str, str], list[dict[str, Any]]] = {}
            provider_limits: dict[tuple[str, str], int] = {}
            for item in job_items:
                key = (
                    str(item["provider_id"]),
                    str(item["provider_version"]),
                )
                provider_items.setdefault(key, []).append(item)
                if key not in provider_limits:
                    provider_limits[key] = self._provider_max_concurrent_items(item)

            provider_order = list(provider_items)
            next_index = {key: 0 for key in provider_order}
            active_by_provider = {key: 0 for key in provider_order}
            worker_count = max(1, min(total_items, self.settings.max_workers))
            futures: dict[
                Future[tuple[bool, bool, DomainError | None]], tuple[str, str]
            ] = {}

            def submit_available(pool: ThreadPoolExecutor) -> None:
                made_progress = True
                while len(futures) < worker_count and made_progress:
                    made_progress = False
                    for key in provider_order:
                        if len(futures) >= worker_count:
                            break
                        index = next_index[key]
                        items = provider_items[key]
                        if index >= len(items):
                            continue
                        if active_by_provider[key] >= provider_limits[key]:
                            continue
                        future = pool.submit(
                            self._run_download_item,
                            job,
                            job_id,
                            items[index],
                            cancel_event,
                        )
                        futures[future] = key
                        next_index[key] = index + 1
                        active_by_provider[key] += 1
                        made_progress = True

            abort_error: Exception | None = None
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="education-resource-item",
            ) as pool:
                submit_available(pool)
                while futures:
                    done, _pending = wait(
                        tuple(futures), return_when=FIRST_COMPLETED
                    )
                    for future in done:
                        key = futures.pop(future)
                        active_by_provider[key] -= 1
                        try:
                            usable, partial, item_abort = future.result()
                        except Exception as exc:
                            abort_error = abort_error or exc
                        else:
                            usable_primary_count += int(usable)
                            saw_partial = saw_partial or partial
                            processed_count += 1
                            try:
                                self._update_download_job_progress(
                                    job_id,
                                    int((processed_count / total_items) * 100),
                                )
                            except Exception as exc:
                                abort_error = abort_error or exc
                            if abort_error is None and item_abort is not None:
                                abort_error = item_abort
                    if abort_error is not None:
                        for pending in futures:
                            pending.cancel()
                        break
                    submit_available(pool)

            if abort_error is not None:
                raise abort_error

            self._raise_for_cancel_event(job_id, cancel_event)
            if usable_primary_count:
                try:
                    self.store.finalize_job_success(job_id)
                except ValueError as exc:
                    if str(exc) != "job_cancelling":
                        raise
                    self.store.finalize_job_cancellation(job_id)
            else:
                self._finalize_download_job_failure(
                    job_id,
                    failure_code="DOWNLOAD_FAILED",
                    failure_message="所选资源均未产生可用 primary 资产",
                    retriable=saw_partial,
                )
        except DomainError as exc:
            if self._job_cancellation_is_persisted(job_id):
                self.store.finalize_job_cancellation(
                    job_id,
                    failure_code="JOB_CANCELLED",
                    failure_message="任务已取消",
                )
            elif exc.code == "JOB_CANCELLED":
                self.store.audit(
                    str(job["flow_id"]),
                    "download.provider_cancel_rejected",
                    job_id,
                    {"source": "domain_error"},
                )
                self._finalize_download_job_failure(
                    job_id,
                    failure_code="DOWNLOAD_FAILED",
                    failure_message="资源获取提供方异常终止",
                    retriable=False,
                )
            else:
                self._finalize_download_job_failure(
                    job_id,
                    failure_code=(
                        exc.code
                        if exc.code in PUBLIC_JOB_FAILURE_CODES
                        else "INTERNAL_ERROR"
                    ),
                    failure_message=exc.message,
                    retriable=exc.retryable,
                )
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "job_cancelling":
                self.store.finalize_job_cancellation(
                    job_id,
                    failure_code="JOB_CANCELLED",
                    failure_message="任务已取消",
                )
                return
            incident_id = new_id("incident")
            self._finalize_download_job_failure(
                job_id,
                failure_code="INTERNAL_ERROR",
                failure_message=f"资源获取任务发生内部错误（事件 {incident_id}）",
                retriable=False,
            )
            self.store.audit(
                str(job["flow_id"]),
                "download.internal_error",
                job_id,
                {
                    "incident_id": incident_id,
                    "exception_type": type(exc).__name__,
                },
            )
