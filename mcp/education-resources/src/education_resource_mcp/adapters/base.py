"""Minimal shared interface for platform search adapters."""

from __future__ import annotations

from typing import Any, Protocol


class PlatformSearchAdapter(Protocol):
    platform_id: str

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        ...


def adapter_error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def make_resource(
    *,
    platform: str,
    title: str,
    source_url: str,
    resource_type: str = "其他",
    summary: str | None = None,
    author: str | None = None,
    creator_sec_uid: str | None = None,
    creator_mid: str | None = None,
    published_at: str | None = None,
    language: str | None = None,
    download_feasibility: str | None = None,
    platform_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"platform_signals": platform_signals or {}}
    if author is not None:
        metadata["author"] = author
    if creator_sec_uid:
        metadata["creator_sec_uid"] = creator_sec_uid
    if creator_mid:
        metadata["creator_mid"] = creator_mid
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
