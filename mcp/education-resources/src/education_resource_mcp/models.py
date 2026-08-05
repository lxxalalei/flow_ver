"""Strict MCP input models matching contracts/v2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResourceType = Literal[
    "article", "book", "document", "video", "audio", "course", "dataset", "other"
]


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


class ArchiveMetadata(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    primary_domain: str | None = Field(default=None, min_length=1, max_length=64)
    topics: list[str] | None = Field(default=None, max_length=8)
    source_name: str | None = Field(default=None, min_length=1, max_length=128)
    collection: str | None = Field(default=None, min_length=1, max_length=128)
    tags: list[str] | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)


class LibraryFilters(StrictModel):
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    primary_domain: str | None = Field(default=None, min_length=1, max_length=64)
    topics: list[str] | None = Field(default=None, max_length=8)
    platforms: list[str] | None = Field(default=None, max_length=16)
    resource_types: list[ResourceType] | None = Field(default=None, max_length=8)
    collections: list[str] | None = Field(default=None, max_length=16)
    tags: list[str] | None = Field(default=None, max_length=32)
    archived_after: str | None = None
