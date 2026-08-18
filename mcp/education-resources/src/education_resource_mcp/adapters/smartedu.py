"""SmartEdu (国家中小学智慧教育平台) search adapter.

Uses the platform's combine-search POST API with token auth.  The token
is pulled from ``SessionStore`` (stored as ``tokens.accessToken``);
without a token the search API still returns some public results.

This adapter consolidates the search-only path from four legacy files
(``_search.py``, ``_constants.py``, ``_text_utils.py``, ``_auth_http.py``)
into a single module.  Detail-fetching, catalog walking and tag filtering
beyond the search response are not included — those belong to a future
download/detail adapter.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


# ---------------------------------------------------------------------------
# Constants (ported from _constants.py — search-relevant subset)
# ---------------------------------------------------------------------------

SEARCH_URLS = (
    "https://x-search.ykt.eduyun.cn/v1/resources/combine/search",
    "https://resource-gateway.ykt.eduyun.cn/resources/combine/search",
    "https://resource-gateway.ykt.eduyun.cn/resources/aggregate",
)

# National-lesson textbook discovery via public static CDN JSON (0057 M4b).
# No browser: the frontend renders these endpoints, so we call them directly.
CDN_DATA_VERSION_URL = (
    "https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/national_lesson/"
    "teachingmaterials/version/data_version.json"
)
CDN_MATERIAL_PARTS_TMPL = (
    "https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/national_lesson/"
    "teachingmaterials/{mid}/resources/part_{n}.json"
)
CDN_MATERIAL_TREES_TMPL = (
    "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/national_lesson/trees/{mid}.json"
)

DETAIL_PAGE = (
    "https://basic.smartedu.cn/{catalog}/detail?"
    "contentType={content_type}&contentId={id}&catalogType={catalog}&subCatalog={sub_catalog}"
)

DEFAULT_SDP_APP_ID = "e5649925-441d-4a53-b525-51a2f1c4e0a8"

DEFAULT_TAB_CODES = [
    "qualityCourse", "prepareLesson", "questions", "examinationPapers",
    "teachingKnMicroLesson", "sedu", "family", "labourEdu", "schoolService",
    "specialEdu", "tchMaterial", "teacherTraining", "lecturer",
    "AIEducation", "technologyEdu", "areaSite", "topic", "live",
    "art", "sport", "eduReform", "nationality", "childhoodEdu",
    "questions_ai_answer", "studio-inst-teachres", "studio-inst-spres",
]

TAG_DIMENSIONS = {
    "zxxxd": "stage",
    "zxxxk": "subject",
    "zxxnj": "grade",
    "zxxbb": "version",
    "zxxcc": "volume",
}

RESOURCE_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "json",
    "srt", "superboard", "jpg", "jpeg", "png", "webp", "gif",
    "mp3", "wav", "m4a", "mp4", "mov", "m3u8", "zip", "rar", "7z",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# Chinese type → MCP ResourceType mapping (service layer maps further).
SMARTEDU_TYPE_MAP = {
    "视频": "视频", "音频": "音频", "课件": "课件", "文档": "文档",
    "图片": "图片", "习题": "习题", "试卷": "试卷",
    "课程": "课程", "教材": "教材", "专题": "专题",
}


# ---------------------------------------------------------------------------
# Text utils (ported from _text_utils.py)
# ---------------------------------------------------------------------------

def _norm(value: Any) -> str:
    return str(value or "").strip()


def _clean_html_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return _norm(re.sub(r"\s+", " ", text))


def _stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _first_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


# ---------------------------------------------------------------------------
# Search-item extraction (ported from _search.py)
# ---------------------------------------------------------------------------

def _detail_page_from_item(item: dict[str, Any]) -> str:
    explicit = _norm(_first_value(item, [
        "url", "web_url", "webUrl", "href", "detail_url", "detailUrl",
        "share_url", "shareUrl",
    ]))
    if explicit.startswith("http"):
        return explicit
    resource_id = _norm(_first_value(item, [
        "id", "resource_id", "resourceId", "content_id", "contentId",
        "course_id", "courseId",
    ]))
    content_type = _norm(_first_value(item, [
        "content_type", "contentType", "resource_type", "resourceType",
        "resource_type_code", "resourceTypeCode",
    ])) or "resource"
    tab_code = _norm(_first_value(item, [
        "tab_code", "tabCode", "catalog", "catalog_type", "catalogType",
        "channel_code", "channelCode",
    ]))
    if content_type == "elite_lesson":
        return f"https://basic.smartedu.cn/qualityCourse?courseId={urllib.parse.quote(resource_id)}"
    if content_type == "national_lesson":
        return f"https://basic.smartedu.cn/syncClassroom/classActivity?activityId={urllib.parse.quote(resource_id)}"
    if content_type in ("prepare_lesson", "experiment_elite_lesson"):
        return f"https://basic.smartedu.cn/syncClassroom/prepare/detail?resourceId={urllib.parse.quote(resource_id)}"
    if tab_code == "tchMaterial":
        return (
            "https://basic.smartedu.cn/tchMaterial/detail?"
            f"contentType={urllib.parse.quote(content_type or 'teaching_material')}"
            f"&contentId={urllib.parse.quote(resource_id)}"
            "&catalogType=tchMaterial&subCatalog=tchMaterial"
        )
    if tab_code == "qualityCourse":
        return f"https://basic.smartedu.cn/qualityCourse?courseId={urllib.parse.quote(resource_id)}"
    catalog = _norm(_first_value(item, [
        "tab_code", "tabCode", "catalog", "catalog_type", "catalogType",
        "channel_code", "channelCode",
    ])) or "syncClassroom"
    sub_catalog = _norm(_first_value(item, [
        "sub_catalog", "subCatalog", "sub_catalog_code", "subCatalogCode",
    ]))
    return DETAIL_PAGE.format(
        catalog=urllib.parse.quote(catalog),
        content_type=urllib.parse.quote(content_type),
        id=urllib.parse.quote(resource_id),
        sub_catalog=urllib.parse.quote(sub_catalog),
    )


def _identity_from_url(url: str) -> dict[str, str]:
    if not url.startswith(("http://", "https://")):
        return {}
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    def qv(*names: str) -> str:
        for name in names:
            values = query.get(name)
            if values:
                return _norm(values[0])
        return ""

    path_parts = [p for p in parsed.path.split("/") if p]
    catalog_from_path = path_parts[0] if path_parts else ""
    page_type = path_parts[1] if len(path_parts) > 1 else ""
    resource_id = qv("contentId", "content_id", "resourceId", "resource_id",
                     "activityId", "activity_id", "courseId", "course_id", "id")
    content_type = qv("contentType", "content_type", "resourceType", "resource_type")
    if catalog_from_path == "syncClassroom" and page_type == "classActivity" and not content_type:
        content_type = "national_lesson"
    if catalog_from_path == "qualityCourse" and not content_type:
        content_type = "elite_lesson"
    return {"resource_id": resource_id, "catalog": catalog_from_path, "content_type": content_type}


def _is_search_item_like(item: dict[str, Any]) -> bool:
    has_id = any(item.get(key) for key in [
        "id", "resource_id", "resourceId", "content_id", "contentId",
        "course_id", "courseId",
    ])
    if not has_id:
        ident = _identity_from_url(_detail_page_from_item(item))
        has_id = bool(ident.get("resource_id"))
    has_title = any(item.get(key) for key in [
        "title", "name", "content_name", "contentName",
        "resource_name", "resourceName", "global_title",
    ])
    has_type = any(item.get(key) for key in [
        "catalog", "catalog_type", "catalogType", "tab_code", "tabCode",
        "resource_type", "resourceType", "content_type", "contentType",
    ])
    return bool(has_id and (has_title or has_type))


def _candidate_lists(data: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            dicts = [item for item in node if isinstance(item, dict)]
            if dicts and any(_is_search_item_like(item) for item in dicts):
                found.append(dicts)
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(data)
    return found


def _extract_search_items(data: Any, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [item for group in _candidate_lists(data) for item in group]:
        if not _is_search_item_like(row):
            continue
        key = _norm(_first_value(row, [
            "id", "resource_id", "resourceId", "content_id", "contentId",
            "course_id", "courseId",
        ])) or _identity_from_url(_detail_page_from_item(row)).get("resource_id", "")
        title = _norm(_first_value(row, [
            "title", "name", "content_name", "contentName",
            "resource_name", "resourceName", "global_title",
        ]))
        fingerprint = f"{key}:{title}"
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        items.append(row)
        if len(items) >= limit:
            break
    return items


def _infer_format(item: dict[str, Any], url: str) -> str:
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    fmt = _norm(
        _first_value(item, [
            "format", "file_format", "fileFormat", "resource_format",
            "resourceFormat", "ti_format",
        ]) or extra.get("format")
    ).lower()
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[-1]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
    title_suffix = Path(_clean_html_text(_first_value(item, [
        "title", "name", "content_name", "contentName",
    ]))).suffix.lower().lstrip(".")
    detected = ("jpg" if fmt == "jpeg" else fmt) or suffix or title_suffix
    return detected if detected in RESOURCE_EXTENSIONS else "网页"


def _resource_type_for(fmt: str, item: dict[str, Any]) -> str:
    if fmt in {"ppt", "pptx"}:
        return "课件"
    if fmt in {"jpg", "png", "webp", "gif", "bmp"}:
        return "图片"
    if fmt in {"pdf", "doc", "docx", "txt", "xls", "xlsx"}:
        return "文档"
    if fmt in {"m3u8", "mp4", "mov", "avi", "webm"}:
        return "视频"
    if fmt in {"mp3", "wav", "m4a", "aac", "flac", "ogg"}:
        return "音频"
    return "文档"


def _search_tags(item: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag in item.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        dim = TAG_DIMENSIONS.get(str(tag.get("dimension_id") or tag.get("tag_dimension_id")))
        if dim and dim not in values:
            values[dim] = _clean_html_text(tag.get("title") or tag.get("tag_name"))
    return values


def _provider_name(item: dict[str, Any]) -> str:
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    providers = extra.get("providers") if isinstance(extra.get("providers"), list) else []
    names = [
        _clean_html_text(row.get("name"))
        for row in providers
        if isinstance(row, dict) and _clean_html_text(row.get("name"))
    ]
    return "/".join(names) if names else ""


def _item_to_resource(item: dict[str, Any], query: str) -> dict[str, Any] | None:
    source_url = _detail_page_from_item(item)
    fmt = _infer_format(item, source_url)
    title = _clean_html_text(_first_value(item, [
        "title", "name", "content_name", "contentName",
        "resource_name", "resourceName", "global_title",
    ])) or "SmartEdu 资源"
    tag_values = _search_tags(item)

    resource_type = _norm(_first_value(item, [
        "resource_type_name", "resourceTypeName",
        "content_type_name", "contentTypeName",
    ])) or _resource_type_for(fmt, item)

    description = _clean_html_text(_first_value(item, [
        "description", "summary", "intro", "content", "snippet", "global_description",
    ]))

    provider = _norm(_first_value(item, [
        "provider", "provider_name", "providerName",
        "source_name", "sourceName",
    ])) or _provider_name(item) or "国家中小学智慧教育平台"

    signals: dict[str, Any] = {}
    visit_count = _first_value(item, ["visit_count", "visitCount", "view_count", "viewCount"])
    if isinstance(visit_count, (int, float)):
        signals["views"] = int(visit_count)
    for dim in ("stage", "grade", "subject", "version"):
        val = _norm(tag_values.get(dim))
        if val:
            signals[dim] = val

    published_at = _norm(_first_value(item, [
        "publish_time", "publishTime", "create_time", "createTime",
    ])) or None

    return make_resource(
        platform="smartedu",
        title=title,
        source_url=source_url,
        resource_type=resource_type,
        summary=description or None,
        author=provider,
        published_at=published_at,
        language="zh",
        download_feasibility="低",
        platform_signals=signals or None,
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class SmartEduSearchAdapter:
    """Search SmartEdu via the combine-search POST API."""

    platform_id = "smartedu"
    descriptor = descriptor_for_platform("smartedu")

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    def _build_headers(self, session_data: dict[str, Any] | None) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://basic.smartedu.cn",
            "Referer": "https://basic.smartedu.cn/",
            "sdp-app-id": DEFAULT_SDP_APP_ID,
            "Content-Type": "application/json;charset=UTF-8",
        }
        if session_data:
            tokens = session_data.get("tokens") or {}
            token = tokens.get("accessToken")
            if token:
                raw = token[7:].strip() if token.lower().startswith("bearer ") else token
                headers["Authorization"] = f"Bearer {raw}"
                headers["accessToken"] = raw
            extra = session_data.get("headers") or {}
            headers.update(extra)
        return headers

    def _build_payload(
        self, query: str, limit: int, tabs: list[str] | None = None
    ) -> dict[str, Any]:
        # Request more than the caller's limit because the post-filter
        # (elite_lesson only) discards the majority of raw results.
        fetch_limit = max(limit * 5, 50)
        return {
            "identity": "家长",
            "identity_code": "GUARDIAN",
            "keyword": query,
            "tab_codes": tabs if tabs else DEFAULT_TAB_CODES,
            "cross_tenant": True,
            "duplicate_filter": True,
            "search_order": {"field": "_score", "direction": "desc"},
            "offset": 0,
            "limit": min(fetch_limit, 100),
            "combine_intentions": [],
            "combine_resources": [],
        }

    def _post_search(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any] | None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise _SmartEduError(
                    "AUTH_REQUIRED",
                    f"SmartEdu 搜索认证失败: HTTP {exc.code}；"
                    "如本机保存过智慧教育登录态，可能已过期，请重新登录后再试",
                    False,
                )
            return None
        except (TimeoutError, URLError, json.JSONDecodeError):
            return None

    # -- textbook discovery (0057 M4b) -----------------------------------

    def discover_textbook_courses(self, specs: list[str]) -> list[dict[str, Any]]:
        """Locate national-lesson textbooks by spec and list their courses.

        *specs* look like "学科/年级/册次/版本", e.g. "语文/一年级/上册/统编版".
        Uses the public static CDN JSON endpoints directly — no browser.
        """

        session_data = self.session_store.get_session_data("smartedu")
        headers = self._build_headers(session_data)
        try:
            data_version = self._cdn_json(CDN_DATA_VERSION_URL, headers)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise _SmartEduError(
                "NETWORK_BLOCKED", f"教材索引拉取失败: {type(exc).__name__}", True
            ) from None
        part_urls = [str(u) for u in (data_version.get("urls") or []) if isinstance(u, str)]
        if not part_urls:
            raise _SmartEduError("PARTIAL_FAILURE", "教材索引没有 part 文件", False)

        wanted = [tuple(str(p).strip() for p in spec.split("/")) for spec in specs]
        matched: list[dict[str, Any]] = []
        for part_url in part_urls:
            try:
                items = self._cdn_json(part_url, headers)
            except Exception:  # noqa: BLE001 - one bad part must not kill discovery
                continue
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                tags = {
                    str(t.get("tag_dimension_id") or ""): str(t.get("tag_name") or "")
                    for t in item.get("tag_list") or []
                    if isinstance(t, dict)
                }
                for want in wanted:
                    subject = want[0] if len(want) > 0 else ""
                    grade = want[1] if len(want) > 1 else ""
                    volume = want[2] if len(want) > 2 else ""
                    version = want[3] if len(want) > 3 else ""
                    if (
                        tags.get("zxxxk") == subject
                        and (not grade or tags.get("zxxnj") == grade)
                        and (not volume or tags.get("zxxcc") == volume)
                        and (not version or tags.get("zxxbb") == version)
                        and tags.get("zxxxjjc", "新教材") == "新教材"
                    ):
                        mid = str(item.get("id") or "")
                        if mid and mid not in {m["textbook_id"] for m in matched}:
                            matched.append(
                                {
                                    "textbook_id": mid,
                                    "textbook": str(item.get("title") or mid),
                                }
                            )
                        break
        if not matched:
            raise _SmartEduError(
                "RESOURCE_NOT_FOUND",
                f"未找到匹配教材: {specs}（格式：学科/年级/册次/版本）",
                False,
            )

        courses: list[dict[str, Any]] = []
        for mat in matched:
            mid = mat["textbook_id"]
            try:
                data = self._cdn_json(
                    CDN_MATERIAL_PARTS_TMPL.format(mid=mid, n=100), headers
                )
            except Exception:  # noqa: BLE001
                continue
            for item in data or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("resource_type_code") or "") != "national_lesson":
                    continue
                aid = str(item.get("id") or "")
                title = str(item.get("title") or "").strip()
                if not aid or not title:
                    continue
                courses.append(
                    {
                        "id": aid,
                        "title": title,
                        "textbook": mat["textbook"],
                        "textbook_id": mid,
                    }
                )
        return courses

    def _cdn_json(self, url: str, headers: dict[str, str]) -> Any:
        request = Request(url, headers=headers)
        with urlopen_with_fallback(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    # -- public API ------------------------------------------------------

    def search(
        self, query: str, limit: int, tabs: list[str] | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        results: list[dict[str, Any]] = []
        try:
            session_data = self.session_store.get_session_data("smartedu")
            headers = self._build_headers(session_data)
            payload = self._build_payload(query, limit, tabs)

            data: dict[str, Any] | None = None
            for url in SEARCH_URLS:
                data = self._post_search(url, payload, headers)
                if data is not None:
                    break

            if data is None:
                return [], adapter_error("PARTIAL_FAILURE", "SmartEdu 搜索所有端点均失败", True)

            # Extract as many items as the API returned (not just the caller's
            # limit) because the post-filter discards the majority of results.
            fetch_limit = max(limit * 5, 50)
            items = _extract_search_items(data, min(fetch_limit, 100))
            if not items:
                # Retry without tag filters (wide search).
                wide_payload = dict(payload)
                wide_payload["combine_resources"] = []
                for url in SEARCH_URLS:
                    wide_data = self._post_search(url, wide_payload, headers)
                    if wide_data is not None:
                        items = _extract_search_items(wide_data, search_limit)
                        if items:
                            break

            for item in items:
                # Only return student-facing items with standalone pages:
                # courses (elite_lesson, national_lesson) and teaching materials.
                # Skip sub-assets and teacher-facing items.
                search_rtype = _norm(_first_value(item, ["search_resource_type", "searchResourceType"]))
                rtype = _norm(_first_value(item, ["resource_type", "resourceType", "content_type", "contentType"]))
                if search_rtype not in ("course", "teaching_material"):
                    continue
                if rtype in {
                    "prepare_lesson", "experiment_elite_lesson",
                    "thematic_course", "assets_url",
                }:
                    continue
                resource = _item_to_resource(item, query)
                if resource:
                    results.append(resource)
                if len(results) >= limit:
                    break

            # Textbook materials (tchMaterial) don't appear in combined search;
            # do a dedicated search and merge.
            if len(results) < limit:
                tch_payload = dict(payload)
                tch_payload["tab_codes"] = ["tchMaterial"]
                for url in SEARCH_URLS:
                    tch_data = self._post_search(url, tch_payload, headers)
                    if tch_data is not None:
                        tch_items = _extract_search_items(tch_data, limit)
                        for item in tch_items:
                            resource = _item_to_resource(item, query)
                            if resource:
                                results.append(resource)
                            if len(results) >= limit:
                                break
                        break
            return results, None
        except _SmartEduError as exc:
            # Auth/status failures are adapter facts, not crashes; return
            # them as the error contract so callers can act on the code.
            return results, exc.to_dict()


class _SmartEduError(Exception):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
