"""Retired 0025/0027 capability-authority compatibility seam.

0037 removed Descriptor -> Readiness -> Eligibility -> binding-digest state from
the active acquisition model.  New runtime code must use
``acquisition.planner.AcquisitionPlanner`` and exact Provider registrations.

This module intentionally stays tiny during the staged Service cutover because
the pre-0037 ``service.py`` base still imports these names.  It must not grow a
second registry, persist authority facts, hash Plan/Execution state, or become
a fallback route.  Git history retains the former implementation for audit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class CapabilityAuthorityError(ValueError):
    """Compatibility error shape for callers still importing the old name."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        *,
        retryable: bool = False,
    ) -> None:
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})
        self.retryable = bool(retryable)
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            result["details"] = dict(self.details)
        return result


class CapabilityCoordinator:
    """Fail-fast guard for accidental use of the retired authority chain."""

    def __init__(self, *_: Any, **__: Any) -> None:
        raise RuntimeError(
            "CapabilityCoordinator was retired by 0037; use AcquisitionPlanner "
            "with the simplified ResourceService"
        )


__all__ = ["CapabilityAuthorityError", "CapabilityCoordinator"]
