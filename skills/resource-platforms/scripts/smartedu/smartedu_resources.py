#!/usr/bin/env python3
"""Normalize SmartEdu platform resources into learning resource candidates.

模块结构（Phase 3E 拆分，2861→1160 行）：
- _constants.py    共享常量（SEARCH_URLS/DETAIL_URLS/TAG_DIMENSIONS/DEFAULT_TAB_CODES 等）
- _auth_http.py    HTTP/授权传输层（load_local_env / build_headers / request_json* / browser_request_json_status）
- _text_utils.py   纯文本/URL 工具 + load_json（norm / clean_html_text / stable_id / absolute_url / RESOURCE_EXTENSIONS）
- _page_profile.py 页面 HTML/JS 结构线索分析（extract_*_hints / infer_page_type）
- _catalog.py      栏目与路由处理（flatten_catalogs / route_for_catalog / route_coverage 等）
- _search.py       搜索与候选标准化（extract_search_items / search_item_to_candidate / identity 等）
- _detail.py       详情探测与详情候选标准化（probe_detail_for_search_item / candidates_from_detail 等）
- 本文件           命令处理 + 扫描 + CLI（11 个子命令的 run_* + build_parser）
下层模块不依赖本文件，本文件 import 复用，外部命令行接口和 JSON 输出不变。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.logger import getLogger
log = getLogger("smartedu")

from _auth_http import (
    browser_request_json_status,
    build_headers,
    has_auth_context,
    has_runtime_auth_context,
    load_local_env,
    parse_extra_headers,
    request_json,
    request_json_status,
    request_text,
)
from _text_utils import (
    RESOURCE_EXTENSIONS,
    absolute_url,
    clean_html_text,
    first_value,
    load_json,
    norm,
    quote_url_path,
    resource_extension,
    stable_id,
)
from _constants import (
    DEFAULT_FORMATS,
    DEFAULT_RESOURCE_TYPES,
    DEFAULT_TAB_CODES,
    DETAIL_ENDPOINT_FAMILY,
    DETAIL_PAGE,
    DETAIL_URLS,
    LIBRARY_LIST_URL,
    PRIVATE_HOST,
    PRIVATE_NDR_RE,
    PUBLIC_HOSTS,
    SEARCH_URLS,
    SMARTEDU_FILE_SERVERS,
    TAG_DIMENSIONS,
)
from _page_profile import (
    extract_detail_hints,
    extract_resource_link_hints,
    extract_script_sources,
    extract_smartedu_api_hints,
    fetch_script_texts,
    infer_page_type,
)
from _catalog import (
    catalog_page_url,
    catalog_summary,
    count_values,
    dedupe_routes,
    flatten_catalogs,
    route_coverage,
    route_detail_coverage,
    route_for_catalog,
    route_scan_plan,
    scan_route_summary,
    search_tab_for,
)
from _search import (
    detail_page_from_search_item,
    detail_urls_for_identity,
    explicit_detail_json_urls,
    extract_search_items,
    filter_search_items_by_tags,
    grade_to_chinese,
    identity_from_detail_page_url,
    infer_format_from_item,
    metadata_confidence,
    resource_type_for,
    search_item_identity,
    search_item_to_candidate,
    search_model_context,
    search_provider_name,
    search_tags_by_dimension,
)
from _detail import (
    annotate_candidate_detail,
    candidates_from_detail,
    detail_access_policy,
    detail_failure_for_probe,
    detail_for_search_item,
    detail_identity_from_url,
    detail_probe_matrix,
    detail_summary_for_probe,
    fetch_detail,
    probe_detail_for_search_item,
)


def write_output(path: str | None, data: Any) -> None:
    output = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


def parse_tab_codes(values: list[str] | None) -> list[str]:
    tab_codes: list[str] = []
    for value in values or []:
        for part in value.split(","):
            part = part.strip()
            if part and part not in tab_codes:
                tab_codes.append(part)
    return tab_codes or DEFAULT_TAB_CODES


def search_payload(args: argparse.Namespace, filters: dict[str, Any]) -> dict[str, Any]:
    query = args.query or norm(filters.get("query") or filters.get("core_topic") or filters.get("subject"))
    # 把 intent / task-json 的结构化字段映射为 SmartEdu tag 维度筛选
    tag_dimension_map = {
        "version": "tag.zxxbb",
        "grade": "tag.zxxnj",
        "volume": "tag.zxxcc",
        "subject": "tag.zxxxk",
        "stage": "tag.zxxxd",
    }
    combine_resources: list[dict[str, str]] = []
    for field, tag_field in tag_dimension_map.items():
        value = norm(filters.get(field))
        if value:
            # 年级数字转中文：1 -> 一年级, 3 -> 三年级
            value = grade_to_chinese(value)
            combine_resources.append({"field": tag_field, "value": value})
    return {
        "identity": args.identity,
        "identity_code": args.identity_code,
        "keyword": query,
        "tab_codes": parse_tab_codes(args.tab_code),
        "cross_tenant": args.cross_tenant,
        "duplicate_filter": True,
        "search_order": {"field": args.order_field, "direction": args.order_direction},
        "offset": args.offset,
        "limit": args.limit,
        "combine_intentions": [],
        "combine_resources": combine_resources,
    }


def run_route_map(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    if args.library_list_json:
        data = load_json(args.library_list_json)
    else:
        data = request_json(LIBRARY_LIST_URL, access_token=access_token, cookie=args.cookie, extra_headers=extra_headers)
    if not isinstance(data, list):
        raise ValueError("library list must be a JSON list")
    catalogs = flatten_catalogs(data)
    routes, duplicates = dedupe_routes([route_for_catalog(row) for row in catalogs])
    result = {
        "route_map_schema": "smartedu-route-map/v1",
        "source_skill": "smartedu",
        "mapped_at": datetime.now(timezone.utc).isoformat(),
        "routes": routes,
        "summary": {
            "routes": len(routes),
            "duplicates_removed": duplicates,
            "internal_adapter_routes": sum(1 for item in routes if item.get("scan_strategy") == "internal_adapter"),
            "search_then_detail_routes": sum(1 for item in routes if item.get("scan_strategy") == "search_then_detail"),
            "catalogs": catalog_summary(catalogs),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
        },
    }
    write_output(args.output, result)
    return 0


def routes_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.route_map_json:
        data = load_json(args.route_map_json)
        routes = data.get("routes") if isinstance(data, dict) else []
        if not isinstance(routes, list):
            raise ValueError("route-map JSON must contain routes list")
        return dedupe_routes([item for item in routes if isinstance(item, dict)])[0]
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    if args.library_list_json:
        data = load_json(args.library_list_json)
    else:
        data = request_json(LIBRARY_LIST_URL, access_token=access_token, cookie=args.cookie, extra_headers=extra_headers)
    if not isinstance(data, list):
        raise ValueError("library list must be a JSON list")
    return dedupe_routes([route_for_catalog(row) for row in flatten_catalogs(data)])[0]


def select_routes(routes: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for route in routes:
        if args.route_id and route.get("route_id") != args.route_id:
            continue
        if args.catalog and route.get("catalog") != args.catalog:
            continue
        if args.sub_catalog and route.get("sub_catalog") != args.sub_catalog:
            continue
        if args.type and route.get("type") != args.type:
            continue
        if args.title and args.title not in norm(route.get("title")):
            continue
        selected.append(route)
    if getattr(args, "all_routes", False) or args.route_limit <= 0:
        return selected
    return selected[: args.route_limit]


def run_site_index(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    routes = select_routes(routes_from_args(args), args)
    if not routes:
        raise ValueError("no matching routes")

    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    route_results: list[dict[str, Any]] = []
    scan_summary: dict[str, Any] = {}
    if args.site_scan_json:
        scan_data = load_json(args.site_scan_json)
        candidates = [item for item in scan_data.get("candidates") or [] if isinstance(item, dict)]
        failures = [item for item in scan_data.get("failures") or [] if isinstance(item, dict)]
        route_results = [item for item in scan_data.get("routes") or [] if isinstance(item, dict)]
        scan_summary = scan_data.get("summary") if isinstance(scan_data.get("summary"), dict) else {}
    detail_coverage = route_detail_coverage(route_results)

    output = {
        "site_index_schema": "smartedu-site-index/v1",
        "source_skill": "smartedu",
        "source_name": "国家中小学智慧教育平台",
        "site_url": "https://basic.smartedu.cn/",
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "routes": routes,
        "scan_plan": [route_scan_plan(route) for route in routes],
        "coverage": route_coverage(routes),
        "candidates": candidates,
        "failures": failures,
        "scan_summary": scan_summary,
        "detail_coverage": detail_coverage,
        "summary": {
            "routes": len(routes),
            "search_then_detail_routes": sum(1 for item in routes if item.get("scan_strategy") == "search_then_detail"),
            "internal_adapter_routes": sum(1 for item in routes if item.get("scan_strategy") == "internal_adapter"),
            "runtime_validation_routes": sum(1 for item in routes if item.get("requires_runtime_validation")),
            "candidates": len(candidates),
            "failures": len(failures),
            "route_scan_summary": scan_route_summary(route_results) if route_results else {},
            "detail_coverage_routes": len(detail_coverage),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
        },
    }
    write_output(args.output, output)
    return 0


def scan_payload(query: str, route: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "identity": args.identity,
        "identity_code": args.identity_code,
        "keyword": query,
        "tab_codes": [route.get("search_tab_code") or DEFAULT_TAB_CODES[0]],
        "cross_tenant": args.cross_tenant,
        "duplicate_filter": True,
        "search_order": {"field": args.order_field, "direction": args.order_direction},
        "offset": args.offset,
        "limit": args.limit,
        "combine_intentions": [],
        "combine_resources": [],
    }


def scan_query(args: argparse.Namespace, route: dict[str, Any]) -> str:
    return args.query or norm(route.get("title") or route.get("catalog_name") or route.get("sub_catalog_name") or route.get("type"))


def scan_search_data(args: argparse.Namespace, route: dict[str, Any], access_token: str | None, extra_headers: dict[str, str]) -> tuple[Any, bool, str]:
    if args.search_response_json:
        return load_json(args.search_response_json), False, args.search_response_json
    payload = scan_payload(scan_query(args, route), route, args)
    if args.search_url:
        return request_json(args.search_url, access_token=access_token, payload=payload, cookie=args.cookie, extra_headers=extra_headers), True, args.search_url
    errors: list[str] = []
    for url in SEARCH_URLS:
        try:
            return request_json(url, access_token=access_token, payload=payload, cookie=args.cookie, extra_headers=extra_headers), True, url
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def route_scan_result(route: dict[str, Any], args: argparse.Namespace, access_token: str | None, extra_headers: dict[str, str]) -> dict[str, Any]:
    if route.get("scan_strategy") == "internal_adapter":
        return {
            "route": route,
            "status": "skipped_internal_adapter",
            "query": scan_query(args, route),
            "online": False,
            "endpoint": "",
            "search_items_seen": 0,
            "candidates": [],
            "detail_failures": [],
            "summary": {"note": "该栏目当前由内部适配器处理，请使用 textbook-candidates。"},
        }
    query = scan_query(args, route)
    data, online, endpoint = scan_search_data(args, route, access_token, extra_headers)
    items = extract_search_items(data, args.limit)
    scan_filters = load_task_filters(getattr(args, "task_json", None))
    items = filter_search_items_by_tags(items, scan_filters)
    candidates: list[dict[str, Any]] = []
    detail_failures: list[dict[str, str]] = []
    detail_items_seen = 0
    detail_items_skipped = 0
    details_fetched = 0
    if args.fetch_details:
        for item in items:
            detail, identity, error, probe = detail_for_search_item(item, args, access_token, extra_headers)
            detail_summary = detail_summary_for_probe(probe)
            if detail is None:
                fallback = search_item_to_candidate(item, query, {})
                fallback.setdefault("raw", {}).setdefault("warnings", []).append(f"详情追踪失败：{error or 'unknown error'}")
                annotate_candidate_detail(fallback, detail_summary)
                candidates.append(fallback)
                detail_failures.append(detail_failure_for_probe(probe, identity))
                continue
            detail_candidates, seen, skipped = candidates_from_detail(detail, identity["catalog"], identity["sub_catalog"], {})
            if detail_candidates:
                candidates.extend(annotate_candidate_detail(candidate, detail_summary) for candidate in detail_candidates)
            else:
                fallback = search_item_to_candidate(item, query, {})
                fallback.setdefault("raw", {}).setdefault("warnings", []).append("详情已获取但未解析出文件项")
                candidates.append(annotate_candidate_detail(fallback, detail_summary))
            details_fetched += 1
            detail_items_seen += seen
            detail_items_skipped += skipped
    else:
        candidates = [search_item_to_candidate(item, query, {}) for item in items]
    for candidate in candidates:
        raw = candidate.setdefault("raw", {})
        if isinstance(raw, dict):
            raw["smartedu_route_id"] = route.get("route_id")
            raw["smartedu_route_title"] = route.get("title")
            raw["smartedu_scan_strategy"] = route.get("scan_strategy")
    return {
        "route": route,
        "status": "ok" if candidates else "no_candidates",
        "query": query,
        "online": online,
        "endpoint": endpoint,
        "search_items_seen": len(items),
        "candidates": candidates,
        "detail_failures": detail_failures,
        "summary": {
            "candidates": len(candidates),
            "fetch_details": bool(args.fetch_details),
            "details_fetched": details_fetched,
            "detail_items_seen": detail_items_seen,
            "detail_items_skipped": detail_items_skipped,
            "detail_failures": len(detail_failures),
        },
    }


def run_scan_catalog(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    routes = select_routes(routes_from_args(args), args)
    if not routes:
        raise ValueError("no matching routes")
    route_results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for route in routes:
        result = route_scan_result(route, args, access_token, extra_headers)
        route_results.append(result)
        candidates.extend(item for item in result.get("candidates") or [] if isinstance(item, dict))
    output = {
        "scan_schema": "smartedu-catalog-scan/v1",
        "source_skill": "smartedu",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "query": args.query or "",
        "routes": route_results,
        "candidates": candidates,
        "summary": {
            "routes_selected": len(routes),
            "routes_scanned": len(route_results),
            "candidates": len(candidates),
            "search_items_seen": sum(int(item.get("search_items_seen") or 0) for item in route_results),
            "route_scan_summary": scan_route_summary(route_results),
            "online": not bool(args.search_response_json),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
        },
    }
    write_output(args.output, output)
    return 0 if candidates else 1


def candidate_key(candidate: dict[str, Any]) -> str:
    return norm(candidate.get("source_url")) or norm(candidate.get("resource_id")) or stable_id(json.dumps(candidate, ensure_ascii=False, sort_keys=True))


def dedupe_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for candidate in candidates:
        key = candidate_key(candidate)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(candidate)
    return unique, duplicates


def run_scan_site(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    routes = select_routes(routes_from_args(args), args)
    if not routes:
        raise ValueError("no matching routes")

    route_results: list[dict[str, Any]] = []
    raw_candidates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped_internal = 0
    for route in routes:
        try:
            result = route_scan_result(route, args, access_token, extra_headers)
            route_results.append(result)
            if result.get("status") == "skipped_internal_adapter":
                skipped_internal += 1
            raw_candidates.extend(item for item in result.get("candidates") or [] if isinstance(item, dict))
        except Exception as exc:
            failures.append(
                {
                    "route_id": norm(route.get("route_id")),
                    "title": norm(route.get("title")),
                    "catalog": norm(route.get("catalog")),
                    "error": str(exc),
                }
            )
            if not args.continue_on_error:
                break
    candidates, duplicates = dedupe_candidates(raw_candidates)
    output = {
        "site_scan_schema": "smartedu-site-scan/v1",
        "source_skill": "smartedu",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "query": args.query or "",
        "routes": route_results,
        "candidates": candidates,
        "failures": failures,
        "summary": {
            "routes_selected": len(routes),
            "routes_scanned": len(route_results),
            "routes_failed": len(failures),
            "internal_adapter_routes_skipped": skipped_internal,
            "raw_candidates": len(raw_candidates),
            "duplicates_removed": duplicates,
            "candidates": len(candidates),
            "search_items_seen": sum(int(item.get("search_items_seen") or 0) for item in route_results),
            "route_scan_summary": scan_route_summary(route_results),
            "online": not bool(args.search_response_json),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
        },
    }
    write_output(args.output, output)
    return 0 if candidates else 1


def run_page_profile(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    page_url = args.url or "https://basic.smartedu.cn/"
    if args.html_file:
        html_text = Path(args.html_file).read_text(encoding="utf-8", errors="replace")
    else:
        html_text = request_text(page_url, access_token=access_token, timeout=args.timeout, cookie=args.cookie, extra_headers=extra_headers)
    script_sources = extract_script_sources(html_text, page_url)
    script_text = ""
    script_failures: list[dict[str, str]] = []
    if args.fetch_scripts:
        script_text, script_failures = fetch_script_texts(script_sources, access_token, args.cookie, extra_headers, args.timeout, args.script_limit)
    combined_text = f"{html_text}\n{script_text}"
    api_hints = extract_smartedu_api_hints(combined_text, page_url)
    detail_hints = extract_detail_hints(combined_text, page_url)
    resource_links = extract_resource_link_hints(combined_text, page_url)
    page_type = infer_page_type(combined_text, page_url, api_hints, detail_hints, resource_links)
    result = {
        "page_profile_schema": "smartedu-page-profile/v1",
        "source_skill": "smartedu",
        "profiled_at": datetime.now(timezone.utc).isoformat(),
        "page_url": page_url,
        "page_type": page_type,
        "api_hints": api_hints,
        "detail_hints": detail_hints,
        "resource_link_hints": resource_links,
        "script_sources": script_sources,
        "script_failures": script_failures,
        "recommended_next_actions": [],
        "summary": {
            "api_hints": len(api_hints),
            "detail_hints": len(detail_hints),
            "resource_link_hints": len(resource_links),
            "script_sources": len(script_sources),
            "scripts_fetched": min(len(script_sources), args.script_limit) - len(script_failures) if args.fetch_scripts else 0,
            "script_failures": len(script_failures),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
            "offline_html": bool(args.html_file),
            "fetch_scripts": bool(args.fetch_scripts),
        },
    }
    actions: list[str] = []
    if any("librarylist" in item.lower() for item in api_hints):
        actions.append("route-map")
    if detail_hints:
        actions.append("candidates-from-detail")
    if any("search" in item.lower() or "aggregate" in item.lower() or "combine" in item.lower() for item in api_hints):
        actions.append("search-resources")
    if resource_links:
        actions.append("resource-selector")
    result["recommended_next_actions"] = list(dict.fromkeys(actions)) or ["profile_deeper"]
    write_output(args.output, result)
    return 0


def run_site_profile(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    catalogs: list[dict[str, Any]] = []
    catalog_error = ""
    if args.library_list_json:
        data = load_json(args.library_list_json)
        if not isinstance(data, list):
            raise ValueError("library list must be a JSON list")
        catalogs = flatten_catalogs(data)
    elif args.fetch_catalogs:
        try:
            data = request_json(LIBRARY_LIST_URL, access_token=access_token, cookie=args.cookie, extra_headers=extra_headers)
            if isinstance(data, list):
                catalogs = flatten_catalogs(data)
            else:
                catalog_error = "library list response is not a JSON list"
        except Exception as exc:
            catalog_error = str(exc)

    profile = {
        "source_profile_schema": "learning-resource-source-profile/v1",
        "source_skill": "smartedu",
        "source_name": "国家中小学智慧教育平台",
        "site_url": "https://basic.smartedu.cn/",
        "profiled_at": datetime.now(timezone.utc).isoformat(),
        "positioning": "站点级学习资源来源；站内各种栏目和资源类型统一由本 skill 转为候选资源。",
        "routing_policy": {
            "as_candidate_source": True,
            "type_binding": False,
            "topic_binding": False,
            "notes": [
                "不要因为用户提到某一种资源类型就固定选择本来源。",
                "当搜索、来源发现或用户明确站点指向 basic.smartedu.cn 时，可把本来源作为候选来源参与排序。",
                "教材是站内资源分支，不是独立外部来源。",
            ],
        },
        "capabilities": [
            {
                "name": "site_profile",
                "command": "site-profile",
                "status": "stable_offline",
                "description": "输出站点能力、资源类型覆盖、授权策略和栏目摘要。",
            },
            {
                "name": "catalog_profile",
                "command": "list-catalogs",
                "status": "stable",
                "description": "读取栏目配置，识别站内栏目、外链栏目和教材内部适配分支。",
            },
            {
                "name": "route_map",
                "command": "route-map",
                "status": "stable_offline",
                "description": "将栏目配置转为栏目路由图，说明页面、搜索 tab、详情模板和内部适配策略。",
            },
            {
                "name": "page_profile",
                "command": "page-profile",
                "status": "stable_offline",
                "description": "从 SmartEdu 页面 HTML/JS 中提取接口、详情 ID、资源链接和下一步动作线索。",
            },
            {
                "name": "catalog_scan",
                "command": "scan-catalog",
                "status": "stable_offline",
                "description": "按单个或少量栏目路由扫描资源候选，可选继续追踪详情。",
            },
            {
                "name": "site_scan",
                "command": "scan-site",
                "status": "stable_offline",
                "description": "按 route-map 批量扫描多个栏目，输出站点级候选索引摘要。",
            },
            {
                "name": "resource_search",
                "command": "search-resources",
                "status": "needs_runtime_auth_or_endpoint_validation",
                "description": "调用或归一化站内搜索结果，输出搜索候选；下载前通常需要继续解析详情。",
            },
            {
                "name": "detail_items",
                "command": "candidates-from-detail",
                "status": "stable",
                "description": "解析详情 JSON 中的 ti_items，将视频、文档、图片、课件等文件项转为候选。",
            },
            {
                "name": "textbook_branch",
                "command": "textbook-candidates",
                "status": "compatibility_adapter",
                "description": "复用早期教材适配能力，对外仍输出 smartedu 候选。",
            },
        ],
        "resource_coverage": {
            "resource_types": DEFAULT_RESOURCE_TYPES,
            "formats": DEFAULT_FORMATS,
            "default_search_tabs": DEFAULT_TAB_CODES,
            "details_expandable": True,
            "direct_download_by_this_skill": False,
        },
        "access_policy": {
            "supports_auth_context": True,
            "auth_inputs": ["SMARTEDU_ACCESS_TOKEN", "SMARTEDU_COOKIE", "SMARTEDU_AUTHORIZATION", "SMARTEDU_HEADERS", "--access-token", "--cookie", "--header"],
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
            "secret_redaction": "输出只记录 auth_context，不写入 token、cookie、authorization 或 header 原文。",
            "login_limited_resources": "可能被标记为 requires_auth，后续交给 downloader 或专门下载团队处理。",
        },
        "catalog_summary": catalog_summary(catalogs) if catalogs else {},
        "catalog_sample": catalogs[: args.catalog_sample] if catalogs else [],
        "warnings": [],
    }
    if catalog_error:
        profile["warnings"].append(f"栏目配置读取失败：{catalog_error}")
    write_output(args.output, profile)
    return 0


def run_list_catalogs(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    if args.library_list_json:
        data = load_json(args.library_list_json)
    else:
        data = request_json(LIBRARY_LIST_URL, access_token=access_token, cookie=args.cookie, extra_headers=extra_headers)
    if not isinstance(data, list):
        raise ValueError("library list must be a JSON list")
    catalogs = flatten_catalogs(data)
    result = {
        "catalog_profile_schema": "smartedu-catalog-profile/v1",
        "source_skill": "smartedu",
        "profiled_at": datetime.now(timezone.utc).isoformat(),
        "catalogs": catalogs,
        "summary": {
            "catalogs": len(catalogs),
            "resource_catalogs": sum(1 for item in catalogs if item.get("known_skill") == "smartedu"),
            "external_catalogs": sum(1 for item in catalogs if item.get("external")),
            "textbook_catalogs": sum(1 for item in catalogs if item.get("internal_adapter") == "tchMaterial"),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
        },
    }
    write_output(args.output, result)
    return 0


def load_task_filters(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = load_json(path)
    if isinstance(data, dict):
        return data.get("filters") or data.get("intent") or {}
    return {}


def run_candidates_from_detail(args: argparse.Namespace) -> int:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    details: list[dict[str, Any]] = []
    detail_contexts: list[dict[str, str]] = []
    url_context = detail_identity_from_url(args.url) if args.url else None
    default_context = {
        "catalog": (url_context or {}).get("catalog") or args.catalog or "syncClassroom",
        "sub_catalog": (url_context or {}).get("sub_catalog") or args.sub_catalog or "",
    }
    if args.detail_json:
        for path in args.detail_json:
            data = load_json(path)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        details.append(item)
                        detail_contexts.append(default_context)
            elif isinstance(data, dict):
                details.append(data)
                detail_contexts.append(default_context)
    elif args.url:
        identity = detail_identity_from_url(args.url)
        details.append(
            fetch_detail(
                identity["resource_id"],
                identity["catalog"],
                access_token,
                cookie=args.cookie,
                extra_headers=extra_headers,
                browser_state=args.browser_state,
                timeout=args.timeout,
            )
        )
        detail_contexts.append({"catalog": identity["catalog"], "sub_catalog": identity.get("sub_catalog", "")})
    elif args.resource_id and args.catalog:
        details.append(
            fetch_detail(
                args.resource_id,
                args.catalog,
                access_token,
                cookie=args.cookie,
                extra_headers=extra_headers,
                browser_state=args.browser_state,
                timeout=args.timeout,
            )
        )
        detail_contexts.append({"catalog": args.catalog, "sub_catalog": args.sub_catalog or ""})
    else:
        log.error("provide --detail-json, --url, or both --catalog and --resource-id")
        return 2

    filters = load_task_filters(args.task_json)
    all_candidates: list[dict[str, Any]] = []
    items_seen = 0
    skipped = 0
    for index, detail in enumerate(details[: args.limit]):
        context = detail_contexts[index] if index < len(detail_contexts) else {"catalog": args.catalog or "syncClassroom", "sub_catalog": args.sub_catalog or ""}
        candidates, seen, failed = candidates_from_detail(detail, context["catalog"], context.get("sub_catalog", ""), filters)
        all_candidates.extend(candidates)
        items_seen += seen
        skipped += failed

    result = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "smartedu",
        "query": args.query or "",
        "filters": filters,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "candidates": all_candidates,
        "summary": {
            "details": len(details[: args.limit]),
            "items_seen": items_seen,
            "candidates": len(all_candidates),
            "skipped": skipped,
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
            "browser_state_context": bool(args.browser_state),
        },
    }
    write_output(args.output, result)
    return 0 if all_candidates else 1


# SmartEdu 搜索 API 分页硬限制
_SEARCH_PAGE_SIZE = 100
_SEARCH_MAX_OFFSET = 200  # offset + limit ≤ 200

# 深度搜索时用于交叉的维度
_DEEP_SEARCH_GRADES = ["一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "七年级", "八年级", "九年级"]
_DEEP_SEARCH_STAGES = ["小学", "初中", "高中"]


def _make_search_request(
    base_payload: dict[str, Any],
    *,
    keyword: str,
    tab_codes: list[str],
    offset: int,
    limit: int,
    combine_resources: list[dict[str, str]],
    access_token: str | None,
    cookie: str | None,
    extra_headers: dict[str, str],
    search_url: str | None = None,
) -> Any:
    """发一次搜索请求，返回响应 JSON。"""
    payload = dict(base_payload)
    payload["keyword"] = keyword
    payload["tab_codes"] = tab_codes
    payload["offset"] = offset
    payload["limit"] = limit
    payload["combine_resources"] = combine_resources
    urls = [search_url] if search_url else list(SEARCH_URLS)
    errors: list[str] = []
    for url in urls:
        try:
            return request_json(url, access_token=access_token, payload=payload, cookie=cookie, extra_headers=extra_headers)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def _search_all_pages(
    base_payload: dict[str, Any],
    *,
    keyword: str,
    tab_codes: list[str],
    combine_resources: list[dict[str, str]],
    max_results: int,
    access_token: str | None,
    cookie: str | None,
    extra_headers: dict[str, str],
    search_url: str | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """对单组关键词+tab 自动分页拉取，突破 200 条限制。

    返回 (所有搜索项列表, 分页统计)。
    """
    all_raw_items: list[Any] = []
    page_stats: list[dict[str, Any]] = []
    for page_offset in range(0, _SEARCH_MAX_OFFSET, _SEARCH_PAGE_SIZE):
        remaining = max_results - len(all_raw_items)
        if remaining <= 0:
            break
        page_limit = min(_SEARCH_PAGE_SIZE, remaining)
        try:
            data = _make_search_request(
                base_payload,
                keyword=keyword,
                tab_codes=tab_codes,
                offset=page_offset,
                limit=page_limit,
                combine_resources=combine_resources,
                access_token=access_token,
                cookie=cookie,
                extra_headers=extra_headers,
                search_url=search_url,
            )
        except Exception:
            break
        page_items = extract_search_items(data, page_limit)
        if not page_items:
            break
        all_raw_items.extend(page_items)
        page_stats.append({"offset": page_offset, "limit": page_limit, "items": len(page_items)})
        if len(page_items) < page_limit:
            break
    return all_raw_items, page_stats


def deep_search(args: argparse.Namespace, filters: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    """深度搜索：自动分页 + 多维度交叉，突破 API 单次 200 条硬限制。

    策略：
    1. 原始关键词全 tab 分页搜索（最多 200 条）
    2. 如果结果 ≥ 200 且用户给了 stage/grade 维度，按年级细分交叉搜索
    3. 如果结果仍 ≥ 上限，按 stage × tab 组合再搜
    4. 全局去重

    返回 (去重后的搜索项列表, 统计信息)。
    """
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    base_payload = {
        "identity": args.identity,
        "identity_code": args.identity_code,
        "cross_tenant": args.cross_tenant,
        "duplicate_filter": True,
        "search_order": {"field": args.order_field, "direction": args.order_direction},
        "combine_intentions": [],
    }
    tab_codes = parse_tab_codes(args.tab_code)
    query = args.query or norm(filters.get("query") or filters.get("core_topic") or filters.get("subject"))

    # tag 筛选
    tag_dimension_map = {
        "version": "tag.zxxbb",
        "grade": "tag.zxxnj",
        "volume": "tag.zxxcc",
        "subject": "tag.zxxxk",
        "stage": "tag.zxxxd",
    }
    base_combine_resources: list[dict[str, str]] = []
    for field, tag_field in tag_dimension_map.items():
        value = norm(filters.get(field))
        if value:
            value = grade_to_chinese(value)
            base_combine_resources.append({"field": tag_field, "value": value})

    max_results = getattr(args, "max_results", 5000)
    seen_ids: set[str] = set()
    deduped: list[Any] = []
    search_log: list[dict[str, Any]] = []

    def _absorb(raw_items: list[Any], source_desc: str) -> None:
        added = 0
        for item in raw_items:
            key = norm(first_value(item, ["id", "resource_id", "resourceId", "content_id", "contentId", "course_id", "courseId"]))
            title = norm(first_value(item, ["title", "name", "content_name", "contentName", "resource_name", "resourceName", "global_title"]))
            fp = f"{key}:{title}"
            if fp in seen_ids:
                continue
            seen_ids.add(fp)
            deduped.append(item)
            added += 1
            if len(deduped) >= max_results:
                break
        search_log.append({"source": source_desc, "fetched": len(raw_items), "added": added, "total": len(deduped)})

    # Phase 1: 原始关键词 + 全 tab 分页
    phase1_items, _ = _search_all_pages(
        base_payload,
        keyword=query,
        tab_codes=tab_codes,
        combine_resources=base_combine_resources,
        max_results=max_results,
        access_token=access_token,
        cookie=args.cookie,
        extra_headers=extra_headers,
        search_url=args.search_url,
    )
    _absorb(phase1_items, f"phase1: query='{query}' tabs={tab_codes[:3]}...")

    # Phase 2: 如果 Phase 1 接近 200 条上限，按年级细分交叉搜索
    if len(deduped) >= 180 and not getattr(args, "no_deep_search", False):
        stage = norm(filters.get("stage"))
        # 确定要交叉的年级维度
        cross_grades: list[str] = []
        if stage == "小学":
            cross_grades = _DEEP_SEARCH_GRADES[:6]
        elif stage == "初中":
            cross_grades = _DEEP_SEARCH_GRADES[6:9]
        elif stage == "高中":
            cross_grades = ["高一", "高二", "高三"]
        else:
            # 没有明确学段，用全部年级
            cross_grades = _DEEP_SEARCH_GRADES + ["高一", "高二", "高三"]

        for grade in cross_grades:
            if len(deduped) >= max_results:
                break
            grade_query = f"{grade} {query}"
            # 用 tag 维度做精确年级过滤
            grade_resources = [r for r in base_combine_resources if r["field"] != "tag.zxxnj"]
            grade_resources.append({"field": "tag.zxxnj", "value": grade})
            phase2_items, _ = _search_all_pages(
                base_payload,
                keyword=grade_query,
                tab_codes=tab_codes,
                combine_resources=grade_resources,
                max_results=max_results - len(deduped),
                access_token=access_token,
                cookie=args.cookie,
                extra_headers=extra_headers,
                search_url=args.search_url,
            )
            _absorb(phase2_items, f"phase2: query='{grade_query}' grade={grade}")

    # Phase 3: 如果结果仍然不够，按学段 × tab 单独搜索
    if len(deduped) >= 180 and not getattr(args, "no_deep_search", False):
        for stage in _DEEP_SEARCH_STAGES:
            if len(deduped) >= max_results:
                break
            stage_query = f"{stage} {query}"
            for tab in tab_codes[:6]:  # 最多前6个 tab
                if len(deduped) >= max_results:
                    break
                phase3_items, _ = _search_all_pages(
                    base_payload,
                    keyword=stage_query,
                    tab_codes=[tab],
                    combine_resources=base_combine_resources,
                    max_results=max_results - len(deduped),
                    access_token=access_token,
                    cookie=args.cookie,
                    extra_headers=extra_headers,
                    search_url=args.search_url,
                )
                _absorb(phase3_items, f"phase3: query='{stage_query}' tab={tab}")

    stats = {
        "total_unique": len(deduped),
        "phases": search_log,
        "deep_search": not getattr(args, "no_deep_search", False),
        "max_results": max_results,
    }
    return deduped, stats


def fetch_search_results(args: argparse.Namespace, filters: dict[str, Any]) -> Any:
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    payload = search_payload(args, filters)
    tag_filters = payload.get("combine_resources", [])
    if args.search_url:
        return request_json(args.search_url, access_token=access_token, payload=payload, cookie=args.cookie, extra_headers=extra_headers)
    errors: list[str] = []
    # 第一步：带 combine_resources tag 筛选搜索
    for url in SEARCH_URLS:
        try:
            data = request_json(url, access_token=access_token, payload=payload, cookie=args.cookie, extra_headers=extra_headers)
            items = extract_search_items(data, args.limit)
            if items or not tag_filters:
                return data
            # 带筛选搜到0条目，降级为无筛选宽搜索，后面由本地硬过滤补位
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    # 第二步：去掉 combine_resources 做宽搜索
    payload_no_filter = dict(payload)
    payload_no_filter["combine_resources"] = []
    for url in SEARCH_URLS:
        try:
            return request_json(url, access_token=access_token, payload=payload_no_filter, cookie=args.cookie, extra_headers=extra_headers)
        except Exception as exc:
            errors.append(f"{url}(no-filter): {exc}")
    raise RuntimeError("; ".join(errors))


def run_search_resources(args: argparse.Namespace) -> int:
    filters = load_task_filters(args.task_json)
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    query = args.query or norm(filters.get("query") or filters.get("core_topic") or filters.get("subject"))

    deep_search_enabled = bool(getattr(args, "deep_search", False))

    if args.search_response_json:
        data = load_json(args.search_response_json)
        items = extract_search_items(data, args.limit)
        items = filter_search_items_by_tags(items, filters)
        deep_stats = {"deep_search": False, "total_unique": len(items), "phases": [], "note": "offline mode"}
    elif deep_search_enabled:
        items, deep_stats = deep_search(args, filters)
        items = filter_search_items_by_tags(items, filters)
    else:
        data = fetch_search_results(args, filters)
        items = extract_search_items(data, args.limit)
        items = filter_search_items_by_tags(items, filters)
        deep_stats = {"deep_search": False, "total_unique": len(items), "phases": []}

    candidates: list[dict[str, Any]] = []
    details_fetched = 0
    detail_failures: list[dict[str, Any]] = []
    detail_items_seen = 0
    detail_items_skipped = 0
    if args.fetch_details:
        for item in items:
            detail, identity, error, probe = detail_for_search_item(item, args, access_token, extra_headers)
            detail_summary = detail_summary_for_probe(probe)
            if detail is None:
                fallback = search_item_to_candidate(item, query, filters)
                fallback.setdefault("raw", {}).setdefault("warnings", []).append(f"详情追踪失败：{error or 'unknown error'}")
                annotate_candidate_detail(fallback, detail_summary)
                candidates.append(fallback)
                detail_failures.append(detail_failure_for_probe(probe, identity))
                continue
            detail_candidates, seen, skipped = candidates_from_detail(detail, identity["catalog"], identity["sub_catalog"], filters)
            details_fetched += 1
            detail_items_seen += seen
            detail_items_skipped += skipped
            if detail_candidates:
                candidates.extend(annotate_candidate_detail(candidate, detail_summary) for candidate in detail_candidates)
            else:
                fallback = search_item_to_candidate(item, query, filters)
                fallback.setdefault("raw", {}).setdefault("warnings", []).append("详情已获取但未解析出文件项")
                candidates.append(annotate_candidate_detail(fallback, detail_summary))
    else:
        candidates = [search_item_to_candidate(item, query, filters) for item in items]
    result = {
        "candidate_schema": "learning-resource-candidate/v1",
        "source_skill": "smartedu",
        "query": query,
        "filters": filters,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "model_context": search_model_context(items[:20], candidates, query, filters),
        "summary": {
            "search_items_seen": len(items),
            "candidates": len(candidates),
            "fetch_details": bool(args.fetch_details),
            "details_fetched": details_fetched,
            "detail_items_seen": detail_items_seen,
            "detail_items_skipped": detail_items_skipped,
            "detail_failures": len(detail_failures),
            "online": not bool(args.search_response_json),
            "endpoint": args.search_url or SEARCH_URLS[0],
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
            "browser_state_context": bool(args.browser_state),
            "deep_search": deep_stats,
            "note": "已开启详情追踪时，候选优先使用详情文件项；未开启或详情失败时，搜索候选仅适合展示和继续展开，下载前应解析真实文件项。",
        },
    }
    if detail_failures:
        result["detail_failures"] = detail_failures
    write_output(args.output, result)
    return 0 if candidates else 1


def run_detail_probe(args: argparse.Namespace) -> int:
    filters = load_task_filters(args.task_json)
    extra_headers = parse_extra_headers(args.header)
    access_token = args.access_token or os.environ.get("SMARTEDU_ACCESS_TOKEN")
    query = args.query or norm(filters.get("query") or filters.get("core_topic") or filters.get("subject"))
    if args.search_response_json:
        data = load_json(args.search_response_json)
        online = False
        endpoint = args.search_response_json
    else:
        data = fetch_search_results(args, filters)
        online = True
        endpoint = args.search_url or SEARCH_URLS[0]
    items = extract_search_items(data, args.limit)
    items = filter_search_items_by_tags(items, filters)
    probes = [probe_detail_for_search_item(item, args, access_token, extra_headers) for item in items]
    matrix = detail_probe_matrix(probes)
    status_counts = count_values([norm(item.get("detail_status")) for item in probes])
    access_policy_counts = count_values([norm(item.get("detail_access_policy")) for item in probes])
    result = {
        "detail_probe_schema": "smartedu-detail-probe/v1",
        "source_skill": "smartedu",
        "query": query,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "online_search": online,
        "search_endpoint": endpoint,
        "probes": probes,
        "detail_matrix": matrix,
        "summary": {
            "search_items_seen": len(items),
            "probes": len(probes),
            "matrix_rows": len(matrix),
            "status_counts": status_counts,
            "access_policy_counts": access_policy_counts,
            "details_accessible": sum(status_counts.get(key, 0) for key in ["ok_with_file_items", "ok_no_file_items"]),
            "requires_auth": status_counts.get("requires_auth", 0),
            "file_items": sum(int(item.get("file_item_count") or 0) for item in probes),
            "parsed_candidates": sum(int(item.get("parsed_candidate_count") or 0) for item in probes),
            "auth_context": has_runtime_auth_context(access_token, args.cookie, extra_headers, args),
            "browser_state_context": bool(args.browser_state),
        },
    }
    write_output(args.output, result)
    return 0 if probes else 1


def append_arg(command: list[str], flag: str, value: Any) -> None:
    if value not in (None, ""):
        command.extend([flag, str(value)])


def run_textbook_candidates(args: argparse.Namespace) -> int:
    fetch_script = Path(__file__).resolve().parent / "fetch_textbooks.py"
    if not fetch_script.exists():
        log.error("missing internal adapter %s", fetch_script)
        return 2

    command = [
        sys.executable,
        str(fetch_script),
        "--list-only",
        "--work-dir",
        args.work_dir,
        "--show",
        str(args.show),
    ]
    append_arg(command, "--stage", args.stage)
    append_arg(command, "--grade", args.grade)
    append_arg(command, "--subject", args.subject)
    append_arg(command, "--version", args.version)
    append_arg(command, "--volume", args.volume)
    append_arg(command, "--query", args.query)
    append_arg(command, "--limit", args.limit)
    if args.sync:
        command.append("--sync")

    completed = subprocess.run(command, text=True, capture_output=True, cwd=str(Path(__file__).resolve().parents[3]))
    if completed.returncode != 0:
        if completed.stderr:
            log.error("%s", completed.stderr.strip())
        if completed.stdout:
            log.error("%s", completed.stdout.strip())
        return completed.returncode

    data = json.loads(completed.stdout)
    data["source_skill"] = "smartedu"
    data["resource_family"] = "教材"
    data["internal_adapter"] = "tchMaterial"
    for candidate in data.get("candidates") or []:
        candidate["source"] = "smartedu"
        raw = candidate.setdefault("raw", {})
        if isinstance(raw, dict):
            raw["internal_adapter"] = "tchMaterial"
            raw["smartedu_catalog"] = "tchMaterial"
    write_output(args.output, data)
    return 0 if data.get("candidates") else 1


def add_auth_args(p: argparse.ArgumentParser) -> None:
    """通用认证 + 输出参数（多数子命令共用）。"""
    p.add_argument("--access-token", help="SmartEdu access token; prefer SMARTEDU_ACCESS_TOKEN")
    p.add_argument("--cookie", help="SmartEdu cookie; prefer SMARTEDU_COOKIE")
    p.add_argument("--header", action="append", help="额外请求头，格式 'Name: value'；也可用 SMARTEDU_HEADERS")
    p.add_argument("-o", "--output", help="写入 JSON 文件")


def add_search_params(p: argparse.ArgumentParser, *, cross_tenant: bool = False) -> None:
    """SmartEdu 搜索 API 通用参数（scan-catalog/scan-site/detail-probe/search-resources 共用）。

    cross_tenant 默认 False；search-resources 传 True（匹配前端默认开启跨租户）。
    """
    p.add_argument("--identity", default="家长", help="SmartEdu identity，默认 家长")
    p.add_argument("--identity-code", default="GUARDIAN", help="SmartEdu identity_code，默认 GUARDIAN")
    p.add_argument("--search-type", default="resource", help="resource_search_type，默认 resource")
    p.add_argument("--origin", default="basic", help="SmartEdu origin，默认 basic")
    p.add_argument("--order-field", default="_score", help="排序字段")
    p.add_argument("--order-direction", default="desc", help="排序方向")
    p.add_argument("--offset", type=int, default=0, help="分页 offset")
    p.add_argument("--cross-tenant", action="store_true", default=cross_tenant, help="允许跨租户搜索")


def add_route_filters(p: argparse.ArgumentParser, *, route_limit_default: int) -> None:
    """栏目路由筛选参数（site-index/scan-catalog/scan-site 共用）。route_limit_default 因命令而异。"""
    p.add_argument("--route-id", help="只处理指定 route_id")
    p.add_argument("--catalog", help="只处理指定 catalog")
    p.add_argument("--sub-catalog", help="只处理指定 sub_catalog")
    p.add_argument("--type", help="只处理指定栏目 type")
    p.add_argument("--title", help="只处理标题包含该文本的栏目")
    p.add_argument("--route-limit", type=int, default=route_limit_default, help="最多处理多少条栏目路由；0 表示全部")
    p.add_argument("--all-routes", action="store_true", help="处理全部匹配 route，等同于 --route-limit 0")


def add_detail_tracking(p: argparse.ArgumentParser) -> None:
    """详情追踪参数（scan-catalog/scan-site/search-resources 共用）。"""
    p.add_argument("--fetch-details", action="store_true", help="对候选继续追踪详情 JSON 并解析 ti_items")
    p.add_argument("--detail-dir", help="本地详情 JSON 目录；支持 {id}.json、{catalog}-{id}.json、{catalog}/{id}.json")
    p.add_argument("--offline-details-only", action="store_true", help="只使用 --detail-dir，不联网抓取缺失详情")
    p.add_argument("--browser-state", help="可选 Playwright storage state；公开详情失败时用浏览器会话补请求")
    p.add_argument("--timeout", type=int, default=20, help="详情请求超时秒数")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartEdu generic resource source")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("site-profile", help="输出 SmartEdu 站点能力画像")
    profile.add_argument("--library-list-json", help="本地 librarylist JSON；提供后会附带栏目摘要")
    profile.add_argument("--fetch-catalogs", action="store_true", help="联网读取官方栏目配置并附带栏目摘要")
    profile.add_argument("--catalog-sample", type=int, default=8, help="最多输出多少条栏目样例")
    add_auth_args(profile)
    profile.set_defaults(func=run_site_profile)

    catalogs = sub.add_parser("list-catalogs", help="输出 SmartEdu 栏目画像")
    catalogs.add_argument("--library-list-json", help="本地 librarylist JSON；省略时抓取官方公开配置")
    add_auth_args(catalogs)
    catalogs.set_defaults(func=run_list_catalogs)

    route_map = sub.add_parser("route-map", help="输出 SmartEdu 栏目路由图")
    route_map.add_argument("--library-list-json", help="本地 librarylist JSON；省略时抓取官方公开配置")
    add_auth_args(route_map)
    route_map.set_defaults(func=run_route_map)

    site_index = sub.add_parser("site-index", help="输出 SmartEdu 全站 route 覆盖和可选扫描候选索引")
    site_index.add_argument("--route-map-json", help="route-map 输出 JSON；省略时通过 librarylist 构建")
    site_index.add_argument("--library-list-json", help="本地 librarylist JSON；未提供 route-map 时使用")
    site_index.add_argument("--site-scan-json", help="可选 scan-site 输出 JSON；提供后把候选、失败和扫描摘要并入索引")
    add_route_filters(site_index, route_limit_default=0)
    add_auth_args(site_index)
    site_index.set_defaults(func=run_site_index)

    page_profile = sub.add_parser("page-profile", help="分析 SmartEdu 页面 HTML/JS 结构线索")
    page_profile.add_argument("--url", help="页面 URL，默认 https://basic.smartedu.cn/")
    page_profile.add_argument("--html-file", help="本地 HTML 文件；用于离线分析或测试")
    page_profile.add_argument("--fetch-scripts", action="store_true", help="抓取页面引用的 JS 文件并一起分析接口线索")
    page_profile.add_argument("--script-limit", type=int, default=8, help="最多抓取多少个 JS 文件")
    page_profile.add_argument("--timeout", type=int, default=20, help="联网读取页面时的超时秒数")
    add_auth_args(page_profile)
    page_profile.set_defaults(func=run_page_profile)

    scan = sub.add_parser("scan-catalog", help="按栏目路由扫描 SmartEdu 资源候选")
    scan.add_argument("--route-map-json", help="route-map 输出 JSON；省略时通过 librarylist 构建")
    scan.add_argument("--library-list-json", help="本地 librarylist JSON；未提供 route-map 时使用")
    add_route_filters(scan, route_limit_default=5)
    scan.add_argument("--query", help="扫描关键词；省略时使用栏目标题")
    scan.add_argument("--search-response-json", help="本地 SmartEdu 搜索响应 JSON；用于离线扫描测试")
    scan.add_argument("--search-url", help="自定义 SmartEdu 搜索接口 URL")
    add_detail_tracking(scan)
    add_search_params(scan)
    scan.add_argument("--limit", type=int, default=12, help="每条 route 最多输出候选数量")
    add_auth_args(scan)
    scan.set_defaults(func=run_scan_catalog)

    site_scan = sub.add_parser("scan-site", help="按 route-map 批量扫描 SmartEdu 多栏目候选")
    site_scan.add_argument("--route-map-json", help="route-map 输出 JSON；省略时通过 librarylist 构建")
    site_scan.add_argument("--library-list-json", help="本地 librarylist JSON；未提供 route-map 时使用")
    add_route_filters(site_scan, route_limit_default=10)
    site_scan.add_argument("--query", help="扫描关键词；省略时使用栏目标题")
    site_scan.add_argument("--search-response-json", help="本地 SmartEdu 搜索响应 JSON；用于离线扫描测试")
    site_scan.add_argument("--search-url", help="自定义 SmartEdu 搜索接口 URL")
    add_detail_tracking(site_scan)
    site_scan.add_argument("--continue-on-error", action="store_true", help="某条 route 扫描失败时继续扫描后续 route")
    add_search_params(site_scan)
    site_scan.add_argument("--limit", type=int, default=12, help="每条 route 最多输出候选数量")
    add_auth_args(site_scan)
    site_scan.set_defaults(func=run_scan_site)

    detail = sub.add_parser("candidates-from-detail", help="从 SmartEdu 详情 JSON 输出标准候选")
    detail.add_argument("--detail-json", action="append", help="本地 SmartEdu detail JSON，可重复")
    detail.add_argument("--url", help="SmartEdu 详情页 URL，例如 syncClassroom/classActivity、qualityCourse、tchMaterial")
    detail.add_argument("--catalog", help="栏目，例如 qualityCourse、syncClassroom、family")
    detail.add_argument("--sub-catalog", help="子栏目，例如 course、prepare_lesson")
    detail.add_argument("--resource-id", help="资源 ID；与 --catalog 一起尝试抓取详情")
    detail.add_argument("--task-json", help="可选任务 JSON，用于传递 filters")
    detail.add_argument("--query", help="原始查询")
    detail.add_argument("--limit", type=int, default=50, help="最多处理详情数量")
    detail.add_argument("--browser-state", help="可选 Playwright storage state；公开详情失败时用浏览器会话补请求")
    detail.add_argument("--timeout", type=int, default=20, help="详情请求超时秒数")
    add_auth_args(detail)
    detail.set_defaults(func=run_candidates_from_detail)

    detail_probe = sub.add_parser("detail-probe", help="低频探测 SmartEdu 搜索候选能否展开详情 JSON")
    detail_probe.add_argument("--query", help="搜索关键词；省略时从 --task-json 的 filters 中推断")
    detail_probe.add_argument("--task-json", help="可选任务 JSON，用于传递 filters")
    detail_probe.add_argument("--tab-code", action="append", help="SmartEdu tab_code，可重复或逗号分隔")
    detail_probe.add_argument("--search-response-json", help="本地 SmartEdu 搜索响应 JSON；用于离线 probe")
    detail_probe.add_argument("--search-url", help="自定义 SmartEdu 搜索接口 URL")
    detail_probe.add_argument("--detail-dir", help="本地详情 JSON 目录；支持 {id}.json、{catalog}-{id}.json、{catalog}/{id}.json")
    detail_probe.add_argument("--offline-details-only", action="store_true", help="只使用 --detail-dir，不联网抓取缺失详情")
    add_search_params(detail_probe)
    detail_probe.add_argument("--limit", type=int, default=12, help="最多探测多少个搜索候选")
    detail_probe.add_argument("--timeout", type=int, default=20, help="详情请求超时秒数")
    detail_probe.add_argument("--browser-state", help="可选 Playwright storage state；公开详情失败时用浏览器会话补请求")
    add_auth_args(detail_probe)
    detail_probe.set_defaults(func=run_detail_probe)

    search = sub.add_parser("search-resources", help="搜索 SmartEdu 资源并输出标准候选")
    search.add_argument("--query", help="搜索关键词；省略时从 --task-json 的 filters 中推断")
    search.add_argument("--task-json", help="可选任务 JSON，用于传递 filters")
    search.add_argument("--tab-code", action="append", help="SmartEdu tab_code，可重复或逗号分隔")
    search.add_argument("--search-response-json", help="本地 SmartEdu 搜索响应 JSON；用于离线归一化测试")
    search.add_argument("--search-url", help="自定义 SmartEdu 搜索接口 URL")
    add_detail_tracking(search)
    add_search_params(search, cross_tenant=True)
    search.add_argument("--limit", type=int, default=12, help="最多输出候选数量（深度搜索时仅截取前 N 条展示）")
    search.add_argument("--deep-search", action="store_true", help="启用深度搜索：自动分页+多维度交叉，突破API单次200条限制")
    search.add_argument("--max-results", type=int, default=5000, help="深度搜索最大去重候选数（--deep-search 时生效）")
    search.add_argument("--no-deep-search", action="store_true", help="显式禁用深度搜索（覆盖默认行为）")
    add_auth_args(search)
    search.set_defaults(func=run_search_resources)

    textbooks = sub.add_parser("textbook-candidates", help="输出 SmartEdu 站内教材候选")
    textbooks.add_argument("--stage", help="学段，例如 小学")
    textbooks.add_argument("--grade", help="年级，例如 三年级")
    textbooks.add_argument("--subject", help="学科，例如 数学")
    textbooks.add_argument("--version", help="版本，例如 人教版")
    textbooks.add_argument("--volume", help="册次，例如 上册")
    textbooks.add_argument("--query", help="额外关键词")
    textbooks.add_argument("--limit", type=int, help="限制内部索引匹配数量")
    textbooks.add_argument("--show", type=int, default=20, help="最多输出候选数量")
    textbooks.add_argument("--work-dir", default=".smartedu-work/textbooks", help="SmartEdu 教材内部索引工作目录")
    textbooks.add_argument("--sync", action="store_true", help="强制重新同步教材内部索引")
    textbooks.add_argument("-o", "--output", help="写入 JSON 文件")
    textbooks.set_defaults(func=run_textbook_candidates)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
