"""Platform search adapter protocol and shared helpers.

Each platform-specific adapter (bilibili, zhihu, smartedu, …) implements
``PlatformSearchAdapter``.  The ``MultiPlatformSearchProvider`` in
``search.py`` dispatches to these adapters based on the ``platforms``
filter on ``resource_search``.

Adapters return results in the same normalized dict shape that
``GenericWebSearchProvider`` already produces, so the downstream service
layer (``ResourceService.search``) does not need to know which platform
a result came from.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Protocol


class AdapterDescriptorError(ValueError):
    """Raised when an adapter descriptor contains an invalid value."""


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise AdapterDescriptorError(f"{field_name} must be a non-empty printable string")
    return value


def _immutable_text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise AdapterDescriptorError(f"{field_name} must be a sequence of strings")
    values = tuple(_require_text(item, f"{field_name}[{index}]") for index, item in enumerate(value))
    if not values:
        raise AdapterDescriptorError(f"{field_name} must not be empty")
    if len(set(values)) != len(values):
        raise AdapterDescriptorError(f"{field_name} must not contain duplicates")
    return values


def _freeze_value(value: Any, field_name: str) -> Any:
    """Recursively convert JSON-shaped mutable values to immutable values."""

    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, child in value.items():
            key = _require_text(key, f"{field_name} key")
            frozen[key] = _freeze_value(child, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(child, f"{field_name}[{index}]") for index, child in enumerate(value))
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(child, f"{field_name}[]") for child in value)
    if isinstance(value, (bytearray, memoryview)):
        raise AdapterDescriptorError(f"{field_name} contains a mutable binary value")
    return value


def _immutable_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterDescriptorError(f"{field_name} must be an object")
    frozen = _freeze_value(value, field_name)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded above
        raise AdapterDescriptorError(f"{field_name} must be an object")
    return frozen


def _hashable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((key, _hashable_value(child)) for key, child in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_hashable_value(child) for child in value)
    if isinstance(value, (frozenset, set)):
        return frozenset(_hashable_value(child) for child in value)
    return value


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Immutable capability and identity facts for one platform adapter.

    Registry entries are ordinary JSON-shaped dictionaries.  The constructor
    accepts their list/dict forms for convenience, then recursively converts
    them to tuples and read-only mappings.  This keeps a descriptor safe to
    share between retrieval, registration, and later consistency checks.

    The descriptor is metadata only.  The current adapter registration path
    still uses ``platform_id`` so legacy and third-party stubs that do not yet
    expose ``descriptor`` continue to run; later built-in registration will
    make descriptor presence mandatory at its own boundary.
    """

    platform_id: str
    resource_types: tuple[str, ...]
    capabilities: Mapping[str, bool]
    identity_profile: Mapping[str, Any]
    acquisition_strategies: tuple[str, ...]
    auth_mode: str
    auth_kind: str
    source_traits: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform_id", _require_text(self.platform_id, "platform_id"))
        object.__setattr__(self, "resource_types", _immutable_text_tuple(self.resource_types, "resource_types"))
        object.__setattr__(self, "acquisition_strategies", _immutable_text_tuple(
            self.acquisition_strategies,
            "acquisition_strategies",
        ))
        object.__setattr__(self, "source_traits", _immutable_text_tuple(self.source_traits, "source_traits"))
        object.__setattr__(self, "auth_mode", _require_text(self.auth_mode, "auth_mode"))
        object.__setattr__(self, "auth_kind", _require_text(self.auth_kind, "auth_kind"))

        capabilities = _immutable_mapping(self.capabilities, "capabilities")
        if not capabilities:
            raise AdapterDescriptorError("capabilities must not be empty")
        if any(type(value) is not bool for value in capabilities.values()):
            raise AdapterDescriptorError("capabilities values must be booleans")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "identity_profile", _immutable_mapping(
            self.identity_profile,
            "identity_profile",
        ))

    @classmethod
    def from_registry_entry(cls, entry: Mapping[str, Any]) -> "AdapterDescriptor":
        """Build a descriptor from one already validated platform entry.

        Non-descriptor registry metadata (display name, search policy, and
        inspection policy) is intentionally ignored here.  Validation of the
        complete registry remains the responsibility of
        ``retrieval.registry``; this method only validates the shape required
        to produce a safe immutable descriptor and reports malformed input as
        ``AdapterDescriptorError`` rather than leaking ``KeyError``.
        """

        if not isinstance(entry, Mapping):
            raise AdapterDescriptorError("registry entry must be an object")
        required = (
            "platform_id",
            "resource_types",
            "capabilities",
            "auth_mode",
            "auth_kind",
            "source_traits",
            "identity_profile",
            "acquisition",
        )
        missing = [key for key in required if key not in entry]
        if missing:
            raise AdapterDescriptorError(f"registry entry is missing fields: {', '.join(missing)}")
        acquisition = entry["acquisition"]
        if not isinstance(acquisition, Mapping) or "strategies" not in acquisition:
            raise AdapterDescriptorError("registry entry acquisition must contain strategies")
        return cls(
            platform_id=entry["platform_id"],
            resource_types=entry["resource_types"],
            capabilities=entry["capabilities"],
            identity_profile=entry["identity_profile"],
            acquisition_strategies=acquisition["strategies"],
            auth_mode=entry["auth_mode"],
            auth_kind=entry["auth_kind"],
            source_traits=entry["source_traits"],
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.platform_id,
                self.resource_types,
                _hashable_value(self.capabilities),
                _hashable_value(self.identity_profile),
                self.acquisition_strategies,
                self.auth_mode,
                self.auth_kind,
                self.source_traits,
            )
        )


