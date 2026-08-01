"""Platform search adapter protocol and shared helpers.

Each platform-specific adapter (bilibili, zhihu, smartedu, …) implements
``PlatformSearchAdapter``.  The ``MultiPlatformSearchProvider`` in
``search.py`` dispatches to these adapters based on the ``platforms``
filter on ``resource_search``.

Adapters return results in the same normalized dict shape that
``GenericWebSearchProvider`` already produces, so the downstream service
layer (``ResourceService.search``) does not need to know which platform
a result came from.
"""

from __future__ import annotations

from typing import Any, Protocol


class PlatformSearchAdapter(Protocol):
    """Search a single platform.

    Implementations receive ``SessionStore`` and ``Settings`` at
    construction time so they can pull stored cookies / tokens at search
    time without the caller having to thread credentials through.
    """

    platform_id: str

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Search *query* on this platform, returning up to *limit* results.

        Returns a tuple of ``(resources, error)`` where *resources* is a
        list of normalized dicts (see :func:`make_resource`) and *error*
        is ``None`` on success or a dict with keys ``code``, ``message``,
        ``retryable`` on failure.
        """
        ...


def adapter_error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    """Build the error dict returned by adapters on failure."""
    return {"code": code, "message": message, "retryable": retryable}


def make_resource(
    *,
    platform: str,
    title: str,
    source_url: str,
    resource_type: str = "其他",
    summary: str | None = None,
    author: str | None = None,
    published_at: str | None = None,
    language: str | None = None,
    download_feasibility: str | None = None,
    platform_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized resource dict matching the shape that
    ``GenericWebSearchProvider`` produces and ``ResourceService.search``
    consumes.

    Only *platform*, *title* and *source_url* are required; the rest are
    folded into ``metadata`` when present.
    """
    metadata: dict[str, Any] = {"platform_signals": platform_signals or {}}
    if author is not None:
        metadata["author"] = author
    if published_at is not None:
        metadata["published_at"] = published_at
    if language is not None:
        metadata["language"] = language
    if download_feasibility is not None:
        metadata["download_feasibility"] = download_feasibility
    return {
        "platform": platform,
        "title": title,
        "source_url": source_url,
        "resource_type": resource_type,
        "summary": summary,
        "metadata": metadata,
    }
