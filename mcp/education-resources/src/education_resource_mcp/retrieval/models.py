"""Internal retrieval models.

The public MCP resource shape is intentionally small and continues to use the
server-issued ``resource_id``.  These dataclasses are the private vocabulary
used while a search result is being normalised, identified, and merged.  In
particular, a resource identity is not a public identifier and must never be
accepted from a model as an authority-bearing ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _as_dict(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy a mapping without retaining an adapter-owned mutable object."""

    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ResourceIdentity:
    """All identity evidence known for one logical resource.

    The fields are evidence, not a public resource ID.  ``kind``, ``value``
    and ``key`` expose the strongest available evidence according to the
    resolver's ordering: platform-native ID, ISBN, DOI, canonical URL, then
    weak title/creator/edition fingerprint.
    """

    platform: str = "generic"
    native_type: str | None = None
    native_id: str | None = None
    isbn: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    fingerprint: str | None = None

    @property
    def kind(self) -> str | None:
        if self.native_id:
            return "platform_id"
        if self.isbn:
            return "isbn"
        if self.doi:
            return "doi"
        if self.canonical_url:
            return "canonical_url"
        if self.fingerprint:
            return "fingerprint"
        return None

    @property
    def identity_type(self) -> str | None:
        """Readable alias for callers that use ``identity_type``."""

        return self.kind

    @property
    def type(self) -> str | None:
        """Compatibility alias matching the planning document's JSON sketch."""

        return self.kind

    @property
    def value(self) -> str | None:
        if self.native_id:
            return self.native_id
        if self.isbn:
            return self.isbn
        if self.doi:
            return self.doi
        if self.canonical_url:
            return self.canonical_url
        return self.fingerprint

    @property
    def strength(self) -> int:
        return {
            "platform_id": 500,
            "isbn": 400,
            "doi": 300,
            "canonical_url": 200,
            "fingerprint": 100,
        }.get(self.kind or "", 0)

    @property
    def is_strong(self) -> bool:
        return self.kind in {"platform_id", "isbn", "doi", "canonical_url"}

    @property
    def native_identity(self) -> dict[str, str] | None:
        if not self.native_id:
            return None
        result = {"type": "platform_id", "value": self.native_id}
        if self.native_type:
            result["native_type"] = self.native_type
        return result

    @property
    def key(self) -> tuple[str, ...] | None:
        """Return a hashable, namespaced key for the strongest evidence."""

        if self.native_id:
            return (
                "platform_id",
                self.platform or "generic",
                self.native_type or "id",
                self.native_id,
            )
        if self.isbn:
            return ("isbn", self.isbn)
        if self.doi:
            return ("doi", self.doi)
        if self.canonical_url:
            return ("canonical_url", self.canonical_url)
        if self.fingerprint:
            return ("fingerprint", self.fingerprint)
        return None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        platform: str = "generic",
    ) -> "ResourceIdentity":
        """Parse either the internal evidence shape or the JSON sketch.

        Normalisation of values belongs to :mod:`identity`; this method only
        makes hand-authored adapter evidence convenient to represent.
        """

        raw_platform = value.get("platform") or platform or "generic"
        raw_native = value.get("native_identity")
        native_type = value.get("native_type")
        native_id = value.get("native_id")
        if isinstance(raw_native, Mapping):
            native_type = native_type or raw_native.get("native_type")
            native_id = native_id or raw_native.get("native_id")
            kind = str(raw_native.get("type") or raw_native.get("kind") or "")
            raw_value = raw_native.get("value")
            if not native_id and raw_value is not None and kind in {
                "platform_id",
                "native_id",
                "native",
            }:
                native_id = raw_value
        elif raw_native is not None and native_id is None:
            native_id = raw_native
        if native_id is None and value.get("id") is not None:
            native_id = value.get("id")

        return cls(
            platform=str(raw_platform),
            native_type=str(native_type) if native_type else None,
            native_id=str(native_id) if native_id else None,
            isbn=str(value.get("isbn")) if value.get("isbn") else None,
            doi=str(value.get("doi")) if value.get("doi") else None,
            canonical_url=(
                str(value.get("canonical_url"))
                if value.get("canonical_url")
                else None
            ),
            fingerprint=(
                str(value.get("fingerprint"))
                if value.get("fingerprint")
                else None
            ),
        )

    def with_missing(self, other: "ResourceIdentity") -> "ResourceIdentity":
        """Fill absent evidence while retaining this identity's facts."""

        return ResourceIdentity(
            platform=self.platform or other.platform,
            native_type=self.native_type or other.native_type,
            native_id=self.native_id or other.native_id,
            isbn=self.isbn or other.isbn,
            doi=self.doi or other.doi,
            canonical_url=self.canonical_url or other.canonical_url,
            fingerprint=self.fingerprint or other.fingerprint,
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {"platform": self.platform}
        if self.native_id:
            result["native_identity"] = self.native_identity
        if self.isbn:
            result["isbn"] = self.isbn
        if self.doi:
            result["doi"] = self.doi
        if self.canonical_url:
            result["canonical_url"] = self.canonical_url
        if self.fingerprint:
            result["fingerprint"] = self.fingerprint
        return result


@dataclass(frozen=True)
class Representation:
    """A materialisable form of one logical resource."""

    representation_id: str = ""
    kind: str = "other"
    container: str | None = None
    mime_type: str | None = None
    role: str = "primary"
    language: str | None = None
    estimated_size_bytes: int | None = None
    availability: Any = None
    materializable: bool = False
    requires_auth: bool = False
    rights_hint: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Representation":
        return cls(
            representation_id=str(value.get("representation_id") or ""),
            kind=str(value.get("kind") or "other"),
            container=(str(value["container"]) if value.get("container") else None),
            mime_type=(str(value["mime_type"]) if value.get("mime_type") else None),
            role=str(value.get("role") or "primary"),
            language=(str(value["language"]) if value.get("language") else None),
            estimated_size_bytes=(
                int(value["estimated_size_bytes"])
                if value.get("estimated_size_bytes") is not None
                else None
            ),
            availability=value.get("availability"),
            materializable=bool(value.get("materializable")),
            requires_auth=bool(value.get("requires_auth")),
            rights_hint=(str(value["rights_hint"]) if value.get("rights_hint") else None),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "representation_id": self.representation_id,
            "kind": self.kind,
            "container": self.container,
            "mime_type": self.mime_type,
            "role": self.role,
            "language": self.language,
            "estimated_size_bytes": self.estimated_size_bytes,
            "availability": self.availability,
            "materializable": self.materializable,
            "requires_auth": self.requires_auth,
            "rights_hint": self.rights_hint,
        }


@dataclass
class CandidateResourceInternal:
    """A search candidate before detail inspection.

    ``resource_id`` is retained only for public-result compatibility.  The
    identity resolver deliberately ignores it when deciding whether two
    candidates are the same logical resource.
    """

    resource_id: str | None = None
    platform: str = "generic"
    resource_type: str = "other"
    title: str = ""
    canonical_url: str | None = None
    summary: str | None = None
    author: str | None = None
    creator: str | None = None
    published_at: str | None = None
    availability: Any = None
    native_identity: ResourceIdentity | Mapping[str, Any] | str | None = None
    native_type: str | None = None
    native_id: str | None = None
    isbn: str | None = None
    doi: str | None = None
    edition: str | None = None
    version: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    resolution_status: str = "candidate"
    representations: tuple[Representation, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandidateResourceInternal":
        metadata = _as_dict(value.get("metadata"))
        signals = _as_dict(value.get("signals"))
        direct_platform_signals = value.get("platform_signals")
        if isinstance(direct_platform_signals, Mapping):
            signals.update(direct_platform_signals)
        metadata_signals = metadata.get("platform_signals")
        if isinstance(metadata_signals, Mapping):
            signals = {**dict(metadata_signals), **signals}

        raw_representations = value.get("representations") or ()
        representations = tuple(
            item
            if isinstance(item, Representation)
            else Representation.from_mapping(item)
            for item in raw_representations
            if isinstance(item, (Representation, Mapping))
        )

        author = value.get("author") or value.get("creator")
        return cls(
            resource_id=(str(value["resource_id"]) if value.get("resource_id") else None),
            platform=str(value.get("platform") or value.get("platform_id") or "generic"),
            resource_type=str(value.get("resource_type") or value.get("type") or "other"),
            title=str(value.get("title") or value.get("name") or ""),
            canonical_url=(
                str(value.get("canonical_url") or value.get("source_url") or value.get("url"))
                if value.get("canonical_url") or value.get("source_url") or value.get("url")
                else None
            ),
            summary=(str(value["summary"]) if value.get("summary") else None),
            author=(str(author) if author else None),
            creator=(str(value["creator"]) if value.get("creator") else None),
            published_at=(
                str(value["published_at"]) if value.get("published_at") else None
            ),
            availability=value.get("availability"),
            native_identity=value.get("native_identity"),
            native_type=(str(value["native_type"]) if value.get("native_type") else None),
            native_id=(str(value["native_id"]) if value.get("native_id") else None),
            isbn=(str(value["isbn"]) if value.get("isbn") else None),
            doi=(str(value["doi"]) if value.get("doi") else None),
            edition=(str(value["edition"]) if value.get("edition") else None),
            version=(str(value["version"]) if value.get("version") else None),
            signals=signals,
            metadata=metadata,
            resolution_status=str(value.get("resolution_status") or "candidate"),
            representations=representations,
        )

    @property
    def identity(self) -> ResourceIdentity:
        """Resolve identity lazily to keep the model module dependency-free."""

        from .identity import resolve_identity

        return resolve_identity(self)

    def to_mapping(self) -> dict[str, Any]:
        """Map back to the legacy internal adapter shape.

        Internal identity fields are intentionally omitted from this mapping;
        callers must explicitly opt into them through :attr:`identity`.
        """

        metadata = dict(self.metadata)
        if self.signals:
            existing = metadata.get("platform_signals")
            if isinstance(existing, Mapping):
                metadata["platform_signals"] = {**dict(existing), **self.signals}
            else:
                metadata["platform_signals"] = dict(self.signals)
        result: dict[str, Any] = {
            "platform": self.platform,
            "title": self.title,
            "source_url": self.canonical_url or "",
            "resource_type": self.resource_type,
            "summary": self.summary,
            "metadata": metadata,
        }
        if self.resource_id:
            result["resource_id"] = self.resource_id
        return result


@dataclass
class ResolvedResource:
    """A candidate whose logical identity and detail metadata are resolved."""

    resource_id: str | None = None
    platform: str = "generic"
    resource_type: str = "other"
    title: str = ""
    canonical_url: str | None = None
    identity: ResourceIdentity | None = None
    creator: str | None = None
    description: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    availability: Any = None
    representations: tuple[Representation, ...] = ()
    resolution_status: str = "resolved"

    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateResourceInternal,
        *,
        identity: ResourceIdentity | None = None,
    ) -> "ResolvedResource":
        return cls(
            resource_id=candidate.resource_id,
            platform=candidate.platform,
            resource_type=candidate.resource_type,
            title=candidate.title,
            canonical_url=candidate.canonical_url,
            identity=identity or candidate.identity,
            creator=candidate.creator or candidate.author,
            description=candidate.summary,
            metadata=dict(candidate.metadata),
            availability=candidate.availability,
            representations=tuple(candidate.representations),
            resolution_status="resolved",
        )

    def to_mapping(self) -> dict[str, Any]:
        result = {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "platform": self.platform,
            "title": self.title,
            "canonical_url": self.canonical_url,
            "identity": self.identity.to_mapping() if self.identity else None,
            "creator": self.creator,
            "description": self.description,
            "language": self.language,
            "metadata": dict(self.metadata),
            "availability": self.availability,
            "representations": [item.to_mapping() for item in self.representations],
            "resolution_status": self.resolution_status,
        }
        return result


__all__ = [
    "CandidateResourceInternal",
    "Representation",
    "ResolvedResource",
    "ResourceIdentity",
]
