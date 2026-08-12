"""Domain service backing the public MCP tools."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import secrets
import threading
from typing import Any

from .acquisition import (
    AcquisitionRequest,
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from .acquisition.planner import AcquisitionPlanner, AcquisitionPlanningError
from .acquisition.web_materializer import WebMaterializer as StaticWebMaterializer
from .archive import (
    ArchiveFileError,
    ArchiveFileManager,
    build_relative_path,
    resource_format,
)
from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .inspection import (
    INSPECTION_PROFILE_VERSION,
    InspectionRouter,
    resolution_evidence_is_fresh,
    source_fingerprint,
)
from .inspection_registry import default_inspection_router
from .jobs import JobRunner
from .policy import PolicyError, ensure_within_root
from .retrieval import CandidateResourceInternal, deduplicate_candidates
from .retrieval.registry import RegistrySnapshot
from .retrieval.identity import identities_match, resolve_identity
from .search import SearchProvider, canonical_http_url, default_search_provider
from .session_bridge import create_session_store
from .storage import Store, new_id, utc_now
from .taxonomy import (
    domain_display_name,
    normalize_archive_metadata,
    normalize_legacy_domain,
)


LOGGER = logging.getLogger(__name__)

TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
REPRESENTATION_ID_PATTERN = re.compile(r"^repr_[A-Za-z0-9_-]{16,64}$")
BARE_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_BARE_SHA256 = re.compile(r"^[a-f0-9]{64}$")
PERSISTED_ASSET_ROLES = {
    "primary",
    "subtitle",
    "cover",
    "metadata",
    "attachment",
    "transcript",
    "companion",
}
ACQUISITION_ABORT_CODES = {
    "AUTH_REQUIRED",
    "JOB_CANCELLED",
    "NETWORK_BLOCKED",
    "POLICY_DENIED",
    "REDIRECT_BLOCKED",
}
PUBLIC_JOB_FAILURE_CODES = {
    "AUTH_REQUIRED",
    "CONTENT_TYPE_REJECTED",
    "CONTENT_VALIDATION_FAILED",
    "DOWNLOAD_FAILED",
    "DOWNLOAD_TOO_LARGE",
    "INTERNAL_ERROR",
    "JOB_CANCELLED",
    "NETWORK_BLOCKED",
    "PARTIAL_FAILURE",
    "PLATFORM_UNAVAILABLE",
    "POLICY_DENIED",
    "RATE_LIMITED",
    "REDIRECT_BLOCKED",
    "STORAGE_UNAVAILABLE",
}


def _provider_resource(item: dict[str, Any], selected_container: str) -> dict[str, Any]:
    """Build the private Provider input from one immutable JobItem."""

    resource = dict(item["resource"])
    if str(item["provider_id"]) == "smartedu-resource":
        resource["_planned_representation"] = {
            "representation_id": str(item["representation_id"]),
            "container": selected_container,
        }
    return resource


class ResourceService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: Store | None = None,
        search_provider: SearchProvider | None = None,
        download_provider: DownloadProvider | None = None,
        acquisition_router: AcquisitionRouter | None = None,
        job_runner: JobRunner | None = None,
        archive_file_manager: ArchiveFileManager | None = None,
        inspection_router: InspectionRouter | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.settings.ensure_directories()
        self.store = store or Store(self.settings.database_path)
        self.session_store = create_session_store(self.settings)
        self.search_provider = search_provider or default_search_provider(
            self.settings, self.session_store
        )
        self.inspection_router = inspection_router or default_inspection_router(
            self.settings, session_store=self.session_store
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
            except Exception as exc:  # optional provider plugin boundary
                LOGGER.warning("Provider smartedu-resource unavailable during initialization (%s)", type(exc).__name__)
            try:
                from .adapters.douyin_download import DouyinDownloader

                registrations.append(
                    ProviderRegistration(
                        provider_id="douyin-video",
                        provider_version="1.0.0",
                        provider=DouyinDownloader(self.session_store, self.settings),
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                )
            except Exception as exc:  # optional provider plugin boundary
                LOGGER.warning("Provider douyin-video unavailable during initialization (%s)", type(exc).__name__)
            try:
                from .adapters.ximalaya_download import XimalayaDownloader

                registrations.append(
                    ProviderRegistration(
                        provider_id="ximalaya-audio",
                        provider_version="1.0.0",
                        provider=XimalayaDownloader(self.session_store, self.settings),
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                )
            except Exception as exc:  # optional provider plugin boundary
                LOGGER.warning("Provider ximalaya-audio unavailable during initialization (%s)", type(exc).__name__)
            try:
                from .adapters.bilibili_download import BilibiliDownloader

                registrations.append(
                    ProviderRegistration(
                        provider_id="bilibili-video",
                        provider_version="1.0.0",
                        provider=BilibiliDownloader(self.session_store, self.settings),
                        strategies=(AcquisitionStrategy.DIRECT_FILE,),
                        scopes=("primary_resource",),
                    )
                )
            except Exception as exc:  # optional provider plugin boundary
                LOGGER.warning("Provider bilibili-video unavailable during initialization (%s)", type(exc).__name__)
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

    def flow_start(
        self,
        idempotency_key: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_idempotency_key(idempotency_key)
        goal = task.get("goal") if isinstance(task, dict) else None
        topic = str((goal or {}).get("topic") or "").strip()
        if not topic:
            raise DomainError("INVALID_ARGUMENT", "task.goal.topic 不能为空")
        normalized_task: dict[str, Any] = {
            "goal": {"topic": topic},
            "constraints": [],
        }
        outcome = str((goal or {}).get("outcome") or "").strip()
        if outcome:
            normalized_task["goal"]["outcome"] = outcome
        for field in ("user_role", "resource_target"):
            value = task.get(field)
            if value is not None:
                if value not in {"child", "parent"}:
                    raise DomainError("INVALID_ARGUMENT", f"task.{field} 只能是 child 或 parent")
                normalized_task[field] = value
        constraints = task.get("constraints") or []
        if not isinstance(constraints, list):
            raise DomainError("INVALID_ARGUMENT", "task.constraints 必须是数组")
        for item in constraints:
            if not isinstance(item, dict):
                raise DomainError("INVALID_ARGUMENT", "每个 constraint 必须是对象")
            kind = str(item.get("kind") or "").strip()
            value = str(item.get("value") or "").strip()
            if not kind or not value:
                raise DomainError("INVALID_ARGUMENT", "constraint.kind 和 value 不能为空")
            normalized_task["constraints"].append(
                {"constraint_id": new_id("con"), "kind": kind, "value": value}
            )
        request_hash = self._request_hash(task)
        try:
            return self.store.create_flow(
                normalized_task, idempotency_key, request_hash
            )
        except ValueError as exc:
            if str(exc) == "idempotency_conflict":
                raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
            raise

    def search(
        self,
        flow_id: str,
        idempotency_key: str,
        search_tasks: list[dict[str, Any]],
        *,
        task_version: int | None = None,
        mode: str = "replace",
        base_result_set_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        flow = self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        current_task_version = int(flow.get("task_version") or 1)
        effective_task_version = (
            current_task_version if task_version is None else int(task_version)
        )
        if effective_task_version != current_task_version:
            raise DomainError("TASK_VERSION_CONFLICT", "任务版本已经变化")
        normalised_mode = str(mode or "replace").strip().lower()
        normalised_base = str(base_result_set_id or "").strip() or None
        if normalised_mode not in {"replace", "extend"}:
            raise DomainError("INVALID_ARGUMENT", "mode 只能是 replace 或 extend")
        if normalised_mode == "replace" and normalised_base is not None:
            raise DomainError("INVALID_ARGUMENT", "replace 不得提供 base_result_set_id")
        if normalised_mode == "extend" and normalised_base is None:
            raise DomainError("INVALID_ARGUMENT", "extend 必须提供 base_result_set_id")
        if not 1 <= limit <= self.settings.max_search_results:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"limit 必须在 1 到 {self.settings.max_search_results} 之间",
            )
        # Validate and normalise search_tasks.
        if not search_tasks or not isinstance(search_tasks, list):
            raise DomainError("INVALID_ARGUMENT", "search_tasks 不能为空")
        normalised_tasks: list[dict[str, Any]] = []
        all_queries: list[str] = []
        for task in search_tasks:
            if not isinstance(task, dict):
                raise DomainError("INVALID_ARGUMENT", "每个 search_task 必须是对象")
            platform = str(task.get("platform") or "").strip()
            if not platform:
                raise DomainError("INVALID_ARGUMENT", "search_task.platform 不能为空")
            raw_queries = task.get("queries") or []
            if not isinstance(raw_queries, list) or not raw_queries:
                raise DomainError("INVALID_ARGUMENT", "search_task.queries 不能为空")
            clean_queries: list[dict[str, str]] = []
            for q in raw_queries:
                query_text = str((q or {}).get("query") or "").strip()
                if not query_text:
                    raise DomainError("INVALID_ARGUMENT", "query 不能为空")
                clean_queries.append({"query": query_text})
                all_queries.append(query_text)
            normalised_task: dict[str, Any] = {
                "platform": platform,
                "queries": clean_queries,
            }
            direction = str(task.get("direction") or "").strip()
            if direction:
                if len(direction) > 256:
                    raise DomainError("INVALID_ARGUMENT", "search_task.direction 不能超过 256 字符")
                normalised_task["direction"] = direction
            normalised_tasks.append(normalised_task)
        search_filters = filters or {}
        request = {
            "flow_id": flow_id,
            "search_tasks": normalised_tasks,
            "task_version": effective_task_version,
            "mode": normalised_mode,
            "base_result_set_id": normalised_base,
            "filters": search_filters,
            "limit": limit,
        }
        request_hash = self._request_hash(request)
        scope = f"resource_search:{flow_id}"
        replay = self._idempotency_replay(scope, idempotency_key, request_hash)
        if replay is not None:
            return self._public_search_snapshot(replay)

        base_result_set: dict[str, Any] | None = None
        if normalised_mode == "extend":
            base_result_set = self.store.get_result_set(normalised_base or "")
            if base_result_set is None or base_result_set.get("flow_id") != flow_id:
                raise DomainError("RESULT_SET_NOT_FOUND", "基础 ResultSet 不存在")
            if flow.get("current_result_set_id") != normalised_base:
                raise DomainError("RESULT_SET_STATE_CONFLICT", "基础 ResultSet 已不是当前快照")
            if int(base_result_set.get("task_version") or 1) != effective_task_version:
                raise DomainError("TASK_VERSION_CONFLICT", "基础 ResultSet 的任务版本已经变化")
        raw_resources, platform_runs = self.search_provider.search(
            normalised_tasks, limit
        )
        platform_runs = self._annotate_search_directions(
            normalised_tasks,
            platform_runs,
        )
        incoming_candidates = self._normalise_retrieval_candidates(
            raw_resources, default_platform="generic"
        )
        base_candidates = self._stored_retrieval_candidates(base_result_set)
        metrics = self._retrieval_provenance(base_candidates, incoming_candidates)
        merged_candidates = deduplicate_candidates(
            [*base_candidates, *incoming_candidates],
            limit=limit,
        )
        retained_base_count = len(deduplicate_candidates(base_candidates, limit=limit))
        metrics["new_displayable_count"] = max(
            0,
            len(merged_candidates) - retained_base_count,
        )
        resources = self._materialise_retrieval_candidates(merged_candidates)
        round_number = (
            int((base_result_set or {}).get("round") or 1) + 1
            if normalised_mode == "extend"
            else 1
        )
        provenance = metrics
        # Extract flat failures from platform_runs query_run errors.
        failures: list[dict[str, Any]] = []
        for run in platform_runs:
            platform = str(run.get("platform") or "generic")
            for qr in run.get("query_runs") or []:
                err = qr.get("error")
                if err:
                    failures.append(
                        {
                            "platform": platform,
                            "code": self._normalise_failure_code(err.get("code")),
                            "message": str(err.get("message") or "搜索来源失败")[:1024],
                            "retriable": bool(err.get("retryable")),
                        }
                    )
        failures = failures[:32]
        coverage = self._fact_coverage(resources, platform_runs, failures)
        # Build a human-readable summary for audit/storage.
        query_summary = "; ".join(all_queries)[:1000]
        try:
            result = self.store.create_result_set(
                flow_id,
                resources,
                query=query_summary,
                task_version=effective_task_version,
                filters=search_filters,
                failures=failures,
                platform_runs=platform_runs,
                mode=normalised_mode,
                base_result_set_id=normalised_base,
                provenance=provenance,
                coverage=coverage,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            return self._public_search_snapshot(result)
        except KeyError as exc:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在") from exc
        except ValueError as exc:
            if str(exc) == "idempotency_conflict":
                raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
            if str(exc) in {
                "invalid_result_set_mode",
                "base_result_set_required",
                "base_result_set_forbidden",
            }:
                raise DomainError("INVALID_ARGUMENT", "ResultSet 扩展参数无效") from exc
            if str(exc) in {"base_result_set_not_found", "base_result_set_flow_mismatch"}:
                raise DomainError("RESULT_SET_NOT_FOUND", "基础 ResultSet 不存在") from exc
            raise
        except RuntimeError as exc:
            if str(exc) == "task_version_conflict":
                raise DomainError("TASK_VERSION_CONFLICT", "任务版本已经变化") from exc
            if str(exc) == "base_task_version_conflict":
                raise DomainError("TASK_VERSION_CONFLICT", "基础 ResultSet 的任务版本已经变化") from exc
            if str(exc) == "base_result_set_stale":
                raise DomainError("RESULT_SET_STATE_CONFLICT", "基础 ResultSet 已不是当前快照") from exc
            raise DomainError("FLOW_STATE_CONFLICT", "搜索状态冲突") from exc

    def browse_creator(
        self,
        flow_id: str,
        idempotency_key: str,
        platform: str,
        creator_id: str,
        *,
        task_version: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Browse a creator's full content list (social-media platforms only).

        Unlike ``search`` which takes keyword queries, this fetches all
        videos/posts from a specific creator's homepage via the adapter's
        ``search_creator`` method.  Only social-media adapters implement it;
        education/resource platforms return FEATURE_NOT_SUPPORTED.
        """
        flow = self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        current_task_version = int(flow.get("task_version") or 1)
        effective_task_version = (
            current_task_version if task_version is None else int(task_version)
        )
        if effective_task_version != current_task_version:
            raise DomainError("TASK_VERSION_CONFLICT", "任务版本已经变化")
        if not 1 <= limit <= self.settings.max_search_results:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"limit 必须在 1 到 {self.settings.max_search_results} 之间",
            )
        creator_id = str(creator_id or "").strip()
        platform = str(platform or "").strip()
        if not creator_id or not platform:
            raise DomainError("INVALID_ARGUMENT", "platform 和 creator_id 不能为空")

        request = {
            "flow_id": flow_id,
            "platform": platform,
            "creator_id": creator_id,
            "task_version": effective_task_version,
            "limit": limit,
        }
        request_hash = self._request_hash(request)
        scope = f"browse_creator:{flow_id}"
        replay = self._idempotency_replay(scope, idempotency_key, request_hash)
        if replay is not None:
            return replay

        raw_resources, platform_runs = self.search_provider.search_creator(
            platform, creator_id, limit
        )
        resources = self._public_retrieval_candidates(
            raw_resources,
            default_platform=platform,
            limit=limit,
        )
        failures: list[dict[str, Any]] = []
        for run in platform_runs:
            run_platform = str(run.get("platform") or platform)
            for query_run in run.get("query_runs") or []:
                err = query_run.get("error")
                if err:
                    failures.append(
                        {
                            "platform": run_platform,
                            "code": self._normalise_failure_code(err.get("code")),
                            "message": str(err.get("message") or "创作者浏览失败")[:1024],
                            "retriable": bool(err.get("retryable")),
                        }
                    )
        failures = failures[:32]
        query_summary = f"creator:{platform}:{creator_id}"[:1000]
        try:
            return self.store.create_result_set(
                flow_id,
                resources,
                query=query_summary,
                task_version=effective_task_version,
                filters={},
                failures=failures,
                platform_runs=platform_runs,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                idempotency_scope=scope,
                idempotency_action="resource.browse_creator",
            )
        except KeyError as exc:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在") from exc
        except ValueError as exc:
            if str(exc) == "idempotency_conflict":
                raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
            raise
        except RuntimeError as exc:
            if str(exc) == "task_version_conflict":
                raise DomainError("TASK_VERSION_CONFLICT", "任务版本已经变化") from exc
            raise DomainError("FLOW_STATE_CONFLICT", "浏览状态冲突") from exc

    def inspect(
        self,
        flow_id: str,
        idempotency_key: str,
        resource_id: str,
    ) -> dict[str, Any]:
        """Inspect one server-owned resource and persist its Resolution."""

        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        profile_version = INSPECTION_PROFILE_VERSION
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "resource_id": resource_id,
                "profile_version": profile_version,
            }
        )
        scope = f"resource_inspect:{flow_id}"

        # This lock is deliberately separate from the mutation lock.  It
        # covers the replay/cache/network/save sequence so two calls sharing
        # an idempotency key cannot both perform an external inspection.
        with self._inspection_lock:
            replay = self._idempotency_replay(scope, idempotency_key, request_hash)
            if replay is not None:
                return self._public_resolution_output(
                    flow_id, resource_id, replay
                )

            resources = self.store.get_resources(flow_id, [resource_id])
            if len(resources) != 1 or resources[0].get("resource_id") != resource_id:
                # get_resources intentionally filters by Flow.  Do not reveal
                # whether a matching ID belongs to another Flow.
                raise DomainError("RESOURCE_NOT_FOUND", "资源不存在")
            resource = resources[0]
            fingerprint = source_fingerprint(resource)

            cached = self.store.get_cached_resolution(
                flow_id,
                resource_id,
                profile_version,
                fingerprint,
            )
            cache_status = "miss"
            if cached is not None and resolution_evidence_is_fresh(
                cached.get("resolved") or cached.get("resolved_resource") or {}
            ):
                resolved_resource = self._ensure_representation_ids(
                    cached.get("resolved") or cached.get("resolved_resource") or {}
                )
                inspection = self._with_cache_status(
                    cached.get("inspection") or {}, "hit"
                )
                failures = cached.get("failures") or []
                try:
                    saved = self.store.save_resolution(
                        flow_id,
                        resource_id,
                        profile_version,
                        fingerprint,
                        cached["resolution_status"],
                        resolved=resolved_resource,
                        inspection=inspection,
                        failures=failures,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        inspected_at=cached.get("inspected_at"),
                    )
                except ValueError as exc:
                    if str(exc) == "idempotency_conflict":
                        raise DomainError(
                            "IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求"
                        ) from exc
                    raise
                return self._public_resolution_output(
                    flow_id, resource_id, saved
                )
            if cached is not None:
                cache_status = "refresh"

            # The router preserves FEATURE_NOT_SUPPORTED as a domain error.
            # Unsupported platforms are not converted into a generic network
            # request and are not written as a false successful Resolution.
            result = self.inspection_router.inspect(resource)
            payload = result.to_mapping()
            resolved_resource = self._ensure_representation_ids(
                payload.get("resolved_resource") or {}
            )
            inspection = self._with_cache_status(
                payload.get("inspection") or {}, cache_status
            )
            try:
                saved = self.store.save_resolution(
                    flow_id,
                    resource_id,
                    profile_version,
                    fingerprint,
                    payload["resolution_status"],
                    resolved=resolved_resource,
                    inspection=inspection,
                    failures=payload.get("failures") or [],
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    inspected_at=inspection.get("inspected_at"),
                )
            except KeyError as exc:
                raise DomainError("RESOURCE_NOT_FOUND", "资源不存在") from exc
            except (LookupError, PermissionError) as exc:
                raise DomainError("RESOURCE_NOT_FOUND", "资源不存在") from exc
            except ValueError as exc:
                if str(exc) == "idempotency_conflict":
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求"
                    ) from exc
                raise
            return self._public_resolution_output(flow_id, resource_id, saved)


    def presentation_save(
        self,
        flow_id: str,
        result_set_id: str,
        displayed_resource_ids: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "result_set_id": result_set_id,
                "displayed_resource_ids": displayed_resource_ids,
            }
        )
        try:
            return self.store.create_presentation(
                flow_id,
                result_set_id,
                displayed_resource_ids,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except KeyError as exc:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在") from exc
        except LookupError as exc:
            raise DomainError("RESULT_SET_NOT_FOUND", "搜索结果集不存在") from exc
        except PermissionError as exc:
            raise DomainError("RESULT_SET_NOT_FOUND", "搜索结果集不存在") from exc
        except ValueError as exc:
            mapping = {
                "idempotency_conflict": ("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求"),
                "duplicate_resources": ("INVALID_ARGUMENT", "displayed_resource_ids 不得重复"),
            }
            code, message = mapping.get(str(exc), ("INVALID_ARGUMENT", "展示参数无效"))
            raise DomainError(code, message) from exc
        except RuntimeError as exc:
            mapping = {
                "result_set_superseded": ("RESULT_SET_STATE_CONFLICT", "搜索结果集已不是当前结果集"),
                "resource_not_in_result_set": ("RESOURCE_NOT_FOUND", "只能展示该结果集中的资源"),
            }
            code, message = mapping.get(str(exc), ("FLOW_STATE_CONFLICT", "展示状态冲突"))
            raise DomainError(code, message) from exc

    def selection_save(
        self,
        flow_id: str,
        idempotency_key: str,
        presentation_id: str,
        presented_version: int,
        selected_positions: list[int],
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "presentation_id": presentation_id,
                "presented_version": presented_version,
                "selected_positions": selected_positions,
            }
        )
        try:
            return self.store.save_selection(
                flow_id,
                presentation_id,
                presented_version,
                selected_positions,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except KeyError as exc:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在") from exc
        except LookupError as exc:
            raise DomainError("PRESENTATION_NOT_FOUND", "展示记录不存在") from exc
        except PermissionError as exc:
            raise DomainError("PRESENTATION_NOT_FOUND", "展示记录不存在") from exc
        except ValueError as exc:
            mapping = {
                "idempotency_conflict": ("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求"),
                "duplicate_positions": ("INVALID_ARGUMENT", "selected_positions 不得重复"),
                "invalid_position": ("INVALID_ARGUMENT", "选择位置必须从 1 开始"),
            }
            code, message = mapping.get(str(exc), ("INVALID_ARGUMENT", "选择参数无效"))
            raise DomainError(code, message) from exc
        except RuntimeError as exc:
            mapping = {
                "presentation_superseded": ("PRESENTATION_VERSION_CONFLICT", "展示版本已经失效"),
                "position_not_presented": ("POSITION_NOT_PRESENTED", "只能选择实际展示的位置"),
            }
            code, message = mapping.get(str(exc), ("FLOW_STATE_CONFLICT", "选择状态冲突"))
            raise DomainError(code, message) from exc

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
        if container not in {"original", "pdf", "epub", "mp4", "mp3", "m4a", "html", "text"}:
            raise DomainError("INVALID_ARGUMENT", "preferred_container 无效")
        fallback_value = download_options.get("allow_safe_fallback", False)
        if not isinstance(fallback_value, bool):
            raise DomainError("INVALID_ARGUMENT", "allow_safe_fallback 必须是布尔值")
        normalized_options = {
            "preferred_container": str(container),
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

    def flow_status(self, flow_id: str) -> dict[str, Any]:
        flow = self._require_flow(flow_id)
        result_set = (
            self.store.get_result_set(flow["current_result_set_id"])
            if flow.get("current_result_set_id")
            else None
        )
        presentation = (
            self.store.get_presentation(flow["current_presentation_id"])
            if flow.get("current_presentation_id")
            else None
        )
        selection = self.store.get_selection(flow_id)
        plan = self.store.get_latest_plan_for_flow(flow_id)
        job = self.store.get_latest_job_for_flow(flow_id)
        resolutions = self.store.list_latest_resolutions_for_flow(
            flow_id, include_unresolved=True
        )

        current_selection = None
        if (
            selection is not None
            and presentation is not None
            and selection.get("presentation_id") == presentation["presentation_id"]
            and int(selection.get("presented_version") or 0)
            == int(presentation["presented_version"])
        ):
            positions_by_id = {
                item["resource_id"]: int(item["display_position"])
                for item in presentation["items"]
            }
            current_selection = {
                "presentation_id": selection["presentation_id"],
                "presented_version": int(selection["presented_version"]),
                "selection_version": int(selection.get("selection_version") or 0),
                "selected_positions": [
                    positions_by_id[resource_id]
                    for resource_id in selection["resource_ids"]
                    if resource_id in positions_by_id
                ],
                "selected_resource_ids": selection["resource_ids"],
                "selection_digest": selection.get("selection_digest") or "",
                "stage": selection["status"],
                "cancelled": selection["status"] == "cancelled",
                "updated_at": selection["updated_at"],
            }

        current_plan = None
        if plan is not None:
            selection_matches = (
                current_selection is not None
                and plan.get("presentation_id")
                == current_selection["presentation_id"]
                and int(plan.get("presented_version") or 0)
                == current_selection["presented_version"]
                and int(plan.get("selection_version") or 0)
                == current_selection["selection_version"]
                and plan.get("selection_digest")
                == current_selection["selection_digest"]
            )
            if bool(plan["used"]):
                plan_status = "consumed"
            elif str(plan["expires_at"]) <= utc_now():
                plan_status = "expired"
            elif not selection_matches:
                plan_status = "invalidated"
            else:
                plan_status = "prepared"
            current_plan = {
                "plan_id": plan["plan_id"],
                "presentation_id": plan["presentation_id"],
                "presented_version": int(plan["presented_version"]),
                "selection_version": int(plan["selection_version"]),
                "selection_digest": plan["selection_digest"],
                "plan_digest": plan.get("plan_digest") or "",
                "status": plan_status,
                "expires_at": plan["expires_at"],
                "confirmation_required": plan_status == "prepared",
                "created_at": plan["created_at"],
            }
            plan_authority_digest = str(plan.get("authority_digest") or "")
            if BARE_SHA256_PATTERN.fullmatch(plan_authority_digest):
                current_plan["authority_digest"] = plan_authority_digest

        current_job = None
        if job is not None:
            job_plan = self.store.get_plan(job["plan_id"])
            if job_plan is not None:
                job_bundles = self.store.get_asset_bundles_for_job(job["job_id"])
                ready_asset_ids = []
                for asset_id in job["asset_ids"]:
                    asset = self.store.get_asset(asset_id)
                    if asset is not None and asset["status"] == "ready":
                        ready_asset_ids.append(asset_id)
                current_job = {
                    "job_id": job["job_id"],
                    "plan_id": job["plan_id"],
                    "presentation_id": job_plan["presentation_id"],
                    "presented_version": int(job_plan["presented_version"]),
                    "selection_version": int(job_plan["selection_version"]),
                    "selection_digest": job_plan["selection_digest"],
                    "plan_digest": job_plan.get("plan_digest") or "",
                    "status": job["status"],
                    "progress_percent": int(job["progress"]),
                    "asset_ids": ready_asset_ids,
                    "bundle_ids": [bundle["bundle_id"] for bundle in job_bundles],
                    "failures": self._public_bundle_failures(job_bundles)[:32]
                    or (
                        [self._public_stored_job_error(job.get("error"))]
                        if self._public_stored_job_error(job.get("error"))
                        else []
                    ),
                    "created_at": job["created_at"],
                    "updated_at": job["updated_at"],
                }
                job_authority_digest = str(job_plan.get("authority_digest") or "")
                if BARE_SHA256_PATTERN.fullmatch(job_authority_digest):
                    current_job["authority_digest"] = job_authority_digest
                completion = self._job_completion(job, job_bundles)
                if completion is not None:
                    current_job["completion"] = completion

        current_presentation = None
        if presentation is not None:
            current_presentation = {
                "presentation_id": presentation["presentation_id"],
                "result_set_id": presentation["result_set_id"],
                "presented_version": int(presentation["presented_version"]),
                "items": [
                    {
                        "display_position": int(item["display_position"]),
                        "resource_id": item["resource_id"],
                    }
                    for item in presentation["items"]
                ],
                "empty": not presentation["items"],
                "created_at": presentation["created_at"],
            }

        allowed = [
            "resource_flow_status",
            "resource_search",
            "resource_browse_creator",
            "resource_library_search",
        ]
        if result_set is not None:
            allowed.extend(["resource_presentation_save", "resource_inspect"])
        if current_presentation is not None:
            allowed.append("resource_selection_save")
        if current_selection is not None and current_selection["stage"] == "selected":
            allowed.append("resource_download_prepare")
        if current_plan is not None and current_plan["status"] == "prepared":
            allowed.append("resource_download_start")
        if current_job is not None and current_job["status"] not in TERMINAL_JOB_STATES:
            allowed.extend(["resource_job_status", "resource_job_cancel"])
        elif current_job is not None:
            allowed.append("resource_job_status")
            if current_job["status"] == "succeeded" and current_job["asset_ids"]:
                allowed.append("resource_archive")

        stage = str(flow["status"])
        if current_job is not None:
            if current_job["status"] in {"queued", "running", "cancelling"}:
                stage = "downloading"
            elif current_job["status"] == "succeeded":
                stage = "downloaded"
            elif current_job["status"] in {"failed", "cancelled"}:
                stage = current_job["status"]

        return {
            "flow_id": flow_id,
            "stage": stage,
            "task_version": int(flow.get("task_version") or 1),
            "task": flow["context"],
            "current_result_set": (
                {
                    "task_version": int(flow.get("task_version") or 1),
                    "search_run_id": result_set["search_run_id"],
                    "result_set_id": result_set["result_set_id"],
                    "result_version": int(result_set["result_version"]),
                    "mode": result_set.get("mode") or "replace",
                    **(
                        {"base_result_set_id": result_set["base_result_set_id"]}
                        if result_set.get("base_result_set_id")
                        else {}
                    ),
                    "round": int(result_set.get("round") or 1),
                    **(
                        {"provenance": result_set["provenance"]}
                        if result_set.get("provenance")
                        else {}
                    ),
                    **(
                        {"coverage": result_set["coverage"]}
                        if result_set.get("coverage")
                        else {}
                    ),
                    "status": result_set["status"],
                    "platform_runs": result_set.get("platform_runs") or [],
                    "candidates": [
                        self._public_resource(item)
                        for item in result_set["resources"]
                    ],
                    "failures": result_set["failures"],
                    "has_more": False,
                    "created_at": result_set["created_at"],
                }
                if result_set is not None
                else None
            ),
            "current_presentation": current_presentation,
            "current_selection": current_selection,
            "current_plan": current_plan,
            "current_job": current_job,
            "current_resolutions": [
                self._public_resolution_output(
                    flow_id,
                    str(resolution["resource_id"]),
                    resolution,
                )
                for resolution in resolutions[:50]
            ],
            "allowed_next_actions": list(dict.fromkeys(allowed)),
            "created_at": flow["created_at"],
            "updated_at": flow["updated_at"],
        }

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

    def job_cancel(
        self,
        flow_id: str,
        job_id: str,
        idempotency_key: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        job = self.store.get_job(job_id)
        if job is None or job["flow_id"] != flow_id:
            raise DomainError("JOB_NOT_FOUND", "任务不存在")
        request_hash = self._request_hash(
            {"flow_id": flow_id, "job_id": job_id, "reason": reason}
        )
        scope = f"resource_job_cancel:{flow_id}"
        with self._mutation_lock:
            replay = self._idempotency_replay(scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            try:
                cancellation = self.store.request_job_cancellation(job_id)
            except KeyError as exc:
                raise DomainError("JOB_NOT_FOUND", "任务不存在") from exc
            except ValueError as exc:
                if str(exc) == "job_not_cancellable":
                    raise DomainError("JOB_NOT_CANCELLABLE", "终态任务不能取消") from exc
                raise DomainError("FLOW_STATE_CONFLICT", "任务取消状态冲突") from exc
            except RuntimeError as exc:
                raise DomainError("FLOW_STATE_CONFLICT", "任务取消状态冲突") from exc

            if cancellation["status"] == "cancelled":
                status = "cancelled"
            else:
                active = self.job_runner.cancel(job_id)
                if not active:
                    try:
                        cancellation = self.store.finalize_job_cancellation(job_id)
                    except ValueError as exc:
                        if str(exc) == "job_not_cancellable":
                            raise DomainError(
                                "JOB_NOT_CANCELLABLE", "终态任务不能取消"
                            ) from exc
                        raise DomainError(
                            "FLOW_STATE_CONFLICT", "任务取消状态冲突"
                        ) from exc
                status = "cancelling" if active else "cancelled"
            result = {
                "flow_id": flow_id,
                "job_id": job_id,
                "status": status,
                "cancel_requested_at": utc_now(),
            }
            self.store.audit(
                flow_id, "job.cancel", job_id, {"status": status, "reason": reason}
            )
            self.store.put_idempotency(
                scope, idempotency_key, request_hash, job_id, result
            )
            return result

    def _run_download_job(self, job_id: str, cancel_event: threading.Event) -> None:
        """Execute the immutable JobItem route."""

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

    def archive(
        self,
        flow_id: str,
        job_id: str,
        asset_id: str,
        *,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        asset = self.store.get_asset(asset_id)
        if asset is None:
            raise DomainError("ASSET_NOT_FOUND", "资产不存在")
        job = self.store.get_job(job_id)
        if job is None or job["flow_id"] != flow_id or asset["job_id"] != job_id:
            raise DomainError("ASSET_NOT_FOUND", "资产不属于当前 Flow")
        if job["status"] != "succeeded" or asset["status"] != "ready":
            raise DomainError("ASSET_NOT_ARCHIVABLE", "只有成功且校验通过的资产可以归档")
        try:
            asset = self.store.assert_asset_archivable(asset_id)
        except KeyError as exc:
            raise DomainError("ASSET_NOT_FOUND", "资产不存在") from exc
        except ValueError as exc:
            raise DomainError(
                "ASSET_NOT_ARCHIVABLE",
                "资产缺少完整且一致的获取结果关系，不能归档",
            ) from exc
        raw_archive_metadata = dict(metadata or {})
        try:
            archive_metadata = normalize_archive_metadata(raw_archive_metadata)
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_ARGUMENT", f"归档分类无效：{exc}") from exc
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "job_id": job_id,
                "asset_id": asset_id,
                "metadata": archive_metadata,
            }
        )
        legacy_request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "job_id": job_id,
                "asset_id": asset_id,
                "metadata": raw_archive_metadata,
            }
        )
        scope = f"resource_archive:{flow_id}"
        source = Path(asset["local_path"]).resolve()
        try:
            ensure_within_root(source, self.settings.jobs_dir)
        except PolicyError as exc:
            raise DomainError("POLICY_DENIED", str(exc)) from exc
        if not source.is_file():
            raise DomainError("ASSET_NOT_FOUND", "资产文件不存在")
        resources = self.store.get_resources(flow_id, [asset["resource_id"]])
        if not resources:
            raise DomainError("ASSET_NOT_FOUND", "资产对应的 Resource 不存在")
        resource = resources[0]
        intended_relative_path = build_relative_path(
            archive_metadata["classification"],
            source_name=str(resource.get("platform") or ""),
            title=str(resource.get("title") or "学习资料"),
            filename=str(asset.get("filename") or source.name),
            media_type=str(asset["media_type"]),
        )

        with self._mutation_lock:
            idempotency = self.store.get_idempotency(scope, idempotency_key)
            if idempotency is not None:
                if idempotency["request_hash"] not in {
                    request_hash,
                    legacy_request_hash,
                }:
                    previous_result = idempotency.get("result")
                    same_asset = (
                        isinstance(previous_result, dict)
                        and previous_result.get("asset_id") == asset_id
                        and previous_result.get("job_id") == job_id
                    )
                    previous_archive = self.store.get_archive_for_asset(asset_id)
                    try:
                        same_metadata = (
                            previous_archive is not None
                            and normalize_archive_metadata(
                                previous_archive.get("metadata")
                            )
                            == archive_metadata
                        )
                    except (TypeError, ValueError):
                        same_metadata = False
                    if not (same_asset and same_metadata):
                        raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求")
                replay = idempotency.get("result")
                if isinstance(replay, dict) and replay.get("archive_status") == "ready":
                    return dict(replay)

            retry_reservation: dict[str, Any] | None = None
            existing = self.store.get_archive_for_asset(asset_id)
            if existing is not None:
                try:
                    existing_metadata = normalize_archive_metadata(existing.get("metadata"))
                except (TypeError, ValueError):
                    existing_metadata = existing.get("metadata") or {}
                if existing_metadata != archive_metadata:
                    raise DomainError("ARCHIVE_CONFLICT", "该 Asset 已使用不同分类元数据归档")
                if existing.get("status") == "pending":
                    self._reconcile_archive_item(existing)
                    existing = self.store.get_archive_for_asset(asset_id) or existing
                if existing.get("status") == "failed":
                    try:
                        retry_reservation = self.store.retry_archive_reservation(
                            existing["archive_id"]
                        )
                    except (KeyError, ValueError) as exc:
                        raise DomainError(
                            "STORAGE_UNAVAILABLE",
                            "失败归档当前不能安全重试",
                            retryable=True,
                        ) from exc
                    existing = None
                if existing is not None and (
                    existing.get("status") != "ready"
                    or not self._archive_file_is_ready(existing)
                ):
                    raise DomainError(
                        "STORAGE_UNAVAILABLE",
                        "既有归档记录尚未恢复为可用状态",
                        retryable=True,
                    )
                if existing is not None:
                    result = self._archive_result(
                        flow_id, job_id, asset, existing, deduplicated=True
                    )
                    if idempotency is None:
                        self.store.put_idempotency(
                            scope,
                            idempotency_key,
                            request_hash,
                            existing["archive_id"],
                            result,
                        )
                    elif existing.get("relative_path"):
                        self.store.mark_archive_ready(
                            existing["archive_id"],
                            relative_path=existing["relative_path"],
                            resource_format=existing.get("resource_format"),
                            flow_id=flow_id,
                            result=result,
                        )
                    return result

            if retry_reservation is not None:
                reservation = retry_reservation
            else:
                try:
                    reservation = self.store.reserve_archive(
                        asset_id,
                        archive_metadata,
                        intended_relative_path,
                        idempotency_scope=scope,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                    )
                except ValueError as exc:
                    if str(exc) == "idempotency_conflict":
                        raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
                    if str(exc) == "archive_metadata_conflict":
                        raise DomainError("ARCHIVE_CONFLICT", "该 Asset 已使用不同分类元数据归档") from exc
                    if str(exc) == "asset_not_archivable":
                        raise DomainError(
                            "ASSET_NOT_ARCHIVABLE",
                            "资产缺少完整且一致的获取结果关系，不能归档",
                        ) from exc
                    raise DomainError("INVALID_ARGUMENT", f"归档预留失败：{exc}") from exc
                except Exception as exc:
                    raise DomainError("STORAGE_UNAVAILABLE", "归档索引预留失败", retryable=True) from exc

            archive_id = reservation["archive_id"]
            try:
                if reservation.get("content_status") == "ready":
                    content = self.store.get_ready_content(
                        reservation["sha256"],
                        reservation["byte_size"],
                        reservation.get("media_type"),
                    )
                    if content is None or not content.get("relative_path"):
                        raise ArchiveFileError("deduplicated_content_missing", "去重内容缺少安全相对路径")
                    verified = self.archive_files.verify_ready(content["relative_path"])
                    if verified != "ready":
                        self.store.mark_archive_missing(archive_id, {"code": "CONTENT_MISSING"})
                        raise ArchiveFileError("deduplicated_content_unavailable", "既有去重内容不可用")
                    relative_path = str(content["relative_path"])
                    deduplicated = True
                else:
                    staged_relative = f".archive-staging/{archive_id}.pending"
                    staged_path = self.archive_files.absolute_for_internal_read(staged_relative)
                    if not staged_path.exists():
                        staged = self.archive_files.stage(
                            source,
                            media_type=str(asset["media_type"]),
                            operation_id=archive_id,
                        )
                        staged_relative = staged.relative_path
                    published = self.archive_files.publish_no_replace(
                        staged_relative,
                        intended_relative_path,
                    )
                    relative_path = published.relative_path
                    deduplicated = published.deduplicated

                pending = self.store.get_archive_for_asset(asset_id)
                if pending is None:
                    raise ArchiveFileError("archive_reservation_lost", "归档预留记录丢失")
                result = self._archive_result(
                    flow_id,
                    job_id,
                    asset,
                    {**pending, "relative_path": relative_path, "status": "ready"},
                    deduplicated=deduplicated,
                )
                ready = self.store.mark_archive_ready(
                    archive_id,
                    relative_path=relative_path,
                    resource_format=resource_format(
                        str(asset["media_type"]), str(asset.get("filename") or source.name)
                    ),
                    flow_id=flow_id,
                    result=result,
                )
                result["archived_at"] = ready.get("archived_at") or result["archived_at"]
                return result
            except ArchiveFileError as exc:
                try:
                    self.archive_files.remove_staging(
                        f".archive-staging/{archive_id}.pending"
                    )
                except (ArchiveFileError, OSError):
                    pass
                try:
                    self.store.mark_archive_failed(
                        archive_id, {"code": exc.code, "message": str(exc)}
                    )
                except (KeyError, ValueError):
                    pass
                if exc.code in {
                    "path_escape",
                    "symlink_escape",
                    "unsafe_destination",
                    "unsafe_library_root",
                }:
                    raise DomainError("POLICY_DENIED", str(exc)) from exc
                if exc.code == "asset_format_mismatch":
                    raise DomainError("ASSET_NOT_ARCHIVABLE", str(exc)) from exc
                raise DomainError("STORAGE_UNAVAILABLE", str(exc), retryable=True) from exc
            except OSError as exc:
                try:
                    self.archive_files.remove_staging(
                        f".archive-staging/{archive_id}.pending"
                    )
                except (ArchiveFileError, OSError):
                    pass
                try:
                    self.store.mark_archive_failed(
                        archive_id,
                        {"code": "FILESYSTEM_ERROR", "message": type(exc).__name__},
                    )
                except (KeyError, ValueError):
                    pass
                raise DomainError("STORAGE_UNAVAILABLE", "归档文件提交失败", retryable=True) from exc
            except Exception as exc:
                # The published file remains tied to a pending row.  Startup
                # reconciliation can safely finish the commit after SQLite recovers.
                raise DomainError("STORAGE_UNAVAILABLE", "归档索引提交失败", retryable=True) from exc

    def library_search(
        self,
        flow_id: str,
        *,
        filters: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        if not 1 <= limit <= 50:
            raise DomainError("INVALID_ARGUMENT", "limit 必须在 1 到 50 之间")
        library_filters = self._normalize_library_filters(filters or {})
        keyset = self._decode_library_cursor(cursor, library_filters) if cursor else None
        page = self.store.search_library(
            library_filters.get("query"),
            limit,
            filters=library_filters,
            cursor=keyset,
        )
        assets: list[dict[str, Any]] = []
        for item in page["items"]:
            if not self._archive_file_is_ready(item):
                self.store.mark_archive_missing(item["archive_id"], {"code": "CONTENT_MISSING"})
                continue
            classification = dict(item["classification"])
            primary_domain = classification.get("primary_domain")
            public_item: dict[str, Any] = {
                "archive_id": item["archive_id"],
                "asset_id": item["asset_id"],
                "resource_id": item["resource_id"],
                "platform": item["platform"],
                "title": item["title"],
                "resource_type": item["resource_type"],
                "resource_format": item["resource_format"],
                "media_type": item["media_type"],
                "size_bytes": item["byte_size"],
                "sha256": item["sha256"],
                "classification": classification,
                "tags": item.get("tags") or [],
                "archived_at": item["archived_at"],
            }
            if item.get("bundle_id"):
                public_item.update(
                    {
                        "bundle_id": item["bundle_id"],
                        "role": item["role"],
                        "order": int(item["position"]) + 1,
                        "bundle_completion": item.get("bundle_completion")
                        or item["completion"],
                    }
                )
            if primary_domain:
                public_item["primary_domain"] = primary_domain
                public_item["primary_domain_display_name"] = domain_display_name(
                    primary_domain
                )
            else:
                public_item["primary_domain_display_name"] = "待分类"
            if item.get("collection"):
                public_item["collection"] = item["collection"]
            relative_path = item.get("relative_path")
            if relative_path:
                public_item["relative_path"] = relative_path
                public_item["library_path"] = relative_path
            assets.append(public_item)
        result: dict[str, Any] = {
            "flow_id": flow_id,
            "assets": assets,
            "has_more": bool(page["has_more"]),
        }
        if page.get("next_keyset"):
            result["next_cursor"] = self._encode_library_cursor(
                page["next_keyset"], library_filters
            )
        return result

    def _archive_result(
        self,
        flow_id: str,
        job_id: str,
        asset: dict[str, Any],
        archive: dict[str, Any],
        *,
        deduplicated: bool,
    ) -> dict[str, Any]:
        classification = dict(archive.get("classification") or {})
        result: dict[str, Any] = {
            "flow_id": flow_id,
            "job_id": job_id,
            "asset_id": asset["asset_id"],
            "resource_id": asset["resource_id"],
            "archive_id": archive["archive_id"],
            "archive_status": "ready",
            "archived_at": archive.get("archived_at") or archive.get("created_at") or utc_now(),
            "deduplicated": bool(deduplicated),
            "classification": classification,
        }
        primary_domain = classification.get("primary_domain")
        if primary_domain:
            result["primary_domain_display_name"] = domain_display_name(primary_domain)
        else:
            result["primary_domain_display_name"] = "待分类"
        if archive.get("relative_path"):
            result["relative_path"] = archive["relative_path"]
        result.update(self._bundle_relation_for_asset(str(asset["asset_id"])))
        return result

    def _normalize_library_filters(self, filters: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            key: value
            for key, value in filters.items()
            if value is not None and value != [] and value != ""
        }
        legacy_primary = normalized.pop("primary_domain", None)
        if legacy_primary is not None:
            mapped = normalize_legacy_domain(legacy_primary)
            if mapped is None:
                raise DomainError("INVALID_ARGUMENT", "primary_domain 不是已知学习领域")
            existing = list(normalized.get("primary_domains") or [])
            if mapped not in existing:
                existing.append(mapped)
            normalized["primary_domains"] = existing
        return normalized

    @staticmethod
    def _library_filter_digest(filters: dict[str, Any]) -> str:
        payload = json.dumps(filters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _base64url_encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _base64url_decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _encode_library_cursor(
        self, keyset: tuple[str, str], filters: dict[str, Any]
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "archived_at": keyset[0],
                "archive_id": keyset[1],
                "filter_digest": self._library_filter_digest(filters),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        body = self._base64url_encode(payload)
        signature = self._base64url_encode(
            hmac.new(self._library_cursor_key, body.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{body}.{signature}"

    def _decode_library_cursor(
        self, cursor: str, filters: dict[str, Any]
    ) -> tuple[str, str]:
        try:
            body, encoded_signature = cursor.split(".", 1)
            expected = hmac.new(
                self._library_cursor_key, body.encode("ascii"), hashlib.sha256
            ).digest()
            signature = self._base64url_decode(encoded_signature)
            if not hmac.compare_digest(signature, expected):
                raise ValueError("invalid signature")
            payload = json.loads(self._base64url_decode(body))
            if (
                payload.get("v") != 1
                or payload.get("filter_digest") != self._library_filter_digest(filters)
            ):
                raise ValueError("cursor does not match filters")
            archived_at = str(payload["archived_at"])
            archive_id = str(payload["archive_id"])
            if not archive_id.startswith("archive_") or not archived_at:
                raise ValueError("invalid cursor keyset")
            return archived_at, archive_id
        except (
            binascii.Error,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise DomainError("INVALID_ARGUMENT", "cursor 无效、已损坏或与过滤条件不匹配") from exc

    def _archive_file_status(self, archive: dict[str, Any]) -> str:
        relative_path = archive.get("relative_path")
        if relative_path:
            return self.archive_files.verify_ready(str(relative_path))
        return self._legacy_archive_file_status(archive)

    def _archive_file_is_ready(self, archive: dict[str, Any]) -> bool:
        return self._archive_file_status(archive) == "ready"

    def _legacy_archive_file_status(self, archive: dict[str, Any]) -> str:
        raw_path = archive.get("library_path")
        if not raw_path:
            return "missing"
        candidate = Path(str(raw_path))
        if not candidate.is_absolute() or candidate.is_symlink():
            return "missing"
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return "missing"
        allowed_roots = (self.settings.library_dir, *self.settings.legacy_library_dirs)
        if not any(self._path_is_within(resolved, Path(root).resolve()) for root in allowed_roots):
            return "missing"
        if not resolved.is_file():
            return "missing"
        return "ready"

    @staticmethod
    def _path_is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _reconcile_archives(self) -> None:
        for item in self.store.list_archive_reconciliation_items():
            self._reconcile_archive_item(item)

    def _reconcile_archive_item(self, item: dict[str, Any]) -> None:
        archive_id = str(item["archive_id"])
        status = str(item.get("status") or "")
        relative_path = item.get("relative_path")
        try:
            if status == "ready":
                file_status = self._archive_file_status(item)
                if file_status == "missing":
                    self.store.mark_archive_missing(archive_id, {"code": "CONTENT_MISSING"})
                return
            if status != "pending":
                return
            if item.get("content_status") == "ready" and relative_path:
                if self.archive_files.verify_ready(str(relative_path)) == "ready":
                    self.store.mark_archive_ready(
                        archive_id,
                        relative_path=str(relative_path),
                        resource_format=item.get("resource_format"),
                    )
                    return
            if relative_path and self.archive_files.verify_ready(str(relative_path)) == "ready":
                self.store.mark_archive_ready(
                    archive_id,
                    relative_path=str(relative_path),
                    resource_format=item.get("resource_format"),
                )
                return
            temporary = item.get("temporary_path") or f".archive-staging/{archive_id}.pending"
            temporary_path = self.archive_files.absolute_for_internal_read(str(temporary))
            if temporary_path.exists() and relative_path:
                published = self.archive_files.publish_no_replace(
                    str(temporary),
                    str(relative_path),
                )
                self.store.mark_archive_ready(
                    archive_id,
                    relative_path=published.relative_path,
                    resource_format=item.get("resource_format"),
                )
                return
            self.store.mark_archive_failed(archive_id, {"code": "PENDING_CONTENT_LOST"})
        except (ArchiveFileError, OSError, KeyError, ValueError) as exc:
            try:
                self.store.mark_archive_failed(
                    archive_id,
                    {"code": "ARCHIVE_RECONCILIATION_FAILED", "message": type(exc).__name__},
                )
            except (KeyError, ValueError):
                pass

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def session_status(
        self,
        platforms: list[str] | None = None,
        *,
        deep: bool = False,
    ) -> dict[str, Any]:
        """Return batch auth status for the requested platforms.

        When *deep* is true, platforms with a stored session are actively
        probed to confirm the session is still accepted server-side; each
        such entry gains ``probe_status``, ``probed_at`` and ``probe_detail``.
        """
        statuses = self.session_store.get_status(platforms)
        entries = [s.to_dict() for s in statuses]
        if deep:
            for entry, status in zip(entries, statuses):
                if status.status != "valid":
                    continue
                probe = self.session_store.validate(status.platform)
                entry["probe_status"] = probe["probe_status"]
                entry["probed_at"] = probe["probed_at"]
                if probe.get("detail"):
                    entry["probe_detail"] = probe["detail"]
            self.store.audit(
                None,
                "session.validate",
                None,
                {"platforms": [s.platform for s in statuses], "deep": True},
            )
        return {
            "sessions": entries,
            "needs_login": [
                {"platform": s.platform, "label": s.label, "login_url": s.login_url}
                for s in statuses
                if s.status in ("missing", "expired") and s.login_url
            ],
        }

    def session_save(
        self,
        platform: str,
        session_data: dict[str, Any],
        *,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist a captured browser session for *platform*."""
        result = self.session_store.save(
            platform, session_data, expires_at=expires_at
        )
        self.store.audit(None, "session.save", None, {"platform": platform})
        return result

    def session_delete(self, platform: str) -> dict[str, Any]:
        """Remove a stored session."""
        result = self.session_store.delete(platform)
        self.store.audit(None, "session.delete", None, {"platform": platform})
        return result

    def close(self) -> None:
        self.job_runner.shutdown(wait=True)

    def _job_cancellation_is_persisted(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        return bool(
            job is not None and job.get("status") in {"cancelling", "cancelled"}
        )

    def _raise_for_cancel_event(
        self, job_id: str, cancel_event: threading.Event
    ) -> None:
        """Treat the process-local event only as a wake-up signal."""

        if not cancel_event.is_set():
            return
        if self._job_cancellation_is_persisted(job_id):
            raise DomainError("JOB_CANCELLED", "任务已取消")
        raise DomainError(
            "INTERNAL_ERROR",
            "任务执行收到未持久化的中断信号",
        )

    def _finalize_download_job_failure(
        self,
        job_id: str,
        *,
        failure_code: str,
        failure_message: str,
        retriable: bool,
    ) -> None:
        """Publish failure unless a persisted cancellation request won first."""

        try:
            self.store.finalize_job_failure(
                job_id,
                failure_code=failure_code,
                failure_message=failure_message,
                retriable=retriable,
            )
        except ValueError as exc:
            if str(exc) != "job_cancelling":
                raise
            self.store.finalize_job_cancellation(job_id)

    def _start_download_job_execution(self, job_id: str) -> None:
        """Enter running state while preserving a persisted cancellation win."""

        try:
            self.store.start_job_execution(job_id)
        except ValueError as exc:
            if str(exc) != "job_cancelling":
                raise
            raise DomainError("JOB_CANCELLED", "任务已取消") from exc

    def _update_download_job_progress(self, job_id: str, progress: int) -> None:
        """Publish progress without allowing a runner to overwrite cancellation."""

        try:
            self.store.update_job_progress(job_id, progress)
        except ValueError as exc:
            if str(exc) != "job_cancelling":
                raise
            raise DomainError("JOB_CANCELLED", "任务已取消") from exc

    def _require_flow(self, flow_id: str) -> dict[str, Any]:
        flow = self.store.get_flow(flow_id)
        if flow is None:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在")
        return flow

    @staticmethod
    def _token_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _public_resource(item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata") or {}
        result = {
            "resource_id": item["resource_id"],
            "platform": item["platform"],
            "title": item["title"][:512],
            "resource_type": item["resource_type"],
            "canonical_url": item["source_url"],
            "availability": "unknown",
        }
        if item.get("summary"):
            result["summary"] = str(item["summary"])[:4000]
        if metadata.get("author"):
            result["author"] = str(metadata["author"])[:256]
        if metadata.get("language"):
            result["language"] = str(metadata["language"])[:35]
        return result

    @staticmethod
    def _public_search_snapshot(value: dict[str, Any]) -> dict[str, Any]:
        """Return a contract-safe copy of a durable search result."""

        result = json.loads(json.dumps(value))
        if result.get("base_result_set_id") is None:
            result.pop("base_result_set_id", None)
        return result

    @staticmethod
    def _ensure_representation_ids(value: Any) -> dict[str, Any]:
        """Copy a resolved resource and assign only server-owned IDs."""

        if not isinstance(value, dict):
            raise DomainError("INTERNAL_ERROR", "检查器返回的资源解析结果无效")
        resolved = dict(value)
        raw_representations = resolved.get("representations")
        if not isinstance(raw_representations, list):
            return resolved
        representations: list[dict[str, Any]] = []
        for raw_representation in raw_representations:
            if not isinstance(raw_representation, dict):
                raise DomainError("INTERNAL_ERROR", "检查器返回的表示形式无效")
            representation = dict(raw_representation)
            representation_id = representation.get("representation_id")
            if not isinstance(representation_id, str) or not REPRESENTATION_ID_PATTERN.fullmatch(
                representation_id
            ):
                representation["representation_id"] = new_id("repr")
            representations.append(representation)
        resolved["representations"] = representations
        return resolved

    @staticmethod
    def _with_cache_status(value: Any, cache_status: str) -> dict[str, Any]:
        inspection = dict(value) if isinstance(value, dict) else {}
        inspection["cache_status"] = cache_status
        return inspection

    @staticmethod
    def _public_resolution_output(
        flow_id: str, resource_id: str, value: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate Store's private Resolution row to the public shape."""

        resolved_resource = value.get("resolved_resource")
        if not isinstance(resolved_resource, dict):
            resolved_resource = value.get("resolved")
        if not isinstance(resolved_resource, dict):
            resolved_resource = {}
        inspection = value.get("inspection")
        if not isinstance(inspection, dict):
            inspection = {}
        failures = value.get("failures")
        if not isinstance(failures, list):
            failures = []
        return {
            "flow_id": flow_id,
            "resource_id": resource_id,
            "resolution_id": value.get("resolution_id"),
            "resolution_status": value.get("resolution_status"),
            "resolved_resource": json.loads(json.dumps(resolved_resource)),
            "inspection": json.loads(json.dumps(inspection)),
            "failures": json.loads(json.dumps(failures)),
        }

    def _public_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        result = {
            "asset_id": asset["asset_id"],
            "resource_id": asset["resource_id"],
            "size_bytes": asset["byte_size"],
            "media_type": asset["media_type"],
            "sha256": asset["sha256"],
            "validation_status": "validated",
            "created_at": asset["created_at"],
        }
        result.update(self._bundle_relation_for_asset(str(asset["asset_id"])))
        return result

    def _bundle_relation_for_asset(self, asset_id: str) -> dict[str, Any]:
        bundle = self.store.get_asset_bundle_for_asset(asset_id)
        if bundle is None:
            return {}
        for item in bundle.get("items") or []:
            if item.get("asset_id") != asset_id:
                continue
            return {
                "bundle_id": bundle["bundle_id"],
                "role": item["role"],
                "order": int(item["position"]) + 1,
                "bundle_completion": bundle["completion"],
            }
        return {}

    @staticmethod
    def _job_completion(
        job: dict[str, Any], bundles: list[dict[str, Any]]
    ) -> str | None:
        if job.get("status") != "succeeded" or not bundles:
            return None
        if all(
            bundle.get("status") == "succeeded"
            and bundle.get("completion") == "complete"
            for bundle in bundles
        ):
            return "complete"
        return "partial"

    @staticmethod
    def _public_bundle_failures(
        bundles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for bundle in bundles:
            items_by_id = {
                item.get("bundle_item_id"): item
                for item in bundle.get("items") or []
            }
            for failure in bundle.get("failures") or []:
                item = items_by_id.get(failure.get("bundle_item_id")) or {}
                code = str(failure.get("code") or "DOWNLOAD_FAILED")
                public: dict[str, Any] = {
                    "resource_id": bundle["resource_id"],
                    "code": (
                        code if code in PUBLIC_JOB_FAILURE_CODES else "DOWNLOAD_FAILED"
                    ),
                    "message": str(failure.get("message") or "资源项获取失败")[:1024],
                    "retriable": bool(failure.get("retriable")),
                    "bundle_id": bundle["bundle_id"],
                }
                if item:
                    public["role"] = item["role"]
                    public["order"] = int(item["position"]) + 1
                    metadata = item.get("metadata") or {}
                    if metadata.get("item_key"):
                        public["item_key"] = str(metadata["item_key"])
                failures.append(public)
        return failures

    @staticmethod
    def _public_stored_job_error(error: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(error, dict):
            return None
        code = str(error.get("code") or "DOWNLOAD_FAILED")
        return {
            "code": code if code in PUBLIC_JOB_FAILURE_CODES else "DOWNLOAD_FAILED",
            "message": str(error.get("message") or "资源获取失败")[:1024],
            "retriable": bool(error.get("retriable")),
        }

    def _public_retrieval_candidates(
        self,
        raw_resources: list[dict[str, Any]],
        *,
        default_platform: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Normalize, identify, and expose search candidates.

        URL policy validation and title filtering intentionally happen before
        identity resolution.  The retrieval layer then owns platform-aware
        identity matching and conservative enrichment; public IDs are minted
        only after the de-duplicated prefix has been selected.
        """

        internal_candidates = self._normalise_retrieval_candidates(
            raw_resources,
            default_platform=default_platform,
        )
        deduplicated = deduplicate_candidates(internal_candidates, limit=limit)
        return self._materialise_retrieval_candidates(deduplicated)

    def _normalise_retrieval_candidates(
        self,
        raw_resources: list[dict[str, Any]],
        *,
        default_platform: str,
    ) -> list[CandidateResourceInternal]:
        """Validate adapter candidates without minting public IDs."""

        internal_candidates: list[CandidateResourceInternal] = []
        for raw in raw_resources:
            if not isinstance(raw, dict):
                continue
            try:
                source_url = canonical_http_url(str(raw.get("source_url") or ""))
            except DomainError:
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue

            normalized = dict(raw)
            # Adapter-provided IDs are never authority-bearing public IDs.
            normalized.pop("resource_id", None)
            normalized["platform"] = str(raw.get("platform") or default_platform)
            normalized["title"] = title
            normalized["source_url"] = source_url
            # CandidateResourceInternal prefers canonical_url when present;
            # make the already policy-checked URL the only locator it sees.
            normalized["canonical_url"] = source_url
            normalized["resource_type"] = self._normalise_resource_type(
                str(raw.get("resource_type") or "other")
            )
            metadata = raw.get("metadata")
            normalized["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
            internal_candidates.append(
                CandidateResourceInternal.from_mapping(normalized)
            )
        return internal_candidates

    def _stored_retrieval_candidates(
        self,
        result_set: dict[str, Any] | None,
    ) -> list[CandidateResourceInternal]:
        """Rehydrate the private identity evidence of an immutable snapshot."""

        if result_set is None:
            return []
        candidates: list[CandidateResourceInternal] = []
        for resource in result_set.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            value = {
                "platform": resource.get("platform"),
                "title": resource.get("title"),
                "source_url": resource.get("source_url"),
                "resource_type": resource.get("resource_type"),
                "summary": resource.get("summary"),
                "metadata": resource.get("metadata") or {},
            }
            identity = resource.get("identity")
            if isinstance(identity, dict):
                value.update(identity)
            candidates.append(CandidateResourceInternal.from_mapping(value))
        return candidates

    @staticmethod
    def _retrieval_provenance(
        base_candidates: list[CandidateResourceInternal],
        incoming_candidates: list[CandidateResourceInternal],
    ) -> dict[str, int]:
        """Compute deterministic, recomputable cross-round information gain."""

        base_unique = deduplicate_candidates(base_candidates)
        round_unique: list[CandidateResourceInternal] = []
        duplicate_of_base = 0
        duplicate_within_round = 0
        identity_unknown = 0
        for candidate in incoming_candidates:
            identity = resolve_identity(candidate)
            if identity.key is None:
                identity_unknown += 1
            if any(
                identities_match(resolve_identity(existing), identity)
                for existing in base_unique
            ):
                duplicate_of_base += 1
                continue
            if any(
                identities_match(resolve_identity(existing), identity)
                for existing in round_unique
            ):
                duplicate_within_round += 1
                continue
            round_unique.append(candidate)
        duplicate_count = duplicate_of_base + duplicate_within_round
        new_unique_count = len(round_unique)
        return {
            "raw_candidate_count": len(incoming_candidates),
            "new_unique_count": new_unique_count,
            "duplicate_count": duplicate_count,
            "duplicate_of_base_count": duplicate_of_base,
            "duplicate_within_round_count": duplicate_within_round,
            "identity_unknown_count": identity_unknown,
            # The caller replaces this pre-limit value after applying the
            # immutable ResultSet's total-capacity limit.  Keeping the field in
            # this complete shape makes the helper independently testable.
            "new_displayable_count": new_unique_count,
        }

    @staticmethod
    def _annotate_search_directions(
        search_tasks: list[dict[str, Any]],
        platform_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Attach semantic SearchDirection labels without changing providers."""

        directions_by_query: dict[tuple[str, str], list[str]] = {}
        directions_by_platform: dict[str, list[str]] = {}
        for task in search_tasks:
            platform = str(task.get("platform") or "")
            direction = str(task.get("direction") or "").strip()
            if not direction:
                continue
            if direction not in directions_by_platform.setdefault(platform, []):
                directions_by_platform[platform].append(direction)
            for query in task.get("queries") or []:
                query_text = str((query or {}).get("query") or "").strip()
                key = (platform, query_text)
                if direction not in directions_by_query.setdefault(key, []):
                    directions_by_query[key].append(direction)

        annotated: list[dict[str, Any]] = []
        for raw_run in platform_runs:
            run = dict(raw_run) if isinstance(raw_run, dict) else {}
            platform = str(run.get("platform") or "")
            platform_directions = directions_by_platform.get(platform, [])
            if len(platform_directions) == 1:
                run["direction"] = platform_directions[0][:256]
            query_runs: list[dict[str, Any]] = []
            for raw_query_run in run.get("query_runs") or []:
                query_run = (
                    dict(raw_query_run)
                    if isinstance(raw_query_run, dict)
                    else {}
                )
                query_text = str(query_run.get("query") or "").strip()
                query_directions = directions_by_query.get((platform, query_text), [])
                if len(query_directions) == 1:
                    query_run["direction"] = query_directions[0][:256]
                query_runs.append(query_run)
            run["query_runs"] = query_runs
            annotated.append(run)
        return annotated

    def _materialise_retrieval_candidates(
        self,
        candidates: list[CandidateResourceInternal],
    ) -> list[dict[str, Any]]:
        """Mint fresh ResultSet-bound IDs while retaining private identity."""

        resources: list[dict[str, Any]] = []
        for candidate in candidates:
            # to_mapping keeps the public-facing adapter shape while retaining
            # only facts merged by the internal retrieval model.  The random
            # resource_id is deliberately created at this final boundary.
            candidate_mapping = candidate.to_mapping()
            resources.append(
                {
                    "resource_id": new_id("res"),
                    "platform": candidate_mapping["platform"],
                    "title": candidate_mapping["title"],
                    "source_url": candidate_mapping["source_url"],
                    "resource_type": self._normalise_resource_type(
                        str(candidate_mapping.get("resource_type") or "other")
                    ),
                    "summary": candidate_mapping.get("summary"),
                    "metadata": dict(candidate_mapping.get("metadata") or {}),
                    "identity": resolve_identity(candidate).to_mapping(),
                    "identity_rules_version": "identity-v1",
                }
            )
        return resources

    @staticmethod
    def _fact_coverage(
        resources: list[dict[str, Any]],
        platform_runs: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Report only server-observed ResultSet facts.

        This summary is deliberately not a recommendation, semantic coverage
        score, Skill Gap, or StopDecision.  It is persisted with the immutable
        ResultSet so recovery can distinguish machine-observed facts from the
        Skill's private, recomputed semantic review.
        """

        type_counts: dict[str, int] = {}
        platforms: set[str] = set()
        for resource in resources:
            resource_type = str(resource.get("resource_type") or "other")
            type_counts[resource_type] = type_counts.get(resource_type, 0) + 1
            platforms.add(str(resource.get("platform") or "generic"))

        gaps: list[dict[str, Any]] = []
        if not resources:
            gaps.append(
                {
                    "dimension": "source",
                    "reason": "本轮没有服务端记录的候选",
                    "count": 0,
                }
            )
        if failures:
            gaps.append(
                {
                    "dimension": "source",
                    "reason": "一个或多个检索来源失败",
                    "count": len(failures),
                }
            )
        if resources:
            gaps.append(
                {
                    "dimension": "inspection",
                    "reason": "候选尚未完成详情检查",
                    "count": len(resources),
                }
            )
        # Unknown identity is already projected by provenance.  It is not
        # availability evidence and therefore must not be relabelled as an
        # availability gap here.  Availability is only authoritative after a
        # concrete Resolution/Inspection fact exists.
        return {
            "kind": "factual",
            "schema_version": "factual-coverage-v1",
            "status": "empty" if not resources else ("partial" if gaps else "covered"),
            "candidate_count": len(resources),
            "platform_count": len(platforms or {
                str(run.get("platform") or "generic")
                for run in platform_runs
                if isinstance(run, dict)
            }),
            "resource_types": [
                {"resource_type": key, "count": type_counts[key]}
                for key in sorted(type_counts)
            ],
            "gaps": gaps,
        }

    @staticmethod
    def _normalise_resource_type(value: str) -> str:
        normalised = value.strip().lower()
        mapping = {
            "网页": "article",
            "文章": "article",
            "图书": "book",
            "文档": "document",
            "视频": "video",
            "音频": "audio",
            "课程": "course",
        }
        allowed = {"article", "book", "document", "video", "audio", "course", "dataset", "other"}
        return mapping.get(value.strip(), normalised if normalised in allowed else "other")

    @staticmethod
    def _normalise_failure_code(value: Any) -> str:
        allowed = {
            "PLATFORM_UNAVAILABLE",
            "PARTIAL_FAILURE",
            "AUTH_REQUIRED",
            "RATE_LIMITED",
            "POLICY_DENIED",
            "NETWORK_BLOCKED",
        }
        return str(value) if str(value) in allowed else "PARTIAL_FAILURE"

    @staticmethod
    def _failure_item(error: DomainError) -> dict[str, Any]:
        return {
            "code": error.code,
            "message": error.message[:1024],
            "retriable": error.retryable,
        }

    @staticmethod
    def _request_hash(value: dict[str, Any]) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_idempotency_key(value: str) -> None:
        if not IDEMPOTENCY_PATTERN.fullmatch(value):
            raise DomainError(
                "INVALID_ARGUMENT",
                "idempotency_key 必须为 16-128 位字母、数字或 ._:-",
            )

    def _idempotency_replay(
        self, scope: str, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        record = self.store.get_idempotency(scope, key)
        if record is None:
            return None
        if record["request_hash"] != request_hash:
            raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求")
        if not isinstance(record.get("result"), dict):
            return None
        return dict(record["result"])

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
