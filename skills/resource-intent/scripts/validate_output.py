#!/usr/bin/env python3
"""Validate the compact intent-spec/v1 output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SLOT_NAMES = {
    "core_topic", "learning_domain", "target_age", "grade_level",
    "learning_goal", "difficulty", "resource_types", "format_preferences",
    "file_formats", "use_scenario", "version", "language", "search_mode",
}
ARRAY_SLOTS = {"resource_types", "format_preferences", "file_formats"}
STATUSES = {"explicit", "inferred", "defaulted"}
DIFFICULTIES = {"启蒙", "基础", "同步", "进阶", "竞赛", "不限"}
RESOURCE_TYPES = {"视频类", "音频类", "文档类", "练习类", "图文类", "图片类", "互动类", "活动类", "不限"}
FORMATS = {
    "视频", "教程", "讲解", "课程", "纪录片", "动画", "讲座", "公开课", "短视频",
    "音频", "故事", "朗诵", "儿歌", "听书", "音频课", "播客", "专辑",
    "文档", "课件", "教案", "讲义", "电子书", "知识点整理", "学习资料",
    "练习题", "习题", "试卷", "作业", "测试题", "练习册", "题卡",
    "百科", "指南", "图文教程", "文章", "知识点", "经验", "方法",
    "挂图", "插画", "思维导图", "手抄报", "范画", "图集", "卡片",
    "软件", "应用", "游戏", "题库", "互动课程", "模拟实验",
    "实验", "手工", "活动方案", "亲子游戏", "实践任务", "绘本", "合集",
}
FILE_FORMATS = {
    "PDF", "DOC", "DOCX", "PPT", "PPTX", "XLS", "XLSX", "TXT", "CSV",
    "EPUB", "MOBI", "MP3", "M4A", "WAV", "MP4", "WEBM", "ZIP",
}
SEARCH_MODES = {"standard", "exhaustive"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("根节点必须是 object")
    return value


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def validate(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(document) != {"_meta", "_summary", "data"}:
        errors.append("根节点只能包含 _meta、_summary 和 data")
    meta = document.get("_meta")
    summary = document.get("_summary")
    data = document.get("data")
    if not isinstance(meta, dict):
        return ["缺少 object: _meta"]
    if not isinstance(data, dict):
        return ["缺少 object: data"]
    if not isinstance(summary, dict):
        return ["缺少 object: _summary"]

    allowed_meta = {"schema_version", "session_id", "created_at"}
    if set(meta) != allowed_meta:
        errors.append("_meta 只能包含 schema_version、session_id、created_at")
    if meta.get("schema_version") != "intent-spec/v1":
        errors.append("_meta.schema_version 必须为 intent-spec/v1")
    for key in ("session_id", "created_at"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            errors.append(f"_meta.{key} 必须是非空字符串")

    allowed_data = {"status", "raw_request", "slots", "constraints", "search_concepts", "clarification", "assumptions"}
    if set(data) - allowed_data:
        errors.append(f"data 存在未定义字段: {sorted(set(data) - allowed_data)}")
    status = data.get("status")
    if status not in {"ready", "needs_clarification"}:
        errors.append("data.status 必须为 ready 或 needs_clarification")
    if not isinstance(data.get("raw_request"), str) or not data["raw_request"].strip():
        errors.append("data.raw_request 必须是非空字符串")

    slots = data.get("slots")
    if not isinstance(slots, dict):
        errors.append("data.slots 必须是 object")
        slots = {}
    extra_slots = set(slots) - SLOT_NAMES
    if extra_slots:
        errors.append(f"data.slots 存在未定义字段: {sorted(extra_slots)}")
    for name, slot in slots.items():
        if not isinstance(slot, dict):
            errors.append(f"slots.{name} 必须是 object")
            continue
        if set(slot) != {"value", "status", "evidence"}:
            errors.append(f"slots.{name} 只能包含 value、status、evidence")
        slot_status = slot.get("status")
        value = slot.get("value")
        evidence = slot.get("evidence")
        if slot_status not in STATUSES:
            errors.append(f"slots.{name}.status 非法")
        if name in ARRAY_SLOTS:
            if not _string_list(value):
                errors.append(f"slots.{name}.value 必须是非空字符串数组")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"slots.{name}.value 必须是非空字符串")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            errors.append(f"slots.{name}.evidence 必须是字符串数组")
            evidence = []
        if slot_status in {"explicit", "inferred"} and not evidence:
            errors.append(f"slots.{name} 标为 {slot_status} 时必须提供 evidence")

    if status == "ready" and not slots.get("core_topic", {}).get("value"):
        errors.append("ready 状态必须有 core_topic")

    difficulty = slots.get("difficulty", {}).get("value") if isinstance(slots.get("difficulty"), dict) else None
    if difficulty is not None and difficulty not in DIFFICULTIES:
        errors.append(f"difficulty 非法: {difficulty!r}")
    resource_types = slots.get("resource_types", {}).get("value", []) if isinstance(slots.get("resource_types"), dict) else []
    if isinstance(resource_types, list) and set(resource_types) - RESOURCE_TYPES:
        errors.append(f"resource_types 含非法值: {sorted(set(resource_types) - RESOURCE_TYPES)}")
    formats = slots.get("format_preferences", {}).get("value", []) if isinstance(slots.get("format_preferences"), dict) else []
    if isinstance(formats, list) and set(formats) - FORMATS:
        errors.append(f"format_preferences 含非法值: {sorted(set(formats) - FORMATS)}")
    file_formats = slots.get("file_formats", {}).get("value", []) if isinstance(slots.get("file_formats"), dict) else []
    if isinstance(file_formats, list):
        if any(item != item.upper() for item in file_formats):
            errors.append("file_formats 必须使用大写规范值")
        if set(file_formats) - FILE_FORMATS:
            errors.append(f"file_formats 含非法值: {sorted(set(file_formats) - FILE_FORMATS)}")
    search_mode = slots.get("search_mode", {}).get("value") if isinstance(slots.get("search_mode"), dict) else None
    if search_mode is not None and search_mode not in SEARCH_MODES:
        errors.append(f"search_mode 非法: {search_mode!r}")

    constraints = data.get("constraints")
    if not isinstance(constraints, dict):
        errors.append("data.constraints 必须是 object")
        constraints = {}
    elif set(constraints) - {"must", "prefer", "exclude"}:
        errors.append("constraints 只能包含 must、prefer、exclude")
    for key, value in constraints.items():
        if not _string_list(value):
            errors.append(f"constraints.{key} 必须是非空字符串数组")
    must = set(constraints.get("must", []))
    excluded = set(constraints.get("exclude", []))
    if must & excluded:
        errors.append(f"must 与 exclude 冲突: {sorted(must & excluded)}")

    concepts = data.get("search_concepts")
    if not isinstance(concepts, dict):
        errors.append("data.search_concepts 必须是 object")
    else:
        extra = set(concepts) - {"canonical_terms", "synonyms", "related_terms"}
        if extra:
            errors.append(f"search_concepts 存在未定义字段: {sorted(extra)}")
        for key, value in concepts.items():
            if not _string_list(value):
                errors.append(f"search_concepts.{key} 必须是非空字符串数组")

    clarification = data.get("clarification")
    if status == "needs_clarification":
        if not isinstance(clarification, dict) or set(clarification) != {"question", "reason"}:
            errors.append("needs_clarification 状态必须提供仅含 question、reason 的 clarification")
        else:
            for key in ("question", "reason"):
                if not isinstance(clarification.get(key), str) or not clarification[key].strip():
                    errors.append(f"clarification.{key} 必须是非空字符串")
    elif clarification is not None:
        errors.append("ready 状态不得输出 clarification")

    if summary.get("status") != status:
        errors.append("_summary.status 必须与 data.status 一致")
    if status == "ready":
        if set(summary) != {"status"}:
            errors.append("ready 状态的 _summary 只能包含 status")
    elif status == "needs_clarification":
        question = clarification.get("question") if isinstance(clarification, dict) else None
        if set(summary) != {"status", "question"} or summary.get("question") != question:
            errors.append("needs_clarification 的 _summary.question 必须与 data.clarification.question 一致")

    assumptions = data.get("assumptions")
    if assumptions is not None and not _string_list(assumptions):
        errors.append("data.assumptions 必须是非空字符串数组")
    if any(isinstance(slot, dict) and slot.get("status") == "defaulted" for slot in slots.values()) and not assumptions:
        errors.append("存在 defaulted 槽位时必须说明 assumptions")

    for forbidden in ("queries", "search_tasks", "selected_platforms"):
        if forbidden in data:
            errors.append(f"Intent 不得输出搜索执行字段: data.{forbidden}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验精简 intent-spec/v1 输出")
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load_json(args.file))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
