"""Bounded Anna's Archive inspection backed by public Libgen metadata.

The search adapter obtains Anna-compatible MD5/book metadata from Libgen, and
the downloader fetches the file from Libgen mirrors by MD5.  The synthetic
``annas-archive.gl/md5/<md5>`` source URL is a user-facing identity page only:
it is neither the data source nor the acquisition channel, so this inspector
performs no request against it.  A valid MD5 must already be present in the
server's resource metadata before any platform enrichment is allowed.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from ..inspection import InspectionResult, build_representation_authority
from .inspect_nlc import (
    PlatformBoundedInspector,
    _first_text,
    _first_value,
    _safe_integer,
    _safe_text,
    _safe_year,
)


INSPECTOR_ID = "annas_archive"
MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_EXTENSION_RE = re.compile(r"^[a-z0-9][a-z0-9.+_-]{0,15}$", re.IGNORECASE)
RIGHTS_HINT = (
    "仅展示公开 Libgen 书目元数据；不代表 Anna's Archive 官方 API 或下载授权，"
    "获取前请确认版权与来源许可。"
)
_MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "txt": "text/plain",
    "html": "text/html",
    "htm": "text/html",
    "rtf": "application/rtf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _valid_md5(value: Any) -> str | None:
    text = _safe_text(value, maximum=32)
    if text is None or MD5_RE.fullmatch(text) is None:
        return None
    return text.casefold()


def _size_bytes(value: Any) -> int | None:
    direct = _safe_integer(value)
    if direct is not None:
        return direct
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*", value, re.IGNORECASE)
    if match is None:
        return None
    amount = float(match.group(1))
    multiplier = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }[match.group(2).upper()]
    result = amount * multiplier
    if not result.is_integer() or result < 0 or result > 10**15:
        return None
    return int(result)


class AnnasArchiveInspector(PlatformBoundedInspector):
    """Inspect a Libgen-backed resource from search metadata using a validated MD5."""

    platform_id = "annas-archive"
    inspector_id = INSPECTOR_ID

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if not isinstance(resource, Mapping):
            return super().inspect(resource)
        md5 = None
        # The URL is intentionally not consulted.  The search result must
        # carry the identity in a server-controlled field or metadata.
        for mapping in self._md5_mappings(resource):
            candidate = _valid_md5(mapping.get("md5"))
            if candidate is not None:
                md5 = candidate
                break
        if md5 is None:
            return self._validation_result(
                resource,
                "PLATFORM_VALIDATION_BLOCKED",
                "Libgen-backed 检查需要资源元数据中的合法 32 位 MD5",
            )
        # The MD5 is the whole platform identity: search and download both go
        # through Libgen mirrors, and the downloader resolves mirrors and
        # validates the real file format post-download.  The synthetic
        # Anna's Archive detail page is not the inspection or acquisition
        # channel, so no request is made against it — its risk control or
        # unreachability must not veto the pipeline.
        base = self._result(
            resource, resolution_status="resolved", availability="available"
        )
        return self._enrich(resource, base)

    @staticmethod
    def _md5_mappings(resource: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        # Keep this explicit rather than recursively traversing arbitrary
        # metadata: no headers, cookies, tokens, or hidden locator objects are
        # eligible as identity input.
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

    def _enrich(self, resource: Mapping[str, Any], result: InspectionResult) -> InspectionResult:
        if not self._enrichment_allowed(result):
            return result

        md5 = None
        for mapping in self._md5_mappings(resource):
            md5 = _valid_md5(mapping.get("md5"))
            if md5 is not None:
                break
        if md5 is None:  # Defensive: inspect() performs the same gate.
            return self._validation_result(
                resource,
                "PLATFORM_VALIDATION_BLOCKED",
                "Libgen-backed 检查需要资源元数据中的合法 32 位 MD5",
            )

        metadata: dict[str, Any] = {"md5": md5}
        isbn = _first_text(resource, "isbn", "ISBN")
        if isbn:
            metadata["isbn"] = isbn
        author = _first_text(resource, "author", "creator")
        if author:
            metadata["author"] = author
        publisher = _first_text(resource, "publisher")
        if publisher:
            metadata["publisher"] = publisher
        year = _safe_year(
            _first_value(resource, "year", "publication_year", "publish_year", "published_at")
        )
        if year is not None:
            metadata["year"] = year

        raw_extension = _first_value(resource, "extension", "format", "file_extension")
        extension = _safe_text(raw_extension, maximum=16)
        if extension:
            extension = extension.lstrip(".").casefold()
        if not extension or _EXTENSION_RE.fullmatch(extension) is None:
            extension = None
        if extension:
            metadata["extension"] = extension

        size = _size_bytes(_first_value(resource, "size_bytes", "size", "file_size"))
        if size is not None:
            metadata["size_bytes"] = size
        language = _first_text(resource, "language", "lang")
        if language:
            metadata["language"] = language

        current = [dict(item) for item in result.to_mapping()["resolved_resource"]["representations"]]
        concrete_primary = [
            item
            for item in current
            if item.get("scope") == "primary_resource"
            and item.get("role") == "primary"
            and item.get("materializable") is True
            and item.get("technical_availability") == "available"
        ]
        if concrete_primary:
            # A verified concrete response outranks Libgen/Anna metadata.  Do
            # not replace or downgrade the primary representation.
            representations = current
        else:
            base = current[0] if current else {}
            # Anna's Archive resources carry a stable md5 identifier and a
            # known file format from search metadata.  The downloader
            # resolves Libgen mirrors and validates the real file format
            # post-download; the inspector does not need to prove
            # downloadability to mark the primary as materializable.
            representation: dict[str, Any] = {
                "representation_id": self._representation_id(resource, "document", "primary"),
                "kind": "document",
                "container": extension or "document",
                "scope": "primary_resource",
                "role": "primary",
                "technical_availability": "available",
                "materializable": True,
                "rights_hint": RIGHTS_HINT,
            }
            representation.update(
                build_representation_authority(
                    resource,
                    scope="primary_resource",
                    role="primary",
                    technical_availability="available",
                    source="metadata",
                    observed_at=result.to_mapping()["inspection"].get("inspected_at"),
                )
            )
            mime_type = _MIME_BY_EXTENSION.get(extension or "")
            if mime_type:
                representation["mime_type"] = mime_type
            if size is not None:
                representation["size_bytes"] = size
            if language:
                representation["language"] = language
            elif isinstance(base, Mapping) and base.get("language"):
                # Only copy the already-validated language scalar.
                representation["language"] = base["language"]

            landing = next(
                (
                    item
                    for item in current
                    if item.get("kind") == "webpage"
                    and item.get("scope") == "landing_page"
                ),
                None,
            )
            if landing is None:
                landing = {
                    "representation_id": self._representation_id(resource, "webpage", "landing"),
                    "kind": "webpage",
                    "container": "html",
                    "mime_type": "text/html",
                    "scope": "landing_page",
                    "role": "landing",
                    "technical_availability": "available",
                    "materializable": False,
                }
            representations = [representation, landing]

        return self._rewrite_result(
            resource,
            result,
            resource_type="book",
            metadata=metadata,
            representations=representations,
            creator=author,
            availability="available",
            method="platform_metadata",
        )


AnnaArchiveInspector = AnnasArchiveInspector


__all__ = [
    "AnnaArchiveInspector",
    "AnnasArchiveInspector",
    "INSPECTOR_ID",
    "MD5_RE",
    "RIGHTS_HINT",
]
