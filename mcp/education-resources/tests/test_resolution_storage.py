from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.storage import Store


class ResolutionStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self._temporary_directory.name) / "resolution.sqlite"
        self.store = Store(self.database)
        self._flow_sequence = 0
        self.flow_id = self._create_flow("主流程")
        result_set = self._create_result_set(
            self.flow_id,
            [
                self._resource("res_a", "资源 A"),
                self._resource("res_b", "资源 B"),
            ],
        )
        self.result_set_id = result_set["result_set_id"]

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _create_flow(self, topic: str) -> str:
        self._flow_sequence += 1
        result = self.store.create_flow(
            {"goal": {"topic": topic}},
            idempotency_key=f"flow-start-{self._flow_sequence}",
            request_hash=f"flow-hash-{self._flow_sequence}",
        )
        return result["flow_id"]

    @staticmethod
    def _resource(resource_id: str, title: str) -> dict[str, object]:
        return {
            "resource_id": resource_id,
            "platform": "generic",
            "title": title,
            "source_url": f"https://example.com/{resource_id}",
            "resource_type": "document",
            "summary": f"{title}摘要",
            "metadata": {"author": "测试作者", "language": "zh-CN"},
        }

    def _create_result_set(
        self, flow_id: str, resources: list[dict[str, object]], *, suffix: str = "main"
    ) -> dict[str, object]:
        return self.store.create_result_set(
            flow_id,
            resources,
            query="儿童资源",
            task_version=1,
            filters={"language": "zh-CN"},
            failures=[],
            idempotency_key=f"search-{flow_id}-{suffix}",
            request_hash=f"search-hash-{flow_id}-{suffix}",
        )

    def _save(
        self,
        *,
        flow_id: str | None = None,
        resource_id: str = "res_a",
        profile_version: str = "inspect-v1",
        source_fingerprint: str = "fingerprint-a",
        resolution_status: str = "resolved",
        idempotency_key: str = "inspect-a",
        request_hash: str | None = "request-a",
        resolved: object | None = None,
        inspection: object | None = None,
        failures: object | None = None,
    ) -> dict[str, object]:
        return self.store.save_resolution(
            flow_id or self.flow_id,
            resource_id,
            profile_version,
            source_fingerprint,
            resolution_status,
            resolved={"title": "解析后的资源"} if resolved is None else resolved,
            inspection={"inspector_id": "test"} if inspection is None else inspection,
            failures=[] if failures is None else failures,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    def _resolution_rows(self) -> list[sqlite3.Row]:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM resource_resolutions ORDER BY resolution_id"
            ).fetchall()

    def test_save_resolution_is_atomic_with_audit_and_inspect_idempotency(self) -> None:
        before_result_set = copy.deepcopy(self.store.get_result_set(self.result_set_id))
        before_resources = copy.deepcopy(
            self.store.get_resources(self.flow_id, ["res_a", "res_b"])
        )
        before_flow = copy.deepcopy(self.store.get_flow(self.flow_id))

        result = self._save(
            resolved={"title": "原子结果"},
            inspection={"method": "bounded_get"},
            failures=[],
        )

        self.assertTrue(str(result["resolution_id"]).startswith("resolve_"))
        self.assertEqual(before_result_set, self.store.get_result_set(self.result_set_id))
        self.assertEqual(
            before_resources,
            self.store.get_resources(self.flow_id, ["res_a", "res_b"]),
        )
        self.assertEqual(before_flow, self.store.get_flow(self.flow_id))

        with closing(sqlite3.connect(self.database)) as connection:
            audit = connection.execute(
                """
                SELECT flow_id, action, object_id, details_json
                FROM audit_events
                WHERE flow_id = ? AND action = 'resource.inspect'
                """,
                (self.flow_id,),
            ).fetchall()
            idempotency = connection.execute(
                """
                SELECT scope, key, request_hash, result_id, result_json
                FROM idempotency_keys
                WHERE scope = ? AND key = ?
                """,
                (f"resource_inspect:{self.flow_id}", "inspect-a"),
            ).fetchone()

        self.assertEqual(1, len(audit))
        self.assertEqual(self.flow_id, audit[0][0])
        self.assertEqual("resource.inspect", audit[0][1])
        self.assertEqual(result["resolution_id"], audit[0][2])
        self.assertEqual("res_a", json.loads(audit[0][3])["resource_id"])
        self.assertIsNotNone(idempotency)
        assert idempotency is not None
        self.assertEqual(f"resource_inspect:{self.flow_id}", idempotency[0])
        self.assertEqual("inspect-a", idempotency[1])
        self.assertEqual("request-a", idempotency[2])
        self.assertEqual(result["resolution_id"], idempotency[3])
        self.assertEqual(result, json.loads(idempotency[4]))

    def test_same_idempotency_key_replays_and_different_hash_conflicts(self) -> None:
        first = self._save(
            idempotency_key="same-key",
            request_hash="same-hash",
            resolved={"title": "第一次"},
        )
        replay = self._save(
            idempotency_key="same-key",
            request_hash="same-hash",
            resolved={"title": "第一次"},
        )
        self.assertEqual(first, replay)

        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._save(
                idempotency_key="same-key",
                request_hash="different-hash",
                resolved={"title": "不同请求"},
            )

        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT COUNT(*) FROM audit_events WHERE action = 'resource.inspect'"
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*) FROM idempotency_keys
                    WHERE scope = ? AND key = ?
                    """,
                    (f"resource_inspect:{self.flow_id}", "same-key"),
                ).fetchone()[0],
            )

    def test_cacheable_statuses_are_readable_with_a_new_attempt_and_unresolved_is_opt_in(
        self,
    ) -> None:
        resolved = self._save(
            resource_id="res_a",
            source_fingerprint="resolved-fingerprint",
            idempotency_key="resolved-attempt",
            request_hash="resolved-request",
            resolution_status="resolved",
        )
        resolved_cache = self.store.get_cached_resolution(
            self.flow_id,
            "res_a",
            "inspect-v1",
            "resolved-fingerprint",
        )
        self.assertIsNotNone(resolved_cache)
        assert resolved_cache is not None
        self.assertEqual(resolved["resolution_id"], resolved_cache["resolution_id"])
        self.assertTrue(resolved_cache["cacheable"])

        partial = self.store.save_resolution(
            self.flow_id,
            "res_a",
            "inspect-v1",
            "partial-fingerprint",
            "partial",
            resolved={"title": "部分结果"},
            inspection={"method": "metadata_only"},
            failures=[{"code": "PARTIAL_METADATA"}],
            idempotency_key="partial-attempt",
            request_hash="partial-request",
        )
        partial_cache = self.store.get_resource_resolution(
            self.flow_id,
            "res_a",
            "inspect-v1",
            "partial-fingerprint",
        )
        self.assertIsNotNone(partial_cache)
        assert partial_cache is not None
        self.assertEqual(partial["resolution_id"], partial_cache["resolution_id"])
        self.assertEqual("partial", partial_cache["resolution_status"])

        unresolved = self._save(
            resource_id="res_b",
            source_fingerprint="unresolved-fingerprint",
            resolution_status="unresolved",
            idempotency_key="unresolved-attempt",
            request_hash="unresolved-request",
            failures=[{"code": "NETWORK_TIMEOUT"}],
        )
        self.assertIsNone(
            self.store.get_cached_resolution(
                self.flow_id,
                "res_b",
                "inspect-v1",
                "unresolved-fingerprint",
            )
        )
        unresolved_cache = self.store.get_resource_resolution(
            self.flow_id,
            "res_b",
            "inspect-v1",
            "unresolved-fingerprint",
            allow_unresolved=True,
        )
        self.assertIsNotNone(unresolved_cache)
        assert unresolved_cache is not None
        self.assertEqual(unresolved["resolution_id"], unresolved_cache["resolution_id"])
        self.assertFalse(unresolved_cache["cacheable"])

    def test_cross_flow_resolution_read_and_write_are_rejected(self) -> None:
        other_flow_id = self._create_flow("另一个流程")
        self._create_result_set(
            other_flow_id,
            [self._resource("res_other", "另一个资源")],
            suffix="other",
        )

        with self.assertRaisesRegex(PermissionError, "resource_flow_mismatch"):
            self._save(flow_id=other_flow_id, resource_id="res_a")
        with self.assertRaisesRegex(PermissionError, "resource_flow_mismatch"):
            self.store.get_cached_resolution(
                other_flow_id,
                "res_a",
                "inspect-v1",
                "fingerprint-a",
            )
        with self.assertRaisesRegex(PermissionError, "resource_flow_mismatch"):
            self.store.get_resource_resolution(
                other_flow_id,
                "res_a",
                "inspect-v1",
                "fingerprint-a",
                allow_unresolved=True,
            )
        self.assertEqual([], self._resolution_rows())

    def test_current_result_set_recovery_returns_latest_per_resource_and_excludes_unresolved(
        self,
    ) -> None:
        self._save(
            resource_id="res_a",
            resolution_status="resolved",
            idempotency_key="old-attempt",
            request_hash="old-request",
            resolved={"title": "旧结果"},
        )
        time.sleep(0.002)
        latest = self.store.save_resolution(
            self.flow_id,
            "res_a",
            "inspect-v1",
            "new-fingerprint",
            "partial",
            resolved={"title": "最新结果"},
            inspection={"method": "metadata_only"},
            failures=[],
            idempotency_key="new-attempt",
            request_hash="new-request",
        )
        self._save(
            resource_id="res_b",
            resolution_status="unresolved",
            idempotency_key="failed-attempt",
            request_hash="failed-request",
            failures=[{"code": "UNAVAILABLE"}],
        )

        recovered = self.store.list_latest_resolutions(
            self.flow_id, result_set_id=self.result_set_id
        )
        recovered_alias = self.store.list_latest_resolutions_for_flow(self.flow_id)

        self.assertEqual(1, len(recovered))
        self.assertEqual(recovered, recovered_alias)
        self.assertEqual("res_a", recovered[0]["resource_id"])
        self.assertEqual(latest["resolution_id"], recovered[0]["resolution_id"])
        self.assertEqual("partial", recovered[0]["resolution_status"])
        self.assertEqual("最新结果", recovered[0]["resolved"]["title"])

        recovered_with_unresolved = self.store.list_latest_resolutions_for_flow(
            self.flow_id, include_unresolved=True
        )
        self.assertEqual({"res_a", "res_b"}, {item["resource_id"] for item in recovered_with_unresolved})
        self.assertIn(
            "unresolved",
            {item["resolution_status"] for item in recovered_with_unresolved},
        )

    def test_resolution_payload_is_recursively_stripped_before_persistence(self) -> None:
        private_keys = {
            "source_url",
            "url",
            "uri",
            "href",
            "path",
            "file_path",
            "cookie",
            "token",
            "access_token",
            "authorization",
            "credential",
            "password",
            "secret",
        }
        nested_payload: dict[str, object] = {
            key: f"private-{key}" for key in private_keys
        }
        nested_payload["URL"] = "private-uppercase-url"
        nested_payload["safe_nested"] = {"value": "preserve"}
        payload = {
            "safe": "preserve",
            "nested": nested_payload,
            "items": [
                {"href": "private-list-href", "safe_item": True},
                {"deep": {"path": "private-deep-path", "keep": "yes"}},
            ],
        }

        result = self._save(
            resolved=payload,
            inspection={"nested": payload},
            failures=[{"details": payload}],
            idempotency_key="sanitizer-attempt",
            request_hash="sanitizer-request",
        )

        def assert_sanitized(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(str(key).casefold(), private_keys)
                    assert_sanitized(item)
            elif isinstance(value, list):
                for item in value:
                    assert_sanitized(item)

        for value in (
            result["resolved"],
            result["inspection"],
            result["failures"],
        ):
            assert_sanitized(value)
        self.assertEqual("preserve", result["resolved"]["safe"])
        self.assertEqual("preserve", result["resolved"]["nested"]["safe_nested"]["value"])

        with closing(sqlite3.connect(self.database)) as connection:
            row = connection.execute(
                """
                SELECT resolved_json, inspection_json, failures_json
                FROM resource_resolutions WHERE resolution_id = ?
                """,
                (result["resolution_id"],),
            ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        for encoded in row:
            assert_sanitized(json.loads(encoded))

    def test_concurrent_same_key_is_one_atomic_attempt(self) -> None:
        def save_from_worker(_: int) -> dict[str, object]:
            return self._save(
                idempotency_key="concurrent-attempt",
                request_hash="concurrent-request",
                resolved={"title": "并发结果"},
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(save_from_worker, range(8)))

        self.assertEqual(1, len({item["resolution_id"] for item in results}))
        self.assertTrue(all(item == results[0] for item in results))
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*) FROM resource_resolutions
                    WHERE resource_id = 'res_a'
                    """
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*) FROM audit_events
                    WHERE flow_id = ? AND action = 'resource.inspect'
                    """,
                    (self.flow_id,),
                ).fetchone()[0],
            )
            self.assertEqual(
                1,
                connection.execute(
                    """
                    SELECT COUNT(*) FROM idempotency_keys
                    WHERE scope = ? AND key = 'concurrent-attempt'
                    """,
                    (f"resource_inspect:{self.flow_id}",),
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
