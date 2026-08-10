from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.retrieval.adaptive import (  # noqa: E402
    AdaptiveModelError,
    AdaptiveRetrievalEvaluator,
    CandidateFact,
    FactualCoverageSummary,
    Gap,
    GapSeverity,
    InformationGain,
    RetrievalRound,
    SemanticReview,
    StopDecision,
    _failure_decision,
    evaluate_retrieval,
)


FIXTURE = Path(__file__).parent / "fixtures" / "adaptive_retrieval_cases.json"


class AdaptiveRetrievalGoldenTests(unittest.TestCase):
    def test_golden_cases_cover_decision_focused_calibration(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 24)
        self.assertLessEqual(len(cases), 40)
        for case in cases:
            with self.subTest(case=case["name"]):
                if "expected_error" in case:
                    with self.assertRaisesRegex(AdaptiveModelError, case["expected_error"]):
                        evaluate_retrieval(case["task"], case["rounds"])
                    continue
                evaluation = evaluate_retrieval(case["task"], case["rounds"])
                self.assertEqual(case["expected"], evaluation.stop_decision.value)
                if "expected_unique" in case:
                    self.assertEqual(case["expected_unique"], evaluation.unique_candidate_count)
                if "expected_max_rounds" in case:
                    self.assertEqual(case["expected_max_rounds"], evaluation.max_rounds)
                if "expected_displayable" in case:
                    self.assertEqual(tuple(case["expected_displayable"]), evaluation.displayable_resource_ids)
                if "expected_inspect" in case:
                    self.assertEqual(tuple(case["expected_inspect"]), evaluation.inspect_resource_ids)
                if "expected_clarify" in case:
                    self.assertEqual(tuple(case["expected_clarify"]), evaluation.clarify_fields)
                if "expected_no_gain_streak" in case:
                    self.assertEqual(case["expected_no_gain_streak"], evaluation.no_gain_streak)
                if "expected_gap_contains" in case:
                    actual_gaps = {item.gap_id for item in evaluation.gaps}
                    self.assertTrue(
                        set(case["expected_gap_contains"]).issubset(actual_gaps),
                        (case["name"], actual_gaps),
                    )
                if "expected_gap_causes" in case:
                    actual_causes = {item.gap_id: item.cause_code for item in evaluation.gaps if item.cause_code is not None}
                    self.assertEqual(case["expected_gap_causes"], {key: actual_causes.get(key) for key in case["expected_gap_causes"]})


