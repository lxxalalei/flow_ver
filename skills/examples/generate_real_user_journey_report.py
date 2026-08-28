#!/usr/bin/env python3
"""Generate a deterministic Markdown summary from real user journey evidence.

The report deliberately separates machine-verifiable execution facts from
semantic acceptance. It never declares a journey PASS solely from its own
heuristics; completed journeys remain REVIEW until a human inspects the real
conversation/tool evidence against the recorded acceptance/forbidden criteria.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


TOOL_NAME = re.compile(r"\b(?:resource_[a-z_]+|web_search)\b")
URL = re.compile(r"https?://[^\s\"'<>\]\)]+")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def fmt_ms(value: int) -> str:
    if value < 1000:
        return f"{value} ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    return f"{seconds / 60:.1f} min"


def turn_stdout(run_root: Path, journey_id: str, run_index: int, turn_index: int) -> str:
    path = (
        run_root
        / journey_id
        / f"run-{run_index:02d}"
        / f"turn-{turn_index:02d}"
        / "stdout.json"
    )
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def extract_tools(text: str, turn: dict[str, Any]) -> list[str]:
    tools = set(TOOL_NAME.findall(text))
    openclaw = turn.get("openclaw")
    if isinstance(openclaw, dict):
        summary = openclaw.get("toolSummary")
        if summary is not None:
            tools.update(TOOL_NAME.findall(json.dumps(summary, ensure_ascii=False)))
    return sorted(tools)


def extract_urls(text: str) -> list[str]:
    return sorted(set(URL.findall(text)))


def technical_status(journey: dict[str, Any]) -> str:
    turns = journey.get("turns") or []
    if not turns:
        return "NO_RUN"
    if all(turn.get("status") == "dry_run" for turn in turns):
        return "DRY_RUN"
    if journey.get("stopped_after_turn"):
        return "HARNESS_FAIL"
    for turn in turns:
        if turn.get("status") != "completed" or turn.get("returncode") != 0:
            return "HARNESS_FAIL"
    planned = journey.get("planned_turns")
    if isinstance(planned, int) and planned != len(turns):
        return "HARNESS_FAIL"
    session_ids = {str(turn.get("session_id") or "") for turn in turns}
    session_ids.discard("")
    if len(session_ids) != 1:
        return "SESSION_BROKEN"
    return "EXECUTED"


def journey_observation(run_root: Path, journey: dict[str, Any]) -> dict[str, Any]:
    journey_id = str(journey.get("journey_id") or "unknown")
    run_index = int(journey.get("run_index") or 0)
    tools: Counter[str] = Counter()
    urls: set[str] = set()
    elapsed_ms = 0
    models: set[str] = set()
    providers: set[str] = set()
    session_ids: set[str] = set()
    errors: list[str] = []

    for turn in journey.get("turns") or []:
        turn_index = int(turn.get("turn") or 0)
        text = turn_stdout(run_root, journey_id, run_index, turn_index)
        tools.update(extract_tools(text, turn))
        urls.update(extract_urls(text))
        elapsed_ms += int(turn.get("elapsed_ms") or 0)
        session_id = str(turn.get("session_id") or "").strip()
        if session_id:
            session_ids.add(session_id)
        openclaw = turn.get("openclaw")
        if isinstance(openclaw, dict):
            model = str(openclaw.get("model") or "").strip()
            provider = str(openclaw.get("provider") or "").strip()
            if model:
                models.add(model)
            if provider:
                providers.add(provider)
        if turn.get("status") not in {"completed", "dry_run"}:
            errors.append(f"turn {turn_index}: {turn.get('status')}")
        elif turn.get("returncode") not in {None, 0}:
            errors.append(f"turn {turn_index}: exit {turn.get('returncode')}")

    status = technical_status(journey)
    semantic = "N/A" if status in {"HARNESS_FAIL", "SESSION_BROKEN", "NO_RUN"} else "REVIEW"
    return {
        "journey_id": journey_id,
        "run_index": run_index,
        "technical_status": status,
        "semantic_status": semantic,
        "turns": len(journey.get("turns") or []),
        "planned_turns": journey.get("planned_turns"),
        "tools": tools,
        "urls": sorted(urls),
        "elapsed_ms": elapsed_ms,
        "models": sorted(models),
        "providers": sorted(providers),
        "session_ids": sorted(session_ids),
        "errors": errors,
        "acceptance": journey.get("acceptance") or [],
        "forbidden": journey.get("forbidden") or [],
    }


def generate_report(run_root: Path, output: Path | None = None) -> Path:
    run_root = run_root.resolve()
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    observations = [
        journey_observation(run_root, journey)
        for journey in manifest.get("journeys") or []
        if isinstance(journey, dict)
    ]

    total_tools: Counter[str] = Counter()
    for item in observations:
        total_tools.update(item["tools"])

    executed = sum(item["technical_status"] == "EXECUTED" for item in observations)
    dry_runs = sum(item["technical_status"] == "DRY_RUN" for item in observations)
    technical_failures = sum(
        item["technical_status"] in {"HARNESS_FAIL", "SESSION_BROKEN", "NO_RUN"}
        for item in observations
    )
    review_pending = sum(item["semantic_status"] == "REVIEW" for item in observations)

    lines: list[str] = []
    lines.append("# Real User Journey Test Report")
    lines.append("")
    lines.append("> This report summarizes machine-verifiable execution facts. `REVIEW` is intentional: semantic acceptance must be checked against the real conversation and tool evidence; the harness does not grade itself.")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for key in (
        "suite_version",
        "workspace_head",
        "label",
        "invocation_id",
        "started_at",
        "finished_at",
    ):
        lines.append(f"| {key} | {md(manifest.get(key))} |")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("| --- | ---: |")
    lines.append(f"| Journey runs | {len(observations)} |")
    lines.append(f"| Technically executed | {executed} |")
    lines.append(f"| Dry runs | {dry_runs} |")
    lines.append(f"| Technical/session failures | {technical_failures} |")
    lines.append(f"| Semantic review pending | {review_pending} |")
    lines.append(f"| Skipped definitions | {len(manifest.get('skipped') or [])} |")
    lines.append("")

    lines.append("## Tool activation observed")
    lines.append("")
    if total_tools:
        lines.append("| Tool | Mentions |")
        lines.append("| --- | ---: |")
        for name, count in sorted(total_tools.items()):
            lines.append(f"| `{name}` | {count} |")
    else:
        lines.append("No tool names were recoverable from the recorded OpenClaw JSON output.")
    lines.append("")

    lines.append("## Journey overview")
    lines.append("")
    lines.append("| Journey | Run | Technical | Semantic | Turns | Tools | URLs | Duration |")
    lines.append("| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |")
    for item in observations:
        lines.append(
            "| {journey} | {run} | {technical} | {semantic} | {turns} | {tools} | {urls} | {duration} |".format(
                journey=md(item["journey_id"]),
                run=item["run_index"],
                technical=item["technical_status"],
                semantic=item["semantic_status"],
                turns=item["turns"],
                tools=sum(item["tools"].values()),
                urls=len(item["urls"]),
                duration=fmt_ms(item["elapsed_ms"]),
            )
        )
    lines.append("")

    if manifest.get("skipped"):
        lines.append("## Skipped")
        lines.append("")
        for item in manifest["skipped"]:
            lines.append(f"- `{md(item.get('journey_id'))}`: {md(item.get('reason'))}")
        lines.append("")

    lines.append("## Detailed review")
    lines.append("")
    for item in observations:
        evidence = f"{item['journey_id']}/run-{item['run_index']:02d}/"
        lines.append(f"### {item['journey_id']} / run-{item['run_index']:02d}")
        lines.append("")
        lines.append(f"- Technical status: **{item['technical_status']}**")
        lines.append(f"- Semantic status: **{item['semantic_status']}**")
        planned = item["planned_turns"]
        lines.append(
            f"- Turns: {item['turns']}"
            + (f" / planned {planned}" if isinstance(planned, int) else "")
        )
        lines.append(
            "- Session continuity: "
            + ("stable" if len(item["session_ids"]) == 1 else f"broken/unknown ({len(item['session_ids'])} ids)")
        )
        lines.append(f"- Duration: {fmt_ms(item['elapsed_ms'])}")
        lines.append(f"- Models: {', '.join(item['models']) if item['models'] else 'not captured'}")
        lines.append(f"- Providers: {', '.join(item['providers']) if item['providers'] else 'not captured'}")
        if item["tools"]:
            tool_text = ", ".join(f"`{name}` × {count}" for name, count in sorted(item["tools"].items()))
            lines.append(f"- Tool evidence: {tool_text}")
        else:
            lines.append("- Tool evidence: none recovered")
        lines.append(f"- Unique URLs observed: {len(item['urls'])}")
        if item["errors"]:
            lines.append(f"- Execution errors: {'; '.join(item['errors'])}")
        lines.append(f"- Raw evidence: `{evidence}`")
        lines.append("")
        lines.append("Acceptance review:")
        for criterion in item["acceptance"]:
            lines.append(f"- [ ] {criterion}")
        if not item["acceptance"]:
            lines.append("- [ ] No acceptance criteria recorded")
        lines.append("")
        lines.append("Forbidden-behavior review:")
        for criterion in item["forbidden"]:
            lines.append(f"- [ ] Did **not** occur: {criterion}")
        if not item["forbidden"]:
            lines.append("- [ ] No forbidden criteria recorded")
        lines.append("")
        if item["urls"]:
            lines.append("Observed URLs:")
            for url in item["urls"]:
                lines.append(f"- `{url}`")
            lines.append("")

    lines.append("## Interpretation rule")
    lines.append("")
    lines.append("- `EXECUTED` means every recorded turn completed with exit code 0 and retained one session id.")
    lines.append("- `HARNESS_FAIL` / `SESSION_BROKEN` are deterministic technical failures.")
    lines.append("- `REVIEW` is not a pass or fail. A reviewer must inspect the raw turns and mark the acceptance/forbidden checklist.")
    lines.append("- Tool mention counts are diagnostic evidence, not proof that the tool call was semantically correct.")
    lines.append("")

    output = output or (run_root / "real-user-journey-report.md")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path, help="One .openclaw-test/real-user-journeys/<run> directory")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(generate_report(args.run_root, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
