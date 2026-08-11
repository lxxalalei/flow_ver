"""Capability authority coordination for candidate acquisition.

This module is the narrow bridge between the retrieval registry and the
candidate/plan lifecycle.  It intentionally does not own a second registry,
perform network I/O, or select a provider on behalf of the acquisition router.
Instead it projects one immutable descriptor/readiness/resolution/eligibility
chain into the storage-shaped capability binding consumed by ``Store``.

The coordinator is deliberately useful in isolation (for contract tests and
offline probes), while accepting a ``Store`` instance when callers want the
server-generated readiness and eligibility facts persisted immediately.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .inspection import representation_evidence_is_fresh, source_fingerprint
from .retrieval.models import Representation
from .retrieval.registry import (
    CapabilityDescriptor,
    PlatformRegistryError,
    ReadinessSnapshot,
    RegistrySnapshot,
    load_registry_snapshot,
    probe_runtime_readiness,
    revalidate_readiness,
)
from .storage import Store


_CAPABILITY_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "capabilities"
    / "capability-descriptors.json"
)
_CAPABILITY_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "schemas"
    / "capability-descriptors.schema.json"
)


_SCOPE_STRENGTH = {
    "metadata": 0,
    "landing_page": 1,
    "representation": 2,
    "primary_resource": 3,
}
_SCOPES = frozenset(_SCOPE_STRENGTH)
_ELIGIBILITY_ACTION_BY_STRATEGY = {
    "direct_file": "download",
    "web_materialize": "materialize",
    "web_capture": "materialize",
}
_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_SENSITIVE_KEYS = frozenset(
    {
        "source_url",
        "canonical_url",
        "url",
        "uri",
        "href",
        "download_url",
        "stream_url",
        "path",
        "file_path",
        "local_path",
        "locator",
        "cookie",
        "cookies",
        "token",
        "access_token",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "headers",
    }
)


class CapabilityAuthorityError(ValueError):
    """Structured failure raised when an authority chain cannot be built."""

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

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            result["details"] = _json_safe(self.details)
        return result


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Server-side action eligibility fact in storage-compatible form."""

    eligibility_id: str
    flow_id: str
    resource_id: str
    representation_id: str
    action: str
    status: str
    policy_class: str
    source_fingerprint: str
    capability_id: str
    descriptor_digest: str
    readiness_snapshot_id: str
    evaluated_at: str
    expires_at: str
    reason_codes: tuple[str, ...] = ()
    resolution_id: str | None = None
    decision_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "eligibility_id": self.eligibility_id,
            "flow_id": self.flow_id,
            "resource_id": self.resource_id,
            "resolution_id": self.resolution_id,
            "representation_id": self.representation_id,
            "action": self.action,
            "status": self.status,
            "policy_class": self.policy_class,
            "reason_codes": list(self.reason_codes),
            "source_fingerprint": self.source_fingerprint,
            "capability_id": self.capability_id,
            "descriptor_digest": self.descriptor_digest,
            "readiness_snapshot_id": self.readiness_snapshot_id,
            "evaluated_at": self.evaluated_at,
            "expires_at": self.expires_at,
        }
        item["decision_digest"] = self.decision_digest or _canonical_authority_digest(item)
        return item


@dataclass(frozen=True, slots=True)
class PlanCapabilityItem:
    """One immutable per-resource capability binding for a download Plan."""

    resource_id: str
    representation_id: str
    capability_scope: str
    strategy: str
    provider_id: str
    provider_version: str
    capability_id: str
    descriptor_version: str
    descriptor_digest: str
    registry_version: str
    registry_digest: str
    readiness_snapshot_id: str
    readiness_digest: str
    eligibility_id: str
    eligibility_digest: str
    source_fingerprint: str
    representation: Mapping[str, Any]
    position: int = 0
    resolution_id: str | None = None
    binding_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "resource_id": self.resource_id,
            "resolution_id": self.resolution_id,
            "representation_id": self.representation_id,
            "capability_scope": self.capability_scope,
            "strategy": self.strategy,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "capability_id": self.capability_id,
            "descriptor_version": self.descriptor_version,
            "descriptor_digest": self.descriptor_digest,
            "registry_version": self.registry_version,
            "registry_digest": self.registry_digest,
            "readiness_snapshot_id": self.readiness_snapshot_id,
            "readiness_digest": self.readiness_digest,
            "eligibility_id": self.eligibility_id,
            "eligibility_digest": self.eligibility_digest,
            "source_fingerprint": self.source_fingerprint,
            "representation": _json_safe(self.representation),
            "position": self.position,
        }
        item["binding_digest"] = self.binding_digest or _request_digest(item)
        return item


@dataclass(frozen=True, slots=True)
class RevalidationResult:
    """Structured result returned by fresh plan-item revalidation."""

    ok: bool
    code: str | None = None
    message: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    readiness: ReadinessSnapshot | None = None
    eligibility: Mapping[str, Any] | None = None
    # The authority bound actually safe to execute after a fresh check.  This
    # may carry new readiness/eligibility IDs because those IDs include
    # observation timestamps; callers must use this binding rather than
    # treating timestamp churn as policy drift.
    execution_binding: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": self.ok}
        if self.code:
            result["code"] = self.code
        if self.message:
            result["message"] = self.message
        if self.details:
            result["details"] = _json_safe(self.details)
        if self.readiness is not None:
            result["readiness"] = _readiness_storage_shape(self.readiness)
        if self.eligibility is not None:
            result["eligibility"] = _json_safe(self.eligibility)
        if self.execution_binding is not None:
            result["execution_binding"] = _json_safe(self.execution_binding)
        return result

    # A small Mapping-like convenience keeps this object friendly to callers
    # that historically consumed ``dict`` service results.
    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


_ELIGIBILITY_STABLE_FIELDS = (
    "flow_id",
    "resource_id",
    "resolution_id",
    "representation_id",
    "action",
    "status",
    "policy_class",
    "reason_codes",
    "source_fingerprint",
    "capability_id",
    "descriptor_digest",
)


def _eligibility_invariants(value: Mapping[str, Any]) -> dict[str, Any]:
    """Extract policy/rights facts while excluding time-derived identity."""

    return {
        field: _json_safe(value.get(field))
        for field in _ELIGIBILITY_STABLE_FIELDS
    }


