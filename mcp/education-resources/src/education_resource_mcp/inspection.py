"""Bounded, non-network inspection primitives.

The inspection layer deliberately owns only the shape and safety boundary of
an inspection result.  Network access, platform-specific parsing, caching,
and persistence belong to the callers/adapters.  Keeping this module small
also makes it safe to use from tests and from adapters that are supplied by a
future platform integration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePath
import re
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
import unicodedata

from .errors import DomainError


INSPECTION_PROFILE_VERSION = "inspect-v1"
INSPECTOR_VERSION = "1.0.0"

MAX_REPRESENTATIONS = 32
MAX_WARNINGS = 32
MAX_FAILURES = 32
MAX_METADATA_PROPERTIES = 32

RESOLUTION_STATUSES = frozenset({"resolved", "partial", "unresolved"})
AVAILABILITY_STATUSES = frozenset(
    {"available", "auth_required", "unavailable", "unknown", "policy_blocked"}
)
REPRESENTATION_KINDS = frozenset(
    {"webpage", "document", "video", "audio", "image", "subtitle", "other"}
)
CACHE_STATUSES = frozenset({"hit", "miss", "refresh"})
RESOURCE_TYPES = frozenset(
    {"article", "book", "document", "video", "audio", "course", "dataset", "other"}
)

_PLATFORM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_RESOURCE_ID_RE = re.compile(r"^res_[A-Za-z0-9_-]{16,64}$")
_REPRESENTATION_ID_RE = re.compile(r"^repr_[A-Za-z0-9_-]{16,64}$")
_MIME_RE = re.compile(r"^[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+$")
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INSPECTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_METADATA_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# This is intentionally broader than the public schema's additional-property
# checks.  Adapters may carry nested internal objects before they are handed
# to this module, so the boundary must reject a locator or secret at every
# level rather than only at the top-level representation object.
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "source_url",
        "url",
        "uri",
        "href",
        "path",
        "file_path",
        "cookie",
        "token",
        "access_token",
        "authorization",
        "credential",
        "password",
        "secret",
        "locator",
        "canonical_url",
        "download_url",
        "local_path",
        "remote_url",
        "filename",
        "file",
        "headers",
        "api_key",
        "api_token",
        "refresh_token",
        "private_key",
    }
)
_SENSITIVE_COMPACT_NAMES = frozenset(
    re.sub(r"[^a-z0-9]", "", name) for name in _SENSITIVE_KEY_NAMES
)
_URL_VALUE_RE = re.compile(
    r"(?i)(?:\b(?:https?|ftp|file|data|javascript):\s*//|\b(?:https?|ftp|file):)"
)
_ABSOLUTE_PATH_RE = re.compile(
    r"^(?:/(?:[^\s\x00/]+/)*[^\s\x00/]+|~[/\\]|[A-Za-z]:[/\\]|\\\\)"
)
_AUTH_VALUE_RE = re.compile(r"(?i)^(?:bearer|basic)\s+[^\s]+")

# Metadata is deliberately an allow-list rather than a hash of the entire
# metadata blob.  Crawl timestamps, UI labels, and retry diagnostics are not
# resource identity.  These names cover the stable native/edition evidence
# used by the retrieval identity layer and common platform aliases.
_STABLE_IDENTITY_KEYS = frozenset(
    {
        "id",
        "isbn",
        "doi",
        "native_id",
        "native_type",
        "native_identity",
        "identity",
        "edition",
        "edition_id",
        "version",
        "version_id",
        "content_id",
        "course_id",
        "video_id",
        "episode_id",
        "album_id",
        "question_id",
        "answer_id",
        "book_id",
        "chapter_id",
        "md5",
        "creator_id",
        "author_id",
        "external_id",
        "source_id",
        "platform_id",
        "title",
        "canonical_url",
        "source_url",
    }
)
_STABLE_IDENTITY_COMPACT_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", key) for key in _STABLE_IDENTITY_KEYS
)

_RESOLVED_RESOURCE_FIELDS = frozenset(
    {
        "title",
        "resource_type",
        "summary",
        "creator",
        "language",
        "availability",
        "representations",
        "metadata",
    }
)
_AVAILABILITY_FIELDS = frozenset({"status"})
_REPRESENTATION_FIELDS = frozenset(
    {
        "representation_id",
        "kind",
        "container",
        "mime_type",
        "role",
        "language",
        "estimated_size_bytes",
        "materializable",
        "requires_auth",
        "rights_hint",
    }
)
_INSPECTION_FIELDS = frozenset(
    {"inspector_id", "version", "method", "cache_status", "inspected_at", "warnings"}
)
_FAILURE_FIELDS = frozenset({"platform", "resource_id", "code", "message", "retriable"})


def _invalid(message: str) -> None:
    raise DomainError("INVALID_ARGUMENT", message)


def _unsupported(message: str = "资源平台暂不支持检查") -> None:
    raise DomainError("FEATURE_NOT_SUPPORTED", message)


def _normalise_key_name(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _reject_sensitive_key(key: Any) -> str:
    if not isinstance(key, str):
        _invalid("输出对象的键必须是字符串")
    normalised = _normalise_key_name(key)
    compact = re.sub(r"[^a-z0-9]", "", normalised)
    if normalised in _SENSITIVE_KEY_NAMES or compact in _SENSITIVE_COMPACT_NAMES:
        _invalid("检查结果不得包含定位信息或秘密字段")
    return key


def _reject_sensitive_value(value: str) -> None:
    stripped = value.strip()
    if _URL_VALUE_RE.search(stripped) or _AUTH_VALUE_RE.search(stripped):
        _invalid("检查结果不得泄漏定位信息或凭据")
    if _ABSOLUTE_PATH_RE.search(stripped):
        _invalid("检查结果不得包含本地或远程文件路径")


def _json_copy(value: Any, *, reject_sensitive: bool = True) -> Any:
    """Copy JSON-compatible data while rejecting non-JSON objects.

    This helper is intentionally not a generic serializer.  Accepting an
    arbitrary object and calling ``str`` on it would make it possible for a
    Path, response object, cookie jar, or a custom secret-bearing object to
    cross the MCP boundary.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _invalid("检查结果不得包含 NaN 或 Infinity")
        return value
    if isinstance(value, str):
        if reject_sensitive:
            _reject_sensitive_value(value)
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)) or isinstance(
        value, (Path, PurePath, os.PathLike)
    ):
        _invalid("检查结果不得包含字节、路径或其他非 JSON 对象")
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _reject_sensitive_key(raw_key) if reject_sensitive else raw_key
            if not isinstance(key, str):
                _invalid("输出对象的键必须是字符串")
            copied[key] = _json_copy(raw_value, reject_sensitive=reject_sensitive)
        return copied
    if isinstance(value, (list, tuple)):
        return [_json_copy(item, reject_sensitive=reject_sensitive) for item in value]
    _invalid("检查结果不得包含任意 Python 对象")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _string(
    value: Any,
    field: str,
    *,
    minimum: int = 0,
    maximum: int,
    pattern: re.Pattern[str] | None = None,
    reject_sensitive: bool = True,
) -> str:
    if not isinstance(value, str):
        _invalid(f"{field} 必须是字符串")
    if reject_sensitive:
        _reject_sensitive_value(value)
    if not minimum <= len(value) <= maximum:
        _invalid(f"{field} 长度超出范围")
    if pattern is not None and pattern.fullmatch(value) is None:
        _invalid(f"{field} 格式无效")
    return str(value)


