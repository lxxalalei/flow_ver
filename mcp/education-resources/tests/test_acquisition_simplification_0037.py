from __future__ import annotations

import inspect
import json
from pathlib import Path
import tempfile
import threading
import unittest

from education_resource_mcp.acquisition import (
    AcquisitionRequest,
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.acquisition.planner import AcquisitionPlanner
from education_resource_mcp.config import Settings
from education_resource_mcp.service import ResourceService, _provider_resource
from education_resource_mcp.storage import Store


class _Materializer:
    def materialize(self, request):  # pragma: no cover - routing registration only
        raise AssertionError("not executed")


class _Downloader:
    def download(self, resource, job_id, strategy, cancel_event):  # pragma: no cover
        raise AssertionError("not executed")


class _SearchProvider:
    def search(self, *args, **kwargs):  # pragma: no cover
        return []

    def browse_creator(self, *args, **kwargs):  # pragma: no cover
        return []


class _InspectionRouter:
    def inspect(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("not executed")


class AcquisitionSimplification0037Tests(unittest.TestCase):
    def test_active_service_initializes_without_capability_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                data_dir=root / "data",
                database_path=root / "data" / "state.sqlite3",
                jobs_dir=root / "data" / "jobs",
                library_dir=root / "library",
            )
            service = ResourceService(
                settings=settings,
                search_provider=_SearchProvider(),
                download_provider=_Downloader(),
                inspection_router=_InspectionRouter(),
            )
            try:
                self.assertIsInstance(service.store, Store)
                self.assertIsInstance(service.acquisition_planner, AcquisitionPlanner)
            finally:
                service.close()

    def test_request_has_no_legacy_authority_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = AcquisitionRequest(
                job_id="job_test_0037",
                resource={"resource_id": "res_test_0037", "platform": "generic"},
                strategy="web_materialize",
                provider_id="generic-web-materializer",
                provider_version="1.0.0",
                planned_scope="primary_resource",
                representation_id="repr_test_0037",
                preferred_container="html",
                cancel_event=threading.Event(),
                jobs_root=Path(directory),
            )
            for deleted in (
                "binding_digest",
                "source_fingerprint",
                "capability_id",
                "descriptor_digest",
                "readiness_snapshot_id",
                "readiness_digest",
                "eligibility_id",
                "eligibility_digest",
            ):
                self.assertFalse(hasattr(request, deleted), deleted)
            with self.assertRaises(TypeError):
                AcquisitionRequest(
                    job_id="job_test_legacy_kwarg",
                    resource={"resource_id": "res_test_legacy_kwarg", "platform": "generic"},
                    strategy="web_materialize",
                    provider_id="generic-web-materializer",
                    provider_version="1.0.0",
                    planned_scope="primary_resource",
                    representation_id="repr_test_legacy_kwarg",
                    preferred_container="html",
                    cancel_event=threading.Event(),
                    jobs_root=Path(directory),
                    binding_digest="legacy",  # type: ignore[call-arg]
                )
        public = request.to_dict()
        self.assertEqual(public["planned_scope"], "primary_resource")
        self.assertEqual(public["strategy"], "web_materialize")

    def test_primary_article_webpage_routes_to_materializer(self) -> None:
        router = AcquisitionRouter(
            [
                ProviderRegistration(
                    provider_id="generic-web-materializer",
                    provider_version="1.0.0",
                    provider=_Materializer(),
                    strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                    scopes=("primary_resource", "landing_page"),
                )
            ]
        )
        planner = AcquisitionPlanner(router)
        items = planner.plan_selection(
            [
                {
                    "resource_id": "res_article_0037",
                    "platform": "generic",
                    "resource_type": "article",
                    "title": "正文网页",
                    "source_url": "https://example.com/article",
                    "metadata": {},
                }
            ],
            [
                {
                    "resolution_id": "resolution_0037",
                    "representations": [
                        {
                            "representation_id": "repr_article_0037",
                            "scope": "primary_resource",
                            "kind": "webpage",
                            "role": "primary",
                            "container": "html",
                            "mime_type": "text/html",
                            "materializable": True,
                            "technical_availability": "available",
                        }
                    ],
                }
            ],
            preferred_container="html",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["planned_scope"], "primary_resource")
        self.assertEqual(items[0]["strategy"], "web_materialize")
        self.assertEqual(items[0]["provider_id"], "generic-web-materializer")
        self.assertNotIn("authority_digest", items[0])
        self.assertNotIn("eligibility_id", items[0])

    def test_smartedu_primary_media_routes_to_exact_provider(self) -> None:
        router = AcquisitionRouter(
            [
                ProviderRegistration(
                    provider_id="smartedu-resource",
                    provider_version="1.0.0",
                    provider=_Downloader(),
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                )
            ]
        )
        planner = AcquisitionPlanner(router)
        cases = (
            ("document", "pdf", "document"),
            ("video", "mp4", "course"),
            ("audio", "mp3", "audio"),
        )
        for kind, container, resource_type in cases:
            with self.subTest(kind=kind):
                items = planner.plan_selection(
                    [
                        {
                            "resource_id": f"res_smartedu_{kind}_0038",
                            "platform": "smartedu",
                            "resource_type": resource_type,
                            "title": "SmartEdu 资源",
                            "source_url": "https://basic.smartedu.cn/resource?contentId=item-1",
                            "metadata": {},
                        }
                    ],
                    [
                        {
                            "resolution_id": f"resolution_smartedu_{kind}_0038",
                            "representations": [
                                {
                                    "representation_id": f"repr_smartedu_{kind}_0038",
                                    "scope": "primary_resource",
                                    "kind": kind,
                                    "role": "primary",
                                    "container": container,
                                    "materializable": True,
                                    "technical_availability": "available",
                                }
                            ],
                        }
                    ],
                    preferred_container="original",
                )
                self.assertEqual("direct_file", items[0]["strategy"])
                self.assertEqual("smartedu-resource", items[0]["provider_id"])
                self.assertEqual("1.0.0", items[0]["provider_version"])
                self.assertEqual("primary_resource", items[0]["planned_scope"])
                self.assertEqual(container, items[0]["representation"]["selected_container"])

    def test_only_smartedu_provider_receives_confirmed_representation_binding(self) -> None:
        item = {
            "resource": {
                "resource_id": "res_smartedu_binding_0038",
                "platform": "smartedu",
                "source_url": "https://basic.smartedu.cn/resource?contentId=item-1",
            },
            "provider_id": "smartedu-resource",
            "representation_id": "repr_smartedu_binding_0038",
        }
        bound = _provider_resource(item, "pdf")
        self.assertEqual(
            {
                "representation_id": "repr_smartedu_binding_0038",
                "container": "pdf",
            },
            bound["_planned_representation"],
        )
        self.assertNotIn("_planned_representation", item["resource"])

        generic = dict(item)
        generic["provider_id"] = "generic-direct"
        self.assertNotIn(
            "_planned_representation",
            _provider_resource(generic, "pdf"),
        )

    def test_active_service_registers_only_exact_smartedu_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                data_dir=root / "data",
                database_path=root / "data" / "state.sqlite3",
                jobs_dir=root / "data" / "jobs",
                library_dir=root / "library",
            )
            service = ResourceService(
                settings=settings,
                search_provider=_SearchProvider(),
                inspection_router=_InspectionRouter(),
            )
            try:
                registry = service.acquisition_router.provider_registry
                self.assertIn(("smartedu-resource", "1.0.0"), registry)
                smartedu_registration = registry[("smartedu-resource", "1.0.0")]
                self.assertEqual(
                    frozenset({AcquisitionStrategy.DIRECT_FILE}),
                    smartedu_registration.strategies,
                )
                self.assertEqual(frozenset({"primary_resource"}), smartedu_registration.scopes)
            finally:
                service.close()

    def test_migration_9_drops_legacy_authority_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.sqlite3")
            with store._connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                plan_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(acquisition_plan_items)"
                    ).fetchall()
                }
                job_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(job_items)"
                    ).fetchall()
                }
                outcome_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(execution_outcomes)"
                    ).fetchall()
                }
        self.assertEqual(version, 9)
        self.assertTrue({"acquisition_plan_items", "job_items", "execution_outcomes"} <= tables)
        self.assertTrue(
            {
                "capability_readiness_snapshots",
                "eligibility_decisions",
                "download_plan_items",
                "job_execution_items",
                "acquisition_outcomes",
            }.isdisjoint(tables)
        )
        deleted = {
            "authority_digest",
            "binding_digest",
            "plan_binding_digest",
            "execution_binding_digest",
            "outcome_digest",
            "readiness_snapshot_id",
            "eligibility_id",
        }
        self.assertFalse(plan_columns & deleted)
        self.assertFalse(job_columns & deleted)
        self.assertFalse(outcome_columns & deleted)

    def test_public_start_signature_has_no_authority_digest(self) -> None:
        parameters = inspect.signature(ResourceService.download_start).parameters
        self.assertNotIn("authority_digest", parameters)

    def test_download_contracts_do_not_expose_authority_chain(self) -> None:
        root = Path(__file__).resolve().parents[1] / "contracts" / "schemas"
        plan = json.loads((root / "plan-item.schema.json").read_text(encoding="utf-8"))
        start = json.loads(
            (root / "tools" / "resource_download_start.schema.json").read_text(
                encoding="utf-8"
            )
        )
        job = json.loads(
            (root / "tools" / "resource_job_status.schema.json").read_text(
                encoding="utf-8"
            )
        )
        actual = json.loads(
            (root / "actual-outcome.schema.json").read_text(encoding="utf-8")
        )
        text = json.dumps([plan, start, job, actual], ensure_ascii=False)
        for deleted in (
            "authority_digest",
            "plan_binding_digest",
            "execution_binding_digest",
            "outcome_digest",
            "eligibility_id",
            "readiness_snapshot_id",
        ):
            self.assertNotIn(deleted, text)


if __name__ == "__main__":
    unittest.main()
