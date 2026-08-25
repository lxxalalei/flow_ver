"""Pure SmartEdu resource identity, relation, and file-selection facts.

This module contains deterministic platform rules shared by inspection,
expansion, and download. It deliberately performs no network or filesystem IO.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse, urlunparse

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
_SAFE_FACT = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")

CDN_BASE = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2"
CDN_SPECIAL = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrs"
STORAGE_PREFIX = "https://r1-ndr-private.ykt.cbern.com.cn"


def _smartedu_representation_id(
    resource: Mapping[str, Any], candidate: Mapping[str, Any]
) -> str:
    file_key = _smartedu_file_key_from_resource(resource)
    seed = "|".join(
        (
            "smartedu-primary-v1",
            file_key or str(resource.get("resource_id") or ""),
            str(resource.get("source_url") or ""),
            str(candidate.get("item_key") or ""),
            str(candidate.get("format") or "").casefold(),
        )
    )
    return "repr_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


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


def _provider_item_id(item: Mapping[str, Any]) -> str:
    """Return only a platform-provided item identity, never a locator."""

    for candidate in (
        item.get("ti_item_id"),
        item.get("item_id"),
        item.get("id"),
        item.get("resource_id"),
        item.get("resourceId"),
    ):
        text = _safe_fact(candidate)
        if text:
            return text
    return ""


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

    explicit = _provider_item_id(item)
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


def _provider_group_id(parent: Mapping[str, Any]) -> str:
    for candidate in (
        parent.get("resource_id"),
        parent.get("resourceId"),
        parent.get("id"),
        parent.get("content_id"),
    ):
        text = _safe_fact(candidate)
        if text:
            return text
    return ""


def _source_group_key(
    relation_key: str, parent: dict[str, Any], label: str, source_order: int
) -> str:
    explicit = _provider_group_id(parent)
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
                "provider_item_id": _provider_item_id(item),
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
            candidate["provider_group_id"] = _provider_group_id(obj)
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


def _video_quality(candidate: dict[str, Any]) -> tuple[int, int, int]:
    """Rank explicit provider quality flags; prefer a direct file over HLS at
    equal quality, then keep source order stable."""

    flag = _flag_text(candidate)
    quality = 0
    for marker, score in (("2160p", 4), ("1080p", 3), ("720p", 2), ("480p", 1), ("360p", 0)):
        if marker in flag:
            quality = score
            break
    direct = 1 if str(candidate.get("format") or "").casefold() == "mp4" else 0
    return quality, direct, -int(candidate.get("source_order") or 0)


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


def _smartedu_file_key(content_id: str, candidate: Mapping[str, Any]) -> str:
    """Identify one logical course file only from stable provider facts.

    Video variants share the native relation-group identity. Other files use
    their native item identity. A signed storage URL, filename, source order,
    size, or inferred fallback key is never accepted as child identity.
    """

    native_content_id = _safe_fact(content_id)
    relation_key = _safe_relation_key(candidate.get("relation_key"))
    if not native_content_id:
        return ""
    if _is_video(dict(candidate)):
        identity_kind = "group"
        native_item_id = _safe_fact(candidate.get("provider_group_id"))
    else:
        identity_kind = "item"
        native_item_id = _safe_fact(candidate.get("provider_item_id"))
    if not native_item_id:
        return ""
    digest = hashlib.sha256(
        "\x1f".join(
            ("smartedu-file-v1", native_content_id, relation_key, identity_kind, native_item_id)
        ).encode("utf-8")
    ).hexdigest()[:32]
    return f"smartedu-file:{digest}"


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
    if re.fullmatch(r"smartedu-file:[0-9a-f]{32}", key):
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
