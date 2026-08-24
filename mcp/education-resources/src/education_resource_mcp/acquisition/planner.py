"""Choose one concrete downloader for a freshly inspected resource."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import AcquisitionStrategy
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
    containers: frozenset[str] = frozenset()
    resource_types: frozenset[str] = frozenset()

    def matches(
        self,
        resource: Mapping[str, Any],
        representation: Mapping[str, Any],
        scope: str,
    ) -> bool:
        if str(resource.get("platform") or "generic") != self.platform_id:
            return False
        if scope != self.scope:
            return False
        if str(representation.get("kind") or "") != self.representation_kind:
            return False
        if _role(representation) != self.role:
            return False
        container = str(representation.get("container") or "").strip().lower()
        if self.containers and container and container not in self.containers:
            return False
        resource_type = str(resource.get("resource_type") or "other")
        if self.resource_types and resource_type not in self.resource_types:
            return False
        return bool(representation.get("materializable", True))


DEFAULT_PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "smartedu", "primary_resource", "document", "primary",
        AcquisitionStrategy.DIRECT_FILE, "smartedu-resource",
        frozenset({"pdf"}), frozenset({"book", "course", "document", "other"}),
    ),
    ProviderSpec(
        "smartedu", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "smartedu-resource",
        frozenset({"mp4", "m3u8"}), frozenset({"course", "video"}),
    ),
    ProviderSpec(
        "smartedu", "primary_resource", "audio", "primary",
        AcquisitionStrategy.DIRECT_FILE, "smartedu-resource",
        frozenset({"mp3", "m4a"}), frozenset({"audio", "course"}),
    ),
    ProviderSpec(
        "douyin", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "douyin-video",
        frozenset({"mp4"}), frozenset({"video"}),
    ),
    ProviderSpec(
        "ximalaya", "primary_resource", "audio", "primary",
        AcquisitionStrategy.DIRECT_FILE, "ximalaya-audio",
        frozenset({"mp3", "m4a"}), frozenset({"audio"}),
    ),
    ProviderSpec(
        "bilibili", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "bilibili-video",
        frozenset({"mp4"}), frozenset({"video"}),
    ),
    ProviderSpec(
        "yixi", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "generic-direct",
        frozenset({"mp4"}), frozenset({"video"}),
    ),
    ProviderSpec(
        "cctv", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "cctv-video",
        frozenset({"mp4"}), frozenset({"video"}),
    ),
    ProviderSpec(
        "zjer", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "zjer-video",
        frozenset({"mp4"}), frozenset({"video"}),
    ),
    ProviderSpec(
        "libgen", "primary_resource", "document", "primary",
        AcquisitionStrategy.DIRECT_FILE, "libgen",
        frozenset(), frozenset({"book", "document"}),
    ),
    ProviderSpec(
        "shuge", "primary_resource", "document", "primary",
        AcquisitionStrategy.DIRECT_FILE, "generic-direct",
        _DOCUMENT_CONTAINERS, frozenset({"book", "document", "other"}),
    ),
    ProviderSpec(
        "generic", "primary_resource", "document", "primary",
        AcquisitionStrategy.DIRECT_FILE, "generic-direct",
        _DOCUMENT_CONTAINERS,
        frozenset({"article", "book", "course", "dataset", "document", "other"}),
    ),
    ProviderSpec(
        "generic", "primary_resource", "video", "primary",
        AcquisitionStrategy.DIRECT_FILE, "generic-direct",
        frozenset({"mp4"}), frozenset({"course", "video"}),
    ),
    ProviderSpec(
        "generic", "primary_resource", "webpage", "primary",
        AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer",
        frozenset({"html"}),
        frozenset({"article", "course", "dataset", "document", "other"}),
    ),
    ProviderSpec(
        "generic", "landing_page", "webpage", "landing",
        AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer",
        frozenset({"html"}), frozenset(),
    ),
    ProviderSpec(
        "zhihu", "primary_resource", "webpage", "primary",
        AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer",
        frozenset({"article", "webpage", "html"}), frozenset(),
    ),
    ProviderSpec(
        "zhihu", "landing_page", "webpage", "landing",
        AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer",
        frozenset({"article", "webpage", "html"}), frozenset(),
    ),
)


def _role(representation: Mapping[str, Any]) -> str:
    role = str(representation.get("role") or "").strip().lower()
    if role:
        return role
    return "landing" if str(representation.get("kind") or "") == "webpage" else "primary"


def _scope(representation: Mapping[str, Any]) -> str:
    scope = str(representation.get("scope") or "").strip()
    if scope:
        return scope
    role = _role(representation)
    if role == "primary":
        return "primary_resource"
    if role == "landing":
        return "landing_page"
    if role == "metadata":
        return "metadata"
    return "representation"


def _choose_representation(
    resolution: Mapping[str, Any], preferred_container: str
) -> dict[str, Any]:
    resolved = resolution.get("resolved_resource")
    if not isinstance(resolved, Mapping):
        resolved = resolution
    raw = resolved.get("representations") or []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise AcquisitionPlanningError("RESOURCE_UNAVAILABLE", "检查结果没有可下载资源")
    values = [
        dict(item)
        for item in raw
        if isinstance(item, Mapping) and bool(item.get("materializable", True))
    ]
    if not values:
        raise AcquisitionPlanningError("RESOURCE_UNAVAILABLE", "资源当前没有可下载表示")

    primaries = [item for item in values if _scope(item) == "primary_resource"]
    pool = primaries or values

    if preferred_container == "original":
        if len(pool) == 1:
            return pool[0]
        raise AcquisitionPlanningError(
            "REPRESENTATION_AMBIGUOUS",
            "资源存在多个主表示，无法自动确定自然交付入口",
        )

    matching = [
        item for item in pool
        if str(item.get("container") or "").lower() == preferred_container.lower()
    ]
    if len(matching) == 1:
        return matching[0]
    if not matching:
        raise AcquisitionPlanningError(
            "REPRESENTATION_UNAVAILABLE",
            f"资源没有可用的 {preferred_container} 主表示",
        )
    raise AcquisitionPlanningError(
        "REPRESENTATION_AMBIGUOUS",
        f"资源存在多个 {preferred_container} 主表示，无法自动选择",
    )


class AcquisitionPlanner:
    def __init__(
        self,
        router: AcquisitionRouter,
        specs: Sequence[ProviderSpec] = DEFAULT_PROVIDER_SPECS,
    ) -> None:
        self.router = router
        self.specs = tuple(specs)

    def route(
        self,
        resource: Mapping[str, Any],
        resolution: Mapping[str, Any],
        *,
        preferred_container: str = "original",
    ) -> dict[str, Any]:
        representation = _choose_representation(resolution, preferred_container)
        availability = str(representation.get("technical_availability") or "available")
        if availability == "auth_required":
            raise AcquisitionPlanningError("AUTH_REQUIRED", "该资源需要有效登录会话")
        if availability in {"unavailable", "policy_blocked"}:
            raise AcquisitionPlanningError(
                "POLICY_DENIED" if availability == "policy_blocked" else "RESOURCE_UNAVAILABLE",
                "该资源当前不可下载",
            )

        scope = _scope(representation)
        for spec in self.specs:
            if not spec.matches(resource, representation, scope):
                continue
            registration = self.router.provider_registry.get(spec.provider_id)
            if registration is None:
                raise AcquisitionPlanningError(
                    "PROVIDER_UNAVAILABLE",
                    f"下载器 {spec.provider_id} 当前未部署",
                    retryable=True,
                )
            if spec.strategy not in registration.strategies or scope not in registration.scopes:
                continue
            representation_id = str(representation.get("representation_id") or "")
            if not representation_id:
                raise AcquisitionPlanningError("RESOURCE_UNAVAILABLE", "资源表示缺少 ID")
            container = str(representation.get("container") or "").strip().lower()
            return {
                "strategy": spec.strategy.kind,
                "provider_id": spec.provider_id,
                "scope": scope,
                "representation_id": representation_id,
                "container": (
                    container
                    if spec.platform_id == "smartedu" and container
                    else preferred_container
                ),
            }

        raise AcquisitionPlanningError(
            "CAPABILITY_NOT_DECLARED",
            "当前资源没有可用下载器",
            {
                "platform": str(resource.get("platform") or "generic"),
                "kind": str(representation.get("kind") or ""),
                "scope": scope,
            },
        )


__all__ = [
    "AcquisitionPlanner",
    "AcquisitionPlanningError",
    "DEFAULT_PROVIDER_SPECS",
    "ProviderSpec",
]
