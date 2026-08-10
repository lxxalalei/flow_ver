#!/usr/bin/env python3
"""Run the deterministic adaptive retrieval calibration fixture.

The command is intentionally offline: it only loads JSON fixtures and invokes
``retrieval.adaptive``.  It never calls adapters, MCP tools, or the network.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
FIXTURE = SERVICE_ROOT / "tests" / "fixtures" / "adaptive_retrieval_cases.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.retrieval.adaptive import (  # noqa: E402
    AdaptiveModelError,
    evaluate_retrieval,
)


def load_cases(path: Path = FIXTURE) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("calibration fixture must be a JSON array")
    return value


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    name = str(case.get("name") or "unnamed")
    expected_error = case.get("expected_error")
    try:
        evaluation = evaluate_retrieval(case.get("task"), case.get("rounds"))
    except AdaptiveModelError as exc:
        passed = expected_error is not None and str(expected_error).casefold() in str(exc).casefold()
        return {
            "name": name,
            "passed": passed,
            "expected_error": expected_error,
            "error": str(exc),
        }
    except Exception as exc:  # calibration should expose unexpected implementation errors
        return {"name": name, "passed": False, "error_type": type(exc).__name__, "error": str(exc)}

    mismatches: list[str] = []
    expected = case.get("expected")
    if expected is not None and evaluation.stop_decision.value != expected:
        mismatches.append(f"decision expected {expected!r}, got {evaluation.stop_decision.value!r}")
    for key, actual in (
        ("expected_unique", evaluation.unique_candidate_count),
        ("expected_max_rounds", evaluation.max_rounds),
        ("expected_no_gain_streak", evaluation.no_gain_streak),
    ):
        if key in case and case[key] != actual:
            mismatches.append(f"{key} expected {case[key]!r}, got {actual!r}")
    for key, actual in (
        ("expected_displayable", list(evaluation.displayable_resource_ids)),
        ("expected_inspect", list(evaluation.inspect_resource_ids)),
        ("expected_clarify", list(evaluation.clarify_fields)),
    ):
        if key in case and list(case[key]) != actual:
            mismatches.append(f"{key} expected {case[key]!r}, got {actual!r}")
    if "expected_gap_contains" in case:
        actual_gaps = {item.gap_id for item in evaluation.gaps}
        missing = sorted(set(case["expected_gap_contains"]) - actual_gaps)
        if missing:
            mismatches.append(f"expected_gap_contains missing {missing!r}; got {sorted(actual_gaps)!r}")
    if "expected_gap_causes" in case:
        actual_gap_causes = {item.gap_id: item.cause_code for item in evaluation.gaps}
        for gap_id, expected_cause in case["expected_gap_causes"].items():
            actual_cause = actual_gap_causes.get(gap_id)
            if actual_cause != expected_cause:
                mismatches.append(
                    f"gap {gap_id!r} cause expected {expected_cause!r}, got {actual_cause!r}"
                )
    return {
        "name": name,
        "passed": not mismatches,
        "expected": expected,
        "actual": evaluation.stop_decision.value,
        "reason_code": evaluation.reason_code,
        "gaps": [item.gap_id for item in evaluation.gaps],
        "gap_causes": {item.gap_id: item.cause_code for item in evaluation.gaps if item.cause_code is not None},
        "displayable_resource_ids": list(evaluation.displayable_resource_ids),
        "inspect_resource_ids": list(evaluation.inspect_resource_ids),
        "clarify_fields": list(evaluation.clarify_fields),
        "unique_candidate_count": evaluation.unique_candidate_count,
        "mismatches": mismatches,
    }


def run_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [evaluate_case(case) for case in cases]
    failed = [item for item in results if not item["passed"]]
    return {
        "fixture_cases": len(cases),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    summary = run_cases(load_cases(args.fixture))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"calibration cases={summary['fixture_cases']} passed={summary['passed']} failed={summary['failed']}")
        for result in summary["results"]:
            if not result["passed"]:
                print(f"FAIL {result['name']}: {result.get('mismatches') or result.get('error')}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
