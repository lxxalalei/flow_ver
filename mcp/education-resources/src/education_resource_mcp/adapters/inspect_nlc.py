"""Bounded public inspection for the National Library of China catalog.

The platform inspectors in this small module share a deliberately narrow
base with the Anna's Archive/Libgen and Ximalaya inspectors.  The base is kept
here so the three adapters remain independently discoverable while retaining
one result-rebuild and host-policy implementation.  It never accepts or
emits credentials, headers, locators, paths, or response bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from ..inspection import (
    InspectionResult,
    build_representation_authority,
    source_fingerprint,
)
from .inspect_generic import GenericWebInspector


PLATFORM_INSPECTION_METHOD = "platform_bounded_get"
_PUBLIC_SCALAR_MAX = 1024
_YEAR_RE = re.compile(r"^(?:[12]\d{3})(?:[-/].*)?$")
_NUMERIC_ID_RE = re.compile(r"^\d{1,32}$")


def _safe_text(value: Any, *, maximum: int = _PUBLIC_SCALAR_MAX) -> str | None:
    """Return a short public scalar, or ignore a non-public value."""

    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not text or len(text) > maximum:
        return None
    if any(ord(char) < 32 and char not in "\t\n\r" for char in text):
        return None
    lowered = text.casefold()
    if re.search(r"\b(?:https?|ftp|file|data|javascript):", lowered):
        return None
    if re.match(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)", text):
        return None
    if lowered.startswith(("bearer ", "basic ")):
        return None
    return text


def _safe_integer(value: Any, *, maximum: int = 10**15) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= maximum else None
    if isinstance(value, float):
        if value.is_integer() and 0 <= value <= maximum:
            return int(value)
        return None
    if isinstance(value, str):
        candidate = value.strip().replace(",", "")
        if re.fullmatch(r"\d+", candidate) is None:
            return None
        try:
            parsed = int(candidate)
        except ValueError:
            return None
        return parsed if parsed <= maximum else None
    return None


def _safe_year(value: Any) -> str | int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 1000 <= value <= 9999 else None
    text = _safe_text(value, maximum=32)
    if text is None:
        return None
    match = re.match(r"^([12]\d{3})", text)
    if match is None:
        return None
    return match.group(1)


def _safe_numeric_id(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    text = _safe_text(value, maximum=32)
    if text is None or _NUMERIC_ID_RE.fullmatch(text) is None:
        return None
    return text


def _source_mappings(resource: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Expose only public metadata locations used by search adapters."""

    values: list[Mapping[str, Any]] = [resource]
    metadata = resource.get("metadata")
    if isinstance(metadata, Mapping):
        values.append(metadata)
        signals = metadata.get("platform_signals")
        if isinstance(signals, Mapping):
            values.append(signals)
    signals = resource.get("platform_signals")
    if isinstance(signals, Mapping):
        values.append(signals)
    return tuple(values)


def _first_value(resource: Mapping[str, Any], *keys: str) -> Any:
    for mapping in _source_mappings(resource):
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return value
    return None


def _first_text(resource: Mapping[str, Any], *keys: str) -> str | None:
    return _safe_text(_first_value(resource, *keys))


