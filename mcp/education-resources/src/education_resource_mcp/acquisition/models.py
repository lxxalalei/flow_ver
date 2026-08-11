"""Internal acquisition models.

The public MCP contract deliberately stops at ``Plan``/``Job``/``Asset``.
This module is the private seam between a job runner and the concrete ways in
which a selected resource can become one or more materialized files.  The
models are intentionally small, immutable at their boundary, and independent
from the SQLite and MCP models.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import json
import math
from pathlib import Path, PurePosixPath
import re
import threading
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from ..downloader import DownloadItemFailure


StrategyKind: TypeAlias = Literal[
    "direct_file", "web_materialize", "web_capture"
]
CapabilityScope: TypeAlias = Literal[
    "primary_resource", "representation", "landing_page", "metadata"
]
CompletionKind: TypeAlias = Literal["complete", "partial"]
PersistentArtifactRole: TypeAlias = Literal[
    "primary",
    "subtitle",
    "cover",
    "metadata",
    "attachment",
    "transcript",
    "companion",
]
InternalArtifactRole: TypeAlias = Literal[
    "markdown",
    "sanitized_html",
    "image",
    "bundle",
]
ArtifactRole: TypeAlias = Literal[
    "primary",
    "subtitle",
    "cover",
    "transcript",
    "companion",
    "markdown",
    "sanitized_html",
    "metadata",
    "image",
    "attachment",
    "bundle",
]
PreferredContainer: TypeAlias = Literal[
    "original", "pdf", "epub", "mp4", "mp3", "html", "text"
]

ACQUISITION_STRATEGIES: frozenset[str] = frozenset(
    {"direct_file", "web_materialize", "web_capture"}
)
ARTIFACT_ROLES: frozenset[str] = frozenset(
    {
        "primary",
        "subtitle",
        "cover",
        "transcript",
        "companion",
        "markdown",
        "sanitized_html",
        "metadata",
        "image",
        "attachment",
        "bundle",
    }
)
PERSISTENT_ARTIFACT_ROLES: frozenset[str] = frozenset(
    {
        "primary",
        "subtitle",
        "cover",
        "metadata",
        "attachment",
        "transcript",
        "companion",
    }
)
# Storage and contract code may import either descriptive spelling.
ASSET_ROLES = PERSISTENT_ARTIFACT_ROLES
FORMAL_ARTIFACT_ROLES = PERSISTENT_ARTIFACT_ROLES
INTERNAL_ARTIFACT_ROLES: frozenset[str] = frozenset(
    {"markdown", "sanitized_html", "image", "bundle"}
)
MAX_ARTIFACTS = 50
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_COMPONENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.-]{0,63}$")
_REPRESENTATION_ID_PATTERN = re.compile(r"^repr_[A-Za-z0-9_-]{16,64}$")
_DESCRIPTOR_ID_PATTERN = re.compile(r"^cap_[A-Za-z0-9][A-Za-z0-9_.-]{7,123}$")
_READINESS_SNAPSHOT_ID_PATTERN = re.compile(r"^ready_[A-Za-z0-9][A-Za-z0-9_.-]{7,122}$")
_ELIGIBILITY_ID_PATTERN = re.compile(r"^elig_[A-Za-z0-9][A-Za-z0-9_.-]{7,123}$")
CAPABILITY_SCOPES: frozenset[str] = frozenset(
    {"primary_resource", "representation", "landing_page", "metadata"}
)
_FAILURE_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "auth",
        "cookie",
        "credential",
        "credentials",
        "file",
        "filename",
        "password",
        "path",
        "secret",
        "source_url",
        "token",
        "url",
    }
)
_FAILURE_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_FAILURE_CREDENTIAL = re.compile(
    r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"
    r"\b(?:authorization|cookie|password|secret|token)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_FAILURE_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s\"'<>]+)")


def _safe_failure_text(value: str, *, limit: int = 512) -> str:
    text = str(value).replace("\x00", " ").strip()
    text = _FAILURE_URL.sub("[redacted-url]", text)
    text = _FAILURE_CREDENTIAL.sub("[redacted-credential]", text)
    text = _FAILURE_PATH.sub("[redacted-path]", text)
    return text[:limit] or "acquisition item failed"


def _safe_failure_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        raise ValueError("failure details nesting exceeds the bounded limit")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return _safe_failure_text(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("failure details contain a non-finite number")
        return value
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise ValueError("failure details contain too many fields")
        result: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                raise TypeError("failure detail keys must be strings")
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized_key in _FAILURE_SENSITIVE_KEYS or set(normalized_key.split("_")) & {
                "authorization",
                "auth",
                "cookie",
                "credential",
                "password",
                "path",
                "file",
                "filename",
                "destination",
                "url",
                "uri",
                "secret",
                "token",
            }:
                continue
            result[key[:128]] = _safe_failure_value(value[key], depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise ValueError("failure details contain too many items")
        return [_safe_failure_value(item, depth=depth + 1) for item in value]
    raise TypeError(f"failure details contain unsupported value {type(value).__name__}")


def _safe_failure_details(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("failure details must be a mapping")
    normalized = _safe_failure_value(value)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 8 * 1024:
        raise ValueError("failure details exceed the bounded JSON size")
    return normalized


def _json_value(value: Any, *, label: str) -> Any:
    """Return a JSON-safe copy with recursively deterministic key ordering."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                raise TypeError(f"{label} keys must be strings")
            normalized[key] = _json_value(value[key], label=f"{label}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [_json_value(item, label=label) for item in value]
    raise TypeError(f"{label} contains unsupported value {type(value).__name__}")


def _freeze(value: Any, *, label: str) -> Any:
    """Make a JSON-compatible value immutable for provider boundaries."""

    normalized = _json_value(value, label=label)
    if isinstance(normalized, dict):
        return MappingProxyType(
            {key: _freeze(item, label=f"{label}.{key}") for key, item in normalized.items()}
        )
    if isinstance(normalized, list):
        return tuple(_freeze(item, label=label) for item in normalized)
    return normalized


def thaw(value: Any) -> Any:
    """Convert an internal immutable snapshot back to a provider-owned copy."""

    if isinstance(value, Mapping):
        return {str(key): thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def _validate_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label} must be a bounded server identifier without path separators"
        )
    return value


