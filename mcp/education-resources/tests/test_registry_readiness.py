from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys
import unittest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.retrieval.registry import (  # noqa: E402
    CapabilityDescriptor,
    PlatformRegistryError,
    build_registry_snapshot,
    canonical_descriptor_digest,
    load_registry_snapshot,
    probe_runtime_readiness,
    revalidate_readiness,
)


CATALOG = SERVICE_ROOT / "contracts" / "capabilities" / "capability-descriptors.json"
CATALOG_SCHEMA = SERVICE_ROOT / "contracts" / "schemas" / "capability-descriptors.schema.json"
EXPECTED_REGISTRY_DIGEST = "c54c64a024174f0b96c4bddf14c153d2a12a93de9e29344c8a76ff7ae10dbae5"
EXPECTED_CAPABILITIES = {
    "cap_generic_document_primary_direct_v1": {
        "platform_id": "generic",
        "provider_id": "generic-direct",
        "provider_version": "1.0.0",
        "scope": "primary_resource",
        "strategy": "direct_file",
        "descriptor_digest": "a30ba16bf1b70ef81cc9f31003a122d0607eb3094a92de2b3fa864725f5c2421",
    },
    "cap_generic_webpage_landing_materialize_v1": {
        "platform_id": "generic",
        "provider_id": "generic-web-materializer",
        "provider_version": "1.0.0",
        "scope": "landing_page",
        "strategy": "web_materialize",
        "descriptor_digest": "50f8d3f8ede4e260110bcb148ca2abb8dd75f87e95c1be328f85a4a5c0e0cfff",
    },
    "cap_smartedu_document_primary_direct_v1": {
        "platform_id": "smartedu",
        "provider_id": "smartedu-resource",
        "provider_version": "1.0.0",
        "scope": "primary_resource",
        "strategy": "direct_file",
        "descriptor_digest": "b847a01769bf6afeec3228b6853e1cb502e4062ae19010db7fcc225b733344de",
    },
}


def descriptor_by_id(snapshot, descriptor_id: str) -> CapabilityDescriptor:
    matches = tuple(item for item in snapshot.descriptors if item.descriptor_id == descriptor_id)
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one descriptor for {descriptor_id!r}, got {len(matches)}")
    return matches[0]


