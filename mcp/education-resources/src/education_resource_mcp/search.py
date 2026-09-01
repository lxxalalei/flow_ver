"""Search providers owned by the MCP service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .adapters import generic_web
from .adapters.base import PlatformSearchAdapter
from .config import Settings
from .errors import DomainError


class SearchProvider(Protocol):
    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Execute *search_tasks* and return ``(resources, platform_runs)``."""
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


class GenericWebSearchProvider:
    """Search the public web through the MCP-owned generic adapter."""

    _CJK_ENGINES = ("duckduckgo", "baidu", "bing")
    _DEFAULT_ENGINES = ("bing",)

    def __init__(self, settings: Settings, engines: list[str] | None = None) -> None:
        self.settings = settings
        self.engines = tuple(engines) if engines is not None else None

    def _engines_for_query(self, query: str) -> list[str]:
        """Choose a public-search route without rewriting the query."""

        if self.engines is not None:
            return list(self.engines)
        if any("\u3400" <= char <= "\u9fff" for char in query):
            return list(self._CJK_ENGINES)
        return list(self._DEFAULT_ENGINES)

    @staticmethod
    def _tuned_query(query: str) -> str:
        """Turn 书名号 into an exact phrase for long Chinese book titles."""

        def _quote(match: re.Match[str]) -> str:
            return f'"{match.group(1)}"'

        return re.sub(r"《([^《》]{2,40})》", _quote, query)

    def _search_single(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tuned = self._tuned_query(query)
        try:
            response = generic_web.search(
                tuned,
                self._engines_for_query(tuned),
                limit,
                float(self.settings.search_timeout_seconds),
            )
        except Exception as exc:
            raise DomainError(
                "PARTIAL_FAILURE",
                f"Generic 搜索失败：{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc

        errors: list[dict[str, Any]] = []
        for item in response.get("errors", []):
            if isinstance(item, dict):
                errors.append(
                    {
                        "platform": "generic",
                        "code": str(item.get("error_code") or "SEARCH_EXECUTION_FAILED"),
                        "message": str(item.get("message") or "搜索引擎失败"),
                        "retryable": bool(item.get("retryable")),
                    }
                )

        resources: list[dict[str, Any]] = []
        for item in response.get("results", []):
            if not isinstance(item, dict):
                continue
            try:
                source_url = canonical_http_url(str(item.get("source_url") or ""))
            except DomainError:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            resources.append(
                {
                    "platform": str(item.get("platform") or "generic"),
                    "title": title,
                    "source_url": source_url,
                    "resource_type": str(item.get("type") or "网页"),
                    "summary": item.get("description"),
                    "metadata": {
                        "author": item.get("author"),
                        "published_at": item.get("publish_time"),
                        "language": item.get("language"),
                        "download_feasibility": item.get("download_feasibility"),
                        "platform_signals": item.get("platform_signals") or {},
                    },
                }
            )
        return resources, errors

    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        all_resources: list[dict[str, Any]] = []
        platform_runs: list[dict[str, Any]] = []

        for task in search_tasks:
            platform = str(task.get("platform") or "")
            queries = task.get("queries") or []
            if platform != "generic":
                platform_runs.append(
                    {
                        "platform": platform,
                        "status": "skipped",
                        "query_runs": [],
                    }
                )
                continue

            query_runs: list[dict[str, Any]] = []
            task_resources: list[dict[str, Any]] = []
            task_error_count = 0
            for item in queries:
                query_text = str(item.get("query") or "").strip()
                if not query_text:
                    continue
                try:
                    resources, errors = self._search_single(query_text, limit)
                except DomainError as exc:
                    query_runs.append(
                        {
                            "query": query_text,
                            "candidate_count": 0,
                            "failure_count": 1,
                            "error": {
                                "code": exc.code,
                                "message": exc.message,
                                "retryable": exc.retryable,
                            },
                        }
                    )
                    task_error_count += 1
                    continue
                task_error_count += len(errors)
                query_runs.append(
                    {
                        "query": query_text,
                        "candidate_count": len(resources),
                        "failure_count": len(errors),
                    }
                )
                task_resources.extend(resources)

            total_candidates = sum(qr["candidate_count"] for qr in query_runs)
            if task_error_count == 0:
                status = "succeeded"
            elif total_candidates > 0:
                status = "partial"
            else:
                status = "failed"
            platform_runs.append(
                {"platform": "generic", "status": status, "query_runs": query_runs}
            )
            all_resources.extend(task_resources)

        return all_resources, platform_runs


class SearXNGSearchProvider:
    """Search through a local SearXNG instance via its JSON API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.searxng_base_url or "http://localhost:8888"

    def _fetch_page(self, query: str, page_no: int) -> dict[str, Any]:
        params = urlencode(
            {
                "q": query,
                "format": "json",
                "language": "zh",
                "pageno": page_no,
            }
        )
        url = f"{self.base_url}/search?{params}"
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(
            request, timeout=float(self.settings.search_timeout_seconds)
        ) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def _parse_page(
        self, data: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        for entry in data.get("unresponsive_engines", []):
            engine_name = entry[0] if isinstance(entry, list) else str(entry)
            errors.append(
                {
                    "platform": "generic",
                    "code": "PARTIAL_FAILURE",
                    "message": f"SearXNG 引擎 {engine_name} 无响应",
                    "retryable": True,
                }
            )

        resources: list[dict[str, Any]] = []
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            try:
                source_url = canonical_http_url(str(item.get("url") or ""))
            except DomainError:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            engines = item.get("engines") or []
            primary_engine = (
                engines[0] if isinstance(engines, list) and engines else "searxng"
            )
            resources.append(
                {
                    "platform": "generic",
                    "title": title,
                    "source_url": source_url,
                    "resource_type": "网页",
                    "summary": item.get("content"),
                    "metadata": {
                        "engine": primary_engine,
                        "published_at": item.get("publishedDate"),
                        "score": item.get("score"),
                    },
                }
            )
        return resources, errors

    def _search_single(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        max_pages = max(1, min(5, (limit + 19) // 20))
        all_resources: list[dict[str, Any]] = []
        all_errors: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for page_no in range(1, max_pages + 1):
            try:
                data = self._fetch_page(query, page_no)
            except HTTPError as exc:
                raise DomainError(
                    "PARTIAL_FAILURE",
                    f"SearXNG 返回 HTTP {exc.code}",
                    retryable=True,
                ) from exc
            except (OSError, TimeoutError, URLError) as exc:
                if all_resources:
                    all_errors.append(
                        {
                            "platform": "generic",
                            "code": "PARTIAL_FAILURE",
                            "message": f"SearXNG 第 {page_no} 页请求失败：{type(exc).__name__}",
                            "retryable": True,
                        }
                    )
                    break
                raise DomainError(
                    "PARTIAL_FAILURE",
                    f"SearXNG 请求失败：{type(exc).__name__}: {exc}",
                    retryable=True,
                ) from exc

            page_resources, page_errors = self._parse_page(data)
            all_errors.extend(page_errors)

            new_count = 0
            for resource in page_resources:
                url = resource["source_url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_resources.append(resource)
                new_count += 1

            if new_count == 0 or len(all_resources) >= limit:
                break

        return all_resources, all_errors

    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        all_resources: list[dict[str, Any]] = []
        platform_runs: list[dict[str, Any]] = []

        for task in search_tasks:
            platform = str(task.get("platform") or "")
            queries = task.get("queries") or []
            if platform != "generic":
                platform_runs.append(
                    {"platform": platform, "status": "skipped", "query_runs": []}
                )
                continue

            query_runs: list[dict[str, Any]] = []
            task_resources: list[dict[str, Any]] = []
            task_error_count = 0
            for item in queries:
                query_text = str(item.get("query") or "").strip()
                if not query_text:
                    continue
                try:
                    resources, errors = self._search_single(query_text, limit)
                except DomainError as exc:
                    query_runs.append(
                        {
                            "query": query_text,
                            "candidate_count": 0,
                            "failure_count": 1,
                            "error": {
                                "code": exc.code,
                                "message": exc.message,
                                "retryable": exc.retryable,
                            },
                        }
                    )
                    task_error_count += 1
                    continue
                task_error_count += len(errors)
                query_runs.append(
                    {
                        "query": query_text,
                        "candidate_count": len(resources),
                        "failure_count": len(errors),
                    }
                )
                task_resources.extend(resources)

            total_candidates = sum(qr["candidate_count"] for qr in query_runs)
            if task_error_count == 0:
                status = "succeeded"
            elif total_candidates > 0:
                status = "partial"
            else:
                status = "failed"
            platform_runs.append(
                {"platform": "generic", "status": status, "query_runs": query_runs}
            )
            all_resources.extend(task_resources)

        return all_resources, platform_runs


class MultiPlatformSearchProvider:
    """Dispatch search to platform adapters and the generic provider."""

    def __init__(
        self,
        settings: Settings,
        session_store: Any,
        generic_provider: SearchProvider,
    ) -> None:
        self.settings = settings
        self.session_store = session_store
        self.generic_provider = generic_provider
        self._adapters: dict[str, PlatformSearchAdapter] = {}
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        """Instantiate built-in platform adapters."""

        import importlib

        adapter_classes: list[tuple[str, type]] = []
        for module_name, class_name in (
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
        ):
            try:
                module = importlib.import_module(
                    f".adapters.{module_name}", package=__package__
                )
                cls = getattr(module, class_name)
                adapter_classes.append((module_name.replace("_", "-"), cls))
            except ImportError:
                pass
        for _platform_id, cls in adapter_classes:
            self.register_adapter(cls(self.session_store, self.settings))

        try:
            module = importlib.import_module(".adapters.zjer", package=__package__)
            cls = getattr(module, "ZjerSearchAdapter")
            self.register_adapter(cls(self.session_store, self.settings))
        except ImportError:
            pass

    def register_adapter(self, adapter: PlatformSearchAdapter) -> None:
        """Register or replace an adapter by its actual runtime platform id."""

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

        total_candidates = sum(qr["candidate_count"] for qr in query_runs)
        if error_count == 0:
            status = "succeeded"
        elif total_candidates > 0:
            status = "partial"
        else:
            status = "failed"
        return all_resources, {
            "platform": platform,
            "status": status,
            "query_runs": query_runs,
        }

    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        merged: dict[str, dict[str, Any]] = {}
        for task in search_tasks:
            platform = str(task.get("platform") or "")
            queries = [
                str(query.get("query") or "").strip()
                for query in (task.get("queries") or [])
                if str(query.get("query") or "").strip()
            ]
            if not queries:
                continue
            if platform in merged:
                merged[platform]["queries"].extend(queries)
            else:
                merged[platform] = {"queries": list(queries)}

        if not merged:
            return [], []

        adapter_platforms = {
            platform: entry
            for platform, entry in merged.items()
            if platform in self._adapters
        }
        generic_queries = list(merged.get("generic", {}).get("queries", []))
        unknown_platforms = {
            platform: entry
            for platform, entry in merged.items()
            if platform != "generic" and platform not in self._adapters
        }

        work_items: list[tuple[str, str, list[str]]] = []
        for platform, entry in adapter_platforms.items():
            work_items.append(
                (platform, "adapter", list(entry.get("queries") or []))
            )
        if generic_queries:
            work_items.append(("generic", "generic", generic_queries))

        results_by_platform: dict[
            str, tuple[list[dict[str, Any]], dict[str, Any]]
        ] = {}
        if work_items:
            worker_count = max(
                1, min(len(work_items), self.settings.max_workers)
            )
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures: dict[Any, tuple[str, list[str]]] = {}
                for platform, kind, submitted_queries in work_items:
                    if kind == "adapter":
                        future = pool.submit(
                            self._run_platform_adapter,
                            platform,
                            self._adapters[platform],
                            submitted_queries,
                            limit,
                        )
                    else:
                        future = pool.submit(
                            self.generic_provider.search,
                            [
                                {
                                    "platform": "generic",
                                    "queries": [
                                        {"query": query}
                                        for query in submitted_queries
                                    ],
                                }
                            ],
                            limit,
                        )
                    futures[future] = (platform, submitted_queries)

                for future, (platform, submitted_queries) in futures.items():
                    try:
                        if platform == "generic":
                            generic_resources, generic_runs = future.result()
                            results_by_platform[platform] = (
                                generic_resources,
                                generic_runs[0]
                                if generic_runs
                                else {
                                    "platform": "generic",
                                    "status": "failed",
                                    "query_runs": [],
                                },
                            )
                        else:
                            results_by_platform[platform] = future.result()
                    except Exception as exc:  # pragma: no cover - provider boundary
                        results_by_platform[platform] = (
                            [],
                            {
                                "platform": platform,
                                "status": "failed",
                                "query_runs": [
                                    {
                                        "query": "; ".join(submitted_queries),
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

        platform_runs: list[dict[str, Any]] = []
        all_resources: list[dict[str, Any]] = []
        available = sorted(self._adapters) + ["generic"]
        for platform in merged:
            if platform in unknown_platforms:
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
                                        f"平台 {platform} 尚未接入；"
                                        f"可用平台：{', '.join(available)}"
                                    ),
                                    "retryable": False,
                                },
                            }
                            for query in unknown_platforms[platform].get("queries", [])
                        ],
                    }
                )
                continue
            if platform in results_by_platform:
                resources, run = results_by_platform[platform]
                platform_runs.append(run)
                all_resources.extend(resources)
            elif platform == "generic":
                platform_runs.append(
                    {
                        "platform": "generic",
                        "status": "failed",
                        "query_runs": [],
                    }
                )

        return all_resources, platform_runs


def default_search_provider(
    settings: Settings, session_store: Any = None
) -> SearchProvider:
    """Build the default search provider."""

    if settings.searxng_base_url and getattr(settings, "prefer_searxng", False):
        generic: SearchProvider = SearXNGSearchProvider(settings)
    else:
        generic = GenericWebSearchProvider(settings)
    if session_store is not None:
        return MultiPlatformSearchProvider(settings, session_store, generic)
    return generic


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
            platform = str(task.get("platform") or "generic")
            queries = task.get("queries") or []
            query_runs: list[dict[str, Any]] = []
            task_resources: list[dict[str, Any]] = []

            for item in queries:
                query_text = str(item.get("query") or "").lower()
                selected = [
                    dict(resource)
                    for resource in self.resources
                    if not query_text
                    or query_text in str(resource.get("title", "")).lower()
                    or query_text in str(resource.get("summary", "")).lower()
                ]
                query_runs.append(
                    {
                        "query": str(item.get("query") or ""),
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
