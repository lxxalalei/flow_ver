"""Anna's Archive search adapter backed by public Libgen mirrors.

The platform label remains ``annas-archive`` for the user-facing resource
category, but discovery and acquisition are anonymous Libgen-mirror operations
using the same MD5 identity.  No Anna's Archive membership/session is required.
"""
from __future__ import annotations

from typing import Any

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .libgen_client import LibgenError, create_libgen_client


class AnnasArchiveSearchAdapter:
    platform_id = "annas-archive"
    descriptor = descriptor_for_platform("annas-archive")

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self._client = create_libgen_client(float(settings.search_timeout_seconds))

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            books = self._client.search(query, limit=min(limit, 50))
        except LibgenError as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"Anna's Archive 镜像搜索失败: {exc}", True)

        primary_mirror = self._client.mirrors[0]
        results: list[dict[str, Any]] = []
        for book in books:
            results.append(
                make_resource(
                    platform="annas-archive",
                    title=book.title or f"Document {book.md5[:8]}",
                    source_url=f"{primary_mirror}/ads.php?md5={book.md5}",
                    resource_type="图书",
                    summary=book.description or None,
                    author=book.author or None,
                    published_at=book.year or None,
                    download_feasibility="匿名镜像",
                    platform_signals={
                        "md5": book.md5,
                        "format": book.extension or None,
                        "language": book.language or None,
                        "pages": book.pages or None,
                        "size": book.size or None,
                        "publisher": book.publisher or None,
                        "isbn": book.isbn or None,
                        "acquisition_route": "libgen_mirror",
                    },
                )
            )
        return results, None
