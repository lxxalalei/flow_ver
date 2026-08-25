"""Pure SmartEdu resource identity, relation, and file-selection facts.

This module contains deterministic platform rules shared by inspection,
expansion, and download. It deliberately performs no network or filesystem IO.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse, urlunparse

from ..errors import DomainError


_VIDEO_FORMATS = frozenset({"m3u8", "mp4", "webm", "mov", "mkv"})
_AUDIO_FORMATS = frozenset({"mp3", "m4a", "wav", "ogg", "aac", "flac"})
_DOCUMENT_FORMATS = frozenset({
    "pdf", "epub", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt",
})
_SUBTITLE_FORMATS = frozenset({"srt", "vtt", "ass", "ssa", "lrc"})
_IMAGE_FORMATS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})
_COURSE_TYPES = frozenset({"national_lesson", "quality_course", "thematic_course"})
_ACTIVE_PRIMARY_FORMATS = frozenset({"pdf", "mp4", "mp3", "m4a", "m3u8"})

CDN_BASE = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2"
CDN_SPECIAL = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrs"
STORAGE_PREFIX = "https://r1-ndr-private.ykt.cbern.com.cn"


def _text(value: Any) -> str:
    """Preserve a provider text fact; do not impose project-invented truncation."""

    if value is None:
        return ""
    return str(value).strip()


def _bounded_text(value: Any, limit: int = 160) -> str:
    """Legacy internal name; provider facts are no longer silently truncated."""

    del limit
    return _text(value)


def _fact(value: Any, fallback: str = "") -> str:
    """Return a provider fact unless it is empty or contains control bytes."""

    text = _text(value)
    if not text:
        return fallback
    if any(ord(char) < 0x20 and char not in "\t\r\n" for char in text):
        return fallback
    return text


def _component(value: Any) -> str:
    return quote(_fact(value), safe="")


def _smartedu_representation_id(
    resource: Mapping[str, Any], candidate: Mapping[str, Any]
) -> str:
    """Build a transparent deterministic id from the facts used for routing."""

    file_key = _smartedu_file_key_from_resource(resource)
    identity = file_key or _fact(resource.get("source_url")) or _fact(resource.get("resource_id"))
    item_key = _fact(candidate.get("item_key"))
    fmt = _fact(candidate.get("format")).casefold()
    return f"repr_smartedu:v1:{_component(identity)}:{_component(item_key)}:{_component(fmt)}"


def _resolve_content(url: str) -> tuple[str, str]:
    """Extract content_id and content_type from a SmartEdu URL."""

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
    return f"{CDN_BASE}/{content_type}/resources/details/{content_id}.json"


def _fix_storage_url(raw: str) -> str:
    """Convert an internal storage path to a public CDN URL."""

    if not raw:
        return ""
    url = raw if raw.startswith("http") else raw.replace("cs_path:${ref-path}", STORAGE_PREFIX)
    parsed = urlparse(url)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        quote(parsed.path, safe="/"),
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


def _normalize_format(value: Any) -> str:
    raw = _text(value).casefold()
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


def _safe_relation_key(value: Any) -> str:
    return _fact(value, "root")


def _provider_item_id(item: Mapping[str, Any]) -> str:
    """Return only a platform-provided item identity, never a locator."""

    for candidate in (
        item.get("ti_item_id"),
        item.get("item_id"),
        item.get("id"),
        item.get("resource_id"),
        item.get("resourceId"),
    ):
        text = _fact(candidate)
        if text:
            return text
    return ""


def _provider_group_id(parent: Mapping[str, Any]) -> str:
    for candidate in (
        parent.get("resource_id"),
        parent.get("resourceId"),
        parent.get("id"),
        parent.get("content_id"),
    ):
        text = _fact(candidate)
        if text:
            return text
    return ""


def _provider_item_key(
    relation_key: str,
    item: Mapping[str, Any],
    source_order: int,
    seen: set[str],
) -> str:
    """Build an in-detail correlation key without hashing URLs or source text."""

    native = _provider_item_id(item)
    suffix = f"native:{_component(native)}" if native else f"order:{source_order}"
    base = f"smartedu-item:{_component(_safe_relation_key(relation_key))}:{suffix}"
    key = base
    ordinal = 2
    while key in seen:
        key = f"{base}:{ordinal}"
        ordinal += 1
    seen.add(key)
    return key


def _source_group_key(
    relation_key: str,
    parent: Mapping[str, Any],
    group_order: int,
) -> str:
    """Group quality variants of one provider source item for this detail read."""

    explicit = _provider_group_id(parent)
    if explicit:
        suffix = f"native:{_component(explicit)}"
    else:
        suffix = f"order:{group_order}"
    return f"smartedu-group:{_component(_safe_relation_key(relation_key))}:{suffix}"


def _safe_item_metadata(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return non-secret provider facts without arbitrary character/length filters."""

    metadata: dict[str, Any] = {
        "provider": "smartedu",
        "relation_key": _safe_relation_key(candidate.get("relation_key")),
        "source_order": int(candidate.get("source_order") or 0),
        "format": _fact(candidate.get("format"), "unknown"),
    }
    for source_key, output_key in (
        ("ti_file_flag", "ti_file_flag"),
        ("source_type", "source_type"),
        ("source_group_key", "source_group_key"),
    ):
        value = _fact(candidate.get(source_key))
        if value:
            metadata[output_key] = value
    return metadata


