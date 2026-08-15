from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SERVER_PATH = SERVICE_ROOT / "src" / "education_resource_mcp" / "server.py"
SCHEMA_ROOT = CONTRACTS_ROOT / "schemas" / "tools"
CATALOG_PATH = CONTRACTS_ROOT / "tool-catalog.json"

SIMPLIFIED_TOOLS = (
    "resource_search",
    "resource_browse_creator",
    "resource_presentation_save",
    "resource_selection_save",
    "resource_download_prepare",
    "resource_download_start",
    "resource_flow_status",
    "resource_inspect",
    "resource_job_status",
)


def _server_parameters(tool_name: str) -> set[str]:
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"), filename=str(SERVER_PATH))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == tool_name:
            return {argument.arg for argument in node.args.args}
    raise AssertionError(f"tool not found: {tool_name}")


def _schema(tool_name: str) -> dict:
    return json.loads((SCHEMA_ROOT / f"{tool_name}.schema.json").read_text(encoding="utf-8"))


def _input_properties(tool_name: str) -> set[str]:
    return set(_schema(tool_name)["$defs"]["input"]["properties"])


def _public_success_properties(tool_name: str) -> set[str]:
    return set(_schema(tool_name)["$defs"]["public_success"]["properties"])


def _resolve_pointer(document: object, pointer: str) -> object:
    if not pointer:
        return document
    value = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _iter_refs(value: object):
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            yield reference
        for child in value.values():
            yield from _iter_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_refs(child)


def _resolve_local_ref(source_path: Path, reference: str) -> object | None:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference) or reference.startswith("//"):
        return None
    relative_path, separator, fragment = reference.partition("#")
    target_path = source_path if not relative_path else (source_path.parent / relative_path).resolve()
    contracts_root = CONTRACTS_ROOT.resolve()
    if not target_path.is_relative_to(contracts_root):
        raise AssertionError(f"schema ref escapes contracts root: {reference}")
    if not target_path.is_file():
        raise AssertionError(f"schema ref target missing: {reference}")
    document = json.loads(target_path.read_text(encoding="utf-8"))
    if separator and fragment and not fragment.startswith("/"):
        raise AssertionError(f"invalid JSON pointer: {reference}")
    return _resolve_pointer(document, fragment if separator else "")


class PublicSurfaceSimplification0055Tests(unittest.TestCase):
    def test_server_and_schema_inputs_match_for_simplified_tools(self) -> None:
        expected = {
            "resource_search": {
                "contract_version", "flow_id", "idempotency_key", "search_tasks",
                "mode", "filters", "limit",
            },
            "resource_browse_creator": {
                "contract_version", "flow_id", "idempotency_key", "platform",
                "creator_id", "limit",
            },
            "resource_presentation_save": {
                "contract_version", "flow_id", "displayed_resource_ids", "idempotency_key",
            },
            "resource_selection_save": {
                "contract_version", "flow_id", "idempotency_key", "selected_positions",
            },
            "resource_download_prepare": {
                "contract_version", "flow_id", "idempotency_key", "options",
            },
        }
        for tool_name, fields in expected.items():
            with self.subTest(tool=tool_name):
                self.assertEqual(fields, _server_parameters(tool_name))
                self.assertEqual(fields, _input_properties(tool_name))

    def test_removed_transaction_fields_do_not_reappear_in_public_inputs(self) -> None:
        forbidden = {
            "resource_search": {"task_version", "base_result_set_id"},
            "resource_browse_creator": {"task_version"},
            "resource_presentation_save": {"result_set_id"},
            "resource_selection_save": {"presentation_id", "presented_version"},
            "resource_download_prepare": {
                "presentation_id", "presented_version", "selection_version", "selection_digest",
            },
        }
        for tool_name, fields in forbidden.items():
            with self.subTest(tool=tool_name):
                self.assertTrue(fields.isdisjoint(_server_parameters(tool_name)))
                self.assertTrue(fields.isdisjoint(_input_properties(tool_name)))

    def test_compact_outputs_hide_internal_state(self) -> None:
        binding_fields = {
            "result_set_id", "presentation_id", "presented_version",
            "selection_version", "selection_digest", "plan_digest",
        }
        forbidden = {
            "resource_search": binding_fields | {
                "task_version", "search_run_id", "result_version", "platform_runs",
                "provenance", "coverage", "base_result_set_id",
            },
            "resource_browse_creator": binding_fields | {
                "task_version", "search_run_id", "result_version", "platform_runs",
            },
            "resource_presentation_save": binding_fields,
            "resource_selection_save": binding_fields,
            "resource_download_prepare": binding_fields,
            "resource_download_start": binding_fields | {"plan_id"},
            "resource_inspect": {
                "resolution_id", "resolved_resource", "inspection", "resolution_digest", "capability_ref",
            },
            "resource_flow_status": {
                "task_version", "current_resolutions", "created_at", "updated_at",
            },
            "resource_job_status": binding_fields | {"plan_id", "outcomes"},
        }
        for tool_name, fields in forbidden.items():
            with self.subTest(tool=tool_name):
                self.assertTrue(fields.isdisjoint(_public_success_properties(tool_name)))

    def test_public_search_uses_small_default_and_explicit_summary_excerpt(self) -> None:
        schema = _schema("resource_search")
        input_schema = schema["$defs"]["input"]
        candidate = schema["$defs"]["public_candidate"]
        self.assertEqual(8, input_schema["properties"]["limit"]["default"])
        self.assertEqual(600, candidate["properties"]["summary"]["maxLength"])
        self.assertIn("summary_complete", candidate["required"])
        self.assertNotIn("maxItems", schema["$defs"]["public_success"]["properties"]["candidates"])

    def test_creator_browse_keeps_requested_list_reachable(self) -> None:
        schema = _schema("resource_browse_creator")
        self.assertEqual(200, schema["$defs"]["public_success"]["properties"]["candidates"]["maxItems"])
        self.assertEqual(200, schema["$defs"]["input"]["properties"]["limit"]["maximum"])

    def test_prepare_plan_items_hide_provider_and_representation_bindings(self) -> None:
        schema = _schema("resource_download_prepare")
        fields = set(schema["$defs"]["public_plan_item"]["properties"])
        self.assertTrue(
            {"representation_id", "planned_strategy", "planned_provider", "planned_provider_version"}.isdisjoint(fields)
        )

    def test_flow_status_result_set_summary_is_explicitly_bounded(self) -> None:
        schema = _schema("resource_flow_status")
        summary = schema["$defs"]["result_set_summary"]
        candidate_refs = summary["properties"]["candidate_refs"]
        self.assertEqual(20, candidate_refs["maxItems"])
        self.assertIn("candidate_refs_complete", summary["required"])

    def test_modified_schema_refs_resolve(self) -> None:
        for tool_name in SIMPLIFIED_TOOLS:
            path = SCHEMA_ROOT / f"{tool_name}.schema.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            for reference in _iter_refs(document):
                with self.subTest(tool=tool_name, reference=reference):
                    _resolve_local_ref(path, reference)

    def test_catalog_version_and_tool_count_remain_stable(self) -> None:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual("1.7.0", catalog["catalog_version"])
        self.assertEqual("1.0.0", catalog["contract_version"])
        self.assertEqual(14, len(catalog["tools"]))


if __name__ == "__main__":
    unittest.main()
