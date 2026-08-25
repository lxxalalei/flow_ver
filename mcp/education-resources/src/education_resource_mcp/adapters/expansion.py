"""Platform-specific structural expansion implementations."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import re
import urllib.parse
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request
from typing import Any

from ..errors import DomainError
from .http_client import urlopen_with_fallback


_XIMALAYA_TRACKS_URL = "https://www.ximalaya.com/revision/album/v1/getTracksList"
_XIMALAYA_CREATOR_ALBUMS_URL = "https://www.ximalaya.com/revision/user/pub"
_SMARTEDU_MATERIAL_PARTS_URL = (
    "https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/national_lesson/"
    "teachingmaterials/{textbook_id}/resources/part_{part_no}.json"
)
_XIMALAYA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def expand_resource(
    search_provider: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Expand one container Resource using platform-owned mechanics."""

    platform = str(target.get("platform") or "").strip()
    adapter = (getattr(search_provider, "_adapters", None) or {}).get(platform)
    if adapter is None:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            f"平台 {platform or 'generic'} 当前没有结构展开能力",
        )

    handlers = {
        "bilibili": _expand_bilibili,
        "douyin": _expand_douyin,
        "ximalaya": _expand_ximalaya,
        "smartedu": _expand_smartedu,
        "zjer": _expand_zjer,
        "cctv": _expand_cctv,
    }
    handler = handlers.get(platform)
    if handler is None:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            f"平台 {platform} 当前没有结构展开能力",
        )
    if platform == "smartedu":
        yield from handler(
            adapter,
            target,
            cancel_event=cancel_event,
            summary=summary,
        )
        return
    yield from handler(adapter, target, cancel_event=cancel_event)


def _kind(target: Mapping[str, Any]) -> str:
    return str(target.get("resource_type") or "").strip().casefold()


def _url(target: Mapping[str, Any]) -> str:
    return str(target.get("source_url") or "").strip()


