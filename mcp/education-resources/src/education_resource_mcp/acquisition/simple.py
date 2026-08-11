"""Simplified exact-provider acquisition seam.

This module keeps the useful part of the old acquisition boundary — an exact
Provider chosen by a server-authored Plan — without carrying descriptor,
readiness, eligibility, or binding-digest credentials into Provider calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import copy
import threading
from typing import Any

from .models import AcquisitionRequest as _LegacyAcquisitionRequest
from .models import AcquisitionResult, AcquisitionStrategy, CAPABILITY_SCOPES
from .router import AcquisitionRouter as _LegacyAcquisitionRouter
from .router import ProviderRegistration


class AcquisitionRequest(_LegacyAcquisitionRequest):
    """Compatibility subtype exposing only business execution facts.

    Existing Providers that still perform ``isinstance(..., AcquisitionRequest)``
    continue to work because this is a subtype of the previous request class.
    The old authority fields are populated with inert compatibility values and
    are never persisted, validated, or exposed to the Provider-facing dict.
    """

    __slots__ = ()

    def __init__(
        self,
        *,
        job_id: str,
        resource: Mapping[str, Any],
        strategy: AcquisitionStrategy | str,
        provider_id: str,
        provider_version: str,
        planned_scope: str,
        representation_id: str,
        preferred_container: str = "original",
        cancel_event: threading.Event | None = None,
        jobs_root: Path | None = None,
        binding_digest: Any = None,
        source_fingerprint: Any = None,
        capability_id: Any = None,
        descriptor_version: Any = None,
        descriptor_digest: Any = None,
        readiness_snapshot_id: Any = None,
        readiness_digest: Any = None,
        eligibility_id: Any = None,
        eligibility_digest: Any = None,
    ) -> None:
        del (
            binding_digest,
            source_fingerprint,
            capability_id,
            descriptor_version,
            descriptor_digest,
            readiness_snapshot_id,
            readiness_digest,
            eligibility_id,
            eligibility_digest,
        )
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty server identifier")
        if not isinstance(resource, Mapping):
            raise TypeError("resource must be a mapping")
        resource_id = resource.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError("resource must contain resource_id")
        selected_strategy = AcquisitionStrategy.from_value(strategy)
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be non-empty")
        if not isinstance(provider_version, str) or not provider_version:
            raise ValueError("provider_version must be non-empty")
        if planned_scope not in CAPABILITY_SCOPES:
            raise ValueError("planned_scope must be a declared acquisition scope")
        if not isinstance(representation_id, str) or not representation_id:
            raise ValueError("representation_id must be non-empty")
        if preferred_container not in {
            "original", "pdf", "epub", "mp4", "mp3", "html", "text"
        }:
            raise ValueError("unsupported preferred container")
        event = cancel_event or threading.Event()
        if not isinstance(event, threading.Event):
            raise TypeError("cancel_event must be threading.Event")
        if not isinstance(jobs_root, Path):
            raise TypeError("jobs_root must be a server-provided pathlib.Path")
        resolved_root = jobs_root.resolve(strict=False)
        if not resolved_root.is_absolute() or ".." in resolved_root.parts:
            raise ValueError("jobs_root must be an absolute server-controlled root")

        # Base dataclass slots are assigned directly; its old __post_init__ is
        # intentionally not called because the deleted authority credentials
        # are not part of the new runtime contract.
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "resource", copy.deepcopy(dict(resource)))
        object.__setattr__(self, "strategy", selected_strategy)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "provider_version", provider_version)
        object.__setattr__(self, "planned_scope", planned_scope)
        object.__setattr__(self, "representation_id", representation_id)
        object.__setattr__(self, "binding_digest", "")
        object.__setattr__(self, "source_fingerprint", "")
        object.__setattr__(self, "capability_id", "")
        object.__setattr__(self, "descriptor_version", "")
        object.__setattr__(self, "descriptor_digest", "")
        object.__setattr__(self, "readiness_snapshot_id", "")
        object.__setattr__(self, "readiness_digest", "")
        object.__setattr__(self, "eligibility_id", "")
        object.__setattr__(self, "eligibility_digest", "")
        object.__setattr__(self, "preferred_container", preferred_container)
        object.__setattr__(self, "cancel_event", event)
        object.__setattr__(self, "jobs_root", resolved_root)

    @property
    def resource_id(self) -> str:
        return str(self.resource["resource_id"])

    def mutable_resource(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.resource))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "resource_id": self.resource_id,
            "strategy": self.strategy.kind,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "planned_scope": self.planned_scope,
            "representation_id": self.representation_id,
            "preferred_container": self.preferred_container,
        }


class AcquisitionRouter(_LegacyAcquisitionRouter):
    """Exact routing without capability-authority credentials."""

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        if not isinstance(request, AcquisitionRequest):
            raise TypeError("router.acquire expects AcquisitionRequest")
        if request.cancel_event.is_set():
            return self._planned_failure(request, "JOB_CANCELLED", "获取任务已取消")

        registration, failure = self._resolve_registration(request)
        if failure is not None:
            return failure
        assert registration is not None
        provider = registration.provider
        if request.strategy is AcquisitionStrategy.DIRECT_FILE:
            result = self._call_download_provider(
                request,
                provider,  # type: ignore[arg-type]
                provider_strategy="direct",
                result_strategy=AcquisitionStrategy.DIRECT_FILE,
                provider_id=registration.provider_id,
            )
        elif request.strategy is AcquisitionStrategy.WEB_MATERIALIZE:
            result = self._call_result_provider(
                request,
                provider,  # type: ignore[arg-type]
                strategy=AcquisitionStrategy.WEB_MATERIALIZE,
                method_name="materialize",
                provider_id=registration.provider_id,
            )
        elif request.strategy is AcquisitionStrategy.WEB_CAPTURE:
            if callable(getattr(provider, "capture", None)):
                result = self._call_result_provider(
                    request,
                    provider,  # type: ignore[arg-type]
                    strategy=AcquisitionStrategy.WEB_CAPTURE,
                    method_name="capture",
                    provider_id=registration.provider_id,
                )
            elif callable(getattr(provider, "download", None)):
                result = self._call_download_provider(
                    request,
                    provider,  # type: ignore[arg-type]
                    provider_strategy="webpage",
                    result_strategy=AcquisitionStrategy.WEB_CAPTURE,
                    provider_id=registration.provider_id,
                )
            else:
                result = AcquisitionResult.failed(
                    request.strategy,
                    "PROVIDER_UNAVAILABLE",
                    "已绑定的网页捕获器不可用",
                )
        else:  # pragma: no cover
            result = AcquisitionResult.failed(
                request.strategy,
                "UNSUPPORTED_ACQUISITION_STRATEGY",
                "不支持的获取策略",
            )
        return self._bind_result(request, registration, result)

    @staticmethod
    def _authority_kwargs(
        request: AcquisitionRequest,
        registration: ProviderRegistration | None = None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "planned_provider_id": request.provider_id,
            "planned_provider_version": request.provider_version,
            "planned_scope": request.planned_scope,
            "representation_id": request.representation_id,
        }
        if registration is not None:
            values.update(
                {
                    "provider_id": registration.provider_id,
                    "provider_version": registration.provider_version,
                    "actual_scope": request.planned_scope,
                }
            )
        return values


__all__ = ["AcquisitionRequest", "AcquisitionRouter"]
