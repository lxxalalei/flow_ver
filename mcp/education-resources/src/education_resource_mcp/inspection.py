"""Small inspection result and platform router.

Inspectors return current resource facts. There is no persisted Resolution,
evidence authority, fingerprint cache or freshness window in this layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from .errors import DomainError


INSPECTOR_VERSION = "1.0.0"
RESOLUTION_STATUSES = frozenset({"resolved", "partial", "unresolved"})
AVAILABILITY_STATUSES = frozenset(
    {"available", "auth_required", "unavailable", "unknown", "policy_blocked"}
)
REPRESENTATION_KINDS = frozenset(
    {"webpage", "document", "video", "audio", "image", "subtitle", "other"}
)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DomainError("INVALID_ARGUMENT", f"{label} 必须是对象")
    return value


def normalize_resolved_resource(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the current resource facts without building an authority envelope."""

    resource = dict(_mapping(value, "resolved_resource"))
    representations = resource.get("representations")
    if representations is None:
        resource["representations"] = []
    elif isinstance(representations, Sequence) and not isinstance(
        representations, (str, bytes, bytearray)
    ):
        resource["representations"] = [
            dict(item) for item in representations if isinstance(item, Mapping)
        ]
    else:
        raise DomainError("INVALID_ARGUMENT", "representations 必须是数组")

    availability = resource.get("availability")
    if not isinstance(availability, Mapping):
        resource["availability"] = {"status": "unknown"}
    else:
        status = str(availability.get("status") or "unknown")
        resource["availability"] = {
            "status": status if status in AVAILABILITY_STATUSES else "unknown"
        }

    metadata = resource.get("metadata")
    resource["metadata"] = dict(metadata) if isinstance(metadata, Mapping) else {}
    return deepcopy(resource)


@dataclass(frozen=True)
class InspectionResult:
    resolution_status: str
    resolved_resource: Mapping[str, Any]
    inspection: Mapping[str, Any]
    failures: Sequence[Mapping[str, Any]] = ()

    def __post_init__(self) -> None:
        status = str(self.resolution_status or "unresolved")
        if status not in RESOLUTION_STATUSES:
            status = "unresolved"
        object.__setattr__(self, "resolution_status", status)
        object.__setattr__(
            self,
            "resolved_resource",
            normalize_resolved_resource(self.resolved_resource),
        )
        object.__setattr__(
            self,
            "inspection",
            deepcopy(dict(self.inspection)) if isinstance(self.inspection, Mapping) else {},
        )
        object.__setattr__(
            self,
            "failures",
            [deepcopy(dict(item)) for item in self.failures if isinstance(item, Mapping)],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "resolution_status": self.resolution_status,
            "resolved_resource": deepcopy(dict(self.resolved_resource)),
            "inspection": deepcopy(dict(self.inspection)),
            "failures": deepcopy(list(self.failures)),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InspectionResult":
        mapping = _mapping(value, "inspection_result")
        return cls(
            resolution_status=str(mapping.get("resolution_status") or "unresolved"),
            resolved_resource=(
                mapping.get("resolved_resource")
                if isinstance(mapping.get("resolved_resource"), Mapping)
                else {}
            ),
            inspection=(
                mapping.get("inspection")
                if isinstance(mapping.get("inspection"), Mapping)
                else {}
            ),
            failures=(
                mapping.get("failures")
                if isinstance(mapping.get("failures"), Sequence)
                and not isinstance(mapping.get("failures"), (str, bytes, bytearray))
                else ()
            ),
        )


@runtime_checkable
class ResourceInspector(Protocol):
    platform_id: str

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        ...


class InspectionRouter:
    """Dispatch one candidate to the inspector registered for its platform."""

    def __init__(self, inspectors: Sequence[ResourceInspector] | None = None) -> None:
        self._inspectors: dict[str, ResourceInspector] = {}
        for inspector in inspectors or ():
            self.register(inspector)

    def register(self, inspector: ResourceInspector) -> None:
        platform_id = str(getattr(inspector, "platform_id", "") or "").strip()
        if not platform_id or not callable(getattr(inspector, "inspect", None)):
            raise ValueError("inspector must declare platform_id and inspect()")
        if platform_id in self._inspectors:
            raise ValueError(f"duplicate inspector: {platform_id}")
        self._inspectors[platform_id] = inspector

    @property
    def registered_platforms(self) -> tuple[str, ...]:
        return tuple(self._inspectors)

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if not isinstance(resource, Mapping):
            raise DomainError("INVALID_ARGUMENT", "resource 必须是对象")
        platform = str(resource.get("platform") or "").strip()
        inspector = self._inspectors.get(platform)
        if inspector is None:
            raise DomainError("FEATURE_NOT_SUPPORTED", f"平台 {platform or 'unknown'} 暂不支持检查")
        result = inspector.inspect(resource)
        if not isinstance(result, InspectionResult):
            raise DomainError("INTERNAL_ERROR", "检查器返回了无效结果")
        return result

    def resolve(self, resource: Mapping[str, Any]) -> InspectionResult:
        return self.inspect(resource)


def build_default_inspection(
    inspector_id: str,
    *,
    method: str = "get",
    cache_status: str = "miss",
    inspected_at: str | None = None,
    warnings: Sequence[str] = (),
    version: str = INSPECTOR_VERSION,
) -> dict[str, Any]:
    """Build small diagnostic metadata used by existing inspector classes."""

    return {
        "inspector_id": str(inspector_id),
        "version": str(version),
        "method": str(method),
        "cache_status": str(cache_status),
        "inspected_at": inspected_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "warnings": [str(item) for item in warnings],
    }


__all__ = [
    "AVAILABILITY_STATUSES",
    "INSPECTOR_VERSION",
    "InspectionResult",
    "InspectionRouter",
    "ResourceInspector",
    "build_default_inspection",
    "normalize_resolved_resource",
]
