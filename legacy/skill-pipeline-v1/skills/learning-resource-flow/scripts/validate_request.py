#!/usr/bin/env python3
"""Validate a request/v1 snapshot before resource-intent reads it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("根节点必须是 object")
    return value


def validate(document: dict[str, Any], path: Path | None = None) -> list[str]:
    errors: list[str] = []
    if set(document) != {"_meta", "data"}:
        missing = {"_meta", "data"} - set(document)
        extra = set(document) - {"_meta", "data"}
        if missing:
            errors.append(f"根节点缺少字段: {sorted(missing)}")
        if extra:
            errors.append(f"根节点存在未定义字段: {sorted(extra)}")

    meta = document.get("_meta")
    data = document.get("data")
    if not isinstance(meta, dict):
        errors.append("_meta 必须是 object")
        meta = {}
    if not isinstance(data, dict):
        errors.append("data 必须是 object")
        data = {}

    session_id = meta.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        errors.append("_meta.session_id 必须是非空字符串")
    if not isinstance(meta.get("created_at"), str) or not meta.get("created_at", "").strip():
        errors.append("_meta.created_at 必须是非空字符串")
    if meta.get("schema_version") != "request/v1":
        errors.append("_meta.schema_version 必须为 request/v1")
    if set(meta) - {"schema_version", "session_id", "created_at"}:
        errors.append(f"_meta 存在未定义字段: {sorted(set(meta) - {'schema_version', 'session_id', 'created_at'})}")
    if path is not None and isinstance(session_id, str) and path.name == "request.json":
        if path.parent.name != session_id:
            errors.append("_meta.session_id 必须与 request.json 的父目录名一致")

    allowed_data = {"raw_request", "conversation_evidence"}
    extra_data = set(data) - allowed_data
    if extra_data:
        errors.append(f"data 存在未定义字段: {sorted(extra_data)}")
    if not isinstance(data.get("raw_request"), str) or not data.get("raw_request", "").strip():
        errors.append("data.raw_request 必须是非空字符串")

    evidence = data.get("conversation_evidence")
    if not isinstance(evidence, list):
        errors.append("data.conversation_evidence 必须是数组")
    else:
        for index, item in enumerate(evidence):
            prefix = f"data.conversation_evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} 必须是 object")
                continue
            if set(item) != {"role", "content"}:
                errors.append(f"{prefix} 只能包含 role 和 content")
            if item.get("role") not in {"user", "assistant"}:
                errors.append(f"{prefix}.role 必须为 user 或 assistant")
            if not isinstance(item.get("content"), str) or not item.get("content", "").strip():
                errors.append(f"{prefix}.content 必须是非空字符串")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Flow request/v1 快照")
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load_json(args.file), args.file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
