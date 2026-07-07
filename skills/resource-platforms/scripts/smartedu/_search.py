#!/usr/bin/env python3
"""SmartEdu 搜索与候选标准化。

Phase 3E 从 smartedu_resources.py 拆出的搜索域：解析搜索响应、按 tag 维度过滤、
搜索项→标准候选、搜索项→详情 identity/URL。detail 域通过 import 复用 identity
函数和 resource_type_for/metadata_confidence（依赖方向 detail→search，单向）。

不依赖 argparse；search_payload（args→dict）留在主文件。
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from _catalog import count_values
from _constants import (
    DETAIL_ENDPOINT_FAMILY,
    DETAIL_PAGE,
    DETAIL_URLS,
    SMARTEDU_FILE_SERVERS,
    TAG_DIMENSIONS,
)
from _text_utils import (
    RESOURCE_EXTENSIONS,
    clean_html_text,
    first_value,
    norm,
    stable_id,
)


def resource_type_for(fmt: str, item: dict[str, Any], detail: dict[str, Any]) -> str:
    if fmt in {"ppt", "pptx"}:
        return "课件"
    if fmt in {"jpg", "png", "webp", "gif", "bmp"}:
        return "图片"
    if fmt in {"pdf", "doc", "docx", "txt", "xls", "xlsx"}:
        return "文档"
    if fmt in {"srt", "vtt"}:
        return "字幕"
    if fmt == "json":
        return "数据"
    if fmt == "superboard":
        return "白板"
    if fmt in {"zip", "rar", "7z"}:
        return "压缩包"
    if fmt in {"m3u8", "mp4", "mov", "avi", "webm"}:
        return "视频"
    if fmt in {"mp3", "wav", "m4a", "aac", "flac", "ogg"}:
        return "音频"
    blob = " ".join(
        [
            fmt,
            norm(item.get("ti_file_flag")),
            norm(item.get("lc_ti_format")),
            norm(detail.get("resource_type_code_name")),
            norm(detail.get("title")),
        ]
    ).lower()
    if "video" in blob or "视频" in blob:
        return "视频"
    if "audio" in blob or "音频" in blob:
        return "音频"
    if "image" in blob:
        return "图片"
    if any(term in blob for term in ["习题", "作业"]):
        return "习题"
    if any(term in blob for term in ["试卷", "考试"]):
        return "试卷"
    return "文档"


def metadata_confidence(candidate: dict[str, Any]) -> float:
    fields = ["title", "source_url", "resource_type", "format", "provider"]
    return round(sum(1 for field in fields if candidate.get(field)) / len(fields), 2)


def grade_to_chinese(value: str) -> str:
    """将年级数字转为中文格式：'1' -> '一年级', '3' -> '三年级'。已是中文则原样返回。"""
    cn_digits = "零一二三四五六七八九十"
    m = re.match(r"^(\d+)$", value)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 12:
            return cn_digits[n] + "年级"
    return value


def candidate_lists(data: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            dicts = [item for item in node if isinstance(item, dict)]
            if dicts and any(is_search_item_like(item) for item in dicts):
                found.append(dicts)
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(data)
    return found


def is_search_item_like(item: dict[str, Any]) -> bool:
    has_id = any(item.get(key) for key in ["id", "resource_id", "resourceId", "content_id", "contentId", "course_id", "courseId"])
    if not has_id:
        has_id = bool(identity_from_detail_page_url(detail_page_from_search_item(item)).get("resource_id"))
    has_title = any(item.get(key) for key in ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"])
    has_type = any(item.get(key) for key in ["catalog", "catalog_type", "catalogType", "tab_code", "tabCode", "resource_type", "resourceType", "content_type", "contentType"])
    return bool(has_id and (has_title or has_type))


def extract_search_items(data: Any, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [item for group in candidate_lists(data) for item in group]:
        if not is_search_item_like(row):
            continue
        key = norm(first_value(row, ["id", "resource_id", "resourceId", "content_id", "contentId", "course_id", "courseId"])) or identity_from_detail_page_url(detail_page_from_search_item(row)).get("resource_id", "")
        title = norm(first_value(row, ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"]))
        fingerprint = f"{key}:{title}"
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        items.append(row)
        if len(items) >= limit:
            break
    return items


def infer_format_from_item(item: dict[str, Any], url: str) -> str:
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    fmt = norm(
        first_value(item, ["format", "file_format", "fileFormat", "resource_format", "resourceFormat", "ti_format"])
        or extra.get("format")
    ).lower()
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[-1]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
    title_suffix = Path(clean_html_text(first_value(item, ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"]))).suffix.lower().lstrip(".")
    detected = ("jpg" if fmt == "jpeg" else fmt) or suffix or title_suffix
    return detected if detected in RESOURCE_EXTENSIONS else "网页"


def search_tags_by_dimension(item: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag in item.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        dim = TAG_DIMENSIONS.get(str(tag.get("dimension_id") or tag.get("tag_dimension_id")))
        if dim and dim not in values:
            values[dim] = clean_html_text(tag.get("title") or tag.get("tag_name"))
    return values


def filter_search_items_by_tags(items: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    """对搜索结果按 tags 做软过滤，保留相关性更高的条目。

    策略：
    - 版本（version）做硬过滤：用户指定"人教版"但条目标记"北师大版"则丢弃。
    - 年级和册次做软过滤（排序优先），不硬丢弃：因为同一单元可能在不同年级/册次
      有同名课程，且搜索关键词可能跨版本匹配。
    - 没有 tag 信息的条目保留。

    当版本硬过滤导致结果清空时，回退到不过滤版本，由 ranker 处理。
    """
    filter_fields = {
        "version": filters.get("version"),
        "grade": filters.get("grade"),
        "volume": filters.get("volume"),
        "stage": filters.get("stage"),
    }
    active_filters = {k: grade_to_chinese(norm(v)) for k, v in filter_fields.items() if v}
    if not active_filters:
        return items

    kept: list[dict[str, Any]] = []
    for item in items:
        tags = search_tags_by_dimension(item)
        drop = False
        for field, expected in active_filters.items():
            actual = norm(tags.get(field))
            if not actual:
                # 条目没有该维度 tag，保留
                continue
            if not tag_value_matches(actual, expected):
                # 只有 version 不匹配时硬过滤，其他维度软过滤（保留）
                if field == "version":
                    drop = True
                    break
                # grade/volume/stage 不匹配时保留，但不算精确匹配
        if not drop:
            kept.append(item)

    # 版本硬过滤导致结果清空时，回退到不做版本过滤，让 ranker 处理
    if not kept and "version" in active_filters and items:
        version_value = active_filters["version"]
        for item in items:
            tags = search_tags_by_dimension(item)
            actual = norm(tags.get("version"))
            if not actual or tag_value_matches(actual, version_value):
                kept.append(item)
        # 如果去掉版本过滤还是空，保留全部原始结果
        if not kept:
            kept = list(items)

    return kept


def tag_value_matches(actual: str, expected: str) -> bool:
    """宽松匹配 tag 值，处理常见变体如"一年级"/"1年级"/"一年级上"等。"""
    if actual == expected:
        return True
    # 数字与中文数字互转
    cn_digits = "零一二三四五六七八九十"
    def normalize_grade(s: str) -> str:
        s = norm(s)
        # "1年级" -> "一年级"
        m = re.match(r"(\d+)\s*年级", s)
        if m and int(m.group(1)) <= 12:
            return cn_digits[int(m.group(1))] + "年级"
        return s
    if normalize_grade(actual) == normalize_grade(expected):
        return True
    # 子串包含："上册" 匹配 "一年级上册" 中的册次
    if expected in actual or actual in expected:
        return True
    return False


def search_provider_name(item: dict[str, Any]) -> str:
    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    providers = extra.get("providers") if isinstance(extra.get("providers"), list) else []
    names = [clean_html_text(row.get("name")) for row in providers if isinstance(row, dict) and clean_html_text(row.get("name"))]
    return "/".join(names) if names else ""


def is_stable_search_page_item(item: dict[str, Any]) -> bool:
    search_resource_type = norm(first_value(item, ["search_resource_type", "searchResourceType"]))
    resource_type = norm(first_value(item, ["resource_type", "resourceType", "content_type", "contentType"]))
    return search_resource_type == "course" and resource_type in {"elite_lesson", "national_lesson"}


def filter_stable_search_page_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if is_stable_search_page_item(item)]


def detail_page_from_search_item(item: dict[str, Any]) -> str:
    explicit = norm(first_value(item, ["url", "web_url", "webUrl", "href", "detail_url", "detailUrl", "share_url", "shareUrl"]))
    if explicit.startswith("http"):
        return explicit
    resource_id = norm(first_value(item, ["id", "resource_id", "resourceId", "content_id", "contentId", "course_id", "courseId"]))
    catalog = norm(first_value(item, ["catalog", "catalog_type", "catalogType", "tab_code", "tabCode", "channel_code", "channelCode"])) or "syncClassroom"
    sub_catalog = norm(first_value(item, ["sub_catalog", "subCatalog", "sub_catalog_code", "subCatalogCode"]))
    content_type = norm(first_value(item, ["content_type", "contentType", "resource_type", "resourceType", "resource_type_code", "resourceTypeCode"])) or "resource"
    if content_type == "national_lesson":
        return f"https://basic.smartedu.cn/syncClassroom/classActivity?activityId={urllib.parse.quote(resource_id)}"
    if content_type == "elite_lesson":
        return f"https://basic.smartedu.cn/qualityCourse?courseId={urllib.parse.quote(resource_id)}"
    if content_type == "prepare_lesson":
        return f"https://basic.smartedu.cn/syncClassroom/prepare/detail?resourceId={urllib.parse.quote(resource_id)}"
    return DETAIL_PAGE.format(
        catalog=urllib.parse.quote(catalog),
        content_type=urllib.parse.quote(content_type),
        id=urllib.parse.quote(resource_id),
        sub_catalog=urllib.parse.quote(sub_catalog),
    )


def explicit_detail_json_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def walk(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, key)
        elif isinstance(node, list):
            for value in node:
                walk(value, key_hint)
        elif isinstance(node, str):
            value = html.unescape(node.strip())
            if not value.startswith(("http://", "https://")):
                return
            lowered_key = key_hint.lower()
            lowered_value = value.lower()
            if (("detail" in lowered_key or "json" in lowered_key) and ".json" in lowered_value) or "/details/" in lowered_value:
                urls.append(value)

    walk(item)
    return list(dict.fromkeys(urls))


def identity_from_detail_page_url(url: str) -> dict[str, str]:
    if not url.startswith(("http://", "https://")):
        return {}
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    def query_value(*names: str) -> str:
        for name in names:
            values = query.get(name)
            if values:
                return norm(values[0])
        return ""

    path_parts = [part for part in parsed.path.split("/") if part]
    catalog_from_path = path_parts[0] if path_parts else ""
    page_type = path_parts[1] if len(path_parts) > 1 else ""
    resource_id = query_value("contentId", "content_id", "resourceId", "resource_id", "activityId", "activity_id", "courseId", "course_id", "id")
    content_type = query_value("contentType", "content_type", "resourceType", "resource_type")
    if catalog_from_path == "syncClassroom" and page_type == "classActivity" and not content_type:
        content_type = "national_lesson"
    if catalog_from_path == "qualityCourse" and not content_type:
        content_type = "elite_lesson"
    return {
        "resource_id": resource_id,
        "tab_code": query_value("tabCode", "tab_code", "catalogType", "catalog") or catalog_from_path,
        "catalog": query_value("catalogType", "catalog") or catalog_from_path,
        "sub_catalog": query_value("subCatalog", "sub_catalog"),
        "content_type": content_type,
    }


def search_item_to_candidate(item: dict[str, Any], query: str, filters: dict[str, Any]) -> dict[str, Any]:
    source_url = detail_page_from_search_item(item)
    fmt = infer_format_from_item(item, source_url)
    title = clean_html_text(first_value(item, ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"])) or "SmartEdu 资源"
    catalog = norm(first_value(item, ["catalog", "catalog_type", "catalogType", "tab_code", "tabCode", "channel_code", "channelCode"]))
    resource_id = norm(first_value(item, ["id", "resource_id", "resourceId", "content_id", "contentId", "course_id", "courseId"])) or stable_id(title + source_url)
    tag_values = search_tags_by_dimension(item)
    candidate = {
        "source": "smartedu",
        "source_name": "国家中小学智慧教育平台",
        "source_url": source_url,
        "resource_id": f"smartedu:{resource_id}",
        "title": title,
        "description": clean_html_text(first_value(item, ["description", "summary", "intro", "content", "snippet", "global_description"])),
        "resource_type": norm(first_value(item, ["resource_type_name", "resourceTypeName", "content_type_name", "contentTypeName"])) or resource_type_for(fmt, {}, item),
        "format": fmt,
        "stage": norm(first_value(item, ["stage", "phase", "school_section"])) or tag_values.get("stage") or filters.get("stage"),
        "grade": norm(first_value(item, ["grade", "grade_name", "gradeName"])) or tag_values.get("grade") or filters.get("grade"),
        "subject": norm(first_value(item, ["subject", "subject_name", "subjectName"])) or tag_values.get("subject") or filters.get("subject"),
        "learning_domain": norm(first_value(item, ["subject", "subject_name", "subjectName"])) or tag_values.get("subject") or filters.get("learning_domain") or filters.get("subject"),
        "version": norm(first_value(item, ["version", "version_name", "versionName"])) or tag_values.get("version") or filters.get("version"),
        "volume": norm(first_value(item, ["volume", "book", "book_name", "bookName"])) or tag_values.get("volume") or filters.get("volume"),
        "topic": filters.get("core_topic") or query,
        "provider": norm(first_value(item, ["provider", "provider_name", "providerName", "source_name", "sourceName"])) or search_provider_name(item) or "国家中小学智慧教育平台",
        "official": True,
        "downloadable": False,
        "requires_auth": False,
        "metadata_confidence": 0.0,
        "raw": {
            "detail_page": source_url,
            "smartedu_catalog": catalog,
            "smartedu_search_item": item,
            "warnings": ["搜索结果候选尚未解析详情文件项"],
        },
    }
    visit_count = first_value(item, ["visit_count", "visitCount", "view_count", "viewCount"])
    if isinstance(visit_count, (int, float)):
        candidate["platform_signals"] = {"views": int(visit_count)}
    publish_time = norm(first_value(item, ["publish_time", "publishTime", "create_time", "createTime"] ))
    if publish_time:
        candidate["publish_time"] = publish_time
    candidate["metadata_confidence"] = metadata_confidence(candidate)
    return candidate


def search_item_identity(item: dict[str, Any]) -> dict[str, str]:
    page_identity = identity_from_detail_page_url(detail_page_from_search_item(item))
    catalog = norm(first_value(item, ["catalog", "catalog_type", "catalogType", "tab_code", "tabCode", "channel_code", "channelCode"])) or page_identity.get("catalog") or "syncClassroom"
    resource_type = norm(first_value(item, ["resource_type", "resourceType", "resource_type_code", "resourceTypeCode", "content_type", "contentType"]))
    content_type = norm(first_value(item, ["content_type", "contentType"])) or resource_type or page_identity.get("content_type", "")
    if resource_type == "national_lesson":
        catalog = "syncClassroom"
        content_type = "national_lesson"
    elif resource_type == "elite_lesson":
        catalog = "qualityCourse"
        content_type = "elite_lesson"
    elif resource_type == "prepare_lesson":
        catalog = "prepareLesson"
        content_type = "prepare_lesson"
    return {
        "resource_id": norm(first_value(item, ["id", "resource_id", "resourceId", "content_id", "contentId", "course_id", "courseId"])) or page_identity.get("resource_id", ""),
        "tab_code": norm(first_value(item, ["tab_code", "tabCode", "channel_code", "channelCode"])) or page_identity.get("tab_code", "") or catalog,
        "catalog": catalog,
        "sub_catalog": norm(first_value(item, ["sub_catalog", "subCatalog", "sub_catalog_code", "subCatalogCode"])) or page_identity.get("sub_catalog", ""),
        "content_type": content_type,
        "resource_type": resource_type,
        "resource_type_name": clean_html_text(first_value(item, ["resource_type_name", "resourceTypeName", "content_type_name", "contentTypeName"])),
    }


def detail_urls_for_identity(identity: dict[str, str]) -> list[dict[str, str]]:
    resource_id = identity.get("resource_id") or ""
    catalog = identity.get("catalog") or "syncClassroom"
    tab_code = identity.get("tab_code") or catalog
    content_type = identity.get("content_type") or identity.get("resource_type") or ""
    if not resource_id:
        return []
    urls: list[dict[str, str]] = []
    special_templates: list[tuple[str, str]] = []
    if catalog == "syncClassroom" or tab_code in {"syncClassroom", "classActivity"} or content_type == "national_lesson":
        special_templates.append(("s-file-ndrv2-national-lesson-detail", "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/national_lesson/resources/details/{id}.json"))
    if catalog in {"prepareLesson", "prepare_lesson"} or tab_code in {"prepareLesson", "prepare_lesson"} or content_type == "prepare_lesson":
        special_templates.append(("s-file-ndrv2-prepare-sub-type-detail", "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/prepare_sub_type/resources/details/{id}.json"))
    if catalog == "qualityCourse" or tab_code == "qualityCourse" or content_type == "elite_lesson":
        special_templates.append(("s-file-ndrv2-quality-course-detail", "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/resources/{id}.json"))
    if catalog == "tchMaterial" or tab_code == "tchMaterial":
        special_templates.append(("s-file-ndrv2-tch-material-detail", "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{id}.json"))

    seen: set[str] = set()
    for family, template in special_templates:
        for index, server in enumerate(SMARTEDU_FILE_SERVERS, 1):
            url = template.format(server=server, id=urllib.parse.quote(resource_id))
            if url in seen:
                continue
            seen.add(url)
            urls.append(
                {
                    "url": url,
                    "endpoint_family": family,
                    "template_index": f"special-{index}",
                }
            )
    for index, template in enumerate(DETAIL_URLS, 1):
        url = template.format(catalog=urllib.parse.quote(catalog), id=urllib.parse.quote(resource_id))
        if url in seen:
            continue
        seen.add(url)
        urls.append(
            {
                "url": url,
                "endpoint_family": DETAIL_ENDPOINT_FAMILY,
                "template_index": str(index),
            }
        )
    return urls


def values_from_candidates(candidates: list[dict[str, Any]], field: str) -> list[str]:
    return [norm(candidate.get(field)) for candidate in candidates if norm(candidate.get(field))]


def search_model_context(items: list[dict[str, Any]], candidates: list[dict[str, Any]], query: str, filters: dict[str, Any]) -> dict[str, Any]:
    dimensions = {
        "stage": count_values(values_from_candidates(candidates, "stage")),
        "grade": count_values(values_from_candidates(candidates, "grade")),
        "subject": count_values(values_from_candidates(candidates, "subject")),
        "version": count_values(values_from_candidates(candidates, "version")),
        "volume": count_values(values_from_candidates(candidates, "volume")),
        "resource_type": count_values(values_from_candidates(candidates, "resource_type")),
        "format": count_values(values_from_candidates(candidates, "format")),
        "provider": count_values(values_from_candidates(candidates, "provider")),
    }
    ambiguity: list[dict[str, Any]] = []
    for field in ["grade", "subject", "version", "volume", "resource_type", "provider"]:
        values = dimensions.get(field) or {}
        specified = norm(filters.get(field))
        if len(values) > 1 and not specified:
            ambiguity.append({"field": field, "values": values})

    detail_options: list[dict[str, Any]] = []
    for index, item in enumerate(items[:12], 1):
        identity = search_item_identity(item)
        detail_url = detail_page_from_search_item(item)
        title = clean_html_text(first_value(item, ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"])) or "SmartEdu 资源"
        tag_values = search_tags_by_dimension(item)
        detail_options.append(
            {
                "rank": index,
                "title": title,
                "detail_page": detail_url,
                "resource_id": identity.get("resource_id"),
                "tab_code": identity.get("tab_code"),
                "catalog": identity.get("catalog"),
                "content_type": identity.get("content_type"),
                "resource_type": identity.get("resource_type") or identity.get("resource_type_name"),
                "stage": tag_values.get("stage"),
                "grade": tag_values.get("grade"),
                "subject": tag_values.get("subject"),
                "version": tag_values.get("version"),
                "volume": tag_values.get("volume"),
                "provider": search_provider_name(item),
                "next_command": f"candidates-from-detail --url {json.dumps(detail_url, ensure_ascii=False)}",
            }
        )

    return {
        "purpose": "给模型做需求澄清、范围判断和下一步工具调用决策；脚本不替模型硬编码上册/下册/版本选择。",
        "query": query,
        "detected_dimensions": dimensions,
        "ambiguity": ambiguity,
        "coverage_hint": "用户表达全部/整套/完整覆盖时，模型应按课程包、资源类型、主题范围和来源维度聚合；测试取样时可选择最相关详情页。",
        "detail_options": detail_options,
        "suggested_model_actions": [
            "需求范围不明确时优先追问学习主题、资源类型、使用场景或覆盖范围",
            "只有用户明确要求指定教材或唯一定位资源时，才追问版本、出版社或册次",
            "用户要求完整覆盖时不要只取第一条，应按课程包、resource_type、主题范围和来源分组后批量展开详情",
            "测试取样时可选 detail_options[0] 继续 candidates-from-detail",
        ],
    }
