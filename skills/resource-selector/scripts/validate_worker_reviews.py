#!/usr/bin/env python3
"""Validate coverage and shape of optional parallel Selector worker reviews."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def string_list(value: Any, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and item.strip() for item in value)
        and len(value) == len(set(value))
    )


def input_fingerprint(selector_input: dict[str, Any]) -> str:
    canonical = json.dumps(
        selector_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate(selector_input: dict[str, Any], worker_files: list[Path]) -> list[str]:
    errors: list[str] = []
    input_session = selector_input.get("_meta", {}).get("session_id")
    fingerprint = input_fingerprint(selector_input)
    input_ids = [
        item.get("resource_id")
        for item in selector_input.get("data", {}).get("candidates", [])
        if isinstance(item, dict)
    ]
    if not string_list(input_ids):
        errors.append("selector_input 候选必须具有唯一的非空 resource_id")
    if not worker_files:
        return errors + ["没有找到 selector_worker_reviews/worker-*.json"]

    assigned_global: list[str] = []
    reviewed_global: list[str] = []
    candidates_by_id = {
        item.get("resource_id"): item
        for item in selector_input.get("data", {}).get("candidates", [])
        if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
    }
    for path in worker_files:
        try:
            document = load_object(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            continue
        worker_id = document.get("worker_id")
        prefix = path.name
        allowed_document_fields = {
            "worker_id",
            "session_id",
            "selector_input_fingerprint",
            "assigned_resource_ids",
            "reviews",
        }
        extra_document_fields = sorted(set(document) - allowed_document_fields)
        if extra_document_fields:
            errors.append(f"{prefix} 包含未允许字段: {extra_document_fields}")
        if not isinstance(worker_id, str) or not worker_id.strip():
            errors.append(f"{prefix}.worker_id 必须是非空字符串")
        elif path.name != f"worker-{worker_id}.json":
            errors.append(f"{prefix} 文件名必须与 worker_id 一致")
        if document.get("session_id") != input_session:
            errors.append(f"{prefix}.session_id 与 selector_input 不一致")
        if document.get("selector_input_fingerprint") != fingerprint:
            errors.append(f"{prefix}.selector_input_fingerprint 与当前输入不一致")
        assigned = document.get("assigned_resource_ids")
        if not string_list(assigned, allow_empty=False):
            errors.append(f"{prefix}.assigned_resource_ids 必须是唯一非空字符串数组")
            assigned = []
        assigned_global.extend(assigned)
        reviews = document.get("reviews")
        if not isinstance(reviews, list):
            errors.append(f"{prefix}.reviews 必须是 array")
            continue
        review_ids: list[str] = []
        for index, review in enumerate(reviews):
            item_prefix = f"{prefix}.reviews[{index}]"
            if not isinstance(review, dict):
                errors.append(f"{item_prefix} 必须是 object")
                continue
            allowed_review_fields = {"resource_id", "facts", "unknowns", "verdict", "reason"}
            extra_review_fields = sorted(set(review) - allowed_review_fields)
            if extra_review_fields:
                errors.append(f"{item_prefix} 包含未允许字段: {extra_review_fields}")
            resource_id = review.get("resource_id")
            if not isinstance(resource_id, str) or not resource_id.strip():
                errors.append(f"{item_prefix}.resource_id 必须是非空字符串")
                continue
            review_ids.append(resource_id)
            facts = review.get("facts")
            if not isinstance(facts, list):
                errors.append(f"{item_prefix}.facts 必须是 array")
            else:
                seen_facts: set[tuple[str, str]] = set()
                allowed_sources = {"stage3"}
                source_url = candidates_by_id.get(resource_id, {}).get("source_url")
                if isinstance(source_url, str) and source_url:
                    allowed_sources.add(source_url)
                for fact_index, fact in enumerate(facts):
                    fact_prefix = f"{item_prefix}.facts[{fact_index}]"
                    if not isinstance(fact, dict) or set(fact) != {"claim", "source"}:
                        errors.append(f"{fact_prefix} 必须只包含 claim 和 source")
                        continue
                    claim = fact.get("claim")
                    source = fact.get("source")
                    if not isinstance(claim, str) or not claim.strip():
                        errors.append(f"{fact_prefix}.claim 必须是非空字符串")
                    if source not in allowed_sources:
                        errors.append(f"{fact_prefix}.source 必须是 stage3 或该候选 source_url")
                    key = (str(claim), str(source))
                    if key in seen_facts:
                        errors.append(f"{fact_prefix} 不得重复")
                    seen_facts.add(key)
            if not string_list(review.get("unknowns"), allow_empty=True):
                errors.append(f"{item_prefix}.unknowns 必须是唯一字符串数组")
            if review.get("verdict") not in {"keep", "exclude", "uncertain"}:
                errors.append(f"{item_prefix}.verdict 非法")
            if not isinstance(review.get("reason"), str) or not review["reason"].strip():
                errors.append(f"{item_prefix}.reason 必须是非空字符串")
        if len(review_ids) != len(set(review_ids)) or set(review_ids) != set(assigned):
            errors.append(f"{prefix}.reviews 必须与 assigned_resource_ids 一一对应")
        reviewed_global.extend(review_ids)

    if len(assigned_global) != len(set(assigned_global)):
        errors.append("不同 worker 的 assigned_resource_ids 不得重叠")
    if set(assigned_global) != set(input_ids):
        errors.append("worker 批次必须完整覆盖 selector_input 候选")
    if len(reviewed_global) != len(set(reviewed_global)) or set(reviewed_global) != set(input_ids):
        errors.append("worker reviews 必须恰好审查每个候选一次")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Selector 并行 worker 私有审查")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--fingerprint", action="store_true", help="只输出当前 selector_input 指纹")
    parser.add_argument("--cleanup", action="store_true", help="校验通过后删除私有 worker 目录")
    args = parser.parse_args()
    review_dir = args.session_dir / "selector_worker_reviews"
    try:
        selector_input = load_object(args.session_dir / "selector_input.json")
        if args.fingerprint:
            print(input_fingerprint(selector_input))
            return 0
        errors = validate(
            selector_input,
            sorted(review_dir.glob("worker-*.json")),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    if not errors and args.cleanup:
        shutil.rmtree(review_dir)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
