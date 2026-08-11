"""SmartEdu (国家中小学智慧教育平台) resource downloader.

Uses the public CDN detail API to resolve file URLs, then downloads
PDFs directly and videos via ffmpeg (m3u8 → mp4).

Reference: tchMaterial-parser (happycola233) and smartedu-dl-go (hantang).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, TypeAlias
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse
from urllib.error import HTTPError
from urllib.request import Request

from ..config import Settings
from ..downloader import DownloadBatchResult, DownloadItemFailure, DownloadResult

from ..errors import DomainError
from ..sessions import SessionStore
from ..policy import PolicyError, ensure_within_root
from .http_client import urlopen_with_fallback


DownloadReturn: TypeAlias = DownloadResult | DownloadBatchResult

_VIDEO_FORMATS = frozenset({"m3u8", "mp4", "webm", "mov", "mkv"})
_AUDIO_FORMATS = frozenset({"mp3", "m4a", "wav", "ogg", "aac", "flac"})
_DOCUMENT_FORMATS = frozenset({
    "pdf", "epub", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt",
})
_SUBTITLE_FORMATS = frozenset({"srt", "vtt", "ass", "ssa", "lrc"})
_IMAGE_FORMATS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})
_COURSE_TYPES = frozenset({"national_lesson", "quality_course", "thematic_course"})
_FATAL_CODES = frozenset({
    "AUTH_REQUIRED",
    "AUTH_FAILED",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "POLICY_DENIED",
    "NETWORK_BLOCKED",
    "REDIRECT_BLOCKED",
    "JOB_CANCELLED",
    "CANCELLED",
})
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_.-]{0,63}$")
_SAFE_FACT = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")


CDN_BASE = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2"
CDN_SPECIAL = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrs"
STORAGE_PREFIX = "https://r1-ndr-private.ykt.cbern.com.cn"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _resolve_content(url: str) -> tuple[str, str]:
    """Extract content_id and content_type from a smartedu URL."""
    params = parse_qs(urlparse(url, "https").query)

    if "contentId" in params:
        content_id = params["contentId"][0]
        content_type = params.get("contentType", ["assets_document"])[0]
    elif "activityId" in params:
        content_id = params["activityId"][0]
        content_type = "national_lesson"
    elif "courseId" in params:
        content_id = params["courseId"][0]
        content_type = "quality_course"
    elif "resourceId" in params:
        content_id = params["resourceId"][0]
        content_type = params.get("resourceType", ["prepare_sub_type"])[0]
    else:
        # The source URL is an internal input and must never be copied into a
        # structured error or item failure.
        raise DomainError("DOWNLOAD_FAILED", "无法解析 SmartEdu 资源链接")

    return content_id, content_type


def _detail_api_url(content_id: str, content_type: str, url: str) -> str:
    """Build the CDN detail API URL based on content type."""
    if "/tchMaterial/" in url and content_type == "assets_document":
        return f"{CDN_BASE}/resources/tch_material/details/{content_id}.json"
    if content_type == "national_lesson":
        return f"{CDN_BASE}/national_lesson/resources/details/{content_id}.json"
    if content_type == "quality_course":
        return f"{CDN_BASE}/resources/{content_id}.json"
    if content_type == "prepare_sub_type":
        return f"{CDN_BASE}/prepare_sub_type/resources/details/{content_id}.json"
    if content_type == "thematic_course":
        return f"{CDN_SPECIAL}/special_edu/thematic_course/{content_id}/resources/list.json"
    # Generic fallback
    return f"{CDN_BASE}/{content_type}/resources/details/{content_id}.json"


def _fix_storage_url(raw: str) -> str:
    """Convert internal storage path to public CDN URL."""
    if not raw:
        return ""
    if raw.startswith("http"):
        url = raw
    else:
        url = raw.replace("cs_path:${ref-path}", STORAGE_PREFIX)
    # Percent-encode the path to handle Chinese characters and spaces.
    parsed = urlparse(url)
    return urlunparse((
        parsed.scheme, parsed.netloc,
        quote(parsed.path, safe="/"),
        parsed.params, parsed.query, parsed.fragment,
    ))


def _bounded_text(value: Any, limit: int = 160) -> str:
    """Return bounded source text for in-memory selection only."""

    if value is None:
        return ""
    return str(value).strip()[:limit]


def _normalize_format(value: Any) -> str:
    raw = _bounded_text(value, 64).casefold()
    if not raw:
        return ""
    aliases = {
        "application/x-mpegurl": "m3u8",
        "application/vnd.apple.mpegurl": "m3u8",
        "mpegurl": "m3u8",
        "jpeg": "jpg",
    }
    if raw in aliases:
        return aliases[raw]
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return aliases.get(raw, raw.lstrip("."))


def _safe_fact(value: Any, fallback: str = "") -> str:
    """Keep only low-risk provider facts in result metadata."""

    candidate = _bounded_text(value, 96)
    if _SAFE_FACT.fullmatch(candidate):
        return candidate
    return fallback


def _safe_relation_key(value: Any) -> str:
    return _safe_fact(value, "root")


def _stable_digest(*parts: Any) -> str:
    payload = "\x1f".join(_bounded_text(part, 240) for part in parts)
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:20]


def _stable_provider_item_key(
    relation_key: str,
    item: dict[str, Any],
    parent: dict[str, Any],
    fmt: str,
    flag: str,
    url: str,
    seen: set[str],
) -> str:
    """Build a stable opaque provider key without exposing a source URL."""

    explicit = ""
    for candidate in (
        item.get("ti_item_id"),
        item.get("item_id"),
        item.get("id"),
        item.get("resource_id"),
        item.get("resourceId"),
    ):
        text = _safe_fact(candidate)
        if text:
            explicit = text
            break
    if explicit:
        suffix = explicit
    else:
        suffix = f"item-{_stable_digest(relation_key, fmt, flag, item.get('ti_size'), url)}"
    base_key = f"smartedu:{_safe_relation_key(relation_key)}:{suffix}"
    key = base_key
    if key in seen:
        collision = _stable_digest(parent.get("id"), item.get("id"), fmt, flag, url)
        key = f"{base_key}-{collision}"
        ordinal = 2
        while key in seen:
            key = f"{base_key}-{collision}-{ordinal}"
            ordinal += 1
    seen.add(key)
    return key


def _source_group_key(
    relation_key: str, parent: dict[str, Any], label: str, source_order: int
) -> str:
    explicit = ""
    for candidate in (
        parent.get("resource_id"),
        parent.get("resourceId"),
        parent.get("id"),
        parent.get("content_id"),
    ):
        text = _safe_fact(candidate)
        if text:
            explicit = text
            break
    if explicit:
        return f"smartedu-group:{_safe_relation_key(relation_key)}:{explicit}"
    # Without a provider resource ID, keep variants from the same named
    # source item together while still making the fallback deterministic.
    return f"smartedu-group:{_safe_relation_key(relation_key)}:{_stable_digest(label, parent.get('title'), parent.get('global_title'))}"


def _safe_item_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return source facts safe to persist alongside a download result."""

    metadata: dict[str, Any] = {
        "provider": "smartedu",
        "relation_key": _safe_relation_key(candidate.get("relation_key")),
        "source_order": int(candidate.get("source_order") or 0),
        "format": _safe_fact(candidate.get("format"), "unknown"),
    }
    flag = _safe_fact(candidate.get("ti_file_flag"))
    if flag:
        metadata["ti_file_flag"] = flag
    source_type = _safe_fact(candidate.get("source_type"))
    if source_type:
        metadata["source_type"] = source_type
    group_key = _safe_fact(candidate.get("source_group_key"))
    if group_key:
        metadata["source_group_key"] = group_key
    return metadata


