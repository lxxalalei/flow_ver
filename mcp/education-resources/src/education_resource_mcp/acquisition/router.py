"""Internal acquisition router and legacy downloader adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
import re
import threading
from typing import Any, Protocol

from ..downloader import DownloadBatchResult, DownloadItemFailure, DownloadResult
from ..errors import DomainError
from ..policy import PolicyViolation, ensure_within_root
from .models import (
    MAX_ARTIFACTS,
    AcquisitionRequest,
    AcquisitionItemFailure,
    AcquisitionResult,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
    PERSISTENT_ARTIFACT_ROLES,
)


class DirectProvider(Protocol):
    """The existing downloader shape retained behind the acquisition seam."""

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

    # Existing RenderingDownloader instances may expose only the legacy
    # DownloadProvider method.  The Router detects that shape at runtime.
    def download(
        self,
        resource: Mapping[str, Any],
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult | list[DownloadResult] | DownloadBatchResult:
        ...


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
_SAFE_DIRECT_FALLBACK_CODES = frozenset(
    {
        "ACQUISITION_FAILED",
        "DOWNLOAD_FAILED",
        "FEATURE_NOT_SUPPORTED",
        "PLATFORM_UNAVAILABLE",
        "UPSTREAM_UNAVAILABLE",
    }
)
_SAFE_CAPTURE_FALLBACK_CODES = frozenset(
    {
        "ACQUISITION_FAILED",
        "BROWSER_CAPTURE_UNAVAILABLE",
        "CAPTURE_EMPTY",
        "RENDER_BROWSER_FAILED",
        "RENDER_FAILED",
    }
)


class AcquisitionRouter:
    """Choose a private acquisition provider and enforce output boundaries.

    The router accepts the legacy ``DownloadResult`` protocol for direct and
    platform downloaders.  Static materialization and browser capture return
    an ``AcquisitionResult`` directly.  Browser capture is never inferred by
    this class; it is reached only when the request's strategy is explicitly
    ``web_capture``.
    """

    def __init__(
        self,
        direct_provider: DirectProvider,
        platform_providers: Mapping[str, DirectProvider] | None = None,
        web_materializer: WebMaterializer | None = None,
        browser_capture: BrowserCapture | None = None,
    ) -> None:
        if direct_provider is None:
            raise TypeError("direct_provider is required")
        self.direct_provider = direct_provider
        self.platform_providers = dict(platform_providers or {})
        self.web_materializer = web_materializer
        self.browser_capture = browser_capture

    @staticmethod
    def select_strategy(
        value: AcquisitionStrategy | str | None,
        resource: Mapping[str, Any] | None = None,
    ) -> AcquisitionStrategy:
        """Resolve a plan value without ever auto-selecting browser capture."""

        return AcquisitionStrategy.from_plan(value, resource)

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        if not isinstance(request, AcquisitionRequest):
            raise TypeError("router.acquire expects AcquisitionRequest")
        if request.cancel_event.is_set():
            return AcquisitionResult.failed(
                request.strategy,
                "JOB_CANCELLED",
                "获取任务已取消",
            )
        strategy = request.strategy
        if strategy is AcquisitionStrategy.DIRECT_FILE:
            return self._acquire_direct(request)
        if strategy is AcquisitionStrategy.WEB_MATERIALIZE:
            return self._acquire_materialized(request)
        if strategy is AcquisitionStrategy.WEB_CAPTURE:
            return self._acquire_captured(request)
        # The enum makes this unreachable, but retaining a structured result
        # keeps this seam safe if another strategy is added incorrectly.
        return AcquisitionResult.failed(
            strategy,
            "UNSUPPORTED_ACQUISITION_STRATEGY",
            "不支持的获取策略",
        )

    def _acquire_direct(self, request: AcquisitionRequest) -> AcquisitionResult:
        platform = str(request.resource.get("platform") or "")
        provider = self.platform_providers.get(platform, self.direct_provider)
        provider_name = platform if provider is not self.direct_provider else "direct"
        result = self._call_download_provider(
            request, provider, provider_name=provider_name
        )
        if (
            result.ok
            or not request.allow_safe_fallback
            or provider is self.direct_provider
            or result.failure is None
            or result.failure.code not in _SAFE_DIRECT_FALLBACK_CODES
            or self._no_fallback_code(result.failure.code)
        ):
            return result

        fallback = self._call_download_provider(
            request,
            self.direct_provider,
            provider_name="direct-fallback",
        )
        if fallback.ok:
            return AcquisitionResult.success(
                fallback.strategy,
                fallback.bundle,  # type: ignore[arg-type]
                warnings=(
                    "platform provider failed; safe direct provider fallback used",
                ),
                metadata={"fallback": "direct_file"},
                item_failures=fallback.item_failures,
                completion=fallback.completion,
            )
        return result

    def _call_download_provider(
        self,
        request: AcquisitionRequest,
        provider: DirectProvider,
        *,
        provider_name: str,
        provider_strategy: str = "direct",
        result_strategy: AcquisitionStrategy = AcquisitionStrategy.DIRECT_FILE,
    ) -> AcquisitionResult:
        item_failures: tuple[AcquisitionItemFailure, ...] = ()
        results: list[DownloadResult] = []
        try:
            if request.cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "获取任务已取消")
            raw = provider.download(
                request.mutable_resource(),
                request.job_id,
                # Existing providers use ``direct``.  Browser compatibility
                # callers explicitly override this with legacy ``webpage``.
                provider_strategy,
                request.max_bytes,
                request.cancel_event,
            )
            if request.cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "获取任务已取消")
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
            bundle = self._bundle_from_downloads(
                request, results, provider_name
            )
            return AcquisitionResult.success(
                result_strategy,
                bundle,
                metadata={"provider": provider_name},
                item_failures=item_failures,
            )
        except DomainError as exc:
            return self._failure_from_domain_error(
                result_strategy, exc
            )
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
                details={"provider": provider_name, "reason": type(exc).__name__},
                item_failures=item_failures,
            )
        except Exception as exc:  # providers are a plugin boundary
            return AcquisitionResult.failed(
                result_strategy,
                "ACQUISITION_FAILED",
                "直接获取失败",
                retryable=True,
                details={"provider": provider_name, "reason": type(exc).__name__},
                item_failures=item_failures,
            )

    def _acquire_materialized(self, request: AcquisitionRequest) -> AcquisitionResult:
        if self.web_materializer is None:
            return AcquisitionResult.failed(
                AcquisitionStrategy.WEB_MATERIALIZE,
                "MATERIALIZER_UNAVAILABLE",
                "静态网页物化器不可用",
            )
        return self._call_result_provider(
            request,
            self.web_materializer,
            strategy=AcquisitionStrategy.WEB_MATERIALIZE,
            method_name="materialize",
        )

    def _acquire_captured(self, request: AcquisitionRequest) -> AcquisitionResult:
        if self.browser_capture is not None:
            if callable(getattr(self.browser_capture, "capture", None)):
                result = self._call_result_provider(
                    request,
                    self.browser_capture,
                    strategy=AcquisitionStrategy.WEB_CAPTURE,
                    method_name="capture",
                )
            elif callable(getattr(self.browser_capture, "download", None)):
                # RenderingDownloader is a legacy DownloadProvider.  Explicit
                # WEB_CAPTURE receives its old strategy value, then the
                # resulting files go through the same bounded conversion.
                result = self._call_download_provider(
                    request,
                    self.browser_capture,  # type: ignore[arg-type]
                    provider_name="browser-capture-legacy",
                    provider_strategy="webpage",
                    result_strategy=AcquisitionStrategy.WEB_CAPTURE,
                )
            else:
                result = AcquisitionResult.failed(
                    AcquisitionStrategy.WEB_CAPTURE,
                    "BROWSER_CAPTURE_UNAVAILABLE",
                    "浏览器网页捕获器没有可用接口",
                )
            if (
                result.ok
                or not request.allow_safe_fallback
                or result.failure is None
                or result.failure.code not in _SAFE_CAPTURE_FALLBACK_CODES
                or self._no_fallback_code(result.failure.code)
            ):
                return result
        else:
            result = AcquisitionResult.failed(
                AcquisitionStrategy.WEB_CAPTURE,
                "BROWSER_CAPTURE_UNAVAILABLE",
                "浏览器网页捕获器不可用",
            )

        # Static materialization is a safe fallback for an explicitly
        # requested browser capture.  The inverse fallback is intentionally
        # absent because raw HTML is not a safe substitute for materialized
        # content.
        if request.allow_safe_fallback and self.web_materializer is not None:
            fallback = self._call_result_provider(
                request,
                self.web_materializer,
                strategy=AcquisitionStrategy.WEB_MATERIALIZE,
                method_name="materialize",
            )
            if fallback.ok:
                return AcquisitionResult.success(
                    fallback.strategy,
                    fallback.bundle,  # type: ignore[arg-type]
                    warnings=(
                        "browser capture unavailable or failed; static materialization fallback used",
                    ),
                    metadata={"fallback": "web_materialize"},
                    item_failures=fallback.item_failures,
                    completion=fallback.completion,
                )
        return result

    def _call_result_provider(
        self,
        request: AcquisitionRequest,
        provider: WebMaterializer | BrowserCapture,
        *,
        strategy: AcquisitionStrategy,
        method_name: str,
    ) -> AcquisitionResult:
        try:
            if request.cancel_event.is_set():
                raise DomainError("JOB_CANCELLED", "获取任务已取消")
            method = getattr(provider, method_name)
            result = method(request)
            if not isinstance(result, AcquisitionResult):
                raise TypeError("provider must return AcquisitionResult")
            if not result.ok:
                return self._sanitise_result(result)
            if result.bundle is None:  # pragma: no cover - guarded by model
                raise ValueError("successful result has no bundle")
            bundle = self._validate_bundle(request, result.bundle)
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
                details={"reason": type(exc).__name__},
            )
        except Exception as exc:  # provider/plugin boundary
            return AcquisitionResult.failed(
                strategy,
                "ACQUISITION_FAILED",
                "物化任务失败",
                retryable=True,
                details={"reason": type(exc).__name__},
            )

    def _bundle_from_downloads(
        self,
        request: AcquisitionRequest,
        results: Sequence[DownloadResult],
        provider_name: str,
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
            path = self._checked_path(result.path, request.jobs_root)
            actual_size = path.stat().st_size
            if actual_size != result.byte_size:
                raise ValueError("download result byte_size does not match the file")
            if actual_size > request.max_bytes:
                raise ValueError("artifact exceeds max_bytes")
            digest = self._sha256(path, request.max_bytes)
            if not isinstance(result.sha256, str) or not _SHA256.fullmatch(result.sha256.lower()):
                raise ValueError("download result sha256 is invalid")
            if digest != result.sha256.lower():
                raise ValueError("download result sha256 does not match the file")
            filename = result.filename or path.name
            role = roles[index]
            required = bool(result.required)
            metadata = self._sanitise_mapping(result.metadata)
            metadata.setdefault("provider", provider_name)
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
            path = self._checked_path(item.path, request.jobs_root)
            actual_size = path.stat().st_size
            if actual_size != item.byte_size:
                raise ValueError("artifact byte_size does not match the file")
            if actual_size > request.max_bytes:
                raise ValueError("artifact exceeds max_bytes")
            digest = self._sha256(path, request.max_bytes)
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
    def _sha256(path: Path, max_bytes: int) -> str:
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("artifact exceeds max_bytes")
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _no_fallback_code(code: str) -> bool:
        """Authorization, policy and cancellation failures are terminal."""

        normalized = str(code).upper()
        return (
            normalized.startswith("AUTH")
            or normalized.startswith("POLICY")
            or normalized in {"CANCEL", "CANCELLED", "JOB_CANCELLED", "JOB_CANCELLING"}
            or "CANCEL" in normalized
        )

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
    "WebMaterializer",
]
