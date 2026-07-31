from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import checkpoint_intent
import session_state


class CheckpointIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.temporary_directory.name) / "checkpoint-session"
        self.session_dir.mkdir()
        session_state.atomic_write(
            self.session_dir / "manifest.json",
            session_state.new_manifest(self.session_dir, "2026-07-12T10:00:00+08:00"),
        )
        session_state.atomic_write(
            self.session_dir / "request.json",
            {
                "_meta": {
                    "schema_version": "request/v1",
                    "session_id": self.session_dir.name,
                    "created_at": "2026-07-12T10:00:00+08:00",
                },
                "data": {
                    "raw_request": "帮我找些古诗学习资料",
                    "conversation_evidence": [],
                },
            },
        )
        session_state.transition(self.session_dir, "start", 1, None, None)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def evidence(self) -> list[dict[str, str]]:
        return json.loads((self.session_dir / "request.json").read_text(encoding="utf-8"))["data"][
            "conversation_evidence"
        ]

    def test_initial_question_is_checkpointed_before_wait(self) -> None:
        result = checkpoint_intent.checkpoint(
            self.session_dir,
            assistant_question="更偏课内同步、朗读背诵还是启蒙欣赏？",
        )

        self.assertEqual("waiting_user", result["status"])
        self.assertEqual("in_progress", result["stage_status"])
        self.assertEqual(1, result["appended_evidence_count"])
        self.assertEqual(
            [{"role": "assistant", "content": "更偏课内同步、朗读背诵还是启蒙欣赏？"}],
            self.evidence(),
        )

    def test_followup_answer_and_question_are_saved_as_one_turn(self) -> None:
        checkpoint_intent.checkpoint(
            self.session_dir,
            assistant_question="更偏课内同步、朗读背诵还是启蒙欣赏？",
        )
        result = checkpoint_intent.checkpoint(
            self.session_dir,
            user_answer="课内同步",
            assistant_question="孩子现在读几年级？",
        )

        self.assertEqual(2, result["appended_evidence_count"])
        self.assertEqual(
            [
                {"role": "assistant", "content": "更偏课内同步、朗读背诵还是启蒙欣赏？"},
                {"role": "user", "content": "课内同步"},
                {"role": "assistant", "content": "孩子现在读几年级？"},
            ],
            self.evidence(),
        )

    def test_retry_is_idempotent(self) -> None:
        checkpoint_intent.checkpoint(
            self.session_dir,
            user_answer="课内同步",
            assistant_question="孩子现在读几年级？",
        )
        result = checkpoint_intent.checkpoint(
            self.session_dir,
            user_answer="课内同步",
            assistant_question="孩子现在读几年级？",
        )

        self.assertEqual(0, result["appended_evidence_count"])
        self.assertEqual(2, len(self.evidence()))

    def test_final_answer_can_be_checkpointed_without_starting_another_wait(self) -> None:
        checkpoint_intent.checkpoint(
            self.session_dir,
            assistant_question="孩子现在读几年级？",
        )
        result = checkpoint_intent.checkpoint(
            self.session_dir,
            user_answer="五年级",
        )

        self.assertFalse(result["waiting_for_user"])
        self.assertEqual("in_progress", result["status"])
        self.assertEqual("in_progress", result["stage_status"])
        self.assertEqual("run_resource_intent", result["next_action"])
        manifest = session_state.ensure_current_manifest(self.session_dir)
        self.assertNotIn("waiting_for", manifest["stages"]["stage1"])
        self.assertEqual(
            [
                {"role": "assistant", "content": "孩子现在读几年级？"},
                {"role": "user", "content": "五年级"},
            ],
            self.evidence(),
        )


if __name__ == "__main__":
    unittest.main()
