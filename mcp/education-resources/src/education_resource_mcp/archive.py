"""Shared file-format check used by downloaders.

The former archive/library workflow has been removed. This module remains only
because SmartEdu uses the small media signature helper after a download.
"""

from __future__ import annotations

from pathlib import Path


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


__all__ = ["media_signature_matches"]
