"""LibGen search adapter backed by public LibGen mirrors.

Discovery and acquisition use the same MD5 resource identity.
"""
from __future__ import annotations

from typing import Any

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .libgen_client import LibgenError, create_libgen_client


class LibgenSearchAdapter:
    platform_id = "libgen"
    descriptor = descriptor_for_platform("libgen")

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self._client = create_libgen_client(float(settings.search_timeout_seconds))

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            books = self._client.search(query, limit=min(limit, 50))
        except LibgenError as exc:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"LibGen 镜像搜索失败: {exc}",
                True,
            )

        primary_mirror = self._client.mirrors[0]
        results: list[dict[str, Any]] = []
        for book in books:
            results.append(
                make_resource(
                    platform="libgen",
                    title=book.title or f"Document {book.md5[:8]}",
                    source_url=f"{primary_mirror}/ads.php?md5={book.md5}",
                    resource_type="book",
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
__all__ = ["LibgenSearchAdapter"]
