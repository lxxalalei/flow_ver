"""Search providers owned by the MCP service."""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .adapters import generic_web
from .config import Settings
from .errors import DomainError


class SearchProvider(Protocol):
    def search(
        self, query: str, limit: int, platforms: list[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...


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

    def __init__(self, settings: Settings, engines: list[str] | None = None) -> None:
        self.settings = settings
        self.engines = engines or ["duckduckgo", "bing"]

    def search(
        self, query: str, limit: int, platforms: list[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        requested = platforms or ["generic"]
        unsupported = sorted(set(requested) - {"generic"})
        errors: list[dict[str, Any]] = []
        for platform in unsupported:
            errors.append(
                {
                    "platform": platform,
                    "code": "PLATFORM_UNAVAILABLE",
                    "message": "首版 MCP 尚未启用该平台",
                    "retryable": False,
                }
            )
        if "generic" not in requested:
            return [], errors

        try:
            response = generic_web.search(
                query,
                list(self.engines),
                limit,
                float(self.settings.search_timeout_seconds),
            )
        except Exception as exc:
            raise DomainError(
                "PARTIAL_FAILURE",
                f"Generic 搜索失败：{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc

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
        return resources[:limit], errors


class SearXNGSearchProvider:
    """Search through a local SearXNG instance via its JSON API."""

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

    def search(
        self, query: str, limit: int, platforms: list[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # SearXNG returns ~20 results per page. Fetch enough pages to
        # satisfy *limit*, but cap at 5 pages to avoid excessive load.
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
                    # Partial results already collected; degrade gracefully.
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

            # Deduplicate by URL across pages.
            new_count = 0
            for r in page_resources:
                url = r["source_url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_resources.append(r)
                new_count += 1

            # Stop early if the page returned nothing new or we have enough.
            if new_count == 0:
                break
            if len(all_resources) >= limit:
                break

        return all_resources[:limit], all_errors


def default_search_provider(settings: Settings) -> SearchProvider:
    """Pick SearXNG when configured, otherwise fall back to generic web scraping."""
    if settings.searxng_base_url:
        return SearXNGSearchProvider(settings)
    return GenericWebSearchProvider(settings)


class StaticSearchProvider:
    """Deterministic provider for tests and offline smoke runs."""

    def __init__(self, resources: list[dict[str, Any]]) -> None:
        self.resources = resources

    def search(
        self, query: str, limit: int, platforms: list[str] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        query_lower = query.lower()
        selected = [
            dict(item)
            for item in self.resources
            if not query_lower
            or query_lower in str(item.get("title", "")).lower()
            or query_lower in str(item.get("summary", "")).lower()
        ]
        return selected[:limit], []
