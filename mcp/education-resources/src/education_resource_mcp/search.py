"""Search providers owned by the MCP service."""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from concurrent.futures import ThreadPoolExecutor

from .adapters import generic_web
from .adapters.base import (
    AdapterDescriptor,
    PlatformSearchAdapter,
    descriptor_for_platform,
)
from .config import Settings
from .errors import DomainError


class SearchProvider(Protocol):
    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Execute *search_tasks* and return ``(resources, platform_runs)``.

        *search_tasks* is a list of ``{"platform": str, "queries": [str, ...]}``
        dicts and may carry a semantic ``direction`` label. Providers ignore the
        label; the service attaches it to durable query provenance.
        Implementations run platforms in parallel and queries within a platform
        serially.  Each *platform_run* in the return value has the shape::

            {"platform": str, "status": str, "query_runs": [{query, candidate_count, failure_count, ...}]}
        """


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

    descriptor = descriptor_for_platform("generic")
    _CJK_ENGINES = ("duckduckgo", "baidu", "bing")
    _DEFAULT_ENGINES = ("bing",)

    def __init__(self, settings: Settings, engines: list[str] | None = None) -> None:
        self.settings = settings
        self.engines = tuple(engines) if engines is not None else None

    def _engines_for_query(self, query: str) -> list[str]:
        """Choose a bounded public-search route without rewriting the query.

        Bing remains the conservative default for non-CJK text.  In the live
        0028 environment it preserved full Chinese queries but repeatedly
        returned results for only the leading concept.  The existing
        DuckDuckGo/Baidu routes produced relevant Chinese candidates, so CJK
        queries try those routes first while retaining Bing as a final source.
        Explicit test/operator engine choices continue to take precedence.
        """

        if self.engines is not None:
            return list(self.engines)
        if any("\u3400" <= char <= "\u9fff" for char in query):
            return list(self._CJK_ENGINES)
        return list(self._DEFAULT_ENGINES)

    def _search_single(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Execute one *generic* query and return ``(resources, errors)``."""
        try:
            response = generic_web.search(
                query,
                self._engines_for_query(query),
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
                for err in errors:
                    task_error_count += 1
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

    descriptor = descriptor_for_platform("generic")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.searxng_base_url or "http://localhost:8888"

    def _fetch_page(self, query: str, page_no: int) -> dict[str, Any]:
        """Fetch a single SearXNG result page."""
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

    def _parse_page(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract resources and engine errors from a SearXNG response page."""
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
        """Execute one SearXNG query, paginating up to 5 pages."""
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
            for r in page_resources:
                url = r["source_url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_resources.append(r)
                new_count += 1

            if new_count == 0:
                break
            if len(all_resources) >= limit:
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
    """SearchProvider that dispatches to per-platform adapters.

    Runs each platform's queries **serially** (to avoid triggering rate
    limits) and all platforms **in parallel** via a thread pool.
    """

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
            ("nlc", "NlcSearchAdapter"),
            ("open163", "Open163SearchAdapter"),
            ("annas_archive", "AnnasArchiveSearchAdapter"),
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
        for pid, cls in adapter_classes:
            self.register_adapter(
                cls(self.session_store, self.settings),
                require_descriptor=True,
            )

        # Zjer is a runtime-experimental direct-course integration from real
        # course-detail evidence (plan 0052). It is intentionally registered
        # outside the strict broad Registry set until native keyword search is
        # confirmed and the Registry is aligned with a separate minimal diff.
        try:
            module = importlib.import_module(".adapters.zjer", package=__package__)
            cls = getattr(module, "ZjerSearchAdapter")
            self.register_adapter(
                cls(self.session_store, self.settings),
                require_descriptor=False,
            )
        except ImportError:
            pass

    def register_adapter(
        self,
        adapter: PlatformSearchAdapter,
        *,
        require_descriptor: bool = False,
    ) -> None:
        """Register or replace an adapter.

        Built-ins must expose the exact active Registry descriptor.  The
        default remains compatible with legacy and third-party test stubs
        that only expose ``platform_id``.
        """

        if require_descriptor:
            descriptor = getattr(adapter, "descriptor", None)
            if not isinstance(descriptor, AdapterDescriptor):
                raise TypeError(
                    f"built-in adapter {adapter.platform_id!r} has no AdapterDescriptor"
                )
            expected = descriptor_for_platform(adapter.platform_id)
            if descriptor != expected:
                raise ValueError(
                    f"built-in adapter {adapter.platform_id!r} descriptor does not match Registry"
                )
        self._adapters[adapter.platform_id] = adapter

    @staticmethod
    def _creator_platform_run(
        platform: str,
        creator_id: str,
        candidate_count: int,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query_run: dict[str, Any] = {
            "query": creator_id,
            "candidate_count": candidate_count,
            "failure_count": 1 if error else 0,
        }
        if error:
            query_run["error"] = {
                "code": str(error.get("code") or "PARTIAL_FAILURE"),
                "message": str(error.get("message") or "创作者浏览失败"),
                "retryable": bool(error.get("retryable")),
            }
        return {
            "platform": platform,
            "status": (
                "succeeded"
                if error is None
                else ("partial" if candidate_count else "failed")
            ),
            "query_runs": [query_run],
        }

    def search_creator(
        self, platform: str, creator_id: str, limit: int, cancel_event: Any = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Browse a creator's content via the platform adapter.

        Only adapters that implement ``search_creator`` are supported — this
        is a social-media capability (douyin, bilibili, zhihu, weibo, …).
        Education/resource platforms return FEATURE_NOT_SUPPORTED.
        """
        adapter = self._adapters.get(platform)
        if adapter is None:
            return [], [
                self._creator_platform_run(
                    platform,
                    creator_id,
                    0,
                    {
                        "code": "UNKNOWN_PLATFORM",
                        "message": f"平台 {platform} 无 adapter",
                        "retryable": False,
                    },
                )
            ]
        if not hasattr(adapter, "search_creator"):
            return [], [
                self._creator_platform_run(
                    platform,
                    creator_id,
                    0,
                    {
                        "code": "FEATURE_NOT_SUPPORTED",
                        "message": f"平台 {platform} 不支持创作者浏览",
                        "retryable": False,
                    },
                )
            ]
        if cancel_event is None:
            resources, error = adapter.search_creator(creator_id, limit)
        else:
            resources, error = adapter.search_creator(creator_id, limit, cancel_event)
        return resources, [
            self._creator_platform_run(platform, creator_id, len(resources), error)
        ]


    # ------------------------------------------------------------------
    # Per-platform worker: runs queries serially, returns one platform_run.
    # ------------------------------------------------------------------
    def _run_platform_adapter(
        self, platform: str, adapter: PlatformSearchAdapter, queries: list[str], limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        query_runs: list[dict[str, Any]] = []
        all_resources: list[dict[str, Any]] = []
        error_count = 0
        for query in queries:
            try:
                resources, error = adapter.search(query, limit)
            except Exception as exc:  # pragma: no cover - defensive
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
        platform_run = {
            "platform": platform,
            "status": status,
            "query_runs": query_runs,
        }
        return all_resources, platform_run

    def search(
        self, search_tasks: list[dict[str, Any]], limit: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # Merge tasks that share the same platform (preserve order).
        merged: dict[str, list[str]] = {}
        for task in search_tasks:
            platform = str(task.get("platform") or "")
            queries = [
                str(q.get("query") or "").strip()
                for q in (task.get("queries") or [])
                if str(q.get("query") or "").strip()
            ]
            if not queries:
                continue
            if platform in merged:
                merged[platform].extend(queries)
            else:
                merged[platform] = list(queries)

        if not merged:
            return [], []

        # Partition into adapter-backed, generic, and unknown platforms.
        adapter_platforms = {p: qs for p, qs in merged.items() if p in self._adapters}
        generic_queries = merged.get("generic", [])
        unknown_platforms = {
            p: qs for p, qs in merged.items()
            if p != "generic" and p not in self._adapters
        }

        # Build the full platform list for parallel execution.
        work_items: list[tuple[str, Any]] = []
        for pid, queries in adapter_platforms.items():
            work_items.append((pid, ("adapter", queries)))
        if generic_queries:
            work_items.append(("generic", ("generic", generic_queries)))

        worker_count = max(1, min(len(work_items), self.settings.max_workers))

        results_by_platform: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
        if work_items:
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures: dict[Any, str] = {}
                for platform, (kind, queries) in work_items:
                    if kind == "adapter":
                        adapter = self._adapters[platform]
                        futures[
                            pool.submit(self._run_platform_adapter, platform, adapter, queries, limit)
                        ] = platform
                    else:
                        futures[
                            pool.submit(self.generic_provider.search, [{"platform": "generic", "queries": [{"query": q} for q in queries]}], limit)
                        ] = "generic"

                for future, platform in futures.items():
                    try:
                        if platform == "generic":
                            generic_resources, generic_runs = future.result()
                            # generic provider returns its own platform_run
                            results_by_platform[platform] = (
                                generic_resources,
                                generic_runs[0] if generic_runs else {"platform": "generic", "status": "failed", "query_runs": []},
                            )
                        else:
                            results_by_platform[platform] = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        results_by_platform[platform] = (
                            [],
                            {
                                "platform": platform,
                                "status": "failed",
                                "query_runs": [
                                    {
                                        "query": "; ".join(queries) if kind == "adapter" else "; ".join(generic_queries),
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

        # Build platform_runs in the order tasks were submitted.
        platform_runs: list[dict[str, Any]] = []
        all_resources: list[dict[str, Any]] = []
        for platform in merged:
            if platform in unknown_platforms:
                platform_runs.append(
                    {
                        "platform": platform,
                        "status": "skipped",
                        "query_runs": [
                            {
                                "query": q,
                                "candidate_count": 0,
                                "failure_count": 1,
                                "error": {
                                    "code": "PLATFORM_UNAVAILABLE",
                                    "message": "该平台尚未接入搜索适配器",
                                    "retryable": False,
                                },
                            }
                            for q in unknown_platforms[platform]
                        ],
                    }
                )
                continue
            if platform in results_by_platform:
                resources, run = results_by_platform[platform]
                platform_runs.append(run)
                all_resources.extend(resources)

        return all_resources, platform_runs


def default_search_provider(
    settings: Settings, session_store: Any = None
) -> SearchProvider:
    """Build the default search provider.

    Uses the bounded direct-search adapter by default.  CJK queries prefer the
    existing DuckDuckGo/Baidu routes before Bing because live E2E evidence
    showed materially better Chinese recall; non-CJK queries keep Bing as the
    default.  Set ``settings.searxng_base_url`` *and*
    ``settings.prefer_searxng`` to opt back into SearXNG.

    When *session_store* is provided, wrap the generic provider in a
    :class:`MultiPlatformSearchProvider` so platform-specific adapters
    (bilibili, zhihu, smartedu, …) become available.
    """
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
                    dict(r)
                    for r in self.resources
                    if not query_text
                    or query_text in str(r.get("title", "")).lower()
                    or query_text in str(r.get("summary", "")).lower()
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
