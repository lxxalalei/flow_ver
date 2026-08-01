"""Platform search adapters package."""

from __future__ import annotations

from .base import PlatformSearchAdapter, adapter_error, make_resource

__all__ = [
    "PlatformSearchAdapter",
    "adapter_error",
    "make_resource",
]
