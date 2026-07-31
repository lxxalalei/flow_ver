from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import reset_from_stage
import session_state


def ready_intent(session_id: str) -> dict[str, object]:
    return {
        "_meta": {
            "schema_version": "intent-spec/v1",
            "session_id": session_id,
            "created_at": "2026-07-12T12:00:00+08:00",
        },
        "_summary": {"status": "ready"},
        "data": {
            "status": "ready",
            "raw_request": "帮我找些古诗学习资料",
            "slots": {
                "core_topic": {
                    "value": "古诗学习",
                    "status": "explicit",
                    "evidence": ["帮我找些古诗学习资料"],
                }
            },
            "constraints": {},
            "search_concepts": {"canonical_terms": ["古诗学习"]},
        },
    }


def clarification_intent(session_id: str) -> dict[str, object]:
    question = "更偏课内同步、朗读背诵还是启蒙欣赏？"
    return {
        "_meta": {
            "schema_version": "intent-spec/v1",
            "session_id": session_id,
            "created_at": "2026-07-12T12:00:00+08:00",
        },
        "_summary": {"status": "needs_clarification", "question": question},
        "data": {
            "status": "needs_clarification",
            "raw_request": "帮我找些古诗学习资料",
            "clarification": {
                "question": question,
                "reason": "学习路线会改变搜索方向",
            },
        },
    }


class SessionStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.temporary_directory.name) / "test-session"
        self.session_dir.mkdir()
        session_state.atomic_write(
            self.session_dir / "manifest.json",
            session_state.new_manifest(self.session_dir, "2026-07-12T10:00:00+08:00"),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_intent(self, document: dict[str, object]) -> None:
        (self.session_dir / "stage1_intent.json").write_text(
            json.dumps(document, ensure_ascii=False),
            encoding="utf-8",
        )

    def start_stage1(self) -> dict[str, object]:
        return session_state.transition(self.session_dir, "start", 1, None, None)

    def test_stage1_wait_keeps_intent_active_without_formal_output(self) -> None:
        started = self.start_stage1()
        started_at = started["stages"]["stage1"]["started_at"]

        waiting = session_state.transition(self.session_dir, "wait", 1, "user_input", None)

        self.assertEqual("waiting_user", waiting["status"])
        self.assertEqual("in_progress", waiting["stages"]["stage1"]["status"])
        self.assertEqual(started_at, waiting["stages"]["stage1"]["started_at"])
        self.assertEqual("user_input", waiting["stages"]["stage1"]["waiting_for"])
        self.assertEqual(
            "continue_resource_intent_after_user_input",
            session_state.next_action(waiting),
        )
        self.assertFalse((self.session_dir / "stage1_intent.json").exists())
        self.assertEqual([], session_state.validate_manifest(self.session_dir, waiting, check_outputs=True))

    def test_repeated_clarification_then_complete_needs_no_restart(self) -> None:
        first_started_at = self.start_stage1()["stages"]["stage1"]["started_at"]
        session_state.transition(self.session_dir, "wait", 1, "first_answer", None)
        second_wait = session_state.transition(self.session_dir, "wait", 1, "second_answer", None)
        self.assertEqual(first_started_at, second_wait["stages"]["stage1"]["started_at"])

        self.write_intent(ready_intent(self.session_dir.name))
        completed = session_state.transition(self.session_dir, "complete", 1, None, None)

        self.assertEqual("completed", completed["stages"]["stage1"]["status"])
        self.assertEqual(2, completed["current_stage"])
        self.assertEqual("in_progress", completed["status"])
        self.assertEqual("pending", completed["stages"]["stage2"]["status"])
        self.assertEqual([], session_state.validate_manifest(self.session_dir, completed, check_outputs=True))

    def test_continue_stage1_clears_wait_without_restarting(self) -> None:
        started_at = self.start_stage1()["stages"]["stage1"]["started_at"]
        session_state.transition(self.session_dir, "wait", 1, "user_input", None)

        continued = session_state.transition(self.session_dir, "continue", 1, None, None)

        self.assertEqual("in_progress", continued["status"])
        self.assertEqual("in_progress", continued["stages"]["stage1"]["status"])
        self.assertEqual(started_at, continued["stages"]["stage1"]["started_at"])
        self.assertNotIn("waiting_for", continued["stages"]["stage1"])
        self.assertEqual("run_resource_intent", session_state.next_action(continued, self.session_dir))

    def test_complete_stage1_rejects_clarification_document(self) -> None:
        self.start_stage1()
        self.write_intent(clarification_intent(self.session_dir.name))

        with self.assertRaisesRegex(ValueError, "ready"):
            session_state.transition(self.session_dir, "complete", 1, None, None)

        manifest = session_state.ensure_current_manifest(self.session_dir)
        self.assertEqual("in_progress", manifest["stages"]["stage1"]["status"])

    def test_wait_discards_legacy_clarification_document(self) -> None:
        self.start_stage1()
        self.write_intent(clarification_intent(self.session_dir.name))

        waiting = session_state.transition(self.session_dir, "wait", 1, "user_input", None)

        self.assertFalse((self.session_dir / "stage1_intent.json").exists())
        self.assertEqual("in_progress", waiting["stages"]["stage1"]["status"])

    def test_inspect_rejects_new_active_stage_with_provisional_output(self) -> None:
        manifest = self.start_stage1()
        self.write_intent(clarification_intent(self.session_dir.name))

        errors = session_state.validate_manifest(self.session_dir, manifest, check_outputs=True)

        self.assertTrue(any("needs_clarification" in error for error in errors), errors)

    def test_legacy_waiting_manifest_can_be_resumed_without_losing_started_at(self) -> None:
        manifest = self.start_stage1()
        started_at = manifest["stages"]["stage1"]["started_at"]
        manifest["status"] = "waiting_user"
        manifest["stages"]["stage1"]["status"] = "waiting_user"
        manifest["stages"]["stage1"]["waiting_for"] = "user_input"
        session_state.atomic_write(self.session_dir / "manifest.json", manifest)
        self.write_intent(clarification_intent(self.session_dir.name))

        self.assertEqual([], session_state.validate_manifest(self.session_dir, manifest, check_outputs=True))
        resumed = session_state.transition(self.session_dir, "start", 1, None, None)

        self.assertEqual("in_progress", resumed["status"])
        self.assertEqual("in_progress", resumed["stages"]["stage1"]["status"])
        self.assertEqual(started_at, resumed["stages"]["stage1"]["started_at"])
        self.assertNotIn("waiting_for", resumed["stages"]["stage1"])
        self.assertFalse((self.session_dir / "stage1_intent.json").exists())

    def test_legacy_waiting_manifest_with_ready_output_requests_completion(self) -> None:
        manifest = self.start_stage1()
        manifest["status"] = "waiting_user"
        manifest["stages"]["stage1"]["status"] = "waiting_user"
        manifest["stages"]["stage1"]["waiting_for"] = "user_input"
        session_state.atomic_write(self.session_dir / "manifest.json", manifest)
        self.write_intent(ready_intent(self.session_dir.name))

        self.assertEqual([], session_state.validate_manifest(self.session_dir, manifest, check_outputs=True))
        self.assertEqual(
            "complete_resource_intent",
            session_state.next_action(manifest, self.session_dir),
        )

    def test_reset_stage1_works_while_clarification_is_active(self) -> None:
        self.start_stage1()
        session_state.transition(self.session_dir, "wait", 1, "user_input", None)

        result = reset_from_stage.reset(self.session_dir, 1)
        manifest = session_state.ensure_current_manifest(self.session_dir)

        self.assertEqual(list(range(1, 7)), result["reset_stages"])
        self.assertEqual("in_progress", manifest["status"])
        self.assertEqual(1, manifest["current_stage"])
        self.assertEqual("pending", manifest["stages"]["stage1"]["status"])

    def test_completed_stage1_is_revalidated_during_inspection(self) -> None:
        self.start_stage1()
        self.write_intent(ready_intent(self.session_dir.name))
        completed = session_state.transition(self.session_dir, "complete", 1, None, None)
        self.write_intent(clarification_intent(self.session_dir.name))

        errors = session_state.validate_manifest(self.session_dir, completed, check_outputs=True)

        self.assertTrue(any("ready" in error for error in errors), errors)

    def test_non_intent_waiting_stage_keeps_legacy_waiting_status(self) -> None:
        manifest = session_state.ensure_current_manifest(self.session_dir)
        manifest["stages"]["stage1"]["status"] = "completed"
        manifest["stages"]["stage2"]["status"] = "completed"
        manifest["current_stage"] = 3
        session_state.save_manifest(self.session_dir, manifest)

        session_state.transition(self.session_dir, "start", 3, None, None)
        waiting = session_state.transition(self.session_dir, "wait", 3, "credentials", None)

        self.assertEqual("waiting_user", waiting["status"])
        self.assertEqual("waiting_user", waiting["stages"]["stage3"]["status"])
        self.assertEqual("handle_user_input", session_state.next_action(waiting))


if __name__ == "__main__":
    unittest.main()