class PlatformBoundedInspector(GenericWebInspector):
    """Generic bounded GET plus an exact platform host/identity gate."""

    platform_id = "generic"
    inspector_id = "generic"
    allowed_host_suffixes: tuple[str, ...] = ()
    allow_any_public_host = False

    def _request(self, request: Any) -> Any:
        """Apply the platform host rule to every request and final URL.

        GenericWebInspector already validates public DNS and every redirect.
        This additional check prevents a public but unrelated host from being
        treated as an NLC/Ximalaya detail page after a redirect.  The flag is
        converted to a structured policy result by ``inspect`` below because
        GenericWebInspector intentionally catches transport exceptions at its
        own boundary.
        """

        request_url = getattr(request, "full_url", None) or getattr(request, "fullurl", None)
        if not isinstance(request_url, str) or not self._source_host_allowed(request_url):
            self._platform_host_blocked = True
            raise ValueError("platform host blocked")
        response = super()._request(request)
        getter = getattr(response, "geturl", None)
        final_url = None
        if callable(getter):
            try:
                candidate = getter()
            except Exception:
                candidate = None
            if isinstance(candidate, str) and candidate:
                final_url = candidate
        if final_url is not None and not self._source_host_allowed(final_url):
            self._platform_host_blocked = True
            self._close(response)
            raise ValueError("platform redirect host blocked")
        return response

    def _source_host_allowed(self, source_url: str) -> bool:
        try:
            parsed = urlsplit(source_url)
            hostname = parsed.hostname
            scheme = parsed.scheme.casefold()
            # Accessing username/password also makes URL credential handling
            # explicit even though the shared network policy checks it again.
            has_credentials = parsed.username is not None or parsed.password is not None
        except ValueError:
            return False
        if scheme not in {"http", "https"} or not hostname or has_credentials:
            return False
        host = hostname.rstrip(".").casefold()
        if self.allow_any_public_host:
            return True
        return any(host == suffix or host.endswith("." + suffix) for suffix in self.allowed_host_suffixes)

    def _validation_result(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        *,
        availability: str = "policy_blocked",
    ) -> InspectionResult:
        return self._result(
            resource,
            resolution_status="unresolved",
            availability=availability,
            failures=[self._failure(resource, code, message, False)],
        )

    def _result(
        self,
        resource: Mapping[str, Any],
        *,
        resolution_status: str,
        availability: str,
        representation: dict[str, Any] | None = None,
        title: str | None = None,
        summary: str | None = None,
        creator: str | None = None,
        language: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        failures: Sequence[Mapping[str, Any]] = (),
        warnings: Sequence[str] = (),
    ) -> InspectionResult:
        result = super()._result(
            resource,
            resolution_status=resolution_status,
            availability=availability,
            representation=representation,
            title=title,
            summary=summary,
            creator=creator,
            language=language,
            metadata=metadata,
            failures=failures,
            warnings=warnings,
        )
        mapping = result.to_mapping()
        mapping["inspection"]["method"] = PLATFORM_INSPECTION_METHOD
        # Re-enter the strict public boundary even for validation failures.
        return InspectionResult.from_mapping(mapping)

    def _representation_id(self, resource: Mapping[str, Any], kind: str, role: str) -> str:
        try:
            fingerprint = source_fingerprint(resource)
        except Exception:
            fingerprint = hashlib.sha256(self.platform_id.encode("utf-8")).hexdigest()
        seed = f"{self.inspector_id}:{fingerprint}:{kind}:{role}"
        return "repr_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]

    def _copy_representation(
        self,
        resource: Mapping[str, Any],
        representation: Mapping[str, Any],
        *,
        kind: str | None = None,
        role: str,
        scope: str | None = None,
        source: str = "inspection",
    ) -> dict[str, Any]:
        """Copy public representation facts without upgrading capability scope."""

        allowed = (
            "container",
            "mime_type",
            "language",
            "size_bytes",
            "materializable",
            "rights_hint",
            "technical_availability",
        )
        copied: dict[str, Any] = {
            "representation_id": self._representation_id(
                resource, kind or str(representation.get("kind") or "other"), role
            ),
            "kind": kind or str(representation.get("kind") or "other"),
            "role": role,
        }
        for key in allowed:
            if key in representation and representation[key] is not None:
                copied[key] = representation[key]

        old_role = representation.get("role")
        old_scope = representation.get("scope")
        if scope is None:
            if role == old_role and isinstance(old_scope, str):
                scope = old_scope
            else:
                scope = {
                    "primary": "primary_resource",
                    "landing": "landing_page",
                    "metadata": "metadata",
                }.get(role, "representation")
        copied["scope"] = scope
        if role == old_role and isinstance(representation.get("evidence"), Mapping):
            copied["evidence"] = dict(representation["evidence"])
        else:
            authority = build_representation_authority(
                resource,
                scope=scope,
                role=role,
                technical_availability=str(
                    copied.get("technical_availability") or "unknown"
                ),
                source=source,
            )
            copied.update(authority)
        copied.setdefault(
            "technical_availability",
            "available" if copied.get("materializable") else "unknown",
        )
        return copied

    def _rewrite_result(
        self,
        resource: Mapping[str, Any],
        result: InspectionResult,
        *,
        resource_type: str,
        metadata: Mapping[str, Any],
        representations: Sequence[Mapping[str, Any]],
        creator: str | None = None,
        availability: str | None = None,
    ) -> InspectionResult:
        mapping = result.to_mapping()
        resolved = mapping["resolved_resource"]
        resolved["resource_type"] = resource_type
        resolved["metadata"] = dict(metadata)
        observed_at = mapping.get("inspection", {}).get("inspected_at")
        if availability is not None:
            resolved["availability"] = {"status": availability}
        availability_status = resolved.get("availability", {}).get("status", "unknown")
        normalised_representations: list[dict[str, Any]] = []
        for raw in representations:
            item = dict(raw)
            role = str(item.get("role") or "attachment")
            scope = str(
                item.get("scope")
                or {
                    "primary": "primary_resource",
                    "landing": "landing_page",
                    "metadata": "metadata",
                }.get(role, "representation")
            )
            item["scope"] = scope
            item.setdefault(
                "technical_availability",
                "available" if availability_status == "available" else "unknown",
            )
            evidence = item.get("evidence")
            if not isinstance(evidence, Mapping):
                item.update(
                    build_representation_authority(
                        resource,
                        scope=scope,
                        role=role,
                        technical_availability=str(item["technical_availability"]),
                        source="metadata",
                        observed_at=observed_at if isinstance(observed_at, str) else None,
                    )
                )
            normalised_representations.append(item)
        resolved["representations"] = normalised_representations
        if creator:
            resolved["creator"] = creator
        mapping["inspection"]["method"] = PLATFORM_INSPECTION_METHOD
        # Every platform enrichment, including IDs and allowlist metadata,
        # must pass through InspectionResult validation once more.
        return InspectionResult.from_mapping(mapping)

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        self._platform_host_blocked = False
        if isinstance(resource, Mapping):
            source_url = resource.get("source_url")
            if isinstance(source_url, str) and source_url and not self._source_host_allowed(source_url):
                return self._validation_result(
                    resource,
                    "PLATFORM_POLICY_BLOCKED",
                    "资源来源不在该平台的公开检查范围内",
                )
        result = super().inspect(resource)
        if self._platform_host_blocked:
            return self._validation_result(
                resource if isinstance(resource, Mapping) else {},
                "PLATFORM_POLICY_BLOCKED",
                "重定向地址不在该平台的公开检查范围内",
            )
        return self._enrich(resource, result)

    def _enrich(self, resource: Mapping[str, Any], result: InspectionResult) -> InspectionResult:
        return result

    @staticmethod
    def _enrichment_allowed(result: InspectionResult) -> bool:
        if result.resolution_status not in {"resolved", "partial"}:
            return False
        try:
            availability = result.to_mapping()["resolved_resource"]["availability"]["status"]
        except (KeyError, TypeError):
            return False
        return availability in {"available", "unknown"}


