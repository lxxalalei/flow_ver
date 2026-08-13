"""Trusted process configuration for local development and future deployment."""

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
    database_path: Path
    jobs_dir: Path
    library_dir: Path
    search_timeout_seconds: int = 20
    download_timeout_seconds: int = 30
    max_workers: int = 8
    plan_ttl_seconds: int = 15 * 60
    searxng_base_url: str = ""
    session_manager_data_dir: Path | None = None
    legacy_library_dirs: tuple[Path, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(
            os.environ.get(
                "EDUCATION_RESOURCE_MCP_DATA_DIR",
                str(DEFAULT_DATA_DIR),
            )
        ).expanduser().resolve()
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=Path(
                os.environ.get(
                    "EDUCATION_RESOURCE_MCP_LIBRARY_DIR",
                    str(DEFAULT_LIBRARY_DIR),
                )
            ).expanduser().resolve(),
            search_timeout_seconds=_positive_int(
                "EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT", 20
            ),
            download_timeout_seconds=_positive_int(
                "EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT", 30
            ),
            max_workers=_positive_int("EDUCATION_RESOURCE_MCP_MAX_WORKERS", 8),
            plan_ttl_seconds=_positive_int(
                "EDUCATION_RESOURCE_MCP_PLAN_TTL", 15 * 60
            ),
            searxng_base_url=os.environ.get(
                "EDUCATION_RESOURCE_MCP_SEARXNG_URL", ""
            ).rstrip("/"),
            session_manager_data_dir=(
                Path(os.environ["EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR"])
                .expanduser()
                if os.environ.get("EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR")
                else None
            ),
            legacy_library_dirs=(data_dir / "library",),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
