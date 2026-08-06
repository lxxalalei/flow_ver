"""Domain service backing the public MCP tools."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading
from typing import Any

from .archive import (
    ArchiveFileError,
    ArchiveFileManager,
    build_relative_path,
    resource_format,
)
from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .jobs import JobRunner
from .policy import PolicyError, ensure_within_root
from .search import SearchProvider, canonical_http_url, default_search_provider
from .session_bridge import create_session_store
from .storage import Store, new_id, utc_now
from .taxonomy import (
    domain_display_name,
    normalize_archive_metadata,
    normalize_legacy_domain,
)


TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class ResourceService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: Store | None = None,
        search_provider: SearchProvider | None = None,
        download_provider: DownloadProvider | None = None,
        job_runner: JobRunner | None = None,
        archive_file_manager: ArchiveFileManager | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.settings.ensure_directories()
        self.store = store or Store(self.settings.database_path)
        self.session_store = create_session_store(self.settings)
        self.search_provider = search_provider or default_search_provider(
            self.settings, self.session_store
        )
        self.download_provider = download_provider or PublicHttpDownloader(self.settings)
        self._platform_downloaders: dict[str, Any] = {}
        self._register_default_downloaders()
        self.job_runner = job_runner or JobRunner(self.settings.max_workers)
        self._mutation_lock = threading.RLock()
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
            return self.store.create_flow_v2(
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
            normalised_tasks.append({"platform": platform, "queries": clean_queries})
        search_filters = filters or {}
        request = {
            "flow_id": flow_id,
            "search_tasks": normalised_tasks,
            "task_version": effective_task_version,
            "filters": search_filters,
            "limit": limit,
        }
        request_hash = self._request_hash(request)
        scope = f"v2:resource_search:{flow_id}"
        replay = self._idempotency_replay(scope, idempotency_key, request_hash)
        if replay is not None:
            return replay
        raw_resources, platform_runs = self.search_provider.search(
            normalised_tasks, limit
        )
        resources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for raw in raw_resources:
            try:
                source_url = canonical_http_url(str(raw.get("source_url") or ""))
            except DomainError:
                continue
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            resources.append(
                {
                    "resource_id": new_id("res"),
                    "platform": str(raw.get("platform") or "generic"),
                    "title": title,
                    "source_url": source_url,
                    "resource_type": self._normalise_resource_type(
                        str(raw.get("resource_type") or "other")
                    ),
                    "summary": raw.get("summary"),
                    "metadata": dict(raw.get("metadata") or {}),
                }
            )
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
        # Build a human-readable summary for audit/storage.
        query_summary = "; ".join(all_queries)[:1000]
        try:
            return self.store.create_result_set_v2(
                flow_id,
                resources,
                query=query_summary,
                task_version=effective_task_version,
                filters=search_filters,
                failures=failures,
                platform_runs=platform_runs,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
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
            raise DomainError("FLOW_STATE_CONFLICT", "搜索状态冲突") from exc

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
            return self.store.create_presentation_v2(
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
            return self.store.save_selection_v2(
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
        selection = self.store.get_selection(flow_id)
        if selection is None:
            raise DomainError("RESOURCE_NOT_SELECTED", "下载前必须存在非空的明确选择")
        effective_presentation_id = presentation_id or str(selection.get("presentation_id") or "")
        effective_presented_version = (
            int(selection.get("presented_version") or 0)
            if presented_version is None
            else int(presented_version)
        )
        effective_selection_digest = selection_digest or str(
            selection.get("selection_digest") or ""
        )
        self._validate_idempotency_key(idempotency_key)
        download_options = options or {}
        container = str(download_options.get("preferred_container") or "html")
        strategy = "webpage" if container in {"html", "text", "pdf"} else "direct"
        effective_max = int(
            download_options.get("max_bytes_per_resource")
            or self.settings.max_download_bytes
        )
        if effective_max > self.settings.max_download_bytes:
            raise DomainError(
                "INVALID_ARGUMENT",
                "max_bytes 超出服务端允许范围",
                details={"server_max_bytes": self.settings.max_download_bytes},
            )
        normalized_options = {
            "strategy": strategy,
            "max_bytes": effective_max,
            "preferred_container": container,
            "allow_safe_fallback": bool(download_options.get("allow_safe_fallback", True)),
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
        confirmation_token = secrets.token_urlsafe(32)
        confirmation_hash = self._token_hash(confirmation_token)
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=self.settings.plan_ttl_seconds)
        ).isoformat()
        try:
            return self.store.create_plan_v2(
                flow_id,
                effective_presentation_id,
                effective_presented_version,
                selection_version,
                effective_selection_digest,
                normalized_options,
                confirmation_token,
                confirmation_hash,
                expires_at,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except KeyError as exc:
            raise DomainError("FLOW_NOT_FOUND", "Flow 不存在") from exc
        except LookupError as exc:
            raise DomainError("RESOURCE_NOT_SELECTED", "下载前必须存在非空的明确选择") from exc
        except ValueError as exc:
            if str(exc) == "idempotency_conflict":
                raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
            raise
        except RuntimeError as exc:
            mapping = {
                "selection_version_conflict": ("SELECTION_VERSION_CONFLICT", "选择版本已经变化"),
                "selection_changed": ("SELECTION_VERSION_CONFLICT", "当前展示或选择已经变化"),
                "presentation_version_conflict": ("PRESENTATION_VERSION_CONFLICT", "提交的展示绑定已经失效"),
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
        presentation_id: str | None = None,
        presented_version: int | None = None,
        selection_version: int | None = None,
        selection_digest: str | None = None,
        plan_digest: str | None = None,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        if not confirmation_token:
            raise DomainError("INVALID_ARGUMENT", "confirmation_token 不能为空")
        self._validate_idempotency_key(idempotency_key)
        plan = self.store.get_plan(plan_id)
        if plan is None or plan["flow_id"] != flow_id:
            raise DomainError("PLAN_NOT_FOUND", "下载计划不存在")
        bindings = {
            "presentation_id": presentation_id or str(plan.get("presentation_id") or ""),
            "presented_version": (
                int(plan.get("presented_version") or 0)
                if presented_version is None
                else int(presented_version)
            ),
            "selection_version": (
                int(plan.get("selection_version") or 0)
                if selection_version is None
                else int(selection_version)
            ),
            "selection_digest": selection_digest or str(
                plan.get("selection_digest") or ""
            ),
            "plan_digest": plan_digest or str(plan.get("plan_digest") or ""),
        }
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "plan_id": plan_id,
                **bindings,
                "confirmation_token": confirmation_token,
            }
        )
        try:
            job, reused = self.store.reserve_job(
                plan_id,
                self._token_hash(confirmation_token),
                idempotency_key.strip(),
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
            raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已绑定其他请求") from exc
        except RuntimeError as exc:
            mapping = {
                "plan_used": ("PLAN_ALREADY_USED", "下载计划已经使用"),
                "selection_changed": ("SELECTION_VERSION_CONFLICT", "用户选择已变化，请重新准备下载"),
                "plan_binding_mismatch": ("PLAN_BINDING_CONFLICT", "下载计划绑定信息不匹配"),
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
                {"plan_id": plan_id, "idempotency_key": idempotency_key.strip()},
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

        current_job = None
        if job is not None:
            job_plan = self.store.get_plan(job["plan_id"])
            if job_plan is not None:
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
                    "failures": [job["error"]] if job.get("error") else [],
                    "created_at": job["created_at"],
                    "updated_at": job["updated_at"],
                }

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

        allowed = ["resource_flow_status", "resource_search", "resource_library_search"]
        if result_set is not None:
            allowed.append("resource_presentation_save")
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
        assets = []
        for asset_id in job["asset_ids"]:
            asset = self.store.get_asset(asset_id)
            if asset is not None and asset["status"] == "ready":
                assets.append(self._public_asset(asset))
        return {
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
                "completed_items": len(assets),
                "total_items": len(plan["resource_ids"]),
                "percent": job["progress"],
            },
            "assets": assets,
            "failures": [job["error"]] if job["error"] else [],
            "updated_at": job["updated_at"],
        }

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
            if job["status"] in {"succeeded", "failed"}:
                raise DomainError("JOB_NOT_CANCELLABLE", "终态任务不能取消")
            if job["status"] == "cancelled":
                status = "cancelled"
            else:
                self.store.update_job(job_id, status="cancelling")
                active = self.job_runner.cancel(job_id)
                if not active:
                    self.store.quarantine_job_assets(job_id)
                    self.store.update_job(
                        job_id, status="cancelled", progress=job["progress"]
                    )
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
                    verified = self.archive_files.verify_ready(
                        content["relative_path"],
                        reservation["sha256"],
                        reservation["byte_size"],
                    )
                    if verified != "ready":
                        if verified == "corrupt":
                            self.store.mark_archive_corrupt(archive_id, {"code": "CONTENT_CORRUPT"})
                        else:
                            self.store.mark_archive_missing(archive_id, {"code": "CONTENT_MISSING"})
                        raise ArchiveFileError("deduplicated_content_unavailable", "既有去重内容不可用")
                    relative_path = str(content["relative_path"])
                    deduplicated = True
                else:
                    staged_relative = f".archive-staging/{archive_id}.pending"
                    staged_path = self.archive_files.absolute_for_internal_read(staged_relative)
                    if not staged_path.exists():
                        staged = self.archive_files.stage_and_verify(
                            source,
                            expected_sha256=asset["sha256"],
                            expected_size=int(asset["byte_size"]),
                            media_type=str(asset["media_type"]),
                            operation_id=archive_id,
                        )
                        staged_relative = staged.relative_path
                    published = self.archive_files.publish_no_replace(
                        staged_relative,
                        intended_relative_path,
                        sha256=asset["sha256"],
                        byte_size=int(asset["byte_size"]),
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
                if exc.code in {"asset_integrity_mismatch", "asset_format_mismatch"}:
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
                status = self._archive_file_status(item)
                if status == "corrupt":
                    self.store.mark_archive_corrupt(item["archive_id"], {"code": "CONTENT_CORRUPT"})
                else:
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
            return self.archive_files.verify_ready(
                str(relative_path),
                str(archive.get("content_sha256") or archive.get("sha256")),
                int(archive.get("content_byte_size") or archive.get("byte_size") or 0),
            )
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
        digest = hashlib.sha256()
        size = 0
        try:
            with resolved.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
        except OSError:
            return "missing"
        expected_size = int(archive.get("content_byte_size") or archive.get("byte_size") or 0)
        expected_sha = str(archive.get("content_sha256") or archive.get("sha256") or "")
        return "ready" if size == expected_size and digest.hexdigest() == expected_sha else "corrupt"

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
        expected_sha256 = str(item.get("sha256") or item.get("content_sha256") or "")
        expected_size = int(
            item.get("byte_size") or item.get("content_byte_size") or 0
        )
        try:
            if status == "ready":
                file_status = self._archive_file_status(item)
                if file_status == "missing":
                    self.store.mark_archive_missing(archive_id, {"code": "CONTENT_MISSING"})
                elif file_status == "corrupt":
                    self.store.mark_archive_corrupt(archive_id, {"code": "CONTENT_CORRUPT"})
                return
            if status != "pending":
                return
            if item.get("content_status") == "ready" and relative_path:
                if self.archive_files.verify_ready(
                    str(relative_path), expected_sha256, expected_size
                ) == "ready":
                    self.store.mark_archive_ready(
                        archive_id,
                        relative_path=str(relative_path),
                        resource_format=item.get("resource_format"),
                    )
                    return
            if relative_path and self.archive_files.verify_ready(
                str(relative_path), expected_sha256, expected_size
            ) == "ready":
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
                    sha256=expected_sha256,
                    byte_size=expected_size,
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

    def _register_default_downloaders(self) -> None:
        """Register platform-specific downloaders that resolve media URLs."""
        try:
            from .adapters.ximalaya_download import XimalayaDownloader
            self._platform_downloaders["ximalaya"] = XimalayaDownloader(self.session_store, self.settings)
        except ImportError:
            pass
        try:
            from .adapters.bilibili_download import BilibiliDownloader
            self._platform_downloaders["bilibili"] = BilibiliDownloader(self.session_store, self.settings)
        except ImportError:
            pass
        try:
            from .adapters.smartedu_download import SmartEduDownloader
            self._platform_downloaders["smartedu"] = SmartEduDownloader(self.session_store, self.settings)
        except ImportError:
            pass

    def _run_download_job(self, job_id: str, cancel_event: threading.Event) -> None:
        job = self.store.get_job(job_id)
        if job is None:
            return
        plan = self.store.get_plan(job["plan_id"])
        if plan is None:
            self.store.update_job(
                job_id,
                status="failed",
                error={"code": "PLAN_NOT_FOUND", "message": "任务对应的计划不存在"},
            )
            return
        resources = self.store.get_resources(job["flow_id"], plan["resource_ids"])
        asset_ids: list[str] = []
        try:
            self.store.update_job(job_id, status="running", progress=0)
            for index, resource in enumerate(resources):
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "任务已取消")
                # Route to platform-specific downloader if available.
                platform = str(resource.get("platform") or "")
                downloader = self._platform_downloaders.get(platform)
                if downloader is not None:
                    dl_result = downloader.download(
                        resource, job_id, str(plan["options"]["strategy"]),
                        int(plan["options"]["max_bytes"]), cancel_event,
                    )
                else:
                    dl_result = self.download_provider.download(
                    resource,
                    job_id,
                    str(plan["options"]["strategy"]),
                    int(plan["options"]["max_bytes"]),
                    cancel_event,
                )
                # Normalise to list — platform downloaders may return multiple files.
                dl_results = dl_result if isinstance(dl_result, list) else [dl_result]
                for result in dl_results:
                    try:
                        ensure_within_root(result.path.resolve(), self.settings.jobs_dir)
                    except PolicyError as exc:
                        raise DomainError("POLICY_DENIED", str(exc)) from exc
                    if not result.path.is_file():
                        raise DomainError("CONTENT_VALIDATION_FAILED", "下载器没有产生受控文件")
                    asset = self.store.create_asset(
                        job_id,
                        resource["resource_id"],
                        result.path.resolve(),
                        result.byte_size,
                        result.media_type,
                        result.sha256,
                        result.filename,
                    )
                    asset_ids.append(asset["asset_id"])
                progress = int(((index + 1) / max(len(resources), 1)) * 100)
                self.store.update_job(job_id, progress=progress, asset_ids=asset_ids)
            if cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "任务已取消")
            self.store.update_job(
                job_id, status="succeeded", progress=100, asset_ids=asset_ids
            )
        except DomainError as exc:
            self.store.quarantine_job_assets(job_id)
            status = "cancelled" if exc.code == "JOB_CANCELLED" or cancel_event.is_set() else "failed"
            self.store.update_job(
                job_id,
                status=status,
                asset_ids=asset_ids,
                error=self._failure_item(exc) if status == "failed" else None,
            )
        except Exception as exc:
            self.store.quarantine_job_assets(job_id)
            self.store.update_job(
                job_id,
                status="failed",
                asset_ids=asset_ids,
                error={
                    "code": "INTERNAL_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                    "retriable": False,
                },
            )

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
    def _public_asset(asset: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": asset["asset_id"],
            "resource_id": asset["resource_id"],
            "size_bytes": asset["byte_size"],
            "media_type": asset["media_type"],
            "sha256": asset["sha256"],
            "validation_status": "validated",
            "created_at": asset["created_at"],
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