def _optional_string(
    value: Any,
    field: str,
    *,
    minimum: int = 0,
    maximum: int,
    pattern: re.Pattern[str] | None = None,
) -> str | None:
    if value is None:
        return None
    return _string(
        value,
        field,
        minimum=minimum,
        maximum=maximum,
        pattern=pattern,
    )


def _validate_timestamp(value: Any) -> str:
    timestamp = _string(value, "inspected_at", minimum=1, maximum=128)
    candidate = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _invalid("inspected_at 必须是 ISO 8601 时间戳")
    if parsed.tzinfo is None:
        _invalid("inspected_at 必须包含时区")
    return timestamp


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(f"{field} 必须是对象")
    return value


def _reject_extra_fields(value: Mapping[str, Any], allowed: frozenset[str], field: str) -> None:
    for key in value:
        _reject_sensitive_key(key)
        if key not in allowed:
            _invalid(f"{field} 包含未允许字段")


def _normalise_metadata(value: Any) -> dict[str, Any]:
    metadata = _mapping(value, "metadata")
    if len(metadata) > MAX_METADATA_PROPERTIES:
        _invalid("metadata 属性数量超出上限")
    result: dict[str, Any] = {}
    for raw_key, raw_value in metadata.items():
        if not isinstance(raw_key, str) or _METADATA_KEY_RE.fullmatch(raw_key) is None:
            _invalid("metadata 键名格式无效")
        _reject_sensitive_key(raw_key)
        if isinstance(raw_value, bool):
            result[raw_key] = raw_value
        elif isinstance(raw_value, int):
            result[raw_key] = raw_value
        elif isinstance(raw_value, float):
            if not math.isfinite(raw_value):
                _invalid("metadata 不得包含 NaN 或 Infinity")
            result[raw_key] = raw_value
        elif isinstance(raw_value, str):
            if len(raw_value) > 1024:
                _invalid("metadata 字符串长度超出上限")
            _reject_sensitive_value(raw_value)
            result[raw_key] = str(raw_value)
        else:
            _invalid("metadata 仅允许标量值")
    return result


