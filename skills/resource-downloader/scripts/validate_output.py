#!/usr/bin/env python3
"""Validate the small set of download/v1 fields consumed by Library Manager."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from content_validation import validate_download_file


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def error_is_valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("error_code"), str)
        and bool(value["error_code"].strip())
        and isinstance(value.get("message"), str)
        and bool(value["message"].strip())
        and isinstance(value.get("retryable"), bool)
    )


def validate(session_dir: Path, selection: dict[str, Any], stage3: dict[str, Any], output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    downloads_root = (session_dir / "downloads").resolve()
    archived_results: dict[str, dict[str, Any]] = {}
    archive_path = session_dir / "stage6_archive.json"
    if archive_path.is_file():
        try:
            archive = load_object(archive_path)
            if archive.get("_meta", {}).get("session_id") == output.get("_meta", {}).get("session_id"):
                archived_results = {
                    item.get("resource_id"): item
                    for item in archive.get("data", {}).get("results", [])
                    if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
                }
        except (OSError, ValueError, json.JSONDecodeError):
            archived_results = {}

    def has_archived_replacement(resource_id: Any) -> bool:
        archived = archived_results.get(resource_id)
        if not isinstance(archived, dict) or archived.get("archive_status") not in {"archived", "skipped"}:
            return False
        paths = archived.get("library_paths")
        return (
            isinstance(paths, list)
            and bool(paths)
            and all(
                isinstance(raw_path, str)
                and Path(raw_path).is_absolute()
                and Path(raw_path).resolve().is_file()
                for raw_path in paths
            )
        )
    selection_meta = selection.get("_meta", {})
    meta = output.get("_meta", {})
    summary = output.get("_summary", {})
    data = output.get("data", {})
    if meta.get("schema_version") != "download/v1":
        errors.append("Stage 5 schema_version 必须为 download/v1")
    if meta.get("session_id") != selection_meta.get("session_id"):
        errors.append("Stage 5 session_id 必须继承 Stage 4")
    if stage3.get("_meta", {}).get("session_id") != selection_meta.get("session_id"):
        errors.append("Stage 3 与 Stage 4 session_id 不一致")
    if selection.get("data", {}).get("status") != "selected":
        errors.append("只有 selected 状态可以生成 Stage 5")

    selected = selection.get("data", {}).get("selected", [])
    expected_ids = [item.get("resource_id") for item in selected if isinstance(item, dict)]
    stage3_ids = {
        item.get("resource_id") for item in stage3.get("data", {}).get("resources", [])
        if isinstance(item, dict)
    }
    missing_sources = [resource_id for resource_id in expected_ids if resource_id not in stage3_ids]
    if missing_sources:
        errors.append(f"Stage 3 缺少已选资源: {missing_sources}")

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return errors + ["Stage 5 data.results 必须是 array"]
    actual_ids: list[Any] = []
    counts = {"success": 0, "degraded": 0, "failed": 0}
    for index, item in enumerate(results):
        prefix = f"data.results[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是 object")
            continue
        resource_id = item.get("resource_id")
        actual_ids.append(resource_id)
        if not isinstance(resource_id, str) or not resource_id.strip():
            errors.append(f"{prefix}.resource_id 必须是非空字符串")
        status = item.get("download_status")
        if status not in counts:
            errors.append(f"{prefix}.download_status 非法")
            continue
        counts[status] += 1
        files = item.get("files")
        if not isinstance(files, list) or any(not isinstance(path, str) or not path.strip() for path in files):
            errors.append(f"{prefix}.files 必须是路径字符串数组")
            files = []
        if status in {"success", "degraded"}:
            if not files:
                errors.append(f"{prefix} 成功或降级时必须至少有一个文件")
            for raw_path in files:
                path = Path(raw_path)
                if not path.is_absolute():
                    errors.append(f"{prefix}.files 必须使用绝对路径: {raw_path}")
                    continue
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    if not has_archived_replacement(resource_id):
                        errors.append(f"{prefix}.files 文件不存在: {raw_path}")
                    continue
                if not resolved.is_file():
                    errors.append(f"{prefix}.files 不是文件: {raw_path}")
                    continue
                if resolved == downloads_root or downloads_root not in resolved.parents:
                    errors.append(f"{prefix}.files 必须位于本次会话 downloads 目录: {raw_path}")
                if path.is_symlink():
                    errors.append(f"{prefix}.files 不得使用符号链接: {raw_path}")
                validation = validate_download_file(resolved)
                if not validation.get("valid"):
                    issues = validation.get("errors")
                    messages = [
                        str(issue.get("message"))
                        for issue in issues
                        if isinstance(issue, dict) and issue.get("message")
                    ] if isinstance(issues, list) else []
                    errors.append(f"{prefix}.files 内容校验失败: {raw_path}: {'; '.join(messages) or '未知格式或损坏文件'}")
                try:
                    relative = resolved.relative_to(downloads_root)
                    if relative.parts and relative.parts[0] == ".partial":
                        errors.append(f"{prefix}.files 不得指向未完成下载目录: {raw_path}")
                except ValueError:
                    pass
        if status == "success" and ("degraded_level" in item or "error" in item):
            errors.append(f"{prefix} success 不得包含 degraded_level 或 error")
        if status == "degraded":
            if item.get("degraded_level") not in {"Level 1", "Level 2", "Level 3"}:
                errors.append(f"{prefix}.degraded_level 非法")
            if not error_is_valid(item.get("error")):
                errors.append(f"{prefix}.error 必须是完整错误对象")
        if status == "failed":
            if files:
                errors.append(f"{prefix} failed 的 files 必须为空")
            if not error_is_valid(item.get("error")):
                errors.append(f"{prefix}.error 必须是完整错误对象")

    comparable_ids = all(isinstance(value, str) and value for value in actual_ids + expected_ids)
    if not comparable_ids or len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
        errors.append("Stage 5 结果必须与 Stage 4 选择一一对应且 resource_id 不重复")
    expected_summary = {
        "success_count": counts["success"],
        "degraded_count": counts["degraded"],
        "failed_count": counts["failed"],
    }
    if summary != expected_summary:
        errors.append("Stage 5 _summary 必须与 data.results 一致")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 download/v1 输出")
    parser.add_argument("session_dir", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(
            args.session_dir,
            load_object(args.session_dir / "stage4_selection.json"),
            load_object(args.session_dir / "stage3_search_results.json"),
            load_object(args.session_dir / "stage5_download.json"),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
