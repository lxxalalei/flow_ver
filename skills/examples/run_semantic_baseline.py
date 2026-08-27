#!/usr/bin/env python3
"""Run 0074 semantic baseline cases with OpenClaw and save raw evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTO_MODES = {"real", "judgment", "fixture_required"}
PLACEHOLDER = re.compile(r"<([A-Z0-9_]+)>")
ROOT = Path(__file__).resolve().parents[2]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_head(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def case_prompt(case: dict[str, Any], fixtures: dict[str, str]) -> str:
    messages = [
        str(item.get("content") or "").strip()
        for item in case.get("messages") or []
        if isinstance(item, dict) and item.get("role") == "user"
    ]
    if len(messages) != 1 or not messages[0]:
        raise ValueError("automated case must contain exactly one non-empty user message")

    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = str(fixtures.get(key) or "").strip()
        if not value:
            missing.add(key)
            return match.group(0)
        return value

    prompt = PLACEHOLDER.sub(replace, messages[0])
    if missing:
        raise ValueError("missing fixtures: " + ", ".join(sorted(missing)))
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        type=Path,
        default=ROOT / "skills" / "examples" / "semantic-baseline-cases.json",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=ROOT,
        help="Git worktree whose skills/ directory is under test.",
    )
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--model")
    parser.add_argument("--thinking")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--openclaw", default="openclaw")
    parser.add_argument("--expect-head")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--cli",
        choices=("exec", "direct"),
        default="exec",
        help=(
            "exec: 'openclaw agent exec' with --cwd/--state-dir (newer CLI). "
            "direct: 'openclaw agent' with --session-id isolation "
            "(OpenClaw 2026.7.x has no exec subcommand and rejects unknown options)."
        ),
    )
    return parser.parse_args()


def run_case(
    case: dict[str, Any],
    prompt: str,
    run_index: int,
    workspace: Path,
    output_root: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    run_dir = output_root / str(case["id"]) / f"run-{run_index:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    request = run_dir / "request.txt"
    request.write_text(prompt + "\n", encoding="utf-8")

    session_id = f"semantic-{args.label}-{case['id']}-r{run_index:02d}"
    if args.cli == "exec":
        state_dir = run_dir / "state"
        state_dir.mkdir(exist_ok=True)
        command = [
            args.openclaw,
            "agent",
            "exec",
            "--message-file",
            str(request),
            "--cwd",
            str(workspace),
            "--state-dir",
            str(state_dir),
            "--timeout",
            str(args.timeout),
            "--json",
        ]
    else:
        command = [
            args.openclaw,
            "agent",
            "--message-file",
            str(request),
            "--session-id",
            session_id,
            "--timeout",
            str(args.timeout),
            "--json",
        ]
    if args.model:
        command += ["--model", args.model]
    if args.thinking:
        command += ["--thinking", args.thinking]

    record: dict[str, Any] = {
        "case_id": case["id"],
        "run_index": run_index,
        "cli": args.cli,
        "session_id": session_id,
        "command": command,
        "started_at": now(),
    }
    if args.dry_run:
        record["status"] = "dry_run"
        return record

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=None if args.timeout == 0 else args.timeout + 120,
        )
        stdout, stderr = result.stdout, result.stderr
        record.update(status="completed", returncode=result.returncode)
    except FileNotFoundError as exc:
        stdout, stderr = "", str(exc)
        record.update(status="openclaw_not_found", returncode=None)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        record.update(status="harness_timeout", returncode=None)

    (run_dir / "stdout.json").write_text(str(stdout), encoding="utf-8")
    (run_dir / "stderr.txt").write_text(str(stderr), encoding="utf-8")
    record.update(elapsed_ms=int((time.monotonic() - started) * 1000), finished_at=now())
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        summary = {
            key: payload[key]
            for key in ("ok", "status", "model", "provider", "usage", "costUsd", "toolSummary", "sessionId")
            if key in payload
        }
        # OpenClaw 2026.7.x `agent --json` nests run metadata under result.meta.agentMeta;
        # gateway-fallback envelopes put payloads/meta at the top level instead.
        result = payload.get("result")
        meta = result.get("meta") if isinstance(result, dict) else payload.get("meta")
        agent_meta = meta.get("agentMeta") if isinstance(meta, dict) else None
        if isinstance(agent_meta, dict):
            for key in ("model", "provider", "usage", "costUsd", "sessionId"):
                if key not in summary and key in agent_meta:
                    summary[key] = agent_meta[key]
        if isinstance(meta, dict) and "toolSummary" not in summary and "toolSummary" in meta:
            summary["toolSummary"] = meta["toolSummary"]
        record["openclaw"] = summary
    write_json(run_dir / "meta.json", record)
    return record


def main() -> int:
    args = parse_args()
    if args.repeat < 1 or args.timeout < 0:
        raise SystemExit("--repeat must be >= 1 and --timeout must be >= 0")

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")

    suite = read_json(args.suite)
    fixtures = read_json(args.fixtures) if args.fixtures else {}
    if not isinstance(fixtures, dict):
        raise SystemExit("fixtures must be one JSON object")

    head = git_head(workspace)
    if args.expect_head and head != args.expect_head:
        raise SystemExit(f"HEAD mismatch: expected {args.expect_head}, got {head}")

    selected = set(args.case_ids or [])
    output_root = ROOT / ".openclaw-test" / "semantic-baseline" / args.label
    output_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "suite_version": suite.get("version"),
        "suite_baseline_commit": suite.get("baseline_commit"),
        "workspace": str(workspace),
        "workspace_head": head,
        "label": args.label,
        "cli": args.cli,
        "started_at": now(),
        "runs": [],
        "skipped": [],
    }

    for case in suite.get("cases") or []:
        if not isinstance(case, dict) or not case.get("id"):
            continue
        case_id = str(case["id"])
        if selected and case_id not in selected:
            continue
        mode = str(case.get("execution_mode") or "")
        if mode not in AUTO_MODES:
            manifest["skipped"].append({"case_id": case_id, "reason": f"manual mode: {mode}"})
            continue
        try:
            prompt = case_prompt(case, fixtures)
        except ValueError as exc:
            manifest["skipped"].append({"case_id": case_id, "reason": str(exc)})
            continue
        for index in range(1, args.repeat + 1):
            manifest["runs"].append(
                run_case(case, prompt, index, workspace, output_root, args)
            )

    manifest["finished_at"] = now()
    write_json(output_root / "manifest.json", manifest)
    print(output_root / "manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
