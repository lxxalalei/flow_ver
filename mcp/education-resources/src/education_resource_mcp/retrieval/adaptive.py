"""Offline retrieval decision oracle.

This module deliberately does **not** search, inspect, download, persist, or
manufacture public identifiers.  It consumes two already-separated inputs:

* ``FactualCoverageSummary`` and ``CandidateFact`` values produced by the MCP
  service; and
* private ``SemanticReview`` values produced by the Skill/LLM.

The oracle is useful for deterministic calibration and benchmark checks.  It
returns a bounded ``StopDecision`` plus gaps and safe follow-up signals.  It
never infers relevance, usefulness, target fit, availability, or acquisition
success from a title, URL, candidate count, or a missing field.  Missing
information is represented as ``unknown`` and cannot satisfy ``Present``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any

# This is the implementation version of the offline oracle itself.  It is not
# a semantic/model version and is intentionally separate from service-owned
# factual evidence.
ORACLE_VERSION = "2.1.0-offline"
NORMAL_MAX_ROUNDS = 3
COMPREHENSIVE_MAX_ROUNDS = 4
MAX_ROUNDS = COMPREHENSIVE_MAX_ROUNDS
MAX_CANDIDATES = 128
MAX_REVIEWS = 128
MAX_GAPS = 64
MAX_DIRECTIONS = 16
MAX_SOURCES = 32
MAX_FORMS = 16
MAX_CONSTRAINTS = 32
MAX_STRING_LENGTH = 2000
MAX_JSON_DEPTH = 8
MAX_NO_GAIN_LIMIT = 4

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CAUSE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,63}$")
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")

RESOURCE_TYPES = frozenset(
    {"article", "book", "document", "video", "audio", "course", "dataset", "other"}
)
AVAILABILITY_VALUES = frozenset(
    {"available", "partial", "unknown", "unavailable", "requires_auth", "policy_blocked", "unsupported"}
)
INSPECTION_VALUES = frozenset({"succeeded", "partial", "failed", "unsupported", "not_inspected"})
SOURCE_STATUS_VALUES = frozenset(
    {"succeeded", "failed", "auth_required", "policy_blocked", "unsupported", "unknown"}
)

# Stable machine-readable service-boundary causes.  They are intentionally
# separate from the human-facing ``Gap.reason`` text.
AUTH_REQUIRED_CAUSE = "AUTH_REQUIRED"
POLICY_BLOCKED_CAUSE = "POLICY"
UNSUPPORTED_CAUSE = "FEATURE_NOT_SUPPORTED"


class AdaptiveModelError(ValueError):
    """Raised when the bounded oracle receives unsafe or inconsistent input."""


class _ValueEnum(str, Enum):
    @classmethod
    def parse(cls, value: Any, *, field_name: str):
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise AdaptiveModelError(f"{field_name} must be one of {[item.value for item in cls]}")
        candidate = value.strip()
        for item in cls:
            if item.value == candidate:
                return item
        raise AdaptiveModelError(
            f"{field_name} has unknown value {value!r}; expected one of "
            f"{[item.value for item in cls]}"
        )


class SearchMode(_ValueEnum):
    NORMAL = "normal"
    COMPREHENSIVE = "comprehensive"


class StopDecision(_ValueEnum):
    PRESENT = "Present"
    REPLAN = "Replan"
    CLARIFY = "Clarify"
    STOP_WITH_GAP = "StopWithGap"

class GapSeverity(_ValueEnum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    OPTIONAL = "optional"


class SemanticState(_ValueEnum):
    PASS = "pass"
    WEAK = "weak"
    FAIL = "fail"
    UNKNOWN = "unknown"


class EvidenceLevel(_ValueEnum):
    SEARCH_ONLY = "search_only"
    INSPECTED = "inspected"
    UNKNOWN = "unknown"


class Availability(_ValueEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    REQUIRES_AUTH = "requires_auth"
    POLICY_BLOCKED = "policy_blocked"
    UNSUPPORTED = "unsupported"


class InspectionStatus(_ValueEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    NOT_INSPECTED = "not_inspected"


def _copy_json(value: Any, *, path: str = "$", depth: int = 0) -> Any:
    """Copy a bounded JSON-compatible value without retaining caller objects."""

    if depth > MAX_JSON_DEPTH:
        raise AdaptiveModelError(f"{path} exceeds maximum nesting depth")
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AdaptiveModelError(f"{path} must be a finite JSON number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH or _CONTROL_PATTERN.search(value):
            raise AdaptiveModelError(f"{path} contains an overlong or control-character string")
        return value
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise AdaptiveModelError(f"{path} has too many mapping entries")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise AdaptiveModelError(f"{path} has a non-string or empty key")
            result[key] = _copy_json(item, path=f"{path}.{key}", depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise AdaptiveModelError(f"{path} has too many array entries")
        return [_copy_json(item, path=f"{path}[{index}]", depth=depth + 1) for index, item in enumerate(value)]
    raise AdaptiveModelError(f"{path} contains unsupported value type {type(value).__name__}")


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptiveModelError(f"{field_name} must be an object")
    return value


def _text(value: Any, *, field_name: str, required: bool = False, limit: int = MAX_STRING_LENGTH) -> str:
    if value is None:
        if required:
            raise AdaptiveModelError(f"{field_name} is required")
        return ""
    if not isinstance(value, str):
        raise AdaptiveModelError(f"{field_name} must be a string")
    value = value.strip()
    if required and not value:
        raise AdaptiveModelError(f"{field_name} is required")
    if len(value) > limit or _CONTROL_PATTERN.search(value):
        raise AdaptiveModelError(f"{field_name} is overlong or contains control characters")
    return value


def _bounded_int(
    value: Any,
    *,
    field_name: str,
    minimum: int = 0,
    maximum: int = 256,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdaptiveModelError(f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise AdaptiveModelError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _bounded_bool(value: Any, *, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise AdaptiveModelError(f"{field_name} must be a boolean")
    return value


def _id(value: Any, *, field_name: str) -> str:
    value = _text(value, field_name=field_name, required=True, limit=128)
    if not _ID_PATTERN.fullmatch(value):
        raise AdaptiveModelError(f"{field_name} must be a bounded server-issued identifier")
    return value


def _cause_code(value: Any, *, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    value = _text(value, field_name=field_name, required=True, limit=64)
    if not _CAUSE_CODE_PATTERN.fullmatch(value):
        raise AdaptiveModelError(f"{field_name} must be an uppercase stable cause code")
    return value


def _texts(value: Any, *, field_name: str, maximum: int, item_limit: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise AdaptiveModelError(f"{field_name} must be an array")
    if len(value) > maximum:
        raise AdaptiveModelError(f"{field_name} has more than {maximum} entries")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _text(item, field_name=f"{field_name}[{index}]", required=True, limit=item_limit)
        if text not in seen:
            result.append(text)
            seen.add(text)
    return tuple(result)


def _resource_type(value: Any, *, field_name: str, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise AdaptiveModelError(f"{field_name} is required")
        return None
    value = _text(value, field_name=field_name, required=True, limit=64).lower()
    if value not in RESOURCE_TYPES:
        raise AdaptiveModelError(f"{field_name} has unknown resource type {value!r}")
    return value


@dataclass(frozen=True)
class CandidateFact:
    """A service-observed candidate fact; no semantic conclusions are inferred."""

    resource_id: str
    # ``None`` means the service did not report this fact.  It must not be
    # collapsed into ``False`` because a later explicit false is authoritative
    # and must be able to supersede an earlier true value.
    displayable: bool | None = None
    availability: Availability = Availability.UNKNOWN
    resource_type: str | None = None
    source_family: str | None = None
    inspection_status: InspectionStatus = InspectionStatus.NOT_INSPECTED
    representation_types: tuple[str, ...] = ()
    constraint_facts: dict[str, str] = field(default_factory=dict)
    provenance_confirmed: bool | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _id(self.resource_id, field_name="candidate.resource_id"))
        if self.displayable is not None and not isinstance(self.displayable, bool):
            raise AdaptiveModelError("candidate.displayable must be a boolean or null")
        object.__setattr__(self, "availability", Availability.parse(self.availability, field_name="candidate.availability"))
        object.__setattr__(self, "inspection_status", InspectionStatus.parse(self.inspection_status, field_name="candidate.inspection_status"))
        object.__setattr__(self, "resource_type", _resource_type(self.resource_type, field_name="candidate.resource_type"))
        if self.source_family is not None:
            object.__setattr__(self, "source_family", _text(self.source_family, field_name="candidate.source_family", limit=128) or None)
        reps = _texts(self.representation_types, field_name="candidate.representation_types", maximum=16, item_limit=64)
        object.__setattr__(self, "representation_types", reps)
        copied_constraints = _copy_json(self.constraint_facts, path="candidate.constraint_facts")
        if not isinstance(copied_constraints, dict):
            raise AdaptiveModelError("candidate.constraint_facts must be an object")
        for key, value in copied_constraints.items():
            if value not in {"pass", "fail", "unknown"}:
                raise AdaptiveModelError(f"candidate.constraint_facts.{key} must be pass, fail, or unknown")
        object.__setattr__(self, "constraint_facts", copied_constraints)
        if self.provenance_confirmed is not None and not isinstance(self.provenance_confirmed, bool):
            raise AdaptiveModelError("candidate.provenance_confirmed must be boolean or null")
        copied_facts = _copy_json(self.facts, path="candidate.facts")
        if not isinstance(copied_facts, dict):
            raise AdaptiveModelError("candidate.facts must be an object")
        object.__setattr__(self, "facts", copied_facts)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandidateFact":
        raw = _mapping(value, field_name="candidate")
        raw_reps = raw.get("representation_types", raw.get("representations", ()))
        return cls(
            resource_id=raw.get("resource_id", raw.get("id")),
            displayable=raw.get("displayable"),
            availability=raw.get("availability", Availability.UNKNOWN),
            resource_type=raw.get("resource_type", raw.get("type")),
            source_family=raw.get("source_family", raw.get("platform", raw.get("provider"))),
            inspection_status=raw.get("inspection_status", raw.get("inspection", InspectionStatus.NOT_INSPECTED)),
            representation_types=raw_reps,
            constraint_facts=raw.get("constraint_facts", {}),
            provenance_confirmed=raw.get("provenance_confirmed"),
            facts=raw.get("facts", {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "displayable": self.displayable,
            "availability": self.availability.value,
            "resource_type": self.resource_type,
            "source_family": self.source_family,
            "inspection_status": self.inspection_status.value,
            "representation_types": list(self.representation_types),
            "constraint_facts": dict(self.constraint_facts),
            "provenance_confirmed": self.provenance_confirmed,
            "facts": _copy_json(self.facts, path="candidate.facts"),
        }


@dataclass(frozen=True)
class SemanticReview:
    """Private Skill/LLM review; it is advisory and never service authority."""

    resource_id: str
    relevance: SemanticState = SemanticState.UNKNOWN
    usefulness: SemanticState = SemanticState.UNKNOWN
    target_fit: SemanticState = SemanticState.UNKNOWN
    constraint_fit: SemanticState = SemanticState.UNKNOWN
    substantive: SemanticState = SemanticState.UNKNOWN
    evidence_level: EvidenceLevel = EvidenceLevel.UNKNOWN
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _id(self.resource_id, field_name="semantic_review.resource_id"))
        for name in ("relevance", "usefulness", "target_fit", "constraint_fit", "substantive"):
            object.__setattr__(self, name, SemanticState.parse(getattr(self, name), field_name=f"semantic_review.{name}"))
        object.__setattr__(self, "evidence_level", EvidenceLevel.parse(self.evidence_level, field_name="semantic_review.evidence_level"))
        object.__setattr__(self, "reasons", _texts(self.reasons, field_name="semantic_review.reasons", maximum=16, item_limit=512))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SemanticReview":
        raw = _mapping(value, field_name="semantic_review")
        return cls(
            resource_id=raw.get("resource_id", raw.get("id")),
            relevance=raw.get("relevance", SemanticState.UNKNOWN),
            usefulness=raw.get("usefulness", SemanticState.UNKNOWN),
            target_fit=raw.get("target_fit", SemanticState.UNKNOWN),
            constraint_fit=raw.get("constraint_fit", SemanticState.UNKNOWN),
            substantive=raw.get("substantive", SemanticState.UNKNOWN),
            evidence_level=raw.get("evidence_level", EvidenceLevel.UNKNOWN),
            reasons=raw.get("reasons", ()),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "relevance": self.relevance.value,
            "usefulness": self.usefulness.value,
            "target_fit": self.target_fit.value,
            "constraint_fit": self.constraint_fit.value,
            "substantive": self.substantive.value,
            "evidence_level": self.evidence_level.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class InformationGain:
    """Server-reported, bounded facts about one retrieval round.

    ``observed`` is deliberately explicit.  A missing information-gain object
    is unknown and must not be treated as an observed zero-gain round.
    """

    observed: bool = False
    new_unique_candidates: int = 0
    new_source_families: int = 0
    duplicates: int = 0
    closed_gaps: tuple[str, ...] = ()
    source_failures: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.observed, bool):
            raise AdaptiveModelError("information_gain.observed must be a boolean")
        for name in ("new_unique_candidates", "new_source_families", "duplicates", "source_failures"):
            object.__setattr__(self, name, _bounded_int(getattr(self, name), field_name=f"information_gain.{name}", maximum=MAX_CANDIDATES))
        object.__setattr__(self, "closed_gaps", _texts(self.closed_gaps, field_name="information_gain.closed_gaps", maximum=MAX_GAPS, item_limit=128))

    @property
    def score(self) -> int:
        # This is a benchmark convenience, not a semantic coverage score.
        return self.new_unique_candidates + self.new_source_families + len(self.closed_gaps)

    @property
    def is_observed_zero(self) -> bool:
        return self.observed and self.score == 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "InformationGain":
        if value is None:
            return cls()
        raw = _mapping(value, field_name="information_gain")
        # Presence of any canonical gain field is evidence that the service
        # observed this round.  An explicit ``observed: false`` can be used to
        # preserve an unknown state even when a producer sends placeholders.
        gain_fields = {
            "new_unique_candidates",
            "new_source_families",
            "duplicates",
            "closed_gaps",
            "source_failures",
        }
        observed = raw.get("observed", any(key in raw for key in gain_fields))
        return cls(
            observed=observed,
            new_unique_candidates=raw.get("new_unique_candidates", 0),
            new_source_families=raw.get("new_source_families", 0),
            duplicates=raw.get("duplicates", 0),
            closed_gaps=raw.get("closed_gaps", ()),
            source_failures=raw.get("source_failures", 0),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "observed": self.observed,
            "new_unique_candidates": self.new_unique_candidates,
            "new_source_families": self.new_source_families,
            "duplicates": self.duplicates,
            "closed_gaps": list(self.closed_gaps),
            "source_failures": self.source_failures,
            "score": self.score,
        }


@dataclass(frozen=True)
class FactualCoverageSummary:
    """Service-owned factual summary; no relevance/utility judgment is stored."""

    status: str = "unknown"
    candidate_count: int = 0
    platform_count: int = 0
    resource_types: tuple[str, ...] = ()
    source_families: tuple[str, ...] = ()
    inspected_count: int = 0
    failure_codes: tuple[str, ...] = ()
    gaps: tuple[dict[str, Any], ...] = ()
    information_gain: InformationGain = field(default_factory=InformationGain)
    # Optional version of the service's machine-evidence schema.  This is not
    # a semantic/model version and may be absent when a producer does not
    # report one.
    evidence_schema_version: str | None = None

    def __post_init__(self) -> None:
        status = _text(self.status, field_name="factual_coverage.status", required=True, limit=32).lower()
        if status not in {"empty", "partial", "covered", "unknown"}:
            raise AdaptiveModelError(f"factual_coverage.status has unknown value {status!r}")
        object.__setattr__(self, "status", status)
        for name in ("candidate_count", "platform_count", "inspected_count"):
            object.__setattr__(self, name, _bounded_int(getattr(self, name), field_name=f"factual_coverage.{name}", maximum=MAX_CANDIDATES))
        object.__setattr__(self, "resource_types", tuple(_resource_type(item, field_name="factual_coverage.resource_types[]", required=True) for item in _texts(self.resource_types, field_name="factual_coverage.resource_types", maximum=MAX_FORMS, item_limit=64)))
        object.__setattr__(self, "source_families", _texts(self.source_families, field_name="factual_coverage.source_families", maximum=MAX_SOURCES, item_limit=128))
        object.__setattr__(self, "failure_codes", _texts(self.failure_codes, field_name="factual_coverage.failure_codes", maximum=MAX_GAPS, item_limit=128))
        copied_gaps = _copy_json(self.gaps, path="factual_coverage.gaps")
        if not isinstance(copied_gaps, list):
            raise AdaptiveModelError("factual_coverage.gaps must be an array")
        if len(copied_gaps) > MAX_GAPS:
            raise AdaptiveModelError(f"factual_coverage.gaps has more than {MAX_GAPS} entries")
        if any(not isinstance(item, dict) for item in copied_gaps):
            raise AdaptiveModelError("factual_coverage.gaps entries must be objects")
        object.__setattr__(self, "gaps", tuple(copied_gaps))
        object.__setattr__(self, "information_gain", InformationGain.from_mapping(self.information_gain.to_mapping() if isinstance(self.information_gain, InformationGain) else self.information_gain))
        if self.evidence_schema_version is not None:
            object.__setattr__(self, "evidence_schema_version", _text(self.evidence_schema_version, field_name="factual_coverage.evidence_schema_version", limit=64) or None)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "FactualCoverageSummary":
        if value is None:
            return cls()
        raw = _mapping(value, field_name="factual_coverage")
        # Accept the service's public coverage shape, but never derive semantic
        # dimensions from it.  Missing fields remain unknown/empty.
        failures = raw.get("failure_codes", ())
        if not failures and isinstance(raw.get("failures"), (list, tuple)):
            failures = [item.get("code") for item in raw["failures"] if isinstance(item, Mapping) and item.get("code")]
        gain = raw.get("information_gain")
        return cls(
            status=raw.get("status", "unknown"),
            candidate_count=raw.get("candidate_count", 0),
            platform_count=raw.get("platform_count", 0),
            resource_types=[
                item.get("resource_type") if isinstance(item, Mapping) else item
                for item in raw.get("resource_types", ())
            ],
            source_families=raw.get("source_families", raw.get("platforms", ())),
            inspected_count=raw.get("inspected_count", 0),
            failure_codes=failures,
            gaps=raw.get("gaps", ()),
            information_gain=InformationGain.from_mapping(gain),
            evidence_schema_version=raw.get("evidence_schema_version"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "evidence_schema_version": self.evidence_schema_version,
            "status": self.status,
            "candidate_count": self.candidate_count,
            "platform_count": self.platform_count,
            "resource_types": [{"resource_type": item, "count": 0} for item in self.resource_types],
            "source_families": list(self.source_families),
            "inspected_count": self.inspected_count,
            "failure_codes": list(self.failure_codes),
            "gaps": _copy_json(self.gaps, path="factual_coverage.gaps"),
            "information_gain": self.information_gain.to_mapping(),
        }

    def has_failure(self, code: str) -> bool:
        wanted = code.strip().casefold()
        return any(item.casefold() == wanted for item in self.failure_codes)


@dataclass(frozen=True)
class RetrievalPolicy:
    """Bounded task policy consumed by the offline oracle."""

    goal: str = ""
    user_role: str | None = None
    resource_target: str | None = None
    constraints: tuple[dict[str, Any], ...] = ()
    required_forms: tuple[str, ...] = ()
    required_sources: tuple[str, ...] = ()
    selection_min: int = 1
    requires_inspection: bool = False
    requires_substantive: bool = True
    require_source_diversity: bool = False
    mode: SearchMode = SearchMode.NORMAL
    max_rounds: int | None = None
    no_gain_limit: int = 2
    curriculum_sync: bool = False
    curriculum_scope_present: bool = False
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal", _text(self.goal, field_name="policy.goal", limit=1000))
        for name in ("user_role", "resource_target"):
            value = getattr(self, name)
            if value is not None:
                value = _text(value, field_name=f"policy.{name}", limit=32).lower()
                if value not in {"child", "parent"}:
                    raise AdaptiveModelError(f"policy.{name} must be child, parent, or null")
                object.__setattr__(self, name, value)
        object.__setattr__(self, "selection_min", _bounded_int(self.selection_min, field_name="policy.selection_min", minimum=1, maximum=8))
        object.__setattr__(self, "requires_inspection", _bounded_bool(self.requires_inspection, field_name="policy.requires_inspection"))
        object.__setattr__(self, "requires_substantive", _bounded_bool(self.requires_substantive, field_name="policy.requires_substantive", default=True))
        object.__setattr__(self, "require_source_diversity", _bounded_bool(self.require_source_diversity, field_name="policy.require_source_diversity"))
        object.__setattr__(self, "mode", SearchMode.parse(self.mode, field_name="policy.mode"))
        if self.max_rounds is not None:
            object.__setattr__(self, "max_rounds", _bounded_int(self.max_rounds, field_name="policy.max_rounds", minimum=1, maximum=MAX_ROUNDS))
        object.__setattr__(self, "no_gain_limit", _bounded_int(self.no_gain_limit, field_name="policy.no_gain_limit", minimum=1, maximum=MAX_NO_GAIN_LIMIT))
        object.__setattr__(self, "required_forms", tuple(_resource_type(item, field_name="policy.required_forms[]", required=True) for item in _texts(self.required_forms, field_name="policy.required_forms", maximum=MAX_FORMS, item_limit=64)))
        object.__setattr__(self, "required_sources", _texts(self.required_sources, field_name="policy.required_sources", maximum=MAX_SOURCES, item_limit=128))
        copied_constraints = _copy_json(self.constraints, path="policy.constraints")
        if not isinstance(copied_constraints, list):
            raise AdaptiveModelError("policy.constraints must be an array")
        if len(copied_constraints) > MAX_CONSTRAINTS:
            raise AdaptiveModelError(f"policy.constraints has more than {MAX_CONSTRAINTS} entries")
        object.__setattr__(self, "constraints", tuple(item for item in copied_constraints if isinstance(item, dict)))
        object.__setattr__(self, "curriculum_sync", _bounded_bool(self.curriculum_sync, field_name="policy.curriculum_sync"))
        object.__setattr__(self, "curriculum_scope_present", _bounded_bool(self.curriculum_scope_present, field_name="policy.curriculum_scope_present"))
        object.__setattr__(self, "conflicts", _texts(self.conflicts, field_name="policy.conflicts", maximum=MAX_GAPS, item_limit=256))

    @property
    def effective_max_rounds(self) -> int:
        if self.max_rounds is not None:
            return self.max_rounds
        return COMPREHENSIVE_MAX_ROUNDS if self.mode is SearchMode.COMPREHENSIVE else NORMAL_MAX_ROUNDS

    @property
    def hard_constraints(self) -> bool:
        return bool(self.constraints)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RetrievalPolicy":
        raw = {} if value is None else dict(_mapping(value, field_name="policy"))
        goal_value = raw.get("goal", raw.get("target", ""))
        if isinstance(goal_value, Mapping):
            goal = " ".join(
                _text(goal_value.get(key), field_name=f"policy.goal.{key}", limit=1000)
                for key in ("topic", "outcome", "description")
                if goal_value.get(key) is not None
            ).strip()
        else:
            goal = _text(goal_value, field_name="policy.goal", limit=1000)
        constraints = raw.get("constraints", ())
        if isinstance(constraints, str):
            constraints = [{"kind": "condition", "value": constraints}]
        if not isinstance(constraints, (list, tuple)):
            raise AdaptiveModelError("policy.constraints must be an array")
        normalised_constraints: list[dict[str, Any]] = []
        for index, item in enumerate(constraints):
            if isinstance(item, str):
                normalised_constraints.append({"kind": "condition", "value": _text(item, field_name=f"policy.constraints[{index}]", required=True)})
            else:
                copied = _copy_json(_mapping(item, field_name=f"policy.constraints[{index}]"), path=f"policy.constraints[{index}]")
                if not isinstance(copied, dict):
                    raise AdaptiveModelError(f"policy.constraints[{index}] must be an object")
                normalised_constraints.append(copied)
        conflicts = raw.get("conflicts", ())
        if conflicts is True:
            conflicts = ("constraint_conflict",)
        curriculum_scope_present = bool(raw.get("curriculum_scope_present")) or any(
            raw.get(key) not in (None, "", ()) for key in ("grade", "term", "volume", "edition", "curriculum_scope")
        )
        goal_lower = goal.casefold()
        curriculum_sync = bool(raw.get("curriculum_sync")) or any(token in goal_lower for token in ("教材同步", "课本同步", "同步教材"))
        return cls(
            goal=goal,
            user_role=raw.get("user_role"),
            resource_target=raw.get("resource_target"),
            constraints=tuple(normalised_constraints),
            required_forms=raw.get("required_forms", raw.get("resource_types", raw.get("forms", ()))),
            required_sources=raw.get("required_sources", raw.get("sources", ())),
            selection_min=raw.get("selection_min", 1),
            requires_inspection=raw.get("requires_inspection", raw.get("inspection_required", False)),
            requires_substantive=raw.get("requires_substantive", True),
            require_source_diversity=raw.get("require_source_diversity", raw.get("compare_sources", raw.get("source_comparison", False))),
            mode=raw.get("mode", SearchMode.NORMAL),
            max_rounds=raw.get("max_rounds"),
            no_gain_limit=raw.get("no_gain_limit", 2),
            curriculum_sync=curriculum_sync,
            curriculum_scope_present=curriculum_scope_present,
            conflicts=conflicts,
        )


@dataclass(frozen=True)
class RetrievalRound:
    """One bounded round of server facts and private reviews."""

    round_number: int
    factual_coverage: FactualCoverageSummary = field(default_factory=FactualCoverageSummary)
    candidates: tuple[CandidateFact, ...] = ()
    semantic_reviews: tuple[SemanticReview, ...] = ()
    information_gain: InformationGain = field(default_factory=InformationGain)
    source_statuses: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "round_number", _bounded_int(self.round_number, field_name="round.round_number", minimum=1, maximum=MAX_ROUNDS))
        if not isinstance(self.factual_coverage, FactualCoverageSummary):
            object.__setattr__(self, "factual_coverage", FactualCoverageSummary.from_mapping(self.factual_coverage))
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if len(self.candidates) > MAX_CANDIDATES:
            raise AdaptiveModelError(f"round.candidates has more than {MAX_CANDIDATES} entries")
        parsed_candidates: list[CandidateFact] = []
        seen_ids: set[str] = set()
        for item in self.candidates:
            candidate = item if isinstance(item, CandidateFact) else CandidateFact.from_mapping(item)
            if candidate.resource_id in seen_ids:
                raise AdaptiveModelError(f"round contains duplicate resource_id {candidate.resource_id!r}")
            seen_ids.add(candidate.resource_id)
            parsed_candidates.append(candidate)
        object.__setattr__(self, "candidates", tuple(parsed_candidates))
        if not isinstance(self.semantic_reviews, tuple):
            object.__setattr__(self, "semantic_reviews", tuple(self.semantic_reviews))
        if len(self.semantic_reviews) > MAX_REVIEWS:
            raise AdaptiveModelError(f"round.semantic_reviews has more than {MAX_REVIEWS} entries")
        parsed_reviews: list[SemanticReview] = []
        seen_reviews: set[str] = set()
        candidate_ids = {item.resource_id for item in parsed_candidates}
        for item in self.semantic_reviews:
            review = item if isinstance(item, SemanticReview) else SemanticReview.from_mapping(item)
            if review.resource_id in seen_reviews:
                raise AdaptiveModelError(f"round contains duplicate semantic review {review.resource_id!r}")
            if review.resource_id not in candidate_ids:
                raise AdaptiveModelError(f"semantic review {review.resource_id!r} has no matching candidate fact")
            seen_reviews.add(review.resource_id)
            parsed_reviews.append(review)
        object.__setattr__(self, "semantic_reviews", tuple(parsed_reviews))
        if not isinstance(self.information_gain, InformationGain):
            object.__setattr__(self, "information_gain", InformationGain.from_mapping(self.information_gain))
        object.__setattr__(self, "source_statuses", _texts(self.source_statuses, field_name="round.source_statuses", maximum=MAX_SOURCES, item_limit=64))
        for item in self.source_statuses:
            if item not in SOURCE_STATUS_VALUES:
                raise AdaptiveModelError(f"round.source_statuses has unknown value {item!r}")
        object.__setattr__(self, "directions", _texts(self.directions, field_name="round.directions", maximum=MAX_DIRECTIONS, item_limit=128))
        copied_facts = _copy_json(self.facts, path="round.facts")
        if not isinstance(copied_facts, dict):
            raise AdaptiveModelError("round.facts must be an object")
        object.__setattr__(self, "facts", copied_facts)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RetrievalRound":
        raw = _mapping(value, field_name="round")
        nested_facts = raw.get("facts")
        coverage = raw.get("factual_coverage", raw.get("coverage"))
        if coverage is None and isinstance(nested_facts, Mapping):
            coverage = nested_facts.get("factual_coverage", nested_facts.get("coverage"))
        candidates = raw.get("candidate_facts", raw.get("candidates", ()))
        reviews = raw.get("semantic_reviews", raw.get("reviews", ()))
        gain = raw.get("information_gain") if "information_gain" in raw else None
        if gain is None and "information_gain" not in raw and isinstance(nested_facts, Mapping):
            gain = nested_facts.get("information_gain")
        if gain is None and "information_gain" not in raw and isinstance(coverage, Mapping):
            gain = coverage.get("information_gain")
        source_statuses = raw.get("source_statuses", ())
        if not source_statuses and isinstance(raw.get("source_results"), (list, tuple)):
            source_statuses = [item.get("status", "unknown") for item in raw["source_results"] if isinstance(item, Mapping)]
        return cls(
            round_number=raw.get("round_number", raw.get("round", 1)),
            factual_coverage=FactualCoverageSummary.from_mapping(coverage),
            candidates=tuple(candidates),
            semantic_reviews=tuple(reviews),
            information_gain=InformationGain.from_mapping(gain),
            source_statuses=tuple(source_statuses),
            directions=raw.get("directions", ()),
            facts=nested_facts if isinstance(nested_facts, Mapping) else {},
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "factual_coverage": self.factual_coverage.to_mapping(),
            "candidates": [item.to_mapping() for item in self.candidates],
            "semantic_reviews": [item.to_mapping() for item in self.semantic_reviews],
            "information_gain": self.information_gain.to_mapping(),
            "source_statuses": list(self.source_statuses),
            "directions": list(self.directions),
            "facts": _copy_json(self.facts, path="round.facts"),
        }


@dataclass(frozen=True)
class Gap:
    gap_id: str
    dimension: str
    severity: GapSeverity
    reason: str
    action: str
    resource_ids: tuple[str, ...] = ()
    cause_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _id(self.gap_id, field_name="gap.gap_id"))
        object.__setattr__(self, "dimension", _text(self.dimension, field_name="gap.dimension", required=True, limit=64))
        object.__setattr__(self, "severity", GapSeverity.parse(self.severity, field_name="gap.severity"))
        object.__setattr__(self, "reason", _text(self.reason, field_name="gap.reason", required=True, limit=512))
        object.__setattr__(self, "action", _text(self.action, field_name="gap.action", required=True, limit=128))
        object.__setattr__(self, "resource_ids", tuple(_id(item, field_name="gap.resource_ids[]") for item in _texts(self.resource_ids, field_name="gap.resource_ids", maximum=MAX_CANDIDATES, item_limit=128)))
        object.__setattr__(self, "cause_code", _cause_code(self.cause_code, field_name="gap.cause_code"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Gap":
        raw = _mapping(value, field_name="gap")
        return cls(
            gap_id=raw.get("gap_id"),
            dimension=raw.get("dimension"),
            severity=raw.get("severity"),
            reason=raw.get("reason"),
            action=raw.get("action"),
            resource_ids=raw.get("resource_ids", ()),
            cause_code=raw.get("cause_code"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "dimension": self.dimension,
            "severity": self.severity.value,
            "reason": self.reason,
            "action": self.action,
            "resource_ids": list(self.resource_ids),
            "cause_code": self.cause_code,
        }


@dataclass(frozen=True)
class RetrievalEvaluation:
    """Bounded oracle output; advisory and never MCP authority."""

    policy: RetrievalPolicy
    rounds_evaluated: int
    factual_coverage: FactualCoverageSummary
    gaps: tuple[Gap, ...]
    information_gain: InformationGain
    stop_decision: StopDecision
    reason_code: str
    rationale: str
    no_gain_streak: int
    budget_remaining: int
    unique_candidate_count: int
    displayable_resource_ids: tuple[str, ...]
    inspect_resource_ids: tuple[str, ...]
    clarify_fields: tuple[str, ...]
    next_directions: tuple[str, ...]
    candidate_facts: tuple[CandidateFact, ...] = ()

    @property
    def mode(self) -> SearchMode:
        return self.policy.mode

    @property
    def max_rounds(self) -> int:
        return self.policy.effective_max_rounds

    @property
    def displayable_candidates(self) -> int:
        return len(self.displayable_resource_ids)

    @property
    def displayable_resources(self) -> tuple[CandidateFact, ...]:
        ids = set(self.displayable_resource_ids)
        return tuple(item for item in self.candidate_facts if item.resource_id in ids)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "oracle_version": ORACLE_VERSION,
            "mode": self.policy.mode.value,
            "rounds_evaluated": self.rounds_evaluated,
            "max_rounds": self.max_rounds,
            "budget_remaining": self.budget_remaining,
            "factual_coverage": self.factual_coverage.to_mapping(),
            "gaps": [item.to_mapping() for item in self.gaps],
            "information_gain": self.information_gain.to_mapping(),
            "stop_decision": self.stop_decision.value,
            "reason_code": self.reason_code,
            "rationale": self.rationale,
            "no_gain_streak": self.no_gain_streak,
            "unique_candidate_count": self.unique_candidate_count,
            "displayable_resource_ids": list(self.displayable_resource_ids),
            "displayable_candidates": [item.to_mapping() for item in self.displayable_resources],
            "inspect_resource_ids": list(self.inspect_resource_ids),
            "clarify_fields": list(self.clarify_fields),
            "next_directions": list(self.next_directions),
        }


def _normalise_policy(task: Mapping[str, Any] | RetrievalPolicy | None, policy: Mapping[str, Any] | RetrievalPolicy | None) -> RetrievalPolicy:
    if isinstance(policy, RetrievalPolicy):
        return policy
    if isinstance(task, RetrievalPolicy) and policy is None:
        return task
    raw: dict[str, Any] = {}
    if task is not None:
        raw.update(dict(_mapping(task, field_name="task")))
    if policy is not None:
        raw.update(dict(_mapping(policy, field_name="policy")))
    return RetrievalPolicy.from_mapping(raw)


def _normalise_rounds(rounds: Sequence[RetrievalRound | Mapping[str, Any]] | RetrievalRound | Mapping[str, Any] | None) -> tuple[RetrievalRound, ...]:
    if rounds is None:
        return ()
    if isinstance(rounds, (RetrievalRound, Mapping)):
        rounds = (rounds,)
    if not isinstance(rounds, (list, tuple)):
        raise AdaptiveModelError("rounds must be an array or one round object")
    if len(rounds) > MAX_ROUNDS:
        raise AdaptiveModelError(f"rounds has more than {MAX_ROUNDS} entries")
    parsed: list[RetrievalRound] = []
    for index, item in enumerate(rounds, start=1):
        parsed_round = item if isinstance(item, RetrievalRound) else RetrievalRound.from_mapping(item)
        if parsed_round.round_number != index:
            raise AdaptiveModelError(f"rounds[{index - 1}].round_number must be {index}")
        parsed.append(parsed_round)
    return tuple(parsed)


def _merge_candidates(rounds: Sequence[RetrievalRound]) -> tuple[CandidateFact, ...]:
    merged: dict[str, CandidateFact] = {}
    for current_round in rounds:
        for candidate in current_round.candidates:
            previous = merged.get(candidate.resource_id)
            if previous is None:
                merged[candidate.resource_id] = candidate
                continue
            # Prefer later server facts where they are more specific, but never
            # infer a fact from title/quantity/URL.
            merged[candidate.resource_id] = CandidateFact(
                resource_id=candidate.resource_id,
                # ``None`` means no fact was reported in this round.  An
                # explicit false is still a fact and must supersede an older
                # true value (latest explicit server fact wins).
                displayable=(candidate.displayable if candidate.displayable is not None else previous.displayable),
                availability=(candidate.availability if candidate.availability is not Availability.UNKNOWN else previous.availability),
                resource_type=candidate.resource_type or previous.resource_type,
                source_family=candidate.source_family or previous.source_family,
                inspection_status=(candidate.inspection_status if candidate.inspection_status is not InspectionStatus.NOT_INSPECTED else previous.inspection_status),
                representation_types=candidate.representation_types or previous.representation_types,
                constraint_facts={**previous.constraint_facts, **candidate.constraint_facts},
                provenance_confirmed=(candidate.provenance_confirmed if candidate.provenance_confirmed is not None else previous.provenance_confirmed),
                facts={**previous.facts, **candidate.facts},
            )
    return tuple(merged.values())


def _merge_reviews(rounds: Sequence[RetrievalRound]) -> dict[str, SemanticReview]:
    result: dict[str, SemanticReview] = {}
    for current_round in rounds:
        for review in current_round.semantic_reviews:
            result[review.resource_id] = review
    return result


def _hard_constraint(policy: RetrievalPolicy) -> bool:
    return policy.hard_constraints


def _candidate_machine_ready(candidate: CandidateFact, policy: RetrievalPolicy) -> bool:
    if candidate.displayable is not True:
        return False
    if candidate.availability not in {Availability.AVAILABLE, Availability.PARTIAL}:
        return False
    if policy.requires_inspection and candidate.inspection_status is not InspectionStatus.SUCCEEDED:
        return False
    return True


def _candidate_semantic_ready(candidate: CandidateFact, review: SemanticReview | None, policy: RetrievalPolicy) -> bool:
    if review is None:
        return False
    if review.relevance is not SemanticState.PASS or review.usefulness is not SemanticState.PASS:
        return False
    if policy.resource_target is not None and review.target_fit is not SemanticState.PASS:
        return False
    if _hard_constraint(policy) and review.constraint_fit is not SemanticState.PASS:
        return False
    if policy.requires_substantive and review.substantive is not SemanticState.PASS:
        return False
    if policy.requires_inspection and review.evidence_level is not EvidenceLevel.INSPECTED:
        return False
    return True


def _gap(
    gap_id: str,
    dimension: str,
    severity: GapSeverity,
    reason: str,
    action: str,
    resource_ids: Sequence[str] = (),
    cause_code: str | None = None,
) -> Gap:
    return Gap(
        gap_id=gap_id,
        dimension=dimension,
        severity=severity,
        reason=reason,
        action=action,
        resource_ids=tuple(resource_ids),
        cause_code=cause_code,
    )


def _candidate_gaps(candidate: CandidateFact, review: SemanticReview | None, policy: RetrievalPolicy) -> tuple[Gap, ...]:
    gaps: list[Gap] = []
    rid = candidate.resource_id
    if candidate.displayable is None:
        gaps.append(_gap(f"displayable:{rid}", "displayability", GapSeverity.IMPORTANT, "服务端没有报告候选是否具备可展示结构", "inspect", (rid,)))
    elif candidate.displayable is False:
        gaps.append(_gap(f"displayable:{rid}", "displayability", GapSeverity.IMPORTANT, "服务端明确标记候选不可展示", "inspect", (rid,)))
    if candidate.availability in {Availability.UNKNOWN, Availability.UNAVAILABLE}:
        gaps.append(_gap(f"availability:{rid}", "availability", GapSeverity.IMPORTANT, "服务端没有确认候选可用性", "inspect", (rid,)))
    elif candidate.availability in {Availability.REQUIRES_AUTH, Availability.POLICY_BLOCKED, Availability.UNSUPPORTED}:
        cause_code = {
            Availability.REQUIRES_AUTH: AUTH_REQUIRED_CAUSE,
            Availability.POLICY_BLOCKED: POLICY_BLOCKED_CAUSE,
            Availability.UNSUPPORTED: UNSUPPORTED_CAUSE,
        }[candidate.availability]
        gaps.append(
            _gap(
                f"availability:{rid}",
                "availability",
                GapSeverity.CRITICAL,
                f"候选被服务端标记为 {candidate.availability.value}",
                "clarify_or_stop",
                (rid,),
                cause_code,
            )
        )
    if policy.requires_inspection and candidate.inspection_status is not InspectionStatus.SUCCEEDED:
        gaps.append(_gap(f"inspection:{rid}", "inspection", GapSeverity.IMPORTANT, "任务要求资源本体检查，但候选尚未成功检查", "inspect", (rid,)))
    if review is None:
        gaps.append(_gap(f"semantic_review:{rid}", "semantic", GapSeverity.CRITICAL, "缺少 Skill SemanticReview；不能从标题或数量推断通过", "review", (rid,)))
        return tuple(gaps)
    checks = (
        ("relevance", review.relevance, GapSeverity.CRITICAL, "候选与用户目标的语义相关性未通过"),
        ("usefulness", review.usefulness, GapSeverity.IMPORTANT, "候选的使用价值尚未充分证明"),
        ("substantive", review.substantive, GapSeverity.IMPORTANT, "缺少资源本体或正文的充分证据"),
    )
    for dimension, state, severity, reason in checks:
        if state is not SemanticState.PASS:
            gaps.append(_gap(f"{dimension}:{rid}", dimension, severity, reason, "review_or_inspect", (rid,)))
    if policy.resource_target is not None and review.target_fit is not SemanticState.PASS:
        gaps.append(_gap(f"target_fit:{rid}", "target_fit", GapSeverity.CRITICAL, "候选尚未证明适合声明的 resource_target", "review_or_replan", (rid,)))
    if _hard_constraint(policy) and review.constraint_fit is not SemanticState.PASS:
        gaps.append(_gap(f"constraint_fit:{rid}", "constraint_fit", GapSeverity.CRITICAL, "显式硬约束未得到通过证据", "inspect_or_replan", (rid,)))
    if policy.requires_inspection and review.evidence_level is not EvidenceLevel.INSPECTED:
        gaps.append(_gap(f"evidence:{rid}", "evidence", GapSeverity.IMPORTANT, "任务要求检查证据，但 SemanticReview 仍是 search-only/unknown", "inspect", (rid,)))
    return tuple(gaps)


def _global_gaps(
    policy: RetrievalPolicy,
    candidates: Sequence[CandidateFact],
    reviews: Mapping[str, SemanticReview],
    rounds: Sequence[RetrievalRound],
    qualified_ids: Sequence[str],
) -> tuple[Gap, ...]:
    gaps: list[Gap] = []
    qualified = [item for item in candidates if item.resource_id in set(qualified_ids)]
    forms = {item.resource_type for item in qualified if item.resource_type}
    sources = {item.source_family for item in qualified if item.source_family}
    if policy.required_forms:
        missing = [item for item in policy.required_forms if item not in forms]
        if missing:
            gaps.append(_gap("required_forms", "form", GapSeverity.IMPORTANT, f"缺少必要资源形态: {', '.join(missing)}", "replan"))
    if policy.required_sources:
        missing = [item for item in policy.required_sources if item not in sources]
        if missing:
            gaps.append(_gap("required_sources", "source", GapSeverity.IMPORTANT, f"缺少必要来源族: {', '.join(missing)}", "replan"))
    if policy.require_source_diversity and len(sources) < 2:
        gaps.append(_gap("source_diversity", "source", GapSeverity.IMPORTANT, "横向比较任务尚未获得两个独立来源族", "replan"))
    if not candidates:
        gaps.append(_gap("no_candidates", "candidate", GapSeverity.IMPORTANT, "服务端事实中没有候选资源", "replan"))
    elif not qualified:
        gaps.append(_gap("no_qualified_candidate", "semantic", GapSeverity.CRITICAL, "没有候选同时满足必要机器事实和 SemanticReview 通过", "replan_or_stop"))
    statuses: list[str] = []
    failures: set[str] = set()
    for current_round in rounds:
        statuses.extend(current_round.source_statuses)
        failures.update(current_round.factual_coverage.failure_codes)
    status_causes = {
        "auth_required": AUTH_REQUIRED_CAUSE,
        "policy_blocked": POLICY_BLOCKED_CAUSE,
        "unsupported": UNSUPPORTED_CAUSE,
    }
    failure_aliases = {
        AUTH_REQUIRED_CAUSE: AUTH_REQUIRED_CAUSE,
        "AUTH": AUTH_REQUIRED_CAUSE,
        "AUTH_REQUIRED": AUTH_REQUIRED_CAUSE,
        POLICY_BLOCKED_CAUSE: POLICY_BLOCKED_CAUSE,
        "POLICY_BLOCKED": POLICY_BLOCKED_CAUSE,
        UNSUPPORTED_CAUSE: UNSUPPORTED_CAUSE,
        "UNSUPPORTED": UNSUPPORTED_CAUSE,
    }
    canonical_failures = {
        failure_aliases.get(item.strip().upper(), item.strip().upper())
        for item in failures
        if item.strip()
    }
    canonical_failures.update(status_causes[status] for status in statuses if status in status_causes)
    if not qualified:
        if AUTH_REQUIRED_CAUSE in canonical_failures:
            gaps.append(
                _gap(
                    "auth_required",
                    "source",
                    GapSeverity.CRITICAL,
                    "必要来源需要合法授权，服务端未获得授权",
                    "clarify",
                    cause_code=AUTH_REQUIRED_CAUSE,
                )
            )
        if POLICY_BLOCKED_CAUSE in canonical_failures:
            gaps.append(
                _gap(
                    "policy_blocked",
                    "source",
                    GapSeverity.CRITICAL,
                    "必要来源被策略边界阻断",
                    "stop_with_gap",
                    cause_code=POLICY_BLOCKED_CAUSE,
                )
            )
        if UNSUPPORTED_CAUSE in canonical_failures:
            gaps.append(
                _gap(
                    "unsupported",
                    "source",
                    GapSeverity.CRITICAL,
                    "必要来源能力未支持",
                    "stop_with_gap",
                    cause_code=UNSUPPORTED_CAUSE,
                )
            )
    return tuple(gaps)


def _next_directions(policy: RetrievalPolicy, gaps: Sequence[Gap], rounds: Sequence[RetrievalRound]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for current_round in rounds:
        for direction in current_round.directions:
            if direction not in seen:
                seen.add(direction)
                result.append(direction)
    for item in gaps:
        action = item.action
        if action in {"inspect", "review_or_inspect", "inspect_or_replan"}:
            candidate = "inspect_candidates"
        elif item.dimension == "source":
            candidate = "explore_complementary_source"
        elif item.dimension == "form":
            candidate = "search_missing_resource_form"
        elif item.dimension in {"target_fit", "constraint_fit", "semantic"}:
            candidate = "replan_semantic_direction"
        else:
            candidate = "replan_retrieval_direction"
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return tuple(result[:MAX_DIRECTIONS])


def _clarification(policy: RetrievalPolicy) -> tuple[str, ...]:
    fields: list[str] = []
    if not policy.goal:
        fields.append("goal")
    if policy.curriculum_sync and not policy.curriculum_scope_present:
        fields.extend(["grade_or_stage", "volume_or_edition"])
    if policy.conflicts:
        fields.append("conflicting_constraints")
    return tuple(dict.fromkeys(fields))


def _failure_decision(gaps: Sequence[Gap]) -> StopDecision | None:
    causes = {item.cause_code for item in gaps}
    if AUTH_REQUIRED_CAUSE in causes:
        return StopDecision.CLARIFY
    if POLICY_BLOCKED_CAUSE in causes or UNSUPPORTED_CAUSE in causes:
        return StopDecision.STOP_WITH_GAP
    return None


def evaluate_retrieval(
    task: Mapping[str, Any] | RetrievalPolicy | None,
    rounds: Sequence[RetrievalRound | Mapping[str, Any]] | RetrievalRound | Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any] | RetrievalPolicy | None = None,
) -> RetrievalEvaluation:
    """Evaluate bounded facts and private reviews without performing retrieval."""

    effective_policy = _normalise_policy(task, policy)
    parsed_rounds = _normalise_rounds(rounds)
    max_rounds = effective_policy.effective_max_rounds
    if len(parsed_rounds) > max_rounds:
        raise AdaptiveModelError(f"rounds exceeds policy max_rounds {max_rounds}")
    candidates = _merge_candidates(parsed_rounds)
    reviews = _merge_reviews(parsed_rounds)
    factual = parsed_rounds[-1].factual_coverage if parsed_rounds else FactualCoverageSummary()
    latest_gain = parsed_rounds[-1].information_gain if parsed_rounds else InformationGain()
    no_gain_streak = 0
    for current_round in parsed_rounds:
        # Unknown gain is not zero gain.  It breaks an observed zero streak;
        # only an explicitly observed, score-zero service report counts.
        if not current_round.information_gain.observed:
            no_gain_streak = 0
        elif current_round.information_gain.is_observed_zero:
            no_gain_streak += 1
        else:
            no_gain_streak = 0
    machine_candidates = [item for item in candidates if _candidate_machine_ready(item, effective_policy)]
    qualified_ids = [
        item.resource_id
        for item in machine_candidates
        if _candidate_semantic_ready(item, reviews.get(item.resource_id), effective_policy)
    ]
    candidate_gaps: list[Gap] = []
    for item in candidates:
        candidate_gaps.extend(_candidate_gaps(item, reviews.get(item.resource_id), effective_policy))
    global_gaps = list(_global_gaps(effective_policy, candidates, reviews, parsed_rounds, qualified_ids))
    clarify_fields = _clarification(effective_policy)
    if clarify_fields:
        decision = StopDecision.CLARIFY
        reason_code = "clarification_required"
        rationale = "缺少会改变检索空间的用户事实，不能用默认画像替代澄清"
    elif len(qualified_ids) >= effective_policy.selection_min:
        # Candidate-level failures belonging to non-selected resources do not
        # block a valid result.  Required form/source gaps are global and do.
        blocking_global = [item for item in global_gaps if item.dimension in {"form", "source"}]
        if blocking_global:
            decision = StopDecision.REPLAN if len(parsed_rounds) < max_rounds else StopDecision.STOP_WITH_GAP
            reason_code = "required_fact_gap"
            rationale = "已有合格候选，但任务要求的形态/来源事实仍未满足"
        else:
            decision = StopDecision.PRESENT
            reason_code = "semantic_and_factual_threshold_met"
            rationale = "至少 selection_min 个候选同时具备明确机器事实和必要 SemanticReview 通过"
    else:
        failure_decision = _failure_decision([*global_gaps, *candidate_gaps])
        if failure_decision is not None:
            decision = failure_decision
            reason_code = "service_boundary_blocked"
            rationale = "服务端记录的认证、策略或能力边界阻止了必要证据"
        elif len(parsed_rounds) >= max_rounds or no_gain_streak >= effective_policy.no_gain_limit:
            decision = StopDecision.STOP_WITH_GAP
            reason_code = "budget_or_zero_gain_exhausted"
            rationale = "仍有决策缺口，且轮次预算或连续零信息增益上限已耗尽"
        else:
            decision = StopDecision.REPLAN
            reason_code = "actionable_gap_remaining"
            rationale = "证据不足但仍有预算，应继续以缺口为中心重规划或检查候选"
    # Only expose candidate gaps that are relevant to the current decision; if
    # Present, qualified candidates have no gaps and non-selected failures are
    # advisory.  Otherwise include bounded gaps for explainability.
    if decision is StopDecision.PRESENT:
        output_gaps = tuple(global_gaps)
    else:
        combined: list[Gap] = []
        seen_gap_ids: set[str] = set()
        for item in [*global_gaps, *candidate_gaps]:
            if item.gap_id not in seen_gap_ids:
                combined.append(item)
                seen_gap_ids.add(item.gap_id)
        output_gaps = tuple(combined[:MAX_GAPS])
    inspect_ids: list[str] = []
    for item in candidates:
        review = reviews.get(item.resource_id)
        needs_inspection = (
            item.availability in {Availability.UNKNOWN, Availability.PARTIAL}
            or (effective_policy.requires_inspection and item.inspection_status is not InspectionStatus.SUCCEEDED)
            or review is None
            or (review is not None and (review.substantive in {SemanticState.UNKNOWN, SemanticState.WEAK} or (effective_policy.requires_inspection and review.evidence_level is not EvidenceLevel.INSPECTED)))
        )
        if needs_inspection and len(inspect_ids) < MAX_CANDIDATES:
            inspect_ids.append(item.resource_id)
    directions = _next_directions(effective_policy, output_gaps, parsed_rounds)
    budget_remaining = max(0, max_rounds - len(parsed_rounds))
    return RetrievalEvaluation(
        policy=effective_policy,
        rounds_evaluated=len(parsed_rounds),
        factual_coverage=factual,
        gaps=output_gaps,
        information_gain=latest_gain,
        stop_decision=decision,
        reason_code=reason_code,
        rationale=rationale,
        no_gain_streak=no_gain_streak,
        budget_remaining=budget_remaining,
        unique_candidate_count=len(candidates),
        displayable_resource_ids=tuple(qualified_ids[:MAX_CANDIDATES]),
        inspect_resource_ids=tuple(inspect_ids),
        clarify_fields=clarify_fields,
        next_directions=directions,
        candidate_facts=tuple(candidates),
    )


class AdaptiveRetrievalEvaluator:
    """Incremental helper for offline calibration only."""

    def __init__(self, task: Mapping[str, Any] | RetrievalPolicy | None = None, *, mode: SearchMode | str | None = None, policy: Mapping[str, Any] | RetrievalPolicy | None = None) -> None:
        merged_policy: Mapping[str, Any] | RetrievalPolicy | None = policy
        if mode is not None:
            if isinstance(merged_policy, Mapping):
                merged_policy = {**dict(merged_policy), "mode": mode}
            elif merged_policy is None:
                merged_policy = {"mode": mode}
            else:
                raise AdaptiveModelError("mode cannot be combined with a RetrievalPolicy object")
        self._policy = _normalise_policy(task, merged_policy)
        self._rounds: list[RetrievalRound] = []

    @property
    def rounds(self) -> tuple[RetrievalRound, ...]:
        return tuple(self._rounds)

    def add_round(self, search_round: RetrievalRound | Mapping[str, Any]) -> RetrievalEvaluation:
        parsed = search_round if isinstance(search_round, RetrievalRound) else RetrievalRound.from_mapping(search_round)
        expected = len(self._rounds) + 1
        if parsed.round_number != expected:
            raise AdaptiveModelError(f"next round_number must be {expected}")
        self._rounds.append(parsed)
        return self.evaluate()

    def evaluate(self) -> RetrievalEvaluation:
        return evaluate_retrieval(self._policy, tuple(self._rounds))


__all__ = [
    "AdaptiveModelError",
    "AdaptiveRetrievalEvaluator",
    "Availability",
    "CandidateFact",
    "COMPREHENSIVE_MAX_ROUNDS",
    "EvidenceLevel",
    "FactualCoverageSummary",
    "Gap",
    "GapSeverity",
    "InformationGain",
    "InspectionStatus",
    "NORMAL_MAX_ROUNDS",
    "ORACLE_VERSION",
    "RetrievalEvaluation",
    "RetrievalPolicy",
    "RetrievalRound",
    "SearchMode",
    "SemanticReview",
    "SemanticState",
    "StopDecision",
    "evaluate_retrieval",
]