def _find_files(
    data: dict[str, Any], *, source_order_start: int = 0
) -> list[dict[str, Any]]:
    """Scan detail JSON while retaining source relation and order facts.

    ``url`` remains internal-only. Signed storage URLs are never used as a
    logical child resource identity.
    """

    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _extract_ti_items(
        obj: dict[str, Any], relation_key: str = "root", label: str = ""
    ) -> None:
        group_order = source_order_start + len(results)
        group_key = _source_group_key(relation_key, obj, group_order)
        for item in obj.get("ti_items") or []:
            if not isinstance(item, dict):
                continue
            if _normalize_format(item.get("ti_format")) == "folder":
                continue
            flag = _text(item.get("ti_file_flag") or item.get("file_flag"))
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
                "raw_format": _text(raw_format),
                "size": _coerce_size(item.get("ti_size") or item.get("size")),
                "title": _text(title_data),
                "flag": flag,
                "ti_file_flag": flag,
                "relation_key": _safe_relation_key(relation_key),
                "source_order": source_order,
                "source_type": _text(source_type),
                "explicit_role": _text(
                    item.get("role") or item.get("asset_role") or item.get("ti_role")
                ),
                "provider_item_id": _provider_item_id(item),
                "provider_group_id": _provider_group_id(obj),
                "source_group_key": group_key,
            }
            candidate["item_key"] = _provider_item_key(
                relation_key, item, source_order, seen_keys
            )
            candidate["provider_item_key"] = candidate["item_key"]
            candidate["relation"] = candidate["relation_key"]
            candidate["source_index"] = source_order
            candidate["metadata"] = _safe_item_metadata(candidate)
            results.append(candidate)

    _extract_ti_items(data, relation_key="root")

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


def _pick_best_file(
    files: list[dict[str, Any]], content_type: str = "", allow_video: bool = True
) -> dict[str, Any] | None:
    """Pick the most valuable downloadable file."""

    if not files:
        return None

    best_m3u8 = None
    if allow_video:
        for item in files:
            if item["format"] == "m3u8" and "720p" in item.get("flag", ""):
                best_m3u8 = item
                break
        if not best_m3u8:
            best_m3u8 = next((item for item in files if item["format"] == "m3u8"), None)

    is_course = content_type in _COURSE_TYPES
    if is_course and allow_video:
        priority = [("m3u8", best_m3u8), ("mp4", None), ("pdf", None), ("mp3", None)]
    else:
        priority = [
            ("pdf", None),
            ("mp4", None) if allow_video else ("_skip", None),
            ("epub", None),
            ("m3u8", best_m3u8),
            ("mp3", None),
        ]

    for fmt, specific in priority:
        if specific:
            return specific
        if fmt == "_skip":
            continue
        for item in files:
            if item["format"] == fmt:
                return item
    return files[0]


def _flag_text(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("ti_file_flag") or candidate.get("flag") or "").casefold()


def _explicit_role(candidate: Mapping[str, Any]) -> str:
    """Map provider-declared role facts to the fixed asset vocabulary."""

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
    if (
        any(marker in flag for marker in ("cover", "thumbnail", "poster", "封面"))
        or relation_key in {"cover", "covers"}
        or source_type in {"cover", "thumbnail"}
    ):
        return "cover"
    if any(marker in flag for marker in ("subtitle", "caption", "subtitles", "字幕")):
        return "subtitle"
    if any(marker in flag for marker in ("transcript", "transcription", "讲稿")):
        return "transcript"
    if "metadata" in flag or flag in {"meta", "json"}:
        return "metadata"
    return ""


