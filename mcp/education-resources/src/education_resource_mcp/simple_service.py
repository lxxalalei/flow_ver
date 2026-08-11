"""Active ResourceService with the 0037 simplified acquisition state path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets
import threading
from typing import Any

from .acquisition import AcquisitionRouter, AcquisitionStrategy, ProviderRegistration
from .acquisition.planner import AcquisitionPlanner, AcquisitionPlanningError
from .acquisition.web_materializer import WebMaterializer as StaticWebMaterializer
from .archive import ArchiveFileManager
from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .inspection import INSPECTION_PROFILE_VERSION, InspectionRouter, source_fingerprint
from .inspection_registry import default_inspection_router
from .jobs import JobRunner
from .search import SearchProvider, default_search_provider
from .session_bridge import create_session_store
from .simple_storage import Store
from .storage import utc_now
from .service import ResourceService as _LegacyResourceService


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