def _expand_bilibili(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    url = _url(target)
    kind = _kind(target)
    is_collection_url = "space.bilibili.com" in url and (
        "/lists/" in url
        or "/channel/collectiondetail" in url
        or "/channel/seriesdetail" in url
    )
    if kind == "collection" or is_collection_url:
        iterator = getattr(adapter, "iter_collection", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili 合集展开不可用")
        yield from iterator(url, cancel_event=cancel_event)
        return
    if kind == "creator" or ("space.bilibili.com" in url and not is_collection_url):
        iterator = getattr(adapter, "iter_creator", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili 创作者展开不可用")
        yield from iterator(url, cancel_event=cancel_event)
        return
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "Bilibili video 是叶子资源，没有可展开子资源",
    )


def _expand_douyin(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    url = _url(target)
    kind = _kind(target)
    if kind == "collection" or "/collection/" in url or "/mix/" in url:
        iterator = getattr(adapter, "iter_collection", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Douyin 合集展开不可用")
        yield from iterator(url, cancel_event=cancel_event)
        return
    if kind == "creator" or "/user/" in url:
        iterator = getattr(adapter, "iter_creator", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Douyin 创作者展开不可用")
        yield from iterator(url, cancel_event=cancel_event)
        return
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "Douyin video 是叶子资源，没有可展开子资源",
    )


def _expand_ximalaya(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    url = _url(target)
    kind = _kind(target)
    if kind == "album" or re.search(r"/album/\d+", url):
        yield from _iter_ximalaya_album(
            url,
            timeout=float(getattr(adapter, "timeout", 30.0)),
            cancel_event=cancel_event,
        )
        return
    if kind == "creator" or re.search(r"/zhubo/\d+", url):
        yield from _iter_ximalaya_creator(
            url,
            timeout=float(getattr(adapter, "timeout", 30.0)),
            cancel_event=cancel_event,
        )
        return
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "Ximalaya track 是叶子资源，没有可展开子资源",
    )


def _iter_ximalaya_creator(
    source_url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    match = re.search(r"/zhubo/(\d+)", source_url)
    if not match:
        raise DomainError("INVALID_ARGUMENT", "Ximalaya 主播 URL 缺少 uid")
    creator_id = match.group(1)
    page, page_size, seen = 1, 100, 0
    total: int | None = None

    while total is None or seen < total:
        if cancel_event is not None and cancel_event.is_set():
            return
        params = urlencode({
            "uid": creator_id,
            "page": page,
            "pageSize": page_size,
            "orderType": 2,
        })
        request = Request(
            f"{_XIMALAYA_CREATOR_ALBUMS_URL}?{params}",
            headers={
                "User-Agent": _XIMALAYA_UA,
                "Referer": source_url,
                "Accept": "application/json, text/plain, */*",
            },
        )
        try:
            with urlopen_with_fallback(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "PARTIAL_FAILURE",
                f"Ximalaya 主播专辑请求失败：{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("ret") != 200
            or not isinstance(data, dict)
        ):
            raise DomainError(
                "PARTIAL_FAILURE",
                "Ximalaya 主播专辑响应结构异常",
                retryable=True,
            )
        albums = data.get("albumList")
        if not isinstance(albums, list):
            raise DomainError(
                "PARTIAL_FAILURE",
                "Ximalaya 主播专辑列表格式异常",
                retryable=True,
            )
        if total is None:
            try:
                total = int(data["totalCount"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DomainError(
                    "PARTIAL_FAILURE",
                    "Ximalaya 主播专辑响应缺少 totalCount",
                    retryable=True,
                ) from exc
            if total < 0:
                raise DomainError(
                    "PARTIAL_FAILURE",
                    "Ximalaya 主播专辑 totalCount 无效",
                    retryable=True,
                )
        if not albums:
            if seen < total:
                raise DomainError(
                    "PARTIAL_FAILURE",
                    f"Ximalaya 主播专辑分页提前结束：已取得 {seen}/{total}",
                    retryable=True,
                )
            break

        for album in albums:
            if not isinstance(album, dict):
                raise DomainError(
                    "PARTIAL_FAILURE",
                    "Ximalaya 主播专辑条目格式异常",
                    retryable=True,
                )
            album_id = str(album.get("id") or "").strip()
            title = str(album.get("title") or "").strip()
            if not album_id or not title:
                raise DomainError(
                    "PARTIAL_FAILURE",
                    "Ximalaya 主播专辑条目缺少 id 或 title",
                    retryable=True,
                )
            cover = str(album.get("coverPath") or "").strip() or None
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            yield {
                "platform": "ximalaya",
                "title": title,
                "source_url": f"https://www.ximalaya.com/album/{album_id}",
                "resource_type": "album",
                "summary": str(album.get("description") or "").strip() or None,
                "metadata": {
                    "author": str(album.get("anchorNickName") or "").strip() or None,
                    "platform_signals": {
                        "creator_id": creator_id,
                        "album_id": album_id,
                        "play_count": album.get("playCount"),
                        "tracks": album.get("trackCount"),
                        "is_paid": bool(album.get("isPaid")),
                        "is_finished": bool(album.get("isFinished")),
                        "cover_url": cover,
                    },
                },
            }
            seen += 1
        page += 1


def _iter_ximalaya_album(
    source_url: str,
    *,
    timeout: float,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    match = re.search(r"/album/(\d+)", source_url)
    if not match:
        raise DomainError("INVALID_ARGUMENT", "Ximalaya 专辑 URL 缺少 album id")
    album_id = match.group(1)
    page_num, page_size, seen = 1, 100, 0
    total: int | None = None

    while total is None or seen < total:
        if cancel_event is not None and cancel_event.is_set():
            return
        params = urlencode(
            {"albumId": album_id, "pageNum": page_num, "pageSize": page_size}
        )
        request = Request(
            f"{_XIMALAYA_TRACKS_URL}?{params}",
            headers={
                "User-Agent": _XIMALAYA_UA,
                "Referer": source_url,
                "Accept": "application/json, text/plain, */*",
            },
        )
        with urlopen_with_fallback(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise DomainError(
                "PARTIAL_FAILURE",
                "Ximalaya 专辑曲目响应结构异常",
                retryable=True,
            )
        tracks = data.get("tracks") or []
        if not isinstance(tracks, list) or not tracks:
            break
        if total is None:
            try:
                total = int(data.get("trackTotalCount"))
            except (TypeError, ValueError):
                total = None

        for track in tracks:
            if not isinstance(track, dict):
                continue
            track_id = str(track.get("trackId") or track.get("track_id") or "").strip()
            title = str(track.get("title") or "").strip()
            if not track_id or not title:
                continue
            metadata: dict[str, Any] = {
                "platform_signals": {"album_id": album_id, "track_id": track_id}
            }
            duration = track.get("duration")
            if isinstance(duration, (int, float)) and duration >= 0:
                metadata["duration_seconds"] = int(duration)
            yield {
                "platform": "ximalaya",
                "title": title,
                "source_url": f"https://www.ximalaya.com/sound/{track_id}",
                "resource_type": "track",
                "summary": str(track.get("intro") or "").strip() or None,
                "metadata": metadata,
            }
            seen += 1
        if len(tracks) < page_size:
            break
        page_num += 1


def _expand_smartedu(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    url = _url(target)
    kind = _kind(target)
    if kind == "textbook" or "/tchMaterial/" in url:
        yield from _iter_smartedu_textbook(
            adapter,
            target,
            cancel_event=cancel_event,
            summary=summary,
        )
        return
    if kind == "course":
        yield from _iter_smartedu_course_files(
            adapter,
            target,
            cancel_event=cancel_event,
            summary=summary,
        )
        return
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "SmartEdu 当前资源没有已实现的结构展开能力",
    )


def _smartedu_course_detail(
    adapter: Any,
    source_url: str,
) -> tuple[str, str, dict[str, Any]]:
    from .smartedu_download import (
        _COURSE_TYPES,
        _DETAIL_MAX_BYTES,
        _SMARTEDU_DETAIL_HOSTS,
        _SmartEduHttpClient,
        _detail_api_url,
        _raise_for_http_status,
        _read_json_object,
        _resolve_content,
        _smartedu_headers,
    )

    content_id, content_type = _resolve_content(source_url)
    if content_type not in _COURSE_TYPES:
        raise DomainError("FEATURE_NOT_SUPPORTED", "SmartEdu 当前资源不是可展开课程")
    token = ""
    session_store = getattr(adapter, "session_store", None)
    if session_store is not None:
        session_data = session_store.get_session_data("smartedu") or {}
        tokens = session_data.get("tokens") or {}
        raw_token = str(tokens.get("accessToken") or "")
        token = raw_token[7:].strip() if raw_token.casefold().startswith("bearer ") else raw_token
    client = _SmartEduHttpClient(allowed_hosts=_SMARTEDU_DETAIL_HOSTS)
    request = Request(
        _detail_api_url(content_id, content_type, source_url),
        headers=_smartedu_headers(token),
    )
    try:
        with client.open(request, timeout=float(getattr(adapter, "timeout", 30.0))) as response:
            _raise_for_http_status(response)
            detail = _read_json_object(response, _DETAIL_MAX_BYTES, label="课程详情")
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "PARTIAL_FAILURE",
            "SmartEdu 课程文件详情读取失败",
            retryable=True,
        ) from exc
    return content_id, content_type, detail


def _iter_smartedu_course_files(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    from .smartedu_download import (
        _ACTIVE_PRIMARY_FORMATS,
        _find_files,
        _primary_candidate,
        _role_for_candidate,
        _select_course_files,
        _smartedu_file_key,
    )

    source_url = _url(target)
    content_id, content_type, detail = _smartedu_course_detail(adapter, source_url)
    active = [
        candidate
        for candidate in _find_files(detail)
        if str(candidate.get("format") or "").casefold() in _ACTIVE_PRIMARY_FORMATS
    ]
    selected = _select_course_files(active)
    primary = _primary_candidate(
        selected,
        content_type,
        supported_formats=_ACTIVE_PRIMARY_FORMATS,
    )
    if primary is None:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "SmartEdu 课程详情未提供受支持的主文件",
        )
    primary_key = str(primary.get("item_key") or "")
    report = {
        "course_id": content_id,
        "files_seen": len(selected),
        "emitted": 0,
        "unstable_files": 0,
    }
    if summary is not None:
        summary["smartedu"] = report
    seen_keys: set[str] = set()
    role_labels = {
        "primary": "主文件",
        "attachment": "附件",
        "companion": "伴随资源",
        "subtitle": "字幕",
    }
    type_by_format = {
        "mp4": "video",
        "m3u8": "video",
        "mp3": "audio",
        "m4a": "audio",
        "pdf": "document",
    }
    for candidate in selected:
        if cancel_event is not None and cancel_event.is_set():
            return
        file_key = _smartedu_file_key(content_id, candidate)
        if not file_key:
            report["unstable_files"] += 1
            continue
        if file_key in seen_keys:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "SmartEdu 课程详情包含重复的平台文件身份",
            )
        seen_keys.add(file_key)
        fmt = str(candidate.get("format") or "").casefold()
        role = _role_for_candidate(
            candidate,
            primary_key=primary_key,
            content_type=content_type,
        )
        title = str(candidate.get("title") or "").strip() or f"课程文件 {len(seen_keys)}"
        size = int(candidate.get("size") or 0)
        summary_parts = [role_labels.get(role, role), fmt.upper()]
        if size > 0:
            summary_parts.append(f"{size} bytes")
        report["emitted"] += 1
        yield {
            "platform": "smartedu",
            "title": title,
            "source_url": source_url,
            "resource_type": type_by_format.get(fmt, "other"),
            "summary": " · ".join(summary_parts),
            "metadata": {
                "platform_signals": {
                    "course_id": content_id,
                    "file_key": file_key,
                    "relation_key": str(candidate.get("relation_key") or "root"),
                    "course_role": role,
                    "format": fmt,
                }
            },
        }


def _iter_smartedu_textbook(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
    summary: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    source_url = _url(target)
    textbook_id = str(
        (urllib.parse.parse_qs(urlsplit(source_url).query).get("contentId") or [""])[0]
    ).strip()
    if not textbook_id:
        raise DomainError("INVALID_ARGUMENT", "SmartEdu 教材 URL 缺少 contentId")

    headers = adapter._build_headers()  # noqa: SLF001 - same platform layer
    parent_metadata = target.get("metadata")
    parent_signals = (
        parent_metadata.get("platform_signals")
        if isinstance(parent_metadata, Mapping)
        and isinstance(parent_metadata.get("platform_signals"), Mapping)
        else {}
    )
    report: dict[str, Any] = {
        "textbook_id": textbook_id,
        "parts_read": 0,
        "resource_counts": {},
        "emitted": 0,
        "skipped_types": {},
        "invalid_items": 0,
        "termination": None,
    }
    if summary is not None:
        summary["smartedu"] = report

    part_no = 100
    while True:
        if cancel_event is not None and cancel_event.is_set():
            report["termination"] = "cancelled"
            return
        try:
            values = _smartedu_cdn_json(
                adapter,
                _SMARTEDU_MATERIAL_PARTS_URL.format(
                    textbook_id=urllib.parse.quote(textbook_id),
                    part_no=part_no,
                ),
                headers,
            )
        except HTTPError as exc:
            if exc.code == 404:
                report["termination"] = "not_found"
                break
            report["termination"] = "error"
            raise
        except Exception:
            report["termination"] = "error"
            raise
        if not isinstance(values, list):
            report["termination"] = "error"
            raise DomainError(
                "PARTIAL_FAILURE",
                "SmartEdu 教材资源分片格式异常",
                retryable=True,
            )
        report["parts_read"] += 1
        if not values:
            report["termination"] = "empty_page"
            break
        for entry in values:
            if not isinstance(entry, dict):
                report["invalid_items"] += 1
                continue
            resource_type = str(entry.get("resource_type_code") or "").strip()
            child_id = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not resource_type or not child_id or not title:
                report["invalid_items"] += 1
                continue
            counts = report["resource_counts"]
            counts[resource_type] = int(counts.get(resource_type) or 0) + 1
            if resource_type not in {"national_lesson", "elite_lesson"}:
                skipped = report["skipped_types"]
                skipped[resource_type] = int(skipped.get(resource_type) or 0) + 1
                continue
            child_url = (
                "https://basic.smartedu.cn/syncClassroom/classActivity?activityId="
                + urllib.parse.quote(child_id)
                if resource_type == "national_lesson"
                else "https://basic.smartedu.cn/qualityCourse?courseId="
                + urllib.parse.quote(child_id)
            )
            child_signals = {
                "textbook_id": textbook_id,
                "resource_type_code": resource_type,
            }
            for key in ("subject", "grade", "volume", "version", "edition", "stage"):
                if parent_signals.get(key) not in (None, ""):
                    child_signals[key] = parent_signals[key]
            report["emitted"] += 1
            yield {
                "platform": "smartedu",
                "title": title,
                "source_url": child_url,
                "resource_type": "course",
                "metadata": {
                    "platform_signals": child_signals
                },
            }
        part_no += 1


def _smartedu_cdn_json(
    adapter: Any,
    url: str,
    headers: Mapping[str, str],
) -> Any:
    request = Request(url, headers=dict(headers))
    with urlopen_with_fallback(
        request,
        timeout=float(getattr(adapter, "timeout", 30.0)),
    ) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _expand_cctv(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    from . import cctv as cctv_adapter

    url = _url(target)
    kind = _kind(target)
    if kind == "column" or "/lm/" in url:
        iterator = getattr(adapter, "iter_column", None)
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "CCTV 栏目展开不可用")
        results = iterator(url, cancel_event=cancel_event)
        yield from results
        return
    if kind in {"视频", "video", "series"} or cctv_adapter.EPISODE_PATH_RE.search(url):
        timeout = float(getattr(adapter, "timeout", 30.0))
        links = cctv_adapter.series_episode_links(url, timeout=timeout)
        if links:
            yield from cctv_adapter.iter_episodes(
                links, timeout=timeout, cancel_event=cancel_event
            )
            return
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "CCTV 单集是叶子资源，没有可展开子资源；栏目或纪录片系列页才可展开",
        )
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "CCTV 当前资源没有已实现的结构展开能力",
    )


def _expand_zjer(
    adapter: Any,
    target: Mapping[str, Any],
    *,
    cancel_event: Any = None,
) -> Iterator[dict[str, Any]]:
    if _kind(target) not in {"course", "课程"}:
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "Zjer video 是叶子资源，没有可展开子资源",
        )

    from .zjer import (
        _course_id_from_query,
        _detail_url,
        _safe_media_facts,
        best_mp4,
        fetch_course_detail,
        lessons,
    )

    course_id = _course_id_from_query(_url(target))
    if course_id is None:
        raise DomainError("INVALID_ARGUMENT", "Zjer 课程 URL 缺少 courseCateId")
    data = fetch_course_detail(
        course_id,
        timeout=float(getattr(adapter, "timeout", 30.0)),
        transport=getattr(adapter, "detail_transport", None),
    )
    course_name = str(data.get("cateName") or "").strip()
    org_name = str(data.get("teacherOrgName") or data.get("orgName") or "").strip()
    course_uuid = str(data.get("uuid") or "").strip()

    for lesson in lessons(data):
        if cancel_event is not None and cancel_event.is_set():
            return
        try:
            video_id = int(lesson.get("videoId") or 0)
            course_info_id = int(lesson.get("id") or 0)
        except (TypeError, ValueError):
            continue
        lesson_name = str(lesson.get("courseName") or "").strip()
        media = best_mp4(lesson)
        if not video_id or not course_info_id or not lesson_name or media is None:
            continue
        signals: dict[str, Any] = {
            "course_cate_id": course_id,
            "course_info_id": course_info_id,
            "video_id": video_id,
            "course_cate_uuid": course_uuid or None,
            "course_info_uuid": str(lesson.get("uuid") or "").strip() or None,
        }
        signals.update(_safe_media_facts(media))
        yield {
            "platform": "zjer",
            "title": f"{course_name}｜{lesson_name}" if course_name else lesson_name,
            "source_url": _detail_url(course_id, video_id=video_id),
            "resource_type": "视频",
            "metadata": {
                "author": org_name or None,
                "platform_signals": signals,
            },
        }


__all__ = ["expand_resource"]
