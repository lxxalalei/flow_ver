from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SCHEMA_ROOT = CONTRACTS_ROOT / "schemas"
CATALOG_PATH = CONTRACTS_ROOT / "tool-catalog.json"
COMMON_PATH = SCHEMA_ROOT / "common.schema.json"

EXPECTED_TOOLS = (
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
SHA256 = "0" * 64
FLOW_ID = "flow_abcdefghijklmnop"
RESOURCE_ID = "res_abcdefghijklmnop"
PLAN_ID = "plan_abcdefghijklmnop"
PRESENTATION_ID = "pres_abcdefghijklmnop"
JOB_ID = "job_abcdefghijklmnop"
ASSET_ID = "asset_abcdefghijklmnop"
BUNDLE_ID = "bundle_abcdefghijklmnop"
ARCHIVE_ID = "archive_abcdefghijklmnop"
TIMESTAMP = "2026-08-08T00:00:00Z"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry() -> Registry:
    registry = Registry()
    for path in sorted(SCHEMA_ROOT.rglob("*.schema.json")):
        document = load_json(path)
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    error_codes = load_json(CONTRACTS_ROOT / "error-codes.json")
    return registry.with_resource(error_codes["$id"], Resource.from_contents(error_codes))


def validator_for(path: Path, pointer: str, registry: Registry) -> Draft202012Validator:
    document = load_json(path)
    return Draft202012Validator(
        {"$ref": f"{document['$id']}#{pointer}"},
        registry=registry,
        format_checker=FormatChecker(),
    )


def asset_summary(*, enriched: bool = False) -> dict:
    value = {
        "asset_id": ASSET_ID,
        "resource_id": RESOURCE_ID,
        "media_type": "video/mp4",
        "size_bytes": 128,
        "sha256": SHA256,
        "validation_status": "validated",
    }
    if enriched:
        value.update(
            {
                "bundle_id": BUNDLE_ID,
                "role": "primary",
                "order": 1,
                "bundle_completion": "partial",
            }
        )
    return value


def item_failure(*, enriched: bool = False) -> dict:
    value = {
        "resource_id": RESOURCE_ID,
        "code": "DOWNLOAD_FAILED",
        "message": "字幕资源不可用",
        "retriable": True,
    }
    if enriched:
        value.update(
            {
                "bundle_id": BUNDLE_ID,
                "role": "subtitle",
                "order": 2,
                "item_key": "subtitle-2",
            }
        )
    return value


class AssetBundleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = build_registry()
        cls.common = load_json(COMMON_PATH)

    def assert_valid(self, path: Path, pointer: str, value: dict) -> None:
        validator = validator_for(path, pointer, self.registry)
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
        self.assertEqual([], [error.message for error in errors])

    def assert_invalid(self, path: Path, pointer: str, value: dict) -> None:
        validator = validator_for(path, pointer, self.registry)
        self.assertTrue(list(validator.iter_errors(value)))

    def test_catalog_minor_addition_keeps_contract_and_tool_set(self) -> None:
        catalog = load_json(CATALOG_PATH)
        self.assertEqual("1.6.0", catalog["catalog_version"])
        self.assertEqual("1.0.0", catalog["contract_version"])
        self.assertEqual(EXPECTED_TOOLS, tuple(tool["name"] for tool in catalog["tools"]))
        self.assertEqual(13, len(catalog["tools"]))

        catalog_schema = load_json(SCHEMA_ROOT / "tool-catalog.schema.json")
        errors = sorted(
            Draft202012Validator(
                catalog_schema,
                registry=self.registry,
                format_checker=FormatChecker(),
            ).iter_errors(catalog),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual([], [error.message for error in errors])

    def test_common_bundle_fields_are_optional_and_role_is_formal(self) -> None:
        asset_def = self.common["$defs"]["asset_summary"]
        failure_def = self.common["$defs"]["item_failure"]
        self.assertEqual(
            ["asset_id", "resource_id", "media_type", "size_bytes", "sha256", "validation_status"],
            asset_def["required"],
        )
        self.assertEqual(["code", "message", "retriable"], failure_def["required"])
        self.assertEqual(
            ["primary", "subtitle", "cover", "metadata", "attachment", "transcript", "companion"],
            self.common["$defs"]["asset_role"]["enum"],
        )
        self.assertEqual(["complete", "partial"], self.common["$defs"]["bundle_completion"]["enum"])
        self.assertNotIn("partial", self.common["$defs"]["job_status"]["enum"])

        self.assert_valid(COMMON_PATH, "/$defs/asset_summary", asset_summary())
        self.assert_valid(COMMON_PATH, "/$defs/asset_summary", asset_summary(enriched=True))
        self.assert_valid(COMMON_PATH, "/$defs/item_failure", item_failure())
        self.assert_valid(COMMON_PATH, "/$defs/item_failure", item_failure(enriched=True))

        invalid_role = asset_summary(enriched=True)
        invalid_role["role"] = "image"
        self.assert_invalid(COMMON_PATH, "/$defs/asset_summary", invalid_role)
        invalid_item_key = item_failure(enriched=True)
        invalid_item_key["item_key"] = "../secret"
        self.assert_invalid(COMMON_PATH, "/$defs/item_failure", invalid_item_key)

    def test_job_archive_library_and_flow_outputs_accept_enrichment(self) -> None:
        job_status = {
            "contract_version": "1.0.0",
            "ok": True,
            "flow_id": FLOW_ID,
            "plan_id": PLAN_ID,
            "presentation_id": PRESENTATION_ID,
            "presented_version": 1,
            "selection_version": 1,
            "selection_digest": "a" * 64,
            "plan_digest": "b" * 64,
            "job_id": JOB_ID,
            "status": "succeeded",
            "completion": "partial",
            "progress": {
                "percent": 100,
                "completed_items": 1,
                "total_items": 2,
                "message": "主资产已完成，字幕失败",
            },
            "assets": [asset_summary(enriched=True)],
            "failures": [item_failure(enriched=True)],
            "updated_at": TIMESTAMP,
        }
        self.assert_valid(
            SCHEMA_ROOT / "tools" / "resource_job_status.schema.json",
            "/$defs/success",
            job_status,
        )

        classification = {
            "taxonomy_version": "learning-v1",
            "classification_status": "classified",
            "primary_domain": "natural_science",
            "secondary_domains": [],
            "topics": ["天文"],
            "material_purposes": ["explanation"],
            "grade_levels": [],
            "curriculum_versions": [],
        }
        archive_success = {
            "contract_version": "1.0.0",
            "ok": True,
            "flow_id": FLOW_ID,
            "job_id": JOB_ID,
            "asset_id": ASSET_ID,
            "resource_id": RESOURCE_ID,
            "archive_id": ARCHIVE_ID,
            "archive_status": "ready",
            "archived_at": TIMESTAMP,
            "deduplicated": False,
            "classification": classification,
            "primary_domain_display_name": "自然科学",
            "bundle_id": BUNDLE_ID,
            "role": "primary",
            "order": 1,
            "bundle_completion": "partial",
        }
        self.assert_valid(
            SCHEMA_ROOT / "tools" / "resource_archive.schema.json",
            "/$defs/success",
            archive_success,
        )

        library_asset = {
            "archive_id": ARCHIVE_ID,
            "asset_id": ASSET_ID,
            "resource_id": RESOURCE_ID,
            "platform": "generic",
            "title": "天文资料",
            "resource_type": "video",
            "resource_format": "video",
            "media_type": "video/mp4",
            "size_bytes": 128,
            "sha256": SHA256,
            "archived_at": TIMESTAMP,
            "tags": [],
            "classification": classification,
            "primary_domain_display_name": "自然科学",
            "bundle_id": BUNDLE_ID,
            "role": "primary",
            "order": 1,
            "bundle_completion": "partial",
        }
        self.assert_valid(
            SCHEMA_ROOT / "tools" / "resource_library_search.schema.json",
            "/$defs/library_asset",
            library_asset,
        )

        flow_job = {
            "job_id": JOB_ID,
            "plan_id": PLAN_ID,
            "presentation_id": PRESENTATION_ID,
            "presented_version": 1,
            "selection_version": 1,
            "selection_digest": "a" * 64,
            "plan_digest": "b" * 64,
            "status": "succeeded",
            "completion": "partial",
            "progress_percent": 100,
            "asset_ids": [ASSET_ID],
            "bundle_ids": [BUNDLE_ID],
            "failures": [item_failure(enriched=True)],
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
        self.assert_valid(
            SCHEMA_ROOT / "tools" / "resource_flow_status.schema.json",
            "/$defs/job_snapshot",
            flow_job,
        )

        invalid_job = deepcopy(flow_job)
        invalid_job["status"] = "partial"
        self.assert_invalid(
            SCHEMA_ROOT / "tools" / "resource_flow_status.schema.json",
            "/$defs/job_snapshot",
            invalid_job,
        )


if __name__ == "__main__":
    unittest.main()
