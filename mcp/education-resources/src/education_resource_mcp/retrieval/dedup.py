"""Stable, conservative candidate de-duplication."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from .identity import (
    URLIdentityProfile,
    identities_match,
    resolve_identity,
)
from .models import CandidateResourceInternal, ResourceIdentity, Representation


CandidateLike = CandidateResourceInternal | Mapping[str, Any]


def _missing(value: Any, *, field: str = "") -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or (field == "resource_type" and value == "other")
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return len(value) == 0
    return False


def _fill_mapping(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Deep-fill missing mapping fields without overwriting known facts."""

    result = dict(existing)
    for key, value in incoming.items():
        if key not in result or _missing(result[key]):
            result[key] = value
        elif isinstance(result[key], Mapping) and isinstance(value, Mapping):
            result[key] = _fill_mapping(result[key], value)
    return result


def _merge_representations(
    existing: tuple[Representation, ...],
    incoming: tuple[Representation, ...],
) -> tuple[Representation, ...]:
    if not existing:
        return tuple(incoming)
    result = list(existing)
    seen = {
        item.representation_id or (item.kind, item.container, item.role)
        for item in result
    }
    for item in incoming:
        key = item.representation_id or (item.kind, item.container, item.role)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return tuple(result)


def merge_candidates(
    first: CandidateResourceInternal,
    later: CandidateResourceInternal,
) -> CandidateResourceInternal:
    """Merge a duplicate into the first candidate.

    The first candidate owns order, public ``resource_id``, title, URL, and
    any other already-known value.  The later candidate can only fill absent
    scalar fields or absent nested mapping fields.
    """

    changes: dict[str, Any] = {}
    scalar_fields = (
        "resource_id",
        "platform",
        "resource_type",
        "title",
        "canonical_url",
        "summary",
        "author",
        "creator",
        "published_at",
        "availability",
        "native_identity",
        "native_type",
        "native_id",
        "isbn",
        "doi",
        "edition",
        "version",
    )
    for field_name in scalar_fields:
        old_value = getattr(first, field_name)
        new_value = getattr(later, field_name)
        if _missing(old_value, field=field_name) and not _missing(new_value, field=field_name):
            changes[field_name] = new_value

    changes["signals"] = _fill_mapping(first.signals, later.signals)
    changes["metadata"] = _fill_mapping(first.metadata, later.metadata)
    changes["representations"] = _merge_representations(
        first.representations,
        later.representations,
    )
    # resolution_status is a state owned by the pipeline, not candidate
    # metadata.  Preserve the first status unless it is absent.
    if _missing(first.resolution_status):
        changes["resolution_status"] = later.resolution_status
    return replace(first, **changes)


merge_candidate = merge_candidates


def candidate_identity(
    candidate: CandidateLike,
    profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
) -> ResourceIdentity:
    """Return the internal identity for a candidate or legacy mapping."""

    internal = (
        candidate
        if isinstance(candidate, CandidateResourceInternal)
        else CandidateResourceInternal.from_mapping(candidate)
    )
    return resolve_identity(internal, profile)


def candidate_identity_key(
    candidate: CandidateLike,
    profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
) -> tuple[str, ...] | None:
    return candidate_identity(candidate, profile).key


def deduplicate_candidates(
    candidates: Iterable[CandidateLike],
    *,
    limit: int | None = None,
    profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
) -> list[CandidateResourceInternal]:
    """Return stable first-seen candidates with duplicate facts filled in.

    Matching is pairwise instead of a single dictionary lookup because a
    candidate may carry multiple pieces of identity evidence, and a hard
    native/ISBN/DOI conflict must prevent an accidental merge.  The full
    input is processed before applying ``limit`` so later duplicate results
    can still enrich an item that remains in the returned prefix.
    """

    merged: list[CandidateResourceInternal] = []
    identities: list[ResourceIdentity] = []
    for raw in candidates:
        candidate = (
            raw
            if isinstance(raw, CandidateResourceInternal)
            else CandidateResourceInternal.from_mapping(raw)
        )
        identity = resolve_identity(candidate, profile)
        match_index: int | None = None
        for index, existing_identity in enumerate(identities):
            if identities_match(existing_identity, identity):
                match_index = index
                break
        if match_index is None:
            merged.append(candidate)
            identities.append(identity)
            continue
        merged[match_index] = merge_candidates(merged[match_index], candidate)
        # The merge may have filled ISBN/DOI/native evidence, so refresh the
        # evidence set before considering the next candidate.
        identities[match_index] = resolve_identity(merged[match_index], profile)

    if limit is None:
        return merged
    return merged[: max(0, int(limit))]


def deduplicate_candidate_mappings(
    candidates: Iterable[CandidateLike],
    *,
    limit: int | None = None,
    profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
) -> list[dict[str, Any]]:
    """Compatibility helper for callers still carrying adapter dictionaries."""

    return [item.to_mapping() for item in deduplicate_candidates(candidates, limit=limit, profile=profile)]


class CandidateDeduplicator:
    """Incremental form of :func:`deduplicate_candidates` for search runs."""

    def __init__(
        self,
        *,
        profile: URLIdentityProfile | Mapping[str, Any] | str | None = None,
    ) -> None:
        self.profile = profile
        self._candidates: list[CandidateResourceInternal] = []
        self._identities: list[ResourceIdentity] = []

    def add(self, candidate: CandidateLike) -> CandidateResourceInternal:
        internal = (
            candidate
            if isinstance(candidate, CandidateResourceInternal)
            else CandidateResourceInternal.from_mapping(candidate)
        )
        identity = resolve_identity(internal, self.profile)
        for index, existing_identity in enumerate(self._identities):
            if identities_match(existing_identity, identity):
                self._candidates[index] = merge_candidates(self._candidates[index], internal)
                self._identities[index] = resolve_identity(self._candidates[index], self.profile)
                return self._candidates[index]
        self._candidates.append(internal)
        self._identities.append(identity)
        return internal

    def extend(self, candidates: Iterable[CandidateLike]) -> None:
        for candidate in candidates:
            self.add(candidate)

    def results(self, limit: int | None = None) -> list[CandidateResourceInternal]:
        if limit is None:
            return list(self._candidates)
        return self._candidates[: max(0, int(limit))]


deduplicate = deduplicate_candidates


__all__ = [
    "CandidateDeduplicator",
    "CandidateLike",
    "candidate_identity",
    "candidate_identity_key",
    "deduplicate",
    "deduplicate_candidate_mappings",
    "deduplicate_candidates",
    "merge_candidate",
    "merge_candidates",
]