def _execution_binding(
    bound: Mapping[str, Any],
    readiness: ReadinessSnapshot,
    readiness_shape: Mapping[str, Any] | None,
    eligibility: Mapping[str, Any],
) -> dict[str, Any]:
    """Project fresh server facts into a safe, executable plan-item binding."""

    item = dict(bound)
    item.update(
        {
            "provider_id": readiness.provider_id,
            "provider_version": readiness.provider_version,
            "readiness_snapshot_id": readiness.readiness_id,
            "readiness_digest": _digest(
                str((readiness_shape or {}).get("snapshot_digest") or readiness.snapshot_digest_sha256),
                field="readiness_digest",
            ),
            "eligibility_id": eligibility.get("eligibility_id"),
            "eligibility_digest": _digest(
                str(eligibility.get("decision_digest") or ""),
                field="eligibility_digest",
            ),
            "representation": _clean_representation(
                _as_mapping(item.get("representation"), label="representation")
            ),
        }
    )
    # A plan binding digest is deliberately bare SHA-256 in Storage.  Compute
    # it over the same shape that Store validates, excluding the old digest.
    item.pop("binding_digest", None)
    item["binding_digest"] = _request_digest(item)
    return item


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError("non_finite_json_value")
        return value
    if hasattr(value, "to_mapping") and callable(value.to_mapping):
        return _json_safe(value.to_mapping())
    raise ValueError("non_json_authority_value")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _request_digest(value: Any) -> str:
    # Use Storage's canonical implementation rather than maintaining a second
    # hashing algorithm.  The fallback is only for a very small test double.
    request_digest = getattr(Store, "_request_digest", None)
    if callable(request_digest):
        return str(request_digest(value))
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_authority_digest(value: Any) -> str:
    canonical = getattr(Store, "_canonical_authority_digest", None)
    if callable(canonical):
        return str(canonical(value))
    return "sha256:" + _request_digest(value)


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_request_digest(value)[:32]}"


def _digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise CapabilityAuthorityError("INVALID_DIGEST", f"{field} must be a SHA-256 digest")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CapabilityAuthorityError("INVALID_TIMESTAMP", "invalid timestamp") from exc
    else:
        raise CapabilityAuthorityError("INVALID_TIMESTAMP", "invalid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CapabilityAuthorityError("INVALID_TIMESTAMP", "timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _as_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_mapping = getattr(value, "to_mapping", None)
    if callable(to_mapping):
        mapped = to_mapping()
        if isinstance(mapped, Mapping):
            return dict(mapped)
    raise CapabilityAuthorityError("INVALID_INPUT", f"{label} must be a mapping")


def _resource_mapping(resource: Any) -> dict[str, Any]:
    return _as_mapping(resource, label="resource")


def _resolution_mapping(resolution: Any) -> dict[str, Any]:
    mapped = _as_mapping(resolution, label="resolution")
    # Store recovery APIs expose the authoritative resolution payload under
    # ``resolved`` while older callers may use ``resolved_resource``.  Flatten
    # either private nested shape, then let the outer server-owned identity and
    # status/fingerprint fields override or supplement the payload.  Never
    # retain the private wrapper as a domain field.
    nested: Mapping[str, Any] | None = None
    for candidate in ("resolved_resource", "resolved"):
        value = mapped.get(candidate)
        if isinstance(value, Mapping):
            nested = value
            break
    if nested is not None:
        result = dict(nested)
        result.update(
            {
                key: value
                for key, value in mapped.items()
                if key not in {"resolved_resource", "resolved"}
            }
        )
        return result
    return mapped


def _representation_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Representation):
        return value.to_mapping()
    return _as_mapping(value, label="representation")


