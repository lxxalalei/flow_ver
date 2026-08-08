"""Bounded, deterministic semantics for adaptive resource retrieval.

This module is deliberately an internal evaluator.  It does not search, call
an adapter, persist a run, or manufacture public resource IDs.  A caller gives
it a task snapshot and the facts observed during one or more search rounds;
the evaluator returns a small JSON-safe decision record.

The vocabulary follows ``CONTEXT.md``:

``SearchDirection`` is a value/evidence route, ``SearchRound`` is one bounded
set of searches evaluated together, and ``Coverage``/``Gap`` describe what is
known rather than how many results happened to be returned.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any

from .dedup import candidate_identity_key, deduplicate_candidates
from .models import CandidateResourceInternal


MODEL_VERSION = "1.0.0"
NORMAL_MAX_ROUNDS = 3
COMPREHENSIVE_MAX_ROUNDS = 4
MAX_DIRECTIONS = 8
MAX_GAPS = 32
MAX_CANDIDATES_PER_ROUND = 128
MAX_SOURCE_RESULTS_PER_ROUND = 32
MAX_INSPECTIONS_PER_ROUND = 128
MAX_STRING_LENGTH = 2000
MAX_JSON_DEPTH = 8

DIMENSIONS = (
    "target",
    "use",
    "constraints",
    "form",
    "source",
    "availability",
    "selection",
)
RESOURCE_TYPES = frozenset(
    {"article", "book", "document", "video", "audio", "course", "dataset", "other"}
)
SOURCE_STATUSES = frozenset(
    {"succeeded", "failed", "auth_required", "policy_blocked", "unsupported"}
)
AVAILABILITY_STATUSES = frozenset(
    {
        "available",
        "partial",
        "unknown",
        "unavailable",
        "requires_auth",
        "policy_blocked",
        "unsupported",
    }
)
INSPECTION_STATUSES = frozenset(
    {"succeeded", "partial", "failed", "unsupported", "not_inspected"}
)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_TEXT_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_STATE_RANK = {"unsearched": 0, "weak": 1, "covered": 2, "strong": 3}


class AdaptiveModelError(ValueError):
    """Raised when an adaptive model receives an unsafe or unknown value."""


class _ValueEnum(str, Enum):
    @classmethod
    def parse(cls, value: Any, *, field_name: str) -> "_ValueEnum":
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


class CoverageDimension(_ValueEnum):
    TARGET = "target"
    USE = "use"
    CONSTRAINTS = "constraints"
    FORM = "form"
    SOURCE = "source"
    AVAILABILITY = "availability"
    SELECTION = "selection"


class CoverageState(_ValueEnum):
    UNSEARCHED = "unsearched"
    WEAK = "weak"
    COVERED = "covered"
    STRONG = "strong"


class GapSeverity(_ValueEnum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    OPTIONAL = "optional"


class StopDecision(_ValueEnum):
    """The only terminal/replanning decisions produced by the evaluator."""

    PRESENT = "Present"
    CLARIFY = "Clarify"
    STOP_WITH_GAP = "StopWithGap"
    REPLAN = "Replan"

    # Pascal-case aliases make the public vocabulary convenient without
    # adding values to the enum.
    Present = PRESENT
    Clarify = CLARIFY
    StopWithGap = STOP_WITH_GAP
    Replan = REPLAN


def _json_copy(value: Any, *, path: str = "$", depth: int = 0) -> Any:
    """Copy only JSON values, enforcing small deterministic bounds."""

    if depth > MAX_JSON_DEPTH:
        raise AdaptiveModelError(f"{path} exceeds maximum nesting depth")
    if isinstance(value, Enum):
        return _json_copy(value.value, path=path, depth=depth)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AdaptiveModelError(f"{path} must be a finite JSON number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH or _TEXT_CONTROL_PATTERN.search(value):
            raise AdaptiveModelError(f"{path} contains an overlong or control-character string")
        return value
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise AdaptiveModelError(f"{path} has too many mapping entries")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise AdaptiveModelError(f"{path} has a non-string or empty key")
            result[key] = _json_copy(item, path=f"{path}.{key}", depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise AdaptiveModelError(f"{path} has too many list entries")
        return [_json_copy(item, path=f"{path}[{index}]", depth=depth + 1) for index, item in enumerate(value)]
    raise AdaptiveModelError(f"{path} contains a non-JSON value of type {type(value).__name__}")


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptiveModelError(f"{field_name} must be an object")
    return value


def _text(value: Any, *, field_name: str, required: bool = False, limit: int = MAX_STRING_LENGTH) -> str:
    if not isinstance(value, str):
        raise AdaptiveModelError(f"{field_name} must be a string")
    result = value.strip()
    if required and not result:
        raise AdaptiveModelError(f"{field_name} must not be empty")
    if len(result) > limit or _TEXT_CONTROL_PATTERN.search(result):
        raise AdaptiveModelError(f"{field_name} is overlong or contains control characters")
    return result


def _bounded_int(value: Any, *, field_name: str, minimum: int = 0, maximum: int = 256) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdaptiveModelError(f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise AdaptiveModelError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _unique_texts(
    value: Any,
    *,
    field_name: str,
    maximum: int,
    item_limit: int = 128,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise AdaptiveModelError(f"{field_name} must be an array of strings")
    if len(value) > maximum:
        raise AdaptiveModelError(f"{field_name} has too many values")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        parsed = _text(item, field_name=f"{field_name}[{index}]", required=True, limit=item_limit)
        if parsed not in seen:
            result.append(parsed)
            seen.add(parsed)
    return tuple(result)


def _parse_enum_list(value: Any, enum_type: type[_ValueEnum], *, field_name: str, maximum: int) -> tuple[_ValueEnum, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, enum_type)):
        value = [value]
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise AdaptiveModelError(f"{field_name} must be an array with at most {maximum} values")
    result: list[_ValueEnum] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        parsed = enum_type.parse(item, field_name=f"{field_name}[{index}]")
        if parsed.value not in seen:
            result.append(parsed)
            seen.add(parsed.value)
    return tuple(result)


def _normalise_id(value: Any, *, field_name: str, required: bool = True) -> str:
    result = _text(value, field_name=field_name, required=required, limit=64)
    if result and not _ID_PATTERN.fullmatch(result):
        raise AdaptiveModelError(f"{field_name} has an invalid bounded identifier")
    return result


@dataclass(frozen=True)
class SearchDirection:
    """A bounded route for obtaining a particular value or evidence."""

    direction_id: str
    purpose: str
    resource_types: tuple[str, ...] = ()
    source_priority: tuple[str, ...] = ()
    required_dimensions: tuple[CoverageDimension, ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction_id", _normalise_id(self.direction_id, field_name="direction_id"))
        object.__setattr__(self, "purpose", _text(self.purpose, field_name="purpose", required=True, limit=500))
        resource_types = _unique_texts(self.resource_types, field_name="resource_types", maximum=8, item_limit=32)
        for index, resource_type in enumerate(resource_types):
            if resource_type not in RESOURCE_TYPES:
                raise AdaptiveModelError(f"resource_types[{index}] has unknown value {resource_type!r}")
        object.__setattr__(self, "resource_types", resource_types)
        sources = _unique_texts(self.source_priority, field_name="source_priority", maximum=16, item_limit=64)
        for index, source in enumerate(sources):
            if not _ID_PATTERN.fullmatch(source):
                raise AdaptiveModelError(f"source_priority[{index}] must be a bounded identifier")
        object.__setattr__(self, "source_priority", sources)
        dimensions = _parse_enum_list(
            self.required_dimensions,
            CoverageDimension,
            field_name="required_dimensions",
            maximum=len(DIMENSIONS),
        )
        object.__setattr__(self, "required_dimensions", tuple(dimensions))
        object.__setattr__(self, "priority", _bounded_int(self.priority, field_name="priority", maximum=100))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SearchDirection":
        raw = _mapping(value, field_name="direction")
        direction_id = raw.get("direction_id", raw.get("id"))
        dimensions = raw.get("required_dimensions", raw.get("dimensions"))
        if dimensions is None and raw.get("dimension") is not None:
            dimensions = [raw["dimension"]]
        return cls(
            direction_id=_normalise_id(direction_id, field_name="direction_id"),
            purpose=_text(raw.get("purpose"), field_name="purpose", required=True, limit=500),
            resource_types=_unique_texts(raw.get("resource_types"), field_name="resource_types", maximum=8, item_limit=32),
            source_priority=_unique_texts(raw.get("source_priority"), field_name="source_priority", maximum=16, item_limit=64),
            required_dimensions=tuple(_parse_enum_list(dimensions, CoverageDimension, field_name="required_dimensions", maximum=len(DIMENSIONS))),
            priority=_bounded_int(raw.get("priority", 0), field_name="priority", maximum=100),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "direction_id": self.direction_id,
            "purpose": self.purpose,
            "resource_types": list(self.resource_types),
            "source_priority": list(self.source_priority),
            "required_dimensions": [item.value for item in self.required_dimensions],
            "priority": self.priority,
        }


def _candidate_mapping(value: Any, *, index: int) -> dict[str, Any]:
    if isinstance(value, CandidateResourceInternal):
        candidate = value.to_mapping()
        identity = value.identity
        if identity.native_id:
            candidate["native_id"] = identity.native_id
            if identity.native_type:
                candidate["native_type"] = identity.native_type
        if identity.isbn:
            candidate["isbn"] = identity.isbn
        if identity.doi:
            candidate["doi"] = identity.doi
        if identity.canonical_url and not candidate.get("source_url"):
            candidate["source_url"] = identity.canonical_url
    else:
        candidate = dict(_mapping(value, field_name=f"candidates[{index}]"))
    copied = _json_copy(candidate, path=f"candidates[{index}]")
    if not isinstance(copied, dict):
        raise AdaptiveModelError(f"candidates[{index}] must be an object")
    resource_type = copied.get("resource_type", copied.get("type"))
    if resource_type is not None:
        parsed_type = _text(resource_type, field_name=f"candidates[{index}].resource_type", required=True, limit=32)
        if parsed_type not in RESOURCE_TYPES:
            raise AdaptiveModelError(f"candidates[{index}].resource_type has unknown value {parsed_type!r}")
        copied["resource_type"] = parsed_type
    for key in ("availability",):
        raw = copied.get(key)
        if isinstance(raw, str):
            _parse_availability(raw, field_name=f"candidates[{index}].{key}")
        elif raw is not None and not isinstance(raw, (bool, Mapping)):
            raise AdaptiveModelError(f"candidates[{index}].{key} must be a known status, boolean, or object")
    for key in ("requires_auth", "policy_blocked", "unsupported", "displayable"):
        if key in copied and not isinstance(copied[key], bool):
            raise AdaptiveModelError(f"candidates[{index}].{key} must be boolean")
    return copied


def _parse_source_status(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise AdaptiveModelError(f"{field_name} must be a known source status")
    candidate = value.strip().casefold().replace("-", "_")
    aliases = {"success": "succeeded", "ok": "succeeded", "blocked_by_policy": "policy_blocked", "auth": "auth_required"}
    candidate = aliases.get(candidate, candidate)
    if candidate not in SOURCE_STATUSES:
        raise AdaptiveModelError(f"{field_name} has unknown value {value!r}")
    return candidate


def _parse_availability(value: Any, *, field_name: str) -> str:
    if isinstance(value, bool):
        return "available" if value else "unavailable"
    if not isinstance(value, str):
        raise AdaptiveModelError(f"{field_name} must be a known availability status")
    candidate = value.strip().casefold().replace("-", "_")
    aliases = {"login_required": "requires_auth", "auth_required": "requires_auth", "blocked": "policy_blocked"}
    candidate = aliases.get(candidate, candidate)
    if candidate not in AVAILABILITY_STATUSES:
        raise AdaptiveModelError(f"{field_name} has unknown value {value!r}")
    return candidate


def _source_mapping(value: Any, *, index: int) -> dict[str, Any]:
    copied = _json_copy(_mapping(value, field_name=f"source_results[{index}]"), path=f"source_results[{index}]")
    if not isinstance(copied, dict):
        raise AdaptiveModelError(f"source_results[{index}] must be an object")
    source = copied.get("source", copied.get("platform", copied.get("source_id")))
    if source is None:
        raise AdaptiveModelError(f"source_results[{index}] requires source, platform, or source_id")
    copied["source"] = _text(source, field_name=f"source_results[{index}].source", required=True, limit=128)
    copied["status"] = _parse_source_status(copied.get("status", "succeeded"), field_name=f"source_results[{index}].status")
    if "candidate_count" in copied:
        copied["candidate_count"] = _bounded_int(copied["candidate_count"], field_name=f"source_results[{index}].candidate_count", maximum=10000)
    if "failure_count" in copied:
        copied["failure_count"] = _bounded_int(copied["failure_count"], field_name=f"source_results[{index}].failure_count", maximum=10000)
    if "source_family" in copied:
        copied["source_family"] = _text(copied["source_family"], field_name=f"source_results[{index}].source_family", required=True, limit=128)
    return copied


def _inspection_mapping(value: Any, *, index: int) -> dict[str, Any]:
    copied = _json_copy(_mapping(value, field_name=f"inspections[{index}]"), path=f"inspections[{index}]")
    if not isinstance(copied, dict):
        raise AdaptiveModelError(f"inspections[{index}] must be an object")
    status = copied.get("status", "not_inspected")
    if not isinstance(status, str) or status.strip().casefold() not in INSPECTION_STATUSES:
        raise AdaptiveModelError(f"inspections[{index}].status has unknown value {status!r}")
    copied["status"] = status.strip().casefold()
    missing = copied.get("missing_dimensions", copied.get("missing"))
    if missing is not None:
        parsed = _parse_enum_list(missing, CoverageDimension, field_name=f"inspections[{index}].missing_dimensions", maximum=len(DIMENSIONS))
        copied["missing_dimensions"] = [item.value for item in parsed]
    return copied


@dataclass(frozen=True)
class SearchRound:
    """One bounded group of searches and the facts observed from it."""

    round_number: int = 1
    mode: SearchMode = SearchMode.NORMAL
    directions: tuple[SearchDirection, ...] = ()
    candidates: tuple[dict[str, Any], ...] = ()
    source_results: tuple[dict[str, Any], ...] = ()
    inspections: tuple[dict[str, Any], ...] = ()
    gap_closures: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "round_number", _bounded_int(self.round_number, field_name="round_number", minimum=1, maximum=COMPREHENSIVE_MAX_ROUNDS))
        object.__setattr__(self, "mode", SearchMode.parse(self.mode, field_name="mode"))
        if len(self.directions) > MAX_DIRECTIONS:
            raise AdaptiveModelError(f"directions has more than {MAX_DIRECTIONS} entries")
        directions = tuple(item if isinstance(item, SearchDirection) else SearchDirection.from_mapping(item) for item in self.directions)
        object.__setattr__(self, "directions", directions)
        if len(self.candidates) > MAX_CANDIDATES_PER_ROUND:
            raise AdaptiveModelError(f"candidates has more than {MAX_CANDIDATES_PER_ROUND} entries")
        candidates = tuple(_candidate_mapping(item, index=index) for index, item in enumerate(self.candidates))
        object.__setattr__(self, "candidates", candidates)
        if len(self.source_results) > MAX_SOURCE_RESULTS_PER_ROUND:
            raise AdaptiveModelError(f"source_results has more than {MAX_SOURCE_RESULTS_PER_ROUND} entries")
        sources = tuple(_source_mapping(item, index=index) for index, item in enumerate(self.source_results))
        object.__setattr__(self, "source_results", sources)
        if len(self.inspections) > MAX_INSPECTIONS_PER_ROUND:
            raise AdaptiveModelError(f"inspections has more than {MAX_INSPECTIONS_PER_ROUND} entries")
        inspections = tuple(_inspection_mapping(item, index=index) for index, item in enumerate(self.inspections))
        object.__setattr__(self, "inspections", inspections)
        closures = _unique_texts(self.gap_closures, field_name="gap_closures", maximum=MAX_GAPS, item_limit=96)
        for index, gap_id in enumerate(closures):
            if not _ID_PATTERN.fullmatch(gap_id):
                raise AdaptiveModelError(f"gap_closures[{index}] must be a bounded identifier")
        object.__setattr__(self, "gap_closures", closures)
        copied_facts = _json_copy(self.facts, path="facts")
        if not isinstance(copied_facts, dict):
            raise AdaptiveModelError("facts must be an object")
        object.__setattr__(self, "facts", copied_facts)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SearchRound":
        raw = _mapping(value, field_name="search_round")
        raw_directions = raw.get("directions", raw.get("search_directions", ()))
        raw_candidates = raw.get("candidates", raw.get("results", ()))
        raw_sources = raw.get("source_results", raw.get("sources", raw.get("provenance", ())))
        raw_inspections = raw.get("inspections", raw.get("inspection_results", ()))
        for field_name, field_value in (("directions", raw_directions), ("candidates", raw_candidates), ("source_results", raw_sources), ("inspections", raw_inspections)):
            if not isinstance(field_value, (list, tuple)):
                raise AdaptiveModelError(f"{field_name} must be an array")
        return cls(
            round_number=raw.get("round_number", raw.get("round", 1)),
            mode=raw.get("mode", SearchMode.NORMAL),
            directions=tuple(item if isinstance(item, SearchDirection) else SearchDirection.from_mapping(item) for item in raw_directions),
            candidates=tuple(raw_candidates),
            source_results=tuple(raw_sources),
            inspections=tuple(raw_inspections),
            gap_closures=raw.get("gap_closures", raw.get("closed_gaps", ())),
            facts=raw.get("facts", {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "mode": self.mode.value,
            "directions": [item.to_mapping() for item in self.directions],
            "candidates": _json_copy(self.candidates, path="candidates"),
            "source_results": _json_copy(self.source_results, path="source_results"),
            "inspections": _json_copy(self.inspections, path="inspections"),
            "gap_closures": list(self.gap_closures),
            "facts": _json_copy(self.facts, path="facts"),
        }


@dataclass(frozen=True)
class Coverage:
    """Coverage state for the seven required evaluation dimensions."""

    target: CoverageState = CoverageState.UNSEARCHED
    use: CoverageState = CoverageState.UNSEARCHED
    constraints: CoverageState = CoverageState.UNSEARCHED
    form: CoverageState = CoverageState.UNSEARCHED
    source: CoverageState = CoverageState.UNSEARCHED
    availability: CoverageState = CoverageState.UNSEARCHED
    selection: CoverageState = CoverageState.UNSEARCHED

    def __post_init__(self) -> None:
        for dimension in DIMENSIONS:
            object.__setattr__(self, dimension, CoverageState.parse(getattr(self, dimension), field_name=f"coverage.{dimension}"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "Coverage":
        if value is None:
            return cls()
        raw = _mapping(value, field_name="coverage")
        unknown = set(raw) - set(DIMENSIONS)
        if unknown:
            raise AdaptiveModelError(f"coverage has unknown dimensions {sorted(unknown)}")
        return cls(**{dimension: raw.get(dimension, CoverageState.UNSEARCHED) for dimension in DIMENSIONS})

    def state_for(self, dimension: str | CoverageDimension) -> CoverageState:
        parsed = CoverageDimension.parse(dimension, field_name="dimension")
        return getattr(self, parsed.value)

    @property
    def dimensions(self) -> dict[str, str]:
        return self.to_mapping()

    def to_mapping(self) -> dict[str, str]:
        return {dimension: getattr(self, dimension).value for dimension in DIMENSIONS}


@dataclass(frozen=True)
class Gap:
    """A necessary, decision-relevant unmet or unverified condition."""

    gap_id: str
    dimension: CoverageDimension
    severity: GapSeverity
    reason: str
    required_action: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _normalise_id(self.gap_id, field_name="gap_id"))
        object.__setattr__(self, "dimension", CoverageDimension.parse(self.dimension, field_name="gap.dimension"))
        object.__setattr__(self, "severity", GapSeverity.parse(self.severity, field_name="gap.severity"))
        object.__setattr__(self, "reason", _text(self.reason, field_name="gap.reason", required=True, limit=500))
        object.__setattr__(self, "required_action", _text(self.required_action, field_name="gap.required_action", limit=500))
        copied = _json_copy(self.evidence, path="gap.evidence")
        if not isinstance(copied, dict):
            raise AdaptiveModelError("gap.evidence must be an object")
        object.__setattr__(self, "evidence", copied)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Gap":
        raw = _mapping(value, field_name="gap")
        return cls(
            gap_id=raw.get("gap_id", raw.get("id")),
            dimension=raw.get("dimension"),
            severity=raw.get("severity"),
            reason=raw.get("reason"),
            required_action=raw.get("required_action", raw.get("action", "")),
            evidence=raw.get("evidence", {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "dimension": self.dimension.value,
            "severity": self.severity.value,
            "reason": self.reason,
            "required_action": self.required_action,
            "evidence": _json_copy(self.evidence, path="gap.evidence"),
        }


@dataclass(frozen=True)
class InformationGain:
    """Objective facts describing the decision value added by one round."""

    new_candidates: int = 0
    new_unique_resources: int = 0
    new_displayable_candidates: int = 0
    new_source_families: int = 0
    duplicates: int = 0
    closed_gaps: tuple[str, ...] = ()
    source_failures: int = 0
    score: int = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("new_candidates", "new_unique_resources", "new_displayable_candidates", "new_source_families", "duplicates", "source_failures"):
            object.__setattr__(self, field_name, _bounded_int(getattr(self, field_name), field_name=field_name, maximum=MAX_CANDIDATES_PER_ROUND * 2))
        if self.duplicates > self.new_candidates:
            raise AdaptiveModelError("duplicates cannot exceed new_candidates")
        closures = _unique_texts(self.closed_gaps, field_name="closed_gaps", maximum=MAX_GAPS, item_limit=96)
        for index, gap_id in enumerate(closures):
            if not _ID_PATTERN.fullmatch(gap_id):
                raise AdaptiveModelError(f"closed_gaps[{index}] must be a bounded identifier")
        object.__setattr__(self, "closed_gaps", closures)
        computed = (
            self.new_unique_resources * 3
            + self.new_displayable_candidates * 2
            + self.new_source_families
            + len(self.closed_gaps) * 4
        )
        object.__setattr__(self, "score", computed)

    @property
    def new_unique_candidates(self) -> int:
        return self.new_unique_resources

    @property
    def gap_closures(self) -> tuple[str, ...]:
        return self.closed_gaps

    @property
    def is_zero(self) -> bool:
        return not (
            self.new_unique_resources
            or self.new_displayable_candidates
            or self.new_source_families
            or self.closed_gaps
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "new_candidates": self.new_candidates,
            "new_unique_candidates": self.new_unique_resources,
            "new_unique_resources": self.new_unique_resources,
            "new_displayable_candidates": self.new_displayable_candidates,
            "new_source_families": self.new_source_families,
            "duplicates": self.duplicates,
            "closed_gaps": list(self.closed_gaps),
            "gap_closures": list(self.closed_gaps),
            "source_failures": self.source_failures,
            "score": self.score,
        }


@dataclass(frozen=True)
class RoundEvaluation:
    round_number: int
    coverage: Coverage
    gaps: tuple[Gap, ...]
    information_gain: InformationGain
    stop_decision: StopDecision
    reason_code: str
    no_gain_streak: int

    @property
    def decision(self) -> StopDecision:
        return self.stop_decision

    def to_mapping(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "coverage": self.coverage.to_mapping(),
            "gaps": [item.to_mapping() for item in self.gaps],
            "information_gain": self.information_gain.to_mapping(),
            "stop_decision": self.stop_decision.value,
            "decision": self.stop_decision.value,
            "reason_code": self.reason_code,
            "no_gain_streak": self.no_gain_streak,
        }


@dataclass(frozen=True)
class RetrievalEvaluation:
    mode: SearchMode
    rounds_evaluated: int
    coverage: Coverage
    gaps: tuple[Gap, ...]
    information_gain: InformationGain
    stop_decision: StopDecision
    reason_code: str
    rationale: str
    no_gain_streak: int
    max_rounds: int
    budget_remaining: int
    unique_candidates: int
    displayable_candidates: int
    next_directions: tuple[SearchDirection, ...] = ()
    round_evaluations: tuple[RoundEvaluation, ...] = ()

    @property
    def decision(self) -> StopDecision:
        return self.stop_decision

    @property
    def stop(self) -> StopDecision:
        return self.stop_decision

    def to_mapping(self) -> dict[str, Any]:
        return {
            "model_version": MODEL_VERSION,
            "mode": self.mode.value,
            "rounds_evaluated": self.rounds_evaluated,
            "coverage": self.coverage.to_mapping(),
            "gaps": [item.to_mapping() for item in self.gaps],
            "information_gain": self.information_gain.to_mapping(),
            "stop_decision": self.stop_decision.value,
            "decision": self.stop_decision.value,
            "reason_code": self.reason_code,
            "rationale": self.rationale,
            "no_gain_streak": self.no_gain_streak,
            "max_rounds": self.max_rounds,
            "budget_remaining": self.budget_remaining,
            "unique_candidates": self.unique_candidates,
            "displayable_candidates": self.displayable_candidates,
            "next_directions": [item.to_mapping() for item in self.next_directions],
            "rounds": [item.to_mapping() for item in self.round_evaluations],
        }


@dataclass(frozen=True)
class _TaskContext:
    goal: str
    user_role: str | None
    resource_target: str | None
    constraints: tuple[dict[str, Any], ...]
    required_forms: tuple[str, ...]
    required_sources: tuple[str, ...]
    selection_min: int
    inspection_required: bool
    mode: SearchMode
    curriculum_sync: bool
    curriculum_scope_present: bool
    conflict: bool
    required_dimensions: frozenset[str]


def _normalise_task(task: Mapping[str, Any] | None, mode: SearchMode | str | None) -> _TaskContext:
    raw = {} if task is None else dict(_mapping(task, field_name="task"))
    goal_value = raw.get("goal", raw.get("target", ""))
    if isinstance(goal_value, Mapping):
        goal = " ".join(
            _text(goal_value.get(key), field_name=f"task.goal.{key}", limit=1000)
            for key in ("topic", "outcome")
            if goal_value.get(key) is not None
        ).strip()
        if not goal:
            goal = _text(goal_value.get("description", ""), field_name="task.goal.description", limit=1000)
    elif goal_value is None:
        goal = ""
    else:
        goal = _text(goal_value, field_name="task.goal", limit=1000)

    user_role = raw.get("user_role")
    resource_target = raw.get("resource_target")
    for field_name, value in (("user_role", user_role), ("resource_target", resource_target)):
        if value is not None and value not in {"child", "parent"}:
            raise AdaptiveModelError(f"task.{field_name} has unknown value {value!r}")

    raw_constraints = raw.get("constraints", ())
    if not isinstance(raw_constraints, (list, tuple)):
        raise AdaptiveModelError("task.constraints must be an array")
    if len(raw_constraints) > 32:
        raise AdaptiveModelError("task.constraints has too many entries")
    constraints: list[dict[str, Any]] = []
    for index, item in enumerate(raw_constraints):
        if isinstance(item, str):
            constraints.append({"kind": "condition", "value": _text(item, field_name=f"task.constraints[{index}]", required=True, limit=1000)})
            continue
        copied = _json_copy(_mapping(item, field_name=f"task.constraints[{index}]"), path=f"task.constraints[{index}]")
        if not isinstance(copied, dict):
            raise AdaptiveModelError(f"task.constraints[{index}] must be an object")
        kind = _text(copied.get("kind", "condition"), field_name=f"task.constraints[{index}].kind", required=True, limit=64)
        value = _text(copied.get("value"), field_name=f"task.constraints[{index}].value", required=True, limit=1000)
        copied["kind"] = kind
        copied["value"] = value
        constraints.append(copied)
    constraint_text = " ".join(f"{item['kind']} {item['value']}" for item in constraints)
    all_text = f"{goal} {constraint_text}".casefold()

    raw_forms = raw.get("required_forms", raw.get("resource_types", raw.get("forms")))
    required_forms = list(_unique_texts(raw_forms, field_name="task.required_forms", maximum=8, item_limit=32))
    for index, form in enumerate(required_forms):
        if form not in RESOURCE_TYPES:
            raise AdaptiveModelError(f"task.required_forms[{index}] has unknown value {form!r}")
    if not required_forms:
        form_tokens = {
            "视频": "video",
            "音频": "audio",
            "图书": "book",
            "书": "book",
            "文章": "article",
            "文档": "document",
            "课程": "course",
            "数据集": "dataset",
        }
        for token, form in form_tokens.items():
            if token in all_text and form not in required_forms:
                required_forms.append(form)
    required_sources = list(_unique_texts(raw.get("required_sources", raw.get("sources")), field_name="task.required_sources", maximum=16, item_limit=128))
    for item in constraints:
        kind = item["kind"].casefold()
        if any(token in kind for token in ("source", "platform", "来源", "平台")):
            value = item["value"]
            if value not in required_sources:
                required_sources.append(value)

    selection_min = _bounded_int(raw.get("selection_min", 1), field_name="task.selection_min", minimum=1, maximum=8)
    inspection_required = raw.get("inspection_required", raw.get("inspect", False))
    if not isinstance(inspection_required, bool):
        raise AdaptiveModelError("task.inspection_required must be boolean")
    selected_mode = SearchMode.parse(mode if mode is not None else raw.get("mode", SearchMode.NORMAL), field_name="mode")

    curriculum_sync = bool(re.search(r"教材\s*(同步|配套)|同步\s*教材|课本\s*(同步|配套)|指定册次|教辅", all_text))
    scope_pattern = r"(?:[一二三四五六七八九十零0-9]+\s*年级|grade\s*[0-9一二三四五六七八九十]+|第\s*[一二三四五六七八九十0-9]+\s*册|册次|教材版本|教版|curriculum\s*(?:version|grade))"
    curriculum_scope_present = bool(re.search(scope_pattern, all_text, flags=re.I)) or any(
        key in raw and raw.get(key) not in (None, "", [])
        for key in ("grade", "grade_level", "grade_levels", "volume", "book", "subject", "curriculum_version", "curriculum_versions")
    )
    conflict = bool(raw.get("conflicts"))
    if raw.get("conflicts") is not None:
        if not isinstance(raw["conflicts"], (list, tuple)):
            raise AdaptiveModelError("task.conflicts must be an array")
        _json_copy(raw["conflicts"], path="task.conflicts")
    conflict_pairs = (("免费", "付费"), ("free", "paid"), ("视频", "不要视频"), ("video", "no video"), ("官方", "非官方"))
    conflict = conflict or any(left in all_text and right in all_text for left, right in conflict_pairs)
    must = [item["value"].casefold() for item in constraints if item["kind"].casefold() in {"must", "required", "hard", "exclude"}]
    for left in must:
        for right in must:
            if left != right and (("free" in left or "免费" in left) and ("paid" in right or "付费" in right)):
                conflict = True

    required_dimensions = {"target", "availability", "selection"}
    if resource_target is not None:
        required_dimensions.add("use")
    if constraints:
        required_dimensions.add("constraints")
    if required_forms:
        required_dimensions.add("form")
    if required_sources:
        required_dimensions.add("source")
    return _TaskContext(
        goal=goal,
        user_role=user_role,
        resource_target=resource_target,
        constraints=tuple(constraints),
        required_forms=tuple(required_forms),
        required_sources=tuple(required_sources),
        selection_min=selection_min,
        inspection_required=inspection_required,
        mode=selected_mode,
        curriculum_sync=curriculum_sync,
        curriculum_scope_present=curriculum_scope_present,
        conflict=conflict,
        required_dimensions=frozenset(required_dimensions),
    )


def _nested_maps(candidate: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield candidate
    for key in ("evidence", "signals", "platform_signals", "metadata"):
        value = candidate.get(key)
        if isinstance(value, Mapping):
            yield value
            nested = value.get("platform_signals")
            if isinstance(nested, Mapping):
                yield nested


def _fact(candidate: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for mapping in _nested_maps(candidate):
        for key in keys:
            if key in mapping:
                return mapping[key]
    return None


def _explicit_state(candidate: Mapping[str, Any], dimension: str) -> CoverageState | None:
    values: list[Any] = []
    for mapping in _nested_maps(candidate):
        coverage = mapping.get("coverage")
        if isinstance(coverage, Mapping) and dimension in coverage:
            values.append(coverage[dimension])
        direct = mapping.get(f"{dimension}_coverage")
        if direct is not None:
            values.append(direct)
    if not values:
        return None
    states = [CoverageState.parse(item, field_name=f"candidate.{dimension}_coverage") for item in values]
    return max(states, key=lambda item: _STATE_RANK[item.value])


def _explicit_bool(candidate: Mapping[str, Any], keys: Sequence[str]) -> bool | None:
    value = _fact(candidate, keys)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return bool(value)
    if isinstance(value, str):
        parsed = value.strip().casefold()
        if parsed in {"true", "yes", "covered", "strong", "available", "satisfied", "pass", "ok"}:
            return True
        if parsed in {"false", "no", "weak", "unsearched", "unavailable", "failed", "missing", "blocked"}:
            return False
    return None


def _candidate_status(candidate: Mapping[str, Any]) -> str:
    if candidate.get("requires_auth") is True:
        return "requires_auth"
    if candidate.get("policy_blocked") is True:
        return "policy_blocked"
    if candidate.get("unsupported") is True:
        return "unsupported"
    value = candidate.get("availability")
    if isinstance(value, Mapping):
        value = value.get("status", value.get("value"))
    if value is None:
        return "available"
    return _parse_availability(value, field_name="candidate.availability")


def _candidate_displayable(candidate: Mapping[str, Any]) -> bool:
    explicit = _explicit_bool(candidate, ("displayable", "selection_ready"))
    if _candidate_status(candidate) in {"requires_auth", "policy_blocked", "unsupported", "unavailable"}:
        return False
    if explicit is False:
        return False
    title = candidate.get("title", candidate.get("name"))
    if not isinstance(title, str) or not title.strip():
        return False
    if explicit is True:
        return True
    return True


def _candidate_forms(candidate: Mapping[str, Any]) -> set[str]:
    forms: set[str] = set()
    value = candidate.get("resource_type", candidate.get("type"))
    if isinstance(value, str) and value in RESOURCE_TYPES:
        forms.add(value)
    for mapping in _nested_maps(candidate):
        for key in ("form", "forms", "format", "formats"):
            raw = mapping.get(key)
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, (list, tuple)):
                for item in raw:
                    if isinstance(item, str):
                        value = item.casefold()
                        aliases = {
                            "mp4": "video", "mkv": "video", "video": "video",
                            "mp3": "audio", "m4a": "audio", "audio": "audio",
                            "pdf": "document", "docx": "document", "pptx": "document", "document": "document",
                            "epub": "book", "book": "book", "article": "article", "course": "course", "dataset": "dataset",
                        }
                        if value in aliases:
                            forms.add(aliases[value])
        representations = mapping.get("representations")
        if isinstance(representations, (list, tuple)):
            for representation in representations:
                if isinstance(representation, Mapping):
                    nested = dict(representation)
                    forms.update(_candidate_forms(nested))
    return forms


def _candidate_match(candidate: Mapping[str, Any], dimension: str) -> bool | None:
    keys = {
        "target": ("target_match", "topic_match", "relevant", "relevance_match"),
        "use": ("use_match", "audience_match", "resource_target_match"),
        "constraints": ("constraint_match", "constraints_match", "constraints_satisfied", "meets_constraints"),
        "form": ("form_match", "forms_match"),
        "source": ("source_match", "source_verified"),
        "availability": ("available", "availability_verified", "accessible"),
        "selection": ("selection_ready", "displayable"),
    }
    return _explicit_bool(candidate, keys[dimension])


def _source_summary(source_results: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]]) -> tuple[set[str], set[str], int, set[str]]:
    successful: set[str] = set()
    families: set[str] = set()
    failures = 0
    statuses: set[str] = set()
    for source in source_results:
        source_id = str(source["source"])
        status = str(source["status"])
        statuses.add(status)
        family = str(source.get("source_family") or source_id)
        if status == "succeeded":
            successful.add(source_id)
            families.add(family)
        else:
            failures += 1
    for candidate in candidates:
        platform = candidate.get("platform", candidate.get("source"))
        if isinstance(platform, str) and platform:
            families.add(platform)
    return successful, families, failures, statuses


def _inspection_missing_dimensions(
    candidates: Sequence[Mapping[str, Any]], inspections: Sequence[Mapping[str, Any]], *, task: _TaskContext
) -> set[str]:
    missing: set[str] = set()
    for inspection in inspections:
        if inspection.get("status") in {"partial", "failed", "not_inspected"}:
            missing.update(inspection.get("missing_dimensions", ()))
            if inspection.get("status") != "succeeded" and not inspection.get("missing_dimensions"):
                missing.add("availability")
    for candidate in candidates:
        status = _fact(candidate, ("inspection_status",))
        if isinstance(status, str) and status.casefold() in {"partial", "failed", "not_inspected"}:
            raw_missing = _fact(candidate, ("missing_dimensions", "inspection_missing"))
            if isinstance(raw_missing, str):
                raw_missing = [raw_missing]
            if isinstance(raw_missing, (list, tuple)):
                for item in raw_missing:
                    missing.add(CoverageDimension.parse(item, field_name="inspection_missing").value)
            else:
                missing.add("availability")
    if task.inspection_required and candidates and not inspections and not any(_fact(item, ("inspection_status",)) for item in candidates):
        missing.add("availability")
    return missing


def _constraint_match(candidate: Mapping[str, Any], task: _TaskContext) -> bool | None:
    if not task.constraints:
        return True
    direct = _candidate_match(candidate, "constraints")
    if direct is not None:
        return direct
    raw = _fact(candidate, ("constraints", "constraint_results"))
    if isinstance(raw, Mapping):
        values: list[bool] = []
        for item in task.constraints:
            key = item["kind"]
            value = raw.get(key)
            if isinstance(value, bool):
                values.append(value)
        if values:
            return all(values)
    return None


def _coverage_for(
    task: _TaskContext,
    candidates: Sequence[Mapping[str, Any]],
    source_results: Sequence[Mapping[str, Any]],
    inspections: Sequence[Mapping[str, Any]],
    directions: Sequence[SearchDirection],
) -> Coverage:
    displayable = [candidate for candidate in candidates if _candidate_displayable(candidate)]
    successful_sources, source_families, _failures, statuses = _source_summary(source_results, candidates)

    # target
    if not task.goal:
        target = CoverageState.UNSEARCHED
    elif not candidates:
        target = CoverageState.UNSEARCHED
    else:
        matches = [_candidate_match(candidate, "target") for candidate in candidates]
        # A candidate returned through an already-directed search is usable
        # target evidence even when the provider has no separate relevance
        # flag.  Explicit false evidence still blocks the claim.
        target = CoverageState.STRONG if any(item is True for item in matches) else CoverageState.COVERED
        if all(item is False for item in matches):
            target = CoverageState.UNSEARCHED
    # use is intentionally independent of user_role; the resource target is
    # the relevant search fact.
    if task.resource_target is None:
        use = CoverageState.STRONG
    elif not candidates:
        use = CoverageState.UNSEARCHED
    else:
        matches = [_candidate_match(candidate, "use") for candidate in candidates]
        use = CoverageState.STRONG if any(item is True for item in matches) else CoverageState.WEAK
        if any(item is False for item in matches) and not any(item is True for item in matches):
            use = CoverageState.UNSEARCHED
        elif any(item is None for item in matches) and not any(item is True for item in matches):
            use = CoverageState.WEAK
    # constraints
    if not task.constraints:
        constraints = CoverageState.STRONG
    else:
        matches = [_constraint_match(candidate, task) for candidate in candidates]
        constraints = CoverageState.STRONG if any(item is True for item in matches) else CoverageState.WEAK
        if any(item is False for item in matches) and not any(item is True for item in matches):
            constraints = CoverageState.UNSEARCHED
        elif any(item is None for item in matches) and not any(item is True for item in matches):
            constraints = CoverageState.WEAK
    # form
    if not candidates:
        form = CoverageState.STRONG if not task.required_forms else CoverageState.UNSEARCHED
    else:
        candidate_forms = set().union(*(_candidate_forms(candidate) for candidate in candidates))
        explicit_form = any(_candidate_match(candidate, "form") is True for candidate in candidates)
        if not task.required_forms:
            form = CoverageState.STRONG if len(candidate_forms) > 1 or explicit_form else CoverageState.COVERED
        elif all(item in candidate_forms for item in task.required_forms):
            form = CoverageState.STRONG
        elif any(item in candidate_forms for item in task.required_forms):
            form = CoverageState.COVERED
        else:
            form = CoverageState.WEAK
    # source
    if task.required_sources:
        matched = {source.casefold() for source in successful_sources}
        required = {source.casefold() for source in task.required_sources}
        if required <= matched:
            source = CoverageState.STRONG
        elif matched & required:
            source = CoverageState.COVERED
        elif source_results or candidates:
            source = CoverageState.WEAK
        else:
            source = CoverageState.UNSEARCHED
    elif source_families:
        source = CoverageState.STRONG if len(source_families) >= 2 else CoverageState.COVERED
    elif source_results:
        source = CoverageState.WEAK
    else:
        source = CoverageState.UNSEARCHED
    # availability
    statuses_for_candidates = [_candidate_status(candidate) for candidate in candidates]
    available_count = sum(item == "available" or item == "partial" for item in statuses_for_candidates)
    if not candidates:
        availability = CoverageState.UNSEARCHED
    elif available_count == len(candidates) and available_count > 0:
        availability = CoverageState.STRONG
    elif available_count > 0:
        availability = CoverageState.COVERED
    else:
        availability = CoverageState.WEAK
    # selection
    if len(displayable) >= task.selection_min:
        selection = CoverageState.STRONG
    elif displayable:
        selection = CoverageState.COVERED
    else:
        selection = CoverageState.UNSEARCHED
    hints = {dimension: [] for dimension in DIMENSIONS}
    for candidate in candidates:
        for dimension in DIMENSIONS:
            hint = _explicit_state(candidate, dimension)
            if hint is not None:
                hints[dimension].append(hint)
    values = {
        "target": target,
        "use": use,
        "constraints": constraints,
        "form": form,
        "source": source,
        "availability": availability,
        "selection": selection,
    }
    for dimension, states in hints.items():
        if states:
            values[dimension] = max((values[dimension], *states), key=lambda item: _STATE_RANK[item.value])
    # A direction that explicitly owns a dimension is evidence that it was
    # searched, but never enough to claim coverage on its own.
    for direction in directions:
        for dimension in direction.required_dimensions:
            if values[dimension.value] == CoverageState.UNSEARCHED:
                values[dimension.value] = CoverageState.WEAK
    return Coverage(**values)


def _gap(
    gap_id: str,
    dimension: str,
    severity: str,
    reason: str,
    action: str,
    evidence: Mapping[str, Any] | None = None,
) -> Gap:
    return Gap(gap_id, CoverageDimension.parse(dimension, field_name="gap.dimension"), GapSeverity.parse(severity, field_name="gap.severity"), reason, action, dict(evidence or {}))


def _gaps_for(
    task: _TaskContext,
    coverage: Coverage,
    candidates: Sequence[Mapping[str, Any]],
    source_results: Sequence[Mapping[str, Any]],
    inspections: Sequence[Mapping[str, Any]],
) -> tuple[Gap, ...]:
    gaps: list[Gap] = []
    displayable = [candidate for candidate in candidates if _candidate_displayable(candidate)]
    _successful, source_families, source_failures, source_statuses = _source_summary(source_results, candidates)
    if not task.goal:
        gaps.append(_gap("gap_target", "target", "critical", "核心学习目标尚未确定", "clarify_goal"))
    if task.curriculum_sync and not task.curriculum_scope_present:
        gaps.append(_gap("gap_curriculum_scope", "constraints", "critical", "教材同步需要年级、册次或教材版本范围", "clarify_curriculum_scope"))
    if task.conflict:
        gaps.append(_gap("gap_conflicting_constraints", "constraints", "critical", "显式目标或硬约束相互冲突", "clarify_conflict"))

    for dimension in DIMENSIONS:
        if dimension not in task.required_dimensions:
            continue
        state = coverage.state_for(dimension)
        if state not in {CoverageState.UNSEARCHED, CoverageState.WEAK}:
            continue
        if dimension == "target" and candidates:
            severity, reason, action = "important", "候选与核心目标的匹配证据仍弱", "replan_target_direction"
        elif dimension == "use":
            severity, reason, action = "important", "资源使用对象的匹配证据不足", "inspect_use_fit"
        elif dimension == "constraints":
            severity = "critical" if any(item["kind"].casefold() in {"must", "required", "hard", "exclude"} for item in task.constraints) else "important"
            reason, action = "硬约束尚未被候选证据关闭", "verify_constraints"
        elif dimension == "form":
            severity, reason, action = "important", "所需资源形态尚未覆盖", "replan_form_direction"
        elif dimension == "source":
            severity, reason, action = ("critical" if task.required_sources else "important"), "指定或互补来源尚未获得可靠结果", "replan_source_direction"
        elif dimension == "availability":
            severity, reason, action = "important", "候选可用性尚未确认", "inspect_availability"
        else:
            severity, reason, action = "important", "还没有足够候选供用户选择", "replan_selection_direction"
        gaps.append(_gap(f"gap_{dimension}", dimension, severity, reason, action))

    if task.required_forms:
        available_forms = set().union(*(_candidate_forms(candidate) for candidate in candidates)) if candidates else set()
        missing_forms = sorted(set(task.required_forms) - available_forms)
        if missing_forms:
            severity = "critical" if "form" in task.required_dimensions and any(item["kind"].casefold() in {"must", "required", "hard", "exclude"} for item in task.constraints) else "important"
            gaps.append(_gap("gap_missing_forms", "form", severity, "仍缺少所需资源形态: " + ",".join(missing_forms), "replan_form_direction", {"missing_forms": missing_forms}))
    if task.required_sources:
        successful = {str(item["source"]).casefold() for item in source_results if item["status"] == "succeeded"}
        missing_sources = sorted({item.casefold() for item in task.required_sources} - successful)
        if missing_sources:
            gaps.append(_gap("gap_required_source", "source", "critical", "指定来源尚未成功返回结果", "clarify_or_replan_source", {"missing_sources": missing_sources}))

    missing_inspection = _inspection_missing_dimensions(candidates, inspections, task=task)
    for dimension in sorted(missing_inspection):
        gaps.append(_gap(f"gap_inspection_{dimension}", dimension, "important", f"inspection 尚未关闭 {dimension} 证据缺口", f"inspect_{dimension}"))
    if source_failures and not displayable:
        if "auth_required" in source_statuses:
            gaps.append(_gap("gap_authentication", "source", "critical", "可用来源需要用户合法认证", "clarify_authentication"))
        elif "policy_blocked" in source_statuses:
            gaps.append(_gap("gap_policy", "source", "critical", "来源被服务端策略阻断，不能绕过", "stop_with_gap"))
        elif "unsupported" in source_statuses:
            gaps.append(_gap("gap_unsupported", "source", "critical", "请求路线或来源不受支持", "stop_with_gap"))
        else:
            gaps.append(_gap("gap_source_failure", "source", "important", "本轮来源失败且没有可展示候选", "replan_source"))
    elif source_failures and task.required_sources:
        gaps.append(_gap("gap_source_failure", "source", "important", "部分来源失败，指定来源证据不完整", "replan_source"))
    if not candidates and not source_results and task.goal:
        gaps.append(_gap("gap_no_search_evidence", "target", "important", "尚未获得任何检索候选或来源事实", "search_direction"))

    # Stable order: dimension order first, then specialized facts.  Duplicate
    # IDs are collapsed without depending on set iteration order.
    result: list[Gap] = []
    seen: set[str] = set()
    for item in gaps:
        if item.gap_id not in seen:
            result.append(item)
            seen.add(item.gap_id)
    if len(result) > MAX_GAPS:
        raise AdaptiveModelError(f"evaluator produced more than {MAX_GAPS} gaps")
    return tuple(result)


def _deduped_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[CandidateResourceInternal]:
    return deduplicate_candidates(candidates)


def _candidate_count_and_displayable(candidates: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    deduped = _deduped_candidates(candidates)
    normalised = [item.to_mapping() for item in deduped]
    return len(normalised), sum(1 for item in normalised if _candidate_displayable(item))


def _select_next_directions(directions: Sequence[SearchDirection], coverage: Coverage) -> tuple[SearchDirection, ...]:
    selected: list[SearchDirection] = []
    for direction in directions:
        if not direction.required_dimensions or any(coverage.state_for(item) in {CoverageState.UNSEARCHED, CoverageState.WEAK} for item in direction.required_dimensions):
            selected.append(direction)
    return tuple(selected)


def _decision_for(
    task: _TaskContext,
    round_number: int,
    max_rounds: int,
    coverage: Coverage,
    gaps: Sequence[Gap],
    displayable_count: int,
    no_gain_streak: int,
    source_statuses: set[str],
) -> tuple[StopDecision, str, str]:
    gap_ids = {item.gap_id for item in gaps}
    if not task.goal or "gap_curriculum_scope" in gap_ids or "gap_conflicting_constraints" in gap_ids:
        if "gap_curriculum_scope" in gap_ids:
            return StopDecision.CLARIFY, "missing_curriculum_scope", "教材同步范围会改变检索路线，需要先澄清范围"
        if "gap_conflicting_constraints" in gap_ids:
            return StopDecision.CLARIFY, "conflicting_constraints", "目标或硬约束冲突，需要先澄清取舍"
        return StopDecision.CLARIFY, "missing_goal", "核心学习目标尚未足够明确"
    critical = [item for item in gaps if item.severity is GapSeverity.CRITICAL]
    important = [item for item in gaps if item.severity is GapSeverity.IMPORTANT]
    if "gap_authentication" in gap_ids and displayable_count < task.selection_min:
        return StopDecision.CLARIFY, "authentication_required", "继续获取需要用户提供或确认合法认证方式"
    terminal_access = bool({"policy_blocked", "unsupported"} & source_statuses) and displayable_count < task.selection_min
    if terminal_access and not any(item.gap_id == "gap_source_failure" for item in gaps):
        return StopDecision.STOP_WITH_GAP, "terminal_source_boundary", "可用路线受到策略或能力边界限制"
    required_weak = [
        item for item in gaps
        if item.dimension.value in task.required_dimensions and item.severity in {GapSeverity.CRITICAL, GapSeverity.IMPORTANT}
    ]
    ready = displayable_count >= task.selection_min and not critical and not required_weak
    if ready:
        return StopDecision.PRESENT, "coverage_sufficient", "必要维度已有可展示候选和足够证据"
    if no_gain_streak >= 2:
        if displayable_count >= task.selection_min and not critical:
            return StopDecision.PRESENT, "no_gain_with_presentable_candidates", "连续两轮没有新增唯一候选或缺口关闭，保留现有候选"
        return StopDecision.STOP_WITH_GAP, "no_gain_streak_exhausted", "连续两轮没有新增唯一候选或缺口关闭"
    if round_number >= max_rounds:
        if displayable_count >= task.selection_min and not critical and not required_weak:
            return StopDecision.PRESENT, "round_budget_exhausted_with_coverage", "已达到轮次预算且现有覆盖足以展示"
        return StopDecision.STOP_WITH_GAP, "round_budget_exhausted", "已达到轮次预算，仍有必要缺口"
    if not displayable_count and not gaps:
        return StopDecision.REPLAN, "search_more_evidence", "尚未获得可展示候选"
    if important or critical or coverage.selection in {CoverageState.UNSEARCHED, CoverageState.WEAK}:
        return StopDecision.REPLAN, "actionable_gap", "仍有可通过下一方向检索或 inspection 缩小的缺口"
    return StopDecision.PRESENT, "coverage_sufficient", "当前候选可以进入展示"


def _normalise_rounds(rounds: Sequence[SearchRound | Mapping[str, Any]] | SearchRound | Mapping[str, Any] | None) -> tuple[SearchRound, ...]:
    if rounds is None:
        return ()
    if isinstance(rounds, SearchRound):
        values: Sequence[Any] = (rounds,)
    elif isinstance(rounds, Mapping):
        if "rounds" in rounds:
            values = rounds["rounds"]
        else:
            values = (rounds,)
    else:
        values = rounds
    if not isinstance(values, (list, tuple)):
        raise AdaptiveModelError("rounds must be an array")
    if len(values) > COMPREHENSIVE_MAX_ROUNDS:
        raise AdaptiveModelError(f"rounds has more than {COMPREHENSIVE_MAX_ROUNDS} entries")
    result = tuple(item if isinstance(item, SearchRound) else SearchRound.from_mapping(item) for item in values)
    for index, item in enumerate(result, start=1):
        if item.round_number != index:
            raise AdaptiveModelError("round_number values must be consecutive starting at 1")
    return result


def _zero_gain() -> InformationGain:
    return InformationGain()


def evaluate_retrieval(
    task: Mapping[str, Any] | Sequence[SearchRound | Mapping[str, Any]] | None = None,
    rounds: Sequence[SearchRound | Mapping[str, Any]] | SearchRound | Mapping[str, Any] | None = None,
    *,
    mode: SearchMode | str | None = None,
) -> RetrievalEvaluation:
    """Evaluate a bounded retrieval run deterministically.

    ``task`` may be omitted when the first positional value is a round list.
    The return value is immutable at the dataclass boundary and every mapping
    returned by :meth:`RetrievalEvaluation.to_mapping` is a fresh JSON-safe
    copy.
    """

    if rounds is None and isinstance(task, (list, tuple, SearchRound)):
        rounds = task
        task = None
    context = _normalise_task(task if isinstance(task, Mapping) or task is None else None, mode)
    parsed_rounds = _normalise_rounds(rounds)
    effective_mode = context.mode
    if mode is None and task is None and parsed_rounds:
        effective_mode = parsed_rounds[0].mode
    max_rounds = COMPREHENSIVE_MAX_ROUNDS if effective_mode is SearchMode.COMPREHENSIVE else NORMAL_MAX_ROUNDS
    if len(parsed_rounds) > max_rounds:
        raise AdaptiveModelError(f"{effective_mode.value} mode allows at most {max_rounds} rounds")

    previous_candidates: list[dict[str, Any]] = []
    previous_sources: list[dict[str, Any]] = []
    previous_inspections: list[dict[str, Any]] = []
    previous_gaps: tuple[Gap, ...] = ()
    previous_displayable = 0
    previous_source_families: set[str] = set()
    no_gain_streak = 0
    round_evaluations: list[RoundEvaluation] = []
    final_coverage = Coverage()
    final_gaps: tuple[Gap, ...] = ()
    final_gain = _zero_gain()
    final_decision = StopDecision.REPLAN
    final_reason = "no_rounds"
    final_rationale = "尚未评估任何检索轮次"
    final_unique = 0
    final_displayable = 0
    all_directions: list[SearchDirection] = []

    for search_round in parsed_rounds:
        all_directions.extend(search_round.directions)
        current_candidates = previous_candidates + list(search_round.candidates)
        current_sources = previous_sources + list(search_round.source_results)
        current_inspections = previous_inspections + list(search_round.inspections)
        deduped_count, displayable_count = _candidate_count_and_displayable(current_candidates)
        previous_unique, _previous_displayable_check = _candidate_count_and_displayable(previous_candidates)
        new_unique = max(0, deduped_count - previous_unique)
        new_displayable = max(0, displayable_count - previous_displayable)
        _successful, source_families, source_failures, source_statuses = _source_summary(current_sources, current_candidates)
        new_families = len(source_families - previous_source_families)
        raw_count = len(search_round.candidates)
        duplicates = max(0, raw_count - new_unique)
        coverage = _coverage_for(context, current_candidates, current_sources, current_inspections, all_directions)
        gaps = _gaps_for(context, coverage, current_candidates, current_sources, current_inspections)
        previous_gap_ids = {item.gap_id for item in previous_gaps}
        current_gap_ids = {item.gap_id for item in gaps}
        closed = (previous_gap_ids - current_gap_ids) | (set(search_round.gap_closures) & previous_gap_ids)
        if new_unique == 0 and not closed:
            no_gain_streak += 1
        else:
            no_gain_streak = 0
        gain = InformationGain(
            new_candidates=raw_count,
            new_unique_resources=new_unique,
            new_displayable_candidates=new_displayable,
            new_source_families=new_families,
            duplicates=duplicates,
            closed_gaps=tuple(sorted(closed)),
            source_failures=source_failures,
        )
        decision, reason, rationale = _decision_for(
            context,
            search_round.round_number,
            max_rounds,
            coverage,
            gaps,
            displayable_count,
            no_gain_streak,
            source_statuses,
        )
        round_evaluations.append(RoundEvaluation(search_round.round_number, coverage, gaps, gain, decision, reason, no_gain_streak))
        previous_candidates = current_candidates
        previous_sources = current_sources
        previous_inspections = current_inspections
        previous_gaps = gaps
        previous_displayable = displayable_count
        previous_source_families = source_families
        final_coverage, final_gaps, final_gain = coverage, gaps, gain
        final_decision, final_reason, final_rationale = decision, reason, rationale
        final_unique, final_displayable = deduped_count, displayable_count

    if not parsed_rounds:
        coverage = _coverage_for(context, (), (), (), ())
        gaps = _gaps_for(context, coverage, (), (), ())
        decision, reason, rationale = _decision_for(context, 0, max_rounds, coverage, gaps, 0, 0, set())
        final_coverage, final_gaps = coverage, gaps
        final_decision, final_reason, final_rationale = decision, reason, rationale

    unique_directions: list[SearchDirection] = []
    seen_direction_ids: set[str] = set()
    for direction in _select_next_directions(all_directions, final_coverage):
        if direction.direction_id not in seen_direction_ids:
            unique_directions.append(direction)
            seen_direction_ids.add(direction.direction_id)
    return RetrievalEvaluation(
        mode=effective_mode,
        rounds_evaluated=len(parsed_rounds),
        coverage=final_coverage,
        gaps=final_gaps,
        information_gain=final_gain,
        stop_decision=final_decision,
        reason_code=final_reason,
        rationale=final_rationale,
        no_gain_streak=no_gain_streak,
        max_rounds=max_rounds,
        budget_remaining=max(0, max_rounds - len(parsed_rounds)),
        unique_candidates=final_unique,
        displayable_candidates=final_displayable,
        next_directions=tuple(unique_directions),
        round_evaluations=tuple(round_evaluations),
    )


def evaluate_search_round(
    search_round: SearchRound | Mapping[str, Any],
    *,
    task: Mapping[str, Any] | None = None,
    prior_rounds: Sequence[SearchRound | Mapping[str, Any]] = (),
    mode: SearchMode | str | None = None,
) -> RetrievalEvaluation:
    """Convenience evaluator for a current round plus prior rounds."""

    return evaluate_retrieval(task, [*prior_rounds, search_round], mode=mode)


evaluate_round = evaluate_search_round
evaluate = evaluate_retrieval


class AdaptiveRetrievalEvaluator:
    """Small stateful façade for callers that receive rounds incrementally."""

    def __init__(self, task: Mapping[str, Any] | None = None, *, mode: SearchMode | str | None = None) -> None:
        self._task = _json_copy(task or {}, path="task")
        if not isinstance(self._task, dict):
            raise AdaptiveModelError("task must be an object")
        self._mode = mode
        self._rounds: list[SearchRound] = []

    @property
    def rounds(self) -> tuple[SearchRound, ...]:
        return tuple(self._rounds)

    def add_round(self, search_round: SearchRound | Mapping[str, Any]) -> RetrievalEvaluation:
        parsed = search_round if isinstance(search_round, SearchRound) else SearchRound.from_mapping(search_round)
        expected = len(self._rounds) + 1
        if parsed.round_number != expected:
            raise AdaptiveModelError(f"next round_number must be {expected}")
        self._rounds.append(parsed)
        return self.evaluate()

    def evaluate(self) -> RetrievalEvaluation:
        return evaluate_retrieval(self._task, tuple(self._rounds), mode=self._mode)


__all__ = [
    "AdaptiveModelError",
    "AdaptiveRetrievalEvaluator",
    "COMPREHENSIVE_MAX_ROUNDS",
    "Coverage",
    "CoverageDimension",
    "CoverageState",
    "DIMENSIONS",
    "Gap",
    "GapSeverity",
    "InformationGain",
    "MODEL_VERSION",
    "NORMAL_MAX_ROUNDS",
    "RetrievalEvaluation",
    "RoundEvaluation",
    "SearchDirection",
    "SearchMode",
    "SearchRound",
    "StopDecision",
    "evaluate",
    "evaluate_retrieval",
    "evaluate_round",
    "evaluate_search_round",
]