class RegistryReadinessTests(unittest.TestCase):
    def test_legacy_platform_registry_is_readable_but_never_ready(self) -> None:
        snapshot = load_registry_snapshot()
        descriptor = snapshot.descriptors[0]
        self.assertTrue(descriptor.legacy_descriptor)
        readiness = probe_runtime_readiness(
            descriptor,
            snapshot=snapshot,
            provider_versions={},
            inspector_versions={},
            auth_ready=True,
            policy_allowed=True,
            now="2026-08-08T00:00:00Z",
        )
        self.assertEqual("legacy", readiness.status)
        self.assertFalse(readiness.ready)
        self.assertIsNone(readiness.provider_id)
        self.assertTrue(readiness.snapshot_id.startswith("ready_"))

    def test_catalog_round_trip_and_descriptor_id_resolution(self) -> None:
        snapshot = load_registry_snapshot(CATALOG, schema_path=CATALOG_SCHEMA)
        self.assertEqual("1.1.0", snapshot.registry_version)
        self.assertEqual(EXPECTED_REGISTRY_DIGEST, snapshot.registry_digest)
        self.assertEqual(tuple(EXPECTED_CAPABILITIES), tuple(item.descriptor_id for item in snapshot.descriptors))

        for descriptor_id, expected in EXPECTED_CAPABILITIES.items():
            with self.subTest(descriptor_id=descriptor_id):
                descriptor = descriptor_by_id(snapshot, descriptor_id)
                self.assertEqual("1.1.0", descriptor.descriptor_version)
                self.assertEqual("1.1.0", descriptor.registry_version)
                self.assertEqual(expected["platform_id"], descriptor.platform_id)
                self.assertEqual(expected["provider_id"], descriptor.provider_id)
                self.assertEqual(expected["provider_version"], descriptor.provider_version)
                self.assertEqual((expected["scope"],), descriptor.capability_scope)
                self.assertEqual((expected["scope"],), descriptor.provider_scope)
                self.assertEqual(expected["strategy"], descriptor.strategy)
                self.assertEqual(expected["descriptor_digest"], descriptor.descriptor_digest)
                self.assertEqual((), tuple(descriptor.fallback.get("allowed_scopes", ())))
                self.assertFalse(descriptor.fallback["allowed"])

                loaded = snapshot.descriptor_for(
                    descriptor.platform_id,
                    scope=expected["scope"],
                    strategy=expected["strategy"],
                )
                self.assertEqual(descriptor_id, loaded.descriptor_id)
                readiness = probe_runtime_readiness(
                    descriptor_id,
                    snapshot=snapshot,
                    provider_versions={descriptor.provider_id: descriptor.provider_version},
                    inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
                    provider_scopes={descriptor.provider_id: (expected["scope"],)},
                    inspector_scopes={descriptor.inspector_id: (expected["scope"],)},
                    auth_ready=True,
                    policy_allowed=True,
                    now="2026-08-08T00:00:00Z",
                )
                self.assertEqual(expected["scope"], readiness.capability_scope)
                self.assertEqual(expected["strategy"], readiness.strategy)
                self.assertEqual(expected["provider_id"], readiness.provider_id)
                self.assertEqual(expected["provider_version"], readiness.provider_version)
                self.assertEqual(EXPECTED_REGISTRY_DIGEST, readiness.registry_digest)
                self.assertEqual("1.1.0", readiness.registry_version)
                self.assertEqual((), readiness.fallback_capability_ids)
                self.assertTrue(readiness.ready)

    def test_sha256_prefix_is_normalized_and_key_order_digest_is_stable(self) -> None:
        snapshot = load_registry_snapshot(CATALOG, schema_path=CATALOG_SCHEMA)
        descriptor = descriptor_by_id(snapshot, "cap_generic_document_primary_direct_v1")
        self.assertEqual("sha256:" + descriptor.descriptor_digest, descriptor.descriptor_digest_sha256)
        raw = json.loads(CATALOG.read_text(encoding="utf-8"))["descriptors"][0]
        reordered = {key: raw[key] for key in reversed(list(raw))}
        self.assertEqual(canonical_descriptor_digest(raw), canonical_descriptor_digest(reordered))
        readiness = probe_runtime_readiness(
            descriptor,
            snapshot=snapshot,
            provider_versions={descriptor.provider_id: descriptor.provider_version},
            inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
            auth_ready=True,
            policy_allowed=True,
            now="2026-08-08T00:00:00Z",
        )
        self.assertEqual(readiness.snapshot_digest_sha256, "sha256:" + readiness.snapshot_digest)
        self.assertEqual(readiness.to_dict()["snapshot_digest"], readiness.snapshot_digest)

    def test_missing_dependencies_and_scope_version_failures_are_structured(self) -> None:
        snapshot = load_registry_snapshot(CATALOG, schema_path=CATALOG_SCHEMA)
        descriptor = descriptor_by_id(snapshot, "cap_generic_webpage_landing_materialize_v1")
        missing = probe_runtime_readiness(descriptor, snapshot=snapshot, now="2026-08-08T00:00:00Z")
        self.assertEqual("missing_provider", missing.status)
        self.assertFalse(missing.ready)
        bad_import = probe_runtime_readiness(
            descriptor,
            snapshot=snapshot,
            provider_import_errors={descriptor.provider_id: "boom"},
            now="2026-08-08T00:00:00Z",
        )
        self.assertEqual("import_failed", bad_import.status)
        mismatch = probe_runtime_readiness(
            descriptor,
            snapshot=snapshot,
            provider_versions={descriptor.provider_id: "9.9.9"},
            inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
            now="2026-08-08T00:00:00Z",
        )
        self.assertEqual("version_mismatch", mismatch.status)
        scope = probe_runtime_readiness(
            descriptor,
            snapshot=snapshot,
            provider_versions={descriptor.provider_id: descriptor.provider_version},
            provider_scopes={descriptor.provider_id: ("metadata",)},
            inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
            now="2026-08-08T00:00:00Z",
        )
        self.assertEqual("scope_mismatch", scope.status)

    def test_empty_inspector_scope_uses_capability_scope_not_literal_inspect(self) -> None:
        snapshot = load_registry_snapshot(CATALOG, schema_path=CATALOG_SCHEMA)
        descriptor = descriptor_by_id(snapshot, "cap_generic_webpage_landing_materialize_v1")
        descriptor = replace(descriptor, inspector_scope=())
        readiness = probe_runtime_readiness(
            descriptor,
            snapshot=replace(snapshot, descriptors=(descriptor,)),
            provider_versions={descriptor.provider_id: descriptor.provider_version},
            inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
            provider_scopes={descriptor.provider_id: ("landing_page",)},
            inspector_scopes={descriptor.inspector_id: ("landing_page",)},
            auth_ready=True,
            policy_allowed=True,
            now="2026-08-08T00:00:00Z",
        )
        self.assertTrue(readiness.ready, readiness.to_dict())

    def test_readiness_ttl_and_descriptor_change_recompute_snapshot_digest(self) -> None:
        snapshot = load_registry_snapshot(CATALOG, schema_path=CATALOG_SCHEMA)
        descriptor = descriptor_by_id(snapshot, "cap_smartedu_document_primary_direct_v1")
        readiness = probe_runtime_readiness(
            descriptor,
            snapshot=snapshot,
            provider_versions={descriptor.provider_id: descriptor.provider_version},
            inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
            now="2026-08-08T00:00:00Z",
            ttl_seconds=1,
        )
        expired = revalidate_readiness(readiness, now="2026-08-08T00:00:01Z")
        self.assertEqual("expired", expired.status)
        self.assertNotEqual(readiness.snapshot_digest, expired.snapshot_digest)

        changed = CapabilityDescriptor(
            **{
                **descriptor.to_dict(),
                "descriptor_digest": "a" * 64,
            }
        )
        stale = revalidate_readiness(readiness, descriptor=changed, now="2026-08-08T00:00:00Z")
        self.assertEqual("descriptor_changed", stale.status)
        self.assertNotEqual(readiness.snapshot_digest, stale.snapshot_digest)

    def test_catalog_metadata_is_immutable(self) -> None:
        snapshot = load_registry_snapshot(CATALOG, schema_path=CATALOG_SCHEMA)
        descriptor = descriptor_by_id(snapshot, "cap_smartedu_document_primary_direct_v1")
        with self.assertRaises(TypeError):
            descriptor.prerequisites["auth_mode"] = "required"  # type: ignore[index]
        with self.assertRaises(PlatformRegistryError):
            probe_runtime_readiness(
                descriptor,
                snapshot=snapshot,
                provider_versions={descriptor.provider_id: descriptor.provider_version},
                inspector_versions={descriptor.inspector_id: descriptor.inspector_version},
                load_status="broken",
            )


if __name__ == "__main__":
    unittest.main()
