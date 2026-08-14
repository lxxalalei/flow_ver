"""Construction of the active, platform-aware inspection router."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters.inspect_annas_archive import AnnasArchiveInspector
from .adapters.inspect_bilibili import BilibiliInspector
from .adapters.inspect_douyin import DouyinInspector
from .adapters.inspect_generic import GenericWebInspector
from .adapters.inspect_nlc import NlcInspector
from .adapters.inspect_shuge import ShugeInspector
from .adapters.inspect_smartedu import SmartEduInspector
from .adapters.inspect_ximalaya import XimalayaInspector
from .adapters.inspect_yixi import YixiInspector
from .adapters.inspect_zjer import ZjerInspector
from .adapters.inspect_zhihu import ZhihuInspector
from .inspection import InspectionRouter
from .retrieval.registry import INSPECTION_PLATFORM_IDS

if TYPE_CHECKING:
    from .config import Settings


def default_inspection_router(
    settings: "Settings | None" = None,
    *,
    session_store: object | None = None,
) -> InspectionRouter:
    """Build the exact inspection router enabled by the runtime platform set."""

    timeout_seconds = None
    if settings is not None:
        timeout_seconds = settings.search_timeout_seconds

    inspector_options = (
        {"timeout_seconds": timeout_seconds}
        if timeout_seconds is not None
        else {}
    )
    inspectors = (
        GenericWebInspector(**inspector_options),
        BilibiliInspector(session_store=session_store, **inspector_options),
        DouyinInspector(session_store=session_store),
        NlcInspector(**inspector_options),
        AnnasArchiveInspector(**inspector_options),
        XimalayaInspector(session_store=session_store, **inspector_options),
        ZhihuInspector(**inspector_options),
        SmartEduInspector(session_store=session_store, **inspector_options),
        ShugeInspector(**inspector_options),
        YixiInspector(**inspector_options),
        ZjerInspector(**inspector_options),
    )
    router = InspectionRouter(inspectors)
    registered = frozenset(router.registered_platforms)
    # Yixi and Zjer are enabled from real platform evidence in plans 0051 and
    # 0052. Their broad legacy Registry declarations are aligned separately so
    # the functional runtime path does not depend on a large registry rewrite.
    expected = frozenset(INSPECTION_PLATFORM_IDS) | {"yixi", "zjer"}
    if registered != expected:
        raise RuntimeError(
            "inspection router registration does not match the runtime "
            f"platform set: expected={sorted(expected)!r}, registered={sorted(registered)!r}"
        )
    return router


__all__ = ["default_inspection_router"]
