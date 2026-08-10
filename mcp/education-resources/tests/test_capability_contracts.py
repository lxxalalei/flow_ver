"""Schema and fixture checks for the 0025 capability authority contracts.

These tests intentionally stay at the contract boundary.  They do not import the
service, adapter or storage implementations, so a descriptor/readiness/resolution
shape cannot accidentally become a runtime claim just because a module imports.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SCHEMA_ROOT = CONTRACTS_ROOT / "schemas"
CAPABILITY_CATALOG_PATH = CONTRACTS_ROOT / "capabilities" / "capability-descriptors.json"
TOOL_CATALOG_PATH = CONTRACTS_ROOT / "tool-catalog.json"
CATALOG_VERSION = "1.1.0"
REGISTRY_VERSION = "1.1.0"
TOOL_CATALOG_VERSION = "1.5.0"
EXPECTED_PUBLIC_TOOLS = (
    "resource_flow_start",
    "resource_flow_status",
    "resource_search",
    "resource_presentation_save",
    "resource_selection_save",
    "resource_download_prepare",
    "resource_download_start",
    "resource_job_status",
    "resource_job_cancel",
    "resource_archive",
    "resource_library_search",
    "resource_browse_creator",
    "resource_inspect",
)
PLAN_ITEM_AUTHORITY_FIELDS = (
    "representation_id",
    "planned_scope",
    "planned_strategy",
    "planned_provider",
    "capability",
    "eligibility",
    "binding_digest",
)
EXPECTED_DESCRIPTOR_FACTS = {
    "cap_generic_document_primary_direct_v1": {
        "descriptor_version": "1.1.0",
        "registry_version": "1.1.0",
        "platform_id": "generic",
        "scope": "primary_resource",
        "strategy": "direct_file",
        "provider": {
            "provider_id": "generic-direct",
            "version": "1.0.0",
            "scope": "primary_resource",
        },
        "descriptor_digest": "sha256:a30ba16bf1b70ef81cc9f31003a122d0607eb3094a92de2b3fa864725f5c2421",
        "fallback": {
            "allowed": False,
            "max_scope": "primary_resource",
            "allowed_scopes": [],
            "on_errors": [],
            "scope_preserving": True,
        },
    },
    "cap_generic_webpage_landing_materialize_v1": {
        "descriptor_version": "1.1.0",
        "registry_version": "1.1.0",
        "platform_id": "generic",
        "scope": "landing_page",
        "strategy": "web_materialize",
        "provider": {
            "provider_id": "generic-web-materializer",
            "version": "1.0.0",
            "scope": "landing_page",
        },
        "descriptor_digest": "sha256:50f8d3f8ede4e260110bcb148ca2abb8dd75f87e95c1be328f85a4a5c0e0cfff",
        "fallback": {
            "allowed": False,
            "max_scope": "landing_page",
            "allowed_scopes": [],
            "on_errors": [],
            "scope_preserving": True,
        },
    },
    "cap_smartedu_document_primary_direct_v1": {
        "descriptor_version": "1.1.0",
        "registry_version": "1.1.0",
        "platform_id": "smartedu",
        "scope": "primary_resource",
        "strategy": "direct_file",
        "provider": {
            "provider_id": "smartedu-resource",
            "version": "1.0.0",
            "scope": "primary_resource",
        },
        "descriptor_digest": "sha256:b847a01769bf6afeec3228b6853e1cb502e4062ae19010db7fcc225b733344de",
        "fallback": {
            "allowed": False,
            "max_scope": "primary_resource",
            "allowed_scopes": [],
            "on_errors": [],
            "scope_preserving": True,
        },
    },
}

CONTRACT_VERSION = "1.0.0"
OBSERVED_AT = "2026-08-08T00:00:00Z"
EXPIRES_AT = "2026-08-08T01:00:00Z"
RESOURCE_ID = "res_1234567890abcdef"
RESOLUTION_ID = "resolve_1234567890abcdef"
REPRESENTATION_ID = "repr_1234567890abcdef"
FLOW_ID = "flow_1234567890abcdef"
PLAN_ID = "plan_1234567890abcdef"
JOB_ID = "job_1234567890abcdef"
PRESENTATION_ID = "pres_1234567890abcdef"

PRIMARY_DESCRIPTOR_ID = "cap_smartedu_document_primary_direct_v1"
PRIMARY_DESCRIPTOR_DIGEST = (
    "sha256:b847a01769bf6afeec3228b6853e1cb502e4062ae19010db7fcc225b733344de"
)
PRIMARY_READINESS_ID = "ready_smartedu_document_primary_direct_v1"
PRIMARY_CAPABILITY_REF = {
    "capability_id": PRIMARY_DESCRIPTOR_ID,
    "descriptor_digest": PRIMARY_DESCRIPTOR_DIGEST,
    "readiness_snapshot_id": PRIMARY_READINESS_ID,
    "provider": {
        "provider_id": "smartedu-resource",
        "version": "1.0.0",
        "scope": "primary_resource",
    },
    "strategy": "direct_file",
    "scope": "primary_resource",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def catalog_descriptor(descriptor_id: str = PRIMARY_DESCRIPTOR_ID) -> dict:
    matches = [
        descriptor
        for descriptor in load_json(CAPABILITY_CATALOG_PATH)["descriptors"]
        if descriptor["descriptor_id"] == descriptor_id
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one descriptor for {descriptor_id!r}, got {len(matches)}")
    return matches[0]


def build_registry() -> Registry:
    registry = Registry()
    for path in CONTRACTS_ROOT.rglob("*.json"):
        document = load_json(path)
        identifier = document.get("$id")
        if identifier:
            registry = registry.with_resource(identifier, Resource.from_contents(document))
    return registry


REGISTRY = build_registry()


def validator_for(name: str) -> Draft202012Validator:
    schema = load_json(SCHEMA_ROOT / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )


def tool_validator(name: str) -> Draft202012Validator:
    schema = load_json(SCHEMA_ROOT / "tools" / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )


def canonical_digest(value: object, digest_field: str) -> str:
    """Compute the contract's canonical digest preimage."""

    value = copy.deepcopy(value)
    if isinstance(value, dict):
        value.pop(digest_field, None)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def first_error_messages(validator: Draft202012Validator, value: object) -> list[str]:
    return [error.message for error in validator.iter_errors(value)]