def _find_files(
    data: dict[str, Any], *, source_order_start: int = 0
) -> list[dict[str, Any]]:
    """Scan detail JSON while retaining source relation and order facts.

    ``url`` is an internal-only field.  It is intentionally absent from the
    candidate metadata and is never copied to a failure message.
    """
    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _extract_ti_items(
        obj: dict[str, Any], relation_key: str = "root", label: str = ""
    ) -> None:
        for item in obj.get("ti_items") or []:
            if not isinstance(item, dict):
                continue
            if _normalize_format(item.get("ti_format")) == "folder":
                continue
            flag = _bounded_text(item.get("ti_file_flag") or item.get("file_flag"))
            raw_format = (
                item.get("ti_format")
                or item.get("lc_ti_format")
                or item.get("format")
            )
            fmt = _normalize_format(raw_format)
            if not fmt:
                fmt = _normalize_format(item.get("mime_type") or item.get("media_type"))
            if "m3u8" in flag.casefold():
                fmt = "m3u8"
            elif not fmt and "mp3" in flag.casefold():
                fmt = "mp3"
            raw_url = item.get("ti_storage") or ""
            if not raw_url and item.get("ti_storages"):
                storages = item["ti_storages"]
                if isinstance(storages, (list, tuple)):
                    raw_url = storages[0] if storages else ""
                elif isinstance(storages, str):
                    raw_url = storages
            url = _fix_storage_url(str(raw_url))
            if not url or (
                fmt not in _VIDEO_FORMATS
                and fmt not in _AUDIO_FORMATS
                and fmt not in _DOCUMENT_FORMATS
                and fmt not in _SUBTITLE_FORMATS
                and fmt not in _IMAGE_FORMATS
                and not item.get("ti_is_source_file")
                and not flag
            ):
                continue
            source_order = source_order_start + len(results)
            title_data = (
                item.get("global_title")
                or item.get("title")
                or obj.get("global_title")
                or obj.get("title")
                or label
            )
            if isinstance(title_data, dict):
                title_data = title_data.get("zh-CN") or title_data.get("en") or label
            source_type = (
                item.get("resource_type")
                or item.get("resource_type_code")
                or item.get("ti_resource_type")
                or obj.get("resource_type")
                or obj.get("resource_type_code")
                or obj.get("resource_type_code_name")
            )
            candidate = {
                "url": url,
                "format": fmt,
                "raw_format": _bounded_text(raw_format, 96),
                "size": _coerce_size(item.get("ti_size") or item.get("size")),
                "title": _bounded_text(title_data, 120),
                "flag": flag,
                "ti_file_flag": flag,
                "relation_key": _safe_relation_key(relation_key),
                "source_order": source_order,
                "source_type": _bounded_text(source_type, 96),
                "explicit_role": _bounded_text(
                    item.get("role") or item.get("asset_role") or item.get("ti_role"), 64
                ),
            }
            candidate["item_key"] = _stable_provider_item_key(
                relation_key,
                item,
                obj,
                fmt,
                flag,
                url,
                seen_keys,
            )
            candidate["provider_item_key"] = candidate["item_key"]
            candidate["relation"] = candidate["relation_key"]
            candidate["source_index"] = source_order
            candidate["source_group_key"] = _source_group_key(
                relation_key, obj, label, source_order
            )
            candidate["metadata"] = _safe_item_metadata(candidate)
            results.append(candidate)

    # Direct files
    _extract_ti_items(data, relation_key="root")

    # Sub-resources in relations, preserving the JSON mapping and list order.
    relations = data.get("relations") or {}
    if isinstance(relations, dict):
        for rel_key, rel_items in relations.items():
            if not isinstance(rel_items, list):
                continue
            for item in rel_items:
                if isinstance(item, dict):
                    _extract_ti_items(item, relation_key=str(rel_key), label=str(rel_key))

    return results


