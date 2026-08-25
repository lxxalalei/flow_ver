"""Bilibili structural expansion."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from ..errors import DomainError


def _kind(target: Mapping[str, Any]) -> str:
    return str(target.get("resource_type") or "").strip().casefold()


def _url(target: Mapping[str, Any]) -> str:
    return str(target.get("source_url") or "").strip()

def expand(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    url = _url(target)
    kind = _kind(target)
    is_collection_url = "space.bilibili.com" in url and (
        "/lists/" in url
        or "/channel/collectiondetail" in url
        or "/channel/seriesdetail" in url
    )
    if kind == "collection" or is_collection_url:
        iterator = getattr(adapter, "iter_collection", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili 合集展开不可用")
        yield from iterator(url, cancel_event=cancel_event)
        return
    if kind == "creator" or ("space.bilibili.com" in url and not is_collection_url):
        iterator = getattr(adapter, "iter_creator", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili 创作者展开不可用")
        yield from iterator(url, cancel_event=cancel_event)
        return
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "Bilibili video 是叶子资源，没有可展开子资源",
    )


__all__ = ["expand"]