def _clean_representation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only JSON-safe representation evidence, never locators/secrets."""

    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if key.casefold() in _SENSITIVE_KEYS:
            continue
        if isinstance(raw_value, Mapping):
            result[key] = _clean_representation(raw_value)
        elif isinstance(raw_value, (list, tuple)):
            result[key] = [_clean_representation(item) if isinstance(item, Mapping) else _json_safe(item) for item in raw_value]
        else:
            result[key] = _json_safe(raw_value)
    return result


def _representation_list(resource: Mapping[str, Any], resolution: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = resolution.get("representations")
    if not values:
        values = resource.get("representations")
    if not values:
        representation = resolution.get("representation")
        values = [representation] if isinstance(representation, Mapping) else []
    if not isinstance(values, (list, tuple)):
        values = [values]
    return [_clean_representation(_representation_mapping(item)) for item in values if item is not None]


def _resolution_representation_id(resolution: Mapping[str, Any]) -> str | None:
    """Return a Service-selected representation identifier, if present."""

    for key in (
        "selected_representation_id",
        "representation_id",
        "primary_representation_id",
    ):
        value = resolution.get(key)
        if isinstance(value, str) and value:
            return value
    selected = resolution.get("selected_representation")
    if isinstance(selected, Mapping):
        value = selected.get("representation_id")
        if isinstance(value, str) and value:
            return value
    return None


def _select_representation(
    resource: Mapping[str, Any],
    resolution: Mapping[str, Any],
    *,
    representation_id: str | None = None,
    required: bool = False,
) -> dict[str, Any] | None:
    """Select a representation by its server-owned ID, never by list order.

    A single representation is unambiguous.  When multiple representations
    are present, callers must provide the selected ID (or Service must include
    one in the resolution envelope); a unique concrete primary is accepted as
    a safe semantic tie-breaker, but an arbitrary first element is not.
    """

    candidates = _representation_list(resource, resolution)
    requested_id = representation_id or _resolution_representation_id(resolution)
    if requested_id:
        for candidate in candidates:
            if candidate.get("representation_id") == requested_id:
                return candidate
        # A malformed or stale representation binding must be surfaced as a
        # representation-specific authority failure, not silently substituted.
        raise CapabilityAuthorityError(
            "REPRESENTATION_NOT_FOUND",
            "selected representation_id is not present in the resolution",
            {"representation_id": requested_id},
        )
    if not candidates:
        if required:
            raise CapabilityAuthorityError(
                "REPRESENTATION_REQUIRED",
                "a resolved representation is required",
            )
        return None
    if len(candidates) == 1:
        return candidates[0]
    concrete_primary = [
        candidate
        for candidate in candidates
        if _representation_role(candidate) == "primary"
        and _is_concrete_primary(candidate, resolution_scope=_scope_hint(resolution, candidate))
    ]
    if len(concrete_primary) == 1:
        return concrete_primary[0]
    raise CapabilityAuthorityError(
        "REPRESENTATION_AMBIGUOUS",
        "multiple representations require an explicit representation_id",
        {"representation_ids": [str(item.get("representation_id") or "") for item in candidates]},
    )


def _scope_hint(resolution: Mapping[str, Any], representation: Mapping[str, Any] | None) -> str | None:
    for value in (
        resolution.get("scope"),
        resolution.get("capability_scope"),
        representation.get("scope") if representation else None,
    ):
        if isinstance(value, str) and value in _SCOPES:
            return value
    return None


def _representation_role(representation: Mapping[str, Any]) -> str:
    role = str(representation.get("role") or "").strip().lower()
    kind = str(representation.get("kind") or "").strip().lower()
    if role in {"primary", "landing", "metadata", "attachment", "companion"}:
        return role
    if kind in {"landing", "webpage"}:
        return "landing"
    if kind == "metadata":
        return "metadata"
    return "representation"


def _is_materializable(representation: Mapping[str, Any]) -> bool:
    return bool(representation.get("materializable"))


def _eligibility_action(strategy: str) -> str:
    """Map one exact acquisition strategy to its policy action.

    The action is part of the persisted eligibility authority.  It must come
    from the descriptor-bound strategy, never from a client option, resource
    type, or scope inference.
    """

    action = _ELIGIBILITY_ACTION_BY_STRATEGY.get(strategy)
    if action is None:
        raise CapabilityAuthorityError(
            "CAPABILITY_STRATEGY_REQUIRED",
            "capability strategy has no eligibility action",
            {"strategy": strategy},
        )
    return action


def _matches_descriptor_representation(
    descriptor: CapabilityDescriptor,
    representation: Mapping[str, Any],
    *,
    scope: str,
) -> bool:
    """Return whether inspection evidence exactly fits a descriptor shape."""

    actual_kind = str(representation.get("kind") or "").strip().casefold()
    actual_role = _representation_role(representation)
    actual_container = str(representation.get("container") or "").strip().casefold()
    actual_mime = str(representation.get("mime_type") or "").split(";", 1)[0].strip().casefold()
    for raw_shape in descriptor.representations:
        if not isinstance(raw_shape, Mapping):
            continue
        shape = raw_shape
        expected_scope = shape.get("scope")
        if isinstance(expected_scope, str) and expected_scope and expected_scope != scope:
            continue
        expected_kind = str(shape.get("kind") or "").strip().casefold()
        if expected_kind and expected_kind != actual_kind:
            continue
        expected_role = str(shape.get("role") or "").strip().casefold()
        if expected_role and expected_role != actual_role:
            continue
        containers = {
            str(value).strip().casefold()
            for value in shape.get("containers", ())
            if isinstance(value, str) and value.strip()
        }
        if containers and (not actual_container or actual_container not in containers):
            continue
        mime_types = {
            str(value).split(";", 1)[0].strip().casefold()
            for value in shape.get("mime_types", ())
            if isinstance(value, str) and value.strip()
        }
        if mime_types and (not actual_mime or actual_mime not in mime_types):
            continue
        if shape.get("materializable") is True and not _is_materializable(representation):
            continue
        return True
    return False


def _is_concrete_primary(
    representation: Mapping[str, Any],
    *,
    resolution_scope: str | None,
) -> bool:
    role = _representation_role(representation)
    if role != "primary" or not _is_materializable(representation):
        return False
    if "concrete" in representation:
        return bool(representation.get("concrete"))
    # Inspectors that have verified a body emit scope=primary_resource.  The
    # legacy fixture shape carries the same fact on the Resolution instead.
    return resolution_scope == "primary_resource" or representation.get("scope") == "primary_resource"


def classify_representation_scope(
    resolution: Any,
    representation: Any | None = None,
) -> str:
    """Classify one candidate representation without upgrading evidence."""

    resolved = _resolution_mapping(resolution)
    rep = _representation_mapping(representation) if representation is not None else None
    if rep is None:
        rep = _select_representation({}, resolved)
    if rep is None:
        return "metadata"
    hint = _scope_hint(resolved, rep)
    if _is_concrete_primary(rep, resolution_scope=hint):
        return "primary_resource"
    role = _representation_role(rep)
    kind = str(rep.get("kind") or "").strip().lower()
    if role == "landing" or kind in {"landing", "webpage"}:
        return "landing_page"
    if role == "metadata" or kind == "metadata":
        return "metadata"
    return "representation"


def _extract_runtime_inventory(inventory: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize Service-owned provider/inspector observations.

    The coordinator never imports or discovers runtime components.  Service
    may provide either already-normalized ``*_versions``/``*_scopes`` maps or
    exact registration objects (for example ``AcquisitionRouter``
    ``ProviderRegistration`` instances) under ``providers``/
    ``provider_registry`` and their inspector equivalents.  We preserve exact
    IDs and versions; an object under a different ID must not satisfy a
    descriptor by platform or by a generic fallback.
    """

    raw = dict(inventory or {})

    def _as_text(value: Any) -> str | None:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            return text or None
        return None

    def _iter_entries(names: tuple[str, ...]) -> Iterable[tuple[Any, Any]]:
        """Yield ``(key, registration)`` for mappings and sequences."""

        for name in names:
            source = raw.get(name)
            if source is None:
                continue
            if isinstance(source, Mapping):
                yield from source.items()
                continue
            if isinstance(source, (list, tuple, set, frozenset)):
                for value in source:
                    yield (None, value)

    def _component_fields(key: Any, value: Any, *, kind: str) -> tuple[str | None, str | None, tuple[str, ...], Any]:
        """Read one exact registration without assuming a concrete class."""

        data: Mapping[str, Any] = value if isinstance(value, Mapping) else {}
        component_id = _as_text(
            data.get(f"{kind}_id")
            or data.get("id")
            or getattr(value, f"{kind}_id", None)
            or getattr(value, "id", None)
        )
        version = _as_text(
            data.get(f"{kind}_version")
            or data.get("version")
            or getattr(value, f"{kind}_version", None)
            or getattr(value, "version", None)
        )
        scopes_value = (
            data.get(f"{kind}_scopes")
            or data.get("supported_scopes")
            or data.get("scopes")
            or data.get("scope")
            or data.get("capability_scope")
            or getattr(value, "supported_scopes", None)
            or getattr(value, "scopes", None)
            or getattr(value, "scope", None)
            or getattr(value, "capability_scope", None)
        )
        if isinstance(scopes_value, str):
            scopes = (scopes_value,)
        elif isinstance(scopes_value, (list, tuple, set, frozenset)):
            scopes = tuple(str(item) for item in scopes_value if item is not None)
        else:
            scopes = ()
        error = (
            data.get("error")
            or data.get("exception")
            or getattr(value, "error", None)
            or getattr(value, "exception", None)
        )
        status = str(data.get("status") or getattr(value, "status", "")).casefold()
        if status in {"failed", "error", "import_failed", "unavailable", "disabled"} and error is None:
            error = data or status
        # Exact provider registries commonly use ``(id, version)`` keys.
        if isinstance(key, tuple) and len(key) >= 2:
            component_id = component_id or _as_text(key[0])
            version = version or _as_text(key[1])
        elif component_id is None:
            component_id = _as_text(key)
        return component_id, version, scopes, error

    def _component_maps(kind: str) -> tuple[dict[str, str], dict[str, Iterable[str]], dict[str, Any]]:
        if kind == "provider":
            names = ("provider_registry", "providers", "provider_bindings", "downloaders")
            version_name, scope_name, error_name = "provider_versions", "provider_scopes", "provider_import_errors"
        else:
            names = (
                "inspector_registry",
                "registered_inspectors",
                "inspectors",
                "inspector_bindings",
            )
            version_name, scope_name, error_name = "inspector_versions", "inspector_scopes", "inspector_import_errors"
        versions: dict[str, str] = {}
        scopes: dict[str, Iterable[str]] = {}
        errors: dict[str, Any] = {}
        explicit_versions = raw.get(version_name)
        if isinstance(explicit_versions, Mapping):
            for key, value in explicit_versions.items():
                text = _as_text(value)
                if text is not None:
                    versions[str(key)] = text
        explicit_scopes = raw.get(scope_name)
        if isinstance(explicit_scopes, Mapping):
            for key, value in explicit_scopes.items():
                if isinstance(value, str):
                    scopes[str(key)] = (value,)
                elif isinstance(value, (list, tuple, set, frozenset)):
                    scopes[str(key)] = tuple(str(item) for item in value)
        explicit_errors = raw.get(error_name)
        if isinstance(explicit_errors, Mapping):
            errors.update({str(key): value for key, value in explicit_errors.items()})
        for key, value in _iter_entries(names):
            component_id, version, observed_scopes, error = _component_fields(key, value, kind=kind)
            if component_id is None:
                continue
            # Explicit normalized maps are authoritative, while registration
            # objects fill in fields Service did not precompute.
            if version is not None and component_id not in versions:
                versions[component_id] = version
            if observed_scopes and component_id not in scopes:
                scopes[component_id] = observed_scopes
            if error is not None:
                errors.setdefault(component_id, error)
        return versions, scopes, errors

    provider_versions, provider_scopes, provider_errors = _component_maps("provider")
    inspector_versions, inspector_scopes, inspector_errors = _component_maps("inspector")
    return {
        "provider_versions": provider_versions,
        "inspector_versions": inspector_versions,
        "provider_scopes": provider_scopes,
        "inspector_scopes": inspector_scopes,
        "provider_import_errors": provider_errors,
        "inspector_import_errors": inspector_errors,
        "auth_ready": raw.get("auth_ready"),
        "policy_allowed": raw.get("policy_allowed"),
        "load_status": raw.get("load_status"),
        "dependency_checks": raw.get("dependency_checks"),
        "credential_posture": raw.get("credential_posture"),
        "network_policy_status": raw.get("network_policy_status"),
        "policy_profile": raw.get("policy_profile"),
    }


