"""Stable learning-resource taxonomy and archive metadata normalization."""

from __future__ import annotations

import re
from typing import Any, Iterable


TAXONOMY_VERSION = "learning-v1"
UNCLASSIFIED_DIRECTORY = "99-待分类"
FALLBACK_TOPIC = "其他"

DOMAIN_REGISTRY: dict[str, dict[str, str]] = {
    "chinese_language": {
        "display_name": "语文与中文",
        "directory": "01-语文与中文",
    },
    "mathematics_reasoning": {
        "display_name": "数学与思维",
        "directory": "02-数学与思维",
    },
    "english_foreign_languages": {
        "display_name": "英语与外语",
        "directory": "03-英语与外语",
    },
    "natural_science": {
        "display_name": "自然科学",
        "directory": "04-自然科学",
    },
    "humanities_social_studies": {
        "display_name": "人文与社会",
        "directory": "05-人文与社会",
    },
    "information_technology": {
        "display_name": "信息科技",
        "directory": "06-信息科技",
    },
    "arts_aesthetics": {
        "display_name": "艺术与审美",
        "directory": "07-艺术与审美",
    },
    "physical_health": {
        "display_name": "体育与健康",
        "directory": "08-体育与健康",
    },
    "learning_skills": {
        "display_name": "学习方法与通用能力",
        "directory": "09-学习方法与通用能力",
    },
    "interdisciplinary_practice": {
        "display_name": "综合实践与跨学科",
        "directory": "10-综合实践与跨学科",
    },
}
DOMAIN_IDS = tuple(DOMAIN_REGISTRY)

LEGACY_DOMAIN_ALIASES: dict[str, str] = {
    "语文与中文": "chinese_language",
    "数学与思维": "mathematics_reasoning",
    "英语与外语": "english_foreign_languages",
    "自然科学": "natural_science",
    "自然与科学": "natural_science",
    "人文与社会": "humanities_social_studies",
    "信息科技": "information_technology",
    "艺术与审美": "arts_aesthetics",
    "艺术与创造": "arts_aesthetics",
    "体育与健康": "physical_health",
    "运动与健康": "physical_health",
    "安全教育": "physical_health",
    "学习方法与通用能力": "learning_skills",
    "人文与社会认知": "humanities_social_studies",
    "社会认知与价值观": "humanities_social_studies",
    "综合实践与跨学科": "interdisciplinary_practice",
}

CLASSIFICATION_STATUSES = ("classified", "needs_review", "unclassified")
MATERIAL_PURPOSES = (
    "explanation",
    "practice",
    "assessment",
    "reading",
    "reference",
    "experiment",
    "project",
    "lesson_material",
)
DIFFICULTIES = ("introductory", "intermediate", "advanced", "competition")

MAX_SECONDARY_DOMAINS = 4
MAX_TOPICS = 8
MAX_TOPIC_LENGTH = 64
MAX_MATERIAL_PURPOSES = 8
MAX_GRADE_LEVELS = 8
MAX_GRADE_LEVEL_LENGTH = 32
MAX_CURRICULUM_VERSIONS = 8
MAX_CURRICULUM_VERSION_LENGTH = 64
MAX_TAGS = 32
MAX_TAG_LENGTH = 64

_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PATH_RESERVED = re.compile(r'[<>:"/\\|?*]')


def _normalized_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = _WHITESPACE.sub(" ", value).strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    if _CONTROL.search(normalized):
        raise ValueError(f"{field} contains control characters")
    return normalized


def _safe_label(value: Any, *, field: str, max_length: int) -> str:
    normalized = _normalized_text(value, field=field, max_length=max_length)
    if _PATH_RESERVED.search(normalized) or normalized in {".", ".."}:
        raise ValueError(f"{field} contains path characters")
    return normalized


def _normalized_list(
    values: Any,
    *,
    field: str,
    max_items: int,
    max_length: int,
    safe_label: bool = False,
) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    output: list[str] = []
    seen: set[str] = set()
    normalizer = _safe_label if safe_label else _normalized_text
    for value in values:
        item = normalizer(value, field=field, max_length=max_length)
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def normalize_legacy_domain(value: Any) -> str | None:
    """Map one known legacy domain label to a learning-v1 machine ID."""

    if not isinstance(value, str):
        return None
    normalized = _WHITESPACE.sub(" ", value).strip()
    if normalized in DOMAIN_REGISTRY:
        return normalized
    return LEGACY_DOMAIN_ALIASES.get(normalized)


def domain_directory(domain_id: str) -> str:
    try:
        return DOMAIN_REGISTRY[domain_id]["directory"]
    except KeyError as exc:
        raise ValueError(f"unknown learning domain: {domain_id}") from exc


def domain_display_name(domain_id: str) -> str:
    try:
        return DOMAIN_REGISTRY[domain_id]["display_name"]
    except KeyError as exc:
        raise ValueError(f"unknown learning domain: {domain_id}") from exc


def _domain_list(values: Any, *, field: str, max_items: int) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    if len(values) > max_items:
        raise ValueError(f"{field} exceeds {max_items} items")
    output: list[str] = []
    for value in values:
        if value not in DOMAIN_REGISTRY:
            raise ValueError(f"unknown learning domain: {value}")
        if value not in output:
            output.append(value)
    return output


def _enum_list(
    values: Any, *, field: str, allowed: Iterable[str], max_items: int
) -> list[str]:
    normalized = _normalized_list(
        values, field=field, max_items=max_items, max_length=64
    )
    allowed_values = set(allowed)
    unknown = [value for value in normalized if value not in allowed_values]
    if unknown:
        raise ValueError(f"unsupported {field}: {unknown[0]}")
    return normalized


