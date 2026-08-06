"""Safe file-system operations for the learning resource archive.

SQLite owns archive intent and state.  This module only stages, verifies and
publishes files below the configured library root; callers must create a
pending database record before invoking it.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
from typing import BinaryIO

from .taxonomy import domain_directory


MAX_COMPONENT_BYTES = 240
MAX_RELATIVE_PATH_BYTES = 900
COPY_CHUNK_BYTES = 1024 * 1024
STAGING_DIRECTORY = ".archive-staging"

_SEPARATORS = re.compile(r"[/\\]+")
_WHITESPACE = re.compile(r"\s+")
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
_DOCUMENT_EXTENSIONS = {
    ".html", ".htm", ".pdf", ".doc", ".docx", ".ppt", ".pptx",
    ".txt", ".epub", ".mobi", ".jpg", ".jpeg", ".png", ".gif",
    ".webp", ".xls", ".xlsx", ".rtf", ".csv", ".md",
}
_DOCUMENT_MEDIA_TYPES = {
    "application/pdf",
    "application/epub+zip",
    "application/msword",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ZIP_MEDIA_TYPES = {
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ArchiveFileError(ValueError):
    """A safe, expected archive file-system failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class StagedFile:
    relative_path: str
    sha256: str
    byte_size: int
    media_type: str


@dataclass(frozen=True, slots=True)
class PublishedFile:
    relative_path: str
    deduplicated: bool


def _is_control(character: str) -> bool:
    return unicodedata.category(character) in {"Cc", "Cf", "Cs"}