def assert_valid(test: unittest.TestCase, validator: Draft202012Validator, value: object) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    test.assertEqual([], [error.message for error in errors])


def assert_invalid(test: unittest.TestCase, validator: Draft202012Validator, value: object) -> None:
    errors = list(validator.iter_errors(value))
    test.assertTrue(errors, "fixture unexpectedly validated")


def readiness_fixture() -> dict:
    return {
        "readiness_snapshot_id": PRIMARY_READINESS_ID,
        "capability_id": PRIMARY_DESCRIPTOR_ID,
        "descriptor_version": "1.1.0",
        "descriptor_digest": PRIMARY_DESCRIPTOR_DIGEST,
        "snapshot_digest": "sha256:" + "a" * 64,
        "status": "ready",
        "provider": {
            "provider_id": "smartedu-resource",
            "version": "1.0.0",
            "scope": "primary_resource",
        },
        "inspector": {"inspector_id": "smartedu", "version": "1.0.0"},
        "load_status": "loaded",
        "dependency_checks": [
            {"name": "provider", "status": "ok", "version": "1.0.0"},
            {"name": "inspector", "status": "ok", "version": "1.0.0"},
        ],
        "credential_posture": "optional_present",
        "network_policy_status": "allowed",
        "policy_profile": "smartedu_public_resource",
        "observed_at": OBSERVED_AT,
        "expires_at": EXPIRES_AT,
        "fallback_capability_ids": [],
        "checked_scopes": ["primary_resource"],
    }


