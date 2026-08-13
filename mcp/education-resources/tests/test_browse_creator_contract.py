from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SCHEMA_PATH = CONTRACTS_ROOT / "schemas" / "tools" / "resource_browse_creator.schema.json"
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.errors import ok
from education_resource_mcp.search import MultiPlatformSearchProvider
from education_resource_mcp.service import ResourceService
from education_resource_mcp.storage import Store


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _CreatorAdapter:
    platform_id = "bilibili"

    def search_creator(self, creator_id: str, limit: int):
        return [], {
            "code": "FEATURE_NOT_SUPPORTED",
            "message": "创作者浏览不可用",
            "retryable": False,
        }


class _CreatorProvider:
    def __init__(self, *, with_failure: bool) -> None:
        self.with_failure = with_failure

    def search_creator(self, platform: str, creator_id: str, limit: int):
        resource = {
            "platform": platform,
            "title": "创作者资料",
            "source_url": "https://example.com/creator-resource",
            "resource_type": "article",
            "summary": "测试资料",
            "metadata": {},
        }
        query_run = {
            "query": creator_id,
            "candidate_count": 1,
            "failure_count": 1 if self.with_failure else 0,
        }
        if self.with_failure:
            query_run["error"] = {
                "code": "PARTIAL_FAILURE",
                "message": "创作者来源部分失败",
                "retryable": True,
            }
        return [resource], [
            {
                "platform": platform,
                "status": "partial" if self.with_failure else "succeeded",
                "query_runs": [query_run],
            }
        ]


class BrowseCreatorContractTests(unittest.TestCase):
    def test_schema_declares_search_run_and_resolves_shared_platform_run(self) -> None:
        schema = _load_json(SCHEMA_PATH)
        required = schema["$defs"]["success"]["required"]
        self.assertIn("search_run_id", required)
        self.assertIn("search_run_id", schema["$defs"]["success"]["properties"])

        reference = schema["$defs"]["success"]["properties"]["platform_runs"]["items"]["$ref"]
        self.assertEqual("resource_search.schema.json#/$defs/platform_run", reference)
        target = SCHEMA_PATH.parent / reference.split("#", 1)[0]
        self.assertTrue(target.is_file(), target)
        resource_search = _load_json(target)
        self.assertIn("query_runs", resource_search["$defs"]["platform_run"]["properties"])
        self.assertIn("query", resource_search["$defs"]["query_run"]["properties"])

    def test_creator_provider_uses_shared_platform_run_query_run_shape(self) -> None:
        provider = object.__new__(MultiPlatformSearchProvider)
        provider._adapters = {"bilibili": _CreatorAdapter()}

        resources, platform_runs = provider.search_creator("bilibili", "up-123", 10)

        self.assertEqual([], resources)
        self.assertEqual(
            {
                "platform": "bilibili",
                "status": "failed",
                "query_runs": [
                    {
                        "query": "up-123",
                        "candidate_count": 0,
                        "failure_count": 1,
                        "error": {
                            "code": "FEATURE_NOT_SUPPORTED",
                            "message": "创作者浏览不可用",
                            "retryable": False,
                        },
                    }
                ],
            },
            platform_runs[0],
        )

    def test_browse_extracts_query_failures_and_matches_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            store = Store(root / "database.sqlite")
            flow = store.create_flow(
                {"goal": {"topic": "创作者资料"}, "constraints": []},
                "browse-flow-key-0001",
                "flow-request-hash",
            )
            service = object.__new__(ResourceService)
            service.store = store
            service.settings = SimpleNamespace()
            service.search_provider = _CreatorProvider(with_failure=True)

            result = service.browse_creator(
                flow["flow_id"],
                "browse-result-key-0001",
                "bilibili",
                "up-123",
                task_version=flow["task_version"],
                limit=10,
            )

            self.assertIn("search_run_id", result)
            self.assertEqual("PARTIAL_FAILURE", result["failures"][0]["code"])
            self.assertEqual("bilibili", result["failures"][0]["platform"])

            try:
                from jsonschema import Draft202012Validator, FormatChecker
                from referencing import Registry, Resource
            except ImportError:
                self.skipTest("jsonschema/referencing unavailable")
            registry = Registry()
            for path in CONTRACTS_ROOT.rglob("*.json"):
                document = _load_json(path)
                if document.get("$id"):
                    registry = registry.with_resource(
                        document["$id"], Resource.from_contents(document)
                    )
            validator = Draft202012Validator(
                {**_load_json(SCHEMA_PATH), "$ref": "#/$defs/success"},
                registry=registry,
                format_checker=FormatChecker(),
            )
            errors = list(validator.iter_errors(ok(result)))
            self.assertEqual([], errors)

    def test_browse_scope_does_not_conflict_with_resource_search_scope(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            store = Store(root / "database.sqlite")
            flow = store.create_flow(
                {"goal": {"topic": "创作者资料"}, "constraints": []},
                "browse-flow-key-0002",
                "flow-request-hash",
            )
            shared_key = "shared-search-browse-key"
            store.create_result_set(
                flow["flow_id"],
                [],
                query="关键词搜索",
                task_version=flow["task_version"],
                filters={},
                failures=[],
                platform_runs=[],
                idempotency_key=shared_key,
                request_hash="search-request-hash",
            )
            service = object.__new__(ResourceService)
            service.store = store
            service.settings = SimpleNamespace()
            service.search_provider = _CreatorProvider(with_failure=False)

            result = service.browse_creator(
                flow["flow_id"],
                shared_key,
                "bilibili",
                "up-456",
                task_version=flow["task_version"],
                limit=10,
            )

            self.assertTrue(result["result_set_id"].startswith("rset_"))
            self.assertEqual(
                result,
                service.browse_creator(
                    flow["flow_id"],
                    shared_key,
                    "bilibili",
                    "up-456",
                    task_version=flow["task_version"],
                    limit=10,
                ),
            )


if __name__ == "__main__":
    unittest.main()
