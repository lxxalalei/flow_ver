"""Strict loader for the internal platform capability registry.

The registry is an internal Retrieval-layer fact source.  It is deliberately
separate from :mod:`education_resource_mcp.sessions`, whose registry describes
only login/session probing.  This module uses the standard library so loading
the registry does not make ``jsonschema`` or any network service a runtime
requirement.

The JSON Schema beside the registry is the readable contract.  The validator
below mirrors that contract with explicit checks and adds the 1.0.0 semantic
invariants that JSON Schema alone cannot express: the exact active platform
set, unique IDs, capability boundaries, downloader truthfulness, and the
absence of credential/path material.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import copy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any


LEGACY_REGISTRY_VERSION = "1.0.0"
REGISTRY_VERSION = "1.1.0"
SUPPORTED_REGISTRY_VERSIONS = frozenset({LEGACY_REGISTRY_VERSION, REGISTRY_VERSION})
REGISTRY_SCHEMA_REFERENCE = "../schemas/platform-registry.schema.json"
_SERVICE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = _SERVICE_ROOT / "contracts" / "platforms" / "platform-registry.json"
DEFAULT_SCHEMA_PATH = _SERVICE_ROOT / "contracts" / "schemas" / "platform-registry.schema.json"

LEGAL_RESOURCE_TYPES = frozenset(
    {"article", "book", "document", "video", "audio", "course", "dataset", "other"}
)
EXPECTED_PLATFORM_IDS = frozenset(
    {
        "generic",
        "bilibili",
        "douyin",
        "zhihu",
        "smartedu",
        "ximalaya",
        "cctv",
        "yixi",
        "kepu",
        "baiduwenku",
        "runoob",
        "nlc",
        "open163",
        "annas-archive",
        "weibo",
        "wechat",
        "shuge",
    }
)
INSPECTION_PLATFORM_IDS = frozenset(
    {
        "generic",
        "bilibili",
        "douyin",
        "nlc",
        "annas-archive",
        "ximalaya",
        "zhihu",
        "smartedu",
        "shuge",
    }
)
CREATOR_BROWSE_PLATFORM_IDS = frozenset({"bilibili", "douyin", "zhihu", "weibo"})

_PLATFORM_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_NATIVE_ID_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_GENERIC_REMOVABLE_QUERY_PARAMETERS = frozenset(
    {
        "fbclid",
        "gclid",
        "msclkid",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)
_PLATFORM_REMOVABLE_QUERY_PARAMETERS: dict[str, frozenset[str]] = {
    "generic": _GENERIC_REMOVABLE_QUERY_PARAMETERS,
    "bilibili": frozenset({"from", "spm_id_from", "vd_source", "share_source", "share_medium"}),
    "douyin": frozenset({"from_tab", "previous_page", "mode", "enter_from", "share_token"}),
    "zhihu": frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}),
    "smartedu": frozenset(),
    "ximalaya": frozenset({"from", "source", "utm_source"}),
    "cctv": frozenset(),
    "yixi": frozenset(),
    "kepu": frozenset(),
    "baiduwenku": frozenset(),
    "runoob": frozenset(),
    "nlc": frozenset(),
    "open163": frozenset(),
    "annas-archive": frozenset(),
    "weibo": frozenset(),
    "wechat": frozenset(),
    "shuge": frozenset(),
}
_SAFE_QUERY_PARAMETERS = frozenset().union(*_PLATFORM_REMOVABLE_QUERY_PARAMETERS.values())
_SOURCE_TRAITS = frozenset(
    {
        "archive",
        "audio",
        "community",
        "creator",
        "document",
        "education",
        "government",
        "library",
        "media",
        "open_course",
        "reference",
        "search_engine",
        "video",
        "web",
    }
)
_AUTH_MODES = frozenset({"none", "optional", "required"})
_AUTH_KINDS = frozenset({"none", "cookie", "token"})
_ACQUISITION_STRATEGIES = frozenset(
    {"webpage", "platform_video", "platform_audio", "platform_resource", "platform_book"}
)
_SPECIALIZED_STRATEGY_PLATFORMS = {
    "platform_video": frozenset({"bilibili", "douyin"}),
    "platform_audio": frozenset({"ximalaya"}),
    "platform_resource": frozenset({"smartedu"}),
    "platform_book": frozenset({"annas-archive"}),
}
_IDENTITY_SOURCES = frozenset({"native_id", "isbn", "doi", "canonical_url"})
_WEAK_IDENTITY_FIELDS = frozenset({"title", "creator", "edition"})
_FORBIDDEN_KEY_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "browser_path",
    "command",
    "cookie",
    "credential",
    "download_url",
    "file_path",
    "local_path",
    "password",
    "private_key",
    "script",
    "secret",
    "session",
    "token",
)
_ABSOLUTE_PATH_PATTERN = re.compile(r"^(?:/|\\|~[/\\]|[A-Za-z]:[/\\])")

_TOP_LEVEL_KEYS = {"$schema", "registry_version", "platforms"}
_PLATFORM_KEYS = {
    "platform_id",
    "display_name",
    "resource_types",
    "capabilities",
    "auth_mode",
    "auth_kind",
    "source_traits",
    "search",
    "inspection",
    "acquisition",
    "identity_profile",
}
_CAPABILITY_KEYS = {"search", "browse_creator", "inspect", "acquire"}
_SEARCH_KEYS = {"enabled", "recommended_limit", "query_execution"}
_INSPECTION_KEYS = {"supported"}
_ACQUISITION_KEYS = {"strategies"}
_IDENTITY_KEYS = {
    "native_id_fields",
    "strong_identity_sources",
    "weak_identity_fields",
    "canonical_url",
}
_CANONICAL_URL_KEYS = {"remove_fragment", "removable_query_parameters"}

# 1.1 descriptor fields are deliberately optional in the public 1.0 schema.
# The loader accepts them as an internal compatibility extension until the
# contract/schema owner publishes the corresponding public schema.
_DESCRIPTOR_FLAT_KEYS = {
    "descriptor_id",
    "descriptor_version",
    "descriptor_digest",
    "capability_scope",
    "scope",
    "provider_id",
    "provider_version",
    "provider_scope",
    "inspector_id",
    "inspector_version",
    "inspector_scope",
    "representations",
    "representation",
    "strategy",
    "fallbacks",
    "fallback",
    "prerequisites",
    "policy_class",
    "source",
    "compatibility",
    "deprecated",
    "notes",
}
_DESCRIPTOR_BLOCK_KEYS = _DESCRIPTOR_FLAT_KEYS | {"provider", "inspector"}
_PLATFORM_KEYS_V11 = _PLATFORM_KEYS | {"descriptor"} | _DESCRIPTOR_FLAT_KEYS

_CAPABILITY_SCOPE_VALUES = frozenset(
    {
        # Platform-registry capability scopes.
        "search",
        "browse_creator",
        "inspect",
        "resolve",
        "acquire",
        "primary",
        "landing",
        "metadata",
        "materialize",
        "capture",
        # Contract/catalog capability scopes.  Both spellings are accepted
        # during migration; callers can use ``scope_for_contract`` to map
        # them to the singular persistence value.
        "primary_resource",
        "representation",
        "landing_page",
    }
)
_REPRESENTATION_KINDS = frozenset(
    {
        # Internal route/role spellings.
        "primary",
        "landing",
        "metadata",
        "materialized",
        "capture",
        # Contract representation kinds.
        "webpage",
        "document",
        "video",
        "audio",
        "image",
        "subtitle",
        "other",
    }
)
_REPRESENTATION_ROLES = frozenset({"primary", "landing", "metadata", "attachment", "companion"})
_READINESS_STATES = frozenset(
    {
        "ready",
        "degraded",
        "blocked",
        "experimental",
        "unsupported",
        "unavailable",
        "auth_required",
        "policy_blocked",
        "feature_not_supported",
        "missing_provider",
        "missing_inspector",
        "import_failed",
        "version_mismatch",
        "scope_mismatch",
        "legacy",
        "expired",
        "descriptor_changed",
        "not_checked",
        "unknown",
    }
)
_LOAD_STATUS_VALUES = frozenset({"loaded", "partially_loaded", "not_loaded", "failed"})
_CREDENTIAL_POSTURE_VALUES = frozenset({
    "none",
    "optional_missing",
    "optional_present",
    "required_present",
    "required_missing",
    "invalid",
})
_NETWORK_POLICY_STATUS_VALUES = frozenset({
    "not_required",
    "allowed",
    "restricted",
    "blocked",
    "unknown",
})
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_DIGEST_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


class PlatformRegistryError(ValueError):
    """Raised when the platform registry is missing, malformed, or unsafe."""


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Immutable static capability facts for one platform or route.

    The descriptor is intentionally a *declaration*, not a readiness or
    candidate-resolution result.  In particular, ``legacy_descriptor`` is
    true for 1.0 entries and such descriptors never expose a provider or a
    concrete ``primary`` representation.
    """

    descriptor_id: str
    descriptor_version: str
    descriptor_digest: str
    registry_version: str
    platform_id: str
    resource_types: tuple[str, ...]
    capability_scope: tuple[str, ...]
    acquisition_strategies: tuple[str, ...]
    provider_id: str | None = None
    provider_version: str | None = None
    provider_scope: tuple[str, ...] = ()
    inspector_id: str | None = None
    inspector_version: str | None = None
    inspector_scope: tuple[str, ...] = ()
    representations: tuple[Mapping[str, Any], ...] = ()
    fallbacks: tuple[Mapping[str, Any], ...] = ()
    legacy_descriptor: bool = False
    source: Mapping[str, Any] | None = None
    # Optional catalog-level authority metadata.  Legacy platform entries do
    # not have these fields; new descriptors preserve them immutably when
    # present so service/storage layers can bind policy and compatibility
    # without reparsing raw registry JSON.
    strategy: str | None = None
    prerequisites: Mapping[str, Any] | None = None
    policy_class: str | None = None
    source_metadata: Mapping[str, Any] | None = None
    compatibility: Mapping[str, Any] | None = None
    deprecated: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "descriptor_id",
            "descriptor_version",
            "descriptor_digest",
            "registry_version",
            "platform_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise PlatformRegistryError(f"descriptor.{field_name}: must be a non-empty string")
            if any(ord(char) < 32 for char in value):
                raise PlatformRegistryError(f"descriptor.{field_name}: must be printable")
        if _VERSION_PATTERN.fullmatch(self.descriptor_version) is None:
            raise PlatformRegistryError("descriptor.descriptor_version: invalid version")
        digest = self.descriptor_digest
        if isinstance(digest, str) and digest.startswith("sha256:"):
            digest = digest[7:]
        if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
            raise PlatformRegistryError("descriptor.descriptor_digest: must be a lowercase SHA-256 digest")
        object.__setattr__(self, "descriptor_digest", digest)
        if self.registry_version not in SUPPORTED_REGISTRY_VERSIONS:
            raise PlatformRegistryError("descriptor.registry_version: unsupported registry version")
        for field_name in (
            "resource_types",
            "capability_scope",
            "acquisition_strategies",
            "provider_scope",
            "inspector_scope",
        ):
            values = getattr(self, field_name)
            if isinstance(values, (str, bytes, bytearray)):
                raise PlatformRegistryError(f"descriptor.{field_name}: must be a sequence")
            normalized = tuple(str(value) for value in values)
            if len(set(normalized)) != len(normalized):
                raise PlatformRegistryError(f"descriptor.{field_name}: duplicate values")
            object.__setattr__(self, field_name, normalized)
        if any(scope not in _CAPABILITY_SCOPE_VALUES for scope in self.capability_scope):
            raise PlatformRegistryError("descriptor.capability_scope: unknown scope")
        if any(scope not in _CAPABILITY_SCOPE_VALUES for scope in self.provider_scope):
            raise PlatformRegistryError("descriptor.provider_scope: unknown scope")
        if any(scope not in _CAPABILITY_SCOPE_VALUES for scope in self.inspector_scope):
            raise PlatformRegistryError("descriptor.inspector_scope: unknown scope")
        if self.provider_id is not None and (not isinstance(self.provider_id, str) or not self.provider_id):
            raise PlatformRegistryError("descriptor.provider_id: must be a non-empty string")
        if self.provider_version is not None and _VERSION_PATTERN.fullmatch(self.provider_version) is None:
            raise PlatformRegistryError("descriptor.provider_version: invalid version")
        if self.inspector_id is not None and (not isinstance(self.inspector_id, str) or not self.inspector_id):
            raise PlatformRegistryError("descriptor.inspector_id: must be a non-empty string")
        if self.inspector_version is not None and _VERSION_PATTERN.fullmatch(self.inspector_version) is None:
            raise PlatformRegistryError("descriptor.inspector_version: invalid version")
        object.__setattr__(self, "representations", tuple(_freeze_json(item) for item in self.representations))
        object.__setattr__(self, "fallbacks", tuple(_freeze_json(item) for item in self.fallbacks))
        if self.source is not None:
            object.__setattr__(self, "source", _freeze_json(self.source))
        for field_name in ("prerequisites", "source_metadata", "compatibility"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, Mapping):
                    raise PlatformRegistryError(f"descriptor.{field_name}: must be an object")
                object.__setattr__(self, field_name, _freeze_json(value))
        if self.strategy is not None:
            if not isinstance(self.strategy, str) or not self.strategy:
                raise PlatformRegistryError("descriptor.strategy: must be a non-empty string")
        if self.policy_class is not None:
            if not isinstance(self.policy_class, str) or not self.policy_class:
                raise PlatformRegistryError("descriptor.policy_class: must be a non-empty string")
        if self.notes is not None and not isinstance(self.notes, str):
            raise PlatformRegistryError("descriptor.notes: must be a string")
        if not isinstance(self.deprecated, bool):
            raise PlatformRegistryError("descriptor.deprecated: must be boolean")

    @property
    def scope(self) -> tuple[str, ...]:
        """Alias used by callers that call capability scope simply ``scope``."""

        return self.capability_scope
    @property
    def capability_id(self) -> str:
        """Contract alias for the descriptor identifier."""

        return self.descriptor_id

    @property
    def descriptor_digest_sha256(self) -> str:
        """Canonical-digest spelling used by the public JSON contracts."""

        return f"sha256:{self.descriptor_digest}"

    @property
    def scope_for_contract(self) -> str:
        """Map internal multi-scope declarations to a persistence scope."""

        scopes = set(self.capability_scope)
        if "primary_resource" in scopes or "primary" in scopes:
            return "primary_resource"
        if "landing_page" in scopes or "landing" in scopes:
            return "landing_page"
        if "metadata" in scopes:
            return "metadata"
        return "representation"

    @property
    def representation(self) -> Mapping[str, Any] | None:
        """First representation for catalog-style single-representation callers."""

        return self.representations[0] if self.representations else None

    @property
    def fallback(self) -> Mapping[str, Any] | None:
        return self.fallbacks[0] if self.fallbacks else None
    def matches(
        self,
        *,
        resource_type: str | None = None,
        scope: str | Iterable[str] | None = None,
        representation_kind: str | None = None,
        strategy: str | None = None,
    ) -> bool:
        """Return whether this descriptor supports the requested dimensions."""

        if resource_type is not None and resource_type not in self.resource_types:
            return False
        if strategy is not None and strategy not in self.acquisition_strategies:
            return False
        if scope is not None:
            requested = (scope,) if isinstance(scope, str) else tuple(scope)
            if any(item not in self.capability_scope for item in requested):
                return False
        if representation_kind is not None:
            return any(
                isinstance(item, Mapping)
                and (
                    str(item.get("role") or "") == representation_kind
                    or str(item.get("kind") or "") == representation_kind
                )
                for item in self.representations
            )
        return True

    supports = matches

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        """Return a JSON-safe copy suitable for audit/logging boundaries."""

        value: dict[str, Any] = {
            "descriptor_id": self.descriptor_id,
            "descriptor_version": self.descriptor_version,
            "descriptor_digest": self.descriptor_digest,
            "registry_version": self.registry_version,
            "platform_id": self.platform_id,
            "resource_types": list(self.resource_types),
            "capability_scope": list(self.capability_scope),
            "acquisition_strategies": list(self.acquisition_strategies),
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_scope": list(self.provider_scope),
            "inspector_id": self.inspector_id,
            "inspector_version": self.inspector_version,
            "inspector_scope": list(self.inspector_scope),
            "representations": [_json_safe(item) for item in self.representations],
            "fallbacks": [_json_safe(item) for item in self.fallbacks],
            "legacy_descriptor": self.legacy_descriptor,
        }
        if include_source and self.source is not None:
            value["source"] = _json_safe(self.source)
        if self.strategy is not None:
            value["strategy"] = self.strategy
        if self.prerequisites is not None:
            value["prerequisites"] = _json_safe(self.prerequisites)
        if self.policy_class is not None:
            value["policy_class"] = self.policy_class
        if self.source_metadata is not None:
            value["source_metadata"] = _json_safe(self.source_metadata)
        if self.compatibility is not None:
            value["compatibility"] = _json_safe(self.compatibility)
        if self.deprecated:
            value["deprecated"] = True
        if self.notes is not None:
            value["notes"] = self.notes
        return value

    def __hash__(self) -> int:
        return hash(_canonical_json(self.to_dict(include_source=False)))


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    """Runtime loading/readiness facts for one static descriptor."""

    snapshot_id: str
    descriptor_id: str
    descriptor_version: str
    descriptor_digest: str
    platform_id: str
    status: str
    checked_at: str
    expires_at: str | None
    provider_id: str | None = None
    provider_version: str | None = None
    inspector_id: str | None = None
    inspector_version: str | None = None
    scope: tuple[str, ...] = ()
    issues: tuple[Mapping[str, Any], ...] = ()
    legacy_descriptor: bool = False
    # Optional persistence/catalog aliases populated when a RegistrySnapshot
    # is available.  They remain optional for isolated legacy probes.
    registry_digest: str | None = None
    registry_version: str | None = None
    capability_scope: str | None = None
    strategy: str | None = None
    snapshot_digest: str | None = None
    load_status: str | None = None
    dependency_checks: tuple[Mapping[str, Any], ...] = ()
    credential_posture: str | None = None
    network_policy_status: str | None = None
    policy_profile: str | None = None
    fallback_capability_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise PlatformRegistryError("readiness.snapshot_id: must be a non-empty string")
        if not isinstance(self.descriptor_id, str) or not self.descriptor_id:
            raise PlatformRegistryError("readiness.descriptor_id: must be a non-empty string")
        if not isinstance(self.descriptor_version, str) or _VERSION_PATTERN.fullmatch(self.descriptor_version) is None:
            raise PlatformRegistryError("readiness.descriptor_version: invalid version")
        if not isinstance(self.platform_id, str) or not self.platform_id:
            raise PlatformRegistryError("readiness.platform_id: must be a non-empty string")
        if self.status not in _READINESS_STATES:
            raise PlatformRegistryError(f"readiness.status: unsupported state {self.status!r}")
        object.__setattr__(self, "descriptor_digest", _normalize_digest(self.descriptor_digest, "readiness.descriptor_digest"))
        if self.registry_digest is not None:
            object.__setattr__(self, "registry_digest", _normalize_digest(self.registry_digest, "readiness.registry_digest"))
        if self.registry_version is not None:
            if not isinstance(self.registry_version, str) or self.registry_version not in SUPPORTED_REGISTRY_VERSIONS:
                raise PlatformRegistryError("readiness.registry_version: unsupported version")
        if isinstance(self.scope, str):
            object.__setattr__(self, "scope", (self.scope,))
        elif not isinstance(self.scope, tuple):
            object.__setattr__(self, "scope", tuple(self.scope))
        normalized_scope = tuple(str(value) for value in self.scope)
        if len(set(normalized_scope)) != len(normalized_scope):
            raise PlatformRegistryError("readiness.scope: duplicate values")
        object.__setattr__(self, "scope", normalized_scope)
        if self.capability_scope is None and self.scope:
            scopes = set(self.scope)
            if "primary_resource" in scopes or "primary" in scopes:
                object.__setattr__(self, "capability_scope", "primary_resource")
            elif "landing_page" in scopes or "landing" in scopes:
                object.__setattr__(self, "capability_scope", "landing_page")
            elif "metadata" in scopes:
                object.__setattr__(self, "capability_scope", "metadata")
            else:
                object.__setattr__(self, "capability_scope", "representation")
        if self.capability_scope is not None and self.capability_scope not in {"primary_resource", "representation", "landing_page", "metadata"}:
            raise PlatformRegistryError("readiness.capability_scope: unsupported scope")
        if self.strategy is not None and (not isinstance(self.strategy, str) or not self.strategy):
            raise PlatformRegistryError("readiness.strategy: must be a non-empty string")
        if self.load_status is not None and self.load_status not in _LOAD_STATUS_VALUES:
            raise PlatformRegistryError("readiness.load_status: unsupported state")
        if self.credential_posture is not None and self.credential_posture not in _CREDENTIAL_POSTURE_VALUES:
            raise PlatformRegistryError("readiness.credential_posture: unsupported state")
        if self.network_policy_status is not None and self.network_policy_status not in _NETWORK_POLICY_STATUS_VALUES:
            raise PlatformRegistryError("readiness.network_policy_status: unsupported state")
        if self.policy_profile is not None and (not isinstance(self.policy_profile, str) or not self.policy_profile):
            raise PlatformRegistryError("readiness.policy_profile: must be a non-empty string")
        if not isinstance(self.expires_at, (str, type(None))):
            raise PlatformRegistryError("readiness.expires_at: must be an ISO timestamp or null")
        object.__setattr__(self, "issues", tuple(_freeze_json(item) for item in self.issues))
        object.__setattr__(self, "dependency_checks", tuple(_freeze_json(item) for item in self.dependency_checks))
        normalized_fallbacks = tuple(str(value) for value in self.fallback_capability_ids)
        if len(set(normalized_fallbacks)) != len(normalized_fallbacks):
            raise PlatformRegistryError("readiness.fallback_capability_ids: duplicate values")
        object.__setattr__(self, "fallback_capability_ids", normalized_fallbacks)
        if self.snapshot_digest is not None:
            object.__setattr__(self, "snapshot_digest", _normalize_digest(self.snapshot_digest, "readiness.snapshot_digest"))
        else:
            # Compute from the stable storage-shaped authority fields.
            # ``snapshot_digest`` itself is intentionally excluded from the
            # preimage; all richer deployment metadata remains audit-only and
            # does not alter the persistence digest.
            material = {
                "readiness_snapshot_id": self.snapshot_id,
                "capability_id": self.descriptor_id,
                "descriptor_version": self.descriptor_version,
                "descriptor_digest": self.descriptor_digest_sha256,
                "registry_version": self.registry_version,
                "registry_digest": self.registry_digest_sha256 if self.registry_digest else None,
                "platform_id": self.platform_id,
                "capability_scope": self.capability_scope,
                "strategy": self.strategy,
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "inspector_id": self.inspector_id,
                "inspector_version": self.inspector_version,
                "status": self.status,
                "issues": self.issues,
                "observed_at": self.checked_at,
                "expires_at": self.expires_at,
            }
            object.__setattr__(self, "snapshot_digest", hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest())

    @property
    def ready(self) -> bool:
        """Only an explicit non-legacy ready snapshot is usable."""

        return self.status == "ready" and not self.legacy_descriptor

    @property
    def readiness_id(self) -> str:
        return self.snapshot_id

    @property
    def capability_id(self) -> str:
        return self.descriptor_id

    @property
    def descriptor_digest_sha256(self) -> str:
        return f"sha256:{self.descriptor_digest}"

    @property
    def registry_digest_sha256(self) -> str:
        return f"sha256:{self.registry_digest}" if self.registry_digest else ""
    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "readiness_id": self.readiness_id,
            "readiness_snapshot_id": self.readiness_id,
            "capability_id": self.capability_id,
            "descriptor_id": self.descriptor_id,
            "descriptor_version": self.descriptor_version,
            "descriptor_digest": self.descriptor_digest,
            "registry_version": self.registry_version,
            "registry_digest": self.registry_digest,
            "snapshot_digest": self.snapshot_digest,
            "platform_id": self.platform_id,
            "capability_scope": self.capability_scope,
            "strategy": self.strategy,
            "status": self.status,
            "ready": self.ready,
            "checked_at": self.checked_at,
            "observed_at": self.checked_at,
            "expires_at": self.expires_at,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "inspector_id": self.inspector_id,
            "inspector_version": self.inspector_version,
            "scope": list(self.scope),
            "issues": [_json_safe(item) for item in self.issues],
            "load_status": self.load_status,
            "dependency_checks": [_json_safe(item) for item in self.dependency_checks],
            "credential_posture": self.credential_posture,
            "network_policy_status": self.network_policy_status,
            "policy_profile": self.policy_profile,
            "fallback_capability_ids": list(self.fallback_capability_ids),
            "legacy_descriptor": self.legacy_descriptor,
        }


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Immutable registry plus descriptor query facade."""

    registry_version: str
    registry_digest: str
    descriptors: tuple[CapabilityDescriptor, ...]
    source: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.registry_version not in SUPPORTED_REGISTRY_VERSIONS:
            raise PlatformRegistryError("snapshot.registry_version: unsupported version")
        object.__setattr__(self, "descriptors", tuple(self.descriptors))
        if self.source is not None:
            object.__setattr__(self, "source", _freeze_json(self.source))

    def descriptor_for(
        self,
        platform_id: str,
        *,
        resource_type: str | None = None,
        scope: str | Iterable[str] | None = None,
        representation_kind: str | None = None,
        strategy: str | None = None,
    ) -> CapabilityDescriptor:
        candidates = self.query(
            platform_id=platform_id,
            resource_type=resource_type,
            scope=scope,
            representation_kind=representation_kind,
            strategy=strategy,
        )
        if not candidates:
            raise PlatformRegistryError(f"descriptor query matched no route for {platform_id!r}")
        return candidates[0]

    def query(
        self,
        *,
        platform_id: str | None = None,
        resource_type: str | None = None,
        scope: str | Iterable[str] | None = None,
        representation_kind: str | None = None,
        strategy: str | None = None,
    ) -> tuple[CapabilityDescriptor, ...]:
        if representation_kind is not None and representation_kind not in _REPRESENTATION_KINDS:
            return ()
        return tuple(
            descriptor
            for descriptor in self.descriptors
            if (platform_id is None or descriptor.platform_id == platform_id)
            and descriptor.matches(
                resource_type=resource_type,
                scope=scope,
                representation_kind=representation_kind,
                strategy=strategy,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        value = {
            "registry_version": self.registry_version,
            "registry_digest": self.registry_digest,
            "descriptors": [descriptor.to_dict() for descriptor in self.descriptors],
        }
        if self.source is not None:
            value["source"] = _json_safe(self.source)
        return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(child) for child in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_json(child) for child in value)
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(child) for child in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_digest(value: Any, path: str) -> str:
    text = _require_string(value, path)
    if text.startswith("sha256:"):
        text = text[7:]
    if _DIGEST_PATTERN.fullmatch(text) is None:
        _fail(path, "must be a lowercase SHA-256 digest (optionally prefixed sha256:)")
    return text


def canonical_descriptor_digest(value: Mapping[str, Any] | CapabilityDescriptor) -> str:
    """Compute a stable SHA-256 digest for descriptor-shaped JSON.

    ``descriptor_digest`` itself is excluded to avoid a self-referential hash.
    Key order, whitespace, and mutable/list-vs-tuple representation do not
    affect the result.
    """

    if isinstance(value, CapabilityDescriptor):
        material = value.to_dict(include_source=False)
        material.pop("descriptor_digest", None)
    elif isinstance(value, Mapping):
        material = copy.deepcopy(_json_safe(value))
        material.pop("descriptor_digest", None)
        if isinstance(material.get("descriptor"), Mapping):
            nested = dict(material["descriptor"])
            nested.pop("descriptor_digest", None)
            material["descriptor"] = nested
    else:
        raise TypeError("descriptor digest input must be a mapping or CapabilityDescriptor")
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _utc_now(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(raw)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise TypeError("now must be a datetime, ISO timestamp, or None")


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _issue(code: str, message: str, *, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    if detail:
        value["detail"] = _json_safe(detail)
    return value


def _fail(path: str, message: str) -> None:
    raise PlatformRegistryError(f"{path}: {message}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        _fail(path, "unexpected object shape (" + ", ".join(details) + ")")


def _require_string(value: Any, path: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if not value or "\x00" in value or any(ord(char) < 32 for char in value):
        _fail(path, "must be a non-empty printable string")
    if pattern is not None and pattern.fullmatch(value) is None:
        _fail(path, "has an invalid format")
    if _ABSOLUTE_PATH_PATTERN.match(value) or value.lower().startswith(("file:", "data:")):
        _fail(path, "must not contain an absolute path or local data URI")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail(path, "must be a boolean")
    return value


def _require_integer(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(path, f"must be an integer between {minimum} and {maximum}")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    return value


def _require_unique(values: Sequence[Any], path: str) -> None:
    try:
        unique_count = len(set(values))
    except TypeError:
        _fail(path, "must contain scalar values")
    if unique_count != len(values):
        _fail(path, "must not contain duplicates")


def _reject_security_material(value: Any, path: str = "registry") -> None:
    """Reject credential-like keys and local-file material recursively.

    The schema already forbids unknown keys.  Keeping this independent check
    makes the security boundary explicit and protects callers that use the
    semantic validator with a future schema extension.
    """

    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                normalized_key = key.lower().replace("-", "_")
                # Match forbidden material at field-token boundaries.  A raw
                # substring check would reject legitimate descriptor fields
                # such as ``descriptor_id`` because ``descriptor`` contains
                # the letters ``script``.
                forbidden = any(
                    normalized_key == part
                    or normalized_key.startswith(f"{part}_")
                    or normalized_key.endswith(f"_{part}")
                    or f"_{part}_" in normalized_key
                    for part in _FORBIDDEN_KEY_PARTS
                )
                if forbidden:
                    _fail(f"{path}.{key}", "credential, session, command, or path fields are not allowed")
            _reject_security_material(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_security_material(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        _require_string(value, path)


def _validate_schema_document(schema: Mapping[str, Any]) -> None:
    """Check the local schema has the strict root and definitions we rely on."""

    _require_mapping(schema, "schema")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        _fail("schema.$schema", "must use JSON Schema draft 2020-12")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        _fail("schema", "root must be a closed object schema")
    required = schema.get("required")
    if required != ["$schema", "registry_version", "platforms"]:
        _fail("schema.required", "does not match the registry contract")
    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping):
        _fail("schema.$defs", "must define registry object types")
    for name in (
        "platform_id",
        "resource_type",
        "capabilities",
        "search",
        "inspection",
        "acquisition",
        "canonical_url",
        "identity_profile",
        "platform",
    ):
        if name not in definitions or not isinstance(definitions[name], Mapping):
            _fail(f"schema.$defs.{name}", "is missing or malformed")


def _validate_capability_schema_document(schema: Mapping[str, Any]) -> None:
    """Validate the standalone capability-descriptor catalog schema shape."""

    _require_mapping(schema, "schema")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        _fail("schema.$schema", "must use JSON Schema draft 2020-12")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        _fail("schema", "root must be a closed object schema")
    required = schema.get("required")
    if not isinstance(required, list) or "descriptors" not in required or "registry_version" not in required:
        _fail("schema.required", "must require descriptors and registry_version")



def _validate_canonical_url(value: Any, path: str, platform_id: str) -> None:
    canonical = _require_mapping(value, path)
    _require_exact_keys(canonical, _CANONICAL_URL_KEYS, path)
    if not _require_bool(canonical["remove_fragment"], f"{path}.remove_fragment"):
        _fail(f"{path}.remove_fragment", "must be true; fragment removal is the only global URL normalization")
    parameters = _require_list(canonical["removable_query_parameters"], f"{path}.removable_query_parameters")
    _require_unique(parameters, f"{path}.removable_query_parameters")
    for index, parameter in enumerate(parameters):
        name = _require_string(parameter, f"{path}.removable_query_parameters[{index}]")
        if name not in _SAFE_QUERY_PARAMETERS:
            _fail(f"{path}.removable_query_parameters[{index}]", "is not an approved tracking parameter")
    expected = _PLATFORM_REMOVABLE_QUERY_PARAMETERS.get(platform_id, frozenset())
    if set(parameters) != expected:
        _fail(
            f"{path}.removable_query_parameters",
            f"must equal the audited query-key set for {platform_id!r}; "
            f"expected={sorted(expected)}, actual={sorted(parameters)}",
        )


def _validate_identity_profile(value: Any, path: str, platform_id: str) -> None:
    profile = _require_mapping(value, path)
    _require_exact_keys(profile, _IDENTITY_KEYS, path)

    native_fields = _require_list(profile["native_id_fields"], f"{path}.native_id_fields")
    _require_unique(native_fields, f"{path}.native_id_fields")
    for index, field in enumerate(native_fields):
        _require_string(field, f"{path}.native_id_fields[{index}]", pattern=_NATIVE_ID_FIELD_PATTERN)

    strong_sources = _require_list(profile["strong_identity_sources"], f"{path}.strong_identity_sources")
    _require_unique(strong_sources, f"{path}.strong_identity_sources")
    if set(strong_sources) != _IDENTITY_SOURCES:
        _fail(
            f"{path}.strong_identity_sources",
            "must cover native_id, isbn, doi, and canonical_url exactly once",
        )

    weak_fields = _require_list(profile["weak_identity_fields"], f"{path}.weak_identity_fields")
    _require_unique(weak_fields, f"{path}.weak_identity_fields")
    if set(weak_fields) != _WEAK_IDENTITY_FIELDS:
        _fail(f"{path}.weak_identity_fields", "must cover title, creator, and edition")

    _validate_canonical_url(profile["canonical_url"], f"{path}.canonical_url", platform_id)


def _pick_descriptor_value(
    direct: Mapping[str, Any],
    block: Mapping[str, Any],
    name: str,
    path: str,
    *,
    aliases: Sequence[str] = (),
) -> Any:
    names = (name, *aliases)
    direct_values = [direct[item] for item in names if item in direct]
    block_values = [block[item] for item in names if item in block]
    values = direct_values + block_values
    if direct_values and block_values and any(value != direct_values[0] for value in block_values):
        _fail(path, f"conflicting descriptor values for {name!r}")
    if len(values) > 1 and any(value != values[0] for value in values[1:]):
        _fail(path, f"conflicting descriptor aliases for {name!r}")
    return values[0] if values else None


def _validate_scope(value: Any, path: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None:
        if required:
            _fail(path, "must be declared for a 1.1 descriptor")
        return ()
    values = [value] if isinstance(value, str) else _require_list(value, path)
    _require_unique(values, path)
    result: list[str] = []
    for index, item in enumerate(values):
        text = _require_string(item, f"{path}[{index}]")
        if text not in _CAPABILITY_SCOPE_VALUES:
            _fail(f"{path}[{index}]", f"unsupported capability scope {text!r}")
        result.append(text)
    return tuple(result)


def _validate_version(value: Any, path: str) -> str:
    text = _require_string(value, path)
    if _VERSION_PATTERN.fullmatch(text) is None:
        _fail(path, "must be a semantic version")
    return text


def _validate_representations(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    items = [value] if isinstance(value, Mapping) else _require_list(value, path)
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(items):
        mapping = _require_mapping(item, f"{path}[{index}]")
        allowed = {"kind", "role", "concrete", "mime_types", "containers", "scope", "materializable"}
        unknown = set(mapping) - allowed
        if unknown:
            _fail(f"{path}[{index}]", f"unknown representation fields: {sorted(unknown)}")
        raw_kind = mapping.get("kind")
        raw_role = mapping.get("role")
        if raw_kind is None and raw_role is None:
            _fail(f"{path}[{index}]", "must declare kind or role")
        kind = _require_string(raw_kind if raw_kind is not None else raw_role, f"{path}[{index}].kind")
        if kind not in _REPRESENTATION_KINDS:
            _fail(f"{path}[{index}].kind", f"unsupported representation kind {kind!r}")
        normalized = dict(mapping)
        normalized["kind"] = kind
        if raw_role is not None:
            role = _require_string(raw_role, f"{path}[{index}].role")
            if role not in _REPRESENTATION_ROLES:
                _fail(f"{path}[{index}].role", f"unsupported representation role {role!r}")
            normalized["role"] = role
        if "concrete" in normalized:
            _require_bool(normalized["concrete"], f"{path}[{index}].concrete")
        for key in ("mime_types", "containers", "scope"):
            if key in normalized:
                _validate_scope(normalized[key], f"{path}[{index}].{key}") if key == "scope" else _validate_string_list(normalized[key], f"{path}[{index}].{key}")
        if "materializable" in normalized:
            _require_bool(normalized["materializable"], f"{path}[{index}].materializable")
        result.append(normalized)
    kinds = [str(item["kind"]) for item in result]
    if len(set(kinds)) != len(kinds):
        _fail(path, "must not declare duplicate representation kinds")
    return tuple(result)


def _validate_string_list(value: Any, path: str) -> tuple[str, ...]:
    values = _require_list(value, path)
    _require_unique(values, path)
    result: list[str] = []
    for index, item in enumerate(values):
        result.append(_require_string(item, f"{path}[{index}]"))
    return tuple(result)


def _validate_fallbacks(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    # Catalog descriptors use one policy-shaped fallback object; platform
    # entries use a list of provider fallback declarations.  Preserve either
    # shape as an immutable tuple for callers and reject unknown fields.
    if isinstance(value, Mapping):
        mapping = _require_mapping(value, path)
        if "allowed" in mapping or "max_scope" in mapping or "allowed_scopes" in mapping:
            unknown = set(mapping) - {"allowed", "max_scope", "allowed_scopes", "on_errors", "scope_preserving"}
            if unknown:
                _fail(path, f"unknown fallback fields: {sorted(unknown)}")
            normalized = dict(mapping)
            if "allowed" in normalized:
                normalized["allowed"] = _require_bool(normalized["allowed"], f"{path}.allowed")
            if "max_scope" in normalized:
                normalized["max_scope"] = _validate_scope(normalized["max_scope"], f"{path}.max_scope")[0]
            if "allowed_scopes" in normalized:
                normalized["allowed_scopes"] = list(_validate_scope(normalized["allowed_scopes"], f"{path}.allowed_scopes"))
            if "on_errors" in normalized:
                normalized["on_errors"] = list(_validate_string_list(normalized["on_errors"], f"{path}.on_errors"))
            if "scope_preserving" in normalized:
                normalized["scope_preserving"] = _require_bool(normalized["scope_preserving"], f"{path}.scope_preserving")
            return (normalized,)
        # A single provider fallback object is accepted as a one-element list.
        items: list[Any] = [mapping]
    else:
        items = _require_list(value, path)
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            item = {"provider_id": item}
        mapping = _require_mapping(item, f"{path}[{index}]")
        unknown = set(mapping) - {"provider_id", "provider_version", "scope", "reason"}
        if unknown:
            _fail(f"{path}[{index}]", f"unknown fallback fields: {sorted(unknown)}")
        provider_id = mapping.get("provider_id")
        if provider_id is None:
            _fail(f"{path}[{index}].provider_id", "is required")
        normalized = dict(mapping)
        normalized["provider_id"] = _require_string(provider_id, f"{path}[{index}].provider_id")
        if "provider_version" in normalized:
            normalized["provider_version"] = _validate_version(normalized["provider_version"], f"{path}[{index}].provider_version")
        if "scope" in normalized:
            normalized["scope"] = list(_validate_scope(normalized["scope"], f"{path}[{index}].scope"))
        result.append(normalized)
    return tuple(result)


def _descriptor_from_entry(item: Mapping[str, Any], registry_version: str, path: str) -> CapabilityDescriptor:
    """Normalize a validated 1.0/1.1 platform entry into a descriptor."""

    platform_id = _require_string(item["platform_id"], f"{path}.platform_id", pattern=_PLATFORM_ID_PATTERN)
    block_value = item.get("descriptor")
    block = _require_mapping(block_value, f"{path}.descriptor") if block_value is not None else {}
    unknown_block = set(block) - _DESCRIPTOR_BLOCK_KEYS
    if unknown_block:
        _fail(f"{path}.descriptor", f"unknown descriptor fields: {sorted(unknown_block)}")
    legacy = registry_version == LEGACY_REGISTRY_VERSION and not block and not any(key in item for key in _DESCRIPTOR_FLAT_KEYS)
    if registry_version == LEGACY_REGISTRY_VERSION and (block or any(key in item for key in _DESCRIPTOR_FLAT_KEYS)):
        # A descriptor-bearing entry opts into the stricter 1.1 rules even if
        # an older registry_version was left in place during migration.
        legacy = False

    descriptor_id = _pick_descriptor_value(item, block, "descriptor_id", f"{path}.descriptor_id")
    descriptor_version = _pick_descriptor_value(item, block, "descriptor_version", f"{path}.descriptor_version")
    descriptor_digest = _pick_descriptor_value(item, block, "descriptor_digest", f"{path}.descriptor_digest")
    scope_value = _pick_descriptor_value(item, block, "capability_scope", f"{path}.capability_scope", aliases=("scope",))
    provider_id = _pick_descriptor_value(item, block, "provider_id", f"{path}.provider_id")
    provider_version = _pick_descriptor_value(item, block, "provider_version", f"{path}.provider_version")
    provider_scope_value = _pick_descriptor_value(item, block, "provider_scope", f"{path}.provider_scope")
    inspector_id = _pick_descriptor_value(item, block, "inspector_id", f"{path}.inspector_id")
    inspector_version = _pick_descriptor_value(item, block, "inspector_version", f"{path}.inspector_version")
    inspector_scope_value = _pick_descriptor_value(item, block, "inspector_scope", f"{path}.inspector_scope")
    representations_value = _pick_descriptor_value(
        item,
        block,
        "representations",
        f"{path}.representations",
        aliases=("representation",),
    )
    fallbacks_value = _pick_descriptor_value(
        item,
        block,
        "fallbacks",
        f"{path}.fallbacks",
        aliases=("fallback",),
    )
    strategy_value = _pick_descriptor_value(item, block, "strategy", f"{path}.strategy")
    prerequisites_value = _pick_descriptor_value(item, block, "prerequisites", f"{path}.prerequisites")
    policy_class = _pick_descriptor_value(item, block, "policy_class", f"{path}.policy_class")
    source_metadata = _pick_descriptor_value(item, block, "source", f"{path}.source")
    compatibility = _pick_descriptor_value(item, block, "compatibility", f"{path}.compatibility")
    deprecated = _pick_descriptor_value(item, block, "deprecated", f"{path}.deprecated")
    notes = _pick_descriptor_value(item, block, "notes", f"{path}.notes")

    # Nested provider/inspector blocks are accepted as a migration-friendly
    # spelling while the public schema remains 1.0-shaped.
    for key, current, target_path in (("provider", provider_id, f"{path}.provider"), ("inspector", inspector_id, f"{path}.inspector")):
        nested = block.get(key)
        if nested is None:
            continue
        nested_map = _require_mapping(nested, target_path)
        allowed = {"id", "provider_id", "inspector_id", "version", "scope"}
        unknown = set(nested_map) - allowed
        if unknown:
            _fail(target_path, f"unknown fields: {sorted(unknown)}")
        id_name = "provider_id" if key == "provider" else "inspector_id"
        nested_id = nested_map.get(id_name, nested_map.get("id"))
        nested_version = nested_map.get("version")
        nested_scope = nested_map.get("scope")
        if current is not None and nested_id is not None and current != nested_id:
            _fail(target_path, "conflicts with flat provider/inspector ID")
        if key == "provider":
            provider_id = nested_id if current is None else current
            if provider_version is None:
                provider_version = nested_version
            if provider_scope_value is None:
                provider_scope_value = nested_scope
        else:
            inspector_id = nested_id if current is None else current
            if inspector_version is None:
                inspector_version = nested_version
            if inspector_scope_value is None:
                inspector_scope_value = nested_scope

    capabilities = _require_mapping(item["capabilities"], f"{path}.capabilities")
    if legacy:
        derived_scope = [name for name in ("search", "browse_creator", "inspect", "acquire") if bool(capabilities.get(name))]
        capability_scope = tuple(derived_scope)
    else:
        capability_scope = _validate_scope(scope_value, f"{path}.capability_scope", required=True)
    if not legacy:
        # Legacy platform booleans and the richer catalog scopes coexist while
        # the registry migrates.  Enforce exact agreement whenever the
        # descriptor uses the boolean spellings; catalog-only scopes carry
        # their own provider/representation invariants below.
        contract_only_scope = set(capability_scope) & {"primary_resource", "representation", "landing_page"}
        if not contract_only_scope:
            for capability_name in ("search", "browse_creator", "inspect", "acquire"):
                if bool(capabilities.get(capability_name)) != (capability_name in capability_scope):
                    _fail(f"{path}.capability_scope", f"must agree with capabilities.{capability_name}")

    strategies = tuple(_validate_string_list(item["acquisition"]["strategies"], f"{path}.acquisition.strategies"))
    if strategy_value is not None:
        strategy_value = _require_string(strategy_value, f"{path}.strategy")
        if strategy_value not in strategies:
            _fail(f"{path}.strategy", "must be one of acquisition.strategies")
    elif strategies:
        strategy_value = strategies[0]
    representations = _validate_representations(representations_value, f"{path}.representations")
    if prerequisites_value is not None:
        prerequisites_value = _require_mapping(prerequisites_value, f"{path}.prerequisites")
    if policy_class is not None:
        policy_class = _require_string(policy_class, f"{path}.policy_class")
    if source_metadata is not None:
        source_metadata = _require_mapping(source_metadata, f"{path}.source")
    if compatibility is not None:
        compatibility = _require_mapping(compatibility, f"{path}.compatibility")
    if deprecated is None:
        deprecated = False
    else:
        deprecated = _require_bool(deprecated, f"{path}.deprecated")
    if notes is not None:
        notes = _require_string(notes, f"{path}.notes")
    if legacy:
        # Legacy ``acquire=true`` is intentionally not a concrete-primary
        # declaration and must not produce a ready provider route.
        provider_id = provider_version = inspector_id = inspector_version = None
        provider_scope = inspector_scope = ()
        representations = ()
        fallbacks = ()
        descriptor_id = descriptor_id or f"legacy:{platform_id}"
        descriptor_version = descriptor_version or LEGACY_REGISTRY_VERSION
    else:
        if descriptor_id is None:
            _fail(f"{path}.descriptor_id", "is required for a 1.1 descriptor")
        if descriptor_version is None:
            _fail(f"{path}.descriptor_version", "is required for a 1.1 descriptor")
        descriptor_version = _validate_version(descriptor_version, f"{path}.descriptor_version")
        if (set(capability_scope) & {"acquire", "primary", "primary_resource"}) and not provider_id:
            _fail(f"{path}.provider_id", "an acquire/primary descriptor must declare a provider")
        if "inspect" in capability_scope and not inspector_id:
            _fail(f"{path}.inspector_id", "an inspect descriptor must declare an inspector")
        if set(capability_scope) & {"primary", "primary_resource"} and not representations:
            _fail(f"{path}.representations", "primary scope requires a representation declaration")
        fallbacks = _validate_fallbacks(fallbacks_value, f"{path}.fallbacks")
    provider_scope = _validate_scope(provider_scope_value, f"{path}.provider_scope") if provider_id else ()
    inspector_scope = _validate_scope(inspector_scope_value, f"{path}.inspector_scope") if inspector_id else ()
    if provider_id and not provider_scope:
        provider_scope = capability_scope
    if inspector_id and not inspector_scope:
        inspector_scope = ("inspect",) if "inspect" in capability_scope else capability_scope
    if provider_id:
        provider_id = _require_string(provider_id, f"{path}.provider_id")
        if provider_version is not None:
            provider_version = _validate_version(provider_version, f"{path}.provider_version")
    if inspector_id:
        inspector_id = _require_string(inspector_id, f"{path}.inspector_id")
        if inspector_version is not None:
            inspector_version = _validate_version(inspector_version, f"{path}.inspector_version")

    material = {
        "descriptor_id": descriptor_id,
        "descriptor_version": descriptor_version,
        "registry_version": registry_version,
        "platform_id": platform_id,
        "resource_types": list(item["resource_types"]),
        "capability_scope": list(capability_scope),
        "acquisition_strategies": list(strategies),
        "provider_id": provider_id,
        "provider_version": provider_version,
        "provider_scope": list(provider_scope),
        "inspector_id": inspector_id,
        "inspector_version": inspector_version,
        "inspector_scope": list(inspector_scope),
        "representations": list(representations),
        "fallbacks": list(fallbacks),
        "legacy_descriptor": legacy,
    }
    optional_material = {
        "strategy": strategy_value,
        "prerequisites": prerequisites_value,
        "policy_class": policy_class,
        "source": source_metadata,
        "compatibility": compatibility,
        "deprecated": deprecated,
        "notes": notes,
    }
    for key, value in optional_material.items():
        if value is not None and (key != "deprecated" or value):
            material[key] = _json_safe(value)
    computed_digest = canonical_descriptor_digest(material)
    if descriptor_digest is not None:
        descriptor_digest = _normalize_digest(descriptor_digest, f"{path}.descriptor_digest")
        # Accept digests generated from either the normalized descriptor or
        # the nested/raw descriptor block to make migration fixtures stable.
        accepted = {computed_digest}
        if block:
            accepted.add(canonical_descriptor_digest(block))
        if descriptor_digest not in accepted:
            _fail(f"{path}.descriptor_digest", "does not match canonical descriptor content")
    else:
        descriptor_digest = computed_digest
    return CapabilityDescriptor(
        descriptor_id=str(descriptor_id),
        descriptor_version=str(descriptor_version),
        descriptor_digest=descriptor_digest,
        registry_version=registry_version,
        platform_id=platform_id,
        resource_types=tuple(item["resource_types"]),
        capability_scope=capability_scope,
        acquisition_strategies=strategies,
        provider_id=provider_id,
        provider_version=provider_version,
        provider_scope=provider_scope,
        inspector_id=inspector_id,
        inspector_version=inspector_version,
        inspector_scope=inspector_scope,
        representations=representations,
        fallbacks=fallbacks,
        legacy_descriptor=legacy,
        source=item,
        strategy=strategy_value,
        prerequisites=prerequisites_value,
        policy_class=policy_class,
        source_metadata=source_metadata,
        compatibility=compatibility,
        deprecated=deprecated,
        notes=notes,
    )


def _catalog_descriptor_from_entry(
    item: Mapping[str, Any],
    registry_version: str,
    path: str,
) -> CapabilityDescriptor:
    """Normalize one descriptor-catalog entry.

    The standalone capability catalog intentionally carries richer metadata
    than the historical platform registry.  Keep this adapter local to the
    registry loader so callers get the same immutable ``CapabilityDescriptor``
    regardless of which source form supplied the declaration.
    """

    entry = _require_mapping(item, path)
    required = {
        "descriptor_id",
        "descriptor_version",
        "descriptor_digest",
        "registry_version",
        "platform_id",
        "resource_types",
        "scope",
        "representation",
        "strategy",
        "provider",
        "inspector",
        "prerequisites",
        "policy_class",
        "fallback",
        "source",
        "compatibility",
    }
    missing = required - set(entry)
    if missing:
        _fail(path, f"missing descriptor fields: {sorted(missing)}")
    allowed = required | {"deprecated", "notes"}
    unknown = set(entry) - allowed
    if unknown:
        _fail(path, f"unknown descriptor fields: {sorted(unknown)}")
    entry_registry_version = _require_string(entry["registry_version"], f"{path}.registry_version")
    if entry_registry_version != registry_version:
        _fail(f"{path}.registry_version", "must match catalog registry_version")
    descriptor_id = _require_string(entry["descriptor_id"], f"{path}.descriptor_id")
    descriptor_version = _validate_version(entry["descriptor_version"], f"{path}.descriptor_version")
    platform_id = _require_string(entry["platform_id"], f"{path}.platform_id", pattern=_PLATFORM_ID_PATTERN)
    resource_types_value = _require_list(entry["resource_types"], f"{path}.resource_types")
    if not resource_types_value:
        _fail(f"{path}.resource_types", "must not be empty")
    _require_unique(resource_types_value, f"{path}.resource_types")
    resource_types: list[str] = []
    for index, value in enumerate(resource_types_value):
        text = _require_string(value, f"{path}.resource_types[{index}]")
        if text not in LEGAL_RESOURCE_TYPES:
            _fail(f"{path}.resource_types[{index}]", f"illegal resource type {text!r}")
        resource_types.append(text)
    capability_scope = _validate_scope(entry["scope"], f"{path}.scope", required=True)
    strategy = _require_string(entry["strategy"], f"{path}.strategy")
    if strategy not in _ACQUISITION_STRATEGIES and not re.fullmatch(r"[a-z][a-z0-9_.-]*", strategy):
        _fail(f"{path}.strategy", "must be a safe capability strategy")
    provider = _require_mapping(entry["provider"], f"{path}.provider")
    provider_unknown = set(provider) - {"provider_id", "version", "scope"}
    if provider_unknown:
        _fail(f"{path}.provider", f"unknown provider fields: {sorted(provider_unknown)}")
    provider_id = _require_string(provider.get("provider_id"), f"{path}.provider.provider_id")
    provider_version = _validate_version(provider.get("version"), f"{path}.provider.version")
    provider_scope = _validate_scope(provider.get("scope"), f"{path}.provider.scope", required=False)
    if not provider_scope:
        provider_scope = capability_scope
    inspector_id = inspector_version = None
    inspector_scope: tuple[str, ...] = ()
    inspector_value = entry.get("inspector")
    if inspector_value is not None:
        inspector = _require_mapping(inspector_value, f"{path}.inspector")
        inspector_unknown = set(inspector) - {"inspector_id", "version", "scope"}
        if inspector_unknown:
            _fail(f"{path}.inspector", f"unknown inspector fields: {sorted(inspector_unknown)}")
        inspector_id = _require_string(inspector.get("inspector_id"), f"{path}.inspector.inspector_id")
        inspector_version = _validate_version(inspector.get("version"), f"{path}.inspector.version")
        inspector_scope = _validate_scope(inspector.get("scope"), f"{path}.inspector.scope")
        if not inspector_scope:
            inspector_scope = ("inspect",) if "inspect" in capability_scope else capability_scope
    representations = _validate_representations(entry["representation"], f"{path}.representation")
    if not representations:
        _fail(f"{path}.representation", "must not be empty")
    prerequisites = _require_mapping(entry["prerequisites"], f"{path}.prerequisites")
    policy_class = _require_string(entry["policy_class"], f"{path}.policy_class")
    fallbacks = _validate_fallbacks(entry["fallback"], f"{path}.fallback")
    source_metadata = _require_mapping(entry["source"], f"{path}.source")
    compatibility = _require_mapping(entry["compatibility"], f"{path}.compatibility")
    deprecated = _require_bool(entry.get("deprecated", False), f"{path}.deprecated")
    notes = entry.get("notes")
    if notes is not None:
        notes = _require_string(notes, f"{path}.notes")
    descriptor_digest = _normalize_digest(entry["descriptor_digest"], f"{path}.descriptor_digest")
    computed_digest = canonical_descriptor_digest(entry)
    if descriptor_digest != computed_digest:
        _fail(f"{path}.descriptor_digest", "does not match canonical descriptor content")
    return CapabilityDescriptor(
        descriptor_id=descriptor_id,
        descriptor_version=descriptor_version,
        descriptor_digest=descriptor_digest,
        registry_version=registry_version,
        platform_id=platform_id,
        resource_types=tuple(resource_types),
        capability_scope=capability_scope,
        acquisition_strategies=(strategy,),
        provider_id=provider_id,
        provider_version=provider_version,
        provider_scope=provider_scope,
        inspector_id=inspector_id,
        inspector_version=inspector_version,
        inspector_scope=inspector_scope,
        representations=representations,
        fallbacks=fallbacks,
        legacy_descriptor=False,
        source=entry,
        strategy=strategy,
        prerequisites=prerequisites,
        policy_class=policy_class,
        source_metadata=source_metadata,
        compatibility=compatibility,
        deprecated=deprecated,
        notes=notes,
    )


def _validate_descriptor_catalog(payload: Mapping[str, Any]) -> tuple[str, tuple[CapabilityDescriptor, ...]]:
    root = _require_mapping(payload, "catalog")
    allowed = {"$schema", "catalog_version", "registry_version", "descriptors", "registry_digest"}
    unknown = set(root) - allowed
    if unknown:
        _fail("catalog", f"unexpected object shape (extra={sorted(unknown)})")
    for key in ("$schema", "catalog_version", "registry_version", "descriptors"):
        if key not in root:
            _fail("catalog", f"missing required field {key!r}")
    _require_string(root["$schema"], "catalog.$schema")
    catalog_version = _validate_version(root["catalog_version"], "catalog.catalog_version")
    registry_version = _require_string(root["registry_version"], "catalog.registry_version")
    if registry_version not in SUPPORTED_REGISTRY_VERSIONS:
        _fail("catalog.registry_version", f"must be one of {sorted(SUPPORTED_REGISTRY_VERSIONS)!r}")
    descriptors_value = _require_list(root["descriptors"], "catalog.descriptors")
    if not descriptors_value:
        _fail("catalog.descriptors", "must not be empty")
    descriptors: list[CapabilityDescriptor] = []
    seen: set[str] = set()
    for index, item in enumerate(descriptors_value):
        descriptor = _catalog_descriptor_from_entry(item, registry_version, f"descriptors[{index}]")
        if descriptor.descriptor_id in seen:
            _fail(f"descriptors[{index}].descriptor_id", "duplicate descriptor ID")
        seen.add(descriptor.descriptor_id)
        descriptors.append(descriptor)
    if "registry_digest" in root:
        supplied = _normalize_digest(root["registry_digest"], "catalog.registry_digest")
        computed = canonical_registry_digest(root)
        if supplied != computed:
            _fail("catalog.registry_digest", "does not match canonical catalog content")
    return registry_version, tuple(descriptors)


def _validate_platform(
    platform: Any,
    index: int,
    seen_ids: set[str],
    *,
    registry_version: str = LEGACY_REGISTRY_VERSION,
    seen_descriptor_ids: set[str] | None = None,
) -> None:
    path = f"platforms[{index}]"
    item = _require_mapping(platform, path)
    expected_keys = _PLATFORM_KEYS if registry_version == LEGACY_REGISTRY_VERSION else _PLATFORM_KEYS_V11
    actual_keys = set(item)
    if not actual_keys <= expected_keys:
        _fail(path, f"unexpected object shape (extra={sorted(actual_keys - expected_keys)})")
    missing_keys = _PLATFORM_KEYS - actual_keys
    if missing_keys:
        _fail(path, f"unexpected object shape (missing={sorted(missing_keys)})")

    platform_id = _require_string(item["platform_id"], f"{path}.platform_id", pattern=_PLATFORM_ID_PATTERN)
    if platform_id in seen_ids:
        _fail(f"{path}.platform_id", f"duplicate platform ID {platform_id!r}")
    seen_ids.add(platform_id)

    display_name = _require_string(item["display_name"], f"{path}.display_name")
    if len(display_name) > 128:
        _fail(f"{path}.display_name", "must be at most 128 characters")

    resource_types = _require_list(item["resource_types"], f"{path}.resource_types")
    if not resource_types:
        _fail(f"{path}.resource_types", "must not be empty")
    _require_unique(resource_types, f"{path}.resource_types")
    for type_index, resource_type in enumerate(resource_types):
        value = _require_string(resource_type, f"{path}.resource_types[{type_index}]")
        if value not in LEGAL_RESOURCE_TYPES:
            _fail(f"{path}.resource_types[{type_index}]", f"illegal resource type {value!r}")

    capabilities = _require_mapping(item["capabilities"], f"{path}.capabilities")
    _require_exact_keys(capabilities, _CAPABILITY_KEYS, f"{path}.capabilities")
    for name in _CAPABILITY_KEYS:
        _require_bool(capabilities[name], f"{path}.capabilities.{name}")
    if capabilities["browse_creator"] and platform_id not in CREATOR_BROWSE_PLATFORM_IDS:
        _fail(f"{path}.capabilities.browse_creator", f"creator browsing is not active for {platform_id!r}")
    if platform_id in CREATOR_BROWSE_PLATFORM_IDS and not capabilities["browse_creator"]:
        _fail(f"{path}.capabilities.browse_creator", f"active creator browsing is missing for {platform_id!r}")

    auth_mode = _require_string(item["auth_mode"], f"{path}.auth_mode")
    auth_kind = _require_string(item["auth_kind"], f"{path}.auth_kind")
    if auth_mode not in _AUTH_MODES:
        _fail(f"{path}.auth_mode", f"unsupported auth mode {auth_mode!r}")
    if auth_kind not in _AUTH_KINDS:
        _fail(f"{path}.auth_kind", f"unsupported auth kind {auth_kind!r}")
    if auth_mode == "none" and auth_kind != "none":
        _fail(f"{path}.auth_kind", "auth_kind must be none when auth_mode is none")
    if auth_mode == "required" and auth_kind == "none":
        _fail(f"{path}.auth_kind", "required auth must identify a credential kind")

    source_traits = _require_list(item["source_traits"], f"{path}.source_traits")
    if not source_traits:
        _fail(f"{path}.source_traits", "must not be empty")
    _require_unique(source_traits, f"{path}.source_traits")
    for trait_index, trait in enumerate(source_traits):
        value = _require_string(trait, f"{path}.source_traits[{trait_index}]")
        if value not in _SOURCE_TRAITS:
            _fail(f"{path}.source_traits[{trait_index}]", f"unsupported source trait {value!r}")
    if capabilities["browse_creator"] and "creator" not in source_traits:
        _fail(f"{path}.source_traits", "creator-browsing platforms must declare the creator trait")
    if not capabilities["browse_creator"] and "creator" in source_traits:
        _fail(f"{path}.source_traits", "creator trait is reserved for active creator-browsing platforms")

    search = _require_mapping(item["search"], f"{path}.search")
    _require_exact_keys(search, _SEARCH_KEYS, f"{path}.search")
    search_enabled = _require_bool(search["enabled"], f"{path}.search.enabled")
    if search_enabled != capabilities["search"]:
        _fail(f"{path}.search.enabled", "must match capabilities.search")
    _require_integer(search["recommended_limit"], f"{path}.search.recommended_limit", minimum=1, maximum=50)
    if _require_string(search["query_execution"], f"{path}.search.query_execution") != "serial":
        _fail(f"{path}.search.query_execution", "must be serial for the current adapter implementation")

    inspection = _require_mapping(item["inspection"], f"{path}.inspection")
    _require_exact_keys(inspection, _INSPECTION_KEYS, f"{path}.inspection")
    inspection_supported = _require_bool(inspection["supported"], f"{path}.inspection.supported")
    if capabilities["inspect"] != inspection_supported:
        _fail(f"{path}.inspection.supported", "must match capabilities.inspect")

    acquisition = _require_mapping(item["acquisition"], f"{path}.acquisition")
    _require_exact_keys(acquisition, _ACQUISITION_KEYS, f"{path}.acquisition")
    strategies = _require_list(acquisition["strategies"], f"{path}.acquisition.strategies")
    if not strategies:
        _fail(f"{path}.acquisition.strategies", "must declare at least one strategy")
    _require_unique(strategies, f"{path}.acquisition.strategies")
    for strategy_index, strategy in enumerate(strategies):
        value = _require_string(strategy, f"{path}.acquisition.strategies[{strategy_index}]")
        if value not in _ACQUISITION_STRATEGIES:
            _fail(f"{path}.acquisition.strategies[{strategy_index}]", f"unsupported acquisition strategy {value!r}")
        allowed_platforms = _SPECIALIZED_STRATEGY_PLATFORMS.get(value)
        if allowed_platforms is not None and platform_id not in allowed_platforms:
            _fail(
                f"{path}.acquisition.strategies[{strategy_index}]",
                f"{value!r} is not implemented by platform {platform_id!r}",
            )
    if capabilities["acquire"] != bool(strategies):
        _fail(f"{path}.capabilities.acquire", "must match whether acquisition strategies are declared")

    _validate_identity_profile(item["identity_profile"], f"{path}.identity_profile", platform_id)

    descriptor = _descriptor_from_entry(item, registry_version, path)
    if seen_descriptor_ids is not None:
        if descriptor.descriptor_id in seen_descriptor_ids:
            _fail(f"{path}.descriptor_id", f"duplicate descriptor ID {descriptor.descriptor_id!r}")
        seen_descriptor_ids.add(descriptor.descriptor_id)


def validate_platform_registry(
    payload: Mapping[str, Any],
    *,
    schema_path: str | Path | None = None,
) -> None:
    """Validate a decoded registry payload.

    This function is intentionally side-effect free and accepts decoded JSON
    only.  Pass ``schema_path`` when a caller also wants the local schema file
    checked; :func:`load_platform_registry` does that by default.
    """

    if schema_path is not None:
        schema = _read_json(Path(schema_path), "schema")
        _validate_schema_document(schema)

    _reject_security_material(payload)
    root = _require_mapping(payload, "registry")
    actual_root_keys = set(root)
    allowed_root_keys = _TOP_LEVEL_KEYS | {"registry_digest"}
    if not actual_root_keys <= allowed_root_keys:
        _fail("registry", f"unexpected object shape (extra={sorted(actual_root_keys - allowed_root_keys)})")
    missing_root_keys = _TOP_LEVEL_KEYS - actual_root_keys
    if missing_root_keys:
        _fail("registry", f"unexpected object shape (missing={sorted(missing_root_keys)})")
    if _require_string(root["$schema"], "registry.$schema") != REGISTRY_SCHEMA_REFERENCE:
        _fail("registry.$schema", f"must be {REGISTRY_SCHEMA_REFERENCE!r}")
    registry_version = _require_string(root["registry_version"], "registry.registry_version")
    if registry_version not in SUPPORTED_REGISTRY_VERSIONS:
        _fail("registry.registry_version", f"must be one of {sorted(SUPPORTED_REGISTRY_VERSIONS)!r}")
    if "registry_digest" in root:
        digest = _require_string(root["registry_digest"], "registry.registry_digest")
        if _DIGEST_PATTERN.fullmatch(digest) is None:
            _fail("registry.registry_digest", "must be a lowercase SHA-256 digest")

    platforms = _require_list(root["platforms"], "registry.platforms")
    if len(platforms) != len(EXPECTED_PLATFORM_IDS):
        _fail("registry.platforms", f"must contain exactly {len(EXPECTED_PLATFORM_IDS)} platforms")
    seen_ids: set[str] = set()
    seen_descriptor_ids: set[str] = set()
    for index, platform in enumerate(platforms):
        _validate_platform(
            platform,
            index,
            seen_ids,
            registry_version=registry_version,
            seen_descriptor_ids=seen_descriptor_ids,
        )
    if seen_ids != EXPECTED_PLATFORM_IDS:
        _fail(
            "registry.platforms",
            f"platform IDs must equal the active 16-platform set; missing={sorted(EXPECTED_PLATFORM_IDS - seen_ids)}, extra={sorted(seen_ids - EXPECTED_PLATFORM_IDS)}",
        )
    inspection_ids = {
        platform["platform_id"]
        for platform in platforms
        if platform["capabilities"]["inspect"]
    }
    if inspection_ids != INSPECTION_PLATFORM_IDS:
        _fail(
            "registry.platforms",
            "inspect-enabled platform IDs must equal the exact 7-platform set; "
            f"missing={sorted(INSPECTION_PLATFORM_IDS - inspection_ids)}, "
            f"extra={sorted(inspection_ids - INSPECTION_PLATFORM_IDS)}",
        )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlatformRegistryError(f"{label}: cannot read {path}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlatformRegistryError(f"{label}: invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise PlatformRegistryError(f"{label}: root must be a JSON object")
    return value


def load_platform_registry(
    path: str | Path | None = None,
    *,
    registry_path: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and strictly validate the active platform capability registry.

    ``path`` and ``registry_path`` are equivalent convenience arguments; at
    most one may be provided.  The returned object is a deep copy so a caller
    cannot mutate a value that another caller might treat as the registry
    fact source.
    """

    if path is not None and registry_path is not None:
        raise TypeError("provide either path or registry_path, not both")
    registry_file = Path(registry_path or path or DEFAULT_REGISTRY_PATH)
    schema_file = Path(schema_path or DEFAULT_SCHEMA_PATH)
    schema = _read_json(schema_file, "schema")
    _validate_schema_document(schema)
    payload = _read_json(registry_file, "registry")
    validate_platform_registry(payload)
    return copy.deepcopy(payload)



