#!/usr/bin/env python3
"""SmartEdu 详情探测与详情候选标准化。

Phase 3E 从 smartedu_resources.py 拆出的详情域：探测搜索候选能否展开详情 JSON、
抓取详情、解析 ti_items 为标准候选、详情探测矩阵汇总。依赖方向单向：
_detail → _search（identity/resource_type_for/metadata_confidence）。
命令处理 run_candidates_from_detail/run_detail_probe 留主文件，通过 import 调用。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from _auth_http import browser_request_json_status, request_json, request_json_status
from _catalog import count_values
from _constants import (
    DETAIL_ENDPOINT_FAMILY,
    DETAIL_PAGE,
    PRIVATE_HOST,
    PRIVATE_NDR_RE,
    PUBLIC_HOSTS,
    TAG_DIMENSIONS,
)
from _search import (
    detail_page_from_search_item,
    detail_urls_for_identity,
    explicit_detail_json_urls,
    identity_from_detail_page_url,
    metadata_confidence,
    resource_type_for,
    search_item_identity,
)
from _text_utils import clean_html_text, first_value, load_json, norm, quote_url_path, stable_id


def safe_detail_page(detail: dict[str, Any], catalog: str, sub_catalog: str) -> str:
    resource_id = norm(detail.get("id"))
    content_type = norm(detail.get("resource_type_code")) or "resource"
    if catalog == "syncClassroom" and content_type == "national_lesson":
        return f"https://basic.smartedu.cn/syncClassroom/classActivity?activityId={urllib.parse.quote(resource_id)}"
    if catalog == "qualityCourse" and content_type == "elite_lesson":
        return f"https://basic.smartedu.cn/qualityCourse?courseId={urllib.parse.quote(resource_id)}"
    return DETAIL_PAGE.format(
        catalog=urllib.parse.quote(catalog or "syncClassroom"),
        content_type=urllib.parse.quote(content_type),
        id=urllib.parse.quote(resource_id),
        sub_catalog=urllib.parse.quote(sub_catalog or ""),
    )


def provider_name(detail: dict[str, Any]) -> str:
    providers = detail.get("provider_list") or []
    names = [norm(item.get("name")) for item in providers if isinstance(item, dict) and norm(item.get("name"))]
    return "/".join(names) if names else "国家中小学智慧教育平台"


def tags_by_dimension(detail: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag in detail.get("tag_list") or []:
        if not isinstance(tag, dict):
            continue
        dim = TAG_DIMENSIONS.get(str(tag.get("tag_dimension_id")))
        if dim and dim not in values:
            values[dim] = norm(tag.get("tag_name"))
    return values


def requirement_value(item: dict[str, Any], name: str) -> Any:
    custom = item.get("custom_properties") or {}
    for req in custom.get("requirements") or []:
        if isinstance(req, dict) and str(req.get("name")).lower() == name.lower():
            return req.get("value")
    return None


def storage_urls(item: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    storage = norm(item.get("ti_storage"))
    if storage.startswith("cs_path:${ref-path}"):
        suffix = storage.replace("cs_path:${ref-path}", "")
        candidates.append(PRIVATE_HOST + urllib.parse.quote(urllib.parse.unquote(suffix), safe="/:"))
        for host in PUBLIC_HOSTS:
            candidates.append(host + urllib.parse.quote(urllib.parse.unquote(suffix), safe="/:"))
    for url in item.get("ti_storages") or []:
        if not isinstance(url, str) or not url:
            continue
        candidates.append(quote_url_path(url))
        candidates.append(quote_url_path(PRIVATE_NDR_RE.sub(PUBLIC_HOSTS[0], url)))
    unique: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def item_requires_auth(item: dict[str, Any], urls: list[str]) -> bool:
    custom = item.get("custom_properties") or {}
    if custom.get("identification") is True:
        return True
    return any("ndr-private" in url for url in urls)


def normalized_format(item: dict[str, Any], url: str) -> str:
    fmt = norm(item.get("ti_format") or item.get("lc_ti_format")).lower()
    if fmt in {"application/x-mpegurl", "application/vnd.apple.mpegurl"}:
        return "m3u8"
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[-1]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
    if fmt in {"folder", "source", ""} and suffix:
        fmt = suffix
    if fmt == "jpeg":
        return "jpg"
    return fmt or suffix or "unknown"


def detail_url_attempts_for_search_item(item: dict[str, Any], identity: dict[str, str]) -> list[dict[str, str]]:
    attempts: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, url in enumerate(explicit_detail_json_urls(item), 1):
        if url in seen:
            continue
        seen.add(url)
        attempts.append(
            {
                "url": url,
                "endpoint_family": "search-item-detail-json",
                "template_index": f"explicit-{index}",
            }
        )
    for attempt in detail_urls_for_identity(identity):
        url = attempt["url"]
        if url in seen:
            continue
        seen.add(url)
        attempts.append(attempt)
    return attempts


def classify_detail_probe(
    status: int | None,
    detail: dict[str, Any] | None,
    error: str,
    offline: bool = False,
) -> str:
    if offline and detail is None:
        return "detail_not_found_in_dir"
    if detail is not None:
        items = detail.get("ti_items")
        if isinstance(items, list) and items:
            return "ok_with_file_items"
        return "ok_no_file_items"
    if status == 403:
        return "requires_auth"
    if status == 404:
        return "not_found"
    if status is None:
        return "request_failed"
    if error:
        return "invalid_json" if "json decode failed" in error else "request_failed"
    return "unknown"


def detail_access_policy(status: str, via_browser: bool = False) -> str:
    if status in {"ok_with_file_items", "ok_no_file_items"}:
        if via_browser:
            return "browser_session_detail"
        return "public_detail"
    if status == "requires_auth":
        return "requires_auth_context"
    if status in {"detail_not_found_in_dir", "not_found"}:
        return "unavailable_or_template_unknown"
    return "runtime_validation_needed"


def detail_summary_for_probe(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "detail_status": probe.get("detail_status") or "unknown",
        "detail_access_policy": probe.get("detail_access_policy") or "runtime_validation_needed",
        "detail_endpoint_family": probe.get("detail_endpoint_family") or DETAIL_ENDPOINT_FAMILY,
        "file_item_count": int(probe.get("file_item_count") or 0),
        "parsed_candidate_count": int(probe.get("parsed_candidate_count") or 0),
        "attempt_count": len(probe.get("attempts") or []),
        "error": probe.get("error") or "",
    }


def annotate_candidate_detail(candidate: dict[str, Any], detail_summary: dict[str, Any]) -> dict[str, Any]:
    raw = candidate.setdefault("raw", {})
    if isinstance(raw, dict):
        raw["smartedu_detail"] = detail_summary
    return candidate


def detail_failure_for_probe(probe: dict[str, Any], identity: dict[str, str]) -> dict[str, Any]:
    summary = detail_summary_for_probe(probe)
    return {
        "resource_id": identity.get("resource_id", ""),
        "catalog": identity.get("catalog", ""),
        "detail_status": summary["detail_status"],
        "detail_access_policy": summary["detail_access_policy"],
        "detail_endpoint_family": summary["detail_endpoint_family"],
        "file_item_count": summary["file_item_count"],
        "error": summary["error"] or summary["detail_status"],
    }


def detail_matrix_conclusion(status_counts: dict[str, int], access_policy_counts: dict[str, int]) -> str:
    if status_counts.get("ok_with_file_items", 0) > 0:
        return "公开可取"
    if status_counts.get("ok_no_file_items", 0) > 0:
        return "无文件项"
    if status_counts.get("requires_auth", 0) > 0 or access_policy_counts.get("requires_auth_context", 0) > 0:
        return "需要授权"
    if status_counts.get("detail_not_found_in_dir", 0) > 0 or status_counts.get("not_found", 0) > 0:
        return "模板未知"
    if status_counts.get("missing_resource_id", 0) > 0:
        return "模板未知"
    return "需运行时验证"


def detail_probe_matrix(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for probe in probes:
        tab_code = norm(probe.get("tab_code"))
        resource_type = norm(probe.get("resource_type"))
        resource_type_name = norm(probe.get("resource_type_name"))
        catalog = norm(probe.get("catalog"))
        sub_catalog = norm(probe.get("sub_catalog"))
        content_type = norm(probe.get("content_type"))
        key = "|".join([tab_code, resource_type, resource_type_name, catalog, sub_catalog, content_type])
        group = groups.setdefault(
            key,
            {
                "tab_code": tab_code,
                "resource_type": resource_type,
                "resource_type_name": resource_type_name,
                "catalog": catalog,
                "sub_catalog": sub_catalog,
                "content_type": content_type,
                "detail_endpoint_family": probe.get("detail_endpoint_family") or DETAIL_ENDPOINT_FAMILY,
                "detail_url_templates": probe.get("detail_url_templates") or [],
                "resource_ids": [],
                "probe_count": 0,
                "detail_status_values": [],
                "detail_access_policy_values": [],
                "file_item_count": 0,
                "parsed_candidate_count": 0,
            },
        )
        if probe.get("resource_id"):
            group["resource_ids"].append(probe.get("resource_id"))
        group["probe_count"] += 1
        group["detail_status_values"].append(norm(probe.get("detail_status")))
        group["detail_access_policy_values"].append(norm(probe.get("detail_access_policy")))
        group["file_item_count"] += int(probe.get("file_item_count") or 0)
        group["parsed_candidate_count"] += int(probe.get("parsed_candidate_count") or 0)
    matrix: list[dict[str, Any]] = []
    for group in groups.values():
        status_counts = count_values(group.pop("detail_status_values"))
        access_policy_counts = count_values(group.pop("detail_access_policy_values"))
        resource_ids = list(dict.fromkeys(group.pop("resource_ids")))
        group["search_items_seen"] = int(group.pop("probe_count") or 0)
        group["sample_resource_ids"] = resource_ids[:5]
        group["detail_status_counts"] = status_counts
        group["detail_access_policy_counts"] = access_policy_counts
        group["conclusion"] = detail_matrix_conclusion(status_counts, access_policy_counts)
        matrix.append(group)
    return sorted(matrix, key=lambda item: (item.get("tab_code") or "", item.get("resource_type") or "", item.get("content_type") or ""))


def probe_detail_for_search_item(
    item: dict[str, Any],
    args: argparse.Namespace,
    access_token: str | None,
    extra_headers: dict[str, str],
) -> dict[str, Any]:
    identity = search_item_identity(item)
    title = clean_html_text(first_value(item, ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"]))
    result: dict[str, Any] = {
        "resource_id": identity.get("resource_id") or "",
        "title": title,
        "tab_code": identity.get("tab_code") or "",
        "catalog": identity.get("catalog") or "",
        "sub_catalog": identity.get("sub_catalog") or "",
        "content_type": identity.get("content_type") or "",
        "resource_type": identity.get("resource_type") or "",
        "resource_type_name": identity.get("resource_type_name") or "",
        "detail_page": detail_page_from_search_item(item),
        "detail_endpoint_family": DETAIL_ENDPOINT_FAMILY,
        "detail_url_templates": [attempt["url"] for attempt in detail_url_attempts_for_search_item(item, identity)],
        "detail_status": "missing_resource_id" if not identity.get("resource_id") else "not_attempted",
        "detail_access_policy": "template_unknown" if not identity.get("resource_id") else "runtime_validation_needed",
        "attempts": [],
        "file_item_count": 0,
        "parsed_candidate_count": 0,
        "error": "",
    }
    if not identity.get("resource_id"):
        result["error"] = "missing resource id"
        return result

    cached = load_detail_from_dir(args.detail_dir, identity)
    if cached is not None:
        candidates, seen, skipped = candidates_from_detail(cached, identity["catalog"], identity["sub_catalog"], {})
        status = classify_detail_probe(200, cached, "")
        result.update(
            {
                "detail_status": status,
                "detail_access_policy": detail_access_policy(status),
                "attempts": [
                    {
                        "source": "detail_dir",
                        "status": 200,
                        "content_type": "application/json",
                        "has_json": True,
                        "has_ti_items": isinstance(cached.get("ti_items"), list),
                        "ti_items": seen,
                        "skipped_items": skipped,
                        "error": "",
                    }
                ],
                "file_item_count": seen,
                "parsed_candidate_count": len(candidates),
            }
        )
        return result
    if args.offline_details_only:
        status = classify_detail_probe(None, None, "", offline=True)
        result.update({"detail_status": status, "detail_access_policy": detail_access_policy(status), "error": "detail not found in detail dir"})
        return result

    for attempt in detail_url_attempts_for_search_item(item, identity):
        detail, status_code, content_type, error = request_json_status(
            attempt["url"],
            access_token=access_token,
            timeout=args.timeout,
            cookie=args.cookie,
            extra_headers=extra_headers,
        )
        candidates: list[dict[str, Any]] = []
        seen = 0
        skipped = 0
        if detail is not None:
            candidates, seen, skipped = candidates_from_detail(detail, identity["catalog"], identity["sub_catalog"], {})
        classified = classify_detail_probe(status_code, detail, error)
        result["attempts"].append(
            {
                "url": attempt["url"],
                "endpoint_family": attempt["endpoint_family"],
                "template_index": attempt["template_index"],
                "status": status_code,
                "content_type": content_type,
                "has_json": detail is not None,
                "has_ti_items": bool(detail is not None and isinstance(detail.get("ti_items"), list)),
                "ti_items": seen,
                "skipped_items": skipped,
                "error": error,
                "classified_status": classified,
            }
        )
        if detail is not None:
            result.update(
                {
                    "detail_status": classified,
                    "detail_access_policy": detail_access_policy(classified),
                    "detail_endpoint_family": attempt["endpoint_family"],
                    "file_item_count": seen,
                    "parsed_candidate_count": len(candidates),
                    "error": error,
                }
            )
            break
        if getattr(args, "browser_state", None) and classified in {"requires_auth", "request_failed"}:
            browser_detail, browser_status, browser_content_type, browser_error = browser_request_json_status(attempt["url"], args.browser_state, timeout=args.timeout)
            browser_candidates: list[dict[str, Any]] = []
            browser_seen = 0
            browser_skipped = 0
            if browser_detail is not None:
                browser_candidates, browser_seen, browser_skipped = candidates_from_detail(browser_detail, identity["catalog"], identity["sub_catalog"], {})
            browser_classified = classify_detail_probe(browser_status, browser_detail, browser_error)
            result["attempts"].append(
                {
                    "source": "browser_state",
                    "url": attempt["url"],
                    "endpoint_family": attempt["endpoint_family"],
                    "template_index": attempt["template_index"],
                    "status": browser_status,
                    "content_type": browser_content_type,
                    "has_json": browser_detail is not None,
                    "has_ti_items": bool(browser_detail is not None and isinstance(browser_detail.get("ti_items"), list)),
                    "ti_items": browser_seen,
                    "skipped_items": browser_skipped,
                    "error": browser_error,
                    "classified_status": browser_classified,
                }
            )
            if browser_detail is not None:
                result.update(
                    {
                        "detail_status": browser_classified,
                        "detail_access_policy": detail_access_policy(browser_classified, via_browser=True),
                        "detail_endpoint_family": attempt["endpoint_family"],
                        "file_item_count": browser_seen,
                        "parsed_candidate_count": len(browser_candidates),
                        "error": browser_error,
                    }
                )
                break
        if status_code in {403, 404}:
            result.update(
                {
                    "detail_status": classified,
                    "detail_access_policy": detail_access_policy(classified),
                    "detail_endpoint_family": attempt["endpoint_family"],
                    "file_item_count": seen,
                    "parsed_candidate_count": len(candidates),
                    "error": error,
                }
            )
            if status_code == 404:
                break
    if result["detail_status"] == "not_attempted" and result["attempts"]:
        last = result["attempts"][-1]
        status = classify_detail_probe(last.get("status"), None, last.get("error") or "")
        result.update(
            {
                "detail_status": status,
                "detail_access_policy": detail_access_policy(status),
                "detail_endpoint_family": last.get("endpoint_family") or DETAIL_ENDPOINT_FAMILY,
                "error": last.get("error") or "",
            }
        )
    return result


def fetch_detail_for_search_item(
    item: dict[str, Any],
    identity: dict[str, str],
    args: argparse.Namespace,
    access_token: str | None,
    extra_headers: dict[str, str],
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in detail_url_attempts_for_search_item(item, identity):
        detail, status_code, _content_type, error = request_json_status(
            attempt["url"],
            access_token=access_token,
            timeout=getattr(args, "timeout", 20),
            cookie=args.cookie,
            extra_headers=extra_headers,
        )
        if detail is not None:
            return detail
        errors.append(f"{attempt['url']}: status={status_code} error={error}")
        if getattr(args, "browser_state", None) and status_code in {None, 403}:
            browser_detail, browser_status, _browser_content_type, browser_error = browser_request_json_status(attempt["url"], args.browser_state, timeout=getattr(args, "timeout", 20))
            if browser_detail is not None:
                return browser_detail
            errors.append(f"browser_state {attempt['url']}: status={browser_status} error={browser_error}")
    raise RuntimeError("; ".join(errors) or "no detail urls to try")


def load_detail_from_dir(detail_dir: str | None, identity: dict[str, str]) -> dict[str, Any] | None:
    if not detail_dir:
        return None
    root = Path(detail_dir)
    resource_id = identity["resource_id"]
    catalog = identity["catalog"]
    candidates = [
        root / f"{resource_id}.json",
        root / f"{catalog}-{resource_id}.json",
        root / catalog / f"{resource_id}.json",
    ]
    for path in candidates:
        if path.exists():
            data = load_json(str(path))
            if isinstance(data, dict):
                return data
    return None


def detail_for_search_item(
    item: dict[str, Any],
    args: argparse.Namespace,
    access_token: str | None,
    extra_headers: dict[str, str],
) -> tuple[dict[str, Any] | None, dict[str, str], str | None, dict[str, Any]]:
    identity = search_item_identity(item)
    if not identity["resource_id"]:
        probe = probe_detail_for_search_item(item, args, access_token, extra_headers)
        return None, identity, "missing resource id", probe
    cached = load_detail_from_dir(args.detail_dir, identity)
    if cached is not None:
        probe = probe_detail_for_search_item(item, args, access_token, extra_headers)
        return cached, identity, None, probe
    if args.offline_details_only:
        probe = probe_detail_for_search_item(item, args, access_token, extra_headers)
        return None, identity, "detail not found in detail dir", probe
    probe = probe_detail_for_search_item(item, args, access_token, extra_headers)
    if probe.get("detail_status") in {"ok_with_file_items", "ok_no_file_items"}:
        cached_after_probe = load_detail_from_dir(args.detail_dir, identity)
        if cached_after_probe is not None:
            return cached_after_probe, identity, None, probe
    try:
        return (
            fetch_detail_for_search_item(item, identity, args, access_token, extra_headers),
            identity,
            None,
            probe,
        )
    except Exception as exc:
        if not probe.get("error"):
            probe["error"] = str(exc)
        return None, identity, str(exc), probe


def candidate_title(detail: dict[str, Any], item: dict[str, Any], fmt: str) -> str:
    title = norm(detail.get("title") or detail.get("global_title"))
    custom = detail.get("custom_properties") if isinstance(detail.get("custom_properties"), dict) else {}
    original_title = norm(custom.get("original_title") or custom.get("alias_name"))
    if original_title and original_title not in title:
        title = f"{title} - {original_title}" if title else original_title
    flag = norm(item.get("ti_file_flag"))
    if flag and flag not in {"source", "href", "href-m3u8"}:
        return f"{title} - {flag}"
    if fmt and fmt != "unknown":
        return f"{title} - {fmt.upper()}"
    return title or norm(detail.get("id")) or "SmartEdu 资源"


def relation_resource_details(detail: dict[str, Any]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    if isinstance(detail.get("ti_items"), list):
        resources.append(detail)

    relations = detail.get("relations") if isinstance(detail.get("relations"), dict) else {}
    relation_keys = [
        "national_course_resource",
        "course_resource",
        "resources",
        "resource",
    ]
    for key in relation_keys:
        rows = relations.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("ti_items"), list):
                continue
            merged = dict(detail)
            merged.update(row)
            if not merged.get("provider_list") and detail.get("provider_list"):
                merged["provider_list"] = detail.get("provider_list")
            if not merged.get("tag_list") and detail.get("tag_list"):
                merged["tag_list"] = detail.get("tag_list")
            resources.append(merged)

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for resource in resources:
        key = norm(resource.get("id")) or stable_id(json.dumps(resource.get("ti_items") or [], ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append(resource)
    return unique


def candidates_from_detail(detail: dict[str, Any], catalog: str, sub_catalog: str, filters: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], int, int]:
    filters = filters or {}
    candidates: list[dict[str, Any]] = []
    skipped = 0
    total_items = 0
    for resource_detail in relation_resource_details(detail):
        dimensions = tags_by_dimension(resource_detail) or tags_by_dimension(detail)
        detail_page = safe_detail_page(resource_detail, catalog or norm(resource_detail.get("catalog")), sub_catalog)
        provider = provider_name(resource_detail)
        items = resource_detail.get("ti_items") or []
        total_items += len(items)
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                skipped += 1
                continue
            urls = storage_urls(item)
            if not urls:
                skipped += 1
                continue
            primary_url = urls[0]
            fmt = normalized_format(item, primary_url)
            if fmt in {"folder", "unknown"}:
                skipped += 1
                continue
            requires_auth = item_requires_auth(item, urls)
            warnings = ["可能需要 SmartEdu 登录授权"] if requires_auth else []
            resource_type = resource_type_for(fmt, item, resource_detail)
            smartedu_detail_id = norm(resource_detail.get("id") or detail.get("id"))
            candidate = {
                "source": "smartedu",
                "source_name": "国家中小学智慧教育平台",
                "source_url": primary_url,
                "resource_id": f"{smartedu_detail_id}:{index}:{stable_id(primary_url)}",
                "title": candidate_title(resource_detail, item, fmt),
                "description": norm(resource_detail.get("description") or resource_detail.get("global_description") or detail.get("description") or detail.get("global_description")),
                "resource_type": resource_type,
                "format": fmt,
                "stage": dimensions.get("stage") or filters.get("stage"),
                "grade": dimensions.get("grade") or filters.get("grade"),
                "subject": dimensions.get("subject") or filters.get("subject"),
                "learning_domain": dimensions.get("subject") or filters.get("learning_domain"),
                "version": dimensions.get("version") or filters.get("version"),
                "volume": dimensions.get("volume") or filters.get("volume"),
                "topic": filters.get("core_topic") or filters.get("topic"),
                "provider": provider,
                "official": True,
                "downloadable": fmt not in {"folder", "unknown"},
                "requires_auth": requires_auth,
                "size": requirement_value(item, "FileSize") or requirement_value(item, "total_size") or item.get("ti_size"),
                "metadata_confidence": 0.0,
                "raw": {
                    "detail_page": detail_page,
                    "smartedu_detail_id": smartedu_detail_id,
                    "smartedu_catalog": catalog,
                    "smartedu_sub_catalog": sub_catalog,
                    "smartedu_item_index": index,
                    "smartedu_item": item,
                    "smartedu_resource_item": resource_detail,
                    "url_candidates": urls,
                    "warnings": warnings,
                },
            }
            candidate["metadata_confidence"] = metadata_confidence(candidate)
            candidates.append(candidate)
    return candidates, total_items, skipped


def fetch_detail(
    resource_id: str,
    catalog: str,
    access_token: str | None,
    cookie: str | None = None,
    extra_headers: dict[str, str] | None = None,
    browser_state: str | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    errors: list[str] = []
    identity = {
        "resource_id": resource_id,
        "catalog": catalog,
        "tab_code": catalog,
        "content_type": "national_lesson" if catalog == "syncClassroom" else "",
        "resource_type": "",
    }
    for attempt in detail_urls_for_identity(identity):
        url = attempt["url"]
        try:
            return request_json(url, access_token=access_token, cookie=cookie, extra_headers=extra_headers)
        except Exception as exc:
            errors.append(str(exc))
            if browser_state:
                detail, status, _content_type, error = browser_request_json_status(url, browser_state, timeout=timeout)
                if detail is not None:
                    return detail
                errors.append(f"browser_state {url}: status={status} error={error}")
    raise RuntimeError("; ".join(errors))


def detail_identity_from_url(url: str) -> dict[str, str]:
    identity = identity_from_detail_page_url(url)
    if identity.get("resource_id"):
        return {
            "resource_id": identity.get("resource_id", ""),
            "catalog": identity.get("catalog") or identity.get("tab_code") or "syncClassroom",
            "sub_catalog": identity.get("sub_catalog", ""),
            "content_type": identity.get("content_type", ""),
        }
    raise ValueError(f"无法从 SmartEdu URL 识别资源 ID: {url}")


