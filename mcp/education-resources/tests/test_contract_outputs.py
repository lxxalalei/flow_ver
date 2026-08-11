from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from e2e_stdio_client import build_fixture_subprocess_environment


SERVICE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SERVICE_ROOT.parents[1]
CONTRACTS_ROOT = SERVICE_ROOT / "contracts"
CATALOG_PATH = CONTRACTS_ROOT / "tool-catalog.json"
SCHEMA_ROOT = CONTRACTS_ROOT / "schemas"
SERVER_PATH = SERVICE_ROOT / "src" / "education_resource_mcp" / "server.py"
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXPECTED_CATALOG_VERSION = "1.5.0"
EXPECTED_CONTRACT_VERSION = "1.0.0"
EXPECTED_TOOL_NAMES = (
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
KEY_DOCUMENTS = (
    WORKSPACE_ROOT / "README.md",
    WORKSPACE_ROOT / "TOOLS.md",
    WORKSPACE_ROOT / "docs" / "DEVELOPMENT_PLAN.md",
    SERVICE_ROOT / "README.md",
    CONTRACTS_ROOT / "README.md",
    CONTRACTS_ROOT / "domain-contract.md",
    CONTRACTS_ROOT / "compatibility.md",
)
STALE_DOCUMENT_PATTERNS = (
    re.compile(r"contracts/v2"),
    re.compile(r"\b2\.0\.0\b"),
    re.compile(r"11\s*(?:个工具|tools)", re.IGNORECASE),
)
HISTORICAL_OR_NEGATED_DOCUMENT_MARKERS = (
    "历史",
    "过渡",
    "迁移",
    "旧",
    "不存在",
    "不是",
    "不代表",
    "retired",
    "legacy",
    "not current",
)


def module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError):
        return False


MCP_REQUIRED_MODULES = (
    "mcp.server",
    "mcp.client.session",
    "mcp.client.stdio",
    "anyio",
)
MCP_MISSING_MODULES = tuple(
    module_name
    for module_name in MCP_REQUIRED_MODULES
    if not module_available(module_name)
)
MCP_AVAILABLE = not MCP_MISSING_MODULES

try:
    from education_resource_mcp.acquisition import (
        AcquisitionRouter,
        AcquisitionStrategy,
        ProviderRegistration,
    )
    from education_resource_mcp.acquisition.web_fetch import FetchResult
    from education_resource_mcp.acquisition.web_materializer import WebMaterializer
    from education_resource_mcp.config import Settings
    from education_resource_mcp.errors import DomainError, failure, ok
    from education_resource_mcp.inspection import (
        InspectionResult,
        InspectionRouter,
        build_default_inspection,
    )
    from education_resource_mcp.models import FlowTask
    from education_resource_mcp.search import StaticSearchProvider
    from education_resource_mcp.service import ResourceService
except ImportError as exc:
    RUNTIME_AVAILABLE = False
    RUNTIME_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    RUNTIME_AVAILABLE = True
    RUNTIME_IMPORT_ERROR = ""


TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}
EXPECTED_FLOW_STATUS_FIELDS = {
    "current_result_set",
    "current_presentation",
    "current_selection",
    "current_plan",
    "current_job",
    "current_resolutions",
}
LEGACY_FLOW_STATUS_FIELDS = {"latest_result_set", "active_plan", "latest_job"}
BINDING_FIELDS = {
    "presentation_id",
    "presented_version",
    "selection_version",
    "selection_digest",
}
PLAN_ITEM_AUTHORITY_FIELDS = {
    "representation_id",
    "planned_scope",
    "planned_strategy",
    "planned_provider",
    "capability",
    "eligibility",
    "binding_digest",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_json_pointer(document: object, pointer: str) -> object:
    if pointer == "":
        return document
    value = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        else:
            value = value[token]
    return value


def resolve_catalog_schema_reference(reference: str) -> tuple[Path, object]:
    relative_path, separator, pointer = reference.partition("#")
    if not separator or not relative_path or not pointer.startswith("/"):
        raise ValueError(f"invalid catalog schema reference: {reference}")
    path = (CONTRACTS_ROOT / relative_path).resolve()
    contracts_root = CONTRACTS_ROOT.resolve()
    if not path.is_relative_to(contracts_root):
        raise ValueError(f"catalog schema reference escapes contracts root: {reference}")
    document = load_json(path)
    return path, resolve_json_pointer(document, pointer)


def iter_schema_refs(value: object, location: tuple[str, ...] = ()):
    if isinstance(value, dict):
        if "$ref" in value:
            yield location + ("$ref",), value["$ref"]
        for key, child in value.items():
            yield from iter_schema_refs(child, location + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_schema_refs(child, location + (str(index),))


def resolve_local_schema_reference(
    source_path: Path, reference: str
) -> tuple[Path, object, str] | None:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference) or reference.startswith("//"):
        return None
    relative_path, separator, fragment = reference.partition("#")
    target_path = (
        source_path
        if not relative_path
        else (source_path.parent / relative_path).resolve()
    )
    contracts_root = CONTRACTS_ROOT.resolve()
    if not target_path.is_relative_to(contracts_root):
        raise ValueError(f"reference escapes contracts root: {reference}")
    if not target_path.is_file():
        raise FileNotFoundError(target_path)
    target_document = load_json(target_path)
    pointer = fragment if separator else ""
    if pointer and not pointer.startswith("/"):
        raise ValueError(f"invalid JSON Pointer fragment: {reference}")
    return target_path, target_document, pointer


def stdio_parameters(data_dir: str):
    from mcp.client.stdio import StdioServerParameters

    return StdioServerParameters(
        command=sys.executable,
        args=[str(SERVICE_ROOT / "tests" / "stdio_fixture_server.py")],
        cwd=SERVICE_ROOT,
        env=build_fixture_subprocess_environment(data_dir),
    )


class ContractCatalogConsistencyTests(unittest.TestCase):
    def test_catalog_has_current_version_and_exact_13_tools(self) -> None:
        catalog = load_json(CATALOG_PATH)
        names = [tool["name"] for tool in catalog["tools"]]

        self.assertEqual(EXPECTED_CATALOG_VERSION, catalog["catalog_version"])
        self.assertEqual(EXPECTED_CONTRACT_VERSION, catalog["contract_version"])
        self.assertEqual(13, len(names))
        self.assertEqual(EXPECTED_TOOL_NAMES, tuple(names))
        self.assertEqual(13, len(set(names)))
        self.assertIn("resource_browse_creator", names)
        self.assertIn("resource_inspect", names)

    def test_catalog_instance_matches_catalog_schema(self) -> None:
        catalog_schema = load_json(SCHEMA_ROOT / "tool-catalog.schema.json")
        catalog = load_json(CATALOG_PATH)
        validator = Draft202012Validator(
            catalog_schema,
            registry=build_registry(),
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(catalog),
            key=lambda error: list(error.absolute_path),
        )
        messages = [
            f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors
        ]
        self.assertEqual([], messages)

    def test_all_declared_schemas_exist_parse_and_resolve(self) -> None:
        catalog = load_json(CATALOG_PATH)
        schema_paths = sorted(SCHEMA_ROOT.rglob("*.schema.json"))
        self.assertGreater(len(schema_paths), 0)

        for path in schema_paths:
            with self.subTest(schema=path.relative_to(CONTRACTS_ROOT)):
                document = load_json(path)
                Draft202012Validator.check_schema(document)

        for tool in catalog["tools"]:
            for field in ("input_schema", "output_schema"):
                reference = tool[field]
                with self.subTest(tool=tool["name"], schema_field=field):
                    relative_path = reference.partition("#")[0]
                    path = (CONTRACTS_ROOT / relative_path).resolve()
                    self.assertTrue(path.is_file(), reference)
                    resolved_path, fragment = resolve_catalog_schema_reference(reference)
                    self.assertEqual(path, resolved_path)
                    self.assertIsNotNone(fragment)

    def test_all_local_schema_refs_resolve_to_files_and_json_pointers(self) -> None:
        schema_paths = sorted(SCHEMA_ROOT.rglob("*.schema.json"))
        for source_path in schema_paths:
            document = load_json(source_path)
            for location, reference in iter_schema_refs(document):
                with self.subTest(
                    schema=source_path.relative_to(CONTRACTS_ROOT),
                    location="/" + "/".join(location),
                    reference=reference,
                ):
                    self.assertIsInstance(reference, str)
                    if not isinstance(reference, str):
                        continue
                    if re.match(
                        r"^[A-Za-z][A-Za-z0-9+.-]*:", reference
                    ) or reference.startswith("//"):
                        continue
                    try:
                        resolved = resolve_local_schema_reference(
                            source_path, reference
                        )
                        self.assertIsNotNone(resolved)
                        if resolved is None:
                            continue
                        _, target_document, pointer = resolved
                        resolve_json_pointer(target_document, pointer)
                    except Exception as exc:
                        self.fail(
                            f"{source_path.relative_to(CONTRACTS_ROOT)}"
                            f" / {'/'.join(location)} / {reference}: "
                            f"{type(exc).__name__}: {exc}"
                        )

    def test_static_server_registration_matches_catalog(self) -> None:
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"), filename=str(SERVER_PATH))
        registered_names = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            ):
                registered_names.append(node.name)

        self.assertEqual(13, len(registered_names))
        self.assertEqual(set(EXPECTED_TOOL_NAMES), set(registered_names))
        self.assertIn("resource_browse_creator", registered_names)

    def test_key_documents_do_not_claim_retired_contract_as_current(self) -> None:
        violations = []
        for path in KEY_DOCUMENTS:
            self.assertTrue(path.is_file(), path)
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                normalized_line = line.casefold()
                if any(
                    marker.casefold() in normalized_line
                    for marker in HISTORICAL_OR_NEGATED_DOCUMENT_MARKERS
                ):
                    continue
                for pattern in STALE_DOCUMENT_PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            f"{path.relative_to(WORKSPACE_ROOT)}:{line_number}: "
                            f"{pattern.pattern}"
                        )
        self.assertEqual([], violations)

    def test_server_tools_list_matches_catalog(self) -> None:
        if not MCP_AVAILABLE:
            self.skipTest(
                "MCP tools/list dependencies unavailable: "
                + ", ".join(MCP_MISSING_MODULES)
            )

        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        catalog = load_json(CATALOG_PATH)
        catalog_tools = {tool["name"]: tool for tool in catalog["tools"]}

        async def run() -> None:
            with tempfile.TemporaryDirectory() as data_dir:
                async with stdio_client(stdio_parameters(data_dir)) as (
                    read_stream,
                    write_stream,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        listed_names = [tool.name for tool in listed.tools]
                        self.assertEqual(13, len(listed_names))
                        self.assertEqual(set(catalog_tools), set(listed_names))

                        for tool in listed.tools:
                            catalog_entry = catalog_tools[tool.name]
                            _, expected_input_schema = resolve_catalog_schema_reference(
                                catalog_entry["input_schema"]
                            )
                            self.assertEqual(
                                set(expected_input_schema.get("required", [])),
                                set(tool.input_schema.get("required", [])),
                                tool.name,
                            )
                            self.assertEqual(
                                set(expected_input_schema.get("properties", {})),
                                set(tool.input_schema.get("properties", {})),
                                tool.name,
                            )

        anyio.run(run)


class ContractLandingFixtureFetcher:
    """Offline HTML source used by the real generic web materializer."""

    def __init__(self, *, wait_for_cancel: bool = False) -> None:
        self.wait_for_cancel = wait_for_cancel
        self.started = threading.Event()

    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        self.started.set()
        if self.wait_for_cancel:
            if cancel_event is None:
                raise AssertionError("materializer must provide a cancellation event")
            if not cancel_event.wait(2):
                raise AssertionError("fixture materializer did not receive cancellation")
            raise DomainError("JOB_CANCELLED", "cancelled")
        html_bytes = (
            "<html><body><article><h1>儿童恐龙资料</h1>"
            "<p>这是一份静态、可读的恐龙入门资料。</p>"
            "</article></body></html>"
        ).encode("utf-8")
        return FetchResult(url, 200, "text/html", html_bytes, {})


class ContractLandingFixtureInspector:
    """Offline evidence matching the deployed generic landing capability."""

    platform_id = "generic"
    inspector_id = "generic"
    version = "1.0.0"
    supported_scopes = ("landing_page",)

    def inspect(self, resource: dict) -> InspectionResult:
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": resource["title"],
                "resource_type": resource["resource_type"],
                "availability": {"status": "available"},
                "representations": [
                    {
                        "scope": "landing_page",
                        "kind": "webpage",
                        "container": "html",
                        "mime_type": "text/html",
                        "role": "landing",
                        "materializable": True,
                        "technical_availability": "available",
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                "generic",
                version="1.0.0",
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-09T00:00:00Z",
            ),
            failures=[],
        )


class CreatorSearchProvider:
    """Minimal deterministic provider for the creator-browse contract test."""

    def search(
        self, search_tasks: list[dict], limit: int
    ) -> tuple[list[dict], list[dict]]:
        return [], []

    def search_creator(
        self, platform: str, creator_id: str, limit: int
    ) -> tuple[list[dict], list[dict]]:
        resource = {
            "platform": platform,
            "title": "创作者示例视频",
            "source_url": f"https://example.com/{platform}/{creator_id}/video-1",
            "resource_type": "video",
            "summary": "用于契约测试的创作者内容",
            "metadata": {"author": creator_id, "language": "zh-CN"},
        }
        platform_run = {
            "platform": platform,
            "status": "succeeded",
            "query_runs": [
                {
                    "query": f"creator:{creator_id}",
                    "candidate_count": 1,
                    "failure_count": 0,
                }
            ],
        }
        return [resource][:limit], [platform_run]


def build_registry() -> Registry:
    registry = Registry()
    for path in CONTRACTS_ROOT.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        identifier = document.get("$id")
        if identifier:
            registry = registry.with_resource(identifier, Resource.from_contents(document))
    return registry


@unittest.skipUnless(
    RUNTIME_AVAILABLE,
    f"service runtime dependencies unavailable: {RUNTIME_IMPORT_ERROR}",
)
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
        self.service = self._build_service(self.provider)

    def _build_service(
        self, search_provider, *, wait_for_cancel: bool = False
    ) -> ResourceService:
        self.fixture_fetcher = ContractLandingFixtureFetcher(
            wait_for_cancel=wait_for_cancel
        )
        return ResourceService(
            self.settings,
            search_provider=search_provider,
            acquisition_router=AcquisitionRouter(
                [
                    ProviderRegistration(
                        provider_id="generic-web-materializer",
                        provider_version="1.0.0",
                        provider=WebMaterializer(fetcher=self.fixture_fetcher),
                        strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                        scopes=("landing_page",),
                    ),
                ]
            ),
            inspection_router=InspectionRouter([ContractLandingFixtureInspector()]),
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

    def _prepare_flow(self, key_suffix: str) -> dict[str, object]:
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
        inspections = [
            self.service.inspect(
                flow["flow_id"],
                f"contract-inspect-{key_suffix}-{position:03d}",
                resource_id,
            )
            for position, resource_id in enumerate(displayed, start=1)
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
            "displayed": displayed,
            "inspections": inspections,
            "presentation": presentation,
            "selection": selection,
            "binding": binding,
            "plan": plan,
        }

    def test_success_outputs_match_all_contracts_except_cancel(self) -> None:
        state = self._prepare_flow("success")
        flow = state["flow"]
        search = state["search"]
        inspections = state["inspections"]
        presentation = state["presentation"]
        selection = state["selection"]
        binding = state["binding"]
        plan = state["plan"]

        with self.subTest(public_shape="search"):
            self.assertIn("candidates", search)
            self.assertEqual(flow["task_version"], search["task_version"])
        with self.subTest(public_shape="resource_inspect"):
            self.assertEqual(2, len(inspections))
            for inspection in inspections:
                self.assertEqual("generic", inspection["inspection"]["inspector_id"])
                self.assertEqual("1.0.0", inspection["inspection"]["version"])
                self.assertEqual(
                    "landing_page",
                    inspection["resolved_resource"]["representations"][0]["scope"],
                )
                self.assert_contract("resource_inspect", ok(inspection))
        with self.subTest(public_shape="presentation"):
            self.assertIn("items", presentation)
            self.assertIn("empty", presentation)
            self.assertNotIn("displayed_items", presentation)
        with self.subTest(public_shape="prepare"):
            self.assertIn("plan_digest", plan)
            self.assertIn("authority_digest", plan)
            self.assertEqual(
                "capability-binding-v1", plan["capability_binding_version"]
            )
            self.assertEqual(
                {field: plan[field] for field in BINDING_FIELDS}, binding
            )
            item = plan["items"][0]
            self.assertTrue(PLAN_ITEM_AUTHORITY_FIELDS.issubset(item))
            self.assertEqual("landing_page", item["planned_scope"])
            self.assertEqual("web_materialize", item["planned_strategy"])
            self.assertEqual(
                {
                    "provider_id": "generic-web-materializer",
                    "version": "1.0.0",
                    "scope": "landing_page",
                },
                item["planned_provider"],
            )
            self.assertEqual(
                "cap_generic_webpage_landing_materialize_v1",
                item["capability"]["capability_id"],
            )

        status_before_start = self.service.flow_status(flow["flow_id"])
        with self.subTest(public_shape="flow_status_before_start"):
            self.assertTrue(EXPECTED_FLOW_STATUS_FIELDS.issubset(status_before_start))
            self.assertTrue(LEGACY_FLOW_STATUS_FIELDS.isdisjoint(status_before_start))
            self.assertEqual(
                status_before_start["current_plan"]["plan_digest"],
                plan["plan_digest"],
            )
            self.assertEqual(
                status_before_start["current_plan"]["authority_digest"],
                plan["authority_digest"],
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
            plan_digest=plan["plan_digest"],
            authority_digest=plan["authority_digest"],
        )
        status = self._wait(flow["flow_id"], started["job_id"])
        self.assertEqual("succeeded", status["status"])
        with self.subTest(public_shape="download_start"):
            self.assertEqual(
                {field: started[field] for field in BINDING_FIELDS}, binding
            )
            self.assertEqual(started["plan_digest"], plan["plan_digest"])
            self.assertEqual(started["authority_digest"], plan["authority_digest"])
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
            self.assertEqual(
                status_after_start["current_job"]["authority_digest"],
                plan["authority_digest"],
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

        with self.service.store.transaction(immediate=True) as connection:
            outcome_row = connection.execute(
                "SELECT * FROM acquisition_outcomes WHERE job_id = ?",
                (started["job_id"],),
            ).fetchone()
            assert outcome_row is not None
            legacy_outcome = self.service.store._decode_acquisition_outcome(outcome_row)
            legacy_outcome["execution_binding_digest"] = None
            legacy_outcome.pop("outcome_digest", None)
            connection.execute(
                """
                UPDATE acquisition_outcomes
                SET execution_binding_digest = NULL, outcome_digest = ?
                WHERE outcome_id = ?
                """,
                (
                    self.service.store._request_digest(legacy_outcome),
                    outcome_row["outcome_id"],
                ),
            )
            connection.execute(
                "DELETE FROM job_execution_items WHERE job_id = ?",
                (started["job_id"],),
            )
        legacy_status = self.service.job_status(flow["flow_id"], started["job_id"])
        self.assertTrue(legacy_status["outcomes"])
        self.assertNotIn("execution", legacy_status["outcomes"][0])
        self.assert_contract("resource_job_status", ok(legacy_status))

    def test_job_cancel_success_output_matches_contract(self) -> None:
        self.service.close()
        self.service = self._build_service(self.provider, wait_for_cancel=True)
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
            plan_digest=plan["plan_digest"],
            authority_digest=plan["authority_digest"],
        )
        self.assertTrue(
            self.fixture_fetcher.started.wait(1),
            "fixture materializer did not start before cancellation",
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

    def test_browse_creator_success_output_matches_contract(self) -> None:
        self.service.close()
        self.service = self._build_service(CreatorSearchProvider())
        flow = self.service.flow_start(
            "contract-browse-flow-0001", self._flow_task()
        )
        result = self.service.browse_creator(
            flow["flow_id"],
            "contract-browse-creator-0001",
            "bilibili",
            "creator-0001",
            task_version=flow["task_version"],
            limit=1,
        )

        self.assertEqual("reviewing", result["stage"])
        self.assertEqual(1, len(result["candidates"]))
        self.assert_contract("resource_browse_creator", ok(result))


if __name__ == "__main__":
    unittest.main()
