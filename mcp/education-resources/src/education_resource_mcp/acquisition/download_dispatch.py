"""Select one current representation, choose its handler, and execute it.

This module is intentionally small. It is not a workflow planner or capability
registry: the caller already owns one logical Resource, fresh Inspect facts, and
a plain ``provider_id -> handler`` mapping.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..downloader import DownloadBatchResult, DownloadItemFailure, DownloadResult
from ..errors import DomainError
from ..policy import ensure_within_root
from .models import (
    AcquisitionItemFailure,
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
)


_DOCUMENT_CONTAINERS = frozenset(
    {"pdf", "epub", "doc", "docx", "ppt", "pptx", "txt", "rtf", "odt", "zip"}
)


class DownloadDispatchError(ValueError):
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
        raise DownloadDispatchError("RESOURCE_UNAVAILABLE", "检查结果没有可下载资源")

    values = [
        dict(item)
        for item in raw
        if isinstance(item, Mapping) and bool(item.get("materializable", True))
    ]
    if not values:
        raise DownloadDispatchError("RESOURCE_UNAVAILABLE", "资源当前没有可下载表示")

    primaries = [item for item in values if _scope(item) == "primary_resource"]
    pool = primaries or values
    if preferred_container == "original":
        if len(pool) == 1:
            return pool[0]
        raise DownloadDispatchError(
            "REPRESENTATION_AMBIGUOUS",
            "资源存在多个主表示，无法自动确定自然交付入口",
        )

    wanted = preferred_container.strip().lower()
    matching = [
        item
        for item in pool
        if str(item.get("container") or "").strip().lower() == wanted
    ]
    if len(matching) == 1:
        return matching[0]
    if not matching:
        raise DownloadDispatchError(
            "REPRESENTATION_UNAVAILABLE",
            f"资源没有可用的 {preferred_container} 主表示",
        )
    raise DownloadDispatchError(
        "REPRESENTATION_AMBIGUOUS",
        f"资源存在多个 {preferred_container} 主表示，无法自动选择",
    )


def _handler_id(
    resource: Mapping[str, Any], representation: Mapping[str, Any], scope: str
) -> tuple[AcquisitionStrategy, str] | None:
    """Map current resource facts directly to one concrete handler id."""

    platform = str(resource.get("platform") or "generic")
    resource_type = str(resource.get("resource_type") or "other")
    kind = str(representation.get("kind") or "")
    role = _role(representation)
    container = str(representation.get("container") or "").strip().lower()

    if platform == "smartedu" and scope == "primary_resource" and role == "primary":
        if kind == "document" and container == "pdf" and resource_type in {
            "book", "course", "document", "other"
        }:
            return AcquisitionStrategy.DIRECT_FILE, "smartedu-resource"
        if kind == "video" and container in {"mp4", "m3u8"} and resource_type in {
            "course", "video"
        }:
            return AcquisitionStrategy.DIRECT_FILE, "smartedu-resource"
        if kind == "audio" and container in {"mp3", "m4a"} and resource_type in {
            "audio", "course"
        }:
            return AcquisitionStrategy.DIRECT_FILE, "smartedu-resource"

    if platform == "douyin" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return AcquisitionStrategy.DIRECT_FILE, "douyin-video"

    if platform == "ximalaya" and scope == "primary_resource" and role == "primary":
        if kind == "audio" and container in {"mp3", "m4a"} and resource_type == "audio":
            return AcquisitionStrategy.DIRECT_FILE, "ximalaya-audio"

    if platform == "bilibili" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return AcquisitionStrategy.DIRECT_FILE, "bilibili-video"

    if platform == "yixi" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return AcquisitionStrategy.DIRECT_FILE, "generic-direct"

    if platform == "cctv" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return AcquisitionStrategy.DIRECT_FILE, "cctv-video"

    if platform == "zjer" and scope == "primary_resource" and role == "primary":
        if kind == "video" and container == "mp4" and resource_type == "video":
            return AcquisitionStrategy.DIRECT_FILE, "zjer-video"

    if platform == "libgen" and scope == "primary_resource" and role == "primary":
        if kind == "document" and resource_type in {"book", "document"}:
            return AcquisitionStrategy.DIRECT_FILE, "libgen"

    if platform == "zlibrary" and scope == "primary_resource" and role == "primary":
        if kind == "document" and resource_type in {"book", "document"}:
            return AcquisitionStrategy.DIRECT_FILE, "zlibrary"

    if platform == "shuge" and scope == "primary_resource" and role == "primary":
        if (
            kind == "document"
            and container in _DOCUMENT_CONTAINERS
            and resource_type in {"book", "document", "other"}
        ):
            return AcquisitionStrategy.DIRECT_FILE, "generic-direct"

    if platform == "generic" and scope == "primary_resource" and role == "primary":
        if kind == "document" and container in _DOCUMENT_CONTAINERS and resource_type in {
            "article", "book", "course", "dataset", "document", "other"
        }:
            return AcquisitionStrategy.DIRECT_FILE, "generic-direct"
        if kind == "video" and container == "mp4" and resource_type in {"course", "video"}:
            return AcquisitionStrategy.DIRECT_FILE, "generic-direct"
        if kind == "webpage" and container == "html" and resource_type in {
            "article", "course", "dataset", "document", "other"
        }:
            return AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer"

    if platform == "generic" and scope == "landing_page" and role == "landing":
        if kind == "webpage" and container == "html":
            return AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer"

    if platform == "zhihu" and kind == "webpage" and container in {
        "", "article", "webpage", "html"
    }:
        if scope in {"primary_resource", "landing_page"} and role in {"primary", "landing"}:
            return AcquisitionStrategy.WEB_MATERIALIZE, "generic-web-materializer"

    return None


def select_download_handler(
    resource: Mapping[str, Any],
    resolution: Mapping[str, Any],
    *,
    preferred_container: str,
    handlers: Mapping[str, Any],
) -> dict[str, Any]:
    """Choose one representation and one already-instantiated handler."""

    representation = _choose_representation(resolution, preferred_container)
    availability = str(representation.get("technical_availability") or "available")
    if availability == "auth_required":
        raise DownloadDispatchError("AUTH_REQUIRED", "该资源需要有效登录会话")
    if availability in {"unavailable", "policy_blocked"}:
        raise DownloadDispatchError(
            "POLICY_DENIED" if availability == "policy_blocked" else "RESOURCE_UNAVAILABLE",
            "该资源当前不可下载",
        )

    scope = _scope(representation)
    selected = _handler_id(resource, representation, scope)
    if selected is None:
        raise DownloadDispatchError(
            "CAPABILITY_NOT_DECLARED",
            "当前资源没有可用下载器",
            {
                "platform": str(resource.get("platform") or "generic"),
                "kind": str(representation.get("kind") or ""),
                "scope": scope,
            },
        )

    strategy, provider_id = selected
    if provider_id not in handlers:
        raise DownloadDispatchError(
            "PROVIDER_UNAVAILABLE",
            f"下载器 {provider_id} 当前未部署",
            retryable=True,
        )

    representation_id = str(representation.get("representation_id") or "")
    if not representation_id:
        raise DownloadDispatchError("RESOURCE_UNAVAILABLE", "资源表示缺少 ID")

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


def dispatch_download(
    handlers: Mapping[str, Any], request: AcquisitionRequest
) -> AcquisitionResult:
    """Execute the selected handler and normalize its real file result."""

    if request.cancel_event.is_set():
        return AcquisitionResult.failed(
            request.strategy, "JOB_CANCELLED", "任务已取消"
        )

    handler = handlers.get(request.provider_id)
    if handler is None:
        return AcquisitionResult.failed(
            request.strategy,
            "PROVIDER_UNAVAILABLE",
            f"下载器 {request.provider_id} 当前未部署",
            retryable=True,
        )

    try:
        if request.strategy is AcquisitionStrategy.DIRECT_FILE:
            raw = handler.download(
                request.mutable_resource(),
                request.job_id,
                "direct",
                request.cancel_event,
            )
            return _normalize_direct_result(request, raw)

        if request.strategy is AcquisitionStrategy.WEB_MATERIALIZE:
            result = handler.materialize(request)
            return _validate_materialized_result(request, result)
    except DomainError as exc:
        return AcquisitionResult.failed(
            request.strategy,
            exc.code,
            exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )
    except Exception as exc:
        return AcquisitionResult.failed(
            request.strategy,
            "DOWNLOAD_FAILED",
            f"{type(exc).__name__}: {exc}",
        )

    return AcquisitionResult.failed(
        request.strategy,
        "UNSUPPORTED_ACQUISITION_STRATEGY",
        "当前获取方式不支持",
    )


def _normalize_direct_result(
    request: AcquisitionRequest,
    raw: DownloadResult | Sequence[DownloadResult] | DownloadBatchResult,
) -> AcquisitionResult:
    if isinstance(raw, DownloadResult):
        results = [raw]
        failures: Sequence[DownloadItemFailure] = ()
    elif isinstance(raw, DownloadBatchResult):
        results = list(raw.results)
        failures = raw.failures
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        results = list(raw)
        failures = ()
    else:
        raise TypeError("download provider returned an unsupported result")

    item_failures = tuple(
        AcquisitionItemFailure(
            item_key=failure.item_key,
            code=failure.code,
            message=failure.message,
            role=failure.role,
            required=failure.required,
            retryable=failure.retryable,
            details=dict(failure.details),
            metadata=dict(failure.metadata),
        )
        for failure in failures
    )

    artifacts: list[Artifact] = []
    resource_key = request.resource_id or "resource"
    for index, result in enumerate(results):
        if not isinstance(result, DownloadResult):
            raise TypeError("download provider returned an invalid item")
        path = _output_file(result.path, request.jobs_root)
        role = result.role or ("primary" if index == 0 else "attachment")
        artifacts.append(
            Artifact(
                artifact_id=f"{request.job_id}:{resource_key}:artifact:{index}",
                role=role,
                primary=role == "primary",
                path=path,
                byte_size=result.byte_size,
                media_type=result.media_type,
                sha256=result.sha256,
                filename=result.filename or path.name,
                metadata=dict(result.metadata),
                required=bool(result.required),
                item_key=result.item_key,
            )
        )

    if not artifacts:
        if item_failures:
            first = item_failures[0]
            return AcquisitionResult.failed(
                request.strategy,
                first.code,
                first.message,
                retryable=first.retryable,
                details=first.details,
                item_failures=item_failures,
            )
        return AcquisitionResult.failed(
            request.strategy, "DOWNLOAD_FAILED", "下载器没有产生文件"
        )

    return AcquisitionResult.success(
        request.strategy,
        ArtifactBundle(tuple(artifacts)),
        item_failures=item_failures,
        completion="partial" if item_failures else "complete",
    )


def _validate_materialized_result(
    request: AcquisitionRequest, result: AcquisitionResult
) -> AcquisitionResult:
    if not isinstance(result, AcquisitionResult):
        raise TypeError("materializer returned an invalid result")
    if not result.ok or result.bundle is None:
        return result
    for artifact in result.bundle.artifacts:
        _output_file(artifact.path, request.jobs_root)
    return result


def _output_file(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    ensure_within_root(resolved, root.resolve())
    if not resolved.is_file():
        raise ValueError("provider did not create a file")
    return resolved


__all__ = [
    "DownloadDispatchError",
    "dispatch_download",
    "select_download_handler",
]
