"""Direct dispatch from a chosen provider id to its downloader."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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


class DirectProvider(Protocol):
    def download(self, resource, job_id, strategy, cancel_event): ...


class WebMaterializer(Protocol):
    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult: ...


class BrowserCapture(Protocol):
    def capture(self, request: AcquisitionRequest) -> AcquisitionResult: ...


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    provider_id: str
    provider: Any
    strategies: Iterable[AcquisitionStrategy | str]
    scopes: Iterable[str]

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id or "").strip()
        if not provider_id:
            raise ValueError("provider_id is required")
        strategies = frozenset(
            AcquisitionStrategy.from_value(value) for value in self.strategies
        )
        scopes = frozenset(str(value) for value in self.scopes)
        if not strategies or not scopes:
            raise ValueError("provider registration requires strategy and scope")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "strategies", strategies)
        object.__setattr__(self, "scopes", scopes)


class AcquisitionRouter:
    """Call exactly the provider selected by ``AcquisitionPlanner.route``."""

    def __init__(self, registrations: Iterable[ProviderRegistration]) -> None:
        registry: dict[str, ProviderRegistration] = {}
        for registration in registrations:
            if registration.provider_id in registry:
                raise ValueError(f"duplicate provider: {registration.provider_id}")
            registry[registration.provider_id] = registration
        self._provider_registry = registry

    @property
    def provider_registry(self) -> Mapping[str, ProviderRegistration]:
        return self._provider_registry

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        if request.cancel_event.is_set():
            return AcquisitionResult.failed(
                request.strategy, "JOB_CANCELLED", "任务已取消"
            )
        registration = self._provider_registry.get(request.provider_id)
        if registration is None:
            return AcquisitionResult.failed(
                request.strategy,
                "PROVIDER_UNAVAILABLE",
                f"下载器 {request.provider_id} 当前未部署",
                retryable=True,
            )
        if request.strategy not in registration.strategies or request.scope not in registration.scopes:
            return AcquisitionResult.failed(
                request.strategy,
                "CAPABILITY_NOT_DECLARED",
                f"下载器 {request.provider_id} 不支持当前资源",
            )

        try:
            if request.strategy is AcquisitionStrategy.DIRECT_FILE:
                raw = registration.provider.download(
                    request.mutable_resource(),
                    request.job_id,
                    "direct",
                    request.cancel_event,
                )
                return self._from_download_result(request, raw)
            if request.strategy is AcquisitionStrategy.WEB_MATERIALIZE:
                result = registration.provider.materialize(request)
                return self._check_materialized_result(request, result)
            if request.strategy is AcquisitionStrategy.WEB_CAPTURE:
                capture = getattr(registration.provider, "capture", None)
                if not callable(capture):
                    return AcquisitionResult.failed(
                        request.strategy,
                        "PROVIDER_UNAVAILABLE",
                        "网页捕获器不可用",
                    )
                result = capture(request)
                return self._check_materialized_result(request, result)
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

    def _from_download_result(
        self,
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
            path = self._output_file(result.path, request.jobs_root)
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

    def _check_materialized_result(
        self,
        request: AcquisitionRequest,
        result: AcquisitionResult,
    ) -> AcquisitionResult:
        if not isinstance(result, AcquisitionResult):
            raise TypeError("materializer returned an invalid result")
        if not result.ok or result.bundle is None:
            return result
        for artifact in result.bundle.artifacts:
            self._output_file(artifact.path, request.jobs_root)
        return result

    @staticmethod
    def _output_file(path: Path, root: Path) -> Path:
        resolved = path.resolve()
        ensure_within_root(resolved, root.resolve())
        if not resolved.is_file():
            raise ValueError("provider did not create a file")
        return resolved


__all__ = [
    "AcquisitionRouter",
    "BrowserCapture",
    "DirectProvider",
    "ProviderRegistration",
    "WebMaterializer",
]
