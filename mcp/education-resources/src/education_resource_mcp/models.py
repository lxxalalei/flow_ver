"""Strict MCP input models matching contracts."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .taxonomy import (
    DIFFICULTIES,
    DOMAIN_IDS,
    MATERIAL_PURPOSES,
    MAX_CURRICULUM_VERSIONS,
    MAX_GRADE_LEVELS,
    MAX_MATERIAL_PURPOSES,
    MAX_SECONDARY_DOMAINS,
    MAX_TOPICS,
    TAXONOMY_VERSION,
    normalize_archive_metadata,
    normalize_classification,
    normalize_legacy_domain,
)


ResourceType = Literal[
    "article", "book", "document", "video", "audio", "course", "dataset", "other"
]
LearningDomainId = Literal[
    "chinese_language",
    "mathematics_reasoning",
    "english_foreign_languages",
    "natural_science",
    "humanities_social_studies",
    "information_technology",
    "arts_aesthetics",
    "physical_health",
    "learning_skills",
    "interdisciplinary_practice",
]
ClassificationStatus = Literal["classified", "needs_review", "unclassified"]
MaterialPurpose = Literal[
    "explanation",
    "practice",
    "assessment",
    "reading",
    "reference",
    "experiment",
    "project",
    "lesson_material",
]
Difficulty = Literal["introductory", "intermediate", "advanced", "competition"]
ResourceFormat = Literal["video", "document", "audio", "other"]

_SAFE_LABEL_PATTERN = r'^[^<>:"/\\|?*\x00-\x1f\x7f]+$'
_TEXT_PATTERN = r"^[^\x00-\x1f\x7f]+$"
Topic = Annotated[
    str, Field(min_length=1, max_length=64, pattern=_SAFE_LABEL_PATTERN)
]
GradeLevel = Annotated[
    str, Field(min_length=1, max_length=32, pattern=_SAFE_LABEL_PATTERN)
]
CurriculumVersion = Annotated[
    str, Field(min_length=1, max_length=64, pattern=_SAFE_LABEL_PATTERN)
]
Tag = Annotated[str, Field(min_length=1, max_length=64, pattern=_TEXT_PATTERN)]
CollectionName = Annotated[
    str, Field(min_length=1, max_length=128, pattern=_TEXT_PATTERN)
]
PlatformId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
]


def _normalize_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text_list(value: Any) -> Any:
    if value is None or not isinstance(value, (list, tuple)):
        return value
    return [_normalize_text(item) for item in value]


def _deduplicate(value: list[Any] | None) -> list[Any] | None:
    if value is None:
        return None
    return list(dict.fromkeys(value))


def _validate_timestamp(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must use RFC 3339 date-time format") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return normalized


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FlowGoal(StrictModel):
    topic: str = Field(min_length=1, max_length=1000)
    outcome: str | None = Field(default=None, max_length=2000)


class TaskConstraint(StrictModel):
    kind: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=1000)


class FlowTask(StrictModel):
    goal: FlowGoal
    user_role: Literal["child", "parent"] | None = None
    resource_target: Literal["child", "parent"] | None = None
    constraints: list[TaskConstraint] = Field(default_factory=list, max_length=32)


class SearchTaskQuery(StrictModel):
    query: str = Field(min_length=1, max_length=1000)


class SearchTask(StrictModel):
    platform: str = Field(min_length=1, max_length=64)
    queries: list[SearchTaskQuery] = Field(min_length=1, max_length=8)
    direction: str | None = Field(default=None, min_length=1, max_length=256)


class SearchFilters(StrictModel):
    resource_types: list[ResourceType] | None = Field(default=None, max_length=8)
    languages: list[str] | None = Field(default=None, max_length=8)
    published_after: str | None = None
    max_duration_seconds: int | None = Field(default=None, ge=1, le=86400)


class DownloadOptions(StrictModel):
    preferred_container: Literal[
        "original", "pdf", "epub", "mp4", "mp3", "html", "text"
    ] = "html"
    max_bytes_per_resource: int | None = Field(
        default=None, ge=1, le=5_368_709_120
    )
    allow_safe_fallback: bool = True


class ArchiveClassification(StrictModel):
    taxonomy_version: Literal["learning-v1"] = TAXONOMY_VERSION
    classification_status: ClassificationStatus
    primary_domain: LearningDomainId | None = None
    secondary_domains: list[LearningDomainId] = Field(
        default_factory=list, max_length=MAX_SECONDARY_DOMAINS
    )
    topics: list[Topic] = Field(default_factory=list, max_length=MAX_TOPICS)
    material_purposes: list[MaterialPurpose] = Field(
        default_factory=list, max_length=MAX_MATERIAL_PURPOSES
    )
    grade_levels: list[GradeLevel] = Field(
        default_factory=list, max_length=MAX_GRADE_LEVELS
    )
    difficulty: Difficulty | None = None
    curriculum_versions: list[CurriculumVersion] = Field(
        default_factory=list, max_length=MAX_CURRICULUM_VERSIONS
    )

    @field_validator(
        "topics", "grade_levels", "curriculum_versions", mode="before"
    )
    @classmethod
    def normalize_labels(cls, value: Any) -> Any:
        return _normalize_text_list(value)

    @model_validator(mode="after")
    def validate_semantics(self) -> "ArchiveClassification":
        canonical = normalize_classification(self.model_dump(exclude_none=True))
        self.secondary_domains = canonical["secondary_domains"]
        self.topics = canonical["topics"]
        self.material_purposes = canonical["material_purposes"]
        self.grade_levels = canonical["grade_levels"]
        self.curriculum_versions = canonical["curriculum_versions"]
        return self


class ArchiveMetadata(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    classification: ArchiveClassification | None = None
    # Deployed flat fields remain accepted and are normalized into classification.
    primary_domain: str | None = Field(default=None, min_length=1, max_length=64)
    topics: list[Topic] | None = Field(default=None, max_length=MAX_TOPICS)
    source_name: str | None = Field(default=None, min_length=1, max_length=128)
    collection: CollectionName | None = None
    tags: list[Tag] | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "title", "primary_domain", "source_name", "collection", mode="before"
    )
    @classmethod
    def normalize_scalar_text(cls, value: Any) -> Any:
        return _normalize_text(value)

    @field_validator("topics", "tags", mode="before")
    @classmethod
    def normalize_array_text(cls, value: Any) -> Any:
        return _normalize_text_list(value)

    @model_validator(mode="after")
    def normalize_compatibility_fields(self) -> "ArchiveMetadata":
        normalized = normalize_archive_metadata(self.model_dump(exclude_none=True))
        self.classification = ArchiveClassification.model_validate(
            normalized["classification"]
        )
        if self.topics is not None:
            self.topics = normalized["classification"]["topics"]
        if self.tags is not None:
            self.tags = normalized["tags"]
        return self


class LibraryFilters(StrictModel):
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    taxonomy_versions: list[Literal["learning-v1"]] | None = Field(
        default=None, max_length=4
    )
    classification_statuses: list[ClassificationStatus] | None = Field(
        default=None, max_length=3
    )
    # primary_domain is the deployed singular compatibility filter.
    primary_domain: str | None = Field(default=None, min_length=1, max_length=64)
    primary_domains: list[LearningDomainId] | None = Field(default=None, max_length=10)
    secondary_domains: list[LearningDomainId] | None = Field(default=None, max_length=10)
    topics: list[Topic] | None = Field(default=None, max_length=MAX_TOPICS)
    material_purposes: list[MaterialPurpose] | None = Field(
        default=None, max_length=MAX_MATERIAL_PURPOSES
    )
    grade_levels: list[GradeLevel] | None = Field(
        default=None, max_length=MAX_GRADE_LEVELS
    )
    difficulties: list[Difficulty] | None = Field(default=None, max_length=4)
    curriculum_versions: list[CurriculumVersion] | None = Field(
        default=None, max_length=MAX_CURRICULUM_VERSIONS
    )
    platforms: list[PlatformId] | None = Field(default=None, max_length=16)
    resource_types: list[ResourceType] | None = Field(default=None, max_length=8)
    resource_formats: list[ResourceFormat] | None = Field(default=None, max_length=4)
    collections: list[CollectionName] | None = Field(default=None, max_length=16)
    tags: list[Tag] | None = Field(default=None, max_length=32)
    archived_after: str | None = Field(
        default=None, json_schema_extra={"format": "date-time"}
    )
    archived_before: str | None = Field(
        default=None, json_schema_extra={"format": "date-time"}
    )

    @field_validator("query", "primary_domain", mode="before")
    @classmethod
    def normalize_scalar_text(cls, value: Any) -> Any:
        return _normalize_text(value)

    @field_validator(
        "primary_domains",
        "secondary_domains",
        "taxonomy_versions",
        "classification_statuses",
        "topics",
        "material_purposes",
        "grade_levels",
        "difficulties",
        "curriculum_versions",
        "platforms",
        "resource_types",
        "resource_formats",
        "collections",
        "tags",
        mode="before",
    )
    @classmethod
    def normalize_array_text(cls, value: Any) -> Any:
        return _normalize_text_list(value)

    @field_validator("archived_after", "archived_before", mode="before")
    @classmethod
    def validate_timestamp(cls, value: Any) -> Any:
        return _validate_timestamp(value)

    @model_validator(mode="after")
    def validate_compatibility_filter(self) -> "LibraryFilters":
        for field in (
            "taxonomy_versions",
            "classification_statuses",
            "primary_domains",
            "secondary_domains",
            "topics",
            "material_purposes",
            "grade_levels",
            "difficulties",
            "curriculum_versions",
            "platforms",
            "resource_types",
            "resource_formats",
            "collections",
            "tags",
        ):
            setattr(self, field, _deduplicate(getattr(self, field)))
        if self.primary_domain is not None and self.primary_domains:
            mapped = normalize_legacy_domain(self.primary_domain)
            if mapped is None or mapped not in self.primary_domains:
                raise ValueError(
                    "primary_domain conflicts with primary_domains"
                )
        if (
            self.archived_after is not None
            and self.archived_before is not None
            and datetime.fromisoformat(
                self.archived_after.replace("Z", "+00:00")
            )
            >= datetime.fromisoformat(
                self.archived_before.replace("Z", "+00:00")
            )
        ):
            raise ValueError("archived_after must be earlier than archived_before")
        return self


assert tuple(DOMAIN_IDS) == tuple(LearningDomainId.__args__)
assert tuple(MATERIAL_PURPOSES) == tuple(MaterialPurpose.__args__)
assert tuple(DIFFICULTIES) == tuple(Difficulty.__args__)
