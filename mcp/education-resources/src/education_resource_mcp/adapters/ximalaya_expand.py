"""Ximalaya creator and album expansion."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from ..errors import DomainError
from .http_client import urlopen_with_fallback

_XIMALAYA_TRACKS_URL = "https://www.ximalaya.com/revision/album/v1/getTracksList"
_XIMALAYA_CREATOR_ALBUMS_URL = "https://www.ximalaya.com/revision/user/pub"
_XIMALAYA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _kind(target: Mapping[str, Any]) -> str:
    return str(target.get("resource_type") or "").strip().casefold()


def _url(target: Mapping[str, Any]) -> str:
    return str(target.get("source_url") or "").strip()

def expand(
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


__all__ = ["expand"]