def _validate_item_key(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{label} must be a bounded non-empty string")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{label} must not contain control characters")
    if "/" in value or "\\" in value:
        raise ValueError(f"{label} must not contain path separators")
    return value


def _validate_filename(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("artifact filename must be a non-empty relative path")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("artifact filename must not contain control characters")
    portable = value.replace("\\", "/")
    path = PurePosixPath(portable)
    if path.is_absolute() or portable.startswith("//") or ".." in path.parts:
        raise ValueError("artifact filename must stay inside the server bundle")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise ValueError("artifact filename must identify a file")
    return PurePosixPath(*parts).as_posix()


def _validate_server_path(value: Path) -> Path:
    if not isinstance(value, Path):
        raise TypeError("artifact path must be a server-created pathlib.Path")
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("artifact path must be an absolute server-created path")
    if "\x00" in str(value):
        raise ValueError("artifact path must not contain NUL")
    return value


def _validate_pattern(value: str, pattern: re.Pattern[str], *, label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} is not a valid authority reference")
    return value


def _validate_provider_id(value: str, *, label: str) -> str:
    return _validate_pattern(value, _PROVIDER_ID_PATTERN, label=label)


def _validate_component_version(value: str, *, label: str) -> str:
    return _validate_pattern(value, _COMPONENT_VERSION_PATTERN, label=label)


def _validate_sha256(value: str, *, label: str) -> str:
    return _validate_pattern(value, _SHA256_PATTERN, label=label)


def _validate_canonical_digest(value: str, *, label: str) -> str:
    return _validate_pattern(value, _CANONICAL_DIGEST_PATTERN, label=label)


class AcquisitionStrategy(str, Enum):
    """One of the three internal acquisition mechanisms.

    ``web_capture`` is an explicit capability.  The Router never derives it
    from a resource type; callers must request it directly and provide a
    browser capture dependency.
    """

    DIRECT_FILE = "direct_file"
    WEB_MATERIALIZE = "web_materialize"
    WEB_CAPTURE = "web_capture"

    @property
    def kind(self) -> StrategyKind:
        return self.value  # type: ignore[return-value]

    @classmethod
    def from_plan(
        cls,
        value: "AcquisitionStrategy | str | None",
        resource: Mapping[str, Any] | None = None,
    ) -> "AcquisitionStrategy":
        """Translate an explicit plan strategy value to the internal enum.

        ``resource`` remains an ignored compatibility parameter for callers
        that still pass it, but resource type must never determine a download
        strategy. Every executable plan must bind its strategy explicitly.
        """

        if isinstance(value, cls):
            return value
        if value is None:
            raise ValueError("acquisition strategy must be explicitly planned")
        aliases = {
            "direct": cls.DIRECT_FILE,
            "direct_file": cls.DIRECT_FILE,
            "webpage": cls.WEB_MATERIALIZE,
            "web_materialize": cls.WEB_MATERIALIZE,
            "materialize": cls.WEB_MATERIALIZE,
            "capture": cls.WEB_CAPTURE,
            "web_capture": cls.WEB_CAPTURE,
        }
        normalized = aliases.get(str(value))
        if normalized is None:
            raise ValueError(f"unsupported acquisition strategy: {value}")
        return normalized

    @classmethod
    def from_value(cls, value: "AcquisitionStrategy | str") -> "AcquisitionStrategy":
        return cls.from_plan(value)

    @classmethod
    def direct_file(cls) -> "AcquisitionStrategy":
        return cls.DIRECT_FILE

    @classmethod
    def web_materialize(cls) -> "AcquisitionStrategy":
        return cls.WEB_MATERIALIZE

    @classmethod
    def web_capture(cls) -> "AcquisitionStrategy":
        return cls.WEB_CAPTURE

    def to_json_value(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    """Immutable, authority-bound input passed to one acquisition provider.

    A request is formed only after ``download_prepare`` has bound a selected
    resource to a concrete representation, capability descriptor, deployment
    readiness snapshot, eligibility decision, and exact provider version.  A
    router must never reconstruct those facts from a platform name or use a
    fallback provider.  ``resource`` is copied and recursively frozen before
    it is exposed; providers receive a new mutable copy only for their own
    invocation.
    """

    job_id: str
    resource: Mapping[str, Any]
    strategy: AcquisitionStrategy | StrategyKind | str
    provider_id: str
    provider_version: str
    planned_scope: CapabilityScope | str
    representation_id: str
    binding_digest: str
    source_fingerprint: str
    capability_id: str
    descriptor_version: str
    descriptor_digest: str
    readiness_snapshot_id: str
    readiness_digest: str
    eligibility_id: str
    eligibility_digest: str
    preferred_container: PreferredContainer = "html"
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)
    # ``None`` is rejected in ``__post_init__``.  Keeping a sentinel default
    # makes missing server-owned roots unrepresentable at the provider seam.
    jobs_root: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_id(self.job_id, label="job_id")
        if not isinstance(self.resource, Mapping):
            raise TypeError("resource must be a mapping")
        snapshot = _freeze(dict(self.resource), label="resource")
        if not isinstance(snapshot, Mapping):  # pragma: no cover - defensive
            raise TypeError("resource snapshot must be a mapping")
        resource_id = snapshot.get("resource_id")
        if not isinstance(resource_id, str):
            raise ValueError("resource must contain a server-controlled resource_id")
        _validate_id(resource_id, label="resource_id")
        if not isinstance(self.cancel_event, threading.Event):
            raise TypeError("cancel_event must be threading.Event")
        if not isinstance(self.jobs_root, Path):
            raise TypeError("jobs_root must be a server-provided pathlib.Path")
        if not self.jobs_root.is_absolute() or ".." in self.jobs_root.parts:
            raise ValueError("jobs_root must be an absolute server-controlled root")
        object.__setattr__(self, "jobs_root", self.jobs_root.resolve(strict=False))
        if self.preferred_container not in {
            "original", "pdf", "epub", "mp4", "mp3", "html", "text"
        }:
            raise ValueError(f"unsupported preferred container: {self.preferred_container}")
        _validate_provider_id(self.provider_id, label="provider_id")
        _validate_component_version(self.provider_version, label="provider_version")
        if not isinstance(self.planned_scope, str) or self.planned_scope not in CAPABILITY_SCOPES:
            raise ValueError("planned_scope must be a declared capability scope")
        _validate_pattern(
            self.representation_id,
            _REPRESENTATION_ID_PATTERN,
            label="representation_id",
        )
        _validate_sha256(self.binding_digest, label="binding_digest")
        _validate_canonical_digest(self.source_fingerprint, label="source_fingerprint")
        _validate_pattern(self.capability_id, _DESCRIPTOR_ID_PATTERN, label="capability_id")
        _validate_component_version(self.descriptor_version, label="descriptor_version")
        _validate_canonical_digest(self.descriptor_digest, label="descriptor_digest")
        _validate_pattern(
            self.readiness_snapshot_id,
            _READINESS_SNAPSHOT_ID_PATTERN,
            label="readiness_snapshot_id",
        )
        _validate_canonical_digest(self.readiness_digest, label="readiness_digest")
        _validate_pattern(self.eligibility_id, _ELIGIBILITY_ID_PATTERN, label="eligibility_id")
        _validate_canonical_digest(self.eligibility_digest, label="eligibility_digest")

        object.__setattr__(self, "resource", snapshot)
        object.__setattr__(self, "strategy", AcquisitionStrategy.from_value(self.strategy))

    @property
    def resource_id(self) -> str:
        return str(self.resource["resource_id"])

    def mutable_resource(self) -> dict[str, Any]:
        """Return a fresh provider-owned resource copy."""

        return thaw(self.resource)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "resource_id": self.resource_id,
            "strategy": self.strategy.kind,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "planned_provider": {
                "provider_id": self.provider_id,
                "version": self.provider_version,
            },
            "planned_scope": self.planned_scope,
            "representation_id": self.representation_id,
            "binding_digest": self.binding_digest,
            "source_fingerprint": self.source_fingerprint,
            "capability_id": self.capability_id,
            "descriptor_version": self.descriptor_version,
            "descriptor_digest": self.descriptor_digest,
            "readiness_snapshot_id": self.readiness_snapshot_id,
            "readiness_digest": self.readiness_digest,
            "eligibility_id": self.eligibility_id,
            "eligibility_digest": self.eligibility_digest,
            "preferred_container": self.preferred_container,
        }


