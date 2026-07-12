#!/usr/bin/env python3
"""Validate the small set of archive/v1 fields consumed by Flow."""

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


def validate(download: dict[str, Any], archive: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    meta = archive.get("_meta", {})
    summary = archive.get("_summary", {})
    data = archive.get("data", {})
    if meta.get("schema_version") != "archive/v1":
        errors.append("Stage 6 schema_version 必须为 archive/v1")
    if meta.get("session_id") != download.get("_meta", {}).get("session_id"):
        errors.append("Stage 6 session_id 必须继承 Stage 5")
    library_root_value = meta.get("library_root")
    if not isinstance(library_root_value, str) or not library_root_value.strip():
        errors.append("Stage 6 _meta.library_root 必须是非空绝对路径")
        library_root = None
    else:
        library_root = Path(library_root_value).expanduser()
        if not library_root.is_absolute():
            errors.append("Stage 6 _meta.library_root 必须是绝对路径")
            library_root = None
        else:
            library_root = library_root.resolve()
    index_resources: dict[str, dict[str, Any]] = {}
    if library_root is not None:
        index_path = library_root / ".library" / "index.json"
        try:
            index = load_object(index_path)
            if index.get("schema_version") != "library-index/v1" or not isinstance(index.get("resources"), list):
                errors.append("资料库索引必须符合 library-index/v1")
            else:
                index_ids = [
                    item.get("resource_id")
                    for item in index["resources"]
                    if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
                ]
                if len(index_ids) != len(set(index_ids)):
                    errors.append("资料库索引 resource_id 不得重复")
                index_resources = {
                    item.get("resource_id"): item
                    for item in index["resources"]
                    if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
                }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"无法读取资料库索引: {exc}")
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return errors + ["Stage 6 data.results 必须是 array"]

    expected_ids = [
        item.get("resource_id") for item in download.get("data", {}).get("results", [])
        if isinstance(item, dict)
    ]
    actual_ids: list[Any] = []
    counts = {"archived": 0, "skipped": 0, "failed": 0}
    for index, item in enumerate(results):
        prefix = f"data.results[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是 object")
            continue
        resource_id = item.get("resource_id")
        actual_ids.append(resource_id)
        if not isinstance(resource_id, str) or not resource_id.strip():
            errors.append(f"{prefix}.resource_id 必须是非空字符串")
        status = item.get("archive_status")
        if status not in counts:
            errors.append(f"{prefix}.archive_status 非法")
            continue
        counts[status] += 1
        paths = item.get("library_paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path.strip() for path in paths):
            errors.append(f"{prefix}.library_paths 必须是路径字符串数组")
            paths = []
        if status == "archived" and not paths:
            errors.append(f"{prefix} archived 时必须至少有一个资料库路径")
        if status == "archived":
            for path in paths:
                library_path = Path(path).expanduser()
                if not library_path.is_absolute():
                    errors.append(f"{prefix}.library_paths 必须使用绝对路径: {path}")
                    continue
                try:
                    resolved = library_path.resolve(strict=True)
                except OSError:
                    errors.append(f"{prefix}.library_paths 路径不存在: {path}")
                    continue
                if not resolved.is_file():
                    errors.append(f"{prefix}.library_paths 必须指向文件: {path}")
                if library_root is not None and resolved != library_root and library_root not in resolved.parents:
                    errors.append(f"{prefix}.library_paths 必须位于资料库根目录: {path}")
                if library_path.is_symlink():
                    errors.append(f"{prefix}.library_paths 不得使用符号链接: {path}")
            indexed = index_resources.get(resource_id)
            if not isinstance(indexed, dict):
                errors.append(f"{prefix} archived 资源必须存在于资料库索引")
            elif set(indexed.get("library_paths") or []) != set(paths):
                errors.append(f"{prefix}.library_paths 必须与资料库索引一致")
        if status == "skipped" and (
            not isinstance(item.get("duplicate_of"), str) or not item["duplicate_of"].strip()
        ):
            errors.append(f"{prefix} skipped 时必须提供 duplicate_of")
        elif status == "skipped":
            duplicate = index_resources.get(item.get("duplicate_of"))
            if not isinstance(duplicate, dict):
                errors.append(f"{prefix}.duplicate_of 必须引用资料库索引中的资源")
            elif set(paths) != set(duplicate.get("library_paths") or []):
                errors.append(f"{prefix}.library_paths 必须与 duplicate_of 的索引路径一致")
        if status == "failed" and not isinstance(item.get("archive_error"), dict):
            errors.append(f"{prefix} failed 时必须提供 archive_error")
        if status == "failed" and paths:
            errors.append(f"{prefix} failed 的 library_paths 必须为空")

    comparable_ids = all(isinstance(value, str) and value for value in actual_ids + expected_ids)
    if not comparable_ids or len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
        errors.append("Stage 6 结果必须与 Stage 5 一一对应且 resource_id 不重复")
    expected_summary = {
        "archived_count": counts["archived"],
        "skipped_count": counts["skipped"],
        "failed_count": counts["failed"],
    }
    if summary != expected_summary:
        errors.append("Stage 6 _summary 必须与 data.results 一致")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 archive/v1 输出")
    parser.add_argument("session_dir", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(
            load_object(args.session_dir / "stage5_download.json"),
            load_object(args.session_dir / "stage6_archive.json"),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
