from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SEARCH_SCHEMA_PATH = CONTRACTS_ROOT / "schemas" / "tools" / "resource_search.schema.json"
FLOW_STATUS_SCHEMA_PATH = (
    CONTRACTS_ROOT / "schemas" / "tools" / "resource_flow_status.schema.json"
)
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from education_resource_mcp.models import SearchTask
except ImportError as exc:  # pragma: no cover - environment-dependent test setup
    SearchTask = None  # type: ignore[assignment,misc]
    SEARCH_TASK_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    SEARCH_TASK_IMPORT_ERROR = ""


FLOW_ID = "flow_1234567890abcdef"
RESULT_SET_ID = "rset_1234567890abcdef"
SEARCH_RUN_ID = "search_1234567890abcdef"
CREATED_AT = "2026-08-08T00:00:00Z"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry() -> Registry:
    registry = Registry()
    for path in CONTRACTS_ROOT.rglob("*.json"):
        document = load_json(path)
        identifier = document.get("$id")
        if identifier:
            registry = registry.with_resource(
                identifier, Resource.from_contents(document)
            )
    return registry


def validator_for(path: Path, definition: str) -> Draft202012Validator:
    schema = load_json(path)
    validation_schema = {**schema, "$ref": f"#/$defs/{definition}"}
    validation_schema.pop("oneOf", None)
    return Draft202012Validator(
        validation_schema,
        registry=build_registry(),
        format_checker=FormatChecker(),
    )


def legacy_search_input() -> dict:
    return {
        "contract_version": "1.0.0",
        "flow_id": FLOW_ID,
        "task_version": 1,
        "idempotency_key": "adaptive-search-legacy-01",
        "search_tasks": [
            {
                "platform": "generic",
                "queries": [{"query": "儿童科学入门"}],
            }
        ],
    }


def adaptive_success() -> dict:
    return {
        "contract_version": "1.0.0",
        "ok": True,
        "flow_id": FLOW_ID,
        "task_version": 1,
        "search_run_id": SEARCH_RUN_ID,
        "result_set_id": RESULT_SET_ID,
        "result_version": 1,
        "stage": "reviewing",
        "status": "ready",
        "platform_runs": [
            {
                "platform": "generic",
                "direction": "x" * 256,
                "status": "succeeded",
                "query_runs": [
                    {
                        "query": "儿童科学入门",
                        "direction": "x" * 256,
                        "candidate_count": 0,
                        "failure_count": 0,
                        "new_unique_count": 0,
                        "duplicate_count": 0,
                    }
                ],
            }
        ],
        "candidates": [],
        "failures": [],
        "has_more": False,
        "created_at": CREATED_AT,
        "mode": "extend",
        "base_result_set_id": RESULT_SET_ID,
        "round": 1,
        "provenance": {
            "raw_candidate_count": 10000,
            "new_unique_count": 10000,
            "duplicate_count": 10000,
            "duplicate_of_base_count": 10000,
            "duplicate_within_round_count": 10000,
            "identity_unknown_count": 10000,
            "new_displayable_count": 10000,
        },
        "coverage": {
            "kind": "factual",
            "schema_version": "factual-coverage-v1",
            "status": "partial",
            "candidate_count": 0,
            "platform_count": 1,
            "resource_types": [{"resource_type": "article", "count": 0}],
            "gaps": [
                {
                    "dimension": "inspection",
                    "reason": "x" * 256,
                    "count": 0,
                }
            ],
        },
    }


class AdaptiveSearchInputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = validator_for(SEARCH_SCHEMA_PATH, "input")

    def assert_valid(self, instance: dict) -> None:
        errors = list(self.validator.iter_errors(instance))
        self.assertEqual([], [error.message for error in errors])

    def assert_invalid(self, instance: dict) -> None:
        self.assertFalse(self.validator.is_valid(instance), msg="instance unexpectedly valid")

    def test_legacy_request_without_adaptive_fields_remains_valid(self) -> None:
        self.assert_valid(legacy_search_input())

    def test_extend_requires_base_and_replace_forbids_base(self) -> None:
        extend_without_base = legacy_search_input()
        extend_without_base["mode"] = "extend"
        self.assert_invalid(extend_without_base)

        replace_with_base = legacy_search_input()
        replace_with_base["mode"] = "replace"
        replace_with_base["base_result_set_id"] = RESULT_SET_ID
        self.assert_invalid(replace_with_base)

        omitted_mode_with_base = legacy_search_input()
        omitted_mode_with_base["base_result_set_id"] = RESULT_SET_ID
        self.assert_invalid(omitted_mode_with_base)

        extend_with_base = legacy_search_input()
        extend_with_base["mode"] = "extend"
        extend_with_base["base_result_set_id"] = RESULT_SET_ID
        self.assert_valid(extend_with_base)

    def test_direction_length_boundaries_and_model_shape(self) -> None:
        direction_at_max = legacy_search_input()
        direction_at_max["search_tasks"][0]["direction"] = "x" * 256
        self.assert_valid(direction_at_max)

        direction_too_long = copy.deepcopy(direction_at_max)
        direction_too_long["search_tasks"][0]["direction"] = "x" * 257
        self.assert_invalid(direction_too_long)

        if SearchTask is None:
            self.skipTest(f"Pydantic model unavailable: {SEARCH_TASK_IMPORT_ERROR}")
        self.assertEqual(
            "semantic purpose",
            SearchTask(
                platform="generic",
                queries=[{"query": "q"}],
                direction="semantic purpose",
            ).direction,
        )
        with self.assertRaises(Exception):
            SearchTask(platform="generic", queries=[{"query": "q"}], direction="")
        with self.assertRaises(Exception):
            SearchTask(
                platform="generic",
                queries=[{"query": "q"}],
                direction="x" * 257,
            )


class AdaptiveSearchOutputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = validator_for(SEARCH_SCHEMA_PATH, "success")
        cls.status_snapshot_validator = validator_for(
            FLOW_STATUS_SCHEMA_PATH, "result_set_snapshot"
        )

    def assert_valid(self, instance: dict) -> None:
        errors = list(self.validator.iter_errors(instance))
        self.assertEqual([], [error.message for error in errors])

    def assert_invalid(self, instance: dict) -> None:
        self.assertFalse(self.validator.is_valid(instance), msg="instance unexpectedly valid")

    def test_legacy_success_and_new_fields_are_optional(self) -> None:
        payload = adaptive_success()
        for field in (
            "mode",
            "base_result_set_id",
            "round",
            "provenance",
            "coverage",
        ):
            payload.pop(field)
        payload["platform_runs"][0].pop("direction")
        payload["platform_runs"][0]["query_runs"][0].pop("direction")
        payload["platform_runs"][0]["query_runs"][0].pop("new_unique_count")
        payload["platform_runs"][0]["query_runs"][0].pop("duplicate_count")
        self.assert_valid(payload)

    def test_provenance_and_coverage_boundaries(self) -> None:
        payload = adaptive_success()
        self.assert_valid(payload)

        legacy_coverage = copy.deepcopy(payload)
        legacy_coverage["coverage"].pop("kind")
        legacy_coverage["coverage"].pop("schema_version")
        self.assert_valid(legacy_coverage)

        for field in payload["provenance"]:
            invalid = copy.deepcopy(payload)
            invalid["provenance"][field] = -1
            self.assert_invalid(invalid)
            invalid["provenance"][field] = 10001
            self.assert_invalid(invalid)

        invalid_reason = copy.deepcopy(payload)
        invalid_reason["coverage"]["gaps"][0]["reason"] = "x" * 257
        self.assert_invalid(invalid_reason)

        invalid_gap_count = copy.deepcopy(payload)
        invalid_gap_count["coverage"]["gaps"][0]["count"] = -1
        self.assert_invalid(invalid_gap_count)

        invalid_status = copy.deepcopy(payload)
        invalid_status["coverage"]["status"] = "unknown"
        self.assert_invalid(invalid_status)

        invalid_kind = copy.deepcopy(payload)
        invalid_kind["coverage"]["kind"] = "semantic"
        self.assert_invalid(invalid_kind)

        invalid_version = copy.deepcopy(payload)
        invalid_version["coverage"]["schema_version"] = "oracle-v2"
        self.assert_invalid(invalid_version)

        for forbidden_field in (
            "factual_coverage",
            "semantic_review",
            "stop_decision",
            "model_version",
        ):
            invalid_projection = copy.deepcopy(payload)
            invalid_projection["coverage"][forbidden_field] = {}
            self.assert_invalid(invalid_projection)

        legacy_semantic_dimension = copy.deepcopy(payload)
        legacy_semantic_dimension["coverage"]["gaps"][0]["dimension"] = "target"
        self.assert_valid(legacy_semantic_dimension)

    def test_flow_status_result_set_snapshot_mirrors_optional_fields(self) -> None:
        status_schema = load_json(FLOW_STATUS_SCHEMA_PATH)
        properties = status_schema["$defs"]["result_set_snapshot"]["properties"]
        for field in (
            "mode",
            "base_result_set_id",
            "round",
            "provenance",
            "coverage",
        ):
            self.assertIn(field, properties)
            self.assertNotIn(
                field, status_schema["$defs"]["result_set_snapshot"]["required"]
            )

        snapshot = adaptive_success()
        snapshot.pop("ok")
        snapshot.pop("contract_version")
        snapshot.pop("flow_id")
        snapshot.pop("stage")
        self.assertEqual([], [
            error.message
            for error in self.status_snapshot_validator.iter_errors(snapshot)
        ])


if __name__ == "__main__":
    unittest.main()