def normalize_classification(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and canonicalize one learning-v1 classification object."""

    raw = dict(value or {})
    version = raw.get("taxonomy_version", TAXONOMY_VERSION)
    if version != TAXONOMY_VERSION:
        raise ValueError(f"unsupported taxonomy_version: {version}")

    primary = raw.get("primary_domain")
    if primary is not None and primary not in DOMAIN_REGISTRY:
        raise ValueError(f"unknown learning domain: {primary}")
    secondary = _domain_list(
        raw.get("secondary_domains"),
        field="secondary_domains",
        max_items=MAX_SECONDARY_DOMAINS,
    )
    if primary is not None and primary in secondary:
        raise ValueError("primary_domain cannot also be a secondary_domain")

    status = raw.get("classification_status")
    if status is None:
        status = "classified" if primary else "unclassified"
    if status not in CLASSIFICATION_STATUSES:
        raise ValueError(f"unsupported classification_status: {status}")
    if status == "classified" and primary is None:
        raise ValueError("classified metadata requires primary_domain")
    if status == "unclassified" and primary is not None:
        raise ValueError("unclassified metadata cannot declare primary_domain")

    difficulty = raw.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        raise ValueError(f"unsupported difficulty: {difficulty}")

    classification: dict[str, Any] = {
        "taxonomy_version": TAXONOMY_VERSION,
        "classification_status": status,
        "secondary_domains": secondary,
        "topics": _normalized_list(
            raw.get("topics"),
            field="topics",
            max_items=MAX_TOPICS,
            max_length=MAX_TOPIC_LENGTH,
            safe_label=True,
        ),
        "material_purposes": _enum_list(
            raw.get("material_purposes"),
            field="material_purposes",
            allowed=MATERIAL_PURPOSES,
            max_items=MAX_MATERIAL_PURPOSES,
        ),
        "grade_levels": _normalized_list(
            raw.get("grade_levels"),
            field="grade_levels",
            max_items=MAX_GRADE_LEVELS,
            max_length=MAX_GRADE_LEVEL_LENGTH,
            safe_label=True,
        ),
        "curriculum_versions": _normalized_list(
            raw.get("curriculum_versions"),
            field="curriculum_versions",
            max_items=MAX_CURRICULUM_VERSIONS,
            max_length=MAX_CURRICULUM_VERSION_LENGTH,
            safe_label=True,
        ),
    }
    if primary is not None:
        classification["primary_domain"] = primary
    if difficulty is not None:
        classification["difficulty"] = difficulty
    return classification


def normalize_archive_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return canonical metadata while accepting deployed flat v2 fields.

    New persistence always receives a nested ``classification`` object. Known
    legacy Chinese domains are mapped; unknown legacy values are retained and
    explicitly marked ``needs_review`` rather than silently discarded.
    """

    raw = dict(metadata or {})
    legacy_primary = raw.get("primary_domain")
    legacy_topics_present = "topics" in raw
    legacy_topics = _normalized_list(
        raw.get("topics"),
        field="topics",
        max_items=MAX_TOPICS,
        max_length=MAX_TOPIC_LENGTH,
        safe_label=True,
    )

    if raw.get("classification") is not None:
        classification = normalize_classification(raw["classification"])
        if legacy_primary is not None:
            mapped = normalize_legacy_domain(legacy_primary)
            unknown_preserved_for_review = (
                mapped is None
                and classification["classification_status"] == "needs_review"
                and classification.get("primary_domain") is None
            )
            if not unknown_preserved_for_review and mapped != classification.get(
                "primary_domain"
            ):
                raise ValueError("legacy primary_domain conflicts with classification")
        if legacy_topics_present and legacy_topics != classification["topics"]:
            raise ValueError("legacy topics conflict with classification")
    else:
        mapped = normalize_legacy_domain(legacy_primary)
        if legacy_primary is None:
            status = "unclassified"
        elif mapped is None:
            status = "needs_review"
        else:
            status = "classified"
        generated: dict[str, Any] = {
            "taxonomy_version": TAXONOMY_VERSION,
            "classification_status": status,
            "secondary_domains": [],
            "topics": legacy_topics,
            "material_purposes": [],
            "grade_levels": [],
            "curriculum_versions": [],
        }
        if mapped is not None:
            generated["primary_domain"] = mapped
        classification = normalize_classification(generated)

    output = {
        key: value
        for key, value in raw.items()
        if key not in {"classification", "primary_domain", "topics"}
    }
    output["classification"] = classification
    if legacy_primary is not None and normalize_legacy_domain(legacy_primary) is None:
        legacy_raw = output.get("legacy_classification_raw")
        if not isinstance(legacy_raw, dict):
            legacy_raw = {}
        legacy_raw = dict(legacy_raw)
        legacy_raw["primary_domain"] = legacy_primary
        legacy_raw["topics"] = legacy_topics
        output["legacy_classification_raw"] = legacy_raw

    for field, max_length in (
        ("title", 512),
        ("collection", 128),
        ("source_name", 128),
    ):
        if field in output and output[field] is not None:
            output[field] = _normalized_text(
                output[field], field=field, max_length=max_length
            )
    if output.get("notes") is not None:
        notes = str(output["notes"]).strip()
        if len(notes) > 2000 or _CONTROL.search(notes):
            raise ValueError("notes is invalid")
        output["notes"] = notes
    output["tags"] = _normalized_list(
        output.get("tags"),
        field="tags",
        max_items=MAX_TAGS,
        max_length=MAX_TAG_LENGTH,
    )
    return output
