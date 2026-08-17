"""Thin capability service for resource search, inspect, download and archive.

There is no Flow, ResultSet, Presentation, Selection or persisted Plan here.
Search results live in a process-local handle map; downloads are asynchronous
jobs because progress and cancellation are real user-facing needs.
"""

from __future__ import annotations

import importlib
import json
import logging
import secrets
import threading
from typing import Any

from .acquisition import AcquisitionRequest, AcquisitionRouter, ProviderRegistration
from .acquisition.models import AcquisitionStrategy
from .acquisition.planner import AcquisitionPlanner
from .acquisition.web_materializer import WebMaterializer
from .archive import archive_downloaded_files
from .config import Settings
from .downloader import DownloadProvider, PublicHttpDownloader
from .errors import DomainError
from .inspection import InspectionRouter
from .inspection_registry import default_inspection_router
from .batch import BATCH_MODES
from .job_state import (
    CANCEL_FLAG_NAME,
    SPAWN_GRACE_SECONDS,
    TERMINAL_STATUSES,
    job_dir,
    process_alive,
    read_job,
    state_age_seconds,
    terminate_process,
    utc_now_iso,
    write_job,
    write_request,
)
from .jobs import JobSpawner, spawn_worker
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


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


_SEARCH_TASK_EXAMPLE = (
    'search_tasks 结构示例：[{"platform": "bilibili", "queries": ["火山喷发 原理 动画"]}]'
    '；queries 项也可以是 {"query": "..."}。顶层不支持 query 字段。'
)


