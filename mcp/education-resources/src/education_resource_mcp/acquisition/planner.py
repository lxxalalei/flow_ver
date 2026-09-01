"""Select one current representation and its concrete download handler."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def _role(representation: Mapping[str, Any]) -> str:
    role = str(representation.get("role") or "").strip().lower()
    if role:
        return role
    return "landing" if str(representation.get("kind") or "") == "webpage" else "primary"


def _scope(representation: Mapping[str, Any]) -> str:
    scope = str(representation.get("scope") or "").strip()
    if scope:
        return scope
    return "landing_page" if _role(representation) == "landing" else "primary_resource"


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
        item
        for item in pool
        if str(item.get("container") or "").strip().lower()
        == preferred_container.strip().lower()
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


def _direct(provider_id: str) -> tuple[AcquisitionStrategy, str]:
    return AcquisitionStrategy.DIRECT_FILE, provider_id


def _web(provider_id: str) -> tuple[AcquisitionStrategy, str]:
    return AcquisitionStrategy.WEB_MATERIALIZE, provider_id


def _handler_for(
    resource: Mapping[str, Any], representation: Mapping[str, Any], scope: str
) -> tuple[AcquisitionStrategy, str] | None:
    """Map real resource facts directly to one deployed handler id.

    This is intentionally explicit. There is no second capability registry or
    generic rule object: platform-specific differences stay visible here.
    """

    platform = str(resource.get("platform") or "generic")
    resource_type = str(resource.get("resource_type") or "other")
    kind = str(representation.get("kind") or "")
    role = _role(representation)
    container = str(representation.get("container") or "").strip().lower()

    if not bool(representation.get("materializable", True)):
        return None

    if platform == "smartedu" and scope == "primary_resource" and role == "primary":
        if kind == "document" and container == "pdf" and resource_type in {
            "book", "course", "document", "other"
        }:
            return _direct("smartedu-resource")
        if kind == "video" and container in {"mp4", "m3u8"} and resource_type in {
            "course", "video"
        }:
            return _direct("smartedu-resource")
        if kind == "audio" and container in {"mp3", "m4a"} and resource_type in {
            "audio", "course"
        }:
            return _direct("smartedu-resource")

    if platform == "douyin" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return _direct("douyin-video")

    if platform == "ximalaya" and scope == "primary_resource" and role == "primary":
        if kind == "audio" and container in {"mp3", "m4a"} and resource_type == "audio":
            return _direct("ximalaya-audio")

    if platform == "bilibili" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return _direct("bilibili-video")

    if platform == "yixi" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return _direct("generic-direct")

    if platform == "cctv" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return _direct("cctv-video")

    if platform == "zjer" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return _direct("zjer-video")

    if platform == "libgen" and scope == "primary_resource" and role == "primary":
        if kind == "document" and resource_type in {"book", "document"}:
            return _direct("libgen")

    if platform == "zlibrary" and scope == "primary_resource" and role == "primary":
        if kind == "document" and resource_type in {"book", "document"}:
            return _direct("zlibrary")

    if platform == "shuge" and scope == "primary_resource" and role == "primary":
        if (
            kind == "document"
            and container in _DOCUMENT_CONTAINERS
            and resource_type in {"book", "document", "other"}
        ):
            return _direct("generic-direct")

    if platform == "generic" and scope == "primary_resource" and role == "primary":
        if kind == "document" and container in _DOCUMENT_CONTAINERS and resource_type in {
            "article", "book", "course", "dataset", "document", "other"
        }:
            return _direct("generic-direct")
        if kind == "video" and container == "mp4" and resource_type in {"course", "video"}:
            return _direct("generic-direct")
        if kind == "webpage" and container == "html" and resource_type in {
            "article", "course", "dataset", "document", "other"
        }:
            return _web("generic-web-materializer")

    if platform == "generic" and scope == "landing_page" and role == "landing":
        if kind == "webpage" and container == "html":
            return _web("generic-web-materializer")

    if platform == "zhihu" and kind == "webpage" and container in {
        "", "article", "webpage", "html"
    }:
        if scope in {"primary_resource", "landing_page"} and role in {"primary", "landing"}:
            return _web("generic-web-materializer")

    return None


class AcquisitionPlanner:
    """Choose a representation and its concrete handler; no workflow planning."""

    def __init__(self, router: AcquisitionRouter) -> None:
        self.router = router

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
        selected = _handler_for(resource, representation, scope)
        if selected is None:
            raise AcquisitionPlanningError(
                "CAPABILITY_NOT_DECLARED",
                "当前资源没有可用下载器",
                {
                    "platform": str(resource.get("platform") or "generic"),
                    "kind": str(representation.get("kind") or ""),
                    "scope": scope,
                },
            )

        strategy, provider_id = selected
        if provider_id not in self.router.provider_registry:
            raise AcquisitionPlanningError(
                "PROVIDER_UNAVAILABLE",
                f"下载器 {provider_id} 当前未部署",
                retryable=True,
            )

        representation_id = str(representation.get("representation_id") or "")
        if not representation_id:
            raise AcquisitionPlanningError("RESOURCE_UNAVAILABLE", "资源表示缺少 ID")
        actual_container = str(representation.get("container") or "").strip().lower()
        return {
            "strategy": strategy.kind,
            "provider_id": provider_id,
            "scope": scope,
            "representation_id": representation_id,
            "container": (
                actual_container
                if str(resource.get("platform") or "") == "smartedu" and actual_container
                else preferred_container
            ),
        }


__all__ = ["AcquisitionPlanner", "AcquisitionPlanningError"]