def _normalise_availability(value: Any) -> dict[str, str]:
    availability = _mapping(value, "availability")
    _reject_extra_fields(availability, _AVAILABILITY_FIELDS, "availability")
    status = availability.get("status")
    if not isinstance(status, str) or status not in AVAILABILITY_STATUSES:
        _invalid("availability.status 无效")
    return {"status": str(status)}


def _normalise_representation(value: Any, index: int) -> dict[str, Any]:
    representation = _mapping(value, f"representations[{index}]")
    _reject_extra_fields(representation, _REPRESENTATION_FIELDS, "representation")
    result: dict[str, Any] = {}

    raw_id = representation.get("representation_id")
    if raw_id is not None:
        result["representation_id"] = _string(
            raw_id,
            "representation_id",
            minimum=1,
            maximum=73,
            pattern=_REPRESENTATION_ID_RE,
        )

    kind = representation.get("kind")
    if not isinstance(kind, str) or kind not in REPRESENTATION_KINDS:
        _invalid("representation.kind 无效")
    result["kind"] = str(kind)

    container = _optional_string(
        representation.get("container"),
        "representation.container",
        minimum=1,
        maximum=64,
        pattern=_CONTAINER_RE,
    )
    if container is not None:
        result["container"] = container

    mime_type = _optional_string(
        representation.get("mime_type"),
        "representation.mime_type",
        minimum=3,
        maximum=127,
        pattern=_MIME_RE,
    )
    if mime_type is not None:
        result["mime_type"] = mime_type

    role = _optional_string(
        representation.get("role"),
        "representation.role",
        minimum=1,
        maximum=64,
        pattern=_ROLE_RE,
    )
    if role is not None:
        result["role"] = role

    language = _optional_string(
        representation.get("language"),
        "representation.language",
        minimum=2,
        maximum=35,
    )
    if language is not None:
        result["language"] = language

    size = representation.get("estimated_size_bytes")
    if size is not None:
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _invalid("estimated_size_bytes 必须是非负整数")
        result["estimated_size_bytes"] = size

    for boolean_field in ("materializable", "requires_auth"):
        boolean_value = representation.get(boolean_field)
        if boolean_value is not None:
            if not isinstance(boolean_value, bool):
                _invalid(f"{boolean_field} 必须是布尔值")
            result[boolean_field] = boolean_value

    rights_hint = _optional_string(
        representation.get("rights_hint"),
        "representation.rights_hint",
        minimum=1,
        maximum=512,
    )
    if rights_hint is not None:
        result["rights_hint"] = rights_hint
    return result


