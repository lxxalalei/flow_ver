"""Contract guards for capability-authority error normalization.

The capability coordinator, acquisition router, and authority persistence layer
use implementation-specific failures internally.  Public MCP errors must use the
append-only catalog in ``contracts/error-codes.json``.  These tests inventory the
runtime literals mechanically and require every one to be cataloged or assigned
an explicit Service-boundary normalization.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SOURCE_ROOT = SERVICE_ROOT / "src" / "education_resource_mcp"
ERROR_CATALOG_PATH = CONTRACTS_ROOT / "error-codes.json"
CAPABILITY_SOURCE = SOURCE_ROOT / "capability.py"
ROUTER_SOURCE = SOURCE_ROOT / "acquisition" / "router.py"
STORAGE_SOURCE = SOURCE_ROOT / "storage.py"

ERROR_LITERAL = re.compile(r"^[A-Z][A-Z0-9_]+$")
METADATA_FIELDS = {"code", "category", "retriable", "meaning"}

REQUIRED_PUBLIC_AUTHORITY_CODES = {
    "CAPABILITY_BINDING_CONFLICT",
    "CAPABILITY_DESCRIPTOR_AMBIGUOUS",
    "CAPABILITY_DESCRIPTOR_DRIFT",
    "CAPABILITY_DESCRIPTOR_INVALID",
    "CAPABILITY_NOT_DECLARED",
    "CAPABILITY_NOT_READY",
    "CAPABILITY_REGISTRY_DRIFT",
    "CAPABILITY_SCOPE_MISMATCH",
    "CAPABILITY_STRATEGY_MISMATCH",
    "CAPABILITY_STRATEGY_REQUIRED",
    "CAPABILITY_VERSION_CONFLICT",
    "ELIGIBILITY_CONTEXT_REQUIRED",
    "ELIGIBILITY_DRIFT",
    "ELIGIBILITY_EXPIRED",
    "ELIGIBILITY_REQUIRED",
    "OUTCOME_MISMATCH",
    "POLICY_BLOCKED",
    "PROVIDER_DRIFT",
    "PROVIDER_SCOPE_MISMATCH",
    "PROVIDER_UNAVAILABLE",
    "READINESS_DRIFT",
    "READINESS_EXPIRED",
    "READINESS_UNBOUND",
    "REPRESENTATION_AMBIGUOUS",
    "REPRESENTATION_DRIFT",
    "REPRESENTATION_NOT_FOUND",
    "REPRESENTATION_NOT_MATERIALIZABLE",
    "REPRESENTATION_NOT_PRIMARY",
    "REPRESENTATION_REQUIRED",
    "RESOLUTION_STALE",
    "SCOPE_DRIFT",
    "SOURCE_DRIFT",
    "SOURCE_FINGERPRINT_UNAVAILABLE",
    "STRATEGY_DRIFT",
    "VALIDATION_ERROR",
}

# CapabilityAuthorityError and eligibility reason strings that are intentionally
# internal are normalized before a public tool result is returned.  All other
# uppercase literals in capability.py must already be stable public codes.
CAPABILITY_RUNTIME_NORMALIZATION = {
    "CAPABILITY_DEPRECATED": "CAPABILITY_NOT_READY",
    "CAPABILITY_REPRESENTATION_MISMATCH": "CAPABILITY_SCOPE_MISMATCH",
    "INVALID_DIGEST": "VALIDATION_ERROR",
    "INVALID_INPUT": "VALIDATION_ERROR",
    "INVALID_TIMESTAMP": "VALIDATION_ERROR",
    "RESOLUTION_REQUIRED": "RESOLUTION_STALE",
    "RESOLUTION_UNAVAILABLE": "RESOLUTION_STALE",
    "RESOURCE_ID_REQUIRED": "VALIDATION_ERROR",
}

# The router may retain provider/item failure strings in private result models,
# but these implementation failures have stable public meanings only after this
# normalization.  A dynamic unregistered provider/item code falls back to
# DOWNLOAD_FAILED at the public Service boundary.
ROUTER_RUNTIME_NORMALIZATION = {
    "ACQUISITION_FAILED": "DOWNLOAD_FAILED",
    "ACQUISITION_OUTPUT_INVALID": "CONTENT_VALIDATION_FAILED",
    "UNSUPPORTED_ACQUISITION_STRATEGY": "CAPABILITY_STRATEGY_MISMATCH",
}
ROUTER_DYNAMIC_FAILURE_FALLBACK = "DOWNLOAD_FAILED"

# Storage exceptions are persistence implementation details, not public codes.
# Keep this mapping function-specific so a new authority failure cannot silently
# cross the Service boundary without an explicit semantic classification.
STORAGE_RUNTIME_NORMALIZATION = {
    "_normalize_plan_capability_items": {
        "capability_binding_digest_mismatch": "CAPABILITY_BINDING_CONFLICT",
        "capability_binding_missing": "CAPABILITY_BINDING_CONFLICT",
        "capability_binding_resource_mismatch": "CAPABILITY_BINDING_CONFLICT",
        "capability_representation_too_large": "VALIDATION_ERROR",
        "duplicate_capability_binding": "CAPABILITY_BINDING_CONFLICT",
        "duplicate_capability_binding_digest": "CAPABILITY_BINDING_CONFLICT",
        "invalid_capability_binding": "VALIDATION_ERROR",
        "invalid_capability_binding_position": "VALIDATION_ERROR",
        "invalid_capability_representation": "VALIDATION_ERROR",
        "invalid_capability_scope": "VALIDATION_ERROR",
        "invalid_capability_strategy": "VALIDATION_ERROR",
    },
    "_eligibility_action_for_strategy": {
        "capability_strategy_mismatch": "CAPABILITY_STRATEGY_MISMATCH",
    },
    "_normalize_execution_bindings": {
        "execution_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
        "execution_binding_missing": "CAPABILITY_BINDING_CONFLICT",
    },
    "_decode_readiness_authority": {
        "capability_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
    },
    "_decode_eligibility_authority": {
        "capability_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
    },
    "_resolution_representation_evidence": {
        "resolution_stale": "RESOLUTION_STALE",
    },
    "_assert_representation_evidence_matches": {
        "representation_drift": "REPRESENTATION_DRIFT",
    },
    "save_capability_readiness_snapshot": {
        "invalid_capability_scope": "VALIDATION_ERROR",
        "invalid_readiness_expiry": "VALIDATION_ERROR",
        "invalid_readiness_issues": "VALIDATION_ERROR",
        "invalid_readiness_snapshot": "VALIDATION_ERROR",
        "invalid_readiness_status": "VALIDATION_ERROR",
        "readiness_issues_too_large": "VALIDATION_ERROR",
        "readiness_snapshot_conflict": "CAPABILITY_BINDING_CONFLICT",
        "readiness_snapshot_digest_mismatch": "CAPABILITY_BINDING_CONFLICT",
    },
    "save_eligibility_decision": {
        "eligibility_decision_conflict": "CAPABILITY_BINDING_CONFLICT",
        "eligibility_decision_digest_mismatch": "CAPABILITY_BINDING_CONFLICT",
        "invalid_eligibility_action": "VALIDATION_ERROR",
        "invalid_eligibility_decision": "VALIDATION_ERROR",
        "invalid_eligibility_expiry": "VALIDATION_ERROR",
        "invalid_eligibility_reason_codes": "VALIDATION_ERROR",
        "invalid_eligibility_status": "VALIDATION_ERROR",
    },
    "reserve_job": {
        "capability_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
        "capability_binding_missing": "CAPABILITY_BINDING_CONFLICT",
        "confirmation_invalid": "CONFIRMATION_INVALID",
        "eligibility_drift": "ELIGIBILITY_DRIFT",
        "eligibility_expired": "ELIGIBILITY_EXPIRED",
        "eligibility_required": "ELIGIBILITY_REQUIRED",
        "execution_binding_conflict": "CAPABILITY_BINDING_CONFLICT",
        "execution_binding_missing": "CAPABILITY_BINDING_CONFLICT",
        "failed to reserve job": "INTERNAL_ERROR",
        "idempotency record points to a missing job": "INTERNAL_ERROR",
        "idempotency_conflict": "IDEMPOTENCY_CONFLICT",
        "plan_binding_mismatch": "PLAN_BINDING_CONFLICT",
        "plan_expired": "PLAN_EXPIRED",
        "plan_not_found": "PLAN_NOT_FOUND",
        "plan_used": "PLAN_ALREADY_USED",
        "readiness_drift": "READINESS_DRIFT",
        "readiness_expired": "READINESS_EXPIRED",
        "readiness_not_ready": "CAPABILITY_NOT_READY",
        "resolution_stale": "RESOLUTION_STALE",
        "selection_changed": "SELECTION_VERSION_CONFLICT",
    },
    "get_job_execution_items": {
        "execution_binding_missing": "CAPABILITY_BINDING_CONFLICT",
        "job_not_found": "JOB_NOT_FOUND",
    },
    "start_acquisition_outcome": {
        "acquisition_outcome_conflict": "OUTCOME_MISMATCH",
        "execution_binding_missing": "CAPABILITY_BINDING_CONFLICT",
        "failed_to_create_acquisition_outcome": "INTERNAL_ERROR",
        "job_cancelling": "JOB_CANCELLED",
        "job_not_found": "JOB_NOT_FOUND",
    },
    "complete_acquisition_outcome": {
        "acquisition_outcome_asset_mismatch": "OUTCOME_MISMATCH",
        "acquisition_outcome_assets_forbidden": "OUTCOME_MISMATCH",
        "acquisition_outcome_bundle_mismatch": "OUTCOME_MISMATCH",
        "acquisition_outcome_conflict": "OUTCOME_MISMATCH",
        "acquisition_outcome_evidence_missing": "OUTCOME_MISMATCH",
        "acquisition_outcome_failure_missing": "OUTCOME_MISMATCH",
        "acquisition_outcome_not_started": "OUTCOME_MISMATCH",
        "capability_scope_upgrade": "OUTCOME_MISMATCH",
        "failed_to_complete_acquisition_outcome": "INTERNAL_ERROR",
        "invalid_acquisition_outcome_assets": "VALIDATION_ERROR",
        "invalid_acquisition_outcome_retriable": "VALIDATION_ERROR",
        "invalid_acquisition_outcome_status": "VALIDATION_ERROR",
        "invalid_capability_scope": "VALIDATION_ERROR",
        "job_cancelling": "JOB_CANCELLED",
        "job_not_found": "JOB_NOT_FOUND",
        "provider_binding_conflict": "OUTCOME_MISMATCH",
        "strategy_binding_conflict": "OUTCOME_MISMATCH",
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_source(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def uppercase_string_literals(path: Path) -> set[str]:
    tree = parse_source(path)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and ERROR_LITERAL.fullmatch(node.value)
    }


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one function named {name!r}, got {len(matches)}")
    return matches[0]


def literal_raised_failures(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    failures: set[str] = set()
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Raise):
            continue
        raised = candidate.exc
        if not isinstance(raised, ast.Call) or not raised.args:
            continue
        message = raised.args[0]
        if isinstance(message, ast.Constant) and isinstance(message.value, str):
            failures.add(message.value)
    return failures


class AuthorityErrorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_json(ERROR_CATALOG_PATH)
        cls.public_codes = list(cls.catalog["$defs"]["error_code"]["enum"])
        cls.metadata = list(cls.catalog["x-error-codes"])
        cls.public_code_set = set(cls.public_codes)

    def test_catalog_schema_enum_and_metadata_are_one_to_one(self) -> None:
        Draft202012Validator.check_schema(self.catalog)
        validator = Draft202012Validator(self.catalog)

        metadata_codes = [entry.get("code") for entry in self.metadata]
        self.assertEqual(len(self.public_codes), len(set(self.public_codes)), "duplicate enum code")
        self.assertEqual(len(metadata_codes), len(set(metadata_codes)), "duplicate metadata code")
        self.assertEqual(len(self.public_codes), len(metadata_codes))
        self.assertSetEqual(self.public_code_set, set(metadata_codes))

        for entry in self.metadata:
            self.assertSetEqual(METADATA_FIELDS, set(entry), entry.get("code"))
            self.assertIsInstance(entry["code"], str)
            self.assertTrue(entry["code"].strip())
            self.assertIsInstance(entry["category"], str)
            self.assertTrue(entry["category"].strip())
            self.assertIs(type(entry["retriable"]), bool)
            self.assertIsInstance(entry["meaning"], str)
            self.assertTrue(entry["meaning"].strip())

        for code in self.public_codes:
            validator.validate(code)

    def test_required_capability_authority_codes_are_public(self) -> None:
        self.assertSetEqual(
            set(),
            REQUIRED_PUBLIC_AUTHORITY_CODES - self.public_code_set,
            "required authority codes are missing from the stable catalog",
        )

    def test_capability_runtime_literals_are_public_or_normalized(self) -> None:
        runtime_codes = uppercase_string_literals(CAPABILITY_SOURCE)
        unclassified = runtime_codes - self.public_code_set - set(CAPABILITY_RUNTIME_NORMALIZATION)
        self.assertSetEqual(set(), unclassified)
        self.assertSetEqual(
            set(),
            set(CAPABILITY_RUNTIME_NORMALIZATION.values()) - self.public_code_set,
            "capability normalization targets must be public codes",
        )

    def test_router_runtime_literals_are_public_or_normalized(self) -> None:
        runtime_codes = uppercase_string_literals(ROUTER_SOURCE)
        unclassified = runtime_codes - self.public_code_set - set(ROUTER_RUNTIME_NORMALIZATION)
        self.assertSetEqual(set(), unclassified)
        targets = set(ROUTER_RUNTIME_NORMALIZATION.values()) | {
            ROUTER_DYNAMIC_FAILURE_FALLBACK
        }
        self.assertSetEqual(
            set(),
            targets - self.public_code_set,
            "router normalization targets must be public codes",
        )

    def test_storage_authority_failures_have_function_specific_mappings(self) -> None:
        tree = parse_source(STORAGE_SOURCE)
        for name, mapping in STORAGE_RUNTIME_NORMALIZATION.items():
            with self.subTest(function=name):
                observed = literal_raised_failures(function_node(tree, name))
                self.assertSetEqual(observed, set(mapping))
                self.assertSetEqual(
                    set(),
                    set(mapping.values()) - self.public_code_set,
                    "storage normalization targets must be public codes",
                )


if __name__ == "__main__":
    unittest.main()
