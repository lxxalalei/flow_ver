from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from education_resource_mcp.adapters.inspect_annas_archive import AnnasArchiveInspector
from education_resource_mcp.adapters.inspect_generic import GenericWebInspector
from education_resource_mcp.adapters.inspect_nlc import NlcInspector
from education_resource_mcp.inspection import source_fingerprint
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
            "inspector_id": "generic",
            "version": "1.0.0",
            "method": "bounded_get",
            "cache_status": "miss",
            "inspected_at": "2026-08-08T00:00:00Z",
            "warnings": [],
        },
        "failures": [],
    }


class _ResolutionResponse:
    def __init__(self, url: str) -> None:
        self.status = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self._body = "<html lang='zh'><head><title>公开资源</title></head><body>detail</body></html>".encode("utf-8")
        self._offset = 0
        self._url = url
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True


class _ResolutionTransport:
    def __init__(self, url: str) -> None:
        self.url = url
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        return _ResolutionResponse(self.url)


def _public_resolver(hostname: str, port: int):
    return ("93.184.216.34",)


def _resolution_resource(platform: str, source_url: str, **metadata) -> dict:
    return {
        "resource_id": "res_" + "a" * 16,
        "platform": platform,
        "title": "公开教育资源",
        "source_url": source_url,
        "resource_type": "other",
        "metadata": metadata,
    }


def _resolution_envelope(resource: dict, result: object) -> dict:
    """Project one real inspector result into the Resolution contract envelope."""

    mapped = result.to_mapping()  # type: ignore[attr-defined]
    resolved = mapped["resolved_resource"]
    inspection = mapped["inspection"]
    representations = resolved["representations"]
    evidence = representations[0]["evidence"] if representations else None
    observed_at = evidence["observed_at"] if evidence else inspection["inspected_at"]
    expires_at = evidence["expires_at"] if evidence else observed_at
    failures = [
        {
            key: failure[key]
            for key in ("code", "message", "retriable")
            if key in failure
        }
        for failure in mapped["failures"]
    ]
    return {
        "contract_version": "1.0.0",
        "resource_id": resource["resource_id"],
        "resolution_id": "resolve_" + "a" * 16,
        "resolution_version": 1,
        "resolution_status": mapped["resolution_status"],
        "source_fingerprint": "sha256:" + source_fingerprint(resource),
        "inspector": {
            "inspector_id": inspection["inspector_id"],
            "version": inspection["version"],
        },
        "observed_at": observed_at,
        "expires_at": expires_at,
        "availability": resolved["availability"],
        "representations": representations,
        "failures": failures,
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

    def assert_valid_resolution(self, instance: dict) -> None:
        schema = load_json(CONTRACTS_ROOT / "schemas" / "resolution.schema.json")
        validator = Draft202012Validator(
            schema,
            registry=build_registry(),
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
        self.assertEqual([], errors, instance)

    def test_real_generic_nlc_and_annas_inspectors_match_resolution_contract(self) -> None:
        cases = (
            (
                GenericWebInspector,
                _resolution_resource("generic", "https://public.test/resource"),
                "https://public.test/resource",
            ),
            (
                NlcInspector,
                _resolution_resource(
                    "nlc",
                    "https://www.nlc.cn/catalog/42",
                    isbn="9780306406157",
                    author="国家图书馆编",
                ),
                "https://www.nlc.cn/catalog/42",
            ),
            (
                AnnasArchiveInspector,
                _resolution_resource(
                    "annas-archive",
                    "https://libgen.test/book/1",
                    md5="0123456789abcdef0123456789abcdef",
                    extension="pdf",
                ),
                "https://libgen.test/book/1",
            ),
        )

        for inspector_class, resource, final_url in cases:
            with self.subTest(platform=resource["platform"]):
                result = inspector_class(
                    resolver=_public_resolver,
                    transport=_ResolutionTransport(final_url),
                    timeout=0.25,
                ).inspect(resource)
                envelope = _resolution_envelope(resource, result)
                self.assert_valid_resolution(envelope)
                self.assertEqual(
                    "sha256:" + source_fingerprint(resource),
                    envelope["source_fingerprint"],
                )
                for representation in envelope["representations"]:
                    self.assertNotIn("estimated_size_bytes", representation)
                    self.assertNotIn("requires_auth", representation)
                    self.assertRegex(
                        representation["evidence"]["source_fingerprint"],
                        r"^sha256:[a-f0-9]{64}$",
                    )


if __name__ == "__main__":
    unittest.main()