def _normalize_search_tasks(
    search_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate search_tasks loudly.

    A malformed task used to be dropped silently, which surfaced as a
    successful-but-empty search and sent the agent digging through source
    code to guess the shape.  Reject anything malformed with the expected
    structure spelled out instead.
    """

    normalized: list[dict[str, Any]] = []
    for task in search_tasks:
        if not isinstance(task, dict):
            raise DomainError(
                "INVALID_ARGUMENT",
                f"search_tasks 的每一项必须是对象；{_SEARCH_TASK_EXAMPLE}",
            )
        unknown = sorted(set(task) - {"platform", "queries", "tabs"})
        if unknown:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"search_tasks 项含未知字段 {unknown}；{_SEARCH_TASK_EXAMPLE}",
            )
        tabs = task.get("tabs")
        if tabs is not None:
            if (
                not isinstance(tabs, list)
                or not tabs
                or not all(isinstance(t, str) and t.strip() for t in tabs)
            ):
                raise DomainError(
                    "INVALID_ARGUMENT",
                    "tabs 必须是平台分类代码字符串的非空列表（当前仅 smartedu 支持）",
                )
            tabs = [t.strip() for t in tabs]
        platform = str(task.get("platform") or "").strip()
        if not platform:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"search_tasks 项缺少 platform；{_SEARCH_TASK_EXAMPLE}",
            )
        # adapter registry ids use hyphens (annas-archive); callers keep
        # guessing underscores (feedback #1) — normalize instead of failing.
        platform = platform.replace("_", "-")
        raw_queries = task.get("queries")
        if not isinstance(raw_queries, list) or not raw_queries:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"queries 必须是非空列表；{_SEARCH_TASK_EXAMPLE}",
            )
        queries: list[str] = []
        for item in raw_queries:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict) and set(item) <= {"query"}:
                text = str(item.get("query") or "").strip()
            else:
                raise DomainError(
                    "INVALID_ARGUMENT",
                    f'queries 的每一项必须是搜索短语字符串或 {{"query": "..."}}；{_SEARCH_TASK_EXAMPLE}',
                )
            if text:
                queries.append(text)
        if not queries:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"queries 中没有有效搜索短语；{_SEARCH_TASK_EXAMPLE}",
            )
        task_out: dict[str, Any] = {
            "platform": platform,
            "queries": [{"query": text} for text in queries],
        }
        if tabs is not None:
            task_out["tabs"] = tabs
        normalized.append(task_out)
    return normalized


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
    """Expose actual resource capabilities with minimal process-local state.

    Search handles stay process-local; download jobs live in detached worker
    processes whose state is the ``jobs/<job_id>/job.json`` file, so jobs
    survive an MCP/gateway restart (0056).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        search_provider: SearchProvider | None = None,
        inspection_router: InspectionRouter | None = None,
        acquisition_router: AcquisitionRouter | None = None,
        download_provider: DownloadProvider | None = None,
        job_runner: JobSpawner | None = None,
        recover_jobs: bool = True,
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
        self.job_runner = job_runner or JobSpawner(max_workers=self.settings.max_workers)
        self._resources: dict[str, dict[str, Any]] = {}
        self._resource_cache = self.settings.data_dir / "resources.jsonl"
        self._lock = threading.RLock()
        if recover_jobs:
            self._recover_interrupted_jobs()
            self._load_resource_cache()

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
        normalized = _normalize_search_tasks(search_tasks)
        raw_resources, platform_runs = self.search_provider.search(normalized, limit)
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
            self._append_resource_cache(resource)
            candidates.append(self._public_resource(resource, include_summary=include_summary))
        return candidates

    _RESOURCE_CACHE_LIMIT = 1000

    def _load_resource_cache(self) -> None:
        """Reload recent search handles so an MCP restart doesn't strand
        in-flight conversations (feedback #7); a bounded cache, not state."""

        try:
            lines = self._resource_cache.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines[-self._RESOURCE_CACHE_LIMIT :]:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("resource_id"):
                self._resources.setdefault(str(data["resource_id"]), data)

    def _append_resource_cache(self, resource: dict[str, Any]) -> None:
        try:
            if self._resource_cache.exists():
                lines = self._resource_cache.read_text(encoding="utf-8").splitlines()
                if len(lines) >= self._RESOURCE_CACHE_LIMIT * 2:
                    with self._lock:
                        recent = list(self._resources.values())[
                            -self._RESOURCE_CACHE_LIMIT :
                        ]
                    self._resource_cache.write_text(
                        "\n".join(
                            json.dumps(item, ensure_ascii=False) for item in recent
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            with self._resource_cache.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(resource, ensure_ascii=False) + "\n")
        except OSError:
            LOGGER.warning("could not persist resource cache", exc_info=True)

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
        creator_id = (
            metadata.get("creator_sec_uid")
            or metadata.get("creator_id")
            or metadata.get("creator_mid")
        )
        if creator_id not in (None, ""):
            result["creator_id"] = str(creator_id)
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
        creator_id = (
            metadata.get("creator_sec_uid")
            or metadata.get("creator_id")
            or metadata.get("creator_mid")
        )
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
        directory = job_dir(self.settings.jobs_dir, job_id)
        directory.mkdir(parents=True, exist_ok=True)
        write_request(
            directory,
            {
                "job_id": job_id,
                "resources": resources,
                "preferred_container": preferred_container,
            },
        )
        write_job(
            directory,
            {
                "job_id": job_id,
                "status": "queued",
                "total": len(resources),
                "completed": 0,
                "files": [],
                "failures": [],
                "pid": None,
                "created_at": utc_now_iso(),
            },
        )

        def _spawn() -> "subprocess.Popen | None":
            if (directory / CANCEL_FLAG_NAME).exists():
                write_job(directory, {**read_job(directory), "status": "cancelled"})
                return None
            return spawn_worker(directory)

        self.job_runner.submit(job_id, _spawn)
        return {"job_id": job_id, "status": "queued"}

    def job_status(self, job_id: str) -> dict[str, Any]:
        directory, job = self._load_job(job_id)
        job = self._reconcile(directory, job)
        return {
            "job_id": job_id,
            "status": job.get("status"),
            "progress": {
                "completed": _safe_int(job.get("completed")),
                "total": _safe_int(job.get("total")),
            },
            "files": [dict(item) for item in job.get("files") or []],
            "failures": [dict(item) for item in job.get("failures") or []],
        }

    def job_cancel(self, job_id: str) -> dict[str, Any]:
        directory, job = self._load_job(job_id)
        status = str(job.get("status") or "")
        if status in TERMINAL_STATUSES:
            return {"job_id": job_id, "status": status}
        flag = directory / CANCEL_FLAG_NAME
        repeat_cancel = flag.exists()
        flag.touch()
        pid = job.get("pid")
        if pid and process_alive(pid):
            if repeat_cancel:
                # The worker ignored the flag (or is stuck): force kill.
                terminate_process(int(pid))
                write_job(directory, {**read_job(directory), "status": "cancelled"})
                return {"job_id": job_id, "status": "cancelled"}
            return {"job_id": job_id, "status": "cancelling"}
        # No live worker owns job.json any more; the parent may rewrite it.
        write_job(directory, {**job, "status": "cancelled"})
        return {"job_id": job_id, "status": "cancelled"}

    def archive(
        self,
        job_id: str,
        *,
        domain_id: str = "",
        topic: str = "",
    ) -> dict[str, Any]:
        """Move successful files from a finished download Job into the library."""

        directory, job = self._load_job(job_id)
        job = self._reconcile(directory, job)
        if str(job.get("status")) not in {"succeeded", "partial"}:
            raise DomainError("JOB_NOT_FINISHED", "下载任务尚未产生可归档的最终文件")
        downloaded_files = [dict(item) for item in job.get("files") or []]
        if not downloaded_files:
            raise DomainError("FILE_NOT_FOUND", "下载任务没有可归档文件")

        archived, failures = archive_downloaded_files(
            downloaded_files,
            library_root=self.settings.library_root,
            domain_id=domain_id,
            topic=topic,
        )

        archived_by_asset = {
            item.get("asset_id"): item
            for item in archived
            if item.get("asset_id")
        }
        if archived_by_asset:
            # Terminal status implies the worker is gone; parent owns job.json.
            current = read_job(directory)
            current["files"] = [
                dict(archived_by_asset.get(item.get("asset_id"), item))
                for item in current.get("files") or []
            ]
            write_job(directory, current)

        return {
            "job_id": job_id,
            "status": "succeeded" if archived and not failures else "partial",
            "library_root": str(self.settings.library_root),
            "files": archived,
            "failures": failures,
        }

    # ------------------------------------------------------------------
    # Batch collection (0057 M1)
    # ------------------------------------------------------------------

    def batch_collect(
        self,
        platform: str,
        *,
        mode: str = "creator_full",
        creator_id: str = "",
        keyword: str = "",
        start_day: str = "",
        end_day: str = "",
        max_items: int = 500,
    ) -> dict[str, Any]:
        platform = str(platform or "").strip()
        creator_id = str(creator_id or "").strip()
        mode = str(mode or "").strip()
        keyword = str(keyword or "").strip()
        start_day = str(start_day or "").strip()
        end_day = str(end_day or "").strip()
        if mode not in BATCH_MODES:
            raise DomainError(
                "INVALID_ARGUMENT",
                f"未知批量模式 {mode!r}；当前支持 {sorted(BATCH_MODES)}",
            )
        if not platform:
            raise DomainError(
                "INVALID_ARGUMENT", "platform 不能为空，例如 douyin / bilibili / smartedu"
            )
        if mode == "creator_full" and not creator_id:
            raise DomainError(
                "INVALID_ARGUMENT",
                "creator_full 模式需要 creator_id（sec_uid / mid / 主页 URL）",
            )
        if mode == "time_range_search":
            if not keyword:
                raise DomainError("INVALID_ARGUMENT", "time_range_search 需要 keyword")
            if not start_day or not end_day:
                raise DomainError(
                    "INVALID_ARGUMENT",
                    "time_range_search 需要 start_day/end_day（YYYY-MM-DD）",
                )
            try:
                from datetime import date

                start_dt = date.fromisoformat(start_day)
                end_dt = date.fromisoformat(end_day)
            except ValueError as exc:
                raise DomainError(
                    "INVALID_ARGUMENT", f"日期格式应为 YYYY-MM-DD: {exc}"
                ) from None
            if start_dt > end_dt:
                raise DomainError("INVALID_ARGUMENT", "start_day 不能晚于 end_day")
            if (end_dt - start_dt).days > 90:
                raise DomainError("INVALID_ARGUMENT", "单次时间范围最多 90 天")
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or not 1 <= max_items <= 1000
        ):
            raise DomainError("INVALID_ARGUMENT", "max_items 必须在 1..1000 之间")
        job_id = new_id("job")
        directory = job_dir(self.settings.jobs_dir, job_id)
        directory.mkdir(parents=True, exist_ok=True)
        write_request(
            directory,
            {
                "kind": "batch_collect",
                "job_id": job_id,
                "mode": mode,
                "platform": platform,
                "creator_id": creator_id,
                "keyword": keyword,
                "start_day": start_day,
                "end_day": end_day,
                "max_items": max_items,
            },
        )
        write_job(
            directory,
            {
                "job_id": job_id,
                "kind": "batch_collect",
                "mode": mode,
                "platform": platform,
                "status": "queued",
                "total": 0,
                "completed": 0,
                "files": [],
                "failures": [],
                "pid": None,
                "created_at": utc_now_iso(),
            },
        )

        def _spawn() -> "subprocess.Popen | None":
            if (directory / CANCEL_FLAG_NAME).exists():
                write_job(directory, {**read_job(directory), "status": "cancelled"})
                return None
            return spawn_worker(directory)

        self.job_runner.submit(job_id, _spawn)
        return {"job_id": job_id, "status": "queued"}

    def batch_read(
        self, job_id: str, *, offset: int = 0, limit: int = 20
    ) -> dict[str, Any]:
        directory, job = self._load_job(job_id)
        job = self._reconcile(directory, job)
        if str(job.get("kind") or "") != "batch_collect":
            raise DomainError(
                "INVALID_ARGUMENT",
                "该任务不是批量采集任务；下载任务请用 resource_job_status",
            )
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise DomainError("INVALID_ARGUMENT", "offset 必须 >= 0")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise DomainError("INVALID_ARGUMENT", "limit 必须 >= 1")
        limit = min(limit, 50)
        path = directory / "results.jsonl"
        items: list[dict[str, Any]] = []
        total = _safe_int(job.get("total"))
        if path.is_file():
            lines = path.read_text(encoding="utf-8").splitlines()
            total = len(lines)
            for line in lines[offset : offset + limit]:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {
            "job_id": job_id,
            "kind": "batch_collect",
            "status": job.get("status"),
            "total": total,
            "offset": offset,
            "items": items,
            "complete": offset + len(items) >= total,
        }

    # ------------------------------------------------------------------
    # File-backed job state (0056)
    # ------------------------------------------------------------------

    def _load_job(self, job_id: str) -> tuple[Any, dict[str, Any]]:
        directory = job_dir(self.settings.jobs_dir, job_id)
        return directory, read_job(directory)

    def _reconcile(self, directory: Any, job: dict[str, Any]) -> dict[str, Any]:
        """Mark orphaned jobs interrupted; never touch a live worker's file."""

        job_id = str(job.get("job_id"))
        status = str(job.get("status") or "")
        if status in TERMINAL_STATUSES:
            return job
        pid = job.get("pid")
        if pid and process_alive(pid):
            return job
        if self.job_runner.is_pending(job_id):
            return job  # still queued or spawning inside this process
        if not pid and state_age_seconds(job) < SPAWN_GRACE_SECONDS:
            return job  # a detached worker may be starting elsewhere
        job = dict(job)
        job["status"] = "interrupted"
        try:
            write_job(directory, job)
        except OSError:
            LOGGER.exception("could not mark job %s interrupted", job.get("job_id"))
        return job

    def _recover_interrupted_jobs(self) -> None:
        """On startup, declare non-terminal jobs whose worker died."""

        try:
            entries = sorted(self.settings.jobs_dir.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir() or not (entry / "job.json").is_file():
                continue
            try:
                job = read_job(entry)
                self._reconcile(entry, job)
            except DomainError as exc:
                LOGGER.warning("skipping unreadable job state %s: %s", entry, exc)

    def download_resource(
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
                # provenance for the archive manifest (feedback #5)
                "platform": resource.get("platform"),
                "source_url": resource.get("source_url"),
                "title": resource.get("title"),
                "author": (resource.get("metadata") or {}).get("author"),
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
