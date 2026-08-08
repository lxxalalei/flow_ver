from __future__ import annotations

from contextlib import closing
import copy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import Store


class ResultSetExtendStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self._temporary_directory.name) / "result_sets.sqlite"
        self.store = Store(self.database)
        flow = self.store.create_flow(
            {"goal": {"topic": "immutable retrieval"}},
            "flow-key-00000001",
            "flow-request-0001",
        )
        self.flow_id = flow["flow_id"]
        self.task_version = flow["task_version"]

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    @staticmethod
    def _resource(
        resource_id: str,
        title: str,
        *,
        identity: dict[str, object] | None = None,
        identity_rules_version: str = "identity-v1",
    ) -> dict[str, object]:
        return {
            "resource_id": resource_id,
            "platform": "generic",
            "title": title,
            "source_url": f"https://example.com/{resource_id}",
            "resource_type": "article",
            "summary": f"{title} summary",
            "metadata": {"language": "zh-CN"},
            "identity": identity or {},
            "identity_rules_version": identity_rules_version,
        }

    def _create_replace(
        self,
        resources: list[dict[str, object]],
        *,
        suffix: str,
        provenance: dict[str, object] | None = None,
        coverage: dict[str, object] | None = None,
        task_version: int | None = None,
    ) -> dict[str, object]:
        return self.store.create_result_set(
            self.flow_id,
            resources,
            query=f"query-{suffix}",
            task_version=self.task_version if task_version is None else task_version,
            filters={"suffix": suffix},
            failures=[],
            platform_runs=[],
            provenance=provenance,
            coverage=coverage,
            idempotency_key=f"search-key-{suffix}-0001",
            request_hash=f"search-request-{suffix}",
        )

    def test_replace_defaults_are_compatible_and_private_identity_is_recovered(self) -> None:
        result = self._create_replace(
            [
                self._resource(
                    "res_replace",
                    "Replace resource",
                    identity={"native_id": "native-replace"},
                    identity_rules_version="identity-v2",
                )
            ],
            suffix="replace",
        )

        self.assertEqual("replace", result["mode"])
        self.assertIsNone(result["base_result_set_id"])
        self.assertEqual(1, result["round"])
        self.assertEqual({}, result["provenance"])
        self.assertEqual({}, result["coverage"])
        self.assertNotIn("identity", result["candidates"][0])
        self.assertNotIn("identity_rules_version", result["candidates"][0])

        recovered = self.store.get_result_set(result["result_set_id"])
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(1, recovered["task_version"])
        self.assertEqual("replace", recovered["mode"])
        self.assertIsNone(recovered["base_result_set_id"])
        self.assertEqual(1, recovered["round"])
        self.assertEqual({}, recovered["provenance"])
        self.assertEqual({}, recovered["coverage"])
        self.assertEqual(
            {"native_id": "native-replace"},
            recovered["resources"][0]["identity"],
        )
        self.assertEqual("identity-v2", recovered["resources"][0]["identity_rules_version"])

    def test_extend_creates_new_snapshot_and_only_supersedes_old_presentation(self) -> None:
        base = self._create_replace(
            [
                self._resource(
                    "res_a",
                    "A",
                    identity={"native_id": "a"},
                )
            ],
            suffix="base",
            provenance={"round": 1, "new_unique": 1},
            coverage={"covered": ["topic-a"]},
        )
        base_before = copy.deepcopy(self.store.get_result_set(base["result_set_id"]))
        base_resource_before = copy.deepcopy(
            self.store.get_resources(self.flow_id, ["res_a"])
        )
        presentation = self.store.create_presentation(
            self.flow_id,
            base["result_set_id"],
            ["res_a"],
            idempotency_key="presentation-key-0001",
            request_hash="presentation-request-0001",
        )
        presentation_before = self.store.get_presentation(presentation["presentation_id"])
        selection = self.store.save_selection(
            self.flow_id,
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
            idempotency_key="selection-key-0001",
            request_hash="selection-request-0001",
        )
        selection_before = self.store.get_selection(self.flow_id)

        extended = self.store.create_result_set(
            self.flow_id,
            [
                self._resource(
                    "res_b",
                    "B",
                    identity={"native_id": "b"},
                )
            ],
            query="query-extend",
            task_version=self.task_version,
            filters={"suffix": "extend"},
            failures=[],
            platform_runs=[{"platform": "generic", "query_runs": []}],
            mode="extend",
            base_result_set_id=base["result_set_id"],
            provenance={"round": 2, "new_unique": 1, "duplicate": 0},
            coverage={"covered": ["topic-a", "topic-b"]},
            idempotency_key="search-key-extend-0001",
            request_hash="search-request-extend",
        )

        self.assertNotEqual(base["result_set_id"], extended["result_set_id"])
        self.assertEqual("extend", extended["mode"])
        self.assertEqual(base["result_set_id"], extended["base_result_set_id"])
        self.assertEqual(2, extended["round"])
        self.assertEqual({"round": 2, "new_unique": 1, "duplicate": 0}, extended["provenance"])
        self.assertEqual({"covered": ["topic-a", "topic-b"]}, extended["coverage"])

        self.assertEqual(base_before, self.store.get_result_set(base["result_set_id"]))
        self.assertEqual(base_resource_before, self.store.get_resources(self.flow_id, ["res_a"]))
        self.assertEqual(
            ["res_b"],
            [item["resource_id"] for item in self.store.get_result_set(extended["result_set_id"])["resources"]],
        )

        presentation_after = self.store.get_presentation(presentation["presentation_id"])
        self.assertIsNotNone(presentation_before)
        self.assertIsNotNone(presentation_after)
        assert presentation_before is not None
        assert presentation_after is not None
        self.assertEqual("active", presentation_before["status"])
        self.assertEqual("superseded", presentation_after["status"])
        self.assertEqual(presentation_before["items"], presentation_after["items"])
        self.assertEqual(selection["selected_resource_ids"], ["res_a"])
        self.assertEqual(selection_before, self.store.get_selection(self.flow_id))

    def test_extend_validates_base_in_final_transaction(self) -> None:
        base = self._create_replace(
            [self._resource("res_base", "Base")],
            suffix="validation-base",
        )
        other_flow = self.store.create_flow(
            {"goal": {"topic": "other"}},
            "flow-key-00000002",
            "flow-request-0002",
        )
        other_result = self.store.create_result_set(
            other_flow["flow_id"],
            [self._resource("res_other", "Other")],
            query="other",
            task_version=other_flow["task_version"],
            filters={},
            failures=[],
            idempotency_key="search-key-other-0001",
            request_hash="search-request-other",
        )

        with self.assertRaisesRegex(ValueError, "base_result_set_required"):
            self.store.create_result_set(
                self.flow_id,
                [],
                query="missing-base",
                task_version=self.task_version,
                filters={},
                failures=[],
                mode="extend",
                idempotency_key="search-key-missing-0001",
                request_hash="search-request-missing",
            )
        with self.assertRaisesRegex(ValueError, "base_result_set_forbidden"):
            self.store.create_result_set(
                self.flow_id,
                [],
                query="replace-with-base",
                task_version=self.task_version,
                filters={},
                failures=[],
                base_result_set_id=base["result_set_id"],
                idempotency_key="search-key-forbidden-0001",
                request_hash="search-request-forbidden",
            )
        with self.assertRaisesRegex(ValueError, "base_result_set_flow_mismatch"):
            self.store.create_result_set(
                self.flow_id,
                [],
                query="cross-flow",
                task_version=self.task_version,
                filters={},
                failures=[],
                mode="extend",
                base_result_set_id=other_result["result_set_id"],
                idempotency_key="search-key-cross-flow-0001",
                request_hash="search-request-cross-flow",
            )

        replacement = self._create_replace(
            [self._resource("res_replacement", "Replacement")],
            suffix="validation-replacement",
        )
        self.assertNotEqual(base["result_set_id"], replacement["result_set_id"])
        with self.assertRaisesRegex(RuntimeError, "base_result_set_stale"):
            self.store.create_result_set(
                self.flow_id,
                [],
                query="stale-base",
                task_version=self.task_version,
                filters={},
                failures=[],
                mode="extend",
                base_result_set_id=base["result_set_id"],
                idempotency_key="search-key-stale-0001",
                request_hash="search-request-stale",
            )

        current = replacement["result_set_id"]
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE search_result_sets SET task_version = 2 WHERE result_set_id = ?",
                (current,),
            )
            connection.commit()
        with self.assertRaisesRegex(RuntimeError, "base_task_version_conflict"):
            self.store.create_result_set(
                self.flow_id,
                [],
                query="base-task-version",
                task_version=self.task_version,
                filters={},
                failures=[],
                mode="extend",
                base_result_set_id=current,
                idempotency_key="search-key-task-version-0001",
                request_hash="search-request-task-version",
            )

    def test_idempotent_extend_replays_before_stale_base_validation(self) -> None:
        base = self._create_replace(
            [self._resource("res_replay_base", "Replay base")],
            suffix="replay-base",
        )
        extend_resource = self._resource("res_replay_extend", "Replay extend")
        first = self.store.create_result_set(
            self.flow_id,
            [extend_resource],
            query="replay-extend",
            task_version=self.task_version,
            filters={},
            failures=[],
            mode="extend",
            base_result_set_id=base["result_set_id"],
            provenance={"round": 2},
            coverage={"covered": ["replay"]},
            idempotency_key="search-key-replay-0001",
            request_hash="search-request-replay",
        )
        replacement = self._create_replace(
            [self._resource("res_replay_replacement", "Replacement")],
            suffix="replay-replacement",
        )

        replay = self.store.create_result_set(
            self.flow_id,
            [extend_resource],
            query="replay-extend",
            task_version=self.task_version,
            filters={},
            failures=[],
            mode="extend",
            base_result_set_id=base["result_set_id"],
            provenance={"round": 2},
            coverage={"covered": ["replay"]},
            idempotency_key="search-key-replay-0001",
            request_hash="search-request-replay",
        )

        self.assertEqual(first, replay)
        self.assertEqual(
            replacement["result_set_id"],
            self.store.get_flow(self.flow_id)["current_result_set_id"],
        )
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM search_result_sets WHERE flow_id = ?",
                (self.flow_id,),
            ).fetchone()[0]
        self.assertEqual(3, count)


if __name__ == "__main__":
    unittest.main()
