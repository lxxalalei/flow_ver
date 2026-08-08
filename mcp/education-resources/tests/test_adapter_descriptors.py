"""Tests for immutable adapter descriptors and legacy adapter helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
import unittest

from education_resource_mcp.adapters.base import (
    AdapterDescriptor,
    AdapterDescriptorError,
    PlatformSearchAdapter,
    adapter_error,
    descriptor_for_platform,
    make_resource,
)


def _entry() -> dict:
    return {
        "platform_id": "demo",
        "display_name": "Demo platform",
        "resource_types": ["article", "video"],
        "capabilities": {
            "search": True,
            "browse_creator": False,
            "inspect": False,
            "acquire": True,
        },
        "auth_mode": "optional",
        "auth_kind": "cookie",
        "source_traits": ["web", "reference"],
        "search": {
            "enabled": True,
            "recommended_limit": 10,
            "query_execution": "serial",
        },
        "inspection": {"supported": False},
        "acquisition": {"strategies": ["webpage"]},
        "identity_profile": {
            "native_id_fields": ["demo_id"],
            "strong_identity_sources": ["native_id", "isbn", "doi", "canonical_url"],
            "weak_identity_fields": ["title", "creator", "edition"],
            "canonical_url": {
                "remove_fragment": True,
                "removable_query_parameters": ["utm_source"],
            },
        },
    }


def _descriptor(**overrides: object) -> AdapterDescriptor:
    values = {
        "platform_id": "demo",
        "resource_types": ["article", "video"],
        "capabilities": {"search": True, "acquire": False},
        "identity_profile": {"native_id_fields": ["demo_id"]},
        "acquisition_strategies": ["webpage"],
        "auth_mode": "none",
        "auth_kind": "none",
        "source_traits": ["web"],
    }
    values.update(overrides)
    return AdapterDescriptor(**values)


class AdapterDescriptorTests(unittest.TestCase):
    def test_registry_entry_is_converted_to_recursive_immutable_values(self) -> None:
        # This is a registry-entry-shaped fixture representing the output of
        # the already-validated registry loader.  Loading the entire active
        # registry belongs to registry tests and would couple this base
        # interface test to unrelated platform facts.
        entry = _entry()
        descriptor = AdapterDescriptor.from_registry_entry(entry)

        self.assertEqual(descriptor.platform_id, "demo")
        self.assertEqual(descriptor.resource_types, tuple(entry["resource_types"]))
        self.assertEqual(descriptor.acquisition_strategies, ("webpage",))
        self.assertIsInstance(descriptor.capabilities, Mapping)
        self.assertIsInstance(descriptor.identity_profile, Mapping)
        self.assertIsInstance(descriptor.identity_profile["canonical_url"], Mapping)
        self.assertIsInstance(descriptor.identity_profile["canonical_url"]["removable_query_parameters"], tuple)

        entry["resource_types"].append("mutated")
        entry["identity_profile"]["canonical_url"]["removable_query_parameters"].append("mutated")
        self.assertNotIn("mutated", descriptor.resource_types)
        self.assertNotIn(
            "mutated",
            descriptor.identity_profile["canonical_url"]["removable_query_parameters"],
        )

    def test_constructor_converts_sequences_and_mappings(self) -> None:
        descriptor = _descriptor(
            capabilities={"search": True, "acquire": False},
            identity_profile={
                "fields": ["isbn"],
                "canonical_url": {"remove_fragment": True, "options": {"strict": False}},
            },
        )

        self.assertEqual(descriptor.resource_types, ("article", "video"))
        self.assertEqual(descriptor.source_traits, ("web",))
        self.assertEqual(descriptor.identity_profile["fields"], ("isbn",))
        self.assertEqual(descriptor.identity_profile["canonical_url"]["options"]["strict"], False)
        self.assertEqual(hash(descriptor), hash(descriptor))

    def test_descriptor_and_nested_values_are_immutable(self) -> None:
        descriptor = _descriptor(
            capabilities={"search": True},
            identity_profile={"canonical_url": {"remove_fragment": True}},
        )

        with self.assertRaises(FrozenInstanceError):
            descriptor.platform_id = "other"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            descriptor.resource_types += ("book",)  # type: ignore[misc]
        with self.assertRaises(TypeError):
            descriptor.capabilities["search"] = False  # type: ignore[index]
        with self.assertRaises(TypeError):
            descriptor.identity_profile["canonical_url"]["remove_fragment"] = False  # type: ignore[index]

    def test_invalid_direct_values_raise_descriptor_error(self) -> None:
        invalid_values = (
            {"platform_id": "",},
            {"resource_types": []},
            {"resource_types": ["article", "article"]},
            {"capabilities": {"search": 1}},
            {"identity_profile": []},
            {"acquisition_strategies": "webpage"},
            {"source_traits": ["web", "web"]},
        )
        for overrides in invalid_values:
            with self.subTest(overrides=overrides):
                with self.assertRaises(AdapterDescriptorError):
                    _descriptor(**overrides)

    def test_invalid_registry_entry_shape_is_reported(self) -> None:
        with self.assertRaises(AdapterDescriptorError):
            AdapterDescriptor.from_registry_entry({"platform_id": "demo"})

        malformed = _entry()
        malformed["acquisition"] = {"strategies": "webpage"}
        with self.assertRaises(AdapterDescriptorError):
            AdapterDescriptor.from_registry_entry(malformed)

        malformed = _entry()
        malformed["acquisition"] = []
        with self.assertRaises(AdapterDescriptorError):
            AdapterDescriptor.from_registry_entry(malformed)

    def test_protocol_declares_descriptor_without_runtime_requirement_for_legacy_stub(self) -> None:
        class LegacyStub:
            platform_id = "legacy"

            def search(self, query: str, limit: int) -> tuple[list[dict], dict | None]:
                return [], None

        legacy = LegacyStub()
        self.assertFalse(hasattr(legacy, "descriptor"))
        self.assertEqual(legacy.platform_id, "legacy")
        self.assertIn("descriptor", PlatformSearchAdapter.__annotations__)
        self.assertEqual(legacy.search("query", 1), ([], None))

    def test_active_registry_descriptor_lookup_is_cached_and_strict(self) -> None:
        first = descriptor_for_platform("bilibili")
        second = descriptor_for_platform("bilibili")

        self.assertIs(first, second)
        self.assertEqual(first.platform_id, "bilibili")
        self.assertTrue(first.capabilities["browse_creator"])
        self.assertIn("platform_video", first.acquisition_strategies)
        with self.assertRaises(AdapterDescriptorError):
            descriptor_for_platform("not-registered")


class AdapterHelperRegressionTests(unittest.TestCase):
    def test_make_resource_minimal_shape_is_unchanged(self) -> None:
        resource = make_resource(
            platform="demo",
            title="A title",
            source_url="https://example.com/resource",
        )
        self.assertEqual(resource["platform"], "demo")
        self.assertEqual(resource["title"], "A title")
        self.assertEqual(resource["resource_type"], "其他")
        self.assertIsNone(resource["summary"])
        self.assertEqual(resource["metadata"], {"platform_signals": {}})

    def test_make_resource_full_metadata_and_adapter_error_are_unchanged(self) -> None:
        resource = make_resource(
            platform="demo",
            title="A title",
            source_url="https://example.com/resource",
            resource_type="视频",
            summary="Summary",
            author="Author",
            published_at="2024-01-01",
            language="zh",
            download_feasibility="中",
            platform_signals={"views": 10},
        )
        self.assertEqual(resource["metadata"]["author"], "Author")
        self.assertEqual(resource["metadata"]["published_at"], "2024-01-01")
        self.assertEqual(resource["metadata"]["language"], "zh")
        self.assertEqual(resource["metadata"]["download_feasibility"], "中")
        self.assertEqual(resource["metadata"]["platform_signals"], {"views": 10})
        self.assertEqual(
            adapter_error("PARTIAL_FAILURE", "temporary failure", True),
            {"code": "PARTIAL_FAILURE", "message": "temporary failure", "retryable": True},
        )


if __name__ == "__main__":
    unittest.main()