def _storage_timestamp(value: datetime | str | None, field: str) -> str:
    """Normalize timestamps exactly as ``Store`` does before hashing."""

    normalizer = getattr(Store, "_normalize_authority_timestamp", None)
    if callable(normalizer):
        return str(normalizer(value, field))
    return _timestamp(_utc(value))


def _readiness_storage_shape(readiness: ReadinessSnapshot) -> dict[str, Any]:
    """Map registry readiness to ``Store.save_capability_readiness_snapshot``."""

    if not readiness.registry_digest or not readiness.registry_version:
        raise CapabilityAuthorityError("READINESS_UNBOUND", "readiness is not bound to a registry snapshot")
    if not readiness.provider_id or not readiness.provider_version:
        raise CapabilityAuthorityError("PROVIDER_UNAVAILABLE", "readiness has no loaded provider")
    item: dict[str, Any] = {
        "readiness_snapshot_id": readiness.readiness_id,
        "capability_id": readiness.capability_id,
        "descriptor_version": readiness.descriptor_version,
        "descriptor_digest": readiness.descriptor_digest_sha256,
        "registry_version": readiness.registry_version,
        "registry_digest": readiness.registry_digest_sha256,
        "platform_id": readiness.platform_id,
        "capability_scope": readiness.capability_scope or "representation",
        "strategy": readiness.strategy or "unspecified",
        "provider_id": readiness.provider_id,
        "provider_version": readiness.provider_version,
        "inspector_id": readiness.inspector_id,
        "inspector_version": readiness.inspector_version,
        "status": readiness.status,
        "issues": [_json_safe(item) for item in readiness.issues],
        "observed_at": _storage_timestamp(readiness.checked_at, "observed_at"),
        "expires_at": _storage_timestamp(readiness.expires_at, "expires_at"),
    }
    item["snapshot_digest"] = _canonical_authority_digest(item)
    return item


