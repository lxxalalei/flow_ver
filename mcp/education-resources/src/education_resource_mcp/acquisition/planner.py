"""Small provider planner for acquisition.

The planner answers one business question: given a fresh inspected
Representation, which exact registered Provider should execute it?  It does
not persist readiness/eligibility snapshots and does not create authority
hashes.  A Plan stores the selected route; Start revalidates the current
Representation and exact Provider registration before a Job is created.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..inspection import representation_evidence_is_fresh, source_fingerprint
from .models import AcquisitionStrategy, CAPABILITY_SCOPES
from .router import AcquisitionRouter


_DOCUMENT_CONTAINERS = frozenset(
    {"pdf", "epub", "doc", "docx", "ppt", "pptx", "txt", "rtf", "odt", "zip"}
)


class AcquisitionPlanningError(ValueError):
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


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    platform_id: str
    scope: str
    representation_kind: str
    role: str
    strategy: AcquisitionStrategy
    provider_id: str
    provider_version: str
    containers: frozenset[str] = frozenset()
    resource_types: frozenset[str] = frozenset()

    def matches(
        self,
        resource: Mapping[str, Any],
        representation: Mapping[str, Any],
        scope: str,
    ) -> bool:
        platform = str(resource.get("platform") or "generic")
        if platform != self.platform_id or scope != self.scope:
            return False
        if str(representation.get("kind") or "") != self.representation_kind:
            return False
        if _representation_role(representation) != self.role:
            return False
        container = str(representation.get("container") or "").strip().lower()
        if self.containers and container and container not in self.containers:
            return False
        resource_type = str(
            resource.get("resource_type") or resource.get("type") or "other"
        )
        if self.resource_types and resource_type not in self.resource_types:
            return False
        return bool(representation.get("materializable", True))


DEFAULT_PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        platform_id="smartedu",
        scope="primary_resource",
        representation_kind="document",
        role="primary",
        strategy=AcquisitionStrategy.DIRECT_FILE,
        provider_id="smartedu-resource",
        provider_version="1.0.0",
        containers=frozenset({"pdf"}),
        resource_types=frozenset({"book", "course", "document", "other"}),
    ),
    ProviderSpec(
        platform_id="smartedu",
        scope="primary_resource",
        representation_kind="video",
        role="primary",
        strategy=AcquisitionStrategy.DIRECT_FILE,
        provider_id="smartedu-resource",
        provider_version="1.0.0",
        containers=frozenset({"mp4"}),
        resource_types=frozenset({"course", "video"}),
    ),
    ProviderSpec(
        platform_id="smartedu",
        scope="primary_resource",
        representation_kind="audio",
        role="primary",
        strategy=AcquisitionStrategy.DIRECT_FILE,
        provider_id="smartedu-resource",
        provider_version="1.0.0",
        containers=frozenset({"mp3", "m4a"}),
        resource_types=frozenset({"audio", "course"}),
    ),
    ProviderSpec(
        platform_id="douyin",
        scope="primary_resource",
        representation_kind="video",
        role="primary",
        strategy=AcquisitionStrategy.DIRECT_FILE,
        provider_id="douyin-video",
        provider_version="1.0.0",
        containers=frozenset({"mp4"}),
        resource_types=frozenset({"video"}),
    ),
    ProviderSpec(
        platform_id="generic",
        scope="primary_resource",
        representation_kind="document",
        role="primary",
        strategy=AcquisitionStrategy.DIRECT_FILE,
        provider_id="generic-direct",
        provider_version="1.0.0",
        containers=_DOCUMENT_CONTAINERS,
        resource_types=frozenset(
            {"article", "book", "course", "dataset", "document", "other"}
        ),
    ),
    ProviderSpec(
        platform_id="generic",
        scope="primary_resource",
        representation_kind="video",
        role="primary",
        strategy=AcquisitionStrategy.DIRECT_FILE,
        provider_id="generic-direct",
        provider_version="1.0.0",
        containers=frozenset({"mp4"}),
        resource_types=frozenset({"course", "video"}),
    ),
    # When the page itself is the selected article/resource, materialised HTML
    # is the primary resource. A navigation/preview page remains landing_page.
    ProviderSpec(
        platform_id="generic",
        scope="primary_resource",
        representation_kind="webpage",
        role="primary",
        strategy=AcquisitionStrategy.WEB_MATERIALIZE,
        provider_id="generic-web-materializer",
        provider_version="1.0.0",
        containers=frozenset({"html"}),
        resource_types=frozenset(
            {"article", "course", "dataset", "document", "other"}
        ),
    ),
    ProviderSpec(
        platform_id="generic",
        scope="landing_page",
        representation_kind="webpage",
        role="landing",
        strategy=AcquisitionStrategy.WEB_MATERIALIZE,
        provider_id="generic-web-materializer",
        provider_version="1.0.0",
        containers=frozenset({"html"}),
    ),
)


def _fingerprint_key(value: Any) -> str:
    text = str(value or "")
    return text[7:] if text.startswith("sha256:") else text


def _resolved_mapping(resolution: Mapping[str, Any]) -> dict[str, Any]:
    nested = resolution.get("resolved_resource")
    if not isinstance(nested, Mapping):
        nested = resolution.get("resolved")
    if isinstance(nested, Mapping):
        return dict(nested)
    return dict(resolution)


def _representation_role(representation: Mapping[str, Any]) -> str:
    role = str(representation.get("role") or "").strip().lower()
    if role in {"primary", "landing", "metadata", "attachment", "companion"}:
        return role
    kind = str(representation.get("kind") or "").strip().lower()
    if kind == "metadata":
        return "metadata"
    return "landing" if kind == "webpage" else "representation"


def _representation_scope(representation: Mapping[str, Any]) -> str:
    explicit = representation.get("scope")
    if isinstance(explicit, str) and explicit in CAPABILITY_SCOPES:
        return explicit
    role = _representation_role(representation)
    if role == "primary":
        return "primary_resource"
    if role == "landing":
        return "landing_page"
    if role == "metadata":
        return "metadata"
    return "representation"


def _representations(resolution: Mapping[str, Any]) -> list[dict[str, Any]]:
    resolved = _resolved_mapping(resolution)
    values = resolved.get("representations") or []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise AcquisitionPlanningError(
            "RESOLUTION_STALE", "检查结果中的资源表示无效"
        )
    return [dict(item) for item in values if isinstance(item, Mapping)]


def _selected_representation(
    resolution: Mapping[str, Any], representation_id: str | None = None
) -> dict[str, Any]:
    values = _representations(resolution)
    if representation_id:
        for item in values:
            if item.get("representation_id") == representation_id:
                return item
        raise AcquisitionPlanningError(
            "REPRESENTATION_DRIFT",
            "已确认的资源表示已经不存在，请重新检查并准备获取",
            {"representation_id": representation_id},
        )
    for key in ("selected_representation_id", "representation_id", "primary_representation_id"):
        value = resolution.get(key)
        if isinstance(value, str) and value:
            return _selected_representation(resolution, value)
    if len(values) == 1:
        return values[0]
    primaries = [
        item
        for item in values
        if _representation_scope(item) == "primary_resource"
        and _representation_role(item) == "primary"
        and bool(item.get("materializable", True))
    ]
    if len(primaries) == 1:
        return primaries[0]
    raise AcquisitionPlanningError(
        "REPRESENTATION_AMBIGUOUS",
        "当前资源有多个可获取表示，需要先明确具体资源表示",
    )


def _comparable_representation(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "representation_id",
        "scope",
        "kind",
        "role",
        "container",
        "mime_type",
        "materializable",
        "technical_availability",
        "requires_auth",
    )
    return {key: value.get(key) for key in keys if key in value}


class AcquisitionPlanner:
    def __init__(
        self,
        router: AcquisitionRouter,
        specs: Sequence[ProviderSpec] = DEFAULT_PROVIDER_SPECS,
    ) -> None:
        self.router = router
        self.specs = tuple(specs)

    def _resolve_spec(
        self,
        resource: Mapping[str, Any],
        representation: Mapping[str, Any],
    ) -> ProviderSpec:
        scope = _representation_scope(representation)
        availability = str(representation.get("technical_availability") or "available")
        if availability == "auth_required":
            raise AcquisitionPlanningError(
                "AUTH_REQUIRED", "该资源当前需要有效登录会话"
            )
        if availability in {"unavailable", "policy_blocked"}:
            raise AcquisitionPlanningError(
                "POLICY_DENIED" if availability == "policy_blocked" else "RESOURCE_UNAVAILABLE",
                "该资源当前不可获取",
            )
        for spec in self.specs:
            if spec.matches(resource, representation, scope):
                registration = self.router.provider_registry.get(
                    (spec.provider_id, spec.provider_version)
                )
                if registration is None:
                    raise AcquisitionPlanningError(
                        "PROVIDER_UNAVAILABLE",
                        "计划使用的获取提供方当前未部署",
                        {"provider_id": spec.provider_id},
                        retryable=True,
                    )
                if spec.strategy not in registration.strategies or scope not in registration.scopes:
                    raise AcquisitionPlanningError(
                        "PROVIDER_SCOPE_MISMATCH",
                        "计划使用的获取提供方不支持当前资源范围或策略",
                        {"provider_id": spec.provider_id, "scope": scope},
                    )
                return spec
        raise AcquisitionPlanningError(
            "CAPABILITY_NOT_DECLARED",
            "当前资源表示没有可执行的获取方式",
            {
                "platform": str(resource.get("platform") or "generic"),
                "kind": str(representation.get("kind") or ""),
                "scope": scope,
            },
        )

    def plan_selection(
        self,
        resources: Sequence[Mapping[str, Any]],
        resolutions: Sequence[Mapping[str, Any]],
        *,
        preferred_container: str,
    ) -> list[dict[str, Any]]:
        if len(resources) != len(resolutions):
            raise AcquisitionPlanningError(
                "RESOLUTION_STALE", "资源与检查结果数量不一致"
            )
        items: list[dict[str, Any]] = []
        for position, (resource, resolution) in enumerate(
            zip(resources, resolutions, strict=True)
        ):
            representation = _selected_representation(resolution)
            if not representation_evidence_is_fresh(representation):
                raise AcquisitionPlanningError(
                    "RESOLUTION_STALE",
                    "资源表示证据已过期，请重新检查",
                    {"resource_id": resource.get("resource_id")},
                )
            representation_id = representation.get("representation_id")
            if not isinstance(representation_id, str) or not representation_id:
                raise AcquisitionPlanningError(
                    "RESOLUTION_STALE", "资源表示缺少服务端 ID"
                )
            spec = self._resolve_spec(resource, representation)
            snapshot = dict(representation)
            representation_container = str(
                representation.get("container") or ""
            ).strip().lower()
            snapshot["selected_container"] = (
                representation_container
                if str(resource.get("platform") or "generic") == "smartedu"
                and representation_container
                else preferred_container
            )
            items.append(
                {
                    "position": position,
                    "resource_id": str(resource["resource_id"]),
                    "resolution_id": resolution.get("resolution_id"),
                    "representation_id": representation_id,
                    "planned_scope": _representation_scope(representation),
                    "strategy": spec.strategy.kind,
                    "provider_id": spec.provider_id,
                    "provider_version": spec.provider_version,
                    "source_fingerprint": _fingerprint_key(source_fingerprint(resource)),
                    "representation": snapshot,
                }
            )
        return items

    def revalidate_plan_item(
        self,
        plan_item: Mapping[str, Any],
        resource: Mapping[str, Any],
        resolution: Mapping[str, Any],
    ) -> None:
        representation_id = str(plan_item.get("representation_id") or "")
        current = _selected_representation(resolution, representation_id)
        if not representation_evidence_is_fresh(current):
            raise AcquisitionPlanningError(
                "RESOLUTION_STALE", "资源表示证据已过期，请重新检查并准备获取"
            )
        stored = plan_item.get("representation")
        if not isinstance(stored, Mapping):
            raise AcquisitionPlanningError(
                "PLAN_BINDING_CONFLICT", "下载计划缺少资源表示"
            )
        if _comparable_representation(stored) != _comparable_representation(current):
            raise AcquisitionPlanningError(
                "REPRESENTATION_DRIFT",
                "资源表示已经变化，请重新检查并准备获取",
            )
        if _fingerprint_key(plan_item.get("source_fingerprint")) != _fingerprint_key(
            source_fingerprint(resource)
        ):
            raise AcquisitionPlanningError(
                "RESOLUTION_STALE", "资源身份已经变化，请重新搜索并检查"
            )
        spec = self._resolve_spec(resource, current)
        expected = (
            str(plan_item.get("planned_scope") or ""),
            str(plan_item.get("strategy") or ""),
            str(plan_item.get("provider_id") or ""),
            str(plan_item.get("provider_version") or ""),
        )
        actual = (
            _representation_scope(current),
            spec.strategy.kind,
            spec.provider_id,
            spec.provider_version,
        )
        if expected != actual:
            raise AcquisitionPlanningError(
                "PLAN_BINDING_CONFLICT",
                "资源表示或 Provider 路由已经变化，请重新准备获取",
            )


__all__ = [
    "AcquisitionPlanner",
    "AcquisitionPlanningError",
    "DEFAULT_PROVIDER_SPECS",
    "ProviderSpec",
]