def resolution_fixture() -> dict:
    source_fingerprint = "sha256:" + "b" * 64
    return {
        "contract_version": CONTRACT_VERSION,
        "resource_id": RESOURCE_ID,
        "resolution_id": RESOLUTION_ID,
        "resolution_version": 1,
        "resolution_status": "resolved",
        "source_fingerprint": source_fingerprint,
        "inspector": {"inspector_id": "smartedu", "version": "1.0.0"},
        "capability_ref": PRIMARY_CAPABILITY_REF,
        "observed_at": OBSERVED_AT,
        "expires_at": EXPIRES_AT,
        "availability": {"status": "available"},
        "representations": [
            {
                "representation_id": REPRESENTATION_ID,
                "scope": "primary_resource",
                "kind": "document",
                "role": "primary",
                "container": "pdf",
                "mime_type": "application/pdf",
                "size_bytes": 4096,
                "materializable": True,
                "technical_availability": "available",
                "capability_ref": PRIMARY_CAPABILITY_REF,
                "evidence": {
                    "source": "inspection",
                    "source_fingerprint": source_fingerprint,
                    "observed_at": OBSERVED_AT,
                    "expires_at": EXPIRES_AT,
                },
                "language": "zh-CN",
            }
        ],
        "failures": [],
    }


def eligibility_fixture() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "eligibility_id": "elig_smartedu_resource_001",
        "decision_id": "decision_smartedu_resource_001",
        "decision_version": "1.0.0",
        "decision_digest": "sha256:" + "c" * 64,
        "resource_id": RESOURCE_ID,
        "representation_id": REPRESENTATION_ID,
        "action": "download",
        "status": "eligible",
        "capability_ref": PRIMARY_CAPABILITY_REF,
        "policy_id": "smartedu_public_resource",
        "policy_version": "1.0.0",
        "rule_ids": ["public_resource", "primary_representation"],
        "reason": "The selected primary representation is permitted for a download attempt.",
        "reason_code": "ELIGIBILITY_REQUIRED",
        "evaluated_at": OBSERVED_AT,
        "expires_at": EXPIRES_AT,
        "evidence": [
            {
                "kind": "resolution",
                "reference": RESOLUTION_ID,
                "observed_at": OBSERVED_AT,
                "digest": "sha256:" + "b" * 64,
            },
            {
                "kind": "readiness",
                "reference": PRIMARY_READINESS_ID,
                "observed_at": OBSERVED_AT,
            },
        ],
        "revalidation_required": True,
    }


def plan_item_fixture() -> dict:
    return {
        "resource_id": RESOURCE_ID,
        "selected_position": 1,
        "platform": "smartedu",
        "representation_id": REPRESENTATION_ID,
        "planned_scope": "primary_resource",
        "planned_strategy": "direct_file",
        "planned_provider": {
            "provider_id": "smartedu-resource",
            "version": "1.0.0",
            "scope": "primary_resource",
        },
        "capability": {
            "capability_id": PRIMARY_DESCRIPTOR_ID,
            "descriptor_version": "1.1.0",
            "descriptor_digest": PRIMARY_DESCRIPTOR_DIGEST,
            "readiness_snapshot_id": PRIMARY_READINESS_ID,
        },
        "eligibility": {
            "eligibility_id": "elig_smartedu_resource_001",
            "status": "eligible",
            "expires_at": EXPIRES_AT,
            "decision_digest": "sha256:" + "c" * 64,
        },
        "binding_digest": "d" * 64,
        "planned_container": "pdf",
        "estimated_size_bytes": 4096,
        "effective_max_bytes": 5 * 1024 * 1024,
        "risks": [
            {
                "code": "PUBLIC_NETWORK_ACCESS",
                "level": "low",
                "message": "The server will use the bound public source capability.",
            }
        ],
    }


def legacy_v1_4_plan_item_fixture() -> dict:
    """Exact public Plan-item projection emitted before capability authority."""

    return {
        "resource_id": RESOURCE_ID,
        "selected_position": 1,
        "platform": "smartedu",
        "planned_container": "pdf",
        "estimated_size_bytes": 4096,
        "effective_max_bytes": 5 * 1024 * 1024,
        "risks": [
            {
                "code": "PUBLIC_NETWORK_ACCESS",
                "level": "low",
                "message": "The server will access the selected public source.",
            }
        ],
    }