def _coerce_size(value: Any) -> int:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(size, 0)


def _pick_best_file(files: list[dict[str, Any]], content_type: str = "", allow_video: bool = True) -> dict[str, Any] | None:
    """Pick the most valuable downloadable file.

    For courses (national_lesson, quality_course): video first, then PDF.
    For textbooks/documents: PDF first.
    When *allow_video* is False, skip m3u8/mp4 (e.g. no auth token).
    """
    if not files:
        return None

    # Find best m3u8 (prefer 720p).
    best_m3u8 = None
    if allow_video:
        for f in files:
            if f["format"] == "m3u8" and "720p" in f.get("flag", ""):
                best_m3u8 = f
                break
        if not best_m3u8:
            for f in files:
                if f["format"] == "m3u8":
                    best_m3u8 = f
                    break

    is_course = content_type in ("national_lesson", "quality_course", "thematic_course")

    if is_course and allow_video:
        priority = [("m3u8", best_m3u8), ("mp4", None), ("pdf", None), ("mp3", None)]
    else:
        priority = [("pdf", None), ("mp4", None) if allow_video else ("_skip", None),
                    ("epub", None), ("m3u8", best_m3u8), ("mp3", None)]

    for fmt, specific in priority:
        if specific:
            return specific
        if fmt == "_skip":
            continue
        for f in files:
            if f["format"] == fmt:
                return f

    return files[0]


def _flag_text(candidate: dict[str, Any]) -> str:
    return str(candidate.get("ti_file_flag") or candidate.get("flag") or "").casefold()


