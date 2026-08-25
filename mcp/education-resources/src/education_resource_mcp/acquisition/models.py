"""Small execution models shared by download providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import threading
from typing import Any, Literal, Mapping


StrategyKind = Literal["direct_file", "web_materialize", "web_capture"]
AcquisitionScope = Literal["primary_resource", "representation", "landing_page", "metadata"]
PreferredContainer = Literal["original", "pdf", "epub", "mp4", "mp3", "m4a", "html", "text"]
ArtifactRole = str
CompletionKind = Literal["complete", "partial"]

ACQUISITION_SCOPES = frozenset(
    {"primary_resource", "representation", "landing_page", "metadata"}
)
ARTIFACT_ROLES = frozenset(
    {
        "primary", "subtitle", "cover", "metadata", "attachment", "transcript",
        "companion", "bundle", "markdown", "image", "sanitized_html",
    }
)
ASSET_ROLES = ARTIFACT_ROLES
FORMAL_ARTIFACT_ROLES = ARTIFACT_ROLES
INTERNAL_ARTIFACT_ROLES = frozenset({"bundle", "markdown", "image", "sanitized_html"})
PERSISTENT_ARTIFACT_ROLES = frozenset(
    {"primary", "subtitle", "cover", "metadata", "attachment", "transcript", "companion"}
)


class AcquisitionStrategy(str, Enum):
    DIRECT_FILE = "direct_file"
    WEB_MATERIALIZE = "web_materialize"
    WEB_CAPTURE = "web_capture"

    @property
    def kind(self) -> str:
        return self.value

    @classmethod
    def from_value(cls, value: "AcquisitionStrategy | str") -> "AcquisitionStrategy":
        if isinstance(value, cls):
            return value
        return cls(str(value))


ACQUISITION_STRATEGIES = frozenset(strategy.value for strategy in AcquisitionStrategy)


@dataclass(slots=True)
class AcquisitionRequest:
    """Facts needed by one concrete provider call."""

    job_id: str
    resource: Mapping[str, Any]
    strategy: AcquisitionStrategy | str
    provider_id: str
    scope: str
    representation_id: str
    preferred_container: str = "original"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    jobs_root: Path | None = None

    def __post_init__(self) -> None:
        self.strategy = AcquisitionStrategy.from_value(self.strategy)
        self.resource = dict(self.resource)
        if self.jobs_root is None:
            raise ValueError("jobs_root is required")
        self.jobs_root = self.jobs_root.resolve()

    @property
    def resource_id(self) -> str:
        return str(self.resource.get("resource_id") or "")

    def mutable_resource(self) -> dict[str, Any]:
        return dict(self.resource)


@dataclass(slots=True)
class Artifact:
    artifact_id: str
    role: str
    path: Path
    filename: str
    byte_size: int
    media_type: str
    sha256: str | None = None
    primary: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    required: bool = False
    item_key: str | None = None

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "role": self.role,
            "filename": self.filename,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "primary": self.primary,
            "metadata": dict(self.metadata),
            "required": self.required,
            "item_key": self.item_key,
        }
        if self.sha256 is not None:
            value["sha256"] = self.sha256
        if include_path:
            value["path"] = str(self.path)
        return value


@dataclass(slots=True)
class ArtifactBundle:
    artifacts: tuple[Artifact, ...]

    def __post_init__(self) -> None:
        self.artifacts = tuple(self.artifacts)

    @property
    def primary(self) -> Artifact | None:
        return next((artifact for artifact in self.artifacts if artifact.primary), None)


@dataclass(slots=True)
class AcquisitionFailure:
    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AcquisitionItemFailure:
    item_key: str
    code: str
    message: str
    role: str | None = None
    required: bool | None = None
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def retriable(self) -> bool:
        return self.retryable


@dataclass(slots=True)
class AcquisitionResult:
    strategy: AcquisitionStrategy
    bundle: ArtifactBundle | None = None
    failure: AcquisitionFailure | None = None
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    item_failures: tuple[AcquisitionItemFailure, ...] = ()
    completion: str = "complete"

    @property
    def ok(self) -> bool:
        return self.bundle is not None and self.failure is None

    @classmethod
    def success(
        cls,
        strategy: AcquisitionStrategy | str,
        bundle: ArtifactBundle,
        *,
        warnings: tuple[str, ...] = (),
        metadata: Mapping[str, Any] | None = None,
        item_failures: tuple[AcquisitionItemFailure, ...] = (),
        completion: str = "complete",
    ) -> "AcquisitionResult":
        return cls(
            AcquisitionStrategy.from_value(strategy),
            bundle=bundle,
            warnings=tuple(warnings),
            metadata=dict(metadata or {}),
            item_failures=tuple(item_failures),
            completion=completion,
        )

    @classmethod
    def failed(
        cls,
        strategy: AcquisitionStrategy | str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
        item_failures: tuple[AcquisitionItemFailure, ...] = (),
    ) -> "AcquisitionResult":
        return cls(
            AcquisitionStrategy.from_value(strategy),
            failure=AcquisitionFailure(
                str(code), str(message), bool(retryable), dict(details or {})
            ),
            item_failures=tuple(item_failures),
            completion="partial" if item_failures else "complete",
        )
