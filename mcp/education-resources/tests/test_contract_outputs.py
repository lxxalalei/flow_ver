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
CONTRACTS_ROOT = SERVICE_ROOT / "contracts" / "v1"
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.errors import DomainError, failure, ok
from education_resource_mcp.models import FlowIntent
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.service import ResourceService
from pydantic import ValidationError


class ContractDownloader:
    def __init__(self, jobs_dir: Path, wait_for_cancel: bool = False) -> None:
        self.jobs_dir = jobs_dir
        self.wait_for_cancel = wait_for_cancel

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        if self.wait_for_cancel:
            if cancel_event.wait(2):
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
        provider = StaticSearchProvider(
            [
                {
                    "platform": "generic",
                    "title": "儿童恐龙资料",
                    "source_url": "https://example.com/dinosaur",
                    "resource_type": "article",
                    "summary": "公开资料",
                    "metadata": {"language": "zh-CN"},
                }
            ]
        )
        self.provider = provider
        self.service = ResourceService(
            self.settings,
            search_provider=provider,
            download_provider=ContractDownloader(self.settings.jobs_dir),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def test_teacher_is_not_an_active_audience(self) -> None:
        schema = json.loads(
            (
                CONTRACTS_ROOT
                / "schemas/tools/resource_flow_start.schema.json"
            ).read_text(encoding="utf-8")
        )
        audience_values = schema["$defs"]["input"]["properties"]["intent"][
            "properties"
        ]["audience"]["enum"]
        self.assertNotIn("teacher", audience_values)
        with self.assertRaises(ValidationError):
            FlowIntent(topic="恐龙", audience="teacher")

    def assert_contract(self, tool_name: str, instance: dict) -> None:
        path = (
            CONTRACTS_ROOT
            / f"schemas/tools/{tool_name}.schema.json"
        )
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            schema, registry=self.registry, format_checker=FormatChecker()
        )
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
        self.assertEqual([], [error.message for error in errors])

    def _wait(self, flow_id: str, job_id: str) -> dict:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = self.service.job_status(flow_id, job_id)
            if result["status"] in {"succeeded", "failed", "cancelled"}:
                return result
            time.sleep(0.01)
        self.fail("job timeout")

    def test_success_outputs_match_all_non_cancel_contracts(self) -> None:
        flow = self.service.flow_start(
            "contract-flow-key-01", {"topic": "恐龙", "audience": "primary"}
        )
        self.assert_contract("resource_flow_start", ok(flow))

        search = self.service.search(
            flow["flow_id"], "contract-search-001", "恐龙", limit=20
        )
        self.assert_contract("resource_search", ok(search))
        resource_id = search["resources"][0]["resource_id"]

        selection = self.service.selection_save(
            flow["flow_id"],
            "contract-select-001",
            search["presented_version"],
            [resource_id],
        )
        self.assert_contract("resource_selection_save", ok(selection))

        plan = self.service.download_prepare(
            flow["flow_id"],
            "contract-prepare-01",
            selection["selection_version"],
        )
        self.assert_contract("resource_download_prepare", ok(plan))

        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "contract-start-0001",
        )
        self.assert_contract("resource_download_start", ok(started))
        status = self._wait(flow["flow_id"], started["job_id"])
        self.assert_contract("resource_job_status", ok(status))

        archived = self.service.archive(
            flow["flow_id"],
            started["job_id"],
            status["assets"][0]["asset_id"],
            idempotency_key="contract-archive-01",
            metadata={"title": "恐龙资料", "collection": "科学", "tags": ["恐龙"]},
        )
        self.assert_contract("resource_archive", ok(archived))
        library = self.service.library_search(flow["flow_id"], limit=20)
        self.assert_contract("resource_library_search", ok(library))

    def test_cancel_and_error_outputs_match_contracts(self) -> None:
        self.service.close()
        self.service = ResourceService(
            self.settings,
            search_provider=self.provider,
            download_provider=ContractDownloader(
                self.settings.jobs_dir, wait_for_cancel=True
            ),
        )
        flow = self.service.flow_start(
            "contract-flow-key-02", {"topic": "恐龙", "audience": "primary"}
        )
        search = self.service.search(
            flow["flow_id"], "contract-search-002", "恐龙", limit=20
        )
        selection = self.service.selection_save(
            flow["flow_id"],
            "contract-select-002",
            search["presented_version"],
            [search["resources"][0]["resource_id"]],
        )
        plan = self.service.download_prepare(
            flow["flow_id"], "contract-prepare-02", selection["selection_version"]
        )
        started = self.service.download_start(
            flow["flow_id"],
            plan["plan_id"],
            plan["confirmation_token"],
            "contract-start-0002",
        )
        cancelled = self.service.job_cancel(
            flow["flow_id"],
            started["job_id"],
            "contract-cancel-0001",
            "user cancelled",
        )
        self.assert_contract("resource_job_cancel", ok(cancelled))

        error = failure(
            DomainError("FLOW_NOT_FOUND", "Flow 不存在"),
            flow_id="flow_0000000000000000",
        )
        self.assert_contract("resource_search", error)


if __name__ == "__main__":
    unittest.main()
