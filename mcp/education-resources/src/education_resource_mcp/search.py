"""Platform-native search dispatch for the education-resources MCP."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .adapters.base import PlatformSearchAdapter
from .config import Settings
from .errors import DomainError


class SearchProvider(Protocol):
    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Execute platform-native search tasks."""
        ...


def canonical_http_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise DomainError("INVALID_ARGUMENT", "搜索结果包含无效的 HTTP(S) 地址")
    if parsed.username or parsed.password:
        raise DomainError("INVALID_ARGUMENT", "资源地址不得包含凭据")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme.lower(), host + port, parsed.path or "/", parsed.query, ""))


class MultiPlatformSearchProvider:
    """Dispatch search only to built-in platform adapters.

    Open-web discovery belongs to the host ``web_search`` capability. Ordinary
    web URLs enter this MCP later through ``resource_import_url`` and the
    Generic Web inspect/materialization path.
    """

    _DEFAULT_ADAPTERS = (
        ("bilibili", "BilibiliSearchAdapter"),
        ("douyin", "DouyinSearchAdapter"),
        ("zhihu", "ZhihuSearchAdapter"),
        ("smartedu", "SmartEduSearchAdapter"),
        ("ximalaya", "XimalayaSearchAdapter"),
        ("cctv", "CctvSearchAdapter"),
        ("yixi", "YixiSearchAdapter"),
        ("kepu", "KepuSearchAdapter"),
        ("baiduwenku", "BaiduwenkuSearchAdapter"),
        ("runoob", "RunoobSearchAdapter"),
        ("open163", "Open163SearchAdapter"),
        ("libgen", "LibgenSearchAdapter"),
        ("zlibrary", "ZlibrarySearchAdapter"),
        ("weibo", "WeiboSearchAdapter"),
        ("wechat", "WechatSearchAdapter"),
        ("shuge", "ShugeSearchAdapter"),
        ("zjer", "ZjerSearchAdapter"),
    )

    def __init__(self, settings: Settings, session_store: Any) -> None:
        self.settings = settings
        self.session_store = session_store
        self._adapters: dict[str, PlatformSearchAdapter] = {}
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        for module_name, class_name in self._DEFAULT_ADAPTERS:
            try:
                module = importlib.import_module(
                    f".adapters.{module_name}", package=__package__
                )
                adapter_class = getattr(module, class_name)
            except ImportError:
                # Existing runtime behavior is preserved here; release/runtime
                # verification owns deployment failures. Search itself must not
                # substitute an unrelated source for a missing platform adapter.
                continue
            self.register_adapter(adapter_class(self.session_store, self.settings))

    def register_adapter(self, adapter: PlatformSearchAdapter) -> None:
        platform_id = str(getattr(adapter, "platform_id", "") or "").strip()
        if not platform_id or not callable(getattr(adapter, "search", None)):
            raise ValueError("adapter must declare platform_id and search()")
        self._adapters[platform_id] = adapter

    def _run_platform_adapter(
        self,
        platform: str,
        adapter: PlatformSearchAdapter,
        queries: list[str],
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        query_runs: list[dict[str, Any]] = []
        all_resources: list[dict[str, Any]] = []
        error_count = 0

        for query in queries:
            try:
                resources, error = adapter.search(query, limit)
            except Exception as exc:  # pragma: no cover - adapter boundary
                query_runs.append(
                    {
                        "query": query,
                        "candidate_count": 0,
                        "failure_count": 1,
                        "error": {
                            "code": "PARTIAL_FAILURE",
                            "message": f"{type(exc).__name__}: {exc}",
                            "retryable": True,
                        },
                    }
                )
                error_count += 1
                continue

            if error:
                error_count += 1
                query_runs.append(
                    {
                        "query": query,
                        "candidate_count": len(resources),
                        "failure_count": 1,
                        "error": {
                            "code": str(error.get("code") or "PARTIAL_FAILURE"),
                            "message": str(error.get("message") or "搜索失败"),
                            "retryable": bool(error.get("retryable")),
                        },
                    }
                )
            else:
                query_runs.append(
                    {
                        "query": query,
                        "candidate_count": len(resources),
                        "failure_count": 0,
                    }
                )
            all_resources.extend(resources)

        total_candidates = sum(run["candidate_count"] for run in query_runs)
        status = (
            "succeeded"
            if error_count == 0
            else "partial" if total_candidates > 0 else "failed"
        )
        return all_resources, {
            "platform": platform,
            "status": status,
            "query_runs": query_runs,
        }

    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        merged: dict[str, list[str]] = {}
        for task in search_tasks:
            platform = str(task.get("platform") or "").strip()
            queries = [
                str(item.get("query") or "").strip()
                for item in (task.get("queries") or [])
                if isinstance(item, dict) and str(item.get("query") or "").strip()
            ]
            if platform and queries:
                merged.setdefault(platform, []).extend(queries)

        if not merged:
            return [], []

        available = sorted(self._adapters)
        results_by_platform: dict[
            str, tuple[list[dict[str, Any]], dict[str, Any]]
        ] = {}
        work = [
            (platform, queries)
            for platform, queries in merged.items()
            if platform in self._adapters
        ]

        if work:
            worker_count = max(1, min(len(work), self.settings.max_workers))
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = {
                    pool.submit(
                        self._run_platform_adapter,
                        platform,
                        self._adapters[platform],
                        queries,
                        limit,
                    ): (platform, queries)
                    for platform, queries in work
                }
                for future, (platform, queries) in futures.items():
                    try:
                        results_by_platform[platform] = future.result()
                    except Exception as exc:  # pragma: no cover - provider boundary
                        results_by_platform[platform] = (
                            [],
                            {
                                "platform": platform,
                                "status": "failed",
                                "query_runs": [
                                    {
                                        "query": "; ".join(queries),
                                        "candidate_count": 0,
                                        "failure_count": 1,
                                        "error": {
                                            "code": "PARTIAL_FAILURE",
                                            "message": f"{type(exc).__name__}: {exc}",
                                            "retryable": True,
                                        },
                                    }
                                ],
                            },
                        )

        all_resources: list[dict[str, Any]] = []
        platform_runs: list[dict[str, Any]] = []
        for platform, queries in merged.items():
            result = results_by_platform.get(platform)
            if result is None:
                platform_runs.append(
                    {
                        "platform": platform,
                        "status": "skipped",
                        "query_runs": [
                            {
                                "query": query,
                                "candidate_count": 0,
                                "failure_count": 1,
                                "error": {
                                    "code": "PLATFORM_UNAVAILABLE",
                                    "message": (
                                        f"平台 {platform} 尚未接入 resource_search；"
                                        f"可用平台：{', '.join(available)}。"
                                        "开放互联网请使用宿主 web_search；"
                                        "已知网页 URL 请使用 resource_import_url。"
                                    ),
                                    "retryable": False,
                                },
                            }
                            for query in queries
                        ],
                    }
                )
                continue
            resources, run = result
            platform_runs.append(run)
            all_resources.extend(resources)

        return all_resources, platform_runs


def default_search_provider(
    settings: Settings, session_store: Any = None
) -> SearchProvider:
    """Build the platform-native search provider."""

    if session_store is None:
        raise ValueError("session_store is required for platform-native search")
    return MultiPlatformSearchProvider(settings, session_store)


class StaticSearchProvider:
    """Deterministic provider for tests and offline smoke runs."""

    def __init__(self, resources: list[dict[str, Any]]) -> None:
        self.resources = resources

    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        all_resources: list[dict[str, Any]] = []
        platform_runs: list[dict[str, Any]] = []

        for task in search_tasks:
            platform = str(task.get("platform") or "")
            query_runs: list[dict[str, Any]] = []
            task_resources: list[dict[str, Any]] = []
            for item in task.get("queries") or []:
                query = str(item.get("query") or "")
                query_text = query.lower()
                selected = [
                    dict(resource)
                    for resource in self.resources
                    if not query_text
                    or query_text in str(resource.get("title", "")).lower()
                    or query_text in str(resource.get("summary", "")).lower()
                ][:limit]
                query_runs.append(
                    {
                        "query": query,
                        "candidate_count": len(selected),
                        "failure_count": 0,
                    }
                )
                task_resources.extend(selected)
            platform_runs.append(
                {
                    "platform": platform,
                    "status": "succeeded",
                    "query_runs": query_runs,
                }
            )
            all_resources.extend(task_resources)

        return all_resources, platform_runs