def _explicit_role(candidate: dict[str, Any]) -> str:
    """Map only provider-declared role facts to the fixed asset vocabulary."""

    role = str(candidate.get("explicit_role") or "").casefold().strip()
    aliases = {
        "primary": "primary",
        "subtitle": "subtitle",
        "caption": "subtitle",
        "cover": "cover",
        "metadata": "metadata",
        "transcript": "transcript",
        "attachment": "attachment",
        "companion": "companion",
    }
    if role in aliases:
        return aliases[role]
    flag = _flag_text(candidate)
    relation_key = str(candidate.get("relation_key") or "").casefold()
    source_type = str(candidate.get("source_type") or "").casefold()
    if any(marker in flag for marker in ("cover", "thumbnail", "poster", "封面")) or relation_key in {"cover", "covers"} or source_type in {"cover", "thumbnail"}:
        return "cover"
    if any(marker in flag for marker in ("subtitle", "caption", "subtitles", "字幕")):
        return "subtitle"
    if any(marker in flag for marker in ("transcript", "transcription", "讲稿")):
        return "transcript"
    if "metadata" in flag or flag in {"meta", "json"}:
        return "metadata"
    return ""


def _is_cover(candidate: dict[str, Any]) -> bool:
    return _explicit_role(candidate) == "cover"


def _is_video(candidate: dict[str, Any]) -> bool:
    fmt = str(candidate.get("format") or "").casefold()
    if fmt in _VIDEO_FORMATS:
        return True
    flag = _flag_text(candidate)
    source_type = str(candidate.get("source_type") or "").casefold()
    relation_key = str(candidate.get("relation_key") or "").casefold()
    return (
        "m3u8" in flag
        or source_type in {"video", "course_video", "lesson_video"}
        or relation_key in {"video", "videos", "course_video", "course_videos"}
    )


def _video_quality(candidate: dict[str, Any]) -> tuple[int, int]:
    """Rank explicit provider quality flags, then keep source order stable."""

    flag = _flag_text(candidate)
    quality = 0
    for marker, score in (("2160p", 4), ("1080p", 3), ("720p", 2), ("480p", 1), ("360p", 0)):
        if marker in flag:
            quality = score
            break
    return quality, -int(candidate.get("source_order") or 0)


def _is_content_candidate(candidate: dict[str, Any]) -> bool:
    fmt = str(candidate.get("format") or "").casefold()
    if _is_cover(candidate):
        return False
    if fmt in _AUDIO_FORMATS or fmt in _SUBTITLE_FORMATS:
        return False
    if _explicit_role(candidate) in {"metadata", "transcript"}:
        return False
    return True


