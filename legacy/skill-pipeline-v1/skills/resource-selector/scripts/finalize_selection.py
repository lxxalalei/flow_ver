#!/usr/bin/env python3
"""Write Stage 4 from a validated Selector review and explicit user choice."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_review import validate as validate_review_document


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def selected_from_review(
    review: dict[str, Any], indices: list[int], resource_ids: list[str], select_all: bool
) -> list[dict[str, Any]]:
    candidates = review.get("data", {}).get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("review.data.candidates 必须是 array")
    chosen_ids = set(resource_ids)
    if select_all:
        chosen_ids.update(item.get("resource_id") for item in candidates if isinstance(item, dict))
    for index in indices:
        if index < 1 or index > len(candidates):
            raise ValueError(f"候选编号越界: {index}")
        chosen_ids.add(candidates[index - 1].get("resource_id"))
    selected: list[dict[str, Any]] = []
    known_ids = {item.get("resource_id") for item in candidates if isinstance(item, dict)}
    unknown = chosen_ids - known_ids
    if unknown:
        raise ValueError(f"选择了未知或已过滤资源: {sorted(unknown)}")
    for item in candidates:
        if item.get("resource_id") not in chosen_ids:
            continue
        result = {"resource_id": item["resource_id"], "quality_score": item["quality_score"]}
        if item.get("notes"):
            result["notes"] = item["notes"]
        selected.append(result)
    return selected


def validate_selection(document: dict[str, Any], review: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = document.get("_meta", {})
    summary = document.get("_summary", {})
    data = document.get("data", {})
    if meta.get("schema_version") != "selection/v1":
        errors.append("Stage 4 schema_version 必须为 selection/v1")
    if meta.get("session_id") != review.get("_meta", {}).get("session_id"):
        errors.append("Stage 4 session_id 必须继承 selector_review")
    status = data.get("status")
    selected = data.get("selected")
    if status not in {"selected", "cancelled"}:
        errors.append("Stage 4 data.status 非法")
    if not isinstance(selected, list):
        return errors + ["Stage 4 data.selected 必须是 array"]
    if status == "selected" and not selected:
        errors.append("selected 状态必须至少选择一个资源")
    if status == "cancelled" and selected:
        errors.append("cancelled 状态不得包含选择")
    ids = [item.get("resource_id") for item in selected if isinstance(item, dict)]
    if len(ids) != len(selected) or any(not isinstance(value, str) or not value for value in ids):
        errors.append("每个选择必须包含非空 resource_id")
    if len(ids) != len(set(ids)):
        errors.append("Stage 4 resource_id 不得重复")
    if summary != {"status": status, "selected_count": len(selected)}:
        errors.append("Stage 4 _summary 必须与 data 一致")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 Stage 4 用户选择")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--indices", default="", help="逗号分隔的展示编号")
    parser.add_argument("--resource-id", action="append", default=[])
    parser.add_argument("--all", action="store_true", dest="select_all")
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    review_path = args.review or args.session_dir / "selector_review.json"
    review = load_object(review_path)
    selector_input = load_object(args.session_dir / "selector_input.json")
    review_errors = validate_review_document(selector_input, review)
    if review_errors:
        raise ValueError(f"selector_review 未通过校验: {'; '.join(review_errors)}")
    session_id = review.get("_meta", {}).get("session_id")
    if args.cancel:
        selected: list[dict[str, Any]] = []
        status = "cancelled"
    else:
        indices = [int(value.strip()) for value in args.indices.split(",") if value.strip()]
        selected = selected_from_review(review, indices, args.resource_id, args.select_all)
        if not selected:
            raise ValueError("未提供明确选择；不要在用户确认前写入 Stage 4")
        status = "selected"
    document = {
        "_meta": {
            "schema_version": "selection/v1",
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        },
        "_summary": {"status": status, "selected_count": len(selected)},
        "data": {"status": status, "selected": selected},
    }
    output_errors = validate_selection(document, review)
    if output_errors:
        raise ValueError(f"Stage 4 输出无效: {'; '.join(output_errors)}")
    output = args.output or args.session_dir / "stage4_selection.json"
    atomic_write(output, document)
    print(json.dumps(document["_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
