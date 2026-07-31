#!/usr/bin/env python3
"""Remove stale stage artifacts before intentionally rerunning a pipeline stage."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from session_state import STAGE_OUTPUTS, ensure_current_manifest, save_manifest


STAGE_ARTIFACTS: dict[int, tuple[str, ...]] = {
    1: ("stage1_intent.json",),
    2: ("stage2_search_plan.json",),
    3: ("stage3_search_results.json",),
    4: ("selector_input.json", "selector_worker_reviews", "selector_review.json", "stage4_selection.json"),
    5: ("download_plan.json", "stage5_download.json", "downloads"),
    6: ("archive_plan.json", "stage6_archive.json"),
}


def artifact_names(from_stage: int) -> list[str]:
    return [
        name
        for stage in range(from_stage, 7)
        for name in STAGE_ARTIFACTS[stage]
    ]


def reset(session_dir: Path, from_stage: int, dry_run: bool = False) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    manifest = ensure_current_manifest(session_dir)
    session_id = manifest.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("manifest.session_id 必须是非空字符串")
    if session_dir.name != session_id:
        raise ValueError("manifest.session_id 必须与会话目录名一致")

    names = artifact_names(from_stage)
    existing = [name for name in names if (session_dir / name).exists() or (session_dir / name).is_symlink()]
    if dry_run:
        return {"from_stage": from_stage, "would_remove": existing, "reset_stages": list(range(from_stage, 7))}

    for name in existing:
        path = session_dir / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)

    stages = manifest["stages"]
    for stage in range(from_stage, 7):
        stages[f"stage{stage}"] = {
            "status": "pending",
            "output": STAGE_OUTPUTS[stage],
        }
    manifest["status"] = "in_progress"
    manifest["current_stage"] = from_stage
    for field in ("error", "completed_at", "cancelled_at", "cancelled_stage"):
        manifest.pop(field, None)
    save_manifest(session_dir, manifest)
    return {"from_stage": from_stage, "removed": existing, "reset_stages": list(range(from_stage, 7))}


def main() -> int:
    parser = argparse.ArgumentParser(description="清理当前阶段及下游旧输出，准备重新执行")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("from_stage", type=int, choices=range(1, 7))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = reset(args.session_dir, args.from_stage, args.dry_run)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
