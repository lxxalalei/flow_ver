"""Construct the platform-aware inspection router."""

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

if TYPE_CHECKING:
    from .config import Settings


def default_inspection_router(
    settings: "Settings | None" = None,
    *,
    session_store: object | None = None,
) -> InspectionRouter:
    """Register the inspectors that actually exist in this package."""

    timeout = settings.search_timeout_seconds if settings is not None else None
    options = {"timeout_seconds": timeout} if timeout is not None else {}
    return InspectionRouter(
        (
            GenericWebInspector(**options),
            BilibiliInspector(session_store=session_store, **options),
            DouyinInspector(session_store=session_store),
            NlcInspector(**options),
            AnnasArchiveInspector(**options),
            XimalayaInspector(session_store=session_store, **options),
            ZhihuInspector(**options),
            SmartEduInspector(session_store=session_store, **options),
            ShugeInspector(**options),
            YixiInspector(**options),
            ZjerInspector(**options),
        )
    )


__all__ = ["default_inspection_router"]