def _select_course_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select one quality variant per source item and retain companions."""

    if not files:
        return []
    selected: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in files:
        # A thumbnail/cover is an explicit companion and must not be mistaken
        # for the course primary, but it remains available for the bundle.
        if _is_video(candidate):
            groups.setdefault(str(candidate.get("source_group_key") or ""), []).append(candidate)
        else:
            selected.append(candidate)
    for group in groups.values():
        selected.append(max(group, key=_video_quality))
    return sorted(selected, key=lambda item: int(item.get("source_order") or 0))


def _role_for_candidate(
    candidate: dict[str, Any], *, primary_key: str, content_type: str
) -> str:
    if candidate.get("item_key") == primary_key:
        return "primary"
    explicit = _explicit_role(candidate)
    if explicit:
        return explicit
    relation_key = str(candidate.get("relation_key") or "").casefold()
    fmt = str(candidate.get("format") or "").casefold()
    if "audio" in relation_key or fmt in _AUDIO_FORMATS:
        return "companion"
    if fmt in _SUBTITLE_FORMATS:
        return "subtitle"
    if fmt == "json":
        return "metadata"
    return "attachment"


def _primary_candidate(
    files: list[dict[str, Any]], content_type: str
) -> dict[str, Any] | None:
    if not files:
        return None
    if content_type in _COURSE_TYPES:
        videos = [candidate for candidate in files if _is_video(candidate) and not _is_cover(candidate)]
        if videos:
            return max(videos, key=_video_quality)
        content = [candidate for candidate in files if _is_content_candidate(candidate)]
        if content:
            return min(content, key=lambda item: int(item.get("source_order") or 0))
        return min(files, key=lambda item: int(item.get("source_order") or 0))
    return _pick_best_file(files, content_type, allow_video=True)


def _safe_error_code(value: Any, default: str = "DOWNLOAD_FAILED") -> str:
    code = str(value or default).upper().strip()
    return code if _SAFE_CODE.fullmatch(code) else default


def _safe_error_message(code: str) -> str:
    messages = {
        "AUTH_REQUIRED": "下载需要认证",
        "AUTH_FAILED": "下载认证失败",
        "UNAUTHORIZED": "下载认证失败",
        "FORBIDDEN": "下载被拒绝",
        "POLICY_DENIED": "下载被策略阻止",
        "NETWORK_BLOCKED": "网络请求被阻止",
        "REDIRECT_BLOCKED": "重定向被策略阻止",
        "JOB_CANCELLED": "下载已取消",
        "CANCELLED": "下载已取消",
        "CONTENT_VALIDATION_FAILED": "下载内容未通过校验",
        "RELATION_AUDIO_LOOKUP_FAILED": "伴随音频查询失败",
    }
    return messages.get(code, "文件下载失败")


def _exception_code(exc: BaseException) -> str:
    if isinstance(exc, DomainError):
        return _safe_error_code(exc.code)
    if isinstance(exc, HTTPError):
        if exc.code in {401, 403}:
            return "AUTH_REQUIRED"
        if exc.code in {407, 451}:
            return "POLICY_DENIED"
    if isinstance(exc, PolicyError):
        return "POLICY_DENIED"
    return "DOWNLOAD_FAILED"


def _is_fatal_code(code: str) -> bool:
    return code in _FATAL_CODES or code.startswith("AUTH_") or code.startswith("POLICY_")


def _make_item_failure(
    candidate: dict[str, Any], code: str, *, required: bool, role: str | None = None
) -> DownloadItemFailure:
    safe_code = _safe_error_code(code)
    metadata = dict(candidate.get("metadata") or {})
    metadata["required"] = bool(required)
    payloads = (
        {
            "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
            "code": safe_code,
            "message": _safe_error_message(safe_code),
            "role": role,
            "retryable": safe_code not in _FATAL_CODES,
            "required": bool(required),
            "details": metadata,
            "metadata": metadata,
        },
        {
            "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
            "code": safe_code,
            "message": _safe_error_message(safe_code),
            "role": role,
            "retryable": safe_code not in _FATAL_CODES,
            "required": bool(required),
        },
        {
            "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
            "code": safe_code,
            "message": _safe_error_message(safe_code),
            "role": role,
            "retryable": safe_code not in _FATAL_CODES,
        },
    )
    for payload in payloads:
        try:
            return DownloadItemFailure(**payload)  # type: ignore[arg-type]
        except TypeError:
            continue
    return DownloadItemFailure(  # type: ignore[call-arg]
        str(candidate.get("item_key") or "smartedu:unknown"),
        safe_code,
        _safe_error_message(safe_code),
    )


def _make_batch_result(
    results: list[DownloadResult], failures: list[DownloadItemFailure]
) -> DownloadBatchResult:
    """Construct B's envelope while tolerating its final field alias."""

    result_values = tuple(results)
    failure_values = tuple(failures)
    for result_field in ("results", "items", "downloads", "successes"):
        try:
            return DownloadBatchResult(
                **{result_field: result_values, "failures": failure_values}
            )  # type: ignore[arg-type]
        except TypeError:
            continue
    try:
        return DownloadBatchResult(result_values, failure_values)  # type: ignore[call-arg]
    except TypeError as exc:  # pragma: no cover - protects an incompatible B API
        raise TypeError("DownloadBatchResult interface is incompatible") from exc


def _make_download_result(
    path: Path,
    byte_size: int,
    media_type: str,
    sha256: str,
    filename: str,
    candidate: dict[str, Any],
    *,
    role: str,
    required: bool,
) -> DownloadResult:
    metadata = dict(candidate.get("metadata") or {})
    payload = {
        "path": path,
        "byte_size": byte_size,
        "media_type": media_type,
        "sha256": sha256,
        "filename": filename,
        "role": role,
        "required": bool(required),
        "item_key": str(candidate.get("item_key") or "smartedu:unknown"),
        "metadata": metadata,
    }
    try:
        return DownloadResult(**payload)  # type: ignore[arg-type]
    except TypeError:
        # Keep old providers/test fixtures usable until downloader.py's
        # optional fields are present.
        return DownloadResult(path, byte_size, media_type, sha256, filename)


def _safe_destination_name(
    title: str, fmt: str, used_names: set[str], source_order: int
) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", title).strip("-._")[:80] or "resource"
    suffix = {
        "m3u8": ".mp4",
        "mp4": ".mp4",
        "webm": ".webm",
        "mov": ".mov",
        "mp3": ".mp3",
        "m4a": ".m4a",
        "wav": ".wav",
        "ogg": ".ogg",
        "pdf": ".pdf",
        "epub": ".epub",
        "doc": ".doc",
        "docx": ".docx",
        "ppt": ".ppt",
        "pptx": ".pptx",
        "srt": ".srt",
        "vtt": ".vtt",
        "jpg": ".jpg",
        "jpeg": ".jpg",
        "png": ".png",
        "json": ".json",
    }.get(fmt, ".bin")
    base = cleaned if cleaned.lower().endswith(suffix) else f"{cleaned}{suffix}"
    name = base
    if name in used_names:
        stem = Path(base).stem
        name = f"{stem}-{source_order + 1}{suffix}"
        while name in used_names:
            name = f"{stem}-{source_order + 1}-{len(used_names)}{suffix}"
    used_names.add(name)
    return name


