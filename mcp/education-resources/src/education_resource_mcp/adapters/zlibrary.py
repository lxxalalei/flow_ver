"""Authenticated Z-Library search adapter."""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .zlibrary_client import (
    ZlibraryAuthRequired,
    ZlibraryClient,
    ZlibraryError,
    ZlibraryLimitReached,
    ZlibraryUnavailable,
)


class ZlibrarySearchAdapter:
    platform_id = "zlibrary"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self._client = ZlibraryClient(
            session_store, timeout=float(settings.search_timeout_seconds)
        )

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            books = self._client.search(query, limit=min(limit, 50))
            credentials = self._client.credentials()
        except ZlibraryAuthRequired as exc:
            return [], adapter_error("AUTH_REQUIRED", str(exc), False)
        except ZlibraryLimitReached as exc:
            return [], adapter_error("RATE_LIMITED", str(exc), True)
        except ZlibraryUnavailable as exc:
            return [], adapter_error("PLATFORM_UNAVAILABLE", str(exc), True)
        except ZlibraryError as exc:
            return [], adapter_error("PARTIAL_FAILURE", str(exc), False)

        results: list[dict[str, Any]] = []
        for book in books:
            results.append(
                make_resource(
                    platform="zlibrary",
                    title=book.title,
                    source_url=(
                        f"https://{credentials.domain}/book/"
                        f"{book.book_id}/{book.book_hash}"
                    ),
                    resource_type="book",
                    summary=book.description or None,
                    author=book.author or None,
                    published_at=book.year or None,
                    language=book.language or None,
                    download_feasibility="需要用户自己的 Z-Library 登录态和剩余下载额度",
                    platform_signals={
                        "book_id": book.book_id,
                        "book_hash": book.book_hash,
                        "format": book.extension or None,
                        "size": book.size or None,
                        "isbn": book.isbn or None,
                        "publisher": book.publisher or None,
                        "pages": book.pages or None,
                        "cover": book.cover or None,
                        "acquisition_route": "zlibrary_eapi",
                    },
                )
            )
        return results, None


__all__ = ["ZlibrarySearchAdapter"]
