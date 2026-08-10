"""Exact-provider acquisition router and bounded legacy provider adapters.

The router is the enforcement point between a server-authored plan binding and
an implementation provider.  It resolves exactly the ``provider_id`` and
``provider_version`` attached to an :class:`AcquisitionRequest`; resource
platform names never participate in routing and no second provider is tried.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Any, Protocol

from ..downloader import DownloadBatchResult, DownloadItemFailure, DownloadResult
from ..errors import DomainError
from ..policy import PolicyViolation, ensure_within_root
from .models import (
    CAPABILITY_SCOPES,
    MAX_ARTIFACTS,
    AcquisitionItemFailure,
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
    PERSISTENT_ARTIFACT_ROLES,
)


class DirectProvider(Protocol):
    """The legacy bounded downloader shape used by direct/capture adapters."""

    def download(
        self,
        resource: Mapping[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult | list[DownloadResult] | DownloadBatchResult:
        ...


class WebMaterializer(Protocol):
    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult:
        ...


class BrowserCapture(Protocol):
    def capture(self, request: AcquisitionRequest) -> AcquisitionResult:
        ...

    # An explicitly registered legacy rendering downloader may use only this
    # direct protocol for WEB_CAPTURE.  It remains the same exact provider.
    def download(
        self,
        resource: Mapping[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult | list[DownloadResult] | DownloadBatchResult:
        ...


_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_COMPONENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REDACTED_DETAIL_KEYS = {
    "path",
    "file",
    "filename",
    "destination",
    "url",
    "source_url",
    "cookie",
    "token",
    "access_token",
    "authorization",
    "password",
    "secret",
    "headers",
    "request_headers",
    "response_body",
    "body",
}
_REDACTED_DETAIL_PARTS = {
    "url",
    "uri",
    "token",
    "cookie",
    "password",
    "secret",
    "authorization",
    "filename",
    "filepath",
    "destination",
}
# Provider-owned metadata cannot claim router authority facts.  The result
# exposes authoritative values in dedicated top-level fields instead.
_AUTHORITY_METADATA_KEYS = frozenset(
    {
        "provider",
        "provider_id",
        "provider_version",
        "planned_provider",
        "planned_scope",
        "actual_scope",
        "representation_id",
        "binding_digest",
        "source_fingerprint",
        "fallback",
        "fallback_chain",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """An explicitly deployable exact provider binding.

    A registration declares every acquisition strategy and capability scope it
    can execute.  The router will only select an entry by its exact immutable
    ``(provider_id, provider_version)`` key; it never derives a provider from
    ``resource.platform`` or substitutes another registration after failure.
    """

    provider_id: str
    provider_version: str
    provider: DirectProvider | WebMaterializer | BrowserCapture
    strategies: Iterable[AcquisitionStrategy | str]
    scopes: Iterable[str]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not _PROVIDER_ID_PATTERN.fullmatch(
            self.provider_id
        ):
            raise ValueError("provider_id must be a valid provider identifier")
        if not isinstance(self.provider_version, str) or not _COMPONENT_VERSION_PATTERN.fullmatch(
            self.provider_version
        ):
            raise ValueError("provider_version must be a valid component version")
        if self.provider is None:
            raise TypeError("provider registration requires a provider")
        if isinstance(self.strategies, (str, bytes)):
            raise TypeError("registration strategies must be an iterable of strategies")
        try:
            strategies = frozenset(
                AcquisitionStrategy.from_value(strategy) for strategy in self.strategies
            )
        except TypeError as exc:
            raise TypeError("registration strategies must be iterable") from exc
        if not strategies:
            raise ValueError("registration must declare at least one strategy")
        if isinstance(self.scopes, (str, bytes)):
            raise TypeError("registration scopes must be an iterable of capability scopes")
        try:
            scopes = frozenset(self.scopes)
        except TypeError as exc:
            raise TypeError("registration scopes must be iterable") from exc
        if not scopes or any(not isinstance(scope, str) or scope not in CAPABILITY_SCOPES for scope in scopes):
            raise ValueError("registration scopes must contain declared capability scopes")
        object.__setattr__(self, "strategies", strategies)
        object.__setattr__(self, "scopes", scopes)

        if AcquisitionStrategy.DIRECT_FILE in strategies and not callable(
            getattr(self.provider, "download", None)
        ):
            raise TypeError("direct_file registration provider must implement download")
        if AcquisitionStrategy.WEB_MATERIALIZE in strategies and not callable(
            getattr(self.provider, "materialize", None)
        ):
            raise TypeError("web_materialize registration provider must implement materialize")
        if AcquisitionStrategy.WEB_CAPTURE in strategies and not (
            callable(getattr(self.provider, "capture", None))
            or callable(getattr(self.provider, "download", None))
        ):
            raise TypeError("web_capture registration provider must implement capture or download")


class AcquisitionRouter:
    """Route one authority-bound request to its exact registered provider."""

    def __init__(
        self,
        provider_registry: Mapping[tuple[str, str], ProviderRegistration]
        | Iterable[ProviderRegistration],
    ) -> None:
        registry: dict[tuple[str, str], ProviderRegistration] = {}
        if isinstance(provider_registry, Mapping):
            entries = provider_registry.items()
            for raw_key, registration in entries:
                if (
                    not isinstance(raw_key, tuple)
                    or len(raw_key) != 2
                    or not all(isinstance(part, str) for part in raw_key)
                ):
                    raise TypeError("provider registry keys must be (provider_id, provider_version)")
                self._add_registration(
                    registry,
                    registration,
                    expected_key=(raw_key[0], raw_key[1]),
                )
        else:
            if isinstance(provider_registry, (str, bytes)):
                raise TypeError("provider_registry must be a mapping or registration iterable")
            try:
                for registration in provider_registry:
                    self._add_registration(registry, registration)
            except TypeError as exc:
                if str(exc).startswith("provider registry") or str(exc).startswith("registration"):
                    raise
                raise TypeError("provider_registry must be a mapping or registration iterable") from exc
        self._provider_registry: Mapping[tuple[str, str], ProviderRegistration] = MappingProxyType(
            dict(registry)
        )

    @staticmethod
    def _add_registration(
        registry: dict[tuple[str, str], ProviderRegistration],
        registration: ProviderRegistration,
        *,
        expected_key: tuple[str, str] | None = None,
    ) -> None:
        if not isinstance(registration, ProviderRegistration):
            raise TypeError("provider registry values must be ProviderRegistration")
        key = (registration.provider_id, registration.provider_version)
        if expected_key is not None and expected_key != key:
            raise ValueError("provider registry key must match registration provider_id and provider_version")
        if key in registry:
            raise ValueError("provider registry contains duplicate exact provider registration")
        registry[key] = registration

    @property
    def provider_registry(self) -> Mapping[tuple[str, str], ProviderRegistration]:
        """Read-only view of exact registrations, useful for diagnostics only."""

        return self._provider_registry

    @staticmethod
    def select_strategy(
        value: AcquisitionStrategy | str | None,
        resource: Mapping[str, Any] | None = None,
    ) -> AcquisitionStrategy:
        """Translate an explicit plan value; routing itself uses request.strategy only."""

        # Preserve the legacy argument shape without allowing resource type to
        # infer an executable strategy.
        del resource
        return AcquisitionStrategy.from_plan(value)

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        if not isinstance(request, AcquisitionRequest):
            raise TypeError("router.acquire expects AcquisitionRequest")
        if request.cancel_event.is_set():
            return self._planned_failure(
                request,
                "JOB_CANCELLED",
                "获取任务已取消",
            )

        registration, failure = self._resolve_registration(request)
        if failure is not None:
            return failure
        assert registration is not None  # narrowed by _resolve_registration

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
                # Legacy rendering providers are allowed only when this exact
                # registration explicitly declares WEB_CAPTURE.
                result = self._call_download_provider(
                    request,
                    provider,  # type: ignore[arg-type]
                    provider_strategy="webpage",
                    result_strategy=AcquisitionStrategy.WEB_CAPTURE,
                    provider_id=registration.provider_id,
                )
            else:  # pragma: no cover - ProviderRegistration prevents this
                result = AcquisitionResult.failed(
                    request.strategy,
                    "PROVIDER_UNAVAILABLE",
                    "已绑定的网页捕获器不可用",
                )
        else:  # pragma: no cover - AcquisitionRequest validates the enum
            result = AcquisitionResult.failed(
                request.strategy,
                "UNSUPPORTED_ACQUISITION_STRATEGY",
                "不支持的获取策略",
            )
        return self._bind_result(request, registration, result)

    def _resolve_registration(
        self, request: AcquisitionRequest
    ) -> tuple[ProviderRegistration | None, AcquisitionResult | None]:
        key = (request.provider_id, request.provider_version)
        registration = self._provider_registry.get(key)
        if registration is None:
            versions = sorted(
                version
                for provider_id, version in self._provider_registry
                if provider_id == request.provider_id
            )
            if versions:
                return None, self._planned_failure(
                    request,
                    "CAPABILITY_VERSION_CONFLICT",
                    "已绑定的提供方版本未部署",
                    details={
                        "provider_id": request.provider_id,
                        "provider_version": request.provider_version,
                        "reason": "provider_version_not_registered",
                    },
                )
            return None, self._planned_failure(
                request,
                "PROVIDER_UNAVAILABLE",
                "已绑定的提供方未部署",
                details={
                    "provider_id": request.provider_id,
                    "provider_version": request.provider_version,
                    "reason": "provider_not_registered",
                },
            )
        if request.strategy not in registration.strategies or request.planned_scope not in registration.scopes:
            return None, self._planned_failure(
                request,
                "PROVIDER_SCOPE_MISMATCH",
                "已绑定的提供方不支持该策略或资源范围",
                details={
                    "provider_id": registration.provider_id,
                    "provider_version": registration.provider_version,
                    "requested_strategy": request.strategy.kind,
                    "requested_scope": request.planned_scope,
                },
            )
        return registration, None

    @staticmethod
    def _authority_kwargs(
        request: AcquisitionRequest,
        registration: ProviderRegistration | None = None,
    ) -> dict[str, Any]:
        return {
            "planned_provider_id": request.provider_id,
            "planned_provider_version": request.provider_version,
            "provider_id": registration.provider_id if registration is not None else None,
            "provider_version": registration.provider_version if registration is not None else None,
            "planned_scope": request.planned_scope,
            "actual_scope": request.planned_scope if registration is not None else None,
            "representation_id": request.representation_id,
            "binding_digest": request.binding_digest,
            "source_fingerprint": request.source_fingerprint,
        }

    def _planned_failure(
        self,
        request: AcquisitionRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> AcquisitionResult:
        return AcquisitionResult.failed(
            request.strategy,
            code,
            message,
            retryable=retryable,
            details=details,
            **self._authority_kwargs(request),
        )

    def _bind_result(
        self,
        request: AcquisitionRequest,
        registration: ProviderRegistration,
        result: AcquisitionResult,
    ) -> AcquisitionResult:
        if result.strategy is not request.strategy:
            return self._planned_failure(
                request,
                "PROVIDER_SCOPE_MISMATCH",
                "提供方返回了未绑定的获取策略",
                details={
                    "provider_id": registration.provider_id,
                    "provider_version": registration.provider_version,
                    "expected_strategy": request.strategy.kind,
                    "returned_strategy": result.strategy.kind,
                },
            )
        metadata = self._without_authority_metadata(result.metadata)
        return AcquisitionResult(
            request.strategy,
            bundle=result.bundle,
            failure=result.failure,
            warnings=result.warnings,
            metadata=metadata,
            item_failures=result.item_failures,
            completion=result.completion,
            **self._authority_kwargs(request, registration),
        )

    @staticmethod
    def _without_authority_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):  # defensive provider boundary
            raise TypeError("provider result metadata must be a mapping")
        return {
            str(key): value
            for key, value in metadata.items()
            if str(key).strip().lower() not in _AUTHORITY_METADATA_KEYS
        }

    def _call_download_provider(
        self,
        request: AcquisitionRequest,
        provider: DirectProvider,
        *,
        provider_strategy: str,
        result_strategy: AcquisitionStrategy,
        provider_id: str,
    ) -> AcquisitionResult:
        item_failures: tuple[AcquisitionItemFailure, ...] = ()
        results: list[DownloadResult] = []
        try:
            self._raise_if_cancelled(request.cancel_event)
            raw = provider.download(
                request.mutable_resource(),
                request.job_id,
                provider_strategy,
                request.max_bytes,
                request.cancel_event,
            )
            self._raise_if_cancelled(request.cancel_event)
            results, item_failures = self._normalise_download_envelope(raw)
            if not results:
                if item_failures:
                    first = item_failures[0]
                    return AcquisitionResult.failed(
                        result_strategy,
                        first.code,
                        first.message,
                        retryable=first.retryable,
                        details={"item_key": first.item_key},
                        item_failures=item_failures,
                    )
                raise ValueError("download provider returned no artifacts")
            bundle = self._bundle_from_downloads(request, results)
            self._raise_if_cancelled(request.cancel_event)
            return AcquisitionResult.success(
                result_strategy,
                bundle,
                item_failures=item_failures,
            )
        except DomainError as exc:
            return self._failure_from_domain_error(result_strategy, exc)
        except (OSError, PolicyViolation, ValueError, TypeError) as exc:
            primary_failure = next(
                (item for item in item_failures if item.role == "primary"), None
            )
            successful_primary = any(
                (item.role or ("primary" if index == 0 else "attachment"))
                in {"primary", "bundle"}
                for index, item in enumerate(results)
            )
            if primary_failure is not None and not successful_primary:
                return AcquisitionResult.failed(
                    result_strategy,
                    primary_failure.code,
                    primary_failure.message,
                    retryable=primary_failure.retryable,
                    details={"item_key": primary_failure.item_key},
                    item_failures=item_failures,
                )
            return AcquisitionResult.failed(
                result_strategy,
                "ACQUISITION_OUTPUT_INVALID",
                "直接获取结果未通过安全校验",
                details={"provider_id": provider_id, "reason": type(exc).__name__},
                item_failures=item_failures,
            )
        except Exception as exc:  # providers are a plugin boundary
            return AcquisitionResult.failed(
                result_strategy,
                "ACQUISITION_FAILED",
                "直接获取失败",
                retryable=True,
                details={"provider_id": provider_id, "reason": type(exc).__name__},
                item_failures=item_failures,
            )

    def _call_result_provider(
        self,
        request: AcquisitionRequest,
        provider: WebMaterializer | BrowserCapture,
        *,
        strategy: AcquisitionStrategy,
        method_name: str,
        provider_id: str,
    ) -> AcquisitionResult:
        try:
            self._raise_if_cancelled(request.cancel_event)
            method = getattr(provider, method_name)
            result = method(request)
            self._raise_if_cancelled(request.cancel_event)
            if not isinstance(result, AcquisitionResult):
                raise TypeError("provider must return AcquisitionResult")
            if result.strategy is not strategy:
                return AcquisitionResult.failed(
                    strategy,
                    "PROVIDER_SCOPE_MISMATCH",
                    "提供方返回了未绑定的获取策略",
                    details={
                        "provider_id": provider_id,
                        "expected_strategy": strategy.kind,
                        "returned_strategy": result.strategy.kind,
                    },
                )
            if not result.ok:
                return self._sanitise_result(result)
            if result.bundle is None:  # pragma: no cover - guarded by model
                raise ValueError("successful result has no bundle")
            bundle = self._validate_bundle(request, result.bundle)
            self._raise_if_cancelled(request.cancel_event)
            return AcquisitionResult.success(
                strategy,
                bundle,
                warnings=result.warnings,
                metadata=result.metadata,
                item_failures=result.item_failures,
                completion=result.completion,
            )
        except DomainError as exc:
            return self._failure_from_domain_error(strategy, exc)
        except (OSError, PolicyViolation, ValueError, TypeError) as exc:
            return AcquisitionResult.failed(
                strategy,
                "ACQUISITION_OUTPUT_INVALID",
                "物化结果未通过安全校验",
                details={"provider_id": provider_id, "reason": type(exc).__name__},
            )
        except Exception as exc:  # provider/plugin boundary
            return AcquisitionResult.failed(
                strategy,
                "ACQUISITION_FAILED",
                "物化任务失败",
                retryable=True,
                details={"provider_id": provider_id, "reason": type(exc).__name__},
            )

    def _bundle_from_downloads(
        self,
        request: AcquisitionRequest,
        results: Sequence[DownloadResult],
    ) -> ArtifactBundle:
        if not results:
            raise ValueError("download provider returned no artifacts")
        if len(results) > MAX_ARTIFACTS:
            raise ValueError("download provider returned too many artifacts")

        roles: list[str] = []
        for result in results:
            if not isinstance(result, DownloadResult):
                raise TypeError("download provider list contains an invalid result")
            role = result.role or ("primary" if len(roles) == 0 else "attachment")
            # Direct download envelopes are the persistence boundary.  The
            # 0021-only roles (markdown/sanitized_html/image/bundle) remain
            # valid for an already-built internal ArtifactBundle, but a
            # provider may not smuggle them through DownloadResult.
            if role not in PERSISTENT_ARTIFACT_ROLES:
                raise ValueError(f"download result role is unsupported: {role}")
            roles.append(role)

        item_keys: list[str | None] = []
        seen_item_keys: set[str] = set()
        primary_count = 0
        for result, role in zip(results, roles):
            if result.item_key is not None:
                if result.item_key in seen_item_keys:
                    raise ValueError("download provider item_keys must be unique")
                seen_item_keys.add(result.item_key)
            item_keys.append(result.item_key)
            # ``bundle`` is the 0021 compatibility role for the web ZIP.
            primary_count += int(role == "primary")
        if primary_count == 0:
            raise ValueError("download provider returned no primary item")
        if primary_count > 1:
            raise ValueError("download provider returned more than one primary")

        artifacts: list[Artifact] = []
        for index, result in enumerate(results):
            self._raise_if_cancelled(request.cancel_event)
            path = self._checked_path(result.path, request.jobs_root)
            actual_size = path.stat().st_size
            if actual_size != result.byte_size:
                raise ValueError("download result byte_size does not match the file")
            if actual_size > request.max_bytes:
                raise ValueError("artifact exceeds max_bytes")
            digest = self._sha256(path, request.max_bytes, request.cancel_event)
            if not isinstance(result.sha256, str) or not _SHA256.fullmatch(result.sha256.lower()):
                raise ValueError("download result sha256 is invalid")
            if digest != result.sha256.lower():
                raise ValueError("download result sha256 does not match the file")
            filename = result.filename or path.name
            role = roles[index]
            required = bool(result.required)
            metadata = self._sanitise_mapping(result.metadata)
            metadata.setdefault("source", "download_result")
            artifacts.append(
                Artifact(
                    artifact_id=f"{request.job_id}:artifact:{index:03d}",
                    role=role,  # type: ignore[arg-type]
                    primary=role == "primary",
                    path=path,
                    byte_size=actual_size,
                    media_type=result.media_type,
                    sha256=digest,
                    filename=filename,
                    metadata=metadata,
                    required=required,
                    item_key=item_keys[index],
                )
            )
        return ArtifactBundle(tuple(artifacts), request.max_bytes)

    def _validate_bundle(
        self, request: AcquisitionRequest, bundle: ArtifactBundle
    ) -> ArtifactBundle:
        if len(bundle.artifacts) > MAX_ARTIFACTS:
            raise ValueError("provider returned too many artifacts")
        validated: list[Artifact] = []
        total = 0
        for item in bundle.artifacts:
            self._raise_if_cancelled(request.cancel_event)
            path = self._checked_path(item.path, request.jobs_root)
            actual_size = path.stat().st_size
            if actual_size != item.byte_size:
                raise ValueError("artifact byte_size does not match the file")
            if actual_size > request.max_bytes:
                raise ValueError("artifact exceeds max_bytes")
            digest = self._sha256(path, request.max_bytes, request.cancel_event)
            if digest != item.sha256:
                raise ValueError("artifact sha256 does not match the file")
            validated.append(
                Artifact(
                    artifact_id=item.artifact_id,
                    role=item.role,
                    primary=item.primary,
                    path=path,
                    byte_size=actual_size,
                    media_type=item.media_type,
                    sha256=digest,
                    filename=item.filename,
                    metadata=self._sanitise_mapping(item.metadata),
                    required=item.required,
                    item_key=item.item_key,
                )
            )
            total += actual_size
        if total > request.max_bytes:
            raise ValueError("bundle exceeds max_bytes")
        return ArtifactBundle(tuple(validated), request.max_bytes)

    @classmethod
    def _normalise_download_envelope(
        cls,
        raw: DownloadResult | Sequence[DownloadResult] | DownloadBatchResult,
    ) -> tuple[list[DownloadResult], tuple[AcquisitionItemFailure, ...]]:
        """Compatibility adapter for the three provider return shapes."""

        if isinstance(raw, DownloadResult):
            results: Sequence[DownloadResult] = (raw,)
            failures: Sequence[DownloadItemFailure] = ()
        elif isinstance(raw, DownloadBatchResult):
            results = raw.results
            failures = raw.failures
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            results = raw
            failures = ()
        else:
            raise TypeError(
                "download provider must return DownloadResult, a list, or DownloadBatchResult"
            )
        if any(not isinstance(item, DownloadResult) for item in results):
            raise TypeError("download provider results contain an invalid result")
        if len(results) + len(failures) > MAX_ARTIFACTS:
            raise ValueError("download provider returned too many batch items")
        normalised_failures: list[AcquisitionItemFailure] = []
        for failure in failures:
            if not isinstance(failure, DownloadItemFailure):
                raise TypeError("download batch failures contain an invalid failure")
            if failure.role is not None and failure.role not in PERSISTENT_ARTIFACT_ROLES:
                raise ValueError("download item failure role is unsupported")
            normalised_failures.append(
                AcquisitionItemFailure(
                    item_key=failure.item_key,
                    code=failure.code,
                    message=cls._sanitise_message(failure.message),
                    role=failure.role,  # type: ignore[arg-type]
                    required=failure.required,
                    retryable=failure.retryable,
                    details=cls._sanitise_mapping(failure.details),
                    metadata=cls._sanitise_mapping(failure.metadata),
                )
            )
        keys = [item.item_key for item in results if item.item_key is not None]
        keys.extend(item.item_key for item in normalised_failures)
        if len(set(keys)) != len(keys):
            raise ValueError("download provider item_keys must be unique")
        return list(results), tuple(normalised_failures)

    @classmethod
    def _sanitise_item_failure(cls, failure: DownloadItemFailure) -> DownloadItemFailure:
        if not isinstance(failure, DownloadItemFailure):
            raise TypeError("download batch failures contain an invalid failure")
        return DownloadItemFailure(
            item_key=failure.item_key,
            code=failure.code,
            message=cls._sanitise_message(failure.message),
            role=failure.role,
            required=failure.required,
            retryable=failure.retryable,
            details=cls._sanitise_mapping(failure.details),
            metadata=cls._sanitise_mapping(failure.metadata),
        )

    @classmethod
    def _sanitise_result(cls, result: AcquisitionResult) -> AcquisitionResult:
        # AcquisitionResult/AcquisitionItemFailure already enforce the
        # bounded JSON-safe boundary.  Preserve a non-ok bundle carrying a
        # primary-item failure instead of dropping successful companions.
        return result

    @classmethod
    def _sanitise_mapping(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("sensitive detail value must be a mapping")

        def clean(item: Any) -> Any:
            if isinstance(item, Mapping):
                cleaned: dict[str, Any] = {}
                for raw_key, raw_value in item.items():
                    key = str(raw_key)
                    if cls._is_sensitive_key(key):
                        continue
                    cleaned[key] = clean(raw_value)
                return cleaned
            if isinstance(item, (list, tuple)):
                return [clean(entry) for entry in item]
            if item is None or isinstance(item, (str, bool, int, float)):
                return item
            # Do not serialize provider exception/path objects into a public
            # result.  The type name is bounded and contains no instance data.
            return type(item).__name__

        cleaned_value = clean(value)
        if not isinstance(cleaned_value, dict):  # pragma: no cover - defensive
            raise TypeError("sanitised detail value must be a mapping")
        return cleaned_value

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
        if normalized in _REDACTED_DETAIL_KEYS:
            return True
        parts = set(normalized.split("_"))
        return bool(parts.intersection(_REDACTED_DETAIL_PARTS))

    @staticmethod
    def _sanitise_message(message: str) -> str:
        # Provider messages are user-facing, but URLs and local paths are not
        # needed to explain an item failure and may carry credentials.
        safe = re.sub(r"https?://[^\s]+", "[redacted-url]", message)
        safe = re.sub(
            r"(?<![A-Za-z0-9])(?:/Users/|/private/|/tmp/|/var/)[^\s]+",
            "[redacted-path]",
            safe,
        )
        return safe[:1024]

    @staticmethod
    def _checked_path(path: Path, root: Path) -> Path:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("provider path must be absolute")
        resolved = path.resolve(strict=True)
        ensure_within_root(resolved, root)
        if not resolved.is_file():
            raise ValueError("provider path is not a regular file")
        return resolved

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "获取任务已取消")

    @classmethod
    def _sha256(
        cls,
        path: Path,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> str:
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                cls._raise_if_cancelled(cancel_event)
                chunk = handle.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("artifact exceeds max_bytes")
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _failure_from_domain_error(
        cls, strategy: AcquisitionStrategy, error: DomainError
    ) -> AcquisitionResult:
        return AcquisitionResult.failed(
            strategy,
            error.code,
            cls._sanitise_message(error.message),
            retryable=error.retryable,
            details=cls._sanitise_mapping(error.details),
        )


__all__ = [
    "AcquisitionRouter",
    "BrowserCapture",
    "DirectProvider",
    "ProviderRegistration",
    "WebMaterializer",
]
