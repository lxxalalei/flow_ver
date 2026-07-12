#!/usr/bin/env python3
"""Lightweight file format and content validation for downloaded resources."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_FORMATS = (
    "html",
    "pdf",
    "epub",
    "zip",
    "docx",
    "xlsx",
    "pptx",
    "jpeg",
    "png",
    "gif",
    "mp3",
    "mp4",
    "webp",
    "bmp",
    "tiff",
    "avif",
    "heif",
    "wav",
    "flac",
    "ogg",
    "webm",
    "avi",
    "mpegts",
    "gzip",
    "tar",
    "7z",
    "rar",
    "ole",
    "text",
)

FORMAT_ALIASES = {
    "htm": "html",
    "application/xhtml+xml": "html",
    "text/html": "html",
    "application/pdf": "pdf",
    "application/epub+zip": "epub",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "jpg": "jpeg",
    "jpe": "jpeg",
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
    "audio/mpeg": "mp3",
    "video/mp4": "mp4",
    "m4a": "mp4",
    "mov": "mp4",
    "audio/mp4": "mp4",
    "video/quicktime": "mp4",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/avif": "avif",
    "image/heif": "heif",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "video/ogg": "ogg",
    "application/ogg": "ogg",
    "mkv": "webm",
    "video/webm": "webm",
    "video/x-matroska": "webm",
    "video/x-msvideo": "avi",
    "ts": "mpegts",
    "video/mp2t": "mpegts",
    "gz": "gzip",
    "application/gzip": "gzip",
    "application/x-gzip": "gzip",
    "application/x-tar": "tar",
    "application/x-7z-compressed": "7z",
    "application/vnd.rar": "rar",
    "doc": "ole",
    "xls": "ole",
    "ppt": "ole",
    "txt": "text",
    "md": "text",
    "markdown": "text",
    "json": "text",
    "xml": "text",
    "csv": "text",
    "text/plain": "text",
    "text/markdown": "text",
    "application/json": "text",
    "application/xml": "text",
    "text/xml": "text",
    "text/csv": "text",
    "svg": "text",
    "srt": "text",
    "vtt": "text",
    "ass": "text",
    "m3u8": "text",
    "yaml": "text",
    "yml": "text",
}

EXTENSION_FORMATS = {
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".pdf": "pdf",
    ".epub": "epub",
    ".zip": "zip",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".jpe": "jpeg",
    ".png": "png",
    ".gif": "gif",
    ".mp3": "mp3",
    ".mp4": "mp4",
    ".m4a": "mp4",
    ".mov": "mp4",
    ".webp": "webp",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".avif": "avif",
    ".heif": "heif",
    ".heic": "heif",
    ".wav": "wav",
    ".flac": "flac",
    ".ogg": "ogg",
    ".oga": "ogg",
    ".ogv": "ogg",
    ".webm": "webm",
    ".mkv": "webm",
    ".avi": "avi",
    ".ts": "mpegts",
    ".gz": "gzip",
    ".tgz": "gzip",
    ".tar": "tar",
    ".7z": "7z",
    ".rar": "rar",
    ".doc": "ole",
    ".xls": "ole",
    ".ppt": "ole",
    ".txt": "text",
    ".md": "text",
    ".markdown": "text",
    ".json": "text",
    ".xml": "text",
    ".csv": "text",
    ".log": "text",
    ".svg": "text",
    ".srt": "text",
    ".vtt": "text",
    ".ass": "text",
    ".m3u8": "text",
    ".yaml": "text",
    ".yml": "text",
}

MIME_TYPES = {
    "html": "text/html",
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "zip": "application/zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "avif": "image/avif",
    "heif": "image/heif",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "ogg": "application/ogg",
    "webm": "video/webm",
    "avi": "video/x-msvideo",
    "mpegts": "video/mp2t",
    "gzip": "application/gzip",
    "tar": "application/x-tar",
    "7z": "application/x-7z-compressed",
    "rar": "application/vnd.rar",
    "ole": "application/x-ole-storage",
    "text": "text/plain",
    "unknown": "application/octet-stream",
}

ZIP_MARKERS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
HTML_MARKERS = re.compile(rb"<!doctype\s+html\b|<html\b|<head\b|<body\b", re.IGNORECASE)
HTML_ERROR_PATTERNS = (
    re.compile(r"\b(?:400|401|403|404|408|429|500|502|503|504)\b"),
    re.compile(r"\b(?:not found|access denied|forbidden|unauthorized|server error)\b", re.IGNORECASE),
    re.compile(r"\b(?:bad gateway|service unavailable|request blocked|too many requests)\b", re.IGNORECASE),
    re.compile(r"(?:页面不存在|访问被拒绝|无权访问|服务器错误|服务不可用|请求失败|登录后访问)"),
)


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _normalize_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    return FORMAT_ALIASES.get(normalized, normalized)


def _normalize_expected_formats(expected_formats: Iterable[str] | str | None) -> list[str]:
    if expected_formats is None:
        return []
    values = [expected_formats] if isinstance(expected_formats, str) else list(expected_formats)
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("expected_formats must contain non-empty strings")
        file_format = _normalize_format(value)
        if file_format not in SUPPORTED_FORMATS:
            raise ValueError(f"unsupported expected format: {value}")
        if file_format not in normalized:
            normalized.append(file_format)
    return normalized


def _decode_text(data: bytes) -> tuple[str | None, str | None]:
    encodings = []
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        encodings.append("utf-8-sig")
    encodings.extend(("utf-8", "gb18030"))
    for encoding in encodings:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def _looks_like_text(data: bytes) -> tuple[bool, str | None]:
    text, encoding = _decode_text(data)
    if text is None:
        return False, None
    if not text:
        return True, encoding
    printable = sum(character.isprintable() or character in "\r\n\t" for character in text)
    return printable / len(text) >= 0.90, encoding


def _html_details(data: bytes) -> dict[str, Any] | None:
    if not HTML_MARKERS.search(data[:65536]):
        return None
    text, encoding = _decode_text(data[:65536])
    if text is None:
        text = data[:65536].decode("latin-1", errors="replace")
        encoding = "latin-1"
    title_match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", text, re.IGNORECASE | re.DOTALL)
    heading_match = re.search(r"<h1\b[^>]*>(.*?)</h1\s*>", text, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"<[^>]+>", " ", title_match.group(1)).strip() if title_match else ""
    heading = re.sub(r"<[^>]+>", " ", heading_match.group(1)).strip() if heading_match else ""
    error_probe = f"{title}\n{heading}\n{text[:8192]}"
    is_error_page = any(pattern.search(error_probe) for pattern in HTML_ERROR_PATTERNS)
    return {"encoding": encoding, "title": title, "is_error_page": is_error_page}


def _inspect_zip(path: Path) -> tuple[str, dict[str, Any], dict[str, str] | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = {info.filename.replace("\\", "/").lstrip("/").lower() for info in infos}
            details: dict[str, Any] = {"entry_count": len(infos)}
            if "word/document.xml" in names:
                return "docx", details, None
            if "xl/workbook.xml" in names:
                return "xlsx", details, None
            if "ppt/presentation.xml" in names:
                return "pptx", details, None
            if "mimetype" in names:
                info = next(info for info in infos if info.filename.replace("\\", "/").lstrip("/").lower() == "mimetype")
                if info.file_size <= 1024:
                    mimetype_value = archive.read(info).strip()
                    details["container_mimetype"] = mimetype_value.decode("ascii", errors="replace")
                    if mimetype_value == b"application/epub+zip":
                        return "epub", details, None
            if "meta-inf/container.xml" in names and any(name.endswith(".opf") for name in names):
                return "epub", details, None
            return "zip", details, None
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        return "zip", {}, _issue("INVALID_ZIP_CONTAINER", f"ZIP container cannot be read: {exc}")


def _detect_format(path: Path, head: bytes) -> tuple[str, str, dict[str, Any], list[dict[str, str]]]:
    details: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    if head.startswith(ZIP_MARKERS):
        file_format, zip_details, zip_error = _inspect_zip(path)
        details.update(zip_details)
        if zip_error:
            errors.append(zip_error)
        return file_format, "zip_container", details, errors
    pdf_offset = head[:1024].find(b"%PDF-")
    if pdf_offset >= 0:
        details["signature_offset"] = pdf_offset
        return "pdf", "magic", details, errors
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg", "magic", details, errors
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "magic", details, errors
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "magic", details, errors
    if head.startswith(b"ID3") or (
        len(head) >= 2
        and head[0] == 0xFF
        and head[1] & 0xE0 == 0xE0
        and head[1] & 0x06 != 0
    ):
        return "mp3", "magic", details, errors
    if len(head) >= 12 and head[4:8] == b"ftyp" and int.from_bytes(head[:4], "big") >= 8:
        major_brand = head[8:12]
        details["major_brand"] = major_brand.decode("ascii", errors="replace")
        if major_brand in {b"avif", b"avis"}:
            return "avif", "magic", details, errors
        if major_brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return "heif", "magic", details, errors
        return "mp4", "magic", details, errors
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp", "magic", details, errors
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav", "magic", details, errors
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        return "avi", "magic", details, errors
    if len(head) >= 188 and head[0] == 0x47 and all(head[offset] == 0x47 for offset in range(188, min(len(head), 188 * 4), 188)):
        return "mpegts", "magic", details, errors
    if head.startswith(b"BM"):
        return "bmp", "magic", details, errors
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff", "magic", details, errors
    if head.startswith(b"fLaC"):
        return "flac", "magic", details, errors
    if head.startswith(b"OggS"):
        return "ogg", "magic", details, errors
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm", "magic", details, errors
    if head.startswith(b"\x1f\x8b"):
        return "gzip", "magic", details, errors
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar", "magic", details, errors
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z", "magic", details, errors
    if head.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return "rar", "magic", details, errors
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole", "magic", details, errors
    html = _html_details(head)
    if html is not None:
        details.update(html)
        return "html", "content_sniff", details, errors
    is_text, encoding = _looks_like_text(head)
    if is_text:
        details["encoding"] = encoding
        return "text", "content_sniff", details, errors
    return "unknown", "none", details, errors


def _integrity_errors(file_format: str, tail: bytes) -> list[dict[str, str]]:
    if file_format == "pdf" and b"%%EOF" not in tail:
        return [_issue("TRUNCATED_PDF", "PDF end marker is missing")]
    if file_format == "jpeg" and b"\xff\xd9" not in tail:
        return [_issue("TRUNCATED_JPEG", "JPEG end marker is missing")]
    if file_format == "png" and b"IEND" not in tail:
        return [_issue("TRUNCATED_PNG", "PNG IEND chunk is missing")]
    if file_format == "gif" and not tail.rstrip(b"\x00\r\n\t ").endswith(b";"):
        return [_issue("TRUNCATED_GIF", "GIF trailer is missing")]
    return []


def validate_download_file(
    path: str | Path,
    expected_formats: Iterable[str] | str | None = None,
) -> dict[str, Any]:
    """Validate one downloaded file and return a JSON-serializable result.

    ``expected_formats`` accepts canonical names, common extensions, or MIME
    types. When omitted, a known filename extension is used as the expectation.
    """

    file_path = Path(path).expanduser()
    explicit_expected = expected_formats is not None
    normalized_expected = _normalize_expected_formats(expected_formats)
    extension_format = EXTENSION_FORMATS.get(file_path.suffix.lower())
    if not explicit_expected and extension_format:
        normalized_expected = [extension_format]

    result: dict[str, Any] = {
        "valid": False,
        "path": str(file_path.resolve(strict=False)),
        "size_bytes": None,
        "detected_format": "unknown",
        "mime_type": MIME_TYPES["unknown"],
        "detection_method": "none",
        "extension_format": extension_format,
        "expected_formats": normalized_expected,
        "is_html_error_page": False,
        "is_masquerading_html": False,
        "details": {},
        "errors": [],
        "warnings": [],
    }

    if not file_path.exists():
        result["errors"].append(_issue("FILE_NOT_FOUND", "Download file does not exist"))
        return result
    if not file_path.is_file():
        result["errors"].append(_issue("NOT_A_FILE", "Download path is not a regular file"))
        return result

    try:
        size = file_path.stat().st_size
        result["size_bytes"] = size
        if size == 0:
            result["errors"].append(_issue("EMPTY_FILE", "Download file is empty"))
            return result
        with file_path.open("rb") as handle:
            head = handle.read(65536)
            if size > 8192:
                handle.seek(-8192, 2)
            else:
                handle.seek(0)
            tail = handle.read(8192)
    except OSError as exc:
        result["errors"].append(_issue("FILE_READ_ERROR", f"Download file cannot be read: {exc}"))
        return result

    detected_format, method, details, detection_errors = _detect_format(file_path, head)
    result["detected_format"] = detected_format
    result["mime_type"] = MIME_TYPES.get(detected_format, MIME_TYPES["unknown"])
    result["detection_method"] = method
    result["details"] = details
    result["errors"].extend(detection_errors)
    result["errors"].extend(_integrity_errors(detected_format, tail))

    if detected_format == "unknown":
        result["errors"].append(_issue("UNKNOWN_FORMAT", "File content does not match a supported format"))

    if normalized_expected and detected_format not in normalized_expected:
        result["errors"].append(
            _issue(
                "FORMAT_MISMATCH",
                f"Detected {detected_format}, expected one of {', '.join(normalized_expected)}",
            )
        )

    if detected_format == "html":
        is_error_page = bool(details.get("is_error_page"))
        is_masquerading = bool(normalized_expected and "html" not in normalized_expected)
        result["is_html_error_page"] = is_error_page
        result["is_masquerading_html"] = is_masquerading
        if is_error_page:
            title = details.get("title") or "untitled HTML response"
            result["errors"].append(_issue("HTML_ERROR_PAGE", f"Downloaded content is an HTML error page: {title}"))
        if is_masquerading:
            result["errors"].append(
                _issue("UNEXPECTED_HTML_CONTENT", "HTML content is masquerading as a non-HTML download")
            )

    if explicit_expected and extension_format and detected_format != extension_format:
        result["warnings"].append(
            _issue(
                "EXTENSION_CONTENT_MISMATCH",
                f"Filename extension suggests {extension_format}, but content is {detected_format}",
            )
        )

    result["valid"] = not result["errors"]
    return result


__all__ = ["SUPPORTED_FORMATS", "validate_download_file"]
