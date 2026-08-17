"""File helpers for downloaded resources and the local learning library."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files as package_files
import json
import logging
from pathlib import Path
import re
import shutil
from typing import Any

from .errors import DomainError


LOGGER = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
_DOCUMENT_EXTENSIONS = {
    ".html", ".htm", ".pdf", ".doc", ".docx", ".ppt", ".pptx",
    ".txt", ".epub", ".mobi", ".jpg", ".jpeg", ".png", ".gif",
    ".webp", ".xls", ".xlsx", ".rtf", ".csv", ".md",
}
_ZIP_MEDIA_TYPES = {
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_INVALID_COMPONENT_CHARS = re.compile(r'[\\/:*?"<>|]+')


@lru_cache(maxsize=1)
def library_taxonomy() -> dict[str, Any]:
    """Load the small directory-classification config shipped with the MCP."""

    path = package_files("education_resource_mcp").joinpath("library-taxonomy.json")
    return json.loads(path.read_text(encoding="utf-8"))


def archive_domains() -> list[dict[str, Any]]:
    """Return the configured top-level learning-library domains."""

    return [dict(item) for item in library_taxonomy().get("domains", [])]


def domain_directory(domain_id: str) -> str:
    """Resolve a domain id/display name/directory to its configured directory."""

    value = str(domain_id or "").strip()
    taxonomy = library_taxonomy()
    if not value:
        return str(taxonomy.get("unclassified_directory") or "99-待分类")
    for item in taxonomy.get("domains", []):
        if value in {
            str(item.get("id") or ""),
            str(item.get("display_name") or ""),
            str(item.get("directory") or ""),
        }:
            return str(item["directory"])
    raise DomainError(
        "INVALID_ARGUMENT",
        f"未知归档领域：{value}",
        details={"domain_id": value},
    )


def _safe_component(value: str, fallback: str) -> str:
    text = _INVALID_COMPONENT_CHARS.sub("_", str(value or "")).strip().strip(".")
    return text if text not in {"", ".", ".."} else fallback


def _resource_format(media_type: str, filename: str) -> str:
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    extension = Path(filename).suffix.lower()
    if normalized.startswith("video/"):
        return "video"
    if normalized.startswith("audio/"):
        return "audio"
    if normalized.startswith(("text/", "image/")) or normalized in {
        "application/pdf",
        "application/epub+zip",
        "application/msword",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return "document"
    if normalized in {"", "application/octet-stream"}:
        if extension in _VIDEO_EXTENSIONS:
            return "video"
        if extension in _AUDIO_EXTENSIONS:
            return "audio"
        if extension in _DOCUMENT_EXTENSIONS:
            return "document"
    return "other"


def format_directory(media_type: str, filename: str) -> str:
    return {
        "video": "视频",
        "audio": "音频",
        "document": "图文",
        "other": "其他",
    }[_resource_format(media_type, filename)]


def _available_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 2
    while True:
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def archive_downloaded_files(
    downloaded_files: list[dict[str, Any]],
    *,
    library_root: Path,
    domain_id: str = "",
    topic: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Move successful download files into the learning library."""

    taxonomy = library_taxonomy()
    domain = domain_directory(domain_id)
    topic_dir = _safe_component(
        topic,
        str(taxonomy.get("fallback_topic") or "其他"),
    )
    root = Path(library_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    archived: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in downloaded_files:
        source = Path(str(item.get("path") or "")).expanduser()
        if not source.is_file():
            failures.append(
                {
                    "resource_id": item.get("resource_id"),
                    "filename": item.get("filename") or source.name,
                    "code": "FILE_NOT_FOUND",
                    "message": "下载文件不存在，无法归档",
                }
            )
            continue

        filename = _safe_component(str(item.get("filename") or source.name), "学习资料")
        destination_dir = root / domain / topic_dir / format_directory(
            str(item.get("media_type") or ""), filename
        )
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / filename

        try:
            if source.resolve() != destination.resolve():
                destination = _available_target(destination)
                shutil.move(str(source), str(destination))
        except OSError as exc:
            failures.append(
                {
                    "resource_id": item.get("resource_id"),
                    "filename": filename,
                    "code": "ARCHIVE_FAILED",
                    "message": str(exc),
                }
            )
            continue

        archived_item = dict(item)
        archived_item.update(
            {
                "filename": destination.name,
                "path": str(destination.resolve()),
                "size_bytes": destination.stat().st_size,
            }
        )
        archived.append(archived_item)

    if archived:
        record = {
            "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "domain_id": domain_id,
            "topic": topic,
            "files": [
                {
                    key: item.get(key)
                    for key in (
                        "resource_id", "platform", "source_url", "title", "author",
                        "filename", "path", "media_type", "size_bytes",
                    )
                }
                for item in archived
            ],
        }
        try:
            with (root / "manifest.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            LOGGER.warning(
                "archive succeeded but manifest.jsonl could not be updated",
                exc_info=True,
            )

    return archived, failures


def media_signature_matches(media_type: str, filename: str, header: bytes) -> bool:
    """Check formats that have a stable, cheap file signature."""

    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    extension = Path(filename).suffix.lower()
    kind = _resource_format(normalized, filename)
    if extension in _VIDEO_EXTENSIONS and kind not in {"video", "other"}:
        return False
    if extension in _AUDIO_EXTENSIONS and kind not in {"audio", "other"}:
        return False
    if extension in _DOCUMENT_EXTENSIONS and kind not in {"document", "other"}:
        return False
    if normalized == "application/pdf":
        return header.startswith(b"%PDF-")
    if normalized == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if normalized in {"image/jpeg", "image/jpg"}:
        return header.startswith(b"\xff\xd8\xff")
    if normalized == "image/gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if normalized in _ZIP_MEDIA_TYPES:
        return header.startswith(b"PK\x03\x04")
    if normalized in {"video/mp4", "audio/mp4"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return header.startswith(b"ID3") or (
            len(header) >= 2
            and header[0] == 0xFF
            and header[1] & 0xE0 == 0xE0
        )
    return True


__all__ = [
    "archive_domains",
    "archive_downloaded_files",
    "domain_directory",
    "format_directory",
    "library_taxonomy",
    "media_signature_matches",
]
