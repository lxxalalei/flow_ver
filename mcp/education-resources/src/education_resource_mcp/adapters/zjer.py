"""Zhejiang Zjer (之江汇) course-detail adapter.

The current integration is intentionally evidence-driven: it expands a known
``courseCateId`` (or a user-supplied courseAfter URL) through the public course
detail API. Keyword discovery is not claimed until a native list/search request
has been observed.

Signed ``wkfile.zjer.cn`` media URLs are used only as short-lived transport
facts. They are never returned in Resource metadata or persisted inspection
results.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request

from ..config import Settings
from ..errors import DomainError
from ..sessions import SessionStore, session_cookie
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


BASE_URL = "https://k.zjer.cn"
DETAIL_API = BASE_URL + "/api/s/c/courseAfter/{course_cate_id}"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

DetailTransport = Callable[[Request, float], Any]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _course_id_from_query(query: str) -> int | None:
    text = str(query or "").strip()
    if text.isdigit() and int(text) > 0:
        return int(text)
    for pattern in (
        r"/courseAfter/(\d+)",
        r"[?&]courseCateId=(\d+)",
        r"[?&]id=(\d+)",
    ):
        match = re.search(pattern, text, flags=re.I)
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def _detail_url(course_cate_id: int, *, video_id: int | None = None) -> str:
    query: list[tuple[str, str]] = [
        ("id", str(course_cate_id)),
        ("shareId", ""),
    ]
    # videoId is an identity discriminator for individual lesson Resources.
    # The Inspector/Downloader never rely on it being interpreted by the API;
    # they bind the lesson from server-owned metadata and re-read the base
    # detail endpoint.
    if video_id is not None:
        query.append(("videoId", str(video_id)))
    return f"{DETAIL_API.format(course_cate_id=course_cate_id)}?{urlencode(query)}"


def _default_transport(request: Request, timeout: float) -> Any:
    return urlopen_with_fallback(request, timeout=timeout)


def fetch_course_detail(
    course_cate_id: int,
    *,
    timeout: float,
    transport: DetailTransport | None = None,
    cookie: str = "",
) -> dict[str, Any]:
    course_cate_id = _positive_int(course_cate_id) or 0
    if not course_cate_id:
        raise DomainError("INVALID_ARGUMENT", "之江汇 courseCateId 无效")
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": BASE_URL + "/",
    }
    if cookie:
        headers["Cookie"] = cookie
    request = Request(
        _detail_url(course_cate_id),
        headers=headers,
    )
    opener = transport or _default_transport
    try:
        response = opener(request, timeout)
        with response:
            raw = response.read()
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise DomainError("AUTH_REQUIRED", "之江汇课程详情需要授权", retryable=False) from exc
        if exc.code in {404, 410}:
            raise DomainError("RESOURCE_NOT_FOUND", "之江汇课程当前不可用", retryable=False) from exc
        if exc.code == 429:
            raise DomainError("RATE_LIMITED", "之江汇请求过于频繁", retryable=True) from exc
        raise DomainError("PLATFORM_UNAVAILABLE", "之江汇课程详情请求失败", retryable=True) from exc
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("PLATFORM_UNAVAILABLE", "之江汇课程详情请求失败", retryable=True) from exc
    try:
        payload = json.loads(bytes(raw).decode("utf-8", "replace"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DomainError("CONTENT_VALIDATION_FAILED", "之江汇课程详情格式无效") from exc
    if not isinstance(payload, dict):
        raise DomainError("CONTENT_VALIDATION_FAILED", "之江汇课程详情格式无效")
    code = payload.get("code")
    if str(code) not in {"0", "200"}:
        msg = str(payload.get("msg") or "").strip()
        if str(code) in {"401", "402", "403"} or "登录" in msg:
            raise DomainError(
                "AUTH_REQUIRED",
                "之江汇课程详情需要登录",
                retryable=False,
            )
        raise DomainError(
            "PLATFORM_UNAVAILABLE",
            f"之江汇课程详情返回失败（code={code}）：{msg or '无说明'}",
            retryable=True,
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise DomainError("CONTENT_VALIDATION_FAILED", "之江汇课程详情缺少 data")
    return data


def _media_url(value: Any, *, expected_suffix: str = ".mp4") -> str:
    text = _clean(value)
    if text.startswith("//"):
        text = "https:" + text
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or not (host == "zjer.cn" or host.endswith(".zjer.cn"))
        or not parsed.path.casefold().endswith(expected_suffix)
    ):
        return ""
    return text


def best_mp4(lesson: Mapping[str, Any]) -> dict[str, Any] | None:
    values = lesson.get("mp4List")
    if not isinstance(values, list):
        return None
    candidates: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        url = _media_url(raw.get("videoUrl"))
        if not url:
            continue
        item = dict(raw)
        item["_fresh_url"] = url
        candidates.append(item)
    if not candidates:
        return None

    def quality(item: Mapping[str, Any]) -> tuple[int, int, int, int]:
        return tuple(
            _positive_int(item.get(key)) or 0
            for key in ("height", "width", "bitrate", "videoSize")
        )  # type: ignore[return-value]

    return max(candidates, key=quality)


def lessons(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = data.get("courseInfoList")
    if not isinstance(values, list):
        return []
    return [dict(item) for item in values if isinstance(item, Mapping)]


def find_lesson(
    data: Mapping[str, Any],
    *,
    video_id: int,
    course_info_id: int | None = None,
) -> dict[str, Any] | None:
    for item in lessons(data):
        if _positive_int(item.get("videoId")) != video_id:
            continue
        if course_info_id is not None and _positive_int(item.get("id")) != course_info_id:
            continue
        return item
    current = data.get("course")
    if isinstance(current, Mapping):
        if _positive_int(current.get("videoId")) == video_id and (
            course_info_id is None or _positive_int(current.get("id")) == course_info_id
        ):
            return dict(current)
    return None


def resource_video_identity(resource: Mapping[str, Any]) -> tuple[int, int, int] | None:
    metadata = resource.get("metadata")
    signals: Mapping[str, Any] = {}
    if isinstance(metadata, Mapping):
        raw_signals = metadata.get("platform_signals")
        if isinstance(raw_signals, Mapping):
            signals = raw_signals
    course_cate_id = _positive_int(signals.get("course_cate_id"))
    course_info_id = _positive_int(signals.get("course_info_id"))
    video_id = _positive_int(signals.get("video_id"))
    if not course_cate_id or not course_info_id or not video_id:
        return None
    return course_cate_id, course_info_id, video_id


def _safe_media_facts(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return {}
    result: dict[str, Any] = {}
    mapping = {
        "videoSecond": "video_duration_seconds",
        "videoSize": "video_size_bytes",
        "bitrate": "bitrate_kbps",
        "height": "height",
        "width": "width",
        "definition": "definition",
        "uuid": "video_uuid",
    }
    for source, target in mapping.items():
        value = item.get(source)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            result[target] = value
    return result


class ZjerSearchAdapter:
    """Experimental direct-course lookup for Zjer.

    Only a known courseCateId or a courseAfter URL is accepted. This keeps the
    runtime useful for real E2E without inventing an undocumented keyword API.
    """

    platform_id = "zjer"

    def __init__(
        self,
        session_store: SessionStore,
        settings: Settings,
        *,
        detail_transport: DetailTransport | None = None,
    ) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)
        self.detail_transport = detail_transport

    def _cookie(self) -> str:
        return session_cookie(self.session_store, "zjer")

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        course_cate_id = _course_id_from_query(query)
        if course_cate_id is None:
            return [], adapter_error(
                "FEATURE_NOT_SUPPORTED",
                "之江汇当前只支持 courseCateId 或 courseAfter 详情 URL；关键词原生搜索尚未确认",
                False,
            )
        try:
            data = fetch_course_detail(
                course_cate_id,
                timeout=self.timeout,
                transport=self.detail_transport,
                cookie=self._cookie(),
            )
        except DomainError as exc:
            return [], adapter_error(exc.code, exc.message, exc.retryable)

        course_name = _clean(data.get("cateName"))
        org_name = _clean(data.get("teacherOrgName") or data.get("orgName"))
        course_uuid = _clean(data.get("uuid"))
        resources: list[dict[str, Any]] = []
        for lesson in lessons(data):
            video_id = _positive_int(lesson.get("videoId"))
            course_info_id = _positive_int(lesson.get("id"))
            lesson_name = _clean(lesson.get("courseName"))
            if not video_id or not course_info_id or not lesson_name:
                continue
            media = best_mp4(lesson)
            if media is None:
                continue
            signals: dict[str, Any] = {
                "course_cate_id": course_cate_id,
                "course_info_id": course_info_id,
                "video_id": video_id,
                "course_cate_uuid": course_uuid or None,
                "course_info_uuid": _clean(lesson.get("uuid")) or None,
            }
            signals.update(_safe_media_facts(media))
            title = f"{course_name}｜{lesson_name}" if course_name else lesson_name
            resources.append(
                make_resource(
                    platform="zjer",
                    title=title,
                    source_url=_detail_url(course_cate_id, video_id=video_id),
                    resource_type="视频",
                    summary=_clean(data.get("description") or data.get("intro")) or None,
                    author=org_name or None,
                    download_feasibility="高",
                    platform_signals=signals,
                )
            )
            if len(resources) >= limit:
                break
        return resources, None


__all__ = [
    "ZjerSearchAdapter",
    "best_mp4",
    "fetch_course_detail",
    "find_lesson",
    "resource_video_identity",
]
