"""CCTV column and series expansion."""

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
    from . import cctv as cctv_adapter

    url = _url(target)
    kind = _kind(target)
    if kind == "column" or "/lm/" in url:
        iterator = getattr(adapter, "iter_column", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "CCTV 栏目展开不可用")
        results = iterator(url, cancel_event=cancel_event)
        yield from results
        return
    if kind in {"视频", "video", "series"} or cctv_adapter.EPISODE_PATH_RE.search(url):
        timeout = float(getattr(adapter, "timeout", 30.0))
        links = cctv_adapter.series_episode_links(url, timeout=timeout)
        if links:
            yield from cctv_adapter.iter_episodes(
                links, timeout=timeout, cancel_event=cancel_event
            )
            return
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "CCTV 单集是叶子资源，没有可展开子资源；栏目或纪录片系列页才可展开",
        )
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "CCTV 当前资源没有已实现的结构展开能力",
    )


__all__ = ["expand"]