def canonical_registry_digest(value: Mapping[str, Any]) -> str:
    """Compute a stable digest for a registry payload excluding its digest field."""

    material = copy.deepcopy(_json_safe(value))
    material.pop("registry_digest", None)
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def build_registry_snapshot(payload: Mapping[str, Any]) -> RegistrySnapshot:
    """Validate *payload* and build an immutable descriptor snapshot.

    Both the historical platform-registry shape and the richer standalone
    capability-descriptor catalog are accepted.  The returned snapshot uses
    one immutable descriptor model so service code does not need to know which
    source file supplied the declaration.
    """

    if not isinstance(payload, Mapping):
        raise PlatformRegistryError("registry: root must be an object")
    if "descriptors" in payload and "platforms" not in payload:
        registry_version, descriptors = _validate_descriptor_catalog(payload)
    else:
        validate_platform_registry(payload)
        registry_version = str(payload["registry_version"])
        descriptors = tuple(
            _descriptor_from_entry(item, registry_version, f"platforms[{index}]")
            for index, item in enumerate(payload["platforms"])
        )
    digest = canonical_registry_digest(payload)
    supplied_digest = payload.get("registry_digest")
    if supplied_digest is not None and _normalize_digest(supplied_digest, "registry.registry_digest") != digest:
        raise PlatformRegistryError("registry.registry_digest: does not match canonical registry content")
    return RegistrySnapshot(
        registry_version=registry_version,
        registry_digest=digest,
        descriptors=descriptors,
        source=payload,
    )