@dataclass(frozen=True, slots=True)
class Artifact:
    """One server-created file in an acquisition bundle."""

    artifact_id: str
    role: ArtifactRole
    path: Path
    filename: str
    byte_size: int
    media_type: str
    sha256: str
    primary: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    required: bool = False
    item_key: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.artifact_id, label="artifact_id")
        if self.role not in ARTIFACT_ROLES:
            raise ValueError(f"unsupported artifact role: {self.role}")
        if not isinstance(self.primary, bool):
            raise TypeError("artifact primary must be a boolean")
        if self.role == "primary" and not self.primary:
            object.__setattr__(self, "primary", True)
        if not isinstance(self.required, bool):
            raise TypeError("artifact required must be a boolean")
        if self.item_key is not None:
            object.__setattr__(
                self,
                "item_key",
                _validate_item_key(self.item_key, label="artifact item_key"),
            )
        object.__setattr__(self, "path", _validate_server_path(self.path))
        object.__setattr__(self, "filename", _validate_filename(self.filename))
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise TypeError("artifact byte_size must be an integer")
        if self.byte_size < 0:
            raise ValueError("artifact byte_size must not be negative")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise ValueError("artifact media_type must be non-empty")
        media_type = self.media_type.strip().lower()
        if len(media_type) > 128:
            raise ValueError("artifact media_type is too long")
        object.__setattr__(self, "media_type", media_type)
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(self.sha256.lower()):
            raise ValueError("artifact sha256 must be a lowercase hexadecimal digest")
        object.__setattr__(self, "sha256", self.sha256.lower())
        frozen_metadata = _freeze(dict(self.metadata), label="artifact.metadata")
        if not isinstance(frozen_metadata, Mapping):  # pragma: no cover - defensive
            raise TypeError("artifact metadata must be a mapping")
        object.__setattr__(self, "metadata", frozen_metadata)

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "role": self.role,
            "filename": self.filename,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "primary": self.primary,
            "required": self.required,
            "item_key": self.item_key,
            "metadata": thaw(self.metadata),
        }
        if include_path:
            result["path"] = str(self.path)
        return result


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    """The artifacts produced for one selected resource."""

    artifacts: tuple[Artifact, ...]

    def __post_init__(self) -> None:
        normalized = tuple(self.artifacts)
        if len(normalized) > MAX_ARTIFACTS:
            raise ValueError(f"artifact count exceeds {MAX_ARTIFACTS}")
        if any(not isinstance(item, Artifact) for item in normalized):
            raise TypeError("bundle artifacts must contain Artifact values")
        ids = [item.artifact_id for item in normalized]
        filenames = [item.filename for item in normalized]
        if len(set(ids)) != len(ids):
            raise ValueError("bundle artifact IDs must be unique")
        if len(set(filenames)) != len(filenames):
            raise ValueError("bundle artifact filenames must be unique")
        item_keys = [item.item_key for item in normalized if item.item_key is not None]
        if len(set(item_keys)) != len(item_keys):
            raise ValueError("bundle artifact item_keys must be unique")
        for item in normalized:
            if item.primary and item.role not in {"primary", "bundle"}:
                raise ValueError("only primary or legacy bundle artifacts may be primary")
        primary_count = sum(item.primary for item in normalized)
        if normalized and primary_count != 1:
            raise ValueError("a non-empty bundle must contain exactly one primary artifact")
        object.__setattr__(self, "artifacts", normalized)

    @property
    def total_bytes(self) -> int:
        return sum(item.byte_size for item in self.artifacts)

    @property
    def primary(self) -> Artifact | None:
        return next((item for item in self.artifacts if item.primary), None)

    def to_dict(self, *, include_paths: bool = False) -> dict[str, Any]:
        ordered = sorted(self.artifacts, key=lambda item: item.artifact_id)
        return {
            "artifact_count": len(ordered),
            "total_bytes": self.total_bytes,
            "artifacts": [
                item.to_dict(include_path=include_paths) for item in ordered
            ],
        }

    def to_json(self, *, include_paths: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_paths=include_paths),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionItemFailure:
    """A safe, ordered failure for one expected bundle item."""

    item_key: str
    code: str
    message: str
    role: ArtifactRole | None = None
    required: bool | None = None
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_item_key(self.item_key, label="acquisition item failure item_key")
        if not isinstance(self.code, str) or not re.fullmatch(
            r"[A-Z][A-Z0-9_.-]{0,63}", self.code
        ):
            raise ValueError("acquisition item failure code must be an uppercase stable code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("acquisition item failure message must be non-empty")
        if self.role is not None and self.role not in ARTIFACT_ROLES:
            raise ValueError(f"unsupported acquisition item failure role: {self.role}")
        if self.required is not None and not isinstance(self.required, bool):
            raise TypeError("acquisition item failure required must be a boolean")
        if not isinstance(self.retryable, bool):
            raise TypeError("acquisition item failure retryable must be a boolean")
        object.__setattr__(self, "message", _safe_failure_text(self.message))
        safe_details = _safe_failure_details(self.details)
        safe_metadata = _safe_failure_details(self.metadata)
        object.__setattr__(self, "details", _freeze(dict(safe_details), label="item_failure.details"))
        object.__setattr__(self, "metadata", _freeze(dict(safe_metadata), label="item_failure.metadata"))

    @classmethod
    def from_download_failure(
        cls, failure: DownloadItemFailure
    ) -> "AcquisitionItemFailure":
        if not isinstance(failure, DownloadItemFailure):
            raise TypeError("failure must be a DownloadItemFailure")
        if failure.role is None:
            role: ArtifactRole | None = None
        else:
            role = failure.role  # type: ignore[assignment]
        return cls(
            item_key=failure.item_key,
            code=failure.code,
            message=failure.message,
            role=role,
            required=failure.required,
            retryable=failure.retryable,
            details=failure.details,
            metadata=failure.metadata,
        )

    @property
    def retriable(self) -> bool:
        return self.retryable

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "item_key": self.item_key,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": thaw(self.details),
            "metadata": thaw(self.metadata),
        }
        if self.role is not None:
            result["role"] = self.role
        if self.required is not None:
            result["required"] = self.required
        return result


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    """Structured internal failure safe to pass across a job boundary."""

    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_.-]{0,63}", self.code):
            raise ValueError("failure code must be an uppercase stable code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("failure message must be non-empty")
        if not isinstance(self.retryable, bool):
            raise TypeError("failure retryable must be a boolean")
        object.__setattr__(self, "message", _safe_failure_text(self.message))
        safe_details = _safe_failure_details(self.details)
        frozen_details = _freeze(dict(safe_details), label="failure.details")
        if not isinstance(frozen_details, Mapping):  # pragma: no cover
            raise TypeError("failure details must be a mapping")
        object.__setattr__(self, "details", frozen_details)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": thaw(self.details),
        }


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """Success or structured failure returned by an acquisition provider.

    Providers may construct the payload portion of this value, but the router
    attaches the planned and actual provider facts after it resolves the exact
    registration.  These facts are deliberately first-class fields instead of
    untrusted provider metadata.
    """

    strategy: AcquisitionStrategy | StrategyKind | str
    bundle: ArtifactBundle | None = None
    failure: AcquisitionFailure | None = None
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    item_failures: tuple[AcquisitionItemFailure | DownloadItemFailure, ...] = ()
    completion: CompletionKind | None = None
    planned_provider_id: str | None = None
    planned_provider_version: str | None = None
    provider_id: str | None = None
    provider_version: str | None = None
    planned_scope: CapabilityScope | None = None
    actual_scope: CapabilityScope | None = None
    representation_id: str | None = None
    binding_digest: str | None = None
    source_fingerprint: str | None = None

    def __post_init__(self) -> None:
        strategy = AcquisitionStrategy.from_value(self.strategy)
        object.__setattr__(self, "strategy", strategy)
        if (self.bundle is None) == (self.failure is None):
            raise ValueError("result must contain exactly one of bundle or failure")
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if any(not isinstance(item, str) or not item.strip() for item in self.warnings):
            raise ValueError("result warnings must be non-empty strings")
        if not isinstance(self.item_failures, tuple):
            object.__setattr__(self, "item_failures", tuple(self.item_failures))
        normalized_failures = tuple(
            item
            if isinstance(item, AcquisitionItemFailure)
            else AcquisitionItemFailure.from_download_failure(item)
            if isinstance(item, DownloadItemFailure)
            else item
            for item in self.item_failures
        )
        object.__setattr__(self, "item_failures", normalized_failures)
        if len(normalized_failures) > MAX_ARTIFACTS:
            raise ValueError(f"acquisition item failure count exceeds {MAX_ARTIFACTS}")
        if any(not isinstance(item, AcquisitionItemFailure) for item in normalized_failures):
            raise TypeError("result item_failures must contain AcquisitionItemFailure values")
        item_keys = [item.item_key for item in normalized_failures]
        if len(set(item_keys)) != len(item_keys):
            raise ValueError("result item failure item_keys must be unique")
        if self.completion not in {None, "complete", "partial"}:
            raise ValueError("result completion must be complete or partial")
        if self.bundle is not None:
            if self.bundle.primary is None:
                raise ValueError("a successful acquisition result requires a primary artifact")
            if self.completion is None:
                object.__setattr__(
                    self,
                    "completion",
                    "partial" if self.item_failures else "complete",
                )
            elif self.completion == "complete" and self.item_failures:
                raise ValueError("a result with item failures cannot be complete")
            elif self.completion == "partial" and not self.item_failures:
                raise ValueError("a partial result must contain item failures")
        elif self.completion is None and self.item_failures:
            object.__setattr__(self, "completion", "partial")
        elif self.completion == "partial" and self.item_failures:
            pass
        elif self.completion is not None:
            raise ValueError("failed result cannot declare completion without item failures")
        frozen_metadata = _freeze(dict(self.metadata), label="result.metadata")
        if not isinstance(frozen_metadata, Mapping):  # pragma: no cover
            raise TypeError("result metadata must be a mapping")
        object.__setattr__(self, "metadata", frozen_metadata)
        self._validate_provider_facts()

    def _validate_provider_facts(self) -> None:
        planned_values = (self.planned_provider_id, self.planned_provider_version)
        actual_values = (self.provider_id, self.provider_version)
        if any(value is not None for value in planned_values):
            if any(value is None for value in planned_values):
                raise ValueError("planned provider facts must include both id and version")
            _validate_provider_id(self.planned_provider_id, label="planned_provider_id")  # type: ignore[arg-type]
            _validate_component_version(
                self.planned_provider_version,
                label="planned_provider_version",
            )  # type: ignore[arg-type]
        if any(value is not None for value in actual_values):
            if any(value is None for value in actual_values):
                raise ValueError("actual provider facts must include both id and version")
            if any(value is None for value in planned_values):
                raise ValueError("actual provider facts require planned provider facts")
            _validate_provider_id(self.provider_id, label="provider_id")  # type: ignore[arg-type]
            _validate_component_version(self.provider_version, label="provider_version")  # type: ignore[arg-type]
        for field_name, value in (
            ("planned_scope", self.planned_scope),
            ("actual_scope", self.actual_scope),
        ):
            if value is not None and value not in CAPABILITY_SCOPES:
                raise ValueError(f"{field_name} must be a declared capability scope")
        if self.actual_scope is not None and self.planned_scope is None:
            raise ValueError("actual_scope requires planned_scope")
        if self.representation_id is not None:
            _validate_pattern(
                self.representation_id,
                _REPRESENTATION_ID_PATTERN,
                label="representation_id",
            )
        if self.binding_digest is not None:
            _validate_sha256(self.binding_digest, label="binding_digest")
        if self.source_fingerprint is not None:
            _validate_canonical_digest(
                self.source_fingerprint,
                label="source_fingerprint",
            )

    @property
    def ok(self) -> bool:
        if self.bundle is None or self.bundle.primary is None:
            return False
        primary = self.bundle.primary
        return not any(
            failure.role == "primary"
            or (primary.item_key is not None and failure.item_key == primary.item_key)
            for failure in self.item_failures
        )

    @classmethod
    def success(
        cls,
        strategy: AcquisitionStrategy | StrategyKind | str,
        bundle: ArtifactBundle,
        *,
        warnings: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
        item_failures: tuple[AcquisitionItemFailure | DownloadItemFailure, ...]
        | list[AcquisitionItemFailure | DownloadItemFailure] = (),
        completion: CompletionKind | None = None,
        planned_provider_id: str | None = None,
        planned_provider_version: str | None = None,
        provider_id: str | None = None,
        provider_version: str | None = None,
        planned_scope: CapabilityScope | None = None,
        actual_scope: CapabilityScope | None = None,
        representation_id: str | None = None,
        binding_digest: str | None = None,
        source_fingerprint: str | None = None,
    ) -> "AcquisitionResult":
        return cls(
            strategy,
            bundle=bundle,
            warnings=warnings,
            metadata=metadata or {},
            item_failures=tuple(item_failures),
            completion=completion,
            planned_provider_id=planned_provider_id,
            planned_provider_version=planned_provider_version,
            provider_id=provider_id,
            provider_version=provider_version,
            planned_scope=planned_scope,
            actual_scope=actual_scope,
            representation_id=representation_id,
            binding_digest=binding_digest,
            source_fingerprint=source_fingerprint,
        )

    @classmethod
    def failed(
        cls,
        strategy: AcquisitionStrategy | StrategyKind | str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
        item_failures: tuple[AcquisitionItemFailure | DownloadItemFailure, ...]
        | list[AcquisitionItemFailure | DownloadItemFailure] = (),
        completion: CompletionKind | None = None,
        planned_provider_id: str | None = None,
        planned_provider_version: str | None = None,
        provider_id: str | None = None,
        provider_version: str | None = None,
        planned_scope: CapabilityScope | None = None,
        actual_scope: CapabilityScope | None = None,
        representation_id: str | None = None,
        binding_digest: str | None = None,
        source_fingerprint: str | None = None,
    ) -> "AcquisitionResult":
        return cls(
            strategy,
            failure=AcquisitionFailure(
                code, message, retryable=retryable, details=details or {}
            ),
            item_failures=tuple(item_failures),
            completion=completion,
            planned_provider_id=planned_provider_id,
            planned_provider_version=planned_provider_version,
            provider_id=provider_id,
            provider_version=provider_version,
            planned_scope=planned_scope,
            actual_scope=actual_scope,
            representation_id=representation_id,
            binding_digest=binding_digest,
            source_fingerprint=source_fingerprint,
        )

    def to_dict(self, *, include_paths: bool = False) -> dict[str, Any]:
        planned_provider = None
        if self.planned_provider_id is not None:
            planned_provider = {
                "provider_id": self.planned_provider_id,
                "version": self.planned_provider_version,
            }
        provider = None
        if self.provider_id is not None:
            provider = {
                "provider_id": self.provider_id,
                "version": self.provider_version,
            }
        result: dict[str, Any] = {
            "ok": self.ok,
            "strategy": self.strategy.kind,
            "planned_provider": planned_provider,
            "provider": provider,
            "planned_scope": self.planned_scope,
            "actual_scope": self.actual_scope,
            "representation_id": self.representation_id,
            "binding_digest": self.binding_digest,
            "source_fingerprint": self.source_fingerprint,
            "warnings": list(self.warnings),
            "metadata": thaw(self.metadata),
            "item_failures": [item.to_dict() for item in self.item_failures],
        }
        if self.completion is not None:
            result["completion"] = self.completion
        if self.bundle is not None:
            result["bundle"] = self.bundle.to_dict(include_paths=include_paths)
        if self.failure is not None:
            result["failure"] = self.failure.to_dict()
        return result

    def to_json(self, *, include_paths: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_paths=include_paths),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


__all__ = [
    "ACQUISITION_STRATEGIES",
    "CAPABILITY_SCOPES",
    "ARTIFACT_ROLES",
    "ASSET_ROLES",
    "FORMAL_ARTIFACT_ROLES",
    "INTERNAL_ARTIFACT_ROLES",
    "MAX_ARTIFACTS",
    "PERSISTENT_ARTIFACT_ROLES",
    "AcquisitionFailure",
    "AcquisitionItemFailure",
    "AcquisitionRequest",
    "AcquisitionResult",
    "AcquisitionStrategy",
    "Artifact",
    "ArtifactBundle",
    "ArtifactRole",
    "DownloadItemFailure",
    "CapabilityScope",
    "CompletionKind",
    "InternalArtifactRole",
    "PersistentArtifactRole",
    "PreferredContainer",
    "StrategyKind",
    "thaw",
]