def sanitize_component(value: str, *, fallback: str, max_bytes: int) -> str:
    """Return one portable path component with deterministic byte limits."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join("_" if _is_control(char) else char for char in text)
    text = _SEPARATORS.sub("_", text)
    text = re.sub(r'[<>:"|?*]', "_", text)
    text = _WHITESPACE.sub(" ", text).strip(" .")
    if text in {"", ".", ".."}:
        text = fallback

    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    output: list[str] = []
    size = 0
    for character in text:
        width = len(character.encode("utf-8"))
        if size + width > max_bytes:
            break
        output.append(character)
        size += width
    truncated = "".join(output).rstrip(" .")
    return truncated or fallback


def resource_format(media_type: str, filename: str) -> str:
    """Return the stable format ID derived from verified media facts."""

    normalized_media = str(media_type or "").split(";", 1)[0].strip().lower()
    extension = Path(filename).suffix.lower()
    if normalized_media.startswith("video/"):
        return "video"
    if normalized_media.startswith("audio/"):
        return "audio"
    if (
        normalized_media.startswith("text/")
        or normalized_media.startswith("image/")
        or normalized_media in _DOCUMENT_MEDIA_TYPES
    ):
        return "document"
    if normalized_media in {"", "application/octet-stream"}:
        if extension in _VIDEO_EXTENSIONS:
            return "video"
        if extension in _AUDIO_EXTENSIONS:
            return "audio"
        if extension in _DOCUMENT_EXTENSIONS:
            return "document"
    return "other"


def format_directory(media_type: str, filename: str) -> str:
    """Map the stable resource format to its fixed Chinese directory."""

    return {
        "video": "视频",
        "document": "图文",
        "audio": "音频",
        "other": "其他",
    }[resource_format(media_type, filename)]


def media_signature_matches(media_type: str, filename: str, header: bytes) -> bool:
    """Perform conservative format checks when a stable signature exists."""

    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    extension = Path(filename).suffix.lower()
    mime_format = resource_format(normalized, filename)
    extension_formats: set[str] = set()
    if extension in _VIDEO_EXTENSIONS:
        extension_formats.add("video")
    if extension in _AUDIO_EXTENSIONS:
        extension_formats.add("audio")
    if extension in _DOCUMENT_EXTENSIONS:
        extension_formats.add("document")
    if extension_formats and mime_format != "other" and mime_format not in extension_formats:
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
            len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
    return True


def build_relative_path(
    classification: dict[str, object],
    *,
    source_name: str,
    title: str,
    filename: str,
    media_type: str,
) -> str:
    """Build the intended library path from normalized, server-owned facts."""

    status = classification.get("classification_status")
    primary_domain = classification.get("primary_domain")
    if status == "classified" and isinstance(primary_domain, str):
        domain = domain_directory(primary_domain)
        topics = classification.get("topics")
        first_topic = topics[0] if isinstance(topics, list) and topics else "其他"
        topic = sanitize_component(str(first_topic), fallback="其他", max_bytes=128)
    else:
        domain = "99-待分类"
        topic = "其他"

    source = sanitize_component(source_name, fallback="", max_bytes=96)
    resource_title = sanitize_component(title, fallback="学习资料", max_bytes=160)
    suffix = sanitize_extension(Path(filename).suffix)
    stem = f"{source}-{resource_title}" if source else resource_title
    archive_name = f"{stem}{suffix}"
    relative = PurePosixPath(
        domain,
        topic,
        format_directory(media_type, filename),
        archive_name,
    )
    validate_relative_path(relative.as_posix())
    return relative.as_posix()


def sanitize_extension(value: str) -> str:
    extension = str(value or "").lower()
    if re.fullmatch(r"\.[a-z0-9]{1,15}", extension):
        return extension
    return ""


def validate_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ArchiveFileError("invalid_relative_path", "归档相对路径不能为空")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArchiveFileError("invalid_relative_path", "归档路径必须是安全相对路径")
    if len(value.encode("utf-8")) > MAX_RELATIVE_PATH_BYTES:
        raise ArchiveFileError("path_too_long", "归档相对路径超过长度上限")
    for part in path.parts:
        if len(part.encode("utf-8")) > MAX_COMPONENT_BYTES:
            raise ArchiveFileError("path_component_too_long", "归档路径组件超过长度上限")
        if _SEPARATORS.search(part) or any(_is_control(char) for char in part):
            raise ArchiveFileError("invalid_relative_path", "归档路径包含非法字符")
    return path


def _stream_fingerprint(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(COPY_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


class ArchiveFileManager:
    """Publish verified files under a non-symlink library root."""

    def __init__(self, root: Path) -> None:
        configured_root = Path(root)
        configured_root.mkdir(parents=True, exist_ok=True)
        if configured_root.is_symlink() or not configured_root.is_dir():
            raise ArchiveFileError("unsafe_library_root", "资料库根目录不能是符号链接")
        self.root = configured_root.resolve()
        self.staging_root = self.root / STAGING_DIRECTORY
        self.staging_root.mkdir(mode=0o700, exist_ok=True)
        if self.staging_root.is_symlink() or not self.staging_root.is_dir():
            raise ArchiveFileError("unsafe_staging_root", "归档暂存目录不安全")

    def _absolute(self, relative_path: str) -> Path:
        relative = validate_relative_path(relative_path)
        candidate = self.root.joinpath(*relative.parts)
        resolved_parent = candidate.parent.resolve(strict=False)
        try:
            resolved_parent.relative_to(self.root)
        except ValueError as exc:
            raise ArchiveFileError("path_escape", "归档路径逃出资料库根目录") from exc
        return candidate

    def _ensure_safe_parent(self, destination: Path) -> None:
        try:
            relative_parent = destination.parent.relative_to(self.root)
        except ValueError as exc:
            raise ArchiveFileError("path_escape", "归档父目录逃出资料库根目录") from exc
        current = self.root
        for part in relative_parent.parts:
            current = current / part
            try:
                current.mkdir()
            except FileExistsError:
                pass
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ArchiveFileError("symlink_escape", "归档路径包含符号链接或非目录组件")
            try:
                current.resolve().relative_to(self.root)
            except ValueError as exc:
                raise ArchiveFileError("path_escape", "归档父目录逃出资料库根目录") from exc

    def stage_and_verify(
        self,
        source: Path,
        *,
        expected_sha256: str,
        expected_size: int,
        media_type: str,
        operation_id: str,
    ) -> StagedFile:
        source_path = Path(source)
        if source_path.is_symlink() or not source_path.is_file():
            raise ArchiveFileError("source_unavailable", "待归档 Asset 文件不存在或不安全")
        operation = sanitize_component(
            operation_id, fallback="archive", max_bytes=96
        )
        relative = f"{STAGING_DIRECTORY}/{operation}.pending"
        destination = self._absolute(relative)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        digest = hashlib.sha256()
        size = 0
        header = bytearray()
        try:
            fd = os.open(destination, flags, 0o600)
            with source_path.open("rb") as input_stream, os.fdopen(fd, "wb") as output:
                fd = None
                while True:
                    chunk = input_stream.read(COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    output.write(chunk)
                    if len(header) < 64:
                        header.extend(chunk[: 64 - len(header)])
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError as exc:
            raise ArchiveFileError("staging_conflict", "归档暂存文件已存在") from exc
        except Exception:
            if fd is not None:
                os.close(fd)
            destination.unlink(missing_ok=True)
            raise

        actual_sha256 = digest.hexdigest()
        if size != expected_size or actual_sha256 != expected_sha256:
            destination.unlink(missing_ok=True)
            raise ArchiveFileError("asset_integrity_mismatch", "Asset 大小或 SHA-256 校验失败")
        if not media_signature_matches(media_type, source_path.name, bytes(header)):
            destination.unlink(missing_ok=True)
            raise ArchiveFileError("asset_format_mismatch", "Asset 媒体类型、扩展名或文件签名不一致")
        return StagedFile(
            relative_path=relative,
            sha256=actual_sha256,
            byte_size=size,
            media_type=media_type,
        )

    def publish_no_replace(
        self,
        staged_relative_path: str,
        intended_relative_path: str,
        *,
        sha256: str,
        byte_size: int,
    ) -> PublishedFile:
        staged = self._absolute(staged_relative_path)
        if staged.parent != self.staging_root or staged.is_symlink() or not staged.is_file():
            raise ArchiveFileError("staging_missing", "归档暂存文件不存在或不安全")
        destination = self._absolute(intended_relative_path)
        self._ensure_safe_parent(destination)
        selected = self._select_destination(destination, sha256, byte_size)
        if selected.exists():
            staged.unlink(missing_ok=True)
            return PublishedFile(self._relative(selected), True)
        try:
            os.link(staged, selected, follow_symlinks=False)
        except FileExistsError:
            selected = self._select_destination(destination, sha256, byte_size)
            if not selected.exists():
                raise ArchiveFileError("publish_conflict", "归档目标发生并发冲突")
            staged.unlink(missing_ok=True)
            return PublishedFile(self._relative(selected), True)
        except OSError as exc:
            if exc.errno in {errno.EXDEV, errno.EPERM, errno.ENOTSUP}:
                raise ArchiveFileError("atomic_publish_unavailable", "资料库不支持原子无覆盖发布") from exc
            raise
        staged.unlink(missing_ok=True)
        return PublishedFile(self._relative(selected), False)

    def _select_destination(self, destination: Path, sha256: str, byte_size: int) -> Path:
        if not destination.exists():
            return destination
        if destination.is_symlink() or not destination.is_file():
            raise ArchiveFileError("unsafe_destination", "归档目标不是安全的普通文件")
        if self._matches(destination, sha256, byte_size):
            return destination
        suffix = destination.suffix
        stem = destination.name[: -len(suffix)] if suffix else destination.name
        for width in (12, 16, 24, 64):
            candidate = destination.with_name(f"{stem}-{sha256[:width]}{suffix}")
            validate_relative_path(self._relative(candidate))
            if not candidate.exists():
                return candidate
            if candidate.is_symlink() or not candidate.is_file():
                raise ArchiveFileError("unsafe_destination", "归档冲突目标不安全")
            if self._matches(candidate, sha256, byte_size):
                return candidate
        raise ArchiveFileError("hash_collision", "无法为同名不同内容生成安全文件名")

    @staticmethod
    def _matches(path: Path, sha256: str, byte_size: int) -> bool:
        if path.stat().st_size != byte_size:
            return False
        with path.open("rb") as stream:
            actual_sha256, actual_size = _stream_fingerprint(stream)
        return actual_size == byte_size and actual_sha256 == sha256

    def verify_ready(self, relative_path: str, sha256: str, byte_size: int) -> str:
        try:
            path = self._absolute(relative_path)
        except ArchiveFileError:
            return "missing"
        if not path.exists() or path.is_symlink() or not path.is_file():
            return "missing"
        return "ready" if self._matches(path, sha256, byte_size) else "corrupt"

    def remove_staging(self, relative_path: str) -> None:
        path = self._absolute(relative_path)
        if path.parent != self.staging_root:
            raise ArchiveFileError("invalid_staging_path", "只能清理受控归档暂存文件")
        if path.is_symlink():
            raise ArchiveFileError("unsafe_staging_path", "暂存路径不能是符号链接")
        path.unlink(missing_ok=True)

    def absolute_for_internal_read(self, relative_path: str) -> Path:
        """Resolve a stored safe relative path for trusted internal checks only."""

        return self._absolute(relative_path)

    def _relative(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise ArchiveFileError("path_escape", "归档路径逃出资料库根目录") from exc
        validate_relative_path(relative)
        return relative
