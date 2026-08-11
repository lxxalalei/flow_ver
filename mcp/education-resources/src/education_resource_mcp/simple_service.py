"""Active ResourceService with the 0037 simplified acquisition state path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets
import threading
from typing import Any

from .acquisition import AcquisitionRequest, AcquisitionRouter, AcquisitionStrategy, ProviderRegistration
from .acquisition.planner import AcquisitionPlanner, AcquisitionPlanningError
from .acquisition.web_materializer import WebMaterializer as StaticWebMaterializer
from .archive import ArchiveFileManager
from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .inspection import INSPECTION_PROFILE_VERSION, InspectionRouter, source_fingerprint
from .inspection_registry import default_inspection_router
from .jobs import JobRunner
from .policy import PolicyError, ensure_within_root
from .search import SearchProvider, default_search_provider
from .session_bridge import create_session_store
from .simple_storage import Store
from .storage import new_id, utc_now
from .service import (
    ACQUISITION_ABORT_CODES,
    PERSISTED_ASSET_ROLES,
    PUBLIC_JOB_FAILURE_CODES,
    ResourceService as _LegacyResourceService,
)


_BARE_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ResourceService(_LegacyResourceService):
    """Keep mature search/archive behavior, replace only acquisition authority."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: Store | None = None,
        search_provider: SearchProvider | None = None,
        download_provider: DownloadProvider | None = None,
        rendering_downloader: DownloadProvider | None = None,
        acquisition_router: AcquisitionRouter | None = None,
        capability_registry_snapshot: Any | None = None,
        job_runner: JobRunner | None = None,
        archive_file_manager: ArchiveFileManager | None = None,
        inspection_router: InspectionRouter | None = None,
    ) -> None:
        # Kept only so older constructors do not fail during rollout. The
        # snapshot is no longer a runtime state or Provider credential.
        del capability_registry_snapshot
        self.settings = settings or Settings.from_env()
        self.settings.ensure_directories()
        self.store = store or Store(self.settings.database_path)
        if not isinstance(self.store, Store):
            raise TypeError("0037 ResourceService requires simple_storage.Store")
        self.session_store = create_session_store(self.settings)
        self.search_provider = search_provider or default_search_provider(
            self.settings, self.session_store
        )
        self.inspection_router = inspection_router or default_inspection_router(
            self.settings
        )
        if rendering_downloader is not None:
            raise ValueError(
                "rendering_downloader is not a routing fallback; register an exact Provider"
            )

        if acquisition_router is None:
            direct_provider = download_provider or PublicHttpDownloader(self.settings)
            registrations = [
                ProviderRegistration(
                    provider_id="generic-direct",
                    provider_version="1.0.0",
                    provider=direct_provider,
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                ),
                ProviderRegistration(
                    provider_id="generic-web-materializer",
                    provider_version="1.0.0",
                    provider=StaticWebMaterializer(settings=self.settings),
                    strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                    # A webpage can be either the actual article body or only
                    # a landing page. Representation decides which one.
                    scopes=("primary_resource", "landing_page"),
                ),
            ]
            try:
                from .adapters.smartedu_download import SmartEduDownloader

                registrations.append(
                    ProviderRegistration(
                        provider_id="smartedu-resource",
                        provider_version="1.0.0",
                        provider=SmartEduDownloader(self.session_store, self.settings),
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                )
            except Exception:
                # Missing optional Provider is a runtime availability fact. It
                # is surfaced when a Plan actually needs that Provider.
                pass
            self.acquisition_router = AcquisitionRouter(registrations)
        elif isinstance(acquisition_router, AcquisitionRouter):
            self.acquisition_router = acquisition_router
        else:
            registry = getattr(acquisition_router, "provider_registry", None)
            if not registry:
                raise TypeError("acquisition_router must expose exact Provider registrations")
            self.acquisition_router = AcquisitionRouter(registry.values())

        self.acquisition_planner = AcquisitionPlanner(self.acquisition_router)
        self.job_runner = job_runner or JobRunner(self.settings.max_workers)
        self._mutation_lock = threading.RLock()
        self._inspection_lock = threading.RLock()
        self.store.mark_incomplete_jobs_failed()
        self.archive_files = archive_file_manager or ArchiveFileManager(
            self.settings.library_dir
        )
        self._library_cursor_key = bytes.fromhex(
            self.store.get_or_create_metadata_secret("library_cursor_hmac")
        )
        self._reconcile_archives()

    def download_prepare(
        self,
        flow_id: str,
        idempotency_key: str,
        selection_version: int,
        *,
        presentation_id: str | None = None,
        presented_version: int | None = None,
        selection_digest: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        selection = self.store.get_selection(flow_id)
        if selection is None or not selection.get("resource_ids"):
            raise DomainError("RESOURCE_NOT_SELECTED", "下载前必须存在非空的明确选择")
        if not isinstance(selection_version, int) or isinstance(selection_version, bool):
            raise DomainError("INVALID_ARGUMENT", "selection_version 必须是整数")

        effective_presentation_id = presentation_id or str(
            selection.get("presentation_id") or ""
        )
        effective_presented_version = (
            int(selection.get("presented_version") or 0)
            if presented_version is None
            else int(presented_version)
        )
        effective_selection_digest = selection_digest or str(
            selection.get("selection_digest") or ""
        )
        if options is None:
            download_options: dict[str, Any] = {}
        elif isinstance(options, dict):
            download_options = dict(options)
        else:
            raise DomainError("INVALID_ARGUMENT", "options 必须是对象")
        allowed_options = {"preferred_container", "allow_safe_fallback"}
        unknown = sorted(set(download_options) - allowed_options)
        if unknown:
            raise DomainError(
                "INVALID_ARGUMENT",
                "options 包含不支持的字段",
                details={"fields": ",".join(unknown)},
            )
        container = download_options.get("preferred_container", "original")
        if container not in {"original", "pdf", "epub", "mp4", "mp3", "html", "text"}:
            raise DomainError("INVALID_ARGUMENT", "preferred_container 无效")
        fallback_value = download_options.get("allow_safe_fallback", False)
        if not isinstance(fallback_value, bool):
            raise DomainError("INVALID_ARGUMENT", "allow_safe_fallback 必须是布尔值")
        normalized_options = {
            "preferred_container": str(container),
            # Retained as a request preference only. Exact Provider routing
            # never silently tries another Provider after failure.
            "allow_safe_fallback": fallback_value,
        }
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "presentation_id": effective_presentation_id,
                "presented_version": effective_presented_version,
                "selection_version": selection_version,
                "selection_digest": effective_selection_digest,
                "options": normalized_options,
            }
        )
        replay = self._idempotency_replay(
            f"resource_download_prepare:{flow_id}",
            idempotency_key.strip(),
            request_hash,
        )
        if replay is not None:
            return replay

        resource_ids = list(selection["resource_ids"])
        resources = self.store.get_resources(flow_id, resource_ids)
        if [resource.get("resource_id") for resource in resources] != resource_ids:
            raise DomainError(
                "RESOLUTION_STALE",
                "选择中的资源已经变化，请重新搜索、检查并选择",
            )
        resolutions: list[dict[str, Any]] = []
        for resource in resources:
            try:
                fingerprint = source_fingerprint(resource)
            except (TypeError, ValueError) as exc:
                raise DomainError(
                    "RESOLUTION_STALE", "资源来源事实无法校验，请重新搜索并检查"
                ) from exc
            resolution = self.store.get_resource_resolution(
                flow_id,
                str(resource["resource_id"]),
                INSPECTION_PROFILE_VERSION,
                fingerprint,
            )
            if resolution is None:
                raise DomainError(
                    "RESOLUTION_STALE",
                    "下载准备需要每个所选资源的最新检查结果",
                    details={"resource_id": resource["resource_id"]},
                )
            resolutions.append(resolution)

        try:
            plan_items = self.acquisition_planner.plan_selection(
                resources, resolutions, preferred_container=str(container)
            )
        except AcquisitionPlanningError as exc:
            raise DomainError(
                exc.code, exc.message, retryable=exc.retryable, details=exc.details
            ) from exc

        confirmation_token = secrets.token_urlsafe(32)
        confirmation_hash = self._token_hash(confirmation_token)
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=self.settings.plan_ttl_seconds)
        ).isoformat()
        try:
            return self.store.create_plan(
                flow_id,
                effective_presentation_id,
                effective_presented_version,
                selection_version,
                effective_selection_digest,
                normalized_options,
                confirmation_token,
                confirmation_hash,
                expires_at,
                idempotency_key=idempotency_key.strip(),
                request_hash=request_hash,
                plan_items=plan_items,
            )
        except KeyError as exc:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在") from exc
        except LookupError as exc:
            raise DomainError("RESOURCE_NOT_SELECTED", "下载前必须存在非空的明确选择") from exc
        except ValueError as exc:
            if str(exc) == "idempotency_conflict":
                raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
            raise DomainError("VALIDATION_ERROR", "下载计划内容无效") from exc
        except RuntimeError as exc:
            mapping = {
                "selection_version_conflict": ("SELECTION_VERSION_CONFLICT", "选择版本已经变化"),
                "selection_changed": ("SELECTION_VERSION_CONFLICT", "当前展示或选择已经变化"),
                "presentation_version_conflict": ("PRESENTATION_VERSION_CONFLICT", "提交的展示版本已经失效"),
                "selection_digest_conflict": ("SELECTION_DIGEST_CONFLICT", "提交的选择摘要已经失效"),
                "resource_not_found": ("RESOURCE_NOT_FOUND", "选择中的资源已不存在"),
            }
            code, message = mapping.get(str(exc), ("FLOW_STATE_CONFLICT", "下载准备状态冲突"))
            raise DomainError(code, message) from exc

    def download_start(
        self,
        flow_id: str,
        plan_id: str,
        confirmation_token: str,
        idempotency_key: str,
        *,
        presentation_id: str,
        presented_version: int,
        selection_version: int,
        selection_digest: str,
        plan_digest: str,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        if not confirmation_token:
            raise DomainError("INVALID_ARGUMENT", "confirmation_token 不能为空")
        self._validate_idempotency_key(idempotency_key)
        if not isinstance(presentation_id, str) or not presentation_id:
            raise DomainError("INVALID_ARGUMENT", "presentation_id 不能为空")
        for field, value in (
            ("presented_version", presented_version),
            ("selection_version", selection_version),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise DomainError("INVALID_ARGUMENT", f"{field} 必须是正整数")
        for field, value in (
            ("selection_digest", selection_digest),
            ("plan_digest", plan_digest),
        ):
            if not isinstance(value, str) or _BARE_SHA256.fullmatch(value) is None:
                raise DomainError("INVALID_ARGUMENT", f"{field} 必须是 SHA-256 摘要")

        bindings = {
            "presentation_id": presentation_id,
            "presented_version": presented_version,
            "selection_version": selection_version,
            "selection_digest": selection_digest,
            "plan_digest": plan_digest,
        }
        normalized_key = idempotency_key.strip()
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "plan_id": plan_id,
                **bindings,
                "confirmation_token": confirmation_token,
            }
        )
        try:
            replayed = self.store.lookup_download_start_replay(
                idempotency_key=normalized_key,
                request_hash=request_hash,
                flow_id=flow_id,
                plan_id=plan_id,
            )
        except ValueError as exc:
            raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
        except RuntimeError as exc:
            raise DomainError("FLOW_STATE_CONFLICT", "下载重放状态冲突") from exc
        if replayed is not None:
            return {
                "flow_id": flow_id,
                "plan_id": plan_id,
                **bindings,
                "job_id": replayed["job_id"],
                "status": replayed["status"],
                "queued_at": replayed["created_at"],
            }

        plan = self.store.get_plan(plan_id)
        if plan is None or plan["flow_id"] != flow_id:
            raise DomainError("PLAN_NOT_FOUND", "下载计划不存在")
        plan_items = plan.get("plan_items")
        resource_ids = list(plan.get("resource_ids") or [])
        if (
            not isinstance(plan_items, list)
            or not plan_items
            or len(plan_items) != len(resource_ids)
            or [str(item.get("resource_id") or "") for item in plan_items] != resource_ids
        ):
            raise DomainError("PLAN_BINDING_CONFLICT", "下载计划缺少完整的资源获取项")
        resources = self.store.get_resources(flow_id, resource_ids)
        if [str(resource.get("resource_id") or "") for resource in resources] != resource_ids:
            raise DomainError(
                "RESOLUTION_STALE", "下载计划中的资源已经变化，请重新检查并准备下载"
            )

        for plan_item, resource in zip(plan_items, resources, strict=True):
            try:
                fingerprint = source_fingerprint(resource)
            except (TypeError, ValueError) as exc:
                raise DomainError(
                    "RESOLUTION_STALE",
                    "资源来源事实无法校验，请重新搜索并检查",
                    details={"resource_id": resource["resource_id"]},
                ) from exc
            resolution = self.store.get_resource_resolution(
                flow_id,
                str(resource["resource_id"]),
                INSPECTION_PROFILE_VERSION,
                fingerprint,
            )
            if resolution is None:
                raise DomainError(
                    "RESOLUTION_STALE",
                    "下载启动需要每个所选资源的最新检查结果",
                    details={"resource_id": resource["resource_id"]},
                )
            try:
                self.acquisition_planner.revalidate_plan_item(
                    plan_item, resource, resolution
                )
            except AcquisitionPlanningError as exc:
                raise DomainError(
                    exc.code, exc.message, retryable=exc.retryable, details=exc.details
                ) from exc

        try:
            job, reused = self.store.reserve_job(
                plan_id,
                self._token_hash(confirmation_token),
                normalized_key,
                request_hash,
                utc_now(),
                bindings=bindings,
            )
        except LookupError as exc:
            raise DomainError("PLAN_NOT_FOUND", "下载计划不存在") from exc
        except PermissionError as exc:
            raise DomainError("CONFIRMATION_INVALID", "确认令牌无效") from exc
        except TimeoutError as exc:
            raise DomainError("PLAN_EXPIRED", "下载计划已过期") from exc
        except ValueError as exc:
            if str(exc) == "idempotency_conflict":
                raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
            raise DomainError("VALIDATION_ERROR", "下载计划执行参数无效") from exc
        except RuntimeError as exc:
            mapping = {
                "plan_used": ("PLAN_ALREADY_USED", "下载计划已经使用"),
                "selection_changed": ("SELECTION_VERSION_CONFLICT", "用户选择已变化，请重新准备下载"),
                "plan_binding_mismatch": ("PLAN_BINDING_CONFLICT", "下载计划绑定信息不匹配"),
                "plan_item_missing": ("PLAN_BINDING_CONFLICT", "下载计划缺少资源获取项"),
                "resolution_stale": ("RESOLUTION_STALE", "资源检查结果已经变化，请重新检查并准备下载"),
                "failed to reserve job": ("INTERNAL_ERROR", "下载任务创建失败"),
            }
            code, message = mapping.get(str(exc), ("FLOW_STATE_CONFLICT", "下载状态冲突"))
            raise DomainError(code, message) from exc
        if not reused:
            self.job_runner.submit(
                job["job_id"],
                lambda cancel_event: self._run_download_job(job["job_id"], cancel_event),
            )
            self.store.audit(
                flow_id,
                "download.start",
                job["job_id"],
                {"plan_id": plan_id, "idempotency_key": normalized_key},
            )
        return {
            "flow_id": flow_id,
            "plan_id": plan_id,
            **bindings,
            "job_id": job["job_id"],
            "status": "queued",
            "queued_at": job["created_at"],
        }

    def _run_download_job(self, job_id: str, cancel_event: threading.Event) -> None:
        """Execute the immutable JobItem route without legacy authority slots."""

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
            for item in job_items:
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
                    resource=item["resource"],
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
                    expected_actual if observed_actual == expected_actual else (None, None, None, None)
                )

                if not acquisition.ok or acquisition.bundle is None:
                    failure = acquisition.failure
                    failure_code = failure.code if failure is not None else "DOWNLOAD_FAILED"
                    failure_message = failure.message if failure is not None else "获取任务没有产生可用结果"
                    failure_retryable = bool(failure.retryable) if failure is not None else False
                    failure_details = dict(failure.details) if failure is not None else {}
                    if failure_code == "JOB_CANCELLED":
                        if self._job_cancellation_is_persisted(job_id):
                            raise DomainError("JOB_CANCELLED", "任务已取消")
                        self.store.audit(
                            str(job["flow_id"]),
                            "download.provider_cancel_rejected",
                            job_id,
                            {"resource_id": resource_id, "provider_id": str(item["provider_id"])},
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
                    processed_count += 1
                    saw_partial = True
                    self._update_download_job_progress(
                        job_id, int((processed_count / total_items) * 100)
                    )
                    if failure_code in ACQUISITION_ABORT_CODES:
                        raise DomainError(
                            failure_code,
                            failure_message,
                            retryable=failure_retryable,
                            details=failure_details,
                        )
                    continue

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
                usable_primary_count += 1
                processed_count += 1
                saw_partial = saw_partial or bundle_completion == "partial"
                self._update_download_job_progress(
                    job_id, int((processed_count / total_items) * 100)
                )

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
                    failure_code=exc.code if exc.code in PUBLIC_JOB_FAILURE_CODES else "INTERNAL_ERROR",
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
                {"incident_id": incident_id, "exception_type": type(exc).__name__},
            )

    def job_status(self, flow_id: str, job_id: str) -> dict[str, Any]:
        self._require_flow(flow_id)
        job = self.store.get_job(job_id)
        if job is None or job["flow_id"] != flow_id:
            raise DomainError("JOB_NOT_FOUND", "任务不存在")
        plan = self.store.get_plan(job["plan_id"])
        if plan is None:
            raise DomainError("PLAN_NOT_FOUND", "任务对应的下载计划不存在")
        bundles = self.store.get_asset_bundles_for_job(job_id)
        try:
            execution_by_resource = {
                str(item["resource_id"]): item for item in self.store.get_job_items(job_id)
            }
        except RuntimeError:
            execution_by_resource = {}
        outcomes = [
            self._public_acquisition_outcome(
                outcome, execution_by_resource.get(str(outcome["resource_id"]))
            )
            for outcome in self.store.get_acquisition_outcomes_for_job(job_id)
        ]
        assets = []
        for asset_id in job["asset_ids"]:
            asset = self.store.get_asset(asset_id)
            if asset is not None and asset["status"] == "ready":
                assets.append(self._public_asset(asset))
        failures = self._public_bundle_failures(bundles)[:50]
        if not failures and job["error"]:
            public_error = self._public_stored_job_error(job["error"])
            failures = [public_error] if public_error is not None else []
        result = {
            "job_id": job_id,
            "flow_id": job["flow_id"],
            "plan_id": plan["plan_id"],
            "presentation_id": plan["presentation_id"],
            "presented_version": int(plan["presented_version"]),
            "selection_version": int(plan["selection_version"]),
            "selection_digest": plan["selection_digest"],
            "plan_digest": plan.get("plan_digest") or "",
            "status": job["status"],
            "progress": {
                "completed_items": min(
                    len(
                        [
                            outcome
                            for outcome in outcomes
                            if outcome["status"] in {"succeeded", "partial", "failed", "cancelled"}
                        ]
                    ),
                    len(plan["resource_ids"]),
                ),
                "total_items": len(plan["resource_ids"]),
                "percent": job["progress"],
            },
            "assets": assets,
            "failures": failures,
            "outcomes": outcomes,
            "updated_at": job["updated_at"],
        }
        completion = self._job_completion(job, bundles)
        if completion is not None:
            result["completion"] = completion
        return result

    @staticmethod
    def _public_acquisition_outcome(
        outcome: dict[str, Any], execution: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        planned = {
            "scope": str(outcome["planned_scope"]),
            "strategy": str(outcome["planned_strategy"]),
            "provider": {
                "provider_id": str(outcome["planned_provider_id"]),
                "version": str(outcome["planned_provider_version"]),
                "scope": str(outcome["planned_scope"]),
            },
        }
        result: dict[str, Any] = {
            "outcome_id": str(outcome["outcome_id"]),
            "resource_id": str(outcome["resource_id"]),
            "status": str(outcome["status"]),
            "planned": planned,
            "started_at": str(outcome["started_at"]),
        }
        if execution is not None:
            result["execution"] = {
                "scope": str(execution["planned_scope"]),
                "strategy": str(execution["strategy"]),
                "provider": {
                    "provider_id": str(execution["provider_id"]),
                    "version": str(execution["provider_version"]),
                    "scope": str(execution["planned_scope"]),
                },
                "representation_id": str(execution["representation_id"]),
                "revalidated_at": str(execution["revalidated_at"]),
            }
        if outcome.get("completed_at") is not None:
            result["completed_at"] = str(outcome["completed_at"])
        if outcome.get("actual_scope") is not None:
            result["actual"] = {
                "scope": str(outcome["actual_scope"]),
                "strategy": str(outcome["actual_strategy"]),
                "provider": {
                    "provider_id": str(outcome["actual_provider_id"]),
                    "version": str(outcome["actual_provider_version"]),
                    "scope": str(outcome["actual_scope"]),
                },
            }
        if outcome.get("bundle_id") is not None:
            result["bundle_id"] = str(outcome["bundle_id"])
        if isinstance(outcome.get("asset_ids"), list) and outcome["asset_ids"]:
            result["asset_ids"] = [str(asset_id) for asset_id in outcome["asset_ids"][:50]]
        if outcome.get("failure_code") is not None:
            result["failure"] = {
                "code": str(outcome["failure_code"]),
                "message": str(outcome.get("failure_message") or "资源获取失败")[:1024],
                "retriable": bool(outcome.get("retriable")),
            }
        return result


__all__ = ["ResourceService"]
