"""Focused tests for the capability authority coordinator.

These tests exercise only the descriptor/readiness/resolution/eligibility chain;
they intentionally do not invoke the service or acquisition router.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import tempfile
from pathlib import Path
import unittest

from education_resource_mcp.capability import (
    CapabilityAuthorityError,
    CapabilityCoordinator,
    classify_representation_scope,
)
from education_resource_mcp.retrieval.registry import RegistrySnapshot
from education_resource_mcp.storage import Store


NOW = "2026-08-08T00:00:00+00:00"
FLOW_ID = "flow_1234567890abcdef"
RESOURCE_ID = "res_1234567890abcdef"
RESOLUTION_ID = "resolve_1234567890abcdef"
REPRESENTATION_ID = "repr_1234567890abcdef"
SOURCE_DIGEST = "sha256:" + "b" * 64


def ready_inventory() -> dict[str, object]:
    return {
        "provider_versions": {
            "smartedu-resource": "1.0.0",
            "generic-direct": "1.0.0",
            "generic-web-materializer": "1.0.0",
        },
        "inspector_versions": {"smartedu": "1.0.0", "generic": "1.0.0"},
        "provider_scopes": {
            "smartedu-resource": ["primary_resource"],
            "generic-direct": ["primary_resource"],
            "generic-web-materializer": ["landing_page"],
        },
        "inspector_scopes": {
            "smartedu": ["primary_resource"],
            "generic": [
                "primary_resource",
                "representation",
                "landing_page",
                "metadata",
            ],
        },
        "auth_ready": True,
        "policy_allowed": True,
    }


def resource() -> dict[str, object]:
    return {
        "resource_id": RESOURCE_ID,
        "platform": "smartedu",
        "resource_type": "document",
        "title": "Example lesson",
        "source_fingerprint": SOURCE_DIGEST,
    }


def primary_resolution(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "resource_id": RESOURCE_ID,
        "resolution_id": RESOLUTION_ID,
        "resolution_status": "resolved",
        "representations": [
            {
                "representation_id": REPRESENTATION_ID,
                "scope": "primary_resource",
                "kind": "document",
                "role": "primary",
                "container": "pdf",
                "mime_type": "application/pdf",
                "materializable": True,
                "concrete": True,
                # These values must not be persisted in the plan evidence.
                "source_url": "https://example.invalid/file.pdf",
                "locator": {"path": "/tmp/file.pdf", "token": "secret"},
            }
        ],
    }
    value.update(overrides)
    return value


def landing_resolution(*, materializable: bool = True, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "resource_id": RESOURCE_ID,
        "resolution_id": RESOLUTION_ID,
        "resolution_status": "resolved",
        "representations": [
            {
                "representation_id": REPRESENTATION_ID,
                "scope": "landing_page",
                "kind": "webpage",
                "role": "landing",
                "container": "html",
                "mime_type": "text/html",
                "materializable": materializable,
                "technical_availability": "available",
            }
        ],
    }
    value.update(overrides)
    return value


class CapabilityAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = CapabilityCoordinator(runtime_inventory=ready_inventory())

    def test_authority_ttls_must_be_finite_and_positive(self) -> None:
        for field in ("readiness_ttl_seconds", "eligibility_ttl_seconds"):
            for invalid in (None, True, 0, -1, float("nan"), float("inf")):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"^{field} must be a finite positive number$",
                    ):
                        CapabilityCoordinator(
                            runtime_inventory=ready_inventory(),
                            **{field: invalid},
                        )

    def test_default_uses_standalone_catalog_only(self) -> None:
        descriptor_ids = {item.capability_id for item in self.coordinator.registry_snapshot.descriptors}
        self.assertTrue(
            {
                "cap_generic_document_primary_direct_v1",
                "cap_generic_webpage_landing_materialize_v1",
                "cap_smartedu_document_primary_direct_v1",
            }.issubset(descriptor_ids)
        )
        with self.assertRaises(CapabilityAuthorityError) as raised:
            self.coordinator.select_descriptor("bilibili", resource_type="video")
        self.assertEqual("CAPABILITY_NOT_DECLARED", raised.exception.code)

    def test_scope_classification_does_not_upgrade_weak_evidence(self) -> None:
        self.assertEqual(
            "primary_resource",
            classify_representation_scope(primary_resolution(), primary_resolution()["representations"][0]),
        )
        landing = {"resolution_id": RESOLUTION_ID, "scope": "landing_page"}
        self.assertEqual(
            "landing_page",
            classify_representation_scope(landing, {"kind": "webpage", "role": "landing", "materializable": False}),
        )
        self.assertEqual(
            "metadata",
            classify_representation_scope({"resolution_id": RESOLUTION_ID}, {"kind": "metadata"}),
        )
        # materializable=True alone is insufficient to claim a concrete primary.
        self.assertEqual(
            "representation",
            classify_representation_scope(
                {"resolution_id": RESOLUTION_ID},
                {"kind": "document", "role": "primary", "materializable": True},
            ),
        )

    def test_readiness_missing_provider_is_structured(self) -> None:
        descriptor = self.coordinator.select_descriptor("smartedu", resource_type="document")
        readiness = self.coordinator.probe_readiness(descriptor, runtime_inventory={})
        self.assertEqual("missing_provider", readiness.status)
        self.assertFalse(readiness.ready)
        with self.assertRaises(CapabilityAuthorityError) as raised:
            self.coordinator.persist_readiness(readiness)
        self.assertEqual("PROVIDER_UNAVAILABLE", raised.exception.code)

    def test_injected_executable_strategy_is_bound_without_legacy_inference(self) -> None:
        base = self.coordinator.select_descriptor("smartedu", resource_type="document")
        direct = replace(
            base,
            strategy="direct_file",
            acquisition_strategies=("direct_file",),
            descriptor_digest="a" * 64,
        )
        snapshot = replace(self.coordinator.registry_snapshot, descriptors=(direct,))
        coordinator = CapabilityCoordinator(registry_snapshot=snapshot, runtime_inventory=ready_inventory())
        resolution = primary_resolution(strategy="direct_file", capability_id=direct.capability_id)
        item = coordinator.prepare_resource(FLOW_ID, resource(), resolution, now=NOW)
        self.assertEqual("direct_file", item["strategy"])

    def test_descriptor_without_catalog_strategy_is_not_executable(self) -> None:
        base = self.coordinator.select_descriptor("smartedu", resource_type="document")
        undeclared = replace(
            base,
            strategy=None,
            acquisition_strategies=("platform_resource",),
            descriptor_digest="c" * 64,
        )
        snapshot = replace(self.coordinator.registry_snapshot, descriptors=(undeclared,))
        coordinator = CapabilityCoordinator(registry_snapshot=snapshot, runtime_inventory=ready_inventory())
        resolution = primary_resolution(capability_id=undeclared.capability_id)
        with self.assertRaises(CapabilityAuthorityError) as raised:
            coordinator.prepare_resource(FLOW_ID, resource(), resolution, now=NOW)
        self.assertEqual("CAPABILITY_STRATEGY_REQUIRED", raised.exception.code)

    def test_cached_resolved_payload_is_flattened_with_outer_authority_fields(self) -> None:
        nested = primary_resolution(
            resolution_id="resolve_nested_000000000000",
            source_fingerprint="sha256:" + "c" * 64,
        )
        cached = {
            "resolved": nested,
            # Store-owned identity/status/fingerprint fields are authoritative
            # when they accompany the private nested payload.
            "resolution_id": RESOLUTION_ID,
            "resolution_status": "resolved",
            "source_fingerprint": SOURCE_DIGEST,
        }
        item = self.coordinator.prepare_resource(FLOW_ID, resource(), cached, now=NOW)
        self.assertEqual(RESOLUTION_ID, item["resolution_id"])
        self.assertEqual(RESOURCE_ID, item["resource_id"])
        self.assertEqual(REPRESENTATION_ID, item["representation_id"])
        self.assertEqual(SOURCE_DIGEST, item["source_fingerprint"])

    def test_registered_inspector_supported_scopes_are_exact_runtime_evidence(self) -> None:
        descriptor = self.coordinator.select_descriptor("smartedu", resource_type="document")
        inventory = ready_inventory()
        inventory.pop("inspector_versions")
        inventory.pop("inspector_scopes")
        inventory["registered_inspectors"] = {
            "smartedu": {
                "platform_id": "smartedu",
                "inspector_id": "smartedu",
                "version": "1.0.0",
                "supported_scopes": ("primary_resource",),
            }
        }
        readiness = self.coordinator.probe_readiness(descriptor, runtime_inventory=inventory, now=NOW)
        self.assertTrue(readiness.ready, readiness.to_dict())
        self.assertEqual("smartedu", readiness.inspector_id)
        self.assertEqual("1.0.0", readiness.inspector_version)

    def test_prepare_primary_binds_storage_digests_and_sanitizes_representation(self) -> None:
        item = self.coordinator.prepare_resource(
            FLOW_ID,
            resource(),
            primary_resolution(),
            preferred_container="pdf",
            now=NOW,
        )
        for field in (
            "descriptor_digest",
            "registry_digest",
            "readiness_digest",
            "eligibility_digest",
            "source_fingerprint",
        ):
            self.assertRegex(item[field], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(item["binding_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual("pdf", item["representation"].get("selected_container"))
        self.assertNotIn("source_url", item["representation"])
        self.assertNotIn("locator", item["representation"])

    def test_landing_representation_cannot_be_prepared_as_download(self) -> None:
        landing_resource = dict(resource(), platform="generic", resource_type="article")
        with self.assertRaises(CapabilityAuthorityError) as raised:
            self.coordinator.prepare_resource(
                FLOW_ID,
                landing_resource,
                landing_resolution(materializable=False),
                now=NOW,
            )
        self.assertEqual("ELIGIBILITY_REQUIRED", raised.exception.code)
        self.assertEqual("unsupported", raised.exception.details["eligibility"]["status"])
        self.assertIn(
            "CAPABILITY_REPRESENTATION_MISMATCH",
            raised.exception.details["eligibility"]["reason_codes"],
        )

    def test_landing_representation_binds_materialize_without_scope_upgrade(self) -> None:
        landing_resource = dict(resource(), platform="generic", resource_type="article")
        resolution = landing_resolution()
        descriptor = self.coordinator.select_descriptor(
            landing_resource,
            resource_type="article",
            scope="landing_page",
            strategy="web_materialize",
        )
        readiness = self.coordinator.probe_readiness(descriptor, now=NOW)
        decision = self.coordinator.evaluate_eligibility(
            FLOW_ID,
            landing_resource,
            resolution,
            descriptor,
            readiness,
            now=NOW,
        )
        self.assertEqual("materialize", decision.action)
        self.assertEqual("eligible", decision.status)

        item = self.coordinator.prepare_resource(
            FLOW_ID,
            landing_resource,
            resolution,
            now=NOW,
        )
        self.assertEqual("landing_page", item["capability_scope"])
        self.assertEqual("web_materialize", item["strategy"])
        self.assertEqual("generic-web-materializer", item["provider_id"])
        self.assertNotEqual("primary_resource", item["capability_scope"])

    def test_eligibility_is_independent_action_fact(self) -> None:
        descriptor = self.coordinator.select_descriptor(resource(), resource_type="document", scope="primary_resource")
        readiness = self.coordinator.probe_readiness(descriptor, now=NOW)
        decision = self.coordinator.evaluate_eligibility(
            FLOW_ID,
            resource(),
            primary_resolution(),
            descriptor,
            readiness,
            now=NOW,
        )
        self.assertEqual("download", decision.action)
        self.assertEqual("eligible", decision.status)
        self.assertEqual(SOURCE_DIGEST, decision.source_fingerprint)
        self.assertRegex(decision.to_dict()["decision_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_revalidation_accepts_same_authority_chain_with_flow_context(self) -> None:
        item = self.coordinator.prepare_resource(FLOW_ID, resource(), primary_resolution(), now=NOW)
        result = self.coordinator.revalidate_plan_item(item, resource(), primary_resolution(), flow_id=FLOW_ID, now=NOW)
        self.assertTrue(result.ok, result.to_dict())

    def test_revalidation_rejects_provider_drift(self) -> None:
        item = self.coordinator.prepare_resource(FLOW_ID, resource(), primary_resolution(), now=NOW)
        changed = CapabilityCoordinator(
            runtime_inventory={
                **ready_inventory(),
                "provider_versions": {
                    "smartedu-resource": "1.0.0",
                    "generic-direct": "1.0.0",
            "generic-web-materializer": "1.0.0",
                },
            }
        )
        altered = dict(item)
        altered["provider_id"] = "other-provider"
        result = changed.revalidate_plan_item(altered, resource(), primary_resolution(), flow_id=FLOW_ID, now=NOW)
        self.assertFalse(result.ok)
        self.assertEqual("PROVIDER_DRIFT", result.code)

    def test_revalidation_rejects_registry_drift(self) -> None:
        item = self.coordinator.prepare_resource(FLOW_ID, resource(), primary_resolution(), now=NOW)
        snapshot = self.coordinator.registry_snapshot
        changed_snapshot = replace(snapshot, registry_digest="a" * 64)
        changed = CapabilityCoordinator(
            registry_snapshot=changed_snapshot,
            runtime_inventory=ready_inventory(),
        )
        result = changed.revalidate_plan_item(item, resource(), primary_resolution(), flow_id=FLOW_ID, now=NOW)
        self.assertFalse(result.ok)
        self.assertEqual("CAPABILITY_REGISTRY_DRIFT", result.code)

    def test_fallback_requires_explicit_same_provider_scope_and_strategy(self) -> None:
        primary = self.coordinator.select_descriptor("smartedu", resource_type="document")
        generic = self.coordinator.select_descriptor(
            "generic", resource_type="document", scope="primary_resource", strategy="direct_file"
        )
        self.assertFalse(self.coordinator.allow_safe_fallback(primary, generic))
        self.assertFalse(self.coordinator.allow_safe_fallback(generic, primary))
        self.assertFalse(self.coordinator.allow_safe_fallback(primary, primary))

    def test_persist_readiness_uses_storage_canonical_digest_shape(self) -> None:
        descriptor = self.coordinator.select_descriptor("smartedu", resource_type="document")
        readiness = self.coordinator.probe_readiness(descriptor, now=NOW)
        persisted = self.coordinator.persist_readiness(readiness)
        self.assertRegex(persisted["snapshot_digest"], r"^sha256:[0-9a-f]{64}$")
        material = dict(persisted)
        material.pop("snapshot_digest")
        self.assertEqual(Store._canonical_authority_digest(material), persisted["snapshot_digest"])



if __name__ == "__main__":
    unittest.main()