def _safe_fatal_error(exc: BaseException) -> DomainError:
    code = _exception_code(exc)
    retryable = isinstance(exc, DomainError) and bool(exc.retryable)
    return DomainError(code, _safe_error_message(code), retryable=retryable)


def _smartedu_headers(token: str = "") -> dict[str, str]:
    """Build auth headers for smartedu CDN requests.

    Uses only x-nd-auth header (matching smartedu-dl-go). Without a token,
    uses dummy auth that works for public resources.
    """
    t = token or "0"
    return {
        "User-Agent": UA,
        "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/",
        "x-nd-auth": f'MAC id="{t}",nonce="0",mac="0"',
    }


def _stream_download(
    url: str, dest: Path, cancel_event: threading.Event,
    token: str = "",
) -> int:
    """Download a direct file (PDF, MP3, etc.).

    Tries x-nd-auth header first, then ?accessToken= query param as fallback.
    """
    request = Request(url, headers=_smartedu_headers(token))
    written = 0
    with urlopen_with_fallback(request, timeout=120) as response:
        with dest.open("wb") as f:
            while True:
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                f.write(chunk)
    return written


def _get_decryption_key(key_url: str, token: str) -> bytes:
    """Obtain the AES decryption key for video segments.

    Implements the SmartEdu key derivation algorithm (ported from
    smartedu-dl-go):
      1. GET {keyURL}/signs → nonce
      2. sign = MD5(nonce + keyID)[:16]
      3. GET {keyURL}?nonce={nonce}&sign={sign} → base64 encrypted key
      4. AES-ECB decrypt with sign as key → raw decryption key
    """
    headers = _smartedu_headers(token)

    # Extract keyID from URL (last path segment).
    key_id = key_url.rstrip("/").rsplit("/", 1)[-1]

    # 1. Get nonce.
    signs_url = f"{key_url}/signs"
    req = Request(signs_url, headers=headers)
    with urlopen_with_fallback(req, timeout=15) as resp:
        signs_data = json.loads(resp.read().decode("utf-8", "replace"))
    nonce = signs_data.get("nonce")
    if not nonce:
        raise DomainError("DOWNLOAD_FAILED", "密钥服务未返回 nonce")

    # 2. Compute sign = MD5(nonce + keyID)[:16].
    sign = hashlib.md5(f"{nonce}{key_id}".encode()).hexdigest()[:16]

    # 3. Get encrypted key.
    key_req_url = f"{key_url}?nonce={nonce}&sign={sign}"
    req2 = Request(key_req_url, headers=headers)
    with urlopen_with_fallback(req2, timeout=15) as resp2:
        key_data = json.loads(resp2.read().decode("utf-8", "replace"))
    encrypted_key_b64 = key_data.get("key")
    if not encrypted_key_b64:
        raise DomainError("DOWNLOAD_FAILED", "密钥服务未返回 key")

    # 4. AES-ECB decrypt.
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    encrypted_key = base64.b64decode(encrypted_key_b64)
    cipher = AES.new(sign.encode()[:16], AES.MODE_ECB)
    return unpad(cipher.decrypt(encrypted_key), 16)


