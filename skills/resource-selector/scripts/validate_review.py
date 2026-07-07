#!/usr/bin/env python3
"""Validate the model-authored Selector review before user display."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def validate(selector_input: dict[str, Any], review: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    input_session = selector_input.get("_meta", {}).get("session_id")
    if review.get("_meta", {}).get("schema_version") != "selector-review/v1":
        errors.append("review schema_version 必须是 selector-review/v1")
    if review.get("_meta", {}).get("session_id") != input_session:
        errors.append("review session_id 与 selector_input 不一致")
    input_ids = {
        item.get("resource_id") for item in selector_input.get("data", {}).get("candidates", [])
        if isinstance(item, dict) and item.get("resource_id")
    }
    data = review.get("data")
    if not isinstance(data, dict):
        return errors + ["review.data 必须是 object"]
    candidates = data.get("candidates")
    excluded = data.get("excluded")
    if not isinstance(candidates, list) or not isinstance(excluded, list):
        return errors + ["review.data.candidates 和 excluded 必须是 array"]
    reviewed_ids: list[str] = []
    for index, item in enumerate(candidates):
        prefix = f"candidates[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是 object")
            continue
        resource_id = item.get("resource_id")
        reviewed_ids.append(resource_id)
        score = item.get("quality_score")
        if not isinstance(score, int) or isinstance(score, bool) or not 40 <= score <= 100:
            errors.append(f"{prefix}.quality_score 必须是 40-100 整数")
        reasons = item.get("reasons")
        if not isinstance(reasons, list) or not reasons or not all(isinstance(value, str) and value.strip() for value in reasons):
            errors.append(f"{prefix}.reasons 必须是非空字符串数组")
        summary = item.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{prefix}.summary 必须是非空字符串")
        elif len(summary) > 50:
            errors.append(f"{prefix}.summary 不得超过 50 字")
        notes = item.get("notes", [])
        if not isinstance(notes, list) or not all(isinstance(value, str) and value.strip() for value in notes):
            errors.append(f"{prefix}.notes 必须是字符串数组")
    for index, item in enumerate(excluded):
        prefix = f"excluded[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是 object")
            continue
        reviewed_ids.append(item.get("resource_id"))
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            errors.append(f"{prefix}.reason 必须是非空字符串")
    if len(reviewed_ids) != len(set(reviewed_ids)):
        errors.append("同一 resource_id 不能重复审查")
    reviewed_set = set(reviewed_ids)
    if reviewed_set != input_ids:
        missing = sorted(input_ids - reviewed_set)
        extra = sorted(reviewed_set - input_ids, key=str)
        if missing:
            errors.append(f"缺少审查资源: {missing}")
        if extra:
            errors.append(f"出现未知资源: {extra}")
    scores = [item.get("quality_score", 0) for item in candidates if isinstance(item, dict)]
    if scores != sorted(scores, reverse=True):
        errors.append("candidates 必须按 quality_score 降序排列")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Selector 模型审查")
    parser.add_argument("selector_input", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    errors = validate(load_object(args.selector_input), load_object(args.review))
    if errors:
        for error in errors:
            print(error)
        return 1
    print("selector review valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