def legacy_v1_4_prepare_success_fixture() -> dict:
    """Exact 1.4 prepare success shape, without the 1.5 authority projection."""

    return {
        "contract_version": CONTRACT_VERSION,
        "ok": True,
        "flow_id": FLOW_ID,
        "stage": "prepared",
        "plan_id": PLAN_ID,
        "presentation_id": PRESENTATION_ID,
        "presented_version": 1,
        "selection_version": 1,
        "selection_digest": "1" * 64,
        "plan_digest": "2" * 64,
        "expires_at": EXPIRES_AT,
        "confirmation_required": True,
        "confirmation_token": "token_contract_prepare_0001",
        "items": [legacy_v1_4_plan_item_fixture()],
    }


def current_v1_5_prepare_success_fixture() -> dict:
    value = legacy_v1_4_prepare_success_fixture()
    value.update(
        {
            "authority_digest": "3" * 64,
            "capability_binding_version": "capability-binding-v1",
            "items": [plan_item_fixture()],
        }
    )
    return value


def legacy_v1_4_start_input_fixture() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "flow_id": FLOW_ID,
        "plan_id": PLAN_ID,
        "presentation_id": PRESENTATION_ID,
        "presented_version": 1,
        "selection_version": 1,
        "selection_digest": "1" * 64,
        "plan_digest": "2" * 64,
        "confirmation_token": "token_contract_prepare_0001",
        "idempotency_key": "contract-start-0001",
    }


def legacy_v1_4_start_success_fixture() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "ok": True,
        "flow_id": FLOW_ID,
        "plan_id": PLAN_ID,
        "presentation_id": PRESENTATION_ID,
        "presented_version": 1,
        "selection_version": 1,
        "selection_digest": "1" * 64,
        "plan_digest": "2" * 64,
        "job_id": JOB_ID,
        "status": "queued",
        "queued_at": OBSERVED_AT,
    }


def current_v1_5_start_input_fixture() -> dict:
    value = legacy_v1_4_start_input_fixture()
    value["authority_digest"] = "3" * 64
    return value


def current_v1_5_start_success_fixture() -> dict:
    value = legacy_v1_4_start_success_fixture()
    value["authority_digest"] = "3" * 64
    return value


def actual_outcome_fixture(status: str = "succeeded") -> dict:
    outcome = {
        "contract_version": CONTRACT_VERSION,
        "outcome_id": "outcome_smartedu_resource_001",
        "plan_item_id": "pitem_smartedu_resource_001",
        "resource_id": RESOURCE_ID,
        "planned_scope": "primary_resource",
        "actual_scope": "primary_resource",
        "status": status,
        "provider": {
            "provider_id": "smartedu-resource",
            "version": "1.0.0",
            "scope": "primary_resource",
        },
        "strategy": "direct_file",
        "representation": {
            "representation_id": REPRESENTATION_ID,
            "scope": "primary_resource",
            "kind": "document",
            "role": "primary",
            "container": "pdf",
            "mime_type": "application/pdf",
            "size_bytes": 4096,
            "source_fingerprint": "sha256:" + "b" * 64,
        },
        "validation": {
            "status": "validated",
            "mime_type": "application/pdf",
            "magic_status": "matched",
            "size_bytes": 4096,
            "sha256": "e" * 64,
        },
        "observed_at": OBSERVED_AT,
        "outcome_digest": "sha256:" + "f" * 64,
    }
    if status == "succeeded":
        outcome.update({"asset_id": "asset_1234567890abcdef", "bundle_id": "bundle_1234567890abcdef"})
    else:
        outcome["failure"] = {
            "code": "DOWNLOAD_FAILED" if status == "failed" else "JOB_CANCELLED",
            "message": "provider did not produce the requested representation",
            "retriable": status == "failed",
        }
    return outcome