def _decrypt_segment(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-CBC decrypt a video segment."""
    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(data)
    # PKCS7 unpad
    pad_len = decrypted[-1]
    if 0 < pad_len <= 16:
        decrypted = decrypted[:-pad_len]
    return decrypted


def _download_m3u8(
    url: str, dest: Path, cancel_event: threading.Event,
    token: str = "",
) -> int:
    """Download HLS video: parse m3u8, download segments, decrypt, merge.

    No ffmpeg needed — implements SmartEdu's custom key derivation and
    AES-CBC segment decryption in pure Python (requires pycryptodome).
    """
    from urllib.parse import urljoin

    # 1. Download m3u8.
    full_url = f"{url}?accessToken={token}" if token and "?" not in url else url
    request = Request(full_url, headers={
        "User-Agent": UA,
        "Referer": "https://basic.smartedu.cn/",
    })
    with urlopen_with_fallback(request, timeout=20) as resp:
        m3u8_text = resp.read().decode("utf-8", "replace")

    # 2. Parse m3u8: extract key info and segment URLs.
    base = url.rsplit("/", 1)[0] + "/"
    key_url = ""
    iv = b"\x00" * 16  # Default IV (IV=0 in m3u8)
    segments: list[str] = []

    for line in m3u8_text.split("\n"):
        line = line.strip()
        if line.startswith("#EXT-X-KEY:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                key_url = uri_match.group(1)
            iv_match = re.search(r"IV=0x([0-9a-fA-F]+)", line)
            if iv_match:
                iv_hex = iv_match.group(1)
                iv = bytes.fromhex(iv_hex.zfill(32))
        elif line and not line.startswith("#"):
            seg_url = urljoin(base, line)
            segments.append(seg_url)

    if not segments:
        raise DomainError("DOWNLOAD_FAILED", "m3u8 无分段")

    # 3. Get decryption key (if encrypted).
    key = None
    if key_url:
        key = _get_decryption_key(key_url, token)

    # 4. Download + decrypt + merge segments.
    seg_headers = _smartedu_headers(token)

    try:
        with dest.open("wb") as out:
            for i, seg_url in enumerate(segments):
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")

                req = Request(seg_url, headers=seg_headers)
                with urlopen_with_fallback(req, timeout=60) as resp:
                    seg_data = resp.read()

                if key:
                    seg_data = _decrypt_segment(seg_data, key, iv)

                out.write(seg_data)

        return dest.stat().st_size
    except DomainError:
        raise
    except (HTTPError, PolicyError) as exc:
        code = _exception_code(exc)
        raise DomainError(code, _safe_error_message(code), retryable=False) from exc
    except Exception:
        # Do not leak a segment URL, response body, or credential-bearing
        # request details through the provider boundary.
        raise DomainError("DOWNLOAD_FAILED", "视频分段下载失败", retryable=True)


class SmartEduDownloader:
    """Download resources from SmartEdu via the public CDN detail API.

    Handles textbooks (PDF), course videos (m3u8→mp4), documents, and audio.
    Access token is optional — most resources are publicly downloadable.
    """

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.settings = settings

    def download(
        self,
        resource: dict[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadReturn:
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")

        source_url = str(resource.get("source_url") or "")
        title = _bounded_text(resource.get("title") or "smartedu_resource", 120)
        content_id, content_type = _resolve_content(source_url)

        session_data = self.session_store.get_session_data("smartedu")
        token = ""
        if session_data:
            tokens = session_data.get("tokens") or {}
            raw_token = tokens.get("accessToken") or ""
            if raw_token:
                raw_token = str(raw_token)
                token = raw_token[7:] if raw_token.lower().startswith("bearer ") else raw_token

        # Detail lookup is acquisition-wide: without it there is no safe item
        # identity to attach a partial failure to.
        api_url = _detail_api_url(content_id, content_type, source_url)
        request = Request(api_url, headers=_smartedu_headers(token))
        try:
            with urlopen_with_fallback(request, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            raise _safe_fatal_error(exc) from exc
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        if not isinstance(data, dict):
            raise DomainError("DOWNLOAD_FAILED", "资源详情格式无效", retryable=True)

        files = _find_files(data)
        lookup_failures: list[DownloadItemFailure] = []

        # Textbooks expose relation audio through a second endpoint.  The
        # endpoint failure is retained as a non-required item failure; an
        # authentication, policy, or cancellation failure still aborts the
        # whole acquisition.
        if content_type == "assets_document":
            audio_api = f"{CDN_SPECIAL}/resources/{content_id}/relation_audios.json"
            try:
                audio_req = Request(audio_api, headers=_smartedu_headers(token))
                with urlopen_with_fallback(audio_req, timeout=10) as audio_resp:
                    audios = json.loads(audio_resp.read().decode("utf-8", "replace"))
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                if isinstance(audios, dict):
                    audios = audios.get("resources") or audios.get("data") or []
                if not isinstance(audios, list):
                    raise ValueError("invalid relation audio response")
                files.extend(
                    _find_files(
                        {"relations": {"relation_audios": audios}},
                        source_order_start=len(files),
                    )
                )
            except Exception as exc:
                code = _exception_code(exc)
                if cancel_event.is_set():
                    code = "JOB_CANCELLED"
                if _is_fatal_code(code):
                    raise _safe_fatal_error(exc) from exc
                lookup_candidate = {
                    "item_key": "smartedu:relation_audios:lookup",
                    "relation_key": "relation_audios",
                    "source_order": len(files),
                    "format": "mp3",
                    "ti_file_flag": "relation_lookup",
                    "metadata": {
                        "provider": "smartedu",
                        "relation_key": "relation_audios",
                        "source_order": len(files),
                        "format": "mp3",
                    },
                }
                lookup_failures.append(
                    _make_item_failure(lookup_candidate, "RELATION_AUDIO_LOOKUP_FAILED", required=False)
                )

        if not files:
            if lookup_failures:
                return _make_batch_result([], lookup_failures)
            raise DomainError("DOWNLOAD_FAILED", "该资源无可下载文件", retryable=False)

        if content_type in _COURSE_TYPES:
            selected = _select_course_files(files)
        else:
            primary_source = [
                candidate
                for candidate in files
                if str(candidate.get("relation_key") or "") != "relation_audios"
            ]
            primary = _pick_best_file(primary_source or files, content_type, allow_video=True)
            selected = [primary] if primary is not None else []
            # An explicitly declared cover remains useful as an attachment.
            selected.extend(
                candidate
                for candidate in primary_source
                if _is_cover(candidate) and candidate is not primary
            )
            if content_type == "assets_document":
                selected.extend(
                    candidate
                    for candidate in files
                    if str(candidate.get("relation_key") or "") == "relation_audios"
                    and candidate is not primary
                )
        selected = sorted(
            {str(item.get("item_key")): item for item in selected}.values(),
            key=lambda item: int(item.get("source_order") or 0),
        )
        if not selected:
            if lookup_failures:
                return _make_batch_result([], lookup_failures)
            raise DomainError("DOWNLOAD_FAILED", "未找到可下载文件", retryable=False)

        primary = _primary_candidate(selected, content_type)
        if primary is None:
            raise DomainError("DOWNLOAD_FAILED", "未找到可用主资源", retryable=False)
        primary_key = str(primary.get("item_key") or "")

        job_dir = self.settings.jobs_dir / job_id
        created_paths: list[Path] = []
        try:
            job_dir.mkdir(parents=True, exist_ok=True)
            ensure_within_root(job_dir, self.settings.jobs_dir)
        except Exception as exc:
            raise _safe_fatal_error(exc) from exc

        results: list[DownloadResult] = []
        failures = list(lookup_failures)
        used_names: set[str] = set()
        for candidate in selected:
            required = str(candidate.get("item_key") or "") == primary_key
            role = _role_for_candidate(candidate, primary_key=primary_key, content_type=content_type)
            destination = job_dir / _safe_destination_name(
                str(candidate.get("title") or title),
                str(candidate.get("format") or "bin"),
                used_names,
                int(candidate.get("source_order") or 0),
            )
            try:
                if cancel_event.is_set():
                    raise DomainError("JOB_CANCELLED", "下载已取消")
                ensure_within_root(destination, self.settings.jobs_dir)
                destination.unlink(missing_ok=True)
                fmt = str(candidate.get("format") or "").casefold()
                if fmt == "m3u8":
                    _download_m3u8(str(candidate["url"]), destination, cancel_event, token)
                    media_type = "video/mp4"
                else:
                    _stream_download(
                        str(candidate["url"]), destination, cancel_event, token
                    )
                    media_type = {
                        "pdf": "application/pdf",
                        "mp3": "audio/mpeg",
                        "m4a": "audio/mp4",
                        "mp4": "video/mp4",
                        "webm": "video/webm",
                        "epub": "application/epub+zip",
                        "srt": "application/x-subrip",
                        "vtt": "text/vtt",
                        "jpg": "image/jpeg",
                        "png": "image/png",
                    }.get(fmt, "application/octet-stream")
                byte_size = destination.stat().st_size
                if byte_size <= 0:
                    raise DomainError("CONTENT_VALIDATION_FAILED", "下载内容为空")
                digest = hashlib.sha256()
                with destination.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        digest.update(chunk)
                created_paths.append(destination)
                results.append(
                    _make_download_result(
                        destination,
                        byte_size,
                        media_type,
                        digest.hexdigest(),
                        destination.name,
                        candidate,
                        role=role,
                        required=required,
                    )
                )
            except Exception as exc:
                destination.unlink(missing_ok=True)
                code = "JOB_CANCELLED" if cancel_event.is_set() else _exception_code(exc)
                if _is_fatal_code(code):
                    for path in created_paths:
                        path.unlink(missing_ok=True)
                    raise _safe_fatal_error(
                        DomainError(code, _safe_error_message(code))
                    ) from exc
                failures.append(
                    _make_item_failure(candidate, code, required=required, role=role)
                )

        if failures or len(results) > 1:
            return _make_batch_result(results, failures)
        if results:
            return results[0]
        return _make_batch_result([], failures)
