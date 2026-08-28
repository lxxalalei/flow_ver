#!/usr/bin/env python3
"""Run real multi-turn OpenClaw user journeys and save raw evidence.

Unlike the semantic baseline runner, this harness does not synthesize assistant
context into one prompt. Every journey reuses one real OpenClaw session id and
sends user turns sequentially so selection, URLs, jobs and tool behavior must
survive through the actual conversation state.
"""

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


ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = re.compile(r"<([A-Z0-9_]+)>")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def invocation_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


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


def substitute(text: str, fixtures: dict[str, str]) -> tuple[str, list[str]]:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = str(fixtures.get(key) or "").strip()
        if not value:
            missing.add(key)
            return match.group(0)
        return value

    return PLACEHOLDER.sub(replace, text), sorted(missing)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        type=Path,
        default=ROOT / "skills" / "examples" / "real-user-journeys.json",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=ROOT,
        help="Git worktree whose installed Skill/MCP behavior is under test.",
    )
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--label", default="journey")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--openclaw", default="openclaw")
    parser.add_argument("--model")
    parser.add_argument("--thinking")
    parser.add_argument("--expect-head")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def run_turn(
    *,
    prompt: str,
    turn_index: int,
    journey_dir: Path,
    session_id: str,
    workspace: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    turn_dir = journey_dir / f"turn-{turn_index:02d}"
    turn_dir.mkdir(parents=True, exist_ok=True)
    request = turn_dir / "request.txt"
    request.write_text(prompt + "\n", encoding="utf-8")

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
        "turn": turn_index,
        "session_id": session_id,
        "command": command,
        "started_at": now(),
    }
    if args.dry_run:
        record["status"] = "dry_run"
        write_json(turn_dir / "meta.json", record)
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

    (turn_dir / "stdout.json").write_text(str(stdout), encoding="utf-8")
    (turn_dir / "stderr.txt").write_text(str(stderr), encoding="utf-8")
    record.update(
        elapsed_ms=int((time.monotonic() - started) * 1000),
        finished_at=now(),
    )
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        summary = {
            key: payload[key]
            for key in (
                "ok",
                "status",
                "model",
                "provider",
                "usage",
                "costUsd",
                "toolSummary",
                "sessionId",
            )
            if key in payload
        }
        result_payload = payload.get("result")
        meta = (
            result_payload.get("meta")
            if isinstance(result_payload, dict)
            else payload.get("meta")
        )
        agent_meta = meta.get("agentMeta") if isinstance(meta, dict) else None
        if isinstance(agent_meta, dict):
            for key in ("model", "provider", "usage", "costUsd", "sessionId"):
                if key not in summary and key in agent_meta:
                    summary[key] = agent_meta[key]
        if isinstance(meta, dict) and "toolSummary" not in summary and "toolSummary" in meta:
            summary["toolSummary"] = meta["toolSummary"]
        record["openclaw"] = summary
    write_json(turn_dir / "meta.json", record)
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
    invocation = invocation_id()
    output_root = (
        ROOT
        / ".openclaw-test"
        / "real-user-journeys"
        / f"{args.label}-{invocation}"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "suite_version": suite.get("version"),
        "workspace": str(workspace),
        "workspace_head": head,
        "label": args.label,
        "invocation_id": invocation,
        "started_at": now(),
        "journeys": [],
        "skipped": [],
    }

    for journey in suite.get("journeys") or []:
        if not isinstance(journey, dict) or not journey.get("id"):
            continue
        journey_id = str(journey["id"])
        if selected and journey_id not in selected:
            continue

        raw_turns = journey.get("turns") or []
        if not raw_turns or not all(isinstance(turn, str) and turn.strip() for turn in raw_turns):
            manifest["skipped"].append(
                {"journey_id": journey_id, "reason": "journey needs non-empty string turns"}
            )
            continue

        prepared: list[str] = []
        missing: set[str] = set()
        for raw in raw_turns:
            prompt, absent = substitute(raw.strip(), fixtures)
            prepared.append(prompt)
            missing.update(absent)
        if missing:
            manifest["skipped"].append(
                {
                    "journey_id": journey_id,
                    "reason": "missing fixtures: " + ", ".join(sorted(missing)),
                }
            )
            continue

        for run_index in range(1, args.repeat + 1):
            session_id = (
                f"journey-{args.label}-{invocation}-{journey_id}-r{run_index:02d}"
            )
            journey_dir = output_root / journey_id / f"run-{run_index:02d}"
            journey_dir.mkdir(parents=True, exist_ok=True)
            journey_record: dict[str, Any] = {
                "journey_id": journey_id,
                "run_index": run_index,
                "session_id": session_id,
                "acceptance": journey.get("acceptance") or [],
                "forbidden": journey.get("forbidden") or [],
                "started_at": now(),
                "turns": [],
            }
            for turn_index, prompt in enumerate(prepared, start=1):
                turn_record = run_turn(
                    prompt=prompt,
                    turn_index=turn_index,
                    journey_dir=journey_dir,
                    session_id=session_id,
                    workspace=workspace,
                    args=args,
                )
                journey_record["turns"].append(turn_record)
                if not args.dry_run and (
                    turn_record.get("status") != "completed"
                    or turn_record.get("returncode") != 0
                ):
                    journey_record["stopped_after_turn"] = turn_index
                    break
            journey_record["finished_at"] = now()
            write_json(journey_dir / "journey.json", journey_record)
            manifest["journeys"].append(journey_record)

    manifest["finished_at"] = now()
    write_json(output_root / "manifest.json", manifest)
    print(output_root / "manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