def job_status_outcome_fixture() -> dict:
    """Public, locator-free projection of persisted execution authority."""

    return {
        "outcome_id": "outcome_smartedu_resource_001",
        "resource_id": RESOURCE_ID,
        "status": "succeeded",
        "planned": {
            "scope": "primary_resource",
            "strategy": "direct_file",
            "provider": {
                "provider_id": "smartedu-resource",
                "version": "1.0.0",
                "scope": "primary_resource",
            },
            "plan_binding_digest": "d" * 64,
        },
        "execution": {
            "binding_digest": "e" * 64,
            "scope": "primary_resource",
            "strategy": "direct_file",
            "provider": {
                "provider_id": "smartedu-resource",
                "version": "1.0.0",
                "scope": "primary_resource",
            },
            "capability": {
                "capability_id": PRIMARY_DESCRIPTOR_ID,
                "descriptor_version": "1.1.0",
                "descriptor_digest": PRIMARY_DESCRIPTOR_DIGEST,
                "registry_version": "1.1.0",
                "registry_digest": "sha256:" + "a" * 64,
                "readiness_snapshot_id": PRIMARY_READINESS_ID,
                "readiness_digest": "sha256:" + "b" * 64,
            },
            "eligibility": {
                "eligibility_id": "elig_smartedu_resource_001",
                "decision_digest": "sha256:" + "c" * 64,
            },
            "source_fingerprint": "sha256:" + "b" * 64,
            "revalidated_at": OBSERVED_AT,
        },
        "actual": {
            "scope": "primary_resource",
            "strategy": "direct_file",
            "provider": {
                "provider_id": "smartedu-resource",
                "version": "1.0.0",
                "scope": "primary_resource",
            },
        },
        "bundle_id": "bundle_1234567890abcdef",
        "asset_ids": ["asset_1234567890abcdef"],
        "started_at": OBSERVED_AT,
        "completed_at": OBSERVED_AT,
        "outcome_digest": "f" * 64,
    }


