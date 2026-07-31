"""Strict MCP input models matching contracts/v1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResourceType = Literal[
    "article", "book", "document", "video", "audio", "course", "dataset", "other"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FlowIntent(StrictModel):
    topic: str = Field(min_length=1, max_length=1000)
    learning_goal: str | None = Field(default=None, max_length=2000)
    audience: Literal[
        "preschool",
        "primary",
        "middle_school",
        "high_school",
        "parent",
        "general",
    ] | None = None
    resource_types: list[ResourceType] | None = Field(default=None, max_length=8)
    language_preferences: list[str] | None = Field(default=None, max_length=8)
    platform_preferences: list[str] | None = Field(default=None, max_length=16)


class SearchFilters(StrictModel):
    platforms: list[str] | None = Field(default=None, max_length=16)
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
    collection: str | None = Field(default=None, min_length=1, max_length=128)
    tags: list[str] | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)


class LibraryFilters(StrictModel):
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    platforms: list[str] | None = Field(default=None, max_length=16)
    resource_types: list[ResourceType] | None = Field(default=None, max_length=8)
    collections: list[str] | None = Field(default=None, max_length=16)
    tags: list[str] | None = Field(default=None, max_length=32)
    archived_after: str | None = None