class CapabilityCoordinator:
    """Single authority coordinator for descriptor → plan capability facts."""

    def __init__(
        self,
        store: Any | None = None,
        registry_snapshot: RegistrySnapshot | None = None,
        runtime_inventory: Mapping[str, Any] | None = None,
        *,
        readiness_ttl_seconds: int | float = 300,
        eligibility_ttl_seconds: int | float = 300,
    ) -> None:
        for label, value in (
            ("readiness_ttl_seconds", readiness_ttl_seconds),
            ("eligibility_ttl_seconds", eligibility_ttl_seconds),
        ):
            if value is None or isinstance(value, bool):
                raise ValueError(f"{label} must be a finite positive number")
            seconds = float(value)
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError(f"{label} must be a finite positive number")
        self.store = store
        self.registry_snapshot = registry_snapshot or load_registry_snapshot(
            registry_path=_CAPABILITY_CATALOG_PATH,
            schema_path=_CAPABILITY_SCHEMA_PATH,
        )
        self.runtime_inventory = dict(runtime_inventory or {})
        # A coordinator without a Store still needs a local authority seam so
        # a prepare -> revalidate pair can compare policy facts without
        # treating time-derived eligibility IDs as invariants.
        self._eligibility_cache: dict[str, dict[str, Any]] = {}
        self.readiness_ttl_seconds = readiness_ttl_seconds
        self.eligibility_ttl_seconds = eligibility_ttl_seconds

    # ------------------------------------------------------------------
    # Registry and runtime authority
    # ------------------------------------------------------------------
    def select_descriptor(
        self,
        resource_or_platform: Any,
        *,
        resource_type: str | None = None,
        scope: str | None = None,
        representation_kind: str | None = None,
        strategy: str | None = None,
        descriptor_id: str | None = None,
    ) -> CapabilityDescriptor:
        """Select exactly one descriptor; ambiguous routes are rejected."""

        if isinstance(resource_or_platform, str):
            platform_id = resource_or_platform
            resource = {}
        else:
            resource = _resource_mapping(resource_or_platform)
            platform_id = str(resource.get("platform") or resource.get("platform_id") or "generic")
            resource_type = resource_type or resource.get("resource_type") or resource.get("type")
        if descriptor_id is None:
            ref = resource.get("capability_ref") if isinstance(resource, Mapping) else None
            if isinstance(ref, Mapping):
                descriptor_id = ref.get("capability_id")
            elif isinstance(ref, str):
                descriptor_id = ref
        if descriptor_id is not None:
            candidates = tuple(item for item in self.registry_snapshot.descriptors if item.descriptor_id == descriptor_id)
            if not candidates:
                raise CapabilityAuthorityError("CAPABILITY_NOT_DECLARED", "capability descriptor was not found", {"descriptor_id": descriptor_id})
            descriptor = candidates[0]
            if descriptor.platform_id != platform_id:
                raise CapabilityAuthorityError("CAPABILITY_BINDING_CONFLICT", "descriptor platform does not match resource", {"descriptor_id": descriptor_id, "platform_id": platform_id})
            if resource_type and resource_type not in descriptor.resource_types:
                raise CapabilityAuthorityError("CAPABILITY_SCOPE_MISMATCH", "descriptor does not support resource type", {"resource_type": resource_type})
            if scope and scope not in descriptor.capability_scope and descriptor.scope_for_contract != scope:
                raise CapabilityAuthorityError("CAPABILITY_SCOPE_MISMATCH", "descriptor does not support requested scope", {"scope": scope})
            if strategy and descriptor.strategy != strategy:
                raise CapabilityAuthorityError("CAPABILITY_STRATEGY_MISMATCH", "descriptor strategy does not match request", {"strategy": strategy, "declared_strategy": descriptor.strategy})
            return descriptor
        candidates = self.registry_snapshot.query(
            platform_id=platform_id,
            resource_type=str(resource_type) if resource_type else None,
            scope=scope,
            representation_kind=representation_kind,
            strategy=strategy,
        )
        if not candidates:
            raise CapabilityAuthorityError("CAPABILITY_NOT_DECLARED", "no descriptor matches resource capability", {"platform_id": platform_id, "resource_type": resource_type, "scope": scope, "strategy": strategy})
        if len(candidates) > 1:
            # Prefer a descriptor whose contract scope is exact only when the
            # query itself supplied a scope.  Otherwise ambiguity is unsafe.
            exact = tuple(item for item in candidates if scope and item.scope_for_contract == scope)
            if len(exact) == 1:
                return exact[0]
            raise CapabilityAuthorityError("CAPABILITY_DESCRIPTOR_AMBIGUOUS", "multiple descriptors match resource capability", {"platform_id": platform_id, "descriptor_ids": [item.descriptor_id for item in candidates]})
        return candidates[0]

    def probe_readiness(
        self,
        descriptor: CapabilityDescriptor | str,
        *,
        now: datetime | str | None = None,
        runtime_inventory: Mapping[str, Any] | None = None,
    ) -> ReadinessSnapshot:
        snapshot = self.registry_snapshot
        current = descriptor
        if isinstance(descriptor, str):
            current = self.select_descriptor(descriptor)
        inventory = _extract_runtime_inventory(runtime_inventory if runtime_inventory is not None else self.runtime_inventory)
        return probe_runtime_readiness(
            current,
            snapshot=snapshot,
            provider_versions=inventory["provider_versions"],
            inspector_versions=inventory["inspector_versions"],
            provider_scopes=inventory["provider_scopes"],
            inspector_scopes=inventory["inspector_scopes"],
            provider_import_errors=inventory["provider_import_errors"],
            inspector_import_errors=inventory["inspector_import_errors"],
            auth_ready=inventory["auth_ready"],
            policy_allowed=inventory["policy_allowed"],
            load_status=inventory["load_status"],
            dependency_checks=inventory["dependency_checks"],
            credential_posture=inventory["credential_posture"],
            network_policy_status=inventory["network_policy_status"],
            policy_profile=inventory["policy_profile"],
            now=now,
            ttl_seconds=self.readiness_ttl_seconds,
        )

    def persist_readiness(self, readiness: ReadinessSnapshot) -> dict[str, Any]:
        item = _readiness_storage_shape(readiness)
        if self.store is not None:
            saver = getattr(self.store, "save_capability_readiness_snapshot", None)
            if callable(saver):
                return dict(saver(item))
        return item

    # ------------------------------------------------------------------
    # Scope, source, and eligibility
    # ------------------------------------------------------------------
    def classify_scope(self, resolution: Any, representation: Any | None = None) -> str:
        return classify_representation_scope(resolution, representation)

    def _source_fingerprint(self, resource: Mapping[str, Any], resolution: Mapping[str, Any]) -> str:
        supplied = resolution.get("source_fingerprint") or resource.get("source_fingerprint")
        if supplied is not None:
            return _digest(supplied, field="source_fingerprint")
        merged = dict(resource)
        # A resolution may carry a refreshed canonical URL/identity.  It is
        # safe to hash those facts; the URL itself never leaves this module.
        for key in ("platform", "resource_type", "title", "canonical_url", "source_url", "native_id", "isbn", "doi", "metadata"):
            if key in resolution:
                merged[key] = resolution[key]
        try:
            return "sha256:" + source_fingerprint(merged)
        except Exception as exc:
            raise CapabilityAuthorityError("SOURCE_FINGERPRINT_UNAVAILABLE", "source fingerprint could not be observed") from exc

    def _representation_id(self, resource: Mapping[str, Any], resolution: Mapping[str, Any], representation: Mapping[str, Any]) -> str:
        raw = representation.get("representation_id")
        if isinstance(raw, str) and raw:
            return raw
        seed = {
            "resource_id": resource.get("resource_id"),
            "resolution_id": resolution.get("resolution_id"),
            "representation": representation,
        }
        return _stable_id("repr", seed)

    def _resolution_id(self, resource: Mapping[str, Any], resolution: Mapping[str, Any]) -> str | None:
        raw = resolution.get("resolution_id") or resource.get("resolution_id")
        if isinstance(raw, str) and raw:
            return raw
        return None

    def evaluate_eligibility(
        self,
        flow_id: str,
        resource: Any,
        resolution: Any,
        descriptor: CapabilityDescriptor,
        readiness: ReadinessSnapshot,
        *,
        representation: Mapping[str, Any] | None = None,
        now: datetime | str | None = None,
        runtime_inventory: Mapping[str, Any] | None = None,
    ) -> EligibilityDecision:
        resource_map = _resource_mapping(resource)
        resolution_map = _resolution_mapping(resolution)
        resource_id = resource_map.get("resource_id") or resolution_map.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            raise CapabilityAuthorityError("RESOURCE_ID_REQUIRED", "server resource_id is required for eligibility")
        resolution_id = self._resolution_id(resource_map, resolution_map)
        rep = representation
        if rep is None:
            rep = _select_representation(resource_map, resolution_map)
        rep = _clean_representation(rep or {})
        representation_id = self._representation_id(resource_map, resolution_map, rep)
        scope = self.classify_scope(resolution_map, rep or None)
        source = self._source_fingerprint(resource_map, resolution_map)
        checked = _utc(now)
        observed_inventory = _extract_runtime_inventory(
            runtime_inventory if runtime_inventory is not None else self.runtime_inventory
        )
        strategy = self._require_declared_strategy(descriptor)
        action = _eligibility_action(strategy)
        expires = checked + timedelta(seconds=float(self.eligibility_ttl_seconds))
        reasons: list[str] = []
        status = "eligible"
        availability_fact = resolution_map.get("availability")
        if isinstance(availability_fact, Mapping):
            availability = str(availability_fact.get("status") or "")
        else:
            availability = str(availability_fact or "")
        if not availability:
            availability = str(rep.get("technical_availability") or "")
        resolution_status = str(resolution_map.get("resolution_status") or "resolved")
        if not rep:
            status = "unsupported"
            reasons.append("REPRESENTATION_REQUIRED")
        elif descriptor.scope_for_contract != scope and scope not in descriptor.capability_scope:
            status = "unsupported"
            reasons.append("CAPABILITY_SCOPE_MISMATCH")
        elif not _matches_descriptor_representation(descriptor, rep, scope=scope):
            status = "unsupported"
            reasons.append("CAPABILITY_REPRESENTATION_MISMATCH")
        elif action == "download":
            if scope != "primary_resource":
                status = "unsupported"
                reasons.append("REPRESENTATION_NOT_PRIMARY")
            elif not _is_concrete_primary(rep, resolution_scope=_scope_hint(resolution_map, rep)):
                status = "unsupported"
                reasons.append("REPRESENTATION_NOT_MATERIALIZABLE")
        elif action == "materialize":
            if scope == "metadata" or not _is_materializable(rep):
                status = "unsupported"
                reasons.append("REPRESENTATION_NOT_MATERIALIZABLE")
        if resolution_status in {"unresolved", "unknown"} or availability in {"unknown", "unavailable"}:
            status = "unknown"
            reasons.append("RESOLUTION_UNAVAILABLE")
        if availability == "auth_required" or bool(rep.get("requires_auth")) and observed_inventory.get("auth_ready") is not True:
            status = "auth_required"
            reasons.append("AUTH_REQUIRED")
        if availability == "policy_blocked" or observed_inventory.get("policy_allowed") is False:
            status = "policy_blocked"
            reasons.append("POLICY_BLOCKED")
        if readiness.status != "ready" or not readiness.ready:
            if readiness.status in {"auth_required"}:
                status = "auth_required"
                reasons.append("AUTH_REQUIRED")
            elif readiness.status in {"policy_blocked", "blocked"}:
                status = "policy_blocked"
                reasons.append("POLICY_BLOCKED")
            elif readiness.status in {"unsupported", "feature_not_supported", "legacy"}:
                status = "unsupported"
                reasons.append("CAPABILITY_NOT_READY")
            else:
                status = "unknown"
                reasons.append("CAPABILITY_NOT_READY")
        if descriptor.deprecated:
            status = "unsupported"
            reasons.append("CAPABILITY_DEPRECATED")
        # Deduplicate while preserving diagnostic order.
        reasons = list(dict.fromkeys(reasons))
        base: dict[str, Any] = {
            "eligibility_id": "",
            "flow_id": flow_id,
            "resource_id": resource_id,
            "resolution_id": resolution_id,
            "representation_id": representation_id,
            "action": action,
            "status": status,
            "policy_class": descriptor.policy_class or "unknown",
            "reason_codes": reasons,
            "source_fingerprint": source,
            "capability_id": descriptor.capability_id,
            "descriptor_digest": descriptor.descriptor_digest_sha256,
            "readiness_snapshot_id": readiness.readiness_id,
            "evaluated_at": _timestamp(checked),
            "expires_at": _timestamp(expires),
        }
        base["eligibility_id"] = _stable_id("elig", {key: value for key, value in base.items() if key != "eligibility_id"})
        decision = EligibilityDecision(
            eligibility_id=base["eligibility_id"],
            flow_id=flow_id,
            resource_id=resource_id,
            resolution_id=resolution_id,
            representation_id=representation_id,
            action=action,
            status=status,
            policy_class=str(base["policy_class"]),
            reason_codes=tuple(reasons),
            source_fingerprint=source,
            capability_id=descriptor.capability_id,
            descriptor_digest=descriptor.descriptor_digest_sha256,
            readiness_snapshot_id=readiness.readiness_id,
            evaluated_at=base["evaluated_at"],
            expires_at=base["expires_at"],
        )
        item = decision.to_dict()
        if self.store is not None:
            saver = getattr(self.store, "save_eligibility_decision", None)
            if callable(saver):
                item = dict(saver(item))
                decision = EligibilityDecision(
                    **{key: item[key] for key in (
                        "eligibility_id", "flow_id", "resource_id", "representation_id", "action", "status",
                        "policy_class", "source_fingerprint", "capability_id", "descriptor_digest",
                        "readiness_snapshot_id", "evaluated_at", "expires_at",
                    )},
                    resolution_id=item.get("resolution_id"),
                    reason_codes=tuple(item.get("reason_codes") or ()),
                    decision_digest=item.get("decision_digest"),
                )
        self._eligibility_cache[decision.eligibility_id] = decision.to_dict()
        return decision

    def _require_declared_strategy(self, descriptor: CapabilityDescriptor) -> str:
        """Return only the catalog strategy, never a legacy strategy alias."""

        strategy = descriptor.strategy
        if not isinstance(strategy, str) or not strategy:
            raise CapabilityAuthorityError(
                "CAPABILITY_STRATEGY_REQUIRED",
                "capability descriptor does not declare an executable strategy",
                {"capability_id": descriptor.capability_id},
            )
        return strategy

    # ------------------------------------------------------------------
    # Plan binding and fresh revalidation
    # ------------------------------------------------------------------
    def prepare_resource(
        self,
        flow_id: str,
        resource: Any,
        resolution: Any,
        *,
        preferred_container: str | None = None,
        effective_max_bytes: int | None = None,
        now: datetime | str | None = None,
        position: int = 0,
        representation_id: str | None = None,
        runtime_inventory: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        resource_map = _resource_mapping(resource)
        resolution_map = _resolution_mapping(resolution)
        resource_id = resource_map.get("resource_id") or resolution_map.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            raise CapabilityAuthorityError("RESOURCE_ID_REQUIRED", "server resource_id is required for a plan item")
        resolution_id = self._resolution_id(resource_map, resolution_map)
        if not resolution_id:
            raise CapabilityAuthorityError("RESOLUTION_REQUIRED", "fresh resolution_id is required for download preparation")
        rep = _select_representation(
            resource_map,
            resolution_map,
            representation_id=representation_id,
            required=True,
        )
        if not representation_evidence_is_fresh(rep or {}, now=now):
            raise CapabilityAuthorityError(
                "RESOLUTION_STALE",
                "representation evidence is expired or not yet valid",
                {"resource_id": resource_id},
                retryable=True,
            )
        scope = self.classify_scope(resolution_map, rep)
        hinted_scope = _scope_hint(resolution_map, rep)
        if hinted_scope and _SCOPE_STRENGTH[hinted_scope] > _SCOPE_STRENGTH[scope]:
            raise CapabilityAuthorityError("CAPABILITY_SCOPE_MISMATCH", "resolution scope exceeds representation evidence", {"requested_scope": hinted_scope, "observed_scope": scope})
        if hinted_scope == "primary_resource" and scope != "primary_resource":
            raise CapabilityAuthorityError("REPRESENTATION_NOT_MATERIALIZABLE", "primary plan requires a concrete materializable representation", {"observed_scope": scope})
        descriptor = self.select_descriptor(
            resource_map,
            resource_type=str(resource_map.get("resource_type") or resource_map.get("type") or "other"),
            scope=scope,
            representation_kind=(str(rep.get("kind")) if rep else None),
            strategy=(str(resolution_map.get("strategy")) if resolution_map.get("strategy") else None),
            descriptor_id=(str(resolution_map.get("capability_id")) if resolution_map.get("capability_id") else None),
        )
        # A descriptor route itself cannot upgrade a weaker candidate.
        if descriptor.scope_for_contract != scope and scope not in descriptor.capability_scope:
            raise CapabilityAuthorityError("CAPABILITY_SCOPE_MISMATCH", "descriptor scope does not match representation scope", {"descriptor_scope": descriptor.scope_for_contract, "representation_scope": scope})
        readiness = self.probe_readiness(
            descriptor,
            now=now,
            runtime_inventory=runtime_inventory,
        )
        readiness_shape: dict[str, Any] | None = None
        try:
            readiness_shape = self.persist_readiness(readiness)
        except CapabilityAuthorityError:
            # Unready/missing-provider snapshots are still returned in the
            # error details below, but cannot be persisted as executable facts.
            readiness_shape = None
        if not readiness.ready:
            raise CapabilityAuthorityError(
                "CAPABILITY_NOT_READY",
                "declared capability is not ready for this deployment",
                {"readiness": _readiness_storage_shape(readiness) if readiness_shape is None and readiness.provider_id and readiness.provider_version else readiness.to_dict()},
                retryable=True,
            )
        rep = rep or {}
        eligibility = self.evaluate_eligibility(
            flow_id,
            resource_map,
            resolution_map,
            descriptor,
            readiness,
            representation=rep,
            now=now,
            runtime_inventory=runtime_inventory,
        )
        eligibility_item = eligibility.to_dict()
        if eligibility.status != "eligible":
            raise CapabilityAuthorityError(
                "ELIGIBILITY_REQUIRED",
                "acquisition eligibility is not satisfied",
                {"eligibility": eligibility_item},
                retryable=eligibility.status in {"unknown", "auth_required", "policy_blocked"},
            )
        source = eligibility.source_fingerprint
        if preferred_container is not None:
            rep = dict(rep)
            rep["selected_container"] = preferred_container
        if effective_max_bytes is not None:
            if isinstance(effective_max_bytes, bool) or int(effective_max_bytes) < 1:
                raise CapabilityAuthorityError("INVALID_MAX_BYTES", "effective_max_bytes must be positive")
            rep = dict(rep)
            rep["effective_max_bytes"] = int(effective_max_bytes)
        representation_id = eligibility.representation_id
        item: dict[str, Any] = {
            "resource_id": resource_id,
            "resolution_id": resolution_id,
            "representation_id": representation_id,
            "capability_scope": scope,
            "strategy": descriptor.strategy or self._require_declared_strategy(descriptor),
            "provider_id": readiness.provider_id,
            "provider_version": readiness.provider_version,
            "capability_id": descriptor.capability_id,
            "descriptor_version": descriptor.descriptor_version,
            "descriptor_digest": descriptor.descriptor_digest_sha256,
            "registry_version": self.registry_snapshot.registry_version,
            "registry_digest": _digest(self.registry_snapshot.registry_digest, field="registry_digest"),
            "readiness_snapshot_id": readiness.readiness_id,
            "readiness_digest": _digest(
                str((readiness_shape or {}).get("snapshot_digest") or readiness.snapshot_digest_sha256),
                field="readiness_digest",
            ),
            "eligibility_id": eligibility.eligibility_id,
            "eligibility_digest": _digest(eligibility_item["decision_digest"], field="eligibility_digest"),
            "source_fingerprint": source,
            "representation": _clean_representation(rep),
            "position": int(position),
        }
        item["binding_digest"] = _request_digest(item)
        return item

    def prepare_selection(
        self,
        flow_id: str,
        resources: Iterable[Any],
        resolutions: Iterable[Any] | Mapping[str, Any],
        *,
        preferred_container: str | None = None,
        effective_max_bytes: int | None = None,
        now: datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        resource_list = list(resources)
        if isinstance(resolutions, Mapping):
            by_id = resolutions
            resolution_list = []
            for resource in resource_list:
                resource_map = _resource_mapping(resource)
                rid = resource_map.get("resource_id")
                resolution_list.append(by_id.get(rid) if rid is not None else None)
        else:
            resolution_list = list(resolutions)
        if len(resource_list) != len(resolution_list):
            raise CapabilityAuthorityError("RESOLUTION_REQUIRED", "one resolution is required for every selected resource")
        return [
            self.prepare_resource(
                flow_id,
                resource,
                resolution,
                preferred_container=preferred_container,
                effective_max_bytes=effective_max_bytes,
                now=now,
                position=index,
            )
            for index, (resource, resolution) in enumerate(zip(resource_list, resolution_list))
        ]

    def revalidate_plan_item(
        self,
        plan_item: Mapping[str, Any],
        resource: Any,
        resolution: Any,
        *,
        flow_id: str | None = None,
        now: datetime | str | None = None,
        runtime_inventory: Mapping[str, Any] | None = None,
    ) -> RevalidationResult:
        """Freshly re-check a prepared item before ``download_start``.

        Readiness and eligibility IDs/digests are observations, not policy
        invariants: both include timestamps and therefore legitimately change
        on every fresh probe.  Revalidation compares stable descriptor,
        provider, representation, source and policy/rights facts, then returns
        a new execution binding carrying the fresh server-owned IDs.
        """

        bound = dict(plan_item)
        checked = _utc(now)
        try:
            resource_map = _resource_mapping(resource)
            resolution_map = _resolution_mapping(resolution)
            descriptor_id = bound.get("capability_id")
            descriptor = self.select_descriptor(
                resource_map,
                descriptor_id=str(descriptor_id) if descriptor_id else None,
            )
            if _digest(descriptor.descriptor_digest, field="descriptor_digest") != bound.get("descriptor_digest"):
                return RevalidationResult(
                    False,
                    "CAPABILITY_DESCRIPTOR_DRIFT",
                    "descriptor digest changed",
                    {"expected": bound.get("descriptor_digest"), "observed": descriptor.descriptor_digest_sha256},
                )
            current_registry_digest = _digest(self.registry_snapshot.registry_digest, field="registry_digest")
            if current_registry_digest != bound.get("registry_digest") or self.registry_snapshot.registry_version != bound.get("registry_version"):
                return RevalidationResult(
                    False,
                    "CAPABILITY_REGISTRY_DRIFT",
                    "registry snapshot changed",
                    {
                        "expected": {"version": bound.get("registry_version"), "digest": bound.get("registry_digest")},
                        "observed": {"version": self.registry_snapshot.registry_version, "digest": current_registry_digest},
                    },
                )

            fresh = self.probe_readiness(
                descriptor,
                now=checked,
                runtime_inventory=runtime_inventory,
            )
            # Persist every usable fresh observation before binding eligibility;
            # Store's FK makes the readiness fact authoritative for the new
            # eligibility decision.  Missing-provider snapshots cannot be
            # persisted by Storage and are reported from the structured probe.
            readiness_shape: dict[str, Any] | None = None
            try:
                readiness_shape = self.persist_readiness(fresh)
            except CapabilityAuthorityError as exc:
                if fresh.status == "ready" and fresh.ready:
                    return RevalidationResult(False, exc.code, exc.message, exc.details, readiness=fresh)
            if fresh.expires_at is not None and checked >= _utc(fresh.expires_at):
                return RevalidationResult(
                    False,
                    "READINESS_EXPIRED",
                    "fresh readiness snapshot is expired",
                    {},
                    readiness=fresh,
                )
            if fresh.status != "ready" or not fresh.ready:
                code = "READINESS_EXPIRED" if fresh.status == "expired" else "READINESS_DRIFT"
                return RevalidationResult(
                    False,
                    code,
                    "runtime readiness is no longer ready",
                    {"status": fresh.status, "issues": _json_safe(fresh.issues)},
                    readiness=fresh,
                )
            if fresh.provider_id != bound.get("provider_id") or fresh.provider_version != bound.get("provider_version"):
                return RevalidationResult(
                    False,
                    "PROVIDER_DRIFT",
                    "provider binding changed",
                    {
                        "expected": {"id": bound.get("provider_id"), "version": bound.get("provider_version")},
                        "observed": {"id": fresh.provider_id, "version": fresh.provider_version},
                    },
                    readiness=fresh,
                )

            bound_representation_id = bound.get("representation_id")
            rep = _select_representation(
                resource_map,
                resolution_map,
                representation_id=str(bound_representation_id) if bound_representation_id else None,
                required=True,
            )
            if not representation_evidence_is_fresh(rep or {}, now=checked):
                return RevalidationResult(
                    False,
                    "RESOLUTION_STALE",
                    "representation evidence is expired or not yet valid",
                    {"resource_id": resource_map.get("resource_id")},
                    readiness=fresh,
                )
            observed_scope = self.classify_scope(resolution_map, rep)
            if observed_scope != bound.get("capability_scope"):
                return RevalidationResult(
                    False,
                    "SCOPE_DRIFT",
                    "representation scope changed",
                    {"expected": bound.get("capability_scope"), "observed": observed_scope},
                    readiness=fresh,
                )
            observed_strategy = descriptor.strategy or self._require_declared_strategy(descriptor)
            if observed_strategy != bound.get("strategy"):
                return RevalidationResult(
                    False,
                    "STRATEGY_DRIFT",
                    "capability strategy changed",
                    {"expected": bound.get("strategy"), "observed": observed_strategy},
                    readiness=fresh,
                )
            observed_rep_id = self._representation_id(resource_map, resolution_map, _clean_representation(rep or {}))
            if observed_rep_id != bound.get("representation_id"):
                return RevalidationResult(
                    False,
                    "REPRESENTATION_DRIFT",
                    "representation changed",
                    {"expected": bound.get("representation_id"), "observed": observed_rep_id},
                    readiness=fresh,
                )
            observed_source = self._source_fingerprint(resource_map, resolution_map)
            if observed_source != bound.get("source_fingerprint"):
                return RevalidationResult(
                    False,
                    "SOURCE_DRIFT",
                    "source fingerprint changed",
                    {"expected": bound.get("source_fingerprint"), "observed": observed_source},
                    readiness=fresh,
                )

            # Eligibility is flow-bound.  Prefer explicit context, then the
            # fresh resource/resolution envelope, then server persistence/cache.
            effective_flow_id = flow_id or resolution_map.get("flow_id") or resource_map.get("flow_id")
            saved: Mapping[str, Any] | None = None
            getter = getattr(self.store, "get_eligibility_decision", None) if self.store is not None else None
            if callable(getter) and bound.get("eligibility_id"):
                candidate = getter(str(bound.get("eligibility_id")))
                if isinstance(candidate, Mapping):
                    saved = candidate
                    if not isinstance(effective_flow_id, str) or not effective_flow_id:
                        candidate_flow_id = candidate.get("flow_id")
                        if isinstance(candidate_flow_id, str) and candidate_flow_id:
                            effective_flow_id = candidate_flow_id
            if saved is None and bound.get("eligibility_id"):
                candidate = self._eligibility_cache.get(str(bound.get("eligibility_id")))
                if isinstance(candidate, Mapping):
                    saved = candidate
                    if not isinstance(effective_flow_id, str) or not effective_flow_id:
                        candidate_flow_id = candidate.get("flow_id")
                        if isinstance(candidate_flow_id, str) and candidate_flow_id:
                            effective_flow_id = candidate_flow_id
            if not isinstance(effective_flow_id, str) or not effective_flow_id:
                return RevalidationResult(
                    False,
                    "ELIGIBILITY_CONTEXT_REQUIRED",
                    "original flow_id is required to revalidate eligibility",
                    {},
                    readiness=fresh,
                )

            eligibility = self.evaluate_eligibility(
                effective_flow_id,
                resource_map,
                resolution_map,
                descriptor,
                fresh,
                representation=rep or {},
                now=checked,
                runtime_inventory=runtime_inventory,
            )
            eligibility_item = eligibility.to_dict()
            if eligibility.status != "eligible":
                return RevalidationResult(
                    False,
                    "ELIGIBILITY_DRIFT",
                    "acquisition eligibility changed",
                    {"status": eligibility.status, "reason_codes": list(eligibility.reason_codes)},
                    readiness=fresh,
                    eligibility=eligibility_item,
                )
            observed_invariants = _eligibility_invariants(eligibility_item)
            expected_invariants = _eligibility_invariants(saved) if saved is not None else None
            # Older in-memory callers may carry an optional stable projection;
            # use it when no persisted decision is available.  Never compare
            # timestamp-derived eligibility_id or decision_digest values.
            if expected_invariants is None and isinstance(bound.get("eligibility_invariants"), Mapping):
                expected_invariants = _eligibility_invariants(bound["eligibility_invariants"])
            if expected_invariants is not None and expected_invariants != observed_invariants:
                return RevalidationResult(
                    False,
                    "ELIGIBILITY_DRIFT",
                    "eligibility policy or rights facts changed",
                    {"expected": expected_invariants, "observed": observed_invariants},
                    readiness=fresh,
                    eligibility=eligibility_item,
                )

            execution = _execution_binding(bound, fresh, readiness_shape, eligibility_item)
            return RevalidationResult(
                True,
                readiness=fresh,
                eligibility=eligibility_item,
                execution_binding=execution,
            )
        except CapabilityAuthorityError as exc:
            code = exc.code
            # A stale bound representation is a representation drift at the
            # plan boundary, even when the helper reports a missing ID.
            if code == "REPRESENTATION_NOT_FOUND":
                code = "REPRESENTATION_DRIFT"
            return RevalidationResult(False, code, exc.message, exc.details)
        except (PlatformRegistryError, KeyError, TypeError, ValueError) as exc:
            return RevalidationResult(False, "CAPABILITY_BINDING_CONFLICT", str(exc))

    def assert_revalidate_plan_item(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = self.revalidate_plan_item(*args, **kwargs)
        if not result.ok:
            raise CapabilityAuthorityError(result.code or "CAPABILITY_BINDING_CONFLICT", result.message or "capability binding rejected", result.details)
        return result.to_dict()

    # ------------------------------------------------------------------
    # Fallback policy
    # ------------------------------------------------------------------
    def allow_safe_fallback(
        self,
        descriptor: CapabilityDescriptor,
        fallback: CapabilityDescriptor,
        *,
        scope: str | None = None,
        strategy: str | None = None,
        provider_id: str | None = None,
    ) -> bool:
        """Return true only for an explicit, same-provider/scope/strategy route."""

        if not isinstance(descriptor, CapabilityDescriptor) or not isinstance(fallback, CapabilityDescriptor):
            return False
        fallback_id = fallback.capability_id
        declared = False
        for item in descriptor.fallbacks:
            if not isinstance(item, Mapping):
                continue
            candidate = item.get("capability_id", item.get("descriptor_id"))
            if candidate == fallback_id and bool(item.get("allowed", True)):
                declared = True
                break
        if not declared:
            return False
        expected_scope = scope or descriptor.scope_for_contract
        expected_strategy = strategy or descriptor.strategy
        if fallback.provider_id is None or descriptor.provider_id is None:
            return False
        if provider_id is not None and provider_id != descriptor.provider_id:
            return False
        if fallback.provider_id != descriptor.provider_id:
            return False
        fallback_strategy = fallback.strategy
        if expected_strategy is None or fallback_strategy != expected_strategy:
            return False
        if fallback.scope_for_contract != expected_scope or descriptor.scope_for_contract != expected_scope:
            return False
        return True

    # Friendly alias used by router callers.
    can_use_fallback = allow_safe_fallback


__all__ = [
    "CapabilityAuthorityError",
    "CapabilityCoordinator",
    "EligibilityDecision",
    "PlanCapabilityItem",
    "RevalidationResult",
    "classify_representation_scope",
]
