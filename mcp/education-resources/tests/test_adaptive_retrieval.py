from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.retrieval.adaptive import (
    AdaptiveModelError,
    Coverage,
    CoverageState,
    SearchDirection,
    SearchRound,
    evaluate_retrieval,
)


FIXTURE = Path(__file__).parent / "fixtures" / "adaptive_retrieval_cases.json"


class AdaptiveRetrievalGoldenTests(unittest.TestCase):
    def test_golden_cases(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 16)
        for case in cases:
            with self.subTest(case=case["name"]):
                evaluation = evaluate_retrieval(case["task"], case["rounds"])
                self.assertEqual(case["expected"], evaluation.stop_decision.value)
                if "expected_unique" in case:
                    self.assertEqual(case["expected_unique"], evaluation.unique_candidates)
                if "expected_duplicates" in case:
                    self.assertEqual(
                        case["expected_duplicates"],
                        evaluation.information_gain.duplicates,
                    )
                if "expected_max_rounds" in case:
                    self.assertEqual(case["expected_max_rounds"], evaluation.max_rounds)

    def test_models_are_bounded_and_defensively_copied(self) -> None:
        facts = {"nested": {"value": 1}}
        search_round = SearchRound.from_mapping(
            {"round": 1, "candidates": [], "facts": facts}
        )
        facts["nested"]["value"] = 2
        self.assertEqual(1, search_round.facts["nested"]["value"])
        with self.assertRaises(AdaptiveModelError):
            SearchDirection(
                direction_id="direction-1",
                purpose="invalid type",
                resource_types=("executable",),
            )
        with self.assertRaises(AdaptiveModelError):
            SearchRound.from_mapping({"round": 5, "candidates": []})

    def test_coverage_rejects_unknown_dimensions_and_states(self) -> None:
        with self.assertRaises(AdaptiveModelError):
            Coverage.from_mapping({"age": "covered"})
        with self.assertRaises(AdaptiveModelError):
            Coverage(target="invented")
        self.assertEqual(
            CoverageState.COVERED,
            Coverage.from_mapping({"target": "covered"}).target,
        )

    def test_output_mapping_is_json_safe_and_fresh(self) -> None:
        evaluation = evaluate_retrieval(
            {"goal": {"topic": "太阳系"}},
            [
                {
                    "round": 1,
                    "candidates": [
                        {
                            "title": "太阳系图解",
                            "platform": "generic",
                            "resource_type": "article",
                            "source_url": "https://example.test/solar-system",
                        }
                    ],
                }
            ],
        )
        first = evaluation.to_mapping()
        first["coverage"]["target"] = "mutated"
        second = evaluation.to_mapping()
        self.assertEqual("covered", second["coverage"]["target"])
        json.dumps(second, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
