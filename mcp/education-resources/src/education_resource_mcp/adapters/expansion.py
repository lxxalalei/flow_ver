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
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "SmartEdu 课程当前支持自然完整资源包下载；独立附件子资源尚未形成稳定 Resource 身份",
        )
    raise DomainError(
        "FEATURE_NOT_SUPPORTED",
        "SmartEdu 当前资源没有已实现的结构展开能力",
    )


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
