from __future__ import annotations

from dataclasses import FrozenInstanceError
import copy
from pathlib import Path
import unittest

from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import (
    INSPECTION_PROFILE_VERSION,
    INSPECTOR_VERSION,
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
    build_representation_authority,
    representation_evidence_is_fresh,
    resolution_evidence_is_fresh,
    source_fingerprint,
)


def valid_resource(*, platform: str = "bilibili") -> dict:
    return {
        "platform": platform,
        "title": "太阳系入门",
        "source_url": "https://example.com/resource?id=1",
        "resource_type": "article",
        "metadata": {"isbn": "9780306406157", "edition": "1"},
    }


def valid_resolved_resource(*, representations: list[dict] | None = None) -> dict:
    return {
        "title": "太阳系入门",
        "resource_type": "article",
        "availability": {"status": "available"},
        "representations": representations or [{"kind": "webpage"}],
        "metadata": {"edition": "1"},
    }


def valid_result(**kwargs) -> InspectionResult:
    payload = {
        "resolution_status": "partial",
        "resolved_resource": valid_resolved_resource(),
        "inspection": build_default_inspection("test.inspector"),
        "failures": [],
    }
    payload.update(kwargs)
    return InspectionResult(**payload)


class _StubInspector:
    supported_scopes = ("landing_page", "metadata")

    def __init__(self, platform_id: str, result: InspectionResult | None = None) -> None:
        self.platform_id = platform_id
        self.inspector_id = f"{platform_id}.inspector"
        self.version = INSPECTOR_VERSION
        self.result = result or valid_result()
        self.calls = 0

    def inspect(self, resource):
        self.calls += 1
        return self.result


