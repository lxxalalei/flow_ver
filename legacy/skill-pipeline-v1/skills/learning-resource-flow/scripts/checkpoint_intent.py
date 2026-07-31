#!/usr/bin/env python3
"""Persist one live Intent turn before waiting without restarting Stage 1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import session_state
import validate_request


def message(role: str, content: str) -> dict[str, str]:
    value = content.strip()
    if not value:
        raise ValueError(f"{role} content 必须是非空字符串")
    return {"role": role, "content": value}


def append_with_overlap(existing: list[dict[str, Any]], additions: list[dict[str, str]]) -> int:
    """Append additions idempotently, preserving the longest existing suffix."""
    overlap = 0
    maximum = min(len(existing), len(additions))
    for size in range(maximum, 0, -1):
        if existing[-size:] == additions[:size]:
            overlap = size
            break
    existing.extend(additions[overlap:])
    return len(additions) - overlap


def checkpoint(
    session_dir: Path,
    assistant_question: str | None = None,
    user_answer: str | None = None,
    reason: str = "user_input",
) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    manifest = session_state.ensure_current_manifest(session_dir)
    if manifest.get("current_stage") != 1:
        raise ValueError(f"当前不是 Stage 1: {manifest.get('current_stage')}")
    stage1 = manifest.get("stages", {}).get("stage1", {})
    if not isinstance(stage1, dict) or stage1.get("status") not in {"in_progress", "waiting_user"}:
        raise ValueError("Stage 1 当前不处于可澄清状态")

    request_path = session_dir / "request.json"
    document = validate_request.load_json(request_path)
    errors = validate_request.validate(document, request_path)
    if errors:
        raise ValueError("; ".join(errors))

    additions: list[dict[str, str]] = []
    if user_answer is not None:
        additions.append(message("user", user_answer))
    if assistant_question is not None:
        additions.append(message("assistant", assistant_question))
    if not additions:
        raise ValueError("必须提供 user_answer 或 assistant_question")

    evidence = document["data"]["conversation_evidence"]
    appended_count = append_with_overlap(evidence, additions)
    errors = validate_request.validate(document, request_path)
    if errors:
        raise ValueError("; ".join(errors))
    session_state.atomic_write(request_path, document)

    if assistant_question is not None:
        manifest = session_state.transition(session_dir, "wait", 1, reason, None)
    else:
        manifest = session_state.transition(session_dir, "continue", 1, None, None)
    return {
        "ok": True,
        "session_id": manifest["session_id"],
        "status": manifest["status"],
        "stage_status": manifest["stages"]["stage1"]["status"],
        "next_action": session_state.next_action(manifest, session_dir),
        "appended_evidence_count": appended_count,
        "waiting_for_user": assistant_question is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="保存当前 Intent 增量证据；有助手问题时进入等待，不重新初始化 Stage 1"
    )
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--assistant-question")
    parser.add_argument("--user-answer")
    parser.add_argument("--reason", default="user_input")
    args = parser.parse_args()
    try:
        result = checkpoint(
            args.session_dir,
            assistant_question=args.assistant_question,
            user_answer=args.user_answer,
            reason=args.reason,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
