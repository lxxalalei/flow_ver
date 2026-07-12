#!/usr/bin/env python3
"""Create, validate, and transition learning-resource session manifests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILLS_ROOT = Path(__file__).resolve().parents[2]
STAGE_OUTPUTS = {
    1: "stage1_intent.json",
    2: "stage2_search_plan.json",
    3: "stage3_search_results.json",
    4: "stage4_selection.json",
    5: "stage5_download.json",
    6: "stage6_archive.json",
}
STAGE_STATUSES = {"pending", "in_progress", "waiting_user", "completed", "failed", "cancelled"}
SESSION_STATUSES = {"in_progress", "waiting_user", "completed", "failed", "cancelled"}
ROOT_FIELDS = {
    "schema_version", "session_id", "created_at", "updated_at", "status",
    "current_stage", "stages", "error", "completed_at", "cancelled_at",
}
STAGE_FIELDS = {"status", "output", "started_at", "completed_at", "waiting_for", "error"}
NEXT_ACTIONS = {
    1: "run_resource_intent",
    2: "run_resource_search",
    3: "run_resource_platforms",
    4: "run_resource_selector",
    5: "run_resource_downloader",
    6: "run_library_manager",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载校验器: {path}")
    module = importlib.util.module_from_spec(spec)
    parent = str(path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(parent)
    return module


def validate_stage_output(session_dir: Path, stage: int) -> list[str]:
    output_path = session_dir / STAGE_OUTPUTS[stage]
    if not output_path.is_file():
        return [f"Stage {stage} 输出不存在: {output_path.name}"]
    try:
        if stage == 1:
            module = load_module("flow_intent_validator", SKILLS_ROOT / "resource-intent/scripts/validate_output.py")
            return module.validate(load_object(output_path))
        if stage == 2:
            module = load_module("flow_search_validator", SKILLS_ROOT / "resource-search/scripts/validate_output.py")
            return module.validate(
                load_object(output_path),
                load_object(SKILLS_ROOT / "resource-search/config/platform-catalog.json"),
                load_object(session_dir / STAGE_OUTPUTS[1]),
            )
        if stage == 3:
            module = load_module("flow_platform_validator", SKILLS_ROOT / "resource-platforms/scripts/run_search_plan.py")
            return module.validate_output(load_object(output_path), load_object(session_dir / STAGE_OUTPUTS[2]))
        if stage == 4:
            review_module = load_module("flow_review_validator", SKILLS_ROOT / "resource-selector/scripts/validate_review.py")
            selection_module = load_module("flow_selection_validator", SKILLS_ROOT / "resource-selector/scripts/finalize_selection.py")
            selector_input = load_object(session_dir / "selector_input.json")
            review = load_object(session_dir / "selector_review.json")
            errors = review_module.validate(selector_input, review)
            return errors + selection_module.validate_selection(load_object(output_path), review)
        if stage == 5:
            module = load_module("flow_download_validator", SKILLS_ROOT / "resource-downloader/scripts/validate_output.py")
            return module.validate(
                session_dir,
                load_object(session_dir / STAGE_OUTPUTS[4]),
                load_object(session_dir / STAGE_OUTPUTS[3]),
                load_object(output_path),
            )
        module = load_module("flow_archive_validator", SKILLS_ROOT / "library-manager/scripts/validate_output.py")
        return module.validate(load_object(session_dir / STAGE_OUTPUTS[5]), load_object(output_path))
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        return [str(exc)]


def new_manifest(session_dir: Path, created_at: str | None = None) -> dict[str, Any]:
    timestamp = created_at or now_iso()
    return {
        "schema_version": "session-manifest/v1",
        "session_id": session_dir.name,
        "created_at": timestamp,
        "updated_at": timestamp,
        "status": "in_progress",
        "current_stage": 1,
        "stages": {
            f"stage{stage}": {"status": "pending", "output": output}
            for stage, output in STAGE_OUTPUTS.items()
        },
    }


def validate_manifest(session_dir: Path, manifest: dict[str, Any], check_outputs: bool = False) -> list[str]:
    errors: list[str] = []
    extra_root = set(manifest) - ROOT_FIELDS
    if extra_root:
        errors.append(f"manifest 存在未定义字段: {sorted(extra_root)}")
    if manifest.get("schema_version") != "session-manifest/v1":
        errors.append("manifest.schema_version 必须为 session-manifest/v1")
    if manifest.get("session_id") != session_dir.name:
        errors.append("manifest.session_id 必须与会话目录名一致")
    for field in ("created_at", "updated_at"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            errors.append(f"manifest.{field} 必须是非空字符串")
    status = manifest.get("status")
    if status not in SESSION_STATUSES:
        errors.append("manifest.status 非法")
    current_stage = manifest.get("current_stage")
    if not isinstance(current_stage, int) or isinstance(current_stage, bool) or current_stage not in STAGE_OUTPUTS:
        errors.append("manifest.current_stage 必须是 1-6")

    stages = manifest.get("stages")
    expected_keys = {f"stage{stage}" for stage in STAGE_OUTPUTS}
    if not isinstance(stages, dict) or set(stages) != expected_keys:
        return errors + ["manifest.stages 必须完整包含 stage1-stage6"]

    seen_unfinished = False
    for stage, output in STAGE_OUTPUTS.items():
        name = f"stage{stage}"
        item = stages.get(name)
        if not isinstance(item, dict):
            errors.append(f"manifest.stages.{name} 必须是 object")
            continue
        extra_stage = set(item) - STAGE_FIELDS
        if extra_stage:
            errors.append(f"manifest.stages.{name} 存在未定义字段: {sorted(extra_stage)}")
        stage_status = item.get("status")
        if stage_status not in STAGE_STATUSES:
            errors.append(f"manifest.stages.{name}.status 非法")
        if item.get("output") != output:
            errors.append(f"manifest.stages.{name}.output 必须为 {output}")
        if stage_status == "completed":
            if seen_unfinished:
                errors.append(f"{name} 不能在上游阶段未完成时标记 completed")
            if check_outputs:
                errors.extend(f"{name}: {error}" for error in validate_stage_output(session_dir, stage))
        else:
            seen_unfinished = True

    current_item = stages.get(f"stage{current_stage}", {}) if isinstance(current_stage, int) else {}
    current_status = current_item.get("status") if isinstance(current_item, dict) else None
    if status == "completed" and any(item.get("status") != "completed" for item in stages.values() if isinstance(item, dict)):
        errors.append("会话 completed 时所有阶段都必须 completed")
    if status == "waiting_user" and current_status != "waiting_user":
        errors.append("会话 waiting_user 时当前阶段也必须 waiting_user")
    if status == "failed" and current_status != "failed":
        errors.append("会话 failed 时当前阶段也必须 failed")
    if status == "cancelled" and current_status != "cancelled":
        errors.append("会话 cancelled 时当前阶段也必须 cancelled")
    if status == "in_progress" and current_status not in {"pending", "in_progress"}:
        errors.append("会话 in_progress 时当前阶段必须为 pending 或 in_progress")
    return errors


def ensure_current_manifest(session_dir: Path) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    manifest = load_object(session_dir / "manifest.json")
    errors = validate_manifest(session_dir, manifest)
    if errors:
        raise ValueError("; ".join(errors))
    return manifest


def save_manifest(session_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_iso()
    errors = validate_manifest(session_dir, manifest)
    if errors:
        raise ValueError("; ".join(errors))
    atomic_write(session_dir / "manifest.json", manifest)


def next_action(manifest: dict[str, Any]) -> str:
    status = manifest.get("status")
    if status == "completed":
        return "done"
    if status == "waiting_user":
        return "handle_user_input"
    if status == "failed":
        return "resolve_failure"
    if status == "cancelled":
        return "none"
    return NEXT_ACTIONS[int(manifest["current_stage"])]


def transition(session_dir: Path, action: str, stage: int, reason: str | None, error_code: str | None) -> dict[str, Any]:
    manifest = ensure_current_manifest(session_dir)
    stages = manifest["stages"]
    item = stages[f"stage{stage}"]
    if action == "start":
        if any(stages[f"stage{upstream}"]["status"] != "completed" for upstream in range(1, stage)):
            raise ValueError(f"Stage {stage} 的上游阶段尚未全部完成")
        if item["status"] not in {"pending", "failed", "waiting_user"}:
            raise ValueError(f"Stage {stage} 当前状态不能 start: {item['status']}")
        item.clear()
        item.update({"status": "in_progress", "output": STAGE_OUTPUTS[stage], "started_at": now_iso()})
        manifest["status"] = "in_progress"
    elif action == "complete":
        validation_errors = validate_stage_output(session_dir, stage)
        if validation_errors:
            raise ValueError("; ".join(validation_errors))
        item.clear()
        item.update({"status": "completed", "output": STAGE_OUTPUTS[stage], "completed_at": now_iso()})
        if stage == 6:
            manifest["status"] = "completed"
            manifest["completed_at"] = now_iso()
        else:
            manifest["status"] = "in_progress"
            manifest["current_stage"] = stage + 1
    elif action == "wait":
        item.update({"status": "waiting_user", "waiting_for": reason or "user_input"})
        manifest["status"] = "waiting_user"
    elif action == "fail":
        error = {
            "error_code": error_code or "STAGE_FAILED",
            "message": reason or f"Stage {stage} 执行失败",
            "retryable": False,
        }
        item.update({"status": "failed", "error": error})
        manifest["status"] = "failed"
        manifest["error"] = error
    elif action == "cancel":
        item.update({"status": "cancelled"})
        manifest["status"] = "cancelled"
        manifest["cancelled_at"] = now_iso()
    manifest["current_stage"] = stage if action != "complete" or stage == 6 else stage + 1
    save_manifest(session_dir, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="统一维护 learning-resource-flow 会话状态")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("session_dir", type=Path)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("session_dir", type=Path)
    for command in ("start", "complete", "wait", "fail", "cancel"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("session_dir", type=Path)
        command_parser.add_argument("stage", type=int, choices=range(1, 7))
        if command in {"wait", "fail"}:
            command_parser.add_argument("--reason")
        if command == "fail":
            command_parser.add_argument("--error-code")
    args = parser.parse_args()
    try:
        session_dir = args.session_dir.resolve()
        if args.command == "create":
            session_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = session_dir / "manifest.json"
            if manifest_path.exists():
                raise ValueError("manifest.json 已存在")
            manifest = new_manifest(session_dir)
            atomic_write(manifest_path, manifest)
        elif args.command == "inspect":
            manifest = ensure_current_manifest(session_dir)
            errors = validate_manifest(session_dir, manifest, check_outputs=True)
            if errors:
                raise ValueError("; ".join(errors))
        else:
            manifest = transition(
                session_dir,
                args.command,
                args.stage,
                getattr(args, "reason", None),
                getattr(args, "error_code", None),
            )
        print(json.dumps({
            "ok": True,
            "session_id": manifest["session_id"],
            "status": manifest["status"],
            "current_stage": manifest["current_stage"],
            "stage_status": manifest["stages"][f"stage{manifest['current_stage']}"]["status"],
            "next_action": next_action(manifest),
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
