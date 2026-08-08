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

from collections.abc import Mapping, Sequence
import copy
import json
from pathlib import Path
import re
from typing import Any


REGISTRY_VERSION = "1.0.0"
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
    }
)
INSPECTION_PLATFORM_IDS = frozenset(
    {
        "generic",
        "bilibili",
        "nlc",
        "annas-archive",
        "ximalaya",
        "zhihu",
        "smartedu",
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


class PlatformRegistryError(ValueError):
    """Raised when the platform registry is missing, malformed, or unsafe."""


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
                if any(part in normalized_key for part in _FORBIDDEN_KEY_PARTS):
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


def _validate_platform(platform: Any, index: int, seen_ids: set[str]) -> None:
    path = f"platforms[{index}]"
    item = _require_mapping(platform, path)
    _require_exact_keys(item, _PLATFORM_KEYS, path)

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
    _require_exact_keys(root, _TOP_LEVEL_KEYS, "registry")
    if _require_string(root["$schema"], "registry.$schema") != REGISTRY_SCHEMA_REFERENCE:
        _fail("registry.$schema", f"must be {REGISTRY_SCHEMA_REFERENCE!r}")
    if _require_string(root["registry_version"], "registry.registry_version") != REGISTRY_VERSION:
        _fail("registry.registry_version", f"must be {REGISTRY_VERSION}")

    platforms = _require_list(root["platforms"], "registry.platforms")
    if len(platforms) != len(EXPECTED_PLATFORM_IDS):
        _fail("registry.platforms", f"must contain exactly {len(EXPECTED_PLATFORM_IDS)} platforms")
    seen_ids: set[str] = set()
    for index, platform in enumerate(platforms):
        _validate_platform(platform, index, seen_ids)
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
    "CREATOR_BROWSE_PLATFORM_IDS",
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_SCHEMA_PATH",
    "EXPECTED_PLATFORM_IDS",
    "INSPECTION_PLATFORM_IDS",
    "LEGAL_RESOURCE_TYPES",
    "PlatformRegistryError",
    "get_platform_registry",
    "load_platform_registry",
    "load_registry",
    "validate_platform_registry",
]