def load_registry_snapshot(
    path: str | Path | None = None,
    *,
    registry_path: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> RegistrySnapshot:
    """Load an immutable static descriptor snapshot from a registry file."""

    if path is not None and registry_path is not None:
        raise TypeError("provide either path or registry_path, not both")
    registry_file = Path(registry_path or path or DEFAULT_REGISTRY_PATH)
    schema_file = Path(schema_path or DEFAULT_SCHEMA_PATH)
    schema = _read_json(schema_file, "schema")
    payload = _read_json(registry_file, "registry")
    if "descriptors" in payload and "platforms" not in payload:
        _validate_capability_schema_document(schema)
    else:
        _validate_schema_document(schema)
    return build_registry_snapshot(payload)


# Explicit alias used by capability-oriented callers during migration.
load_capability_registry = load_registry_snapshot


def descriptor_for_platform(
    platform_id: str,
    *,
    resource_type: str | None = None,
    scope: str | Iterable[str] | None = None,
    representation_kind: str | None = None,
    strategy: str | None = None,
    snapshot: RegistrySnapshot | None = None,
) -> CapabilityDescriptor:
    """Return a descriptor selected by platform and optional capability dimensions."""

    current = snapshot or load_registry_snapshot()
    return current.descriptor_for(
        platform_id,
        resource_type=resource_type,
        scope=scope,
        representation_kind=representation_kind,
        strategy=strategy,
    )


def _resolve_descriptor(
    descriptor: CapabilityDescriptor | str,
    snapshot: RegistrySnapshot | None,
) -> CapabilityDescriptor:
    if isinstance(descriptor, CapabilityDescriptor):
        return descriptor
    if isinstance(descriptor, str):
        current = snapshot or load_registry_snapshot()
        # Capability callers commonly pass a descriptor/capability ID, while
        # legacy callers pass a platform ID.  Resolve the exact descriptor ID
        # first so catalog routes remain unambiguous, then retain the platform
        # query fallback for the historical registry shape.
        by_id = tuple(item for item in current.descriptors if item.descriptor_id == descriptor)
        if by_id:
            return by_id[0]
        return current.descriptor_for(descriptor)
    raise TypeError("descriptor must be a CapabilityDescriptor, descriptor ID, or platform ID")


def _contract_scope(descriptor: CapabilityDescriptor) -> str:
    """Return the singular persistence scope for a descriptor."""

    return descriptor.scope_for_contract


def _fallback_capability_ids(descriptor: CapabilityDescriptor) -> tuple[str, ...]:
    """Extract only explicit fallback capability IDs, never provider IDs."""

    values: list[str] = []
    for item in descriptor.fallbacks:
        if not isinstance(item, Mapping):
            continue
        candidate = item.get("capability_id", item.get("descriptor_id"))
        if isinstance(candidate, str) and candidate and candidate not in values:
            values.append(candidate)
    return tuple(values)


def _derive_load_status(status: str, *, legacy: bool) -> str:
    if legacy or status in {"not_checked", "missing_provider", "missing_inspector"}:
        return "not_loaded"
    if status in {"ready"}:
        return "loaded"
    if status in {"degraded", "experimental"}:
        return "partially_loaded"
    return "failed"


def _derive_credential_posture(
    descriptor: CapabilityDescriptor,
    auth_ready: bool | None,
) -> str:
    prerequisites = descriptor.prerequisites
    auth_mode = prerequisites.get("auth_mode") if isinstance(prerequisites, Mapping) else None
    if auth_mode == "required":
        if auth_ready is False:
            return "required_missing"
        if auth_ready is True:
            return "required_present"
        return "invalid"
    if auth_mode == "optional":
        if auth_ready is False:
            return "optional_missing"
        if auth_ready is True:
            return "optional_present"
        return "optional_missing"
    return "none"


def _derive_network_policy_status(
    descriptor: CapabilityDescriptor,
    policy_allowed: bool | None,
) -> str:
    if policy_allowed is False:
        return "blocked"
    if policy_allowed is True:
        return "allowed"
    prerequisites = descriptor.prerequisites
    network_policy = prerequisites.get("network_policy") if isinstance(prerequisites, Mapping) else None
    if network_policy in (None, "", "none", "not_required"):
        return "not_required"
    return "unknown"


def _dependency_check(
    name: str,
    status: str,
    *,
    version: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"name": name, "status": status}
    if version is not None:
        value["version"] = version
    return value


def _derive_dependency_checks(
    descriptor: CapabilityDescriptor,
    *,
    provider_versions: Mapping[str, str],
    inspector_versions: Mapping[str, str],
    provider_import_errors: Mapping[str, Any],
    inspector_import_errors: Mapping[str, Any],
    auth_ready: bool | None,
    policy_allowed: bool | None,
) -> tuple[Mapping[str, Any], ...]:
    checks: list[Mapping[str, Any]] = []
    if descriptor.provider_id:
        provider_id = descriptor.provider_id
        if provider_id in provider_import_errors:
            checks.append(_dependency_check(provider_id, "failed"))
        elif provider_id not in provider_versions:
            checks.append(_dependency_check(provider_id, "missing"))
        else:
            checks.append(_dependency_check(provider_id, "ok", version=str(provider_versions[provider_id])))
    else:
        checks.append(_dependency_check("provider", "not_checked"))
    if descriptor.inspector_id:
        inspector_id = descriptor.inspector_id
        if inspector_id in inspector_import_errors:
            checks.append(_dependency_check(inspector_id, "failed"))
        elif inspector_id not in inspector_versions:
            checks.append(_dependency_check(inspector_id, "missing"))
        else:
            checks.append(_dependency_check(inspector_id, "ok", version=str(inspector_versions[inspector_id])))
    else:
        checks.append(_dependency_check("inspector", "not_checked"))
    checks.append(_dependency_check("credentials", "not_checked" if auth_ready is None else ("ok" if auth_ready else "failed")))
    checks.append(_dependency_check("policy", "not_checked" if policy_allowed is None else ("ok" if policy_allowed else "failed")))
    return tuple(checks)


def probe_runtime_readiness(
    descriptor: CapabilityDescriptor | str,
    *,
    snapshot: RegistrySnapshot | None = None,
    provider_versions: Mapping[str, str] | None = None,
    inspector_versions: Mapping[str, str] | None = None,
    provider_scopes: Mapping[str, Iterable[str]] | None = None,
    inspector_scopes: Mapping[str, Iterable[str]] | None = None,
    provider_import_errors: Mapping[str, Any] | None = None,
    inspector_import_errors: Mapping[str, Any] | None = None,
    auth_ready: bool | None = None,
    policy_allowed: bool | None = None,
    load_status: str | None = None,
    dependency_checks: Iterable[Mapping[str, Any]] | None = None,
    credential_posture: str | None = None,
    network_policy_status: str | None = None,
    policy_profile: str | None = None,
    fallback_capability_ids: Iterable[str] | None = None,
    now: datetime | str | None = None,
    ttl_seconds: int | float | None = 300,
) -> ReadinessSnapshot:
    """Create a structured deployment-readiness snapshot.

    The function accepts *observed* provider/inspector registrations rather
    than importing service modules.  This keeps the loader deterministic and
    lets the runtime owner supply import, constructor, session and policy
    probe results without making this module depend on ``service.py``.

    ``snapshot`` contributes the registry digest/version authority.  When a
    descriptor is probed in isolation those fields remain ``None`` so a
    caller cannot accidentally claim that an unbound runtime observation came
    from a particular registry revision.
    """

    current = _resolve_descriptor(descriptor, snapshot)
    checked = _utc_now(now)
    issues: list[Mapping[str, Any]] = []
    status = "not_checked"
    provider_version = None
    inspector_version = None
    provider_versions = provider_versions or {}
    inspector_versions = inspector_versions or {}
    provider_import_errors = provider_import_errors or {}
    inspector_import_errors = inspector_import_errors or {}
    provider_scopes = provider_scopes or {}
    inspector_scopes = inspector_scopes or {}

    if current.legacy_descriptor:
        status = "legacy"
        issues.append(_issue("LEGACY_DESCRIPTOR", "registry 1.0 descriptor has no runtime provider authority"))
    elif auth_ready is False:
        status = "auth_required"
        issues.append(_issue("AUTH_REQUIRED", "runtime authentication dependency is not ready"))
    elif policy_allowed is False:
        status = "policy_blocked"
        issues.append(_issue("POLICY_BLOCKED", "runtime policy dependency is not satisfied"))
    else:
        # Every active descriptor that declares a route/representation needs a
        # matching provider.  ``inspect`` remains inspector-only by design.
        required_provider = bool(current.provider_id) or bool(
            set(current.capability_scope)
            & {
                "search",
                "resolve",
                "acquire",
                "primary",
                "primary_resource",
                "representation",
                "landing",
                "landing_page",
                "metadata",
                "materialize",
                "capture",
            }
        )
        if required_provider:
            if not current.provider_id:
                status = "missing_provider"
                issues.append(_issue("MISSING_PROVIDER", "descriptor declares runtime capability without provider_id"))
            elif current.provider_id in provider_import_errors:
                status = "import_failed"
                issues.append(
                    _issue(
                        "PROVIDER_IMPORT_FAILED",
                        "provider import/constructor failed",
                        detail={"provider_id": current.provider_id},
                    )
                )
            elif current.provider_id not in provider_versions:
                status = "missing_provider"
                issues.append(
                    _issue(
                        "MISSING_PROVIDER",
                        "declared provider is not registered",
                        detail={"provider_id": current.provider_id},
                    )
                )
            else:
                provider_version = str(provider_versions[current.provider_id])
                if current.provider_version and provider_version != current.provider_version:
                    status = "version_mismatch"
                    issues.append(
                        _issue(
                            "PROVIDER_VERSION_MISMATCH",
                            "loaded provider version differs from descriptor",
                            detail={"provider_id": current.provider_id},
                        )
                    )
                observed_scope = provider_scopes.get(current.provider_id)
                if observed_scope is not None and not set(current.provider_scope or current.capability_scope).issubset(
                    set(observed_scope)
                ):
                    status = "scope_mismatch"
                    issues.append(
                        _issue(
                            "PROVIDER_SCOPE_MISMATCH",
                            "loaded provider scope does not cover descriptor scope",
                            detail={"provider_id": current.provider_id},
                        )
                    )
        required_inspector = bool(current.inspector_id) or "inspect" in current.capability_scope
        if required_inspector and status in {"not_checked", "ready", "degraded"}:
            if not current.inspector_id:
                status = "missing_inspector"
                issues.append(_issue("MISSING_INSPECTOR", "descriptor declares inspect capability without inspector_id"))
            elif current.inspector_id in inspector_import_errors:
                status = "import_failed"
                issues.append(
                    _issue(
                        "INSPECTOR_IMPORT_FAILED",
                        "inspector import/constructor failed",
                        detail={"inspector_id": current.inspector_id},
                    )
                )
            elif current.inspector_id not in inspector_versions:
                status = "missing_inspector"
                issues.append(
                    _issue(
                        "MISSING_INSPECTOR",
                        "declared inspector is not registered",
                        detail={"inspector_id": current.inspector_id},
                    )
                )
            else:
                inspector_version = str(inspector_versions[current.inspector_id])
                if current.inspector_version and inspector_version != current.inspector_version:
                    status = "version_mismatch"
                    issues.append(
                        _issue(
                            "INSPECTOR_VERSION_MISMATCH",
                            "loaded inspector version differs from descriptor",
                            detail={"inspector_id": current.inspector_id},
                        )
                    )
                observed_scope = inspector_scopes.get(current.inspector_id)
                if observed_scope is not None and not set(current.inspector_scope or current.capability_scope).issubset(
                    set(observed_scope)
                ):
                    status = "scope_mismatch"
                    issues.append(
                        _issue(
                            "INSPECTOR_SCOPE_MISMATCH",
                            "loaded inspector scope does not cover descriptor scope",
                            detail={"inspector_id": current.inspector_id},
                        )
                    )
        if status == "not_checked" and (provider_versions or inspector_versions):
            status = "ready" if not issues else "degraded"
        elif status == "not_checked" and not current.provider_id and not current.inspector_id:
            issues.append(_issue("RUNTIME_NOT_PROBED", "no provider or inspector observation was supplied"))

    if auth_ready is True and status == "not_checked":
        status = "ready" if current.provider_id or current.inspector_id else "not_checked"
    if policy_allowed is True and status == "not_checked":
        status = "ready" if current.provider_id or current.inspector_id else "not_checked"

    expires = None
    if ttl_seconds is not None:
        if isinstance(ttl_seconds, bool):
            raise ValueError("ttl_seconds must be a non-negative number or None")
        seconds = float(ttl_seconds)
        if seconds < 0 or seconds != seconds or seconds == float("inf") or seconds == float("-inf"):
            raise ValueError("ttl_seconds must be a finite non-negative number or None")
        expires = _timestamp(checked + timedelta(seconds=seconds))

    current_scope = tuple(current.capability_scope)
    contract_scope = _contract_scope(current)
    strategy = current.strategy or (current.acquisition_strategies[0] if current.acquisition_strategies else None)
    observed_dependencies = (
        tuple(dependency_checks)
        if dependency_checks is not None
        else _derive_dependency_checks(
            current,
            provider_versions=provider_versions,
            inspector_versions=inspector_versions,
            provider_import_errors=provider_import_errors,
            inspector_import_errors=inspector_import_errors,
            auth_ready=auth_ready,
            policy_allowed=policy_allowed,
        )
    )
    observed_credential_posture = (
        credential_posture
        if credential_posture is not None
        else _derive_credential_posture(current, auth_ready)
    )
    observed_network_policy_status = (
        network_policy_status
        if network_policy_status is not None
        else _derive_network_policy_status(current, policy_allowed)
    )
    observed_policy_profile = policy_profile if policy_profile is not None else current.policy_class
    observed_fallback_ids = (
        tuple(fallback_capability_ids)
        if fallback_capability_ids is not None
        else _fallback_capability_ids(current)
    )
    effective_load_status = load_status or _derive_load_status(status, legacy=current.legacy_descriptor)
    registry_digest = snapshot.registry_digest if snapshot is not None else None
    registry_version = snapshot.registry_version if snapshot is not None else current.registry_version

    seed = {
        "descriptor_id": current.descriptor_id,
        "descriptor_version": current.descriptor_version,
        "descriptor_digest": current.descriptor_digest,
        "registry_version": registry_version,
        "registry_digest": registry_digest,
        "platform_id": current.platform_id,
        "capability_scope": contract_scope,
        "strategy": strategy,
        "provider_id": current.provider_id,
        "provider_version": provider_version,
        "inspector_id": current.inspector_id,
        "inspector_version": inspector_version,
        "status": status,
        "checked_at": _timestamp(checked),
        "expires_at": expires,
        "issues": issues,
        "load_status": effective_load_status,
        "dependency_checks": observed_dependencies,
        "credential_posture": observed_credential_posture,
        "network_policy_status": observed_network_policy_status,
        "policy_profile": observed_policy_profile,
        "fallback_capability_ids": observed_fallback_ids,
    }
    snapshot_id = "ready_" + hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()[:32]
    return ReadinessSnapshot(
        snapshot_id=snapshot_id,
        descriptor_id=current.descriptor_id,
        descriptor_version=current.descriptor_version,
        descriptor_digest=current.descriptor_digest,
        registry_version=registry_version,
        registry_digest=registry_digest,
        platform_id=current.platform_id,
        status=status,
        checked_at=_timestamp(checked),
        expires_at=expires,
        provider_id=current.provider_id,
        provider_version=provider_version,
        inspector_id=current.inspector_id,
        inspector_version=inspector_version,
        scope=current_scope,
        capability_scope=contract_scope,
        strategy=strategy,
        issues=tuple(issues),
        legacy_descriptor=current.legacy_descriptor,
        load_status=effective_load_status,
        dependency_checks=observed_dependencies,
        credential_posture=observed_credential_posture,
        network_policy_status=observed_network_policy_status,
        policy_profile=observed_policy_profile,
        fallback_capability_ids=observed_fallback_ids,
    )


# Short alias for runtimes that call their capability probe simply ``readiness``.
readiness_snapshot = probe_runtime_readiness


def revalidate_readiness(
    readiness: ReadinessSnapshot,
    *,
    descriptor: CapabilityDescriptor | None = None,
    now: datetime | str | None = None,
) -> ReadinessSnapshot:
    """Revalidate descriptor binding and TTL without hiding stale state."""

    if not isinstance(readiness, ReadinessSnapshot):
        raise TypeError("readiness must be a ReadinessSnapshot")
    current = _utc_now(now)
    if descriptor is not None and descriptor.descriptor_digest != readiness.descriptor_digest:
        issues = tuple(readiness.issues) + (_issue("DESCRIPTOR_CHANGED", "descriptor digest changed"),)
        # Clear the supplied digest so ``ReadinessSnapshot.__post_init__``
        # recomputes it from the changed status/issues instead of preserving a
        # digest for the stale ready state.
        return replace(readiness, status="descriptor_changed", issues=issues, snapshot_digest=None)
    if readiness.expires_at is not None and current >= _utc_now(readiness.expires_at):
        issues = tuple(readiness.issues) + (_issue("READINESS_EXPIRED", "readiness snapshot TTL has expired"),)
        return replace(readiness, status="expired", issues=issues, snapshot_digest=None)
    return readiness


def load_registry(
    path: str | Path | None = None,
    *,
    registry_path: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> dict[str, Any]:
    """Backward-friendly short alias for :func:`load_platform_registry`."""

    return load_platform_registry(path, registry_path=registry_path, schema_path=schema_path)


def get_platform_registry() -> dict[str, Any]:
    """Return a freshly loaded registry snapshot for internal callers."""

    return load_platform_registry()


__all__ = [
    "CapabilityDescriptor",
    "CREATOR_BROWSE_PLATFORM_IDS",
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_SCHEMA_PATH",
    "EXPECTED_PLATFORM_IDS",
    "INSPECTION_PLATFORM_IDS",
    "LEGACY_REGISTRY_VERSION",
    "LEGAL_RESOURCE_TYPES",
    "REGISTRY_VERSION",
    "SUPPORTED_REGISTRY_VERSIONS",
    "PlatformRegistryError",
    "ReadinessSnapshot",
    "RegistrySnapshot",
    "build_registry_snapshot",
    "canonical_descriptor_digest",
    "canonical_registry_digest",
    "descriptor_for_platform",
    "get_platform_registry",
    "load_capability_registry",
    "load_platform_registry",
    "load_registry",
    "load_registry_snapshot",
    "probe_runtime_readiness",
    "readiness_snapshot",
    "revalidate_readiness",
    "validate_platform_registry",
]