class AdaptiveRetrievalModelTests(unittest.TestCase):
    def test_facts_and_reviews_are_defensively_copied(self) -> None:
        factual = {"status": "covered", "gaps": [{"dimension": "inspection", "count": 1}]}
        summary = FactualCoverageSummary.from_mapping(factual)
        factual["gaps"][0]["count"] = 99
        self.assertEqual(1, summary.gaps[0]["count"])

        candidate_raw = {
            "resource_id": "r-copy",
            "displayable": True,
            "availability": "available",
            "resource_type": "article",
            "facts": {"title": "太阳系"},
        }
        candidate = CandidateFact.from_mapping(candidate_raw)
        candidate_raw["facts"]["title"] = "mutated"
        self.assertEqual("太阳系", candidate.facts["title"])

    def test_missing_machine_facts_never_become_pass(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": "太阳系"},
            {
                "round": 1,
                "candidates": [
                    {"resource_id": "r-title", "facts": {"title": "太阳系图解"}},
                ],
                "semantic_reviews": [
                    {
                        "resource_id": "r-title",
                        "relevance": "pass",
                        "usefulness": "pass",
                        "target_fit": "unknown",
                        "constraint_fit": "unknown",
                        "substantive": "pass",
                        "evidence_level": "search_only",
                    }
                ],
            },
        )
        self.assertNotEqual(StopDecision.PRESENT, evaluation.stop_decision)
        self.assertEqual(("r-title",), evaluation.inspect_resource_ids)

    def test_missing_semantic_review_never_becomes_pass(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": "太阳系"},
            {
                "round": 1,
                "candidates": [
                    {
                        "resource_id": "r-fact-only",
                        "displayable": True,
                        "availability": "available",
                        "resource_type": "article",
                        "source_family": "generic",
                    }
                ],
            },
        )
        self.assertEqual(StopDecision.REPLAN, evaluation.stop_decision)
        self.assertTrue(any(item.dimension == "semantic" for item in evaluation.gaps))

    def test_explicit_machine_and_semantic_evidence_can_present(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": "太阳系"},
            {
                "round": 1,
                "factual_coverage": {"status": "covered", "candidate_count": 1, "platform_count": 1},
                "candidates": [
                    {
                        "resource_id": "r-pass",
                        "displayable": True,
                        "availability": "available",
                        "resource_type": "article",
                        "source_family": "generic",
                    }
                ],
                "semantic_reviews": [
                    {
                        "resource_id": "r-pass",
                        "relevance": "pass",
                        "usefulness": "pass",
                        "target_fit": "unknown",
                        "constraint_fit": "unknown",
                        "substantive": "pass",
                        "evidence_level": "search_only",
                    }
                ],
                "information_gain": {"new_unique_candidates": 1},
            },
        )
        self.assertEqual(StopDecision.PRESENT, evaluation.stop_decision)
        self.assertEqual(("r-pass",), evaluation.displayable_resource_ids)
        self.assertEqual(2, evaluation.budget_remaining)

    def test_review_id_must_match_server_candidate_fact(self) -> None:
        with self.assertRaisesRegex(AdaptiveModelError, "semantic review"):
            RetrievalRound.from_mapping(
                {
                    "round": 1,
                    "candidates": [
                        {
                            "resource_id": "r-real",
                            "displayable": True,
                            "availability": "available",
                            "resource_type": "article",
                        }
                    ],
                    "semantic_reviews": [
                        {
                            "resource_id": "r-forged",
                            "relevance": "pass",
                            "usefulness": "pass",
                            "target_fit": "unknown",
                            "constraint_fit": "unknown",
                            "substantive": "pass",
                            "evidence_level": "search_only",
                        }
                    ],
                }
            )

    def test_bounds_and_enums_are_checked(self) -> None:
        with self.assertRaises(AdaptiveModelError):
            CandidateFact.from_mapping({"resource_id": "r-bad", "availability": "invented"})
        with self.assertRaises(AdaptiveModelError):
            InformationGain(new_unique_candidates=-1)
        with self.assertRaises(AdaptiveModelError):
            RetrievalRound.from_mapping({"round": 5, "candidates": []})

    def test_output_mapping_is_json_safe_and_fresh(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": "太阳系"},
            {
                "round": 1,
                "candidates": [
                    {
                        "resource_id": "r-json",
                        "displayable": True,
                        "availability": "available",
                        "resource_type": "article",
                        "source_family": "generic",
                    }
                ],
                "semantic_reviews": [
                    {
                        "resource_id": "r-json",
                        "relevance": "pass",
                        "usefulness": "pass",
                        "target_fit": "unknown",
                        "constraint_fit": "unknown",
                        "substantive": "pass",
                        "evidence_level": "search_only",
                    }
                ],
            },
        )
        first = evaluation.to_mapping()
        first["factual_coverage"]["status"] = "mutated"
        first["displayable_resource_ids"].clear()
        second = evaluation.to_mapping()
        self.assertEqual("unknown", second["factual_coverage"]["status"])
        self.assertEqual(["r-json"], second["displayable_resource_ids"])
        json.dumps(second, ensure_ascii=False)

    def test_stateful_facade_requires_sequential_bounded_rounds(self) -> None:
        evaluator = AdaptiveRetrievalEvaluator({"goal": "太阳系"})
        result = evaluator.add_round(
            {
                "round": 1,
                "information_gain": {"new_unique_candidates": 0},
            }
        )
        self.assertEqual(StopDecision.REPLAN, result.stop_decision)
        with self.assertRaises(AdaptiveModelError):
            evaluator.add_round({"round": 3})

    def test_missing_gain_is_unknown_and_does_not_count_as_zero(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": "冷门主题"},
            [
                {"round": 1, "factual_coverage": {"status": "empty"}},
                {"round": 2, "factual_coverage": {"status": "empty"}},
            ],
        )
        self.assertEqual(StopDecision.REPLAN, evaluation.stop_decision)
        self.assertEqual(0, evaluation.no_gain_streak)
        self.assertFalse(evaluation.information_gain.observed)

    def test_explicit_zero_gain_counts_and_unknown_breaks_streak(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": "冷门主题", "max_rounds": 4},
            [
                {"round": 1, "information_gain": {"observed": True}},
                {"round": 2},
                {"round": 3, "information_gain": {"observed": True}},
            ],
        )
        self.assertEqual(StopDecision.REPLAN, evaluation.stop_decision)
        self.assertEqual(1, evaluation.no_gain_streak)
        self.assertTrue(evaluation.information_gain.observed)

    def test_gap_cause_code_round_trips_as_structured_data(self) -> None:
        mapping = {
            "gap_id": "availability:r-auth",
            "dimension": "availability",
            "severity": "critical",
            "reason": "文案可独立调整",
            "action": "clarify",
            "resource_ids": ["r-auth"],
            "cause_code": "AUTH_REQUIRED",
        }
        gap = Gap.from_mapping(mapping)
        self.assertEqual(mapping, gap.to_mapping())

    def test_gap_cause_code_requires_uppercase_stable_format(self) -> None:
        base = {
            "gap_id": "source-failure",
            "dimension": "source",
            "severity": GapSeverity.CRITICAL.value,
            "reason": "来源失败",
            "action": "stop_with_gap",
        }
        for cause_code in ("auth_required", "AUTH REQUIRED", "", "-AUTH"):
            with self.subTest(cause_code=cause_code):
                if cause_code == "":
                    # Empty string is intentionally treated as absent.
                    self.assertIsNone(Gap.from_mapping({**base, "cause_code": cause_code}).cause_code)
                else:
                    with self.assertRaisesRegex(AdaptiveModelError, "uppercase stable cause code"):
                        Gap.from_mapping({**base, "cause_code": cause_code})

    def test_failure_decision_uses_cause_code_not_reason_text(self) -> None:
        blocked = Gap(
            gap_id="policy-blocked",
            dimension="source",
            severity=GapSeverity.CRITICAL,
            reason="任意的人类可读说明",
            action="stop_with_gap",
            cause_code="POLICY",
        )
        renamed = Gap(
            gap_id="policy-blocked-renamed",
            dimension="source",
            severity=GapSeverity.CRITICAL,
            reason="requires_auth 字样也不应改变政策阻断决策",
            action="stop_with_gap",
            cause_code="POLICY",
        )
        self.assertEqual(_failure_decision([blocked]), StopDecision.STOP_WITH_GAP)
        self.assertEqual(_failure_decision([renamed]), StopDecision.STOP_WITH_GAP)

    def test_failure_reason_text_without_cause_code_is_not_decisive(self) -> None:
        text_only = Gap(
            gap_id="text-only-failure",
            dimension="source",
            severity=GapSeverity.CRITICAL,
            reason="source requires_auth but no structured cause was reported",
            action="clarify",
        )
        self.assertIsNone(_failure_decision([text_only]))


    def test_latest_explicit_displayable_false_supersedes_true(self) -> None:
        base = {
            "goal": "太阳系入门",
        }
        common_review = {
            "resource_id": "r-latest-displayable",
            "relevance": "pass",
            "usefulness": "pass",
            "target_fit": "unknown",
            "constraint_fit": "unknown",
            "substantive": "pass",
            "evidence_level": "search_only",
        }
        unknown_followup = evaluate_retrieval(
            base,
            [
                {
                    "round": 1,
                    "candidates": [{"resource_id": "r-latest-displayable", "displayable": True, "availability": "available", "resource_type": "article"}],
                    "semantic_reviews": [common_review],
                },
                {
                    "round": 2,
                    "candidates": [{"resource_id": "r-latest-displayable", "availability": "available"}],
                },
            ],
        )
        self.assertEqual(StopDecision.PRESENT, unknown_followup.stop_decision)
        explicit_false = evaluate_retrieval(
            base,
            [
                {
                    "round": 1,
                    "candidates": [{"resource_id": "r-latest-displayable", "displayable": True, "availability": "available", "resource_type": "article"}],
                    "semantic_reviews": [common_review],
                },
                {
                    "round": 2,
                    "candidates": [{"resource_id": "r-latest-displayable", "displayable": False}],
                },
            ],
        )
        self.assertEqual(StopDecision.REPLAN, explicit_false.stop_decision)
        self.assertEqual((), explicit_false.displayable_resource_ids)


if __name__ == "__main__":
    unittest.main()
