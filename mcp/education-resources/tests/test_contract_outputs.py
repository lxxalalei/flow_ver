from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


SERVICE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError, failure, ok
from education_resource_mcp.models import FlowTask
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService


TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
EXPECTED_FLOW_STATUS_FIELDS = {
    "current_result_set",
    "current_presentation",
    "current_selection",
    "current_plan",
    "current_job",
}
LEGACY_FLOW_STATUS_FIELDS = {"latest_result_set", "active_plan", "latest_job"}
BINDING_FIELDS = {
    "presentation_id",
    "presented_version",
    "selection_version",
    "selection_digest",
}


class ContractDownloader:
    def __init__(self, jobs_dir: Path, wait_for_cancel: bool = False) -> None:
        self.jobs_dir = jobs_dir
        self.wait_for_cancel = wait_for_cancel

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        if self.wait_for_cancel and cancel_event.wait(2):
            raise DomainError("JOB_CANCELLED", "cancelled")
        payload = b"<html>contract fixture</html>"
        directory = self.jobs_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "fixture.html"
        path.write_bytes(payload)
        return DownloadResult(
            path,
            len(payload),
            "text/html",
            hashlib.sha256(payload).hexdigest(),
            path.name,
        )


def build_registry() -> Registry:
    registry = Registry()
    for path in CONTRACTS_ROOT.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        identifier = document.get("$id")
        if identifier:
            registry = registry.with_resource(identifier, Resource.from_contents(document))
    return registry


class ContractOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = build_registry()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.settings = Settings(
            data_dir=data_dir,
            database_path=data_dir / "database.sqlite",
            jobs_dir=data_dir / "jobs",
            library_dir=data_dir / "library",
            max_download_bytes=1024 * 1024,
            max_search_results=20,
            max_workers=2,
            plan_ttl_seconds=60,
        )
        self.provider = StaticSearchProvider(
            [
                {
                    "platform": "generic",
                    "title": "儿童恐龙资料",
                    "source_url": "https://example.com/dinosaur",
                    "resource_type": "article",
                    "summary": "公开资料",
                    "metadata": {"language": "zh-CN"},
                },
                {
                    "platform": "generic",
                    "title": "恐龙化石资料",
                    "source_url": "https://example.com/fossil",
                    "resource_type": "article",
                    "summary": "化石资料",
                    "metadata": {"language": "zh-CN"},
                },
            ]
        )
        self.service = ResourceService(
            self.settings,
            search_provider=self.provider,
            download_provider=ContractDownloader(self.settings.jobs_dir),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def assert_contract(self, tool_name: str, instance: dict) -> None:
        path = CONTRACTS_ROOT / "schemas" / "tools" / f"{tool_name}.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        validation_schema = schema
        if instance.get("ok") is True:
            validation_schema = {
                **schema,
                "$ref": "#/$defs/success",
            }
            validation_schema.pop("oneOf", None)
        validator = Draft202012Validator(
            validation_schema,
            registry=self.registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
        messages = [
            f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors
        ]
        self.assertEqual([], messages)

    def _flow_task(self) -> dict:
        return FlowTask(
            goal={"topic": "恐龙", "outcome": "找到适合入门理解的资料"},
            user_role="parent",
            resource_target="child",
            constraints=[],
        ).model_dump(exclude_none=True)

    def _wait(self, flow_id: str, job_id: str) -> dict:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = self.service.job_status(flow_id, job_id)
            if result["status"] in TERMINAL_JOB_STATES:
                return result
            time.sleep(0.01)
        self.fail("job timeout")

    def _prepare_flow(self, key_suffix: str) -> dict[str, dict]:
        flow = self.service.flow_start(
            f"contract-flow-{key_suffix}-0001", self._flow_task()
        )
        search = self.service.search(
            flow["flow_id"],
            f"contract-search-{key_suffix}-001",
            [{"platform": "generic", "queries": [{"query": "恐龙"}]}],
            task_version=flow["task_version"],
            filters={
                "resource_types": ["article"],
                "languages": ["zh-CN"],
            },
            limit=20,
        )
        displayed = [
            search["candidates"][1]["resource_id"],
            search["candidates"][0]["resource_id"],
        ]
        presentation = self.service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            displayed,
            f"contract-present-{key_suffix}-01",
        )
        selection = self.service.selection_save(
            flow["flow_id"],
            f"contract-select-{key_suffix}-001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        binding = {
            "presentation_id": presentation["presentation_id"],
            "presented_version": presentation["presented_version"],
            "selection_version": selection["selection_version"],
            "selection_digest": selection["selection_digest"],
        }
        plan = self.service.download_prepare(
            flow["flow_id"],
            f"contract-prepare-{key_suffix}-01",
            selection["selection_version"],
            presentation_id=binding["presentation_id"],
            presented_version=binding["presented_version"],
            selection_digest=binding["selection_digest"],
            options={"preferred_container": "html"},
        )
        return {
            "flow": flow,
            "search": search,
            "presentation": presentation,
            "selection": selection,
            "binding": binding,
            "plan": plan,
        }

    def test_success_outputs_match_all_contracts_except_cancel(self) -> None:
        state = self._prepare_flow("success")
        flow = state["flow"]
        search = state["search"]
        presentation = state["presentation"]
        selection = state["selection"]
        binding = state["binding"]
        plan = state["plan"]

        with self.subTest(public_shape="search"):
            self.assertIn("candidates", search)
            self.assertEqual(flow["task_version"], search["task_version"])
        with self.subTest(public_shape="presentation"):
            self.assertIn("items", presentation)
            self.assertIn("empty", presentation)
            self.assertNotIn("displayed_items", presentation)
        with self.subTest(public_shape="prepare"):
            self.assertIn("plan_digest", plan)
            self.assertEqual(
                {field: plan[field] for field in BINDING_FIELDS}, binding
            )

        status_before_start = self.service.flow_status(flow["flow_id"])
        with self.subTest(public_shape="flow_status_before_start"):
            self.assertTrue(EXPECTED_FLOW_STATUS_FIELDS.issubset(status_before_start))
            self.assertTrue(LEGACY_FLOW_STATUS_FIELDS.isdisjoint(status_before_start))
            self.assertEqual(
                status_before_start["current_plan"]["plan_digest"],
                plan["plan_digest"],
            )
            self.assertNotIn(
                "confirmation_token", status_before_start["current_plan"]
            )

        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "contract-start-success-001",
            **binding,
        )
        status = self._wait(flow["flow_id"], started["job_id"])
        self.assertEqual("succeeded", status["status"])
        with self.subTest(public_shape="download_start"):
            self.assertEqual(
                {field: started[field] for field in BINDING_FIELDS}, binding
            )
            self.assertEqual(started["plan_digest"], plan["plan_digest"])
        with self.subTest(public_shape="job_status"):
            self.assertEqual(status["plan_id"], plan["plan_id"])
            self.assertEqual(
                {field: status[field] for field in BINDING_FIELDS}, binding
            )
            self.assertEqual(status["plan_digest"], plan["plan_digest"])

        status_after_start = self.service.flow_status(flow["flow_id"])
        with self.subTest(public_shape="flow_status_after_start"):
            self.assertTrue(EXPECTED_FLOW_STATUS_FIELDS.issubset(status_after_start))
            self.assertEqual(
                status_after_start["current_job"]["job_id"], started["job_id"]
            )

        archived = self.service.archive(
            flow["flow_id"],
            started["job_id"],
            status["assets"][0]["asset_id"],
            idempotency_key="contract-archive-success-01",
            metadata={"title": "恐龙资料", "collection": "科学", "tags": ["恐龙"]},
        )
        library = self.service.library_search(
            flow["flow_id"], filters={"query": "恐龙"}, limit=20
        )

        outputs = {
            "resource_flow_start": flow,
            "resource_search": search,
            "resource_presentation_save": presentation,
            "resource_selection_save": selection,
            "resource_download_prepare": plan,
            "resource_flow_status": status_after_start,
            "resource_download_start": started,
            "resource_job_status": status,
            "resource_archive": archived,
            "resource_library_search": library,
        }
        for tool_name, output in outputs.items():
            with self.subTest(contract=tool_name):
                self.assert_contract(tool_name, ok(output))

    def test_job_cancel_success_output_matches_contract(self) -> None:
        self.service.close()
        self.service = ResourceService(
            self.settings,
            search_provider=self.provider,
            download_provider=ContractDownloader(
                self.settings.jobs_dir, wait_for_cancel=True
            ),
        )
        state = self._prepare_flow("cancel")
        flow = state["flow"]
        plan = state["plan"]
        binding = state["binding"]
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "contract-start-cancel-0001",
            **binding,
        )
        cancelled = self.service.job_cancel(
            flow["flow_id"],
            started["job_id"],
            "contract-cancel-output-01",
            "user cancelled",
        )
        self.assert_contract("resource_job_cancel", ok(cancelled))

    def test_structured_error_output_matches_schema(self) -> None:
        error = failure(
            DomainError(
                "FLOW_NOT_FOUND",
                "Flow 不存在",
                retryable=False,
                details={"operation": "resource_search"},
            ),
            flow_id="flow_0000000000000000",
        )
        self.assertFalse(error["ok"])
        self.assertEqual("FLOW_NOT_FOUND", error["error"]["code"])
        self.assert_contract("resource_search", error)


if __name__ == "__main__":
    unittest.main()