class InspectionCoreTests(unittest.TestCase):
    def test_constants_and_frozen_defensive_copy(self) -> None:
        self.assertEqual("inspect-v1", INSPECTION_PROFILE_VERSION)
        self.assertEqual("1.0.0", INSPECTOR_VERSION)

        resource = valid_resolved_resource()
        inspection = build_default_inspection("test.inspector")
        result = InspectionResult("resolved", resource, inspection, [])
        with self.assertRaises(FrozenInstanceError):
            result.resolution_status = "partial"  # type: ignore[misc]

        resource["metadata"]["edition"] = "changed"
        first = result.to_mapping()
        first["resolved_resource"]["metadata"]["edition"] = "mutated"
        first["resolved_resource"]["representations"].append({"kind": "audio"})
        second = result.to_mapping()
        self.assertEqual("1", second["resolved_resource"]["metadata"]["edition"])
        self.assertEqual(1, len(second["resolved_resource"]["representations"]))
        self.assertEqual("resolved", second["resolution_status"])

    def test_source_fingerprint_is_stable_and_changes_for_identity_fields(self) -> None:
        first = valid_resource()
        reordered = copy.deepcopy(first)
        reordered["metadata"] = {"edition": "1", "isbn": "9780306406157"}
        self.assertEqual(source_fingerprint(first), source_fingerprint(reordered))

        for field, changed in (
            ("source_url", "https://example.com/resource?id=2"),
            ("title", "太阳系进阶"),
            ("platform", "zhihu"),
            ("resource_type", "video"),
        ):
            candidate = copy.deepcopy(first)
            candidate[field] = changed
            with self.subTest(field=field):
                self.assertNotEqual(source_fingerprint(first), source_fingerprint(candidate))

        identity_changed = copy.deepcopy(first)
        identity_changed["metadata"]["edition"] = "2"
        self.assertNotEqual(source_fingerprint(first), source_fingerprint(identity_changed))

        volatile_changed = copy.deepcopy(first)
        volatile_changed["metadata"]["crawl_timestamp"] = "later"
        self.assertEqual(source_fingerprint(first), source_fingerprint(volatile_changed))

    def test_authority_uses_canonical_fingerprint_and_validates_role_and_timestamps(self) -> None:
        resource = valid_resource()
        authority = build_representation_authority(
            resource,
            scope="representation",
            role="companion",
            technical_availability="unknown",
            observed_at="2026-08-08T00:00:00Z",
            expires_at="2026-08-08T01:00:00Z",
        )
        self.assertRegex(source_fingerprint(resource), r"^[a-f0-9]{64}$")
        self.assertRegex(
            authority["evidence"]["source_fingerprint"],
            r"^sha256:[a-f0-9]{64}$",
        )
        self.assertEqual("2026-08-08T00:00:00Z", authority["evidence"]["observed_at"])
        self.assertEqual("2026-08-08T01:00:00Z", authority["evidence"]["expires_at"])

        with self.assertRaises(DomainError):
            build_representation_authority(
                resource,
                scope="representation",
                role="representation",
                technical_availability="unknown",
            )
        with self.assertRaises(DomainError):
            build_representation_authority(
                resource,
                scope="representation",
                role="companion",
                technical_availability="unknown",
                observed_at="not-a-timestamp",
            )

    def test_representation_evidence_freshness_uses_half_open_expiry_boundary(self) -> None:
        authority = build_representation_authority(
            valid_resource(),
            scope="landing_page",
            role="landing",
            technical_availability="available",
            observed_at="2026-08-08T00:00:00Z",
            expires_at="2026-08-08T01:00:00Z",
        )
        self.assertTrue(
            representation_evidence_is_fresh(
                authority, now="2026-08-08T00:30:00Z"
            )
        )
        self.assertFalse(
            representation_evidence_is_fresh(
                authority, now="2026-08-08T01:00:00Z"
            )
        )
        self.assertFalse(
            representation_evidence_is_fresh(
                authority, now="2026-08-07T23:59:59Z"
            )
        )
        self.assertFalse(
            representation_evidence_is_fresh(
                {"evidence": {"observed_at": "invalid", "expires_at": "invalid"}},
                now="2026-08-08T00:30:00Z",
            )
        )
        self.assertTrue(
            representation_evidence_is_fresh(
                {"kind": "webpage"}, now="2026-08-08T00:30:00Z"
            )
        )

        expired = copy.deepcopy(authority)
        expired["evidence"]["expires_at"] = "2026-08-08T00:15:00Z"
        self.assertFalse(
            resolution_evidence_is_fresh(
                {"representations": [authority, expired]},
                now="2026-08-08T00:30:00Z",
            )
        )
    def test_router_uses_exact_platform_and_has_no_generic_fallback(self) -> None:
        generic = _StubInspector("generic")
        bilibili = _StubInspector("bilibili")
        router = InspectionRouter([generic, bilibili])

        self.assertIs(router.inspect({"platform": "bilibili"}), bilibili.result)
        self.assertEqual(1, bilibili.calls)
        with self.assertRaises(DomainError) as unsupported:
            router.inspect({"platform": "zhihu"})
        self.assertEqual("FEATURE_NOT_SUPPORTED", unsupported.exception.code)
        with self.assertRaises(DomainError) as unknown:
            router.inspect({"platform": "unknown-platform"})
        self.assertEqual("FEATURE_NOT_SUPPORTED", unknown.exception.code)
        with self.assertRaises(DomainError) as missing:
            router.inspect({})
        self.assertEqual("FEATURE_NOT_SUPPORTED", missing.exception.code)

    def test_router_rejects_duplicate_registration(self) -> None:
        router = InspectionRouter([_StubInspector("bilibili")])
        with self.assertRaises(DomainError) as duplicate:
            router.register(_StubInspector("bilibili"))
        self.assertEqual("INVALID_ARGUMENT", duplicate.exception.code)

    def test_recursive_sensitive_values_and_non_json_objects_are_rejected(self) -> None:
        cases = [
            {"metadata": {"url": "https://example.com/private"}},
            {"metadata": {"safe_note": "file:///tmp/private.pdf"}},
            {"metadata": {"safe_note": "/tmp/private.pdf"}},
            {"metadata": {"safe_note": Path("/tmp/private.pdf")}},
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                resource = valid_resolved_resource()
                resource.update(metadata)
                with self.assertRaises(DomainError):
                    valid_result(resolved_resource=resource)

        resource = valid_resolved_resource()
        resource["metadata"] = {"safe_note": b"secret"}
        with self.assertRaises(DomainError):
            valid_result(resolved_resource=resource)

    def test_representation_warning_failure_and_metadata_limits(self) -> None:
        with self.assertRaises(DomainError):
            valid_result(
                resolved_resource=valid_resolved_resource(
                    representations=[{"kind": "webpage"}] * 33
                )
            )
        with self.assertRaises(DomainError):
            valid_result(
                inspection=build_default_inspection(
                    "test.inspector", warnings=["warning"] * 33
                )
            )
        with self.assertRaises(DomainError):
            valid_result(
                failures=[
                    {"code": "PARTIAL_FAILURE", "message": "failed", "retriable": True}
                ]
                * 33
            )
        too_many_metadata = {f"key_{index}": True for index in range(33)}
        resource = valid_resolved_resource()
        resource["metadata"] = too_many_metadata
        with self.assertRaises(DomainError):
            valid_result(resolved_resource=resource)

    def test_invalid_resolution_and_availability_statuses_are_rejected(self) -> None:
        with self.assertRaises(DomainError):
            valid_result(resolution_status="pending")
        resource = valid_resolved_resource()
        resource["availability"] = {"status": "maybe"}
        with self.assertRaises(DomainError):
            valid_result(resolved_resource=resource)


if __name__ == "__main__":
    unittest.main()