@lru_cache(maxsize=1)
def _active_descriptor_index() -> Mapping[str, AdapterDescriptor]:
    """Load the validated Registry once and expose immutable descriptors."""

    from ..retrieval.registry import load_platform_registry

    descriptors = {
        entry["platform_id"]: AdapterDescriptor.from_registry_entry(entry)
        for entry in load_platform_registry()["platforms"]
    }
    return MappingProxyType(descriptors)


def descriptor_for_platform(platform_id: str) -> AdapterDescriptor:
    """Return the active immutable descriptor for ``platform_id``."""

    key = _require_text(platform_id, "platform_id")
    try:
        return _active_descriptor_index()[key]
    except KeyError as exc:
        raise AdapterDescriptorError(f"unknown platform descriptor: {key}") from exc


class PlatformSearchAdapter(Protocol):
    """Search a single platform.

    Implementations receive ``SessionStore`` and ``Settings`` at
    construction time so they can pull stored cookies / tokens at search
    time without the caller having to thread credentials through.
    """

    platform_id: str
    # Static declaration only: the current registration path intentionally
    # remains compatible with legacy/third-party stubs that have platform_id
    # but no descriptor.  Built-in enforcement belongs at a later boundary.
    descriptor: AdapterDescriptor

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Search *query* on this platform, returning up to *limit* results.

        Returns a tuple of ``(resources, error)`` where *resources* is a
        list of normalized dicts (see :func:`make_resource`) and *error*
        is ``None`` on success or a dict with keys ``code``, ``message``,
        ``retryable`` on failure.
        """
        ...


def adapter_error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    """Build the error dict returned by adapters on failure."""
    return {"code": code, "message": message, "retryable": retryable}


def make_resource(
    *,
    platform: str,
    title: str,
    source_url: str,
    resource_type: str = "其他",
    summary: str | None = None,
    author: str | None = None,
    published_at: str | None = None,
    language: str | None = None,
    download_feasibility: str | None = None,
    platform_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized resource dict matching the shape that
    ``GenericWebSearchProvider`` produces and ``ResourceService.search``
    consumes.

    Only *platform*, *title* and *source_url* are required; the rest are
    folded into ``metadata`` when present.
    """
    metadata: dict[str, Any] = {"platform_signals": platform_signals or {}}
    if author is not None:
        metadata["author"] = author
    if published_at is not None:
        metadata["published_at"] = published_at
    if language is not None:
        metadata["language"] = language
    if download_feasibility is not None:
        metadata["download_feasibility"] = download_feasibility
    return {
        "platform": platform,
        "title": title,
        "source_url": source_url,
        "resource_type": resource_type,
        "summary": summary,
        "metadata": metadata,
    }
