from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SCHEMA_PATH = CONTRACTS_ROOT / "schemas" / "tools" / "resource_inspect.schema.json"


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


def valid_input() -> dict:
    return {
        "contract_version": "1.0.0",
        "flow_id": "flow_1234567890abcdef",
        "resource_id": "res_1234567890abcdef",
        "idempotency_key": "inspect-contract-001",
    }


def valid_success() -> dict:
    return {
        "contract_version": "1.0.0",
        "ok": True,
        "flow_id": "flow_1234567890abcdef",
        "resource_id": "res_1234567890abcdef",
        "resolution_id": "resolve_1234567890abcdef",
        "resolution_status": "partial",
        "resolved_resource": {
            "title": "恐龙入门",
            "resource_type": "article",
            "availability": {"status": "unknown"},
            "representations": [
                {
                    "representation_id": "repr_1234567890abcdef",
                    "kind": "webpage",
                    "role": "primary",
                    "materializable": False,
                    "requires_auth": False,
                }
            ],
            "metadata": {},
        },
        "inspection": {
            "inspector_id": "generic_web",
            "version": "1.0.0",
            "method": "bounded_get",
            "cache_status": "miss",
            "inspected_at": "2026-08-08T00:00:00Z",
            "warnings": [],
        },
        "failures": [],
    }


class ResourceInspectContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(
            cls.schema,
            registry=build_registry(),
            format_checker=FormatChecker(),
        )

    def assert_valid(self, instance: dict) -> None:
        errors = list(self.validator.iter_errors(instance))
        self.assertEqual([], errors)

    def assert_invalid(self, instance: dict) -> None:
        self.assertFalse(self.validator.is_valid(instance), instance)

    def test_input_accepts_only_the_four_frozen_fields(self) -> None:
        self.assert_valid(valid_input())

    def test_input_rejects_url_batch_depth_and_extra_fields(self) -> None:
        forbidden = {
            "url": "https://example.com/resource",
            "result_set_id": "rset_1234567890abcdef",
            "resource_ids": ["res_1234567890abcdef"],
            "inspection_depth": "standard",
            "unexpected": "not accepted",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                instance = valid_input()
                instance[field] = value
                self.assert_invalid(instance)

    def test_success_output_is_bounded_and_accepts_required_shapes(self) -> None:
        self.assert_valid(valid_success())

    def test_availability_rejects_url_and_representation_rejects_locator_fields(
        self,
    ) -> None:
        availability_url = copy.deepcopy(valid_success())
        availability_url["resolved_resource"]["availability"]["url"] = (
            "https://example.com/resource"
        )
        self.assert_invalid(availability_url)

        for field, value in {
            "locator": "https://example.com/resource",
            "path": "/tmp/resource.pdf",
        }.items():
            with self.subTest(field=field):
                locator = copy.deepcopy(valid_success())
                locator["resolved_resource"]["representations"][0][field] = value
                self.assert_invalid(locator)


if __name__ == "__main__":
    unittest.main()