class NlcInspector(PlatformBoundedInspector):
    """Inspect public NLC catalog detail pages without using a session."""

    platform_id = "nlc"
    inspector_id = "nlc"
    allowed_host_suffixes = ("nlc.cn",)

    def _enrich(self, resource: Mapping[str, Any], result: InspectionResult) -> InspectionResult:
        if not self._enrichment_allowed(result):
            return result

        metadata: dict[str, Any] = {}
        isbn = _first_text(resource, "isbn", "ISBN")
        if isbn:
            metadata["isbn"] = isbn
        author = _first_text(resource, "author", "creator", "著者")
        if author:
            metadata["author"] = author
        publisher = _first_text(resource, "publisher", "出版社")
        if publisher:
            metadata["publisher"] = publisher
        publication_year = _safe_year(
            _first_value(resource, "publication_year", "publish_year", "pub_year", "year")
        )
        if publication_year is not None:
            metadata["publication_year"] = publication_year
        edition = _first_text(resource, "edition", "edition_statement", "版本")
        if edition:
            metadata["edition"] = edition
        call_number = _first_text(resource, "call_number", "callno", "索书号")
        if call_number:
            metadata["call_number"] = call_number

        current = result.to_mapping()["resolved_resource"]["representations"]
        representations: list[dict[str, Any]] = []
        for representation in current:
            kind = representation.get("kind")
            if kind not in {"webpage", "document"}:
                continue
            is_concrete_primary = (
                representation.get("scope") == "primary_resource"
                and representation.get("role") == "primary"
                and representation.get("materializable") is True
                and representation.get("technical_availability") == "available"
            )
            if kind == "webpage":
                role, scope = "landing", "landing_page"
            elif is_concrete_primary:
                # A genuinely verified file outranks platform metadata; do
                # not downgrade it merely because this is an NLC candidate.
                role, scope = "primary", "primary_resource"
            else:
                role, scope = "metadata", "metadata"
            representations.append(
                self._copy_representation(
                    resource,
                    representation,
                    kind=kind,
                    role=role,
                    scope=scope,
                )
            )
        if not representations:
            representations.append(
                {
                    "representation_id": self._representation_id(resource, "webpage", "landing"),
                    "kind": "webpage",
                    "container": "html",
                    "mime_type": "text/html",
                    "scope": "landing_page",
                    "role": "landing",
                    "technical_availability": "available",
                    "materializable": False,
                }
            )

        return self._rewrite_result(
            resource,
            result,
            resource_type="book",
            metadata=metadata,
            representations=representations,
            creator=author,
        )


# Both spellings are useful to callers while the canonical implementation
# keeps the platform ID's normal acronym casing out of the class name.
NLCInspector = NlcInspector


__all__ = [
    "NLCInspector",
    "NlcInspector",
    "PLATFORM_INSPECTION_METHOD",
    "PlatformBoundedInspector",
    "_first_text",
    "_first_value",
    "_safe_integer",
    "_safe_numeric_id",
    "_safe_text",
    "_safe_year",
]
