"""Authenticated Z-Library inspection using stable EAPI book identity."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from ..inspection import INSPECTOR_VERSION, InspectionResult, build_default_inspection
from .zlibrary_client import (
    ZlibraryAuthRequired,
    ZlibraryClient,
    ZlibraryError,
    ZlibraryLimitReached,
    ZlibraryNotFound,
    ZlibraryUnavailable,
    resource_identity,
)


_MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
    "azw3": "application/x-mobi8-ebook",
    "djvu": "image/vnd.djvu",
    "txt": "text/plain",
}
RIGHTS_HINT = "仅使用用户自己的 Z-Library 账号额度；获取前请确认版权与来源许可。"


class ZlibraryInspector:
    platform_id = "zlibrary"
    inspector_id = "zlibrary"
    version = INSPECTOR_VERSION

    def __init__(
        self,
        *,
        session_store: Any,
        timeout_seconds: float = 20,
        client: ZlibraryClient | None = None,
    ) -> None:
        self.client = client or ZlibraryClient(session_store, timeout_seconds)

    def _failure(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        *,
        retryable: bool,
        availability: str,
    ) -> InspectionResult:
        identity = resource_identity(resource)
        metadata: dict[str, Any] = {}
        if identity is not None:
            metadata = {"book_id": identity[0], "book_hash": identity[1]}
        return InspectionResult(
            resolution_status="unresolved",
            resolved_resource={
                "title": str(resource.get("title") or "Z-Library book")[:512],
                "resource_type": "book",
                "availability": {"status": availability},
                "representations": [],
                "metadata": metadata,
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="platform_detail_api",
                version=self.version,
            ),
            failures=(
                {
                    "platform": "zlibrary",
                    "code": code,
                    "message": message,
                    "retriable": retryable,
                },
            ),
        )

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if not isinstance(resource, Mapping) or resource.get("platform") != "zlibrary":
            return self._failure(
                resource if isinstance(resource, Mapping) else {},
                "PLATFORM_VALIDATION_BLOCKED",
                "Z-Library 检查需要有效的 zlibrary Resource",
                retryable=False,
                availability="unknown",
            )
        identity = resource_identity(resource)
        if identity is None:
            return self._failure(
                resource,
                "PLATFORM_VALIDATION_BLOCKED",
                "Z-Library 检查需要合法 book_id 和 book_hash",
                retryable=False,
                availability="unknown",
            )
        book_id, book_hash = identity
        try:
            book = self.client.get_book(book_id, book_hash)
        except ZlibraryAuthRequired as exc:
            return self._failure(
                resource, "AUTH_REQUIRED", str(exc), retryable=False,
                availability="auth_required",
            )
        except ZlibraryNotFound as exc:
            return self._failure(
                resource, "RESOURCE_NOT_FOUND", str(exc), retryable=False,
                availability="unavailable",
            )
        except ZlibraryLimitReached as exc:
            return self._failure(
                resource, "RATE_LIMITED", str(exc), retryable=True,
                availability="unknown",
            )
        except ZlibraryUnavailable as exc:
            return self._failure(
                resource, "PLATFORM_UNAVAILABLE", str(exc), retryable=True,
                availability="unknown",
            )
        except ZlibraryError as exc:
            return self._failure(
                resource, "CONTENT_VALIDATION_FAILED", str(exc), retryable=False,
                availability="unknown",
            )

        extension = book.extension or "document"
        representation: dict[str, Any] = {
            "representation_id": "repr_" + hashlib.sha256(
                f"zlibrary|{book.book_id}|{book.book_hash}|{extension}".encode()
            ).hexdigest()[:32],
            "kind": "document",
            "container": extension,
            "scope": "primary_resource",
            "role": "primary",
            "technical_availability": "available",
            "materializable": True,
            "requires_auth": True,
            "rights_hint": RIGHTS_HINT,
        }
        if extension in _MIME_BY_EXTENSION:
            representation["mime_type"] = _MIME_BY_EXTENSION[extension]
        metadata = {
            "book_id": book.book_id,
            "book_hash": book.book_hash,
            "author": book.author or None,
            "year": book.year or None,
            "language": book.language or None,
            "extension": book.extension or None,
            "size": book.size or None,
            "isbn": book.isbn or None,
            "publisher": book.publisher or None,
            "pages": book.pages or None,
        }
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": book.title,
                "resource_type": "book",
                "availability": {"status": "available"},
                "representations": [representation],
                "metadata": {key: value for key, value in metadata.items() if value is not None},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="platform_detail_api",
                version=self.version,
            ),
            failures=(),
        )


__all__ = ["ZlibraryInspector"]