def _is_cover(candidate: Mapping[str, Any]) -> bool:
    return _explicit_role(candidate) == "cover"


def _is_video(candidate: Mapping[str, Any]) -> bool:
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


def _video_quality(candidate: Mapping[str, Any]) -> tuple[int, int, int]:
    flag = _flag_text(candidate)
    quality = 0
    for marker, score in (
        ("2160p", 4),
        ("1080p", 3),
        ("720p", 2),
        ("480p", 1),
        ("360p", 0),
    ):
        if marker in flag:
            quality = score
            break
    direct = 1 if str(candidate.get("format") or "").casefold() == "mp4" else 0
    return quality, direct, -int(candidate.get("source_order") or 0)


def _is_content_candidate(candidate: Mapping[str, Any]) -> bool:
    fmt = str(candidate.get("format") or "").casefold()
    if _is_cover(candidate):
        return False
    if fmt in _AUDIO_FORMATS or fmt in _SUBTITLE_FORMATS:
        return False
    if _explicit_role(candidate) in {"metadata", "transcript"}:
        return False
    return True


def _select_course_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select one quality variant per provider source item and retain companions."""

    if not files:
        return []
    selected: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in files:
        if _is_video(candidate):
            groups.setdefault(str(candidate.get("source_group_key") or ""), []).append(candidate)
        else:
            selected.append(candidate)
    for group in groups.values():
        selected.append(max(group, key=_video_quality))
    return sorted(selected, key=lambda item: int(item.get("source_order") or 0))


def _smartedu_file_key(content_id: str, candidate: Mapping[str, Any]) -> str:
    """Identify one logical course file only from stable provider facts.

    Video variants share the provider relation-group identity. Other files use
    their provider item identity. Signed URLs, filenames, sizes and source
    order never become logical child identity.
    """

    native_content_id = _fact(content_id)
    relation_key = _safe_relation_key(candidate.get("relation_key"))
    if not native_content_id:
        return ""
    if _is_video(candidate):
        identity_kind = "group"
        native_item_id = _fact(candidate.get("provider_group_id"))
    else:
        identity_kind = "item"
        native_item_id = _fact(candidate.get("provider_item_id"))
    if not native_item_id:
        return ""
    return (
        "smartedu-file:v1:"
        f"{_component(native_content_id)}:{_component(relation_key)}:"
        f"{identity_kind}:{_component(native_item_id)}"
    )


def _smartedu_file_key_from_resource(resource: Mapping[str, Any]) -> str:
    metadata = resource.get("metadata")
    signals = (
        metadata.get("platform_signals")
        if isinstance(metadata, Mapping)
        and isinstance(metadata.get("platform_signals"), Mapping)
        else {}
    )
    key = str(signals.get("file_key") or "").strip()
    if not key:
        return ""
    parts = key.split(":")
    if (
        len(parts) == 6
        and parts[0] == "smartedu-file"
        and parts[1] == "v1"
        and parts[4] in {"group", "item"}
        and all(unquote(value) for value in (parts[2], parts[3], parts[5]))
    ):
        return key
    raise DomainError(
        "CONTENT_VALIDATION_FAILED",
        "SmartEdu 文件资源身份无效",
        retryable=False,
    )


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
    files: list[dict[str, Any]],
    content_type: str,
    *,
    supported_formats: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    candidates = (
        [
            candidate
            for candidate in files
            if str(candidate.get("format") or "").casefold() in supported_formats
        ]
        if supported_formats is not None
        else list(files)
    )
    if not candidates:
        return None
    if content_type in _COURSE_TYPES:
        videos = [
            candidate
            for candidate in candidates
            if _is_video(candidate) and not _is_cover(candidate)
        ]
        if videos:
            return max(videos, key=_video_quality)
        content = [candidate for candidate in candidates if _is_content_candidate(candidate)]
        if content:
            return min(content, key=lambda item: int(item.get("source_order") or 0))
        return min(candidates, key=lambda item: int(item.get("source_order") or 0))
    return _pick_best_file(candidates, content_type, allow_video=True)
