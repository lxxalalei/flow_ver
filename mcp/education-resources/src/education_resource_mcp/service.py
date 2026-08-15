"""Thin capability service for resource search, inspect and download.

There is no Flow, ResultSet, Presentation, Selection or persisted Plan here.
Search results live in a process-local handle map; downloads are asynchronous
jobs because progress and cancellation are real user-facing needs.
"""

from __future__ import annotations

import importlib
import logging
import secrets
import threading
from typing import Any

from .acquisition import AcquisitionRequest, AcquisitionRouter, ProviderRegistration
from .acquisition.models import AcquisitionStrategy
from .acquisition.planner import AcquisitionPlanner, AcquisitionPlanningError
from .acquisition.web_materializer import WebMaterializer
from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .inspection import InspectionRouter
from .inspection_registry import default_inspection_router
from .jobs import JobRunner
from .search import SearchProvider, canonical_http_url, default_search_provider
from .session_bridge import create_session_store


LOGGER = logging.getLogger(__name__)

_RESOURCE_TYPE_MAP = {
    "网页": "article",
    "文章": "article",
    "图书": "book",
    "文档": "document",
    "视频": "video",
    "音频": "audio",
    "课程": "course",
}
_ALLOWED_RESOURCE_TYPES = {
    "article", "book", "document", "video", "audio", "course", "dataset", "other"
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def _resource_type(value: Any) -> str:
    text = str(value or "other").strip()
    lowered = text.lower()
    return _RESOURCE_TYPE_MAP.get(text, lowered if lowered in _ALLOWED_RESOURCE_TYPES else "other")


def _provider_registrations(
    settings: Settings,
    session_store: Any,
    download_provider: DownloadProvider | None = None,
) -> list[ProviderRegistration]:
    registrations = [
        ProviderRegistration(
            provider_id="generic-direct",
            provider=download_provider or PublicHttpDownloader(settings),
            strategies=(AcquisitionStrategy.DIRECT_FILE,),
            scopes=("primary_resource",),
        ),
        ProviderRegistration(
            provider_id="generic-web-materializer",
            provider=WebMaterializer(settings=settings),
            strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
            scopes=("primary_resource", "landing_page"),
        ),
    ]
    for module_name, class_name, provider_id in (
        ("smartedu_download", "SmartEduDownloader", "smartedu-resource"),
        ("douyin_download", "DouyinDownloader", "douyin-video"),
        ("ximalaya_download", "XimalayaDownloader", "ximalaya-audio"),
        ("bilibili_download", "BilibiliDownloader", "bilibili-video"),
        ("annas_archive_download", "AnnasArchiveDownloader", "annas-archive"),
        ("zjer_download", "ZjerVideoDownloader", "zjer-video"),
    ):
        try:
            module = importlib.import_module(
                f"education_resource_mcp.adapters.{module_name}"
            )
        except ImportError:
            continue
        provider_class = getattr(module, class_name)
        registrations.append(
            ProviderRegistration(
                provider_id=provider_id,
                provider=provider_class(session_store, settings),
                strategies=(AcquisitionStrategy.DIRECT_FILE,),
                scopes=("primary_resource",),
            )
        )
    return registrations


class ResourceService:
    """Expose actual search/inspect/download capabilities with minimal state."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        search_provider: SearchProvider | None = None,
        inspection_router: InspectionRouter | None = None,
        acquisition_router: AcquisitionRouter | None = None,
        download_provider: DownloadProvider | None = None,
        job_runner: JobRunner | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.settings.ensure_directories()
        self.session_store = create_session_store(self.settings)
        self.search_provider = search_provider or default_search_provider(
            self.settings, self.session_store
        )
        self.inspection_router = inspection_router or default_inspection_router(
            self.settings, session_store=self.session_store
        )
        self.acquisition_router = acquisition_router or AcquisitionRouter(
            _provider_registrations(
                self.settings,
                self.session_store,
                download_provider=download_provider,
            )
        )
        self.planner = AcquisitionPlanner(self.acquisition_router)
        self.job_runner = job_runner or JobRunner(max_workers=self.settings.max_workers)
        self._resources: dict[str, dict[str, Any]] = {}
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def shutdown(self) -> None:
        self.job_runner.shutdown(wait=False)

    def search(
        self,
        search_tasks: list[dict[str, Any]],
        *,
        limit: int = 8,
    ) -> dict[str, Any]:
        if not isinstance(search_tasks, list) or not search_tasks:
            raise DomainError("INVALID_ARGUMENT", "search_tasks 不能为空")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise DomainError("INVALID_ARGUMENT", "limit 必须大于 0")
        raw_resources, platform_runs = self.search_provider.search(search_tasks, limit)
        return {
            "candidates": self._remember_resources(raw_resources),
            "failures": self._search_failures(platform_runs),
        }

    def browse_creator(
        self,
        platform: str,
        creator_id: str,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        platform = str(platform or "").strip()
        creator_id = str(creator_id or "").strip()
        if not platform or not creator_id:
            raise DomainError("INVALID_ARGUMENT", "platform 和 creator_id 不能为空")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise DomainError("INVALID_ARGUMENT", "limit 必须大于 0")
        search_creator = getattr(self.search_provider, "search_creator", None)
        if not callable(search_creator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "当前搜索器不支持创作者浏览")
        raw_resources, platform_runs = search_creator(platform, creator_id, limit)
        return {
            "candidates": self._remember_resources(raw_resources, include_summary=False),
            "failures": self._search_failures(platform_runs),
        }

    def _remember_resources(
        self,
        raw_resources: list[dict[str, Any]],
        *,
        include_summary: bool = True,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
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
            platform = str(raw.get("platform") or "generic").strip() or "generic"
            dedup_key = (platform, source_url)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            resource_id = new_id("res")
            resource = dict(raw)
            resource.pop("resource_id", None)
            resource.update(
                {
                    "resource_id": resource_id,
                    "platform": platform,
                    "title": title,
                    "source_url": source_url,
                    "resource_type": _resource_type(raw.get("resource_type") or raw.get("type")),
                }
            )
            metadata = raw.get("metadata")
            resource["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
            with self._lock:
                self._resources[resource_id] = resource
            candidates.append(self._public_resource(resource, include_summary=include_summary))
        return candidates

    @staticmethod
    def _public_resource(
        resource: dict[str, Any],
        *,
        include_summary: bool = True,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "resource_id": resource["resource_id"],
            "platform": resource["platform"],
            "title": resource["title"],
            "resource_type": resource["resource_type"],
            "url": resource["source_url"],
        }
        if include_summary and resource.get("summary"):
            result["summary"] = str(resource["summary"])
        metadata = resource.get("metadata") or {}
        for field in ("author", "language", "published_at", "duration_seconds"):
            if metadata.get(field) not in (None, ""):
                result[field] = metadata[field]
        return result

    @staticmethod
    def _search_failures(platform_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for run in platform_runs:
            if not isinstance(run, dict):
                continue
            platform = str(run.get("platform") or "generic")
            for query_run in run.get("query_runs") or []:
                if not isinstance(query_run, dict):
                    continue
                error = query_run.get("error")
                if isinstance(error, dict):
                    failures.append(
                        {
                            "platform": platform,
                            "query": query_run.get("query"),
                            "code": str(error.get("code") or "PARTIAL_FAILURE"),
                            "message": str(error.get("message") or "搜索失败"),
                            "retryable": bool(error.get("retryable")),
                        }
                    )
        return failures

    def inspect(self, resource_id: str) -> dict[str, Any]:
        resource = self._get_resource(resource_id)
        resolution = self._inspect_raw(resource)
        return self._public_inspection(resource_id, resolution)

    def _inspect_raw(self, resource: dict[str, Any]) -> dict[str, Any]:
        payload = self.inspection_router.inspect(dict(resource)).to_mapping()
        resolved = payload.get("resolved_resource")
        if not isinstance(resolved, dict):
            resolved = {}
        representations: list[dict[str, Any]] = []
        for raw in resolved.get("representations") or []:
            if not isinstance(raw, dict):
                continue
            representation = dict(raw)
            if not representation.get("representation_id"):
                representation["representation_id"] = new_id("repr")
            representations.append(representation)
        resolved["representations"] = representations
        payload["resolved_resource"] = resolved
        return payload

    @staticmethod
    def _public_inspection(resource_id: str, resolution: dict[str, Any]) -> dict[str, Any]:
        resolved = resolution.get("resolved_resource") or {}
        resource: dict[str, Any] = {
            "resource_type": _resource_type(resolved.get("resource_type")),
            "availability": resolved.get("availability") or {"status": "unknown"},
            "representations": [],
        }
        for field in ("title", "summary", "creator", "language"):
            if resolved.get(field) not in (None, ""):
                resource[field] = resolved[field]
        metadata = resolved.get("metadata") or {}
        creator_id = metadata.get("creator_sec_uid") or metadata.get("creator_id")
        if creator_id:
            resource["creator_id"] = str(creator_id)
        for raw in resolved.get("representations") or []:
            if not isinstance(raw, dict):
                continue
            resource["representations"].append(
                {
                    key: raw[key]
                    for key in (
                        "representation_id", "scope", "kind", "role", "container",
                        "mime_type", "language", "estimated_size_bytes",
                        "materializable", "requires_auth", "technical_availability",
                    )
                    if raw.get(key) is not None
                }
            )
        return {
            "resource_id": resource_id,
            "status": resolution.get("resolution_status") or "unresolved",
            "resource": resource,
            "failures": list(resolution.get("failures") or []),
        }

    def download(
        self,
        resource_ids: list[str],
        *,
        preferred_container: str = "original",
    ) -> dict[str, Any]:
        if not isinstance(resource_ids, list) or not resource_ids:
            raise DomainError("INVALID_ARGUMENT", "resource_ids 不能为空")
        if len(set(resource_ids)) != len(resource_ids):
            raise DomainError("INVALID_ARGUMENT", "resource_ids 不得重复")
        resources = [self._get_resource(resource_id) for resource_id in resource_ids]
        job_id = new_id("job")
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "total": len(resources),
                "completed": 0,
                "files": [],
                "failures": [],
            }
        self.job_runner.submit(
            job_id,
            lambda cancel_event: self._run_download_job(
                job_id, resources, preferred_container, cancel_event
            ),
        )
        return {"job_id": job_id, "status": "queued"}

    def job_status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise DomainError("JOB_NOT_FOUND", "任务不存在")
            return {
                "job_id": job_id,
                "status": job["status"],
                "progress": {"completed": job["completed"], "total": job["total"]},
                "files": [dict(item) for item in job["files"]],
                "failures": [dict(item) for item in job["failures"]],
            }

    def job_cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise DomainError("JOB_NOT_FOUND", "任务不存在")
            if job["status"] in {"succeeded", "partial", "failed", "cancelled"}:
                return {"job_id": job_id, "status": job["status"]}
            job["status"] = "cancelling"
        active = self.job_runner.cancel(job_id)
        if not active:
            with self._lock:
                self._jobs[job_id]["status"] = "cancelled"
        return {"job_id": job_id, "status": "cancelling" if active else "cancelled"}

    def _run_download_job(
        self,
        job_id: str,
        resources: list[dict[str, Any]],
        preferred_container: str,
        cancel_event: threading.Event,
    ) -> None:
        with self._lock:
            self._jobs[job_id]["status"] = "running"
        for resource in resources:
            if cancel_event.is_set():
                with self._lock:
                    self._jobs[job_id]["status"] = "cancelled"
                return
            try:
                files = self._download_one(
                    job_id, resource, preferred_container, cancel_event
                )
            except (DomainError, AcquisitionPlanningError) as exc:
                with self._lock:
                    self._jobs[job_id]["failures"].append(
                        {
                            "resource_id": resource["resource_id"],
                            "code": str(getattr(exc, "code", "DOWNLOAD_FAILED")),
                            "message": str(getattr(exc, "message", str(exc))),
                            "retryable": bool(getattr(exc, "retryable", False)),
                        }
                    )
            except Exception as exc:
                LOGGER.exception("download job %s failed for one resource", job_id)
                with self._lock:
                    self._jobs[job_id]["failures"].append(
                        {
                            "resource_id": resource["resource_id"],
                            "code": "DOWNLOAD_FAILED",
                            "message": f"{type(exc).__name__}: {exc}",
                            "retryable": False,
                        }
                    )
            else:
                with self._lock:
                    self._jobs[job_id]["files"].extend(files)
            finally:
                with self._lock:
                    self._jobs[job_id]["completed"] += 1
        with self._lock:
            job = self._jobs[job_id]
            if job["status"] == "cancelling":
                job["status"] = "cancelled"
            elif job["files"] and job["failures"]:
                job["status"] = "partial"
            elif job["files"]:
                job["status"] = "succeeded"
            else:
                job["status"] = "failed"

    def _download_one(
        self,
        job_id: str,
        resource: dict[str, Any],
        preferred_container: str,
        cancel_event: threading.Event,
    ) -> list[dict[str, Any]]:
        resolution = self._inspect_raw(resource)
        route = self.planner.route(
            resource,
            resolution,
            preferred_container=preferred_container,
        )
        provider_resource = dict(resource)
        if route["provider_id"] == "smartedu-resource":
            provider_resource["_planned_representation"] = {
                "representation_id": route["representation_id"],
                "container": route["container"],
            }
        request = AcquisitionRequest(
            job_id=job_id,
            resource=provider_resource,
            strategy=route["strategy"],
            provider_id=route["provider_id"],
            scope=route["scope"],
            representation_id=route["representation_id"],
            preferred_container=route["container"],
            cancel_event=cancel_event,
            jobs_root=self.settings.jobs_dir.resolve(),
        )
        acquisition = self.acquisition_router.acquire(request)
        if not acquisition.ok or acquisition.bundle is None:
            failure = acquisition.failure
            raise DomainError(
                failure.code if failure else "DOWNLOAD_FAILED",
                failure.message if failure else "资源下载失败",
                retryable=bool(failure.retryable) if failure else False,
            )
        files = [
            {
                "asset_id": artifact.artifact_id,
                "resource_id": resource["resource_id"],
                "filename": artifact.filename,
                "path": str(artifact.path),
                "media_type": artifact.media_type,
                "size_bytes": artifact.byte_size,
                "role": artifact.role,
                "primary": artifact.primary,
            }
            for artifact in acquisition.bundle.artifacts
            if artifact.path.is_file()
        ]
        if not files:
            raise DomainError("DOWNLOAD_FAILED", "下载器没有产生可用文件")
        return files

    def _get_resource(self, resource_id: str) -> dict[str, Any]:
        with self._lock:
            resource = self._resources.get(str(resource_id))
            if resource is None:
                raise DomainError(
                    "RESOURCE_NOT_FOUND",
                    "资源句柄不存在；MCP 进程重启后请重新搜索",
                )
            return dict(resource)