class CapabilityContractTests(unittest.TestCase):
    def test_public_catalog_version_keeps_contract_and_exact_tool_set(self) -> None:
        catalog = load_json(TOOL_CATALOG_PATH)
        catalog_schema = load_json(SCHEMA_ROOT / "tool-catalog.schema.json")
        common_schema = load_json(SCHEMA_ROOT / "common.schema.json")

        self.assertEqual(TOOL_CATALOG_VERSION, catalog["catalog_version"])
        self.assertEqual(
            TOOL_CATALOG_VERSION,
            catalog_schema["properties"]["catalog_version"]["const"],
        )
        self.assertEqual(CONTRACT_VERSION, catalog["contract_version"])
        self.assertEqual(
            CONTRACT_VERSION,
            common_schema["$defs"]["contract_version"]["const"],
        )
        self.assertEqual(
            EXPECTED_PUBLIC_TOOLS,
            tuple(tool["name"] for tool in catalog["tools"]),
        )
        self.assertEqual(13, len(catalog["tools"]))

    def test_schema_documents_parse_and_local_refs_resolve(self) -> None:
        for path in sorted(SCHEMA_ROOT.rglob("*.schema.json")):
            with self.subTest(schema=path.relative_to(CONTRACTS_ROOT)):
                schema = load_json(path)
                Draft202012Validator.check_schema(schema)
        # Constructing the validators above and validating a cross-file fixture
        # exercises the URI registry for common.schema.json and error-codes.json.
        assert_valid(self, validator_for("capability-descriptors"), load_json(CAPABILITY_CATALOG_PATH))

    def test_static_catalog_descriptors_and_canonical_digests(self) -> None:
        catalog = load_json(CAPABILITY_CATALOG_PATH)
        assert_valid(self, validator_for("capability-descriptors"), catalog)
        self.assertEqual(CATALOG_VERSION, catalog["catalog_version"])
        self.assertEqual(REGISTRY_VERSION, catalog["registry_version"])
        self.assertEqual(tuple(EXPECTED_DESCRIPTOR_FACTS), tuple(item["descriptor_id"] for item in catalog["descriptors"]))
        descriptor_validator = validator_for("capability-descriptor")
        for descriptor in catalog["descriptors"]:
            with self.subTest(descriptor=descriptor["descriptor_id"]):
                expected = EXPECTED_DESCRIPTOR_FACTS[descriptor["descriptor_id"]]
                assert_valid(self, descriptor_validator, descriptor)
                for field in (
                    "descriptor_version",
                    "registry_version",
                    "platform_id",
                    "scope",
                    "strategy",
                    "provider",
                    "descriptor_digest",
                    "fallback",
                ):
                    self.assertEqual(expected[field], descriptor[field], field)
                self.assertEqual(
                    canonical_digest(descriptor, "descriptor_digest"),
                    descriptor["descriptor_digest"],
                )

    def test_positive_descriptor_readiness_resolution_eligibility_plan_and_outcome(self) -> None:
        fixtures = {
            "capability-descriptor": catalog_descriptor(),
            "deployment-readiness": readiness_fixture(),
            "resolution": resolution_fixture(),
            "eligibility-decision": eligibility_fixture(),
            "plan-item": plan_item_fixture(),
            "actual-outcome": actual_outcome_fixture(),
        }
        for name, fixture in fixtures.items():
            with self.subTest(schema=name):
                assert_valid(self, validator_for(name), fixture)

    def test_invalid_digest_ids_and_unknown_statuses_are_rejected(self) -> None:
        cases = []
        descriptor = catalog_descriptor()
        for field in ("descriptor_id", "descriptor_version", "descriptor_digest", "scope", "provider"):
            value = copy.deepcopy(descriptor)
            value.pop(field)
            cases.append(("capability-descriptor", value, f"missing {field}"))
        value = copy.deepcopy(descriptor)
        value["descriptor_digest"] = "sha256:" + "Z" * 64
        cases.append(("capability-descriptor", value, "uppercase digest"))

        value = readiness_fixture()
        value["status"] = "candidate_available"
        cases.append(("deployment-readiness", value, "unknown readiness status"))
        value = resolution_fixture()
        value["resolution_status"] = "candidate_available"
        cases.append(("resolution", value, "unknown resolution status"))
        value = eligibility_fixture()
        value["status"] = "allowed"
        cases.append(("eligibility-decision", value, "unknown eligibility status"))
        value = actual_outcome_fixture()
        value["status"] = "complete"
        cases.append(("actual-outcome", value, "unknown outcome status"))

        for schema_name, value, label in cases:
            with self.subTest(case=label):
                assert_invalid(self, validator_for(schema_name), value)

    def test_primary_scope_cannot_be_masqueraded_by_landing_or_metadata(self) -> None:
        descriptor = catalog_descriptor()
        for role in ("landing", "metadata"):
            value = copy.deepcopy(descriptor)
            value["representation"]["role"] = role
            with self.subTest(layer="descriptor", role=role):
                assert_invalid(self, validator_for("capability-descriptor"), value)

        for scope, role in (("primary_resource", "landing"), ("landing_page", "primary"), ("primary_resource", "metadata")):
            value = resolution_fixture()
            value["representations"][0]["scope"] = scope
            value["representations"][0]["role"] = role
            with self.subTest(layer="resolution", scope=scope, role=role):
                assert_invalid(self, validator_for("resolution"), value)

        value = actual_outcome_fixture()
        value["representation"]["scope"] = "landing_page"
        value["representation"]["role"] = "landing"
        value["actual_scope"] = "primary_resource"
        with self.subTest(layer="outcome"):
            assert_invalid(self, validator_for("actual-outcome"), value)

    def test_provider_scope_mismatch_is_rejected(self) -> None:
        descriptor = catalog_descriptor()
        descriptor["provider"]["scope"] = "landing_page"
        assert_invalid(self, validator_for("capability-descriptor"), descriptor)

        plan = plan_item_fixture()
        plan["planned_provider"]["scope"] = "landing_page"
        assert_invalid(self, validator_for("plan-item"), plan)

        outcome = actual_outcome_fixture()
        outcome["provider"]["scope"] = "landing_page"
        assert_invalid(self, validator_for("actual-outcome"), outcome)

    def test_allow_safe_fallback_is_a_non_authorizing_compatibility_hint(self) -> None:
        schema = load_json(SCHEMA_ROOT / "tools" / "resource_download_prepare.schema.json")
        description = str(
            schema["$defs"]["options"]["properties"]["allow_safe_fallback"].get(
                "description", ""
            )
        ).lower()
        for term in ("descriptor", "readiness", "provider", "scope", "generic"):
            with self.subTest(term=term):
                self.assertIn(term, description)

        request = {
            "contract_version": CONTRACT_VERSION,
            "flow_id": FLOW_ID,
            "idempotency_key": "contract-prepare-fallback-0001",
            "presentation_id": PRESENTATION_ID,
            "presented_version": 1,
            "selection_version": 1,
            "selection_digest": "1" * 64,
            "options": {"allow_safe_fallback": True},
        }
        validator = tool_validator("resource_download_prepare")
        assert_valid(self, validator, request)

        # No public option may turn the compatibility hint into a provider or
        # scope-routing instruction.  The options object remains closed.
        for forbidden in (
            "fallback_provider",
            "fallback_platform",
            "fallback_scope",
            "fallback_strategy",
        ):
            value = copy.deepcopy(request)
            value["options"][forbidden] = "generic"
            with self.subTest(forbidden=forbidden):
                assert_invalid(self, validator, value)

    def test_required_bindings_and_outcome_state_requirements(self) -> None:
        for name, factory, required in (
            ("eligibility-decision", eligibility_fixture, "evidence"),
            ("plan-item", plan_item_fixture, "capability"),
        ):
            value = factory()
            value.pop(required)
            with self.subTest(schema=name, required=required):
                assert_invalid(self, validator_for(name), value)

        succeeded = actual_outcome_fixture("succeeded")
        succeeded.pop("asset_id")
        assert_invalid(self, validator_for("actual-outcome"), succeeded)
        for status in ("failed", "cancelled"):
            value = actual_outcome_fixture(status)
            value.pop("failure")
            with self.subTest(status=status):
                assert_invalid(self, validator_for("actual-outcome"), value)

    def test_plan_item_accepts_legacy_or_complete_authority_shape_only(self) -> None:
        validator = validator_for("plan-item")
        assert_valid(self, validator, legacy_v1_4_plan_item_fixture())
        assert_valid(self, validator, plan_item_fixture())

        for missing in PLAN_ITEM_AUTHORITY_FIELDS:
            value = plan_item_fixture()
            value.pop(missing)
            with self.subTest(partial_authority_missing=missing):
                assert_invalid(self, validator, value)

    def test_prepare_authority_pair_is_all_or_none(self) -> None:
        validator = tool_validator("resource_download_prepare")
        assert_valid(self, validator, legacy_v1_4_prepare_success_fixture())
        assert_valid(self, validator, current_v1_5_prepare_success_fixture())

        for missing in ("authority_digest", "capability_binding_version"):
            value = current_v1_5_prepare_success_fixture()
            value.pop(missing)
            with self.subTest(partial_prepare_authority_missing=missing):
                assert_invalid(self, validator, value)

    def test_start_authority_digest_remains_optional_for_input_and_success(self) -> None:
        schema = load_json(
            SCHEMA_ROOT / "tools" / "resource_download_start.schema.json"
        )
        self.assertNotIn("authority_digest", schema["$defs"]["input"]["required"])
        self.assertNotIn("authority_digest", schema["$defs"]["success"]["required"])

        validator = tool_validator("resource_download_start")
        for value in (
            legacy_v1_4_start_input_fixture(),
            legacy_v1_4_start_success_fixture(),
            current_v1_5_start_input_fixture(),
            current_v1_5_start_success_fixture(),
        ):
            with self.subTest(shape=tuple(value)):
                assert_valid(self, validator, value)

    def test_paths_urls_credentials_and_unknown_fields_are_not_contract_fields(self) -> None:
        for schema_name, fixture, field in (
            ("capability-descriptor", catalog_descriptor(), "path"),
            ("deployment-readiness", readiness_fixture(), "credential"),
            ("resolution", resolution_fixture(), "url"),
            ("plan-item", plan_item_fixture(), "local_path"),
            ("actual-outcome", actual_outcome_fixture(), "download_url"),
        ):
            value = copy.deepcopy(fixture)
            value[field] = "https://example.com/not-a-server-fact"
            with self.subTest(schema=schema_name, field=field):
                assert_invalid(self, validator_for(schema_name), value)

    def test_legacy_public_tool_samples_remain_valid_with_optional_projection(self) -> None:
        inspect_input = {
            "contract_version": CONTRACT_VERSION,
            "flow_id": FLOW_ID,
            "resource_id": RESOURCE_ID,
            "idempotency_key": "contract-inspect-0001",
        }
        inspect_success = {
            "contract_version": CONTRACT_VERSION,
            "ok": True,
            "flow_id": FLOW_ID,
            "resource_id": RESOURCE_ID,
            "resolution_id": RESOLUTION_ID,
            "resolution_status": "resolved",
            "resolved_resource": {
                "title": "示例课程讲义",
                "resource_type": "document",
                "availability": {"status": "available"},
                "representations": [
                    {"representation_id": REPRESENTATION_ID, "kind": "document"}
                ],
                "metadata": {"language": "zh-CN"},
            },
            "inspection": {
                "inspector_id": "smartedu",
                "version": "1.0.0",
                "method": "fixture",
                "cache_status": "miss",
                "inspected_at": OBSERVED_AT,
                "warnings": [],
            },
            "failures": [],
        }
        plan_input = {
            "contract_version": CONTRACT_VERSION,
            "flow_id": FLOW_ID,
            "idempotency_key": "contract-prepare-0001",
            "presentation_id": PRESENTATION_ID,
            "presented_version": 1,
            "selection_version": 1,
            "selection_digest": "1" * 64,
        }
        plan_success = legacy_v1_4_prepare_success_fixture()
        start_input = legacy_v1_4_start_input_fixture()
        start_success = legacy_v1_4_start_success_fixture()
        status_success = {
            "contract_version": CONTRACT_VERSION,
            "ok": True,
            "flow_id": FLOW_ID,
            "plan_id": PLAN_ID,
            "presentation_id": PRESENTATION_ID,
            "presented_version": 1,
            "selection_version": 1,
            "selection_digest": "1" * 64,
            "plan_digest": "2" * 64,
            "job_id": JOB_ID,
            "status": "succeeded",
            "progress": {"percent": 100, "completed_items": 1, "total_items": 1},
            "assets": [],
            "failures": [],
            "updated_at": OBSERVED_AT,
        }
        for name, values in (
            ("resource_inspect", (inspect_input, inspect_success)),
            ("resource_download_prepare", (plan_input, plan_success)),
            ("resource_download_start", (start_input, start_success)),
            ("resource_job_status", ({"contract_version": CONTRACT_VERSION, "flow_id": FLOW_ID, "job_id": JOB_ID}, status_success)),
        ):
            validator = tool_validator(name)
            for value in values:
                with self.subTest(tool=name):
                    assert_valid(self, validator, value)

    def test_capability_outcome_projection_can_be_embedded_in_job_status(self) -> None:
        status_success = {
            "contract_version": CONTRACT_VERSION,
            "ok": True,
            "flow_id": FLOW_ID,
            "plan_id": PLAN_ID,
            "presentation_id": PRESENTATION_ID,
            "presented_version": 1,
            "selection_version": 1,
            "selection_digest": "1" * 64,
            "plan_digest": "2" * 64,
            "job_id": JOB_ID,
            "status": "succeeded",
            "progress": {"percent": 100, "completed_items": 1, "total_items": 1},
            "assets": [],
            "failures": [],
            "outcomes": [job_status_outcome_fixture()],
            "updated_at": OBSERVED_AT,
        }
        assert_valid(self, tool_validator("resource_job_status"), status_success)


if __name__ == "__main__":
    unittest.main()
