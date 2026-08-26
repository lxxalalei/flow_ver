"""Route structural expansion to the owning platform adapter module."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Callable

from ..errors import DomainError
from . import (
    bilibili_expand,
    cctv_expand,
    douyin_expand,
    smartedu_expand,
    ximalaya_expand,
    zjer_expand,
)


Expander = Callable[..., Iterator[dict[str, Any]]]

_EXPANDERS: dict[str, Expander] = {
    "bilibili": bilibili_expand.expand,
    "douyin": douyin_expand.expand,
    "ximalaya": ximalaya_expand.expand,
    "smartedu": smartedu_expand.expand,
    "zjer": zjer_expand.expand,
    "cctv": cctv_expand.expand,
}


def expand_resource(
    search_provider: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
    session_store: Any = None,
) -> Iterator[dict[str, Any]]:
    """Dispatch one container Resource without owning platform mechanics."""

    platform = str(target.get("platform") or "").strip()
    adapter = (getattr(search_provider, "_adapters", None) or {}).get(platform)
    if adapter is None:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            f"平台 {platform or 'generic'} 当前没有结构展开能力",
        )
    expander = _EXPANDERS.get(platform)
    if expander is None:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            f"平台 {platform} 当前没有结构展开能力",
        )
    if platform == "smartedu":
        yield from expander(
            adapter,
            target,
            cancel_event=cancel_event,
            summary=summary,
        )
        return
    if platform in {"ximalaya", "zjer"}:
        yield from expander(
            adapter,
            target,
            cancel_event=cancel_event,
            session_store=session_store,
        )
        return
    yield from expander(adapter, target, cancel_event=cancel_event)


__all__ = ["expand_resource"]
