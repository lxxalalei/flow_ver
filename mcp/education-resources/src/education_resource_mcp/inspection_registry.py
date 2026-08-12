"""Construction of the active, platform-aware inspection router."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters.inspect_annas_archive import AnnasArchiveInspector
from .adapters.inspect_bilibili import BilibiliInspector
from .adapters.inspect_douyin import DouyinInspector
from .adapters.inspect_generic import GenericWebInspector
from .adapters.inspect_nlc import NlcInspector
from .adapters.inspect_smartedu import SmartEduInspector
from .adapters.inspect_ximalaya import XimalayaInspector
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
    """Build the exact inspection router enabled by the capability registry.

    The registry is an executable invariant here: accidentally omitting an
    inspector, or registering one that the retrieval layer did not advertise,
    is a startup error rather than a silent generic fallback.
    """

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
    )
    router = InspectionRouter(inspectors)
    registered = frozenset(router.registered_platforms)
    expected = frozenset(INSPECTION_PLATFORM_IDS)
    if registered != expected:
        raise RuntimeError(
            "inspection router registration does not match the retrieval "
            f"registry: expected={sorted(expected)!r}, registered={sorted(registered)!r}"
        )
    return router


__all__ = ["default_inspection_router"]
