"""Domain service backing the public MCP tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import threading
from typing import Any

from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .jobs import JobRunner
from .policy import PolicyError, ensure_within_root
from .search import SearchProvider, canonical_http_url, default_search_provider
from .sessions import SessionStore
from .storage import Store, new_id, utc_now


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
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.settings.ensure_directories()
        self.store = store or Store(self.settings.database_path)
        self.search_provider = search_provider or default_search_provider(self.settings)
        self.download_provider = download_provider or PublicHttpDownloader(self.settings)
        self.job_runner = job_runner or JobRunner(self.settings.max_workers)
        self.session_store = SessionStore(self.settings.data_dir)
        self._mutation_lock = threading.RLock()
        self.store.mark_incomplete_jobs_failed()

    def flow_start(
        self,
        idempotency_key: str,
        intent: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_idempotency_key(idempotency_key)
        query = str(intent.get("topic") or "").strip()
        if not query:
            raise DomainError("INVALID_ARGUMENT", "intent.topic 不能为空")
        request_hash = self._request_hash(intent)
        scope = "resource_flow_start"
        with self._mutation_lock:
            replay = self._idempotency_replay(scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            flow = self.store.create_flow(query, intent)
            result = {
                "flow_id": flow["flow_id"],
                "stage": "intent_ready",
                "created_at": flow["created_at"],
            }
            self.store.put_idempotency(
                scope, idempotency_key, request_hash, flow["flow_id"], result
            )
            return result

    def search(
        self,
        flow_id: str,
        idempotency_key: str,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        if not 1 <= limit <= self.settings.max_search_results:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"limit 必须在 1 到 {self.settings.max_search_results} 之间",
            )
        effective_query = query.strip()
        if not effective_query:
            raise DomainError("INVALID_ARGUMENT", "搜索 query 不能为空")
        if cursor is not None:
            raise DomainError("INVALID_ARGUMENT", "首版搜索尚不支持 cursor")
        search_filters = filters or {}
        request = {
            "flow_id": flow_id,
            "query": effective_query,
            "filters": search_filters,
            "cursor": cursor,
            "limit": limit,
        }
        request_hash = self._request_hash(request)
        scope = f"resource_search:{flow_id}"
        with self._mutation_lock:
            replay = self._idempotency_replay(scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            raw_resources, errors = self.search_provider.search(
                effective_query, limit, search_filters.get("platforms")
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
            version = self.store.replace_presented_resources(flow_id, resources)
            public_resources = [self._public_resource(item) for item in resources]
            failures = [
                {
                    "platform": str(item.get("platform") or "generic"),
                    "code": self._normalise_failure_code(item.get("code")),
                    "message": str(item.get("message") or "搜索来源失败")[:1024],
                    "retriable": bool(item.get("retryable")),
                }
                for item in errors[:32]
            ]
            result = {
                "flow_id": flow_id,
                "stage": "selecting",
                "presented_version": version,
                "resources": public_resources,
                "failures": failures,
                "has_more": False,
            }
            self.store.audit(
                flow_id,
                "resource.search",
                None,
                {"query": effective_query, "count": len(public_resources), "version": version},
            )
            self.store.put_idempotency(
                scope, idempotency_key, request_hash, str(version), result
            )
            return result

    def selection_save(
        self,
        flow_id: str,
        idempotency_key: str,
        presented_version: int,
        resource_ids: list[str],
    ) -> dict[str, Any]:
        flow = self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        if presented_version != flow["presented_version"]:
            raise DomainError(
                "SELECTION_VERSION_CONFLICT",
                "候选集合版本已过期，请重新展示候选后再选择",
                details={"current_version": flow["presented_version"]},
            )
        if len(resource_ids) != len(set(resource_ids)):
            raise DomainError("INVALID_ARGUMENT", "resource_ids 不得重复")
        presented = self.store.list_presented_resources(flow_id, presented_version)
        allowed = {item["resource_id"] for item in presented}
        invalid = [item for item in resource_ids if item not in allowed]
        if invalid:
            raise DomainError(
                "RESOURCE_NOT_PRESENTED",
                "只能选择本轮已展示的资源",
                details={"resource_ids": invalid},
            )
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "presented_version": presented_version,
                "selected_resource_ids": resource_ids,
            }
        )
        scope = f"resource_selection_save:{flow_id}"
        with self._mutation_lock:
            replay = self._idempotency_replay(scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            self.store.save_selection(flow_id, presented_version, resource_ids)
            result = {
                "flow_id": flow_id,
                "stage": "selecting" if resource_ids else "cancelled",
                "selection_version": presented_version,
                "selected_resource_ids": resource_ids,
                "cancelled": not resource_ids,
            }
            self.store.put_idempotency(
                scope, idempotency_key, request_hash, str(presented_version), result
            )
            return result

    def download_prepare(
        self,
        flow_id: str,
        idempotency_key: str,
        selection_version: int,
        *,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        self._validate_idempotency_key(idempotency_key)
        selection = self.store.get_selection(flow_id)
        if selection is None or selection["status"] != "selected":
            raise DomainError("RESOURCE_NOT_SELECTED", "下载前必须存在非空的明确选择")
        if int(selection["presented_version"]) != selection_version:
            raise DomainError("SELECTION_VERSION_CONFLICT", "选择版本已经变化")
        download_options = options or {}
        container = str(download_options.get("preferred_container") or "html")
        strategy = "webpage" if container in {"html", "text"} else "direct"
        effective_max = int(
            download_options.get("max_bytes_per_resource")
            or self.settings.max_download_bytes
        )
        if not 1 <= effective_max <= self.settings.max_download_bytes:
            raise DomainError(
                "INVALID_ARGUMENT",
                "max_bytes 超出服务端允许范围",
                details={"server_max_bytes": self.settings.max_download_bytes},
            )
        resources = self.store.get_resources(flow_id, selection["resource_ids"])
        if len(resources) != len(selection["resource_ids"]):
            raise DomainError("RESOURCE_NOT_FOUND", "选择中的资源已不存在")
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "selection_version": selection_version,
                "options": download_options,
            }
        )
        scope = f"resource_download_prepare:{flow_id}"
        with self._mutation_lock:
            replay = self._idempotency_replay(scope, idempotency_key, request_hash)
            if replay is not None:
                return replay
            confirmation_token = secrets.token_urlsafe(32)
            confirmation_hash = self._token_hash(confirmation_token)
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=self.settings.plan_ttl_seconds)
            ).isoformat()
            plan = self.store.create_plan(
                flow_id,
                int(selection["presented_version"]),
                list(selection["resource_ids"]),
                {
                    "strategy": strategy,
                    "max_bytes": effective_max,
                    "preferred_container": container,
                    "allow_safe_fallback": bool(
                        download_options.get("allow_safe_fallback", True)
                    ),
                },
                confirmation_token,
                confirmation_hash,
                expires_at,
            )
            result = {
                "flow_id": flow_id,
                "stage": "prepared",
                "plan_id": plan["plan_id"],
                "selection_version": selection_version,
                "expires_at": expires_at,
                "confirmation_required": True,
                "confirmation_token": confirmation_token,
                "items": [
                    {
                        "resource_id": item["resource_id"],
                        "platform": item["platform"],
                        "planned_container": container,
                        "estimated_size_bytes": None,
                        "effective_max_bytes": effective_max,
                        "risks": [
                            {
                                "code": "PUBLIC_NETWORK_ACCESS",
                                "level": "low",
                                "message": "将访问公开来源并写入隔离任务目录",
                            }
                        ],
                    }
                    for item in resources
                ],
            }
            self.store.put_idempotency(
                scope, idempotency_key, request_hash, plan["plan_id"], result
            )
            return result

    def download_start(
        self,
        flow_id: str,
        plan_id: str,
        confirmation_token: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_flow(flow_id)
        if not confirmation_token or not idempotency_key.strip():
            raise DomainError(
                "INVALID_ARGUMENT", "confirmation_token 和 idempotency_key 不能为空"
            )
        plan = self.store.get_plan(plan_id)
        if plan is None or plan["flow_id"] != flow_id:
            raise DomainError("PLAN_NOT_FOUND", "下载计划不存在")
        request_hash = self._request_hash(
            {"flow_id": flow_id, "plan_id": plan_id, "confirmation_token": confirmation_token}
        )
        try:
            job, reused = self.store.reserve_job(
                plan_id,
                self._token_hash(confirmation_token),
                idempotency_key.strip(),
                request_hash,
                utc_now(),
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
                "selection_changed": ("SELECTION_CHANGED", "用户选择已变化，请重新准备下载"),
            }
            code, message = mapping.get(str(exc), ("STATE_CONFLICT", "下载状态冲突"))
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
            "job_id": job["job_id"],
            "status": "queued",
            "queued_at": job["created_at"],
        }

    def job_status(self, flow_id: str, job_id: str) -> dict[str, Any]:
        self._require_flow(flow_id)
        job = self.store.get_job(job_id)
        if job is None or job["flow_id"] != flow_id:
            raise DomainError("JOB_NOT_FOUND", "任务不存在")
        assets = []
        for asset_id in job["asset_ids"]:
            asset = self.store.get_asset(asset_id)
            if asset is not None:
                assets.append(self._public_asset(asset))
        return {
            "job_id": job_id,
            "flow_id": job["flow_id"],
            "status": job["status"],
            "progress": {
                "completed_items": len(assets),
                "total_items": len(self.store.get_plan(job["plan_id"])["resource_ids"]),
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
        request_hash = self._request_hash(
            {
                "flow_id": flow_id,
                "job_id": job_id,
                "asset_id": asset_id,
                "metadata": metadata or {},
            }
        )
        scope = f"resource_archive:{flow_id}"
        replay = self._idempotency_replay(scope, idempotency_key, request_hash)
        if replay is not None:
            return replay
        existing = self.store.get_archive_for_asset(asset_id)
        if existing is not None:
            result = {
                "flow_id": flow_id,
                "job_id": job_id,
                "asset_id": asset_id,
                "resource_id": asset["resource_id"],
                "archived_at": existing["created_at"],
                "deduplicated": True,
            }
            self.store.put_idempotency(
                scope, idempotency_key, request_hash, existing["archive_id"], result
            )
            return result

        source = Path(asset["local_path"]).resolve()
        try:
            ensure_within_root(source, self.settings.jobs_dir)
        except PolicyError as exc:
            raise DomainError("POLICY_DENIED", str(exc)) from exc
        if not source.is_file():
            raise DomainError("ASSET_NOT_FOUND", "资产文件不存在")
        suffix = source.suffix.lower()[:16]
        filename = f"{asset['sha256']}{suffix}"
        destination = (self.settings.library_dir / filename).resolve()
        try:
            ensure_within_root(destination, self.settings.library_dir)
        except PolicyError as exc:
            raise DomainError("POLICY_DENIED", str(exc)) from exc
        if not destination.exists():
            temporary = self.settings.library_dir / f".{filename}.{new_id('tmp')}"
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        archive_metadata = dict(metadata or {})
        archive_metadata["tags"] = sorted(set(archive_metadata.get("tags") or []))
        archive = self.store.create_archive(asset_id, destination, archive_metadata)
        self.store.audit(flow_id, "asset.archive", archive["archive_id"], {"asset_id": asset_id})
        result = {
            "flow_id": flow_id,
            "job_id": job_id,
            "asset_id": asset_id,
            "resource_id": asset["resource_id"],
            "archived_at": archive["created_at"],
            "deduplicated": False,
        }
        self.store.put_idempotency(
            scope, idempotency_key, request_hash, archive["archive_id"], result
        )
        return result

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
        if cursor is not None:
            raise DomainError("INVALID_ARGUMENT", "首版资料库检索尚不支持 cursor")
        library_filters = filters or {}
        entries = self.store.search_library(library_filters.get("query"), limit)
        assets = [
            {
                "asset_id": item["asset_id"],
                "resource_id": item["resource_id"],
                "platform": item["platform"],
                "title": item["title"],
                "resource_type": item["resource_type"],
                "media_type": item["media_type"],
                "size_bytes": item["byte_size"],
                "sha256": item["sha256"],
                **(
                    {"collection": item["metadata"].get("collection")}
                    if item["metadata"].get("collection")
                    else {}
                ),
                "tags": item["metadata"].get("tags") or [],
                "archived_at": item["created_at"],
            }
            for item in entries
        ]
        return {"flow_id": flow_id, "assets": assets, "has_more": False}

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
                result = self.download_provider.download(
                    resource,
                    job_id,
                    str(plan["options"]["strategy"]),
                    int(plan["options"]["max_bytes"]),
                    cancel_event,
                )
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
            "availability": "available",
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
