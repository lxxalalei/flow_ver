"""Runtime configuration for search, download and archive capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_DATA_DIR = (
    Path.home() / ".local" / "share" / "quanxiao" / "education-resource-mcp-data"
)
DEFAULT_LIBRARY_DIR = Path.home() / "Documents" / "学习资料库"


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    jobs_dir: Path
    search_timeout_seconds: int = 20
    download_timeout_seconds: int = 30
    max_workers: int = 8
    searxng_base_url: str = ""
    prefer_searxng: bool = False
    library_dir: Path | None = None

    @property
    def library_root(self) -> Path:
        return (self.library_dir or DEFAULT_LIBRARY_DIR).expanduser().resolve()

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(
            os.environ.get(
                "EDUCATION_RESOURCE_MCP_DATA_DIR",
                str(DEFAULT_DATA_DIR),
            )
        ).expanduser().resolve()
        prefer_searxng = os.environ.get(
            "EDUCATION_RESOURCE_MCP_PREFER_SEARXNG", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        library_dir = os.environ.get("EDUCATION_RESOURCE_MCP_LIBRARY_DIR")
        return cls(
            data_dir=data_dir,
            jobs_dir=data_dir / "jobs",
            search_timeout_seconds=_positive_int(
                "EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT", 20
            ),
            download_timeout_seconds=_positive_int(
                "EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT", 30
            ),
            max_workers=_positive_int("EDUCATION_RESOURCE_MCP_MAX_WORKERS", 8),
            searxng_base_url=os.environ.get(
                "EDUCATION_RESOURCE_MCP_SEARXNG_URL", ""
            ).rstrip("/"),
            prefer_searxng=prefer_searxng,
            library_dir=Path(library_dir).expanduser() if library_dir else None,
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.library_root.mkdir(parents=True, exist_ok=True)
