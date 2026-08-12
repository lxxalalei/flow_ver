
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from e2e_stdio_client import build_fixture_subprocess_environment


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.taxonomy import (
    DIFFICULTIES,
    DOMAIN_IDS,
    DOMAIN_REGISTRY,
    LEGACY_DOMAIN_ALIASES,
    MATERIAL_PURPOSES,
    TAXONOMY_VERSION,
    domain_directory,
    domain_display_name,
    normalize_archive_metadata,
)


PYDANTIC_AVAILABLE = importlib.util.find_spec("pydantic") is not None
MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None


def _document(path: str) -> dict:
    return json.loads((CONTRACTS_ROOT / path).read_text(encoding="utf-8"))


def _unwrap_nullable(schema: dict, root: dict) -> dict:
    current = schema
    while True:
        reference = current.get("$ref")
        if reference and reference.startswith("#/$defs/"):
            current = root["$defs"][reference.rsplit("/", 1)[-1]]
            continue
        variants = current.get("anyOf") or current.get("oneOf")
        if variants:
            non_null = [item for item in variants if item.get("type") != "null"]
            if len(non_null) == 1:
                current = non_null[0]
                continue
        return current


class TaxonomyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = _document("taxonomy/learning-v1.json")
        self.common = _document("schemas/common.schema.json")

    def test_registry_python_and_schema_are_identical(self) -> None:
        self.assertEqual(self.registry["taxonomy_version"], TAXONOMY_VERSION)
        json_domains = {
            item["id"]: {
                "display_name": item["display_name"],
                "directory": item["directory"],
            }
            for item in self.registry["domains"]
        }
        self.assertEqual(json_domains, DOMAIN_REGISTRY)
        self.assertEqual(tuple(json_domains), DOMAIN_IDS)
        self.assertEqual(
            self.common["$defs"]["learning_domain_id"]["enum"], list(DOMAIN_IDS)
        )
        self.assertEqual(
            self.common["$defs"]["material_purpose"]["enum"],
            list(MATERIAL_PURPOSES),
        )
        self.assertEqual(
            self.common["$defs"]["difficulty"]["enum"], list(DIFFICULTIES)
        )
        self.assertEqual(
            self.registry["legacy_domain_aliases"], LEGACY_DOMAIN_ALIASES
        )

    def test_domains_have_fixed_unique_chinese_directories(self) -> None:
        self.assertEqual(len(DOMAIN_IDS), 10)
        self.assertEqual(len({domain_directory(value) for value in DOMAIN_IDS}), 10)
        self.assertEqual(
            [domain_directory(value).split("-", 1)[0] for value in DOMAIN_IDS],
            [f"{index:02d}" for index in range(1, 11)],
        )
        self.assertNotIn("亲子陪伴", set(DOMAIN_REGISTRY))
        self.assertNotIn("亲子陪伴", {domain_display_name(v) for v in DOMAIN_IDS})
        self.assertNotIn("待分类", set(DOMAIN_REGISTRY))

    def test_every_registered_domain_is_accepted(self) -> None:
        for domain_id in DOMAIN_IDS:
            with self.subTest(domain_id=domain_id):
                normalized = normalize_archive_metadata(
                    {
                        "classification": {
                            "taxonomy_version": "learning-v1",
                            "classification_status": "classified",
                            "primary_domain": domain_id,
                            "secondary_domains": [],
                            "topics": [],
                            "material_purposes": [],
                            "grade_levels": [],
                            "curriculum_versions": [],
                        }
                    }
                )
                self.assertEqual(
                    normalized["classification"]["primary_domain"], domain_id
                )

    def test_secondary_domains_are_deduplicated_and_bounded(self) -> None:
        base = {
            "taxonomy_version": "learning-v1",
            "classification_status": "classified",
            "primary_domain": "natural_science",
            "topics": [],
            "material_purposes": [],
            "grade_levels": [],
            "curriculum_versions": [],
        }
        normalized = normalize_archive_metadata(
            {
                "classification": {
                    **base,
                    "secondary_domains": [
                        "mathematics_reasoning",
                        "mathematics_reasoning",
                    ],
                }
            }
        )
        self.assertEqual(
            normalized["classification"]["secondary_domains"],
            ["mathematics_reasoning"],
        )
        with self.assertRaises(ValueError):
            normalize_archive_metadata(
                {
                    "classification": {
                        **base,
                        "secondary_domains": [
                            value for value in DOMAIN_IDS if value != "natural_science"
                        ][:5],
                    }
                }
            )

    def test_normalizes_known_legacy_metadata(self) -> None:
        normalized = normalize_archive_metadata(
            {
                "primary_domain": "  自然与科学 ",
                "topics": [" 天文与宇宙 ", "天文与宇宙", "太阳系"],
                "tags": ["科普", "科普"],
            }
        )
        self.assertEqual(
            normalized["classification"]["primary_domain"], "natural_science"
        )
        self.assertEqual(
            normalized["classification"]["classification_status"], "classified"
        )
        self.assertEqual(
            normalized["classification"]["topics"], ["天文与宇宙", "太阳系"]
        )
        self.assertEqual(normalized["tags"], ["科普"])
        self.assertNotIn("primary_domain", normalized)
        self.assertNotIn("topics", normalized)

    def test_unknown_legacy_domain_needs_review_and_preserves_raw_value(self) -> None:
        normalized = normalize_archive_metadata(
            {"primary_domain": "亲子陪伴", "topics": ["共读"]}
        )
        self.assertEqual(
            normalized["classification"]["classification_status"], "needs_review"
        )
        self.assertNotIn("primary_domain", normalized["classification"])
        self.assertEqual(
            normalized["legacy_classification_raw"],
            {"primary_domain": "亲子陪伴", "topics": ["共读"]},
        )

    def test_rejects_conflicting_flat_and_nested_classification(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicts"):
            normalize_archive_metadata(
                {
                    "primary_domain": "自然与科学",
                    "classification": {
                        "taxonomy_version": "learning-v1",
                        "classification_status": "classified",
                        "primary_domain": "mathematics_reasoning",
                        "secondary_domains": [],
                        "topics": [],
                        "material_purposes": [],
                        "grade_levels": [],
                        "curriculum_versions": [],
                    },
                }
            )

    def test_rejects_invalid_domain_topic_and_primary_secondary_overlap(self) -> None:
        base = {
            "taxonomy_version": "learning-v1",
            "classification_status": "classified",
            "primary_domain": "natural_science",
            "secondary_domains": [],
            "topics": ["天文与宇宙"],
            "material_purposes": [],
            "grade_levels": [],
            "curriculum_versions": [],
        }
        for update in (
            {"primary_domain": "待分类"},
            {"topics": ["../天文"]},
            {"secondary_domains": ["natural_science"]},
            {"topics": [str(index) for index in range(9)]},
            {"topics": ["x" * 65]},
        ):
            with self.subTest(update=update), self.assertRaises(ValueError):
                normalize_archive_metadata(
                    {"classification": {**base, **update}}
                )

    @unittest.skipUnless(JSONSCHEMA_AVAILABLE, "jsonschema is not installed")
    def test_formal_schema_accepts_every_domain_and_rejects_unknown(self) -> None:
        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(
            {
                "$ref": "#/$defs/archive_classification",
                "$defs": self.common["$defs"],
            }
        )
        base = {
            "taxonomy_version": "learning-v1",
            "classification_status": "classified",
            "secondary_domains": [],
            "topics": [],
            "material_purposes": [],
            "grade_levels": [],
            "curriculum_versions": [],
        }
        for domain_id in DOMAIN_IDS:
            validator.validate({**base, "primary_domain": domain_id})
        self.assertTrue(
            list(validator.iter_errors({**base, "primary_domain": "待分类"}))
        )


@unittest.skipUnless(PYDANTIC_AVAILABLE, "pydantic is not installed")
class TaxonomyModelTests(unittest.TestCase):
    def test_models_normalize_and_reject_taxonomy_errors(self) -> None:
        from pydantic import ValidationError

        from education_resource_mcp.models import ArchiveMetadata

        metadata = ArchiveMetadata.model_validate(
            {"primary_domain": "自然与科学", "topics": ["太空", " 太空 "]}
        )
        self.assertEqual(metadata.classification.primary_domain, "natural_science")
        self.assertEqual(metadata.classification.topics, ["太空"])
        with self.assertRaises(ValidationError):
            ArchiveMetadata.model_validate(
                {
                    "classification": {
                        "taxonomy_version": "learning-v1",
                        "classification_status": "classified",
                        "primary_domain": "not_a_domain",
                    }
                }
            )

    def test_python_model_and_formal_nested_property_sets_match(self) -> None:
        from education_resource_mcp.models import ArchiveMetadata, LibraryFilters

        archive_contract = _document("schemas/tools/resource_archive.schema.json")
        library_contract = _document(
            "schemas/tools/resource_library_search.schema.json"
        )
        self.assertEqual(
            set(ArchiveMetadata.model_json_schema()["properties"]),
            set(archive_contract["$defs"]["archive_metadata"]["properties"]),
        )
        self.assertEqual(
            set(LibraryFilters.model_json_schema()["properties"]),
            set(library_contract["$defs"]["filters"]["properties"]),
        )


@unittest.skipUnless(MCP_AVAILABLE, "mcp dependencies are not installed")
class ToolsListNestedSchemaTests(unittest.TestCase):
    def test_tools_list_nested_archive_and_library_fields_match_contract(self) -> None:
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def run() -> None:
            with tempfile.TemporaryDirectory() as data_dir:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[str(SERVICE_ROOT / "tests" / "stdio_fixture_server.py")],
                    cwd=SERVICE_ROOT,
                    env=build_fixture_subprocess_environment(data_dir),
                )
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                        cases = (
                            (
                                "resource_archive",
                                "metadata",
                                _document("schemas/tools/resource_archive.schema.json")[
                                    "$defs"
                                ]["archive_metadata"],
                            ),
                            (
                                "resource_library_search",
                                "filters",
                                _document(
                                    "schemas/tools/resource_library_search.schema.json"
                                )["$defs"]["filters"],
                            ),
                        )
                        for tool_name, property_name, formal in cases:
                            runtime_root = tools[tool_name].input_schema
                            runtime = _unwrap_nullable(
                                runtime_root["properties"][property_name], runtime_root
                            )
                            self.assertEqual(
                                set(runtime["properties"]),
                                set(formal["properties"]),
                                tool_name,
                            )

                        archive_root = tools["resource_archive"].input_schema
                        runtime_metadata = _unwrap_nullable(
                            archive_root["properties"]["metadata"], archive_root
                        )
                        runtime_classification = _unwrap_nullable(
                            runtime_metadata["properties"]["classification"],
                            archive_root,
                        )
                        formal_classification = _document(
                            "schemas/common.schema.json"
                        )["$defs"]["archive_classification"]
                        self.assertEqual(
                            set(runtime_classification["properties"]),
                            set(formal_classification["properties"]),
                        )
                        runtime_primary = _unwrap_nullable(
                            runtime_classification["properties"]["primary_domain"],
                            archive_root,
                        )
                        self.assertEqual(
                            runtime_primary["enum"], list(DOMAIN_IDS)
                        )

        anyio.run(run)


if __name__ == "__main__":
    unittest.main()

import pytest

pytestmark = pytest.mark.slow
