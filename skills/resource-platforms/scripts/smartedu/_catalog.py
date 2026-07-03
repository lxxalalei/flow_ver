#!/usr/bin/env python3
"""SmartEdu 栏目与路由处理。

Phase 3E 从 smartedu_resources.py 拆出的栏目/路由域：librarylist → 扁平栏目 →
路由图 → 覆盖统计/扫描摘要。纯数据变换，不依赖 argparse 或命令入口；
route-map/site-index/scan 命令通过 import 复用。
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from _constants import (
    CATALOG_TAB_HINTS,
    CATALOG_TO_TAB,
    DEFAULT_TAB_CODES,
    DETAIL_URLS,
    SEARCH_URLS,
    TYPE_TO_TAB,
    VALID_TAB_CODES,
)
from _text_utils import norm, stable_id


def flatten_catalogs(items: list[dict[str, Any]], parent: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = norm(item.get("name") or item.get("title") or item.get("catalog_name"))
        catalog = norm(item.get("catalog") or item.get("id") or item.get("code"))
        is_textbook = item.get("type") == "tchMaterial" or catalog == "tchMaterial"
        row = {
            "id": item.get("id"),
            "title": title,
            "catalog": catalog,
            "catalog_name": item.get("catalog_name") or title,
            "type": item.get("type") or item.get("code"),
            "resource_family": "教材" if is_textbook else "通用资源",
            "sub_catalog": item.get("sub_catalog"),
            "sub_catalog_name": item.get("sub_catalog_name"),
            "parent": parent,
            "known_skill": "smartedu",
            "internal_adapter": "tchMaterial" if is_textbook else "",
            "external": bool(item.get("h5_url") or (item.get("page_mode") or {}).get("type") == "outer_link"),
            "raw": item,
        }
        rows.append(row)
        children = item.get("child")
        if isinstance(children, list):
            rows.extend(flatten_catalogs(children, title or parent))
    return rows


def catalog_summary(catalogs: list[dict[str, Any]]) -> dict[str, Any]:
    families: dict[str, int] = {}
    for item in catalogs:
        family = norm(item.get("resource_family")) or "通用资源"
        families[family] = families.get(family, 0) + 1
    return {
        "catalogs": len(catalogs),
        "resource_catalogs": sum(1 for item in catalogs if item.get("known_skill") == "smartedu"),
        "external_catalogs": sum(1 for item in catalogs if item.get("external")),
        "textbook_catalogs": sum(1 for item in catalogs if item.get("internal_adapter") == "tchMaterial"),
        "resource_families": families,
    }


def catalog_page_url(row: dict[str, Any]) -> str:
    catalog = norm(row.get("catalog")) or "syncClassroom"
    sub_catalog = norm(row.get("sub_catalog"))
    if catalog == "tchMaterial":
        return "https://basic.smartedu.cn/tchMaterial"
    if sub_catalog:
        return f"https://basic.smartedu.cn/{urllib.parse.quote(catalog)}?subCatalog={urllib.parse.quote(sub_catalog)}"
    return f"https://basic.smartedu.cn/{urllib.parse.quote(catalog)}"


def search_tab_for(row: dict[str, Any]) -> str:
    """为栏目 route 生成搜索 API 认识的有效 tab_code。

    搜索接口只接受 VALID_TAB_CODES 中的 tab_code。栏目 librarylist 返回的
    type/sub_catalog（如 agzy/xljk/jygn）不是有效 tab，需要映射到所属大类。

    查找优先级：
    1. type/sub_catalog/catalog 本身就是有效 tab → 直接用
    2. type → TYPE_TO_TAB 映射
    3. sub_catalog → TYPE_TO_TAB 映射
    4. catalog → CATALOG_TO_TAB 兜底映射
    5. 旧版 CATALOG_TAB_HINTS
    6. DEFAULT_TAB_CODES[0]
    """
    row_type = norm(row.get("type"))
    catalog = norm(row.get("catalog"))
    sub_catalog = norm(row.get("sub_catalog"))

    # 1. 本身就是有效 tab
    for value in [row_type, sub_catalog, catalog]:
        if value and value in VALID_TAB_CODES:
            return value

    # 2-3. type / sub_catalog → TYPE_TO_TAB
    for value in [row_type, sub_catalog]:
        if value and value in TYPE_TO_TAB:
            mapped = TYPE_TO_TAB[value]
            if mapped in VALID_TAB_CODES:
                return mapped

    # 4. catalog → CATALOG_TO_TAB
    if catalog and catalog in CATALOG_TO_TAB:
        mapped = CATALOG_TO_TAB[catalog]
        if mapped in VALID_TAB_CODES:
            return mapped

    # 5. 旧版 hints（向后兼容）
    for value in [row_type, sub_catalog, catalog]:
        if value in CATALOG_TAB_HINTS:
            return CATALOG_TAB_HINTS[value]

    # 6. 兜底
    return DEFAULT_TAB_CODES[0]


def route_for_catalog(row: dict[str, Any]) -> dict[str, Any]:
    catalog = norm(row.get("catalog")) or "syncClassroom"
    sub_catalog = norm(row.get("sub_catalog"))
    row_type = norm(row.get("type"))
    internal_adapter = norm(row.get("internal_adapter"))
    if internal_adapter == "tchMaterial" or catalog == "tchMaterial" or row_type == "tchMaterial":
        scan_strategy = "internal_adapter"
        commands = [
            "textbook-candidates",
        ]
        endpoints = []
        detail_templates = []
    else:
        scan_strategy = "search_then_detail"
        commands = [
            "search-resources",
            "candidates-from-detail",
        ]
        endpoints = list(SEARCH_URLS)
        detail_templates = [template.format(catalog=catalog, id="{id}") for template in DETAIL_URLS]
    return {
        "route_id": stable_id("|".join([catalog, sub_catalog, row_type, norm(row.get("title"))])),
        "title": row.get("title"),
        "catalog": catalog,
        "catalog_name": row.get("catalog_name"),
        "sub_catalog": sub_catalog,
        "sub_catalog_name": row.get("sub_catalog_name"),
        "type": row_type,
        "resource_family": row.get("resource_family") or "通用资源",
        "page_url": catalog_page_url(row),
        "known_skill": "smartedu",
        "internal_adapter": internal_adapter,
        "scan_strategy": scan_strategy,
        "supported_commands": commands,
        "search_tab_code": search_tab_for(row),
        "search_payload_defaults": {
            "origin": "basic",
            "resource_search_type": "resource",
            "tab_codes": [search_tab_for(row)],
            "catalog": catalog,
            "sub_catalog": sub_catalog,
        },
        "detail_url_templates": detail_templates,
        "requires_runtime_validation": scan_strategy != "internal_adapter",
        "notes": [
            "搜索接口返回候选后通常还需要详情 JSON 才能解析真实文件项。",
            "详情文件项解析依赖 ti_items。",
        ]
        if scan_strategy != "internal_adapter"
        else ["教材分支当前通过内部兼容适配器生成候选。"],
        "raw_catalog": row.get("raw") or {},
    }


def dedupe_routes(routes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for route in routes:
        key = norm(route.get("route_id")) or stable_id(
            "|".join(
                [
                    norm(route.get("catalog")),
                    norm(route.get("sub_catalog")),
                    norm(route.get("type")),
                    norm(route.get("title")),
                ]
            )
        )
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(route)
    return unique, duplicates


def count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = norm(value) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def route_coverage(routes: list[dict[str, Any]]) -> dict[str, Any]:
    command_values: list[str] = []
    for route in routes:
        command_values.extend(str(item) for item in route.get("supported_commands") or [])
    return {
        "catalogs": count_values([norm(item.get("catalog")) for item in routes]),
        "sub_catalogs": count_values([norm(item.get("sub_catalog")) for item in routes if norm(item.get("sub_catalog"))]),
        "types": count_values([norm(item.get("type")) for item in routes]),
        "resource_families": count_values([norm(item.get("resource_family")) for item in routes]),
        "scan_strategies": count_values([norm(item.get("scan_strategy")) for item in routes]),
        "search_tab_codes": count_values([norm(item.get("search_tab_code")) for item in routes]),
        "supported_commands": count_values(command_values),
    }


def route_scan_plan(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_id": route.get("route_id"),
        "title": route.get("title"),
        "catalog": route.get("catalog"),
        "sub_catalog": route.get("sub_catalog"),
        "type": route.get("type"),
        "page_url": route.get("page_url"),
        "scan_strategy": route.get("scan_strategy"),
        "search_tab_code": route.get("search_tab_code"),
        "supported_commands": route.get("supported_commands") or [],
        "requires_runtime_validation": bool(route.get("requires_runtime_validation")),
    }


def scan_route_summary(route_results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = count_values([norm(item.get("status")) for item in route_results])
    detail_status_values: list[str] = []
    detail_policy_values: list[str] = []
    for result in route_results:
        for candidate in result.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
            detail = raw.get("smartedu_detail") if isinstance(raw.get("smartedu_detail"), dict) else {}
            if detail:
                detail_status_values.append(norm(detail.get("detail_status")))
                detail_policy_values.append(norm(detail.get("detail_access_policy")))
        for failure in result.get("detail_failures") or []:
            if isinstance(failure, dict):
                detail_status_values.append(norm(failure.get("detail_status")))
                detail_policy_values.append(norm(failure.get("detail_access_policy")))
    return {
        "routes_scanned": len(route_results),
        "statuses": statuses,
        "search_items_seen": sum(int(item.get("search_items_seen") or 0) for item in route_results),
        "candidates": sum(len(item.get("candidates") or []) for item in route_results),
        "detail_failures": sum(len(item.get("detail_failures") or []) for item in route_results),
        "details_fetched": sum(int((item.get("summary") or {}).get("details_fetched") or 0) for item in route_results),
        "detail_items_seen": sum(int((item.get("summary") or {}).get("detail_items_seen") or 0) for item in route_results),
        "detail_status_counts": count_values(detail_status_values),
        "detail_access_policy_counts": count_values(detail_policy_values),
    }


def route_detail_coverage(route_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for result in route_results:
        route = result.get("route") if isinstance(result.get("route"), dict) else {}
        detail_status_values: list[str] = []
        detail_policy_values: list[str] = []
        for candidate in result.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
            detail = raw.get("smartedu_detail") if isinstance(raw.get("smartedu_detail"), dict) else {}
            if detail:
                detail_status_values.append(norm(detail.get("detail_status")))
                detail_policy_values.append(norm(detail.get("detail_access_policy")))
        for failure in result.get("detail_failures") or []:
            if isinstance(failure, dict):
                detail_status_values.append(norm(failure.get("detail_status")))
                detail_policy_values.append(norm(failure.get("detail_access_policy")))
        if not detail_status_values and not detail_policy_values:
            continue
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        coverage.append(
            {
                "route_id": route.get("route_id"),
                "title": route.get("title"),
                "catalog": route.get("catalog"),
                "sub_catalog": route.get("sub_catalog"),
                "type": route.get("type"),
                "search_tab_code": route.get("search_tab_code"),
                "search_items_seen": result.get("search_items_seen", 0),
                "details_fetched": int(summary.get("details_fetched") or 0),
                "detail_items_seen": int(summary.get("detail_items_seen") or 0),
                "detail_failures": len(result.get("detail_failures") or []),
                "detail_status_counts": count_values(detail_status_values),
                "detail_access_policy_counts": count_values(detail_policy_values),
            }
        )
    return coverage