def normalize_resolved_resource(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the public resolved-resource shape.

    ``representation_id`` is intentionally optional here.  The resource
    inspection service owns public ID allocation and may fill it after an
    adapter has returned a result.
    """

    resolved_resource = _mapping(value, "resolved_resource")
    _reject_extra_fields(resolved_resource, _RESOLVED_RESOURCE_FIELDS, "resolved_resource")
    for required in ("title", "resource_type", "availability", "representations", "metadata"):
        if required not in resolved_resource:
            _invalid(f"resolved_resource 缺少 {required}")

    result: dict[str, Any] = {
        "title": _string(
            resolved_resource["title"], "resolved_resource.title", minimum=1, maximum=512
        ),
        "resource_type": resolved_resource["resource_type"],
        "availability": _normalise_availability(resolved_resource["availability"]),
        "representations": [],
        "metadata": _normalise_metadata(resolved_resource["metadata"]),
    }
    if not isinstance(result["resource_type"], str) or result["resource_type"] not in RESOURCE_TYPES:
        _invalid("resolved_resource.resource_type 无效")
    result["resource_type"] = str(result["resource_type"])

    raw_representations = resolved_resource["representations"]
    if isinstance(raw_representations, (str, bytes, bytearray)) or not isinstance(
        raw_representations, Sequence
    ):
        _invalid("representations 必须是数组")
    if len(raw_representations) > MAX_REPRESENTATIONS:
        _invalid("representations 数量超出上限")
    result["representations"] = [
        _normalise_representation(item, index)
        for index, item in enumerate(raw_representations)
    ]

    for field, maximum, minimum in (
        ("summary", 4000, 0),
        ("creator", 256, 1),
        ("language", 35, 2),
    ):
        if field in resolved_resource and resolved_resource[field] is not None:
            result[field] = _string(
                resolved_resource[field],
                f"resolved_resource.{field}",
                minimum=minimum,
                maximum=maximum,
            )
    return result


def _normalise_inspection(value: Mapping[str, Any]) -> dict[str, Any]:
    inspection = _mapping(value, "inspection")
    _reject_extra_fields(inspection, _INSPECTION_FIELDS, "inspection")
    for required in _INSPECTION_FIELDS:
        if required not in inspection:
            _invalid(f"inspection 缺少 {required}")
    result = {
        "inspector_id": _string(
            inspection["inspector_id"],
            "inspection.inspector_id",
            minimum=1,
            maximum=64,
            pattern=_INSPECTOR_ID_RE,
        ),
        "version": _string(
            inspection["version"], "inspection.version", minimum=1, maximum=64
        ),
        "method": _string(
            inspection["method"], "inspection.method", minimum=1, maximum=128
        ),
        "cache_status": inspection["cache_status"],
        "inspected_at": _validate_timestamp(inspection["inspected_at"]),
        "warnings": [],
    }
    if (
        not isinstance(result["cache_status"], str)
        or result["cache_status"] not in CACHE_STATUSES
    ):
        _invalid("inspection.cache_status 无效")
    result["cache_status"] = str(result["cache_status"])

    warnings = inspection["warnings"]
    if isinstance(warnings, (str, bytes, bytearray)) or not isinstance(warnings, Sequence):
        _invalid("inspection.warnings 必须是数组")
    if len(warnings) > MAX_WARNINGS:
        _invalid("warnings 数量超出上限")
    result["warnings"] = [
        _string(item, f"warnings[{index}]", maximum=512)
        for index, item in enumerate(warnings)
    ]
    return result


def _normalise_failures(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _invalid("failures 必须是数组")
    if len(value) > MAX_FAILURES:
        _invalid("failures 数量超出上限")
    result: list[dict[str, Any]] = []
    for index, raw_failure in enumerate(value):
        failure = _mapping(raw_failure, f"failures[{index}]")
        _reject_extra_fields(failure, _FAILURE_FIELDS, "failure")
        for required in ("code", "message", "retriable"):
            if required not in failure:
                _invalid(f"failures[{index}] 缺少 {required}")
        item: dict[str, Any] = {
            "code": _string(failure["code"], f"failures[{index}].code", minimum=1, maximum=128),
            "message": _string(
                failure["message"], f"failures[{index}].message", minimum=1, maximum=1024
            ),
            "retriable": failure["retriable"],
        }
        if not isinstance(failure["retriable"], bool):
            _invalid(f"failures[{index}].retriable 必须是布尔值")
        if "platform" in failure and failure["platform"] is not None:
            item["platform"] = _string(
                failure["platform"],
                f"failures[{index}].platform",
                minimum=1,
                maximum=64,
                pattern=_PLATFORM_ID_RE,
            )
        if "resource_id" in failure and failure["resource_id"] is not None:
            item["resource_id"] = _string(
                failure["resource_id"],
                f"failures[{index}].resource_id",
                minimum=20,
                maximum=69,
                pattern=_RESOURCE_ID_RE,
            )
        result.append(item)
    return result


@dataclass(frozen=True)
class InspectionResult:
    """A validated, bounded result returned by a :class:`ResourceInspector`."""

    resolution_status: str
    resolved_resource: Mapping[str, Any]
    inspection: Mapping[str, Any]
    failures: Sequence[Mapping[str, Any]] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.resolution_status, str)
            or self.resolution_status not in RESOLUTION_STATUSES
        ):
            _invalid("resolution_status 无效")
        normalised_resource = normalize_resolved_resource(self.resolved_resource)
        normalised_inspection = _normalise_inspection(self.inspection)
        normalised_failures = _normalise_failures(self.failures)

        # Keep a private immutable snapshot for to_mapping().  The public
        # dataclass fields remain useful to adapters, but mutations to either
        # the caller's input or a previously returned mapping cannot alter a
        # later output.
        public_resource = _json_copy(normalised_resource)
        public_inspection = _json_copy(normalised_inspection)
        public_failures = _json_copy(normalised_failures)
        object.__setattr__(self, "resolved_resource", public_resource)
        object.__setattr__(self, "inspection", public_inspection)
        object.__setattr__(self, "failures", public_failures)
        object.__setattr__(
            self,
            "_snapshot",
            _freeze_json(
                {
                    "resolution_status": str(self.resolution_status),
                    "resolved_resource": normalised_resource,
                    "inspection": normalised_inspection,
                    "failures": normalised_failures,
                }
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a fresh, strictly bounded JSON-compatible mapping."""

        return _thaw_json(self._snapshot)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InspectionResult":
        """Construct a result from the core result shape."""

        mapping = _mapping(value, "inspection_result")
        allowed = frozenset({"resolution_status", "resolved_resource", "inspection", "failures"})
        _reject_extra_fields(mapping, allowed, "inspection_result")
        for required in ("resolution_status", "resolved_resource", "inspection"):
            if required not in mapping:
                _invalid(f"inspection_result 缺少 {required}")
        return cls(
            resolution_status=mapping["resolution_status"],
            resolved_resource=mapping["resolved_resource"],
            inspection=mapping["inspection"],
            failures=mapping.get("failures", ()),
        )


@runtime_checkable
class ResourceInspector(Protocol):
    """Protocol implemented by a platform-specific, non-network-bound adapter."""

    platform_id: str
    inspector_id: str
    version: str

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        ...


class InspectionRouter:
    """Exact platform router for inspection adapters.

    Registration is explicit and one-to-one.  In particular, registering a
    generic inspector does not make it a fallback for an unknown platform.
    """

    def __init__(self, inspectors: Sequence[ResourceInspector] | None = None) -> None:
        self._inspectors: dict[str, ResourceInspector] = {}
        for inspector in inspectors or ():
            self.register(inspector)

    @staticmethod
    def _validate_platform_id(value: Any) -> str:
        if not isinstance(value, str) or _PLATFORM_ID_RE.fullmatch(value) is None:
            _invalid("检查器 platform_id 格式无效")
        return value

    def register(self, inspector: ResourceInspector) -> None:
        platform_id = self._validate_platform_id(getattr(inspector, "platform_id", None))
        if not callable(getattr(inspector, "inspect", None)):
            _invalid("检查器缺少 inspect 方法")
        if platform_id in self._inspectors:
            _invalid("检查器平台重复注册")
        self._inspectors[platform_id] = inspector

    @property
    def registered_platforms(self) -> tuple[str, ...]:
        return tuple(sorted(self._inspectors))

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        if not isinstance(resource, Mapping):
            _unsupported()
        platform = resource.get("platform")
        # Do not strip, case-fold, infer, or otherwise reinterpret the
        # platform.  Platform IDs are canonical at the retrieval boundary.
        if not isinstance(platform, str) or not platform:
            _unsupported()
        inspector = self._inspectors.get(platform)
        if inspector is None:
            _unsupported()
        try:
            result = inspector.inspect(resource)
        except DomainError:
            raise
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            raise DomainError("INTERNAL_ERROR", "检查器执行失败", retryable=True) from exc
        if not isinstance(result, InspectionResult):
            raise DomainError("INTERNAL_ERROR", "检查器返回了无效结果", retryable=True)
        return result

    def resolve(self, resource: Mapping[str, Any]) -> InspectionResult:
        """Alias used by services that call the routing operation resolve."""

        return self.inspect(resource)


def build_default_inspection(
    inspector_id: str,
    *,
    method: str = "bounded_get",
    cache_status: str = "miss",
    inspected_at: str | None = None,
    warnings: Sequence[str] = (),
    version: str = INSPECTOR_VERSION,
) -> dict[str, Any]:
    """Build the fixed metadata envelope used by platform inspectors."""

    if inspected_at is None:
        inspected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return _normalise_inspection(
        {
            "inspector_id": inspector_id,
            "version": version,
            "method": method,
            "cache_status": cache_status,
            "inspected_at": inspected_at,
            "warnings": list(warnings),
        }
    )


def _fingerprint_value(value: Any, *, key: str = "") -> Any:
    """Create deterministic JSON data for the private source fingerprint."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _invalid("资源身份不得包含 NaN 或 Infinity")
        return value
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).replace("\u200b", "")
        text = re.sub(r"\s+", " ", text).strip().casefold()
        if key in {"source_url", "canonical_url", "url"}:
            try:
                from .retrieval.identity import normalize_url

                return normalize_url(text) or ""
            except (ImportError, TypeError, ValueError):
                pass
        return text
    if isinstance(value, (bytes, bytearray, memoryview)) or isinstance(
        value, (Path, PurePath, os.PathLike)
    ):
        _invalid("资源身份不得包含字节或路径对象")
    if isinstance(value, Mapping):
        return {
            str(key): _fingerprint_value(item, key=str(key).casefold())
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item, key=key) for item in value]
    _invalid("资源身份不得包含任意 Python 对象")


def _resource_mapping(resource: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(resource, Mapping):
        return resource
    to_mapping = getattr(resource, "to_mapping", None)
    if callable(to_mapping):
        mapped = to_mapping()
        if isinstance(mapped, Mapping):
            return mapped
    _invalid("resource 必须是对象")


def _collect_stable_metadata(
    value: Mapping[str, Any],
    *,
    path: tuple[str, ...] = (),
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collected = result if result is not None else {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        normalised = _normalise_key_name(key)
        compact = re.sub(r"[^a-z0-9]", "", normalised)
        current_path = path + (key,)
        if (
            normalised in _STABLE_IDENTITY_KEYS
            or compact in _STABLE_IDENTITY_COMPACT_KEYS
            or normalised.endswith("_id")
        ):
            collected[".".join(current_path)] = _fingerprint_value(
                raw_value, key=normalised
            )
        if isinstance(raw_value, Mapping):
            _collect_stable_metadata(raw_value, path=current_path, result=collected)
    return collected


def source_fingerprint(resource: Mapping[str, Any] | Any) -> str:
    """Return a stable SHA-256 identity snapshot for an inspected resource.

    Only stable retrieval identity evidence is included from metadata.  This
    prevents volatile crawl fields from invalidating the inspection cache,
    while title, source URL, platform, type, and native identity changes all
    produce a new fingerprint.
    """

    mapped = _resource_mapping(resource)
    platform = _fingerprint_value(mapped.get("platform", ""), key="platform")
    resource_type = _fingerprint_value(
        mapped.get("resource_type", mapped.get("type", "other")), key="resource_type"
    )
    title = _fingerprint_value(mapped.get("title", mapped.get("name", "")), key="title")
    source_url = mapped.get("source_url", mapped.get("canonical_url", ""))
    normalized_source_url = _fingerprint_value(source_url, key="source_url")

    identity_fields: dict[str, Any] = {}
    for key in (
        "native_identity",
        "native_type",
        "native_id",
        "isbn",
        "doi",
        "edition",
        "version",
        "identity",
        "canonical_url",
        "external_id",
    ):
        if key in mapped:
            identity_fields[key] = _fingerprint_value(mapped[key], key=key)

    metadata = mapped.get("metadata")
    stable_metadata = (
        _collect_stable_metadata(metadata) if isinstance(metadata, Mapping) else {}
    )
    snapshot = {
        "platform": platform,
        "resource_type": resource_type,
        "title": title,
        "source_url": normalized_source_url,
        "identity": identity_fields,
        "metadata": stable_metadata,
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AVAILABILITY_STATUSES",
    "CACHE_STATUSES",
    "INSPECTION_PROFILE_VERSION",
    "INSPECTOR_VERSION",
    "InspectionResult",
    "InspectionRouter",
    "ResourceInspector",
    "build_default_inspection",
    "normalize_resolved_resource",
    "source_fingerprint",
]
