from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resource_intent_validate_output",
    SKILL_DIR / "scripts" / "validate_output.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate = MODULE.validate


def ready_document() -> dict:
    return {
        "_meta": {
            "schema_version": "intent-spec/v1",
            "session_id": "session-1",
            "created_at": "2026-07-12T12:00:00+08:00",
        },
        "_summary": {"status": "ready"},
        "data": {
            "status": "ready",
            "raw_request": "帮我找些古诗学习资料",
            "slots": {
                "core_topic": {
                    "value": "古诗文学习",
                    "status": "explicit",
                    "evidence": ["帮我找些古诗学习资料"],
                },
                "learning_goal": {
                    "value": "课内同步",
                    "status": "explicit",
                    "evidence": ["课内同步"],
                },
                "grade_level": {
                    "value": "五年级",
                    "status": "explicit",
                    "evidence": ["五年级"],
                },
            },
            "constraints": {},
            "search_concepts": {
                "canonical_terms": ["五年级古诗文", "课内同步"],
                "related_terms": ["古诗讲解", "古诗赏析"],
            },
        },
    }


class ValidateIntentV1Test(unittest.TestCase):
    def test_accepts_completed_ready_intent(self) -> None:
        self.assertEqual(validate(ready_document()), [])

    def test_accepts_legacy_clarification_artifact(self) -> None:
        document = ready_document()
        document["_summary"] = {
            "status": "needs_clarification",
            "question": "孩子现在读几年级？",
        }
        document["data"] = {
            "status": "needs_clarification",
            "raw_request": "帮我找些古诗学习资料",
            "clarification": {
                "question": "孩子现在读几年级？",
                "reason": "课内篇目随年级变化",
            },
        }

        self.assertEqual(validate(document), [])

    def test_requires_evidence_for_incrementally_confirmed_slots(self) -> None:
        document = ready_document()
        document["data"]["slots"]["grade_level"]["evidence"] = []

        errors = validate(document)

        self.assertIn("slots.grade_level 标为 explicit 时必须提供 evidence", errors)

    def test_output_schema_preserves_v1_legacy_shape(self) -> None:
        schema = json.loads(
            (SKILL_DIR / "schemas" / "output.schema.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            schema["properties"]["_summary"]["properties"]["status"]["enum"],
            ["ready", "needs_clarification"],
        )
        self.assertEqual(
            schema["properties"]["data"]["properties"]["status"]["enum"],
            ["ready", "needs_clarification"],
        )
        self.assertIn("clarification", schema["properties"]["data"]["properties"])


if __name__ == "__main__":
    unittest.main()
