"""Contract catalog, schema consistency, and output validation tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SERVICE_ROOT / "src"
CONTRACTS_ROOT = SERVICE_ROOT / "contracts" / "v1"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from session_manager.server import _failure, _invoke, _ok, _session_status  # noqa: E402
from session_manager.store import SessionStore  # noqa: E402


JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None
EXPECTED_TOOLS = {
    "resource_session_status",
    "resource_session_login_guide",
    "resource_session_save",
    "resource_session_delete",
}
EXPECTED_ERROR_CODES = {
    "INVALID_ARGUMENT",
    "UNKNOWN_PLATFORM",
    "LOGIN_NOT_REQUIRED",
    "SESSION_EMPTY",
    "SESSION_PAYLOAD_INVALID",
    "SESSION_PAYLOAD_TOO_LARGE",
    "INVALID_IDEMPOTENCY_KEY",
    "IDEMPOTENCY_CONFLICT",
    "IDEMPOTENCY_STALE",
    "UNSAFE_DATA_PATH",
    "SECURE_STORAGE_UNAVAILABLE",
    "INTERNAL_ERROR",
}


def _home_temp_directory(prefix: str = "session-manager-contract-"):
    return tempfile.TemporaryDirectory(prefix=prefix, dir=Path.home())


def _cookie(value: str = "contract-secret") -> dict[str, object]:
    return {
        "name": "SESSDATA",
        "value": value,
        "domain": ".bilibili.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "partitionKey": {
            "topLevelSite": "https://www.bilibili.com",
            "hasCrossSiteAncestor": False,
        },
    }


class ContractCatalogTests(unittest.TestCase):
    def test_all_contract_json_documents_parse(self) -> None:
        paths = sorted(CONTRACTS_ROOT.rglob("*.json"))
        self.assertGreaterEqual(len(paths), 7)
        for path in paths:
            with self.subTest(path=path.relative_to(CONTRACTS_ROOT)):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)

    def test_tool_catalog_has_exact_server_tool_set_and_resolvable_refs(self) -> None:
        catalog = json.loads(
            (CONTRACTS_ROOT / "tool-catalog.json").read_text(encoding="utf-8")
        )
        self.assertEqual(catalog["catalog_version"], "1.1.0")
        self.assertEqual(catalog["contract_version"], "1.0.0")
        self.assertEqual(catalog["server_id"], "session-manager")
        self.assertEqual({tool["name"] for tool in catalog["tools"]}, EXPECTED_TOOLS)

        for tool in catalog["tools"]:
            for field in ("input_schema", "output_schema"):
                relative_path, fragment = tool[field].split("#", 1)
                self.assertTrue((CONTRACTS_ROOT / relative_path).is_file())
                self.assertIn(fragment, {"/$defs/input", "/$defs/output"})
            if tool["side_effect"] == "local_state_write":
                self.assertTrue(tool["idempotency_supported"])

    def test_local_status_and_save_contract_use_stored_revision_semantics(self) -> None:
        status_schema = json.loads(
            (
                CONTRACTS_ROOT
                / "schemas"
                / "tools"
                / "resource_session_status.schema.json"
            ).read_text(encoding="utf-8")
        )
        save_schema = json.loads(
            (
                CONTRACTS_ROOT
                / "schemas"
                / "tools"
                / "resource_session_save.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            status_schema["$defs"]["session_entry"]["properties"]["status"]["enum"],
            ["stored", "expired", "invalid", "missing", "not_required"],
        )
        save_success = save_schema["$defs"]["success"]
        self.assertEqual(save_success["properties"]["status"]["const"], "stored")
        self.assertIn("session_revision", save_success["required"])
        self.assertIn(
            "partitionKey", save_schema["$defs"]["cookie"]["properties"]
        )
        browser_session = save_schema["$defs"]["browser_session"]
        self.assertEqual(
            set(browser_session["properties"]),
            {"cookies", "tokens", "storage_origin", "local_storage", "session_storage"},
        )
        self.assertNotIn(
            "maximum",
            save_success["properties"]["discarded_credential_count"],
        )

    def test_error_code_enum_and_metadata_are_complete_and_unique(self) -> None:
        document = json.loads(
            (CONTRACTS_ROOT / "error-codes.json").read_text(encoding="utf-8")
        )
        enum_codes = set(document["$defs"]["error_code"]["enum"])
        metadata_codes = [entry["code"] for entry in document["codes"]]

        self.assertEqual(enum_codes, EXPECTED_ERROR_CODES)
        self.assertEqual(set(metadata_codes), EXPECTED_ERROR_CODES)
        self.assertEqual(len(metadata_codes), len(set(metadata_codes)))
        for entry in document["codes"]:
            self.assertIs(entry["retriable"], False)
            self.assertTrue(entry["description"])


@unittest.skipUnless(JSONSCHEMA_AVAILABLE, "jsonschema is required for contract validation")
class JsonSchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource

        registry = Registry()
        for path in CONTRACTS_ROOT.rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            document_id = document.get("$id")
            if document_id:
                registry = registry.with_resource(
                    document_id, Resource.from_contents(document)
                )
        cls.registry = registry
        cls.validator_class = Draft202012Validator
        cls.format_checker = FormatChecker()

    def assert_contract(self, tool_name: str, instance: dict[str, object]) -> None:
        path = (
            CONTRACTS_ROOT
            / "schemas"
            / "tools"
            / f"{tool_name}.schema.json"
        )
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator = self.validator_class(
            schema,
            registry=self.registry,
            format_checker=self.format_checker,
        )
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
        self.assertEqual([], [error.message for error in errors])

    def test_four_tool_input_examples_match_contracts(self) -> None:
        examples = {
            "resource_session_status": {
                "contract_version": "1.0.0",
                "platforms": ["bilibili", "smartedu"],
                "deep": False,
            },
            "resource_session_login_guide": {
                "contract_version": "1.0.0",
                "platform": "bilibili",
            },
            "resource_session_save": {
                "contract_version": "1.0.0",
                "platform": "bilibili",
                "session_data": {"cookies": [_cookie()]},
                "expires_at": None,
                "idempotency_key": "contract-save-key-01",
            },
            "resource_session_delete": {
                "contract_version": "1.0.0",
                "platform": "bilibili",
                "idempotency_key": "contract-delete-key-01",
            },
        }
        for tool_name, example in examples.items():
            with self.subTest(tool=tool_name):
                self.assert_contract(tool_name, example)

    def test_broad_smartedu_capture_input_matches_contract(self) -> None:
        example = {
            "contract_version": "1.0.0",
            "platform": "smartedu",
            "session_data": {
                "cookies": [
                    {
                        "name": "UC_TOKEN-synthetic-id-ncet-xedu",
                        "value": "synthetic-cookie-value",
                        "domain": ".auth.smartedu.cn",
                        "path": "/",
                        "priority": "High",
                    }
                ],
                "storage_origin": "https://basic.smartedu.cn",
                "local_storage": {
                    "ND_UC_AUTH-synthetic-id&ncet-xedu&token": json.dumps(
                        {"nested": {"access_token": "synthetic-token"}}
                    ),
                    "unrelated": "discarded",
                },
                "session_storage": {"temporary": "discarded"},
            },
            "idempotency_key": "contract-broad-save-01",
        }
        self.assert_contract("resource_session_save", example)

    def test_broad_capture_contract_rejects_unknown_top_level_and_non_string_storage(self) -> None:
        path = (
            CONTRACTS_ROOT
            / "schemas"
            / "tools"
            / "resource_session_save.schema.json"
        )
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator = self.validator_class(
            schema,
            registry=self.registry,
            format_checker=self.format_checker,
        )
        invalid_examples = [
            {
                "contract_version": "1.0.0",
                "platform": "smartedu",
                "session_data": {"browser_capture": {}},
            },
            {
                "contract_version": "1.0.0",
                "platform": "smartedu",
                "session_data": {
                    "storage_origin": "https://basic.smartedu.cn/path",
                    "local_storage": {"key": "value"},
                },
            },
            {
                "contract_version": "1.0.0",
                "platform": "smartedu",
                "session_data": {
                    "storage_origin": "https://basic.smartedu.cn",
                    "local_storage": {"key": {"not": "a string"}},
                },
            },
        ]
        for example in invalid_examples:
            with self.subTest(example=example):
                self.assertTrue(list(validator.iter_errors(example)))

    def test_real_success_outputs_match_all_four_tool_contracts(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            status = _ok(_session_status(store, ["bilibili", "cctv"], False))
            guide = _ok(store.login_guide("bilibili"))
            saved = _ok(
                store.save(
                    "bilibili",
                    {"cookies": [_cookie()]},
                    idempotency_key="contract-save-key-02",
                )
            )
            deleted = _ok(
                store.delete(
                    "bilibili", idempotency_key="contract-delete-key-02"
                )
            )

        self.assertEqual(saved["status"], "stored")
        self.assertRegex(saved["session_revision"], r"^[0-9a-f]{32}$")
        self.assertEqual(status["sessions"][0]["status"], "missing")
        outputs = {
            "resource_session_status": status,
            "resource_session_login_guide": guide,
            "resource_session_save": saved,
            "resource_session_delete": deleted,
        }
        for tool_name, output in outputs.items():
            with self.subTest(tool=tool_name):
                self.assert_contract(tool_name, output)

    def test_public_and_authenticated_login_guides_match_contract(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            for platform in ("smartedu", "cctv"):
                with self.subTest(platform=platform):
                    self.assert_contract(
                        "resource_session_login_guide",
                        _ok(store.login_guide(platform)),
                    )

    def test_smartedu_guide_exposes_server_extraction_hints(self) -> None:
        with _home_temp_directory() as temp_dir:
            guide = SessionStore(Path(temp_dir) / "data").login_guide("smartedu")

        self.assertEqual(guide["capture_method"], "browser_storage")
        self.assertIn("smartedu.cn", guide["cookie_domains"])
        self.assertIn("ND_UC_AUTH-*&ncet-xedu&token", guide["storage_key_patterns"])
        capture_step = next(
            step for step in guide["steps"] if step["action"] == "browser_storage"
        )
        self.assertIn("全部 Cookie", capture_step["message"])
        self.assertIn("localStorage/sessionStorage", capture_step["message"])
        self.assertIn("MCP", capture_step["message"])
        self.assert_contract("resource_session_login_guide", _ok(guide))

    def test_structured_business_errors_match_each_tool_contract(self) -> None:
        with _home_temp_directory() as temp_dir:
            store = SessionStore(Path(temp_dir) / "data")
            outputs = {
                "resource_session_status": _invoke(
                    lambda: _session_status(store, ["not-a-platform"], False)
                ),
                "resource_session_login_guide": _invoke(
                    lambda: store.login_guide("not-a-platform"),
                    platform="not-a-platform",
                ),
                "resource_session_save": _invoke(
                    lambda: store.save(
                        "bilibili",
                        {"cookies": [{"name": "x", "value": "y", "domain": "example.com"}]},
                    ),
                    platform="bilibili",
                ),
                "resource_session_delete": _failure(
                    "INVALID_IDEMPOTENCY_KEY",
                    "invalid key",
                    platform="bilibili",
                ),
            }

        for tool_name, output in outputs.items():
            with self.subTest(tool=tool_name):
                self.assertFalse(output["ok"])
                self.assert_contract(tool_name, output)

    def test_output_contracts_have_no_credential_container_fields(self) -> None:
        forbidden = {
            "cookies",
            "tokens",
            "session_data",
            "accessToken",
            "access_token",
            "local_storage",
            "session_storage",
            "storage_origin",
            "value",
        }
        for tool_name in EXPECTED_TOOLS:
            path = (
                CONTRACTS_ROOT
                / "schemas"
                / "tools"
                / f"{tool_name}.schema.json"
            )
            document = json.loads(path.read_text(encoding="utf-8"))
            output_text = json.dumps(document["$defs"]["output"], ensure_ascii=False)
            with self.subTest(tool=tool_name):
                self.assertTrue(forbidden.isdisjoint(set(document["$defs"]["output"].get("properties", {}))))
                if tool_name != "resource_session_save":
                    self.assertNotIn('"cookies"', output_text)
                    self.assertNotIn('"tokens"', output_text)


if __name__ == "__main__":
    unittest.main()
