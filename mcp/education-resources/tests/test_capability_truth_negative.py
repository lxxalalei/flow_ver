"""Negative capability-truth gates for capability-bound acquisition.

The fixture in ``fixtures/capability_truth_negative_cases.json`` documents cases
that must never be promoted from search/landing/policy facts into a primary
acquisition.  The runtime tests intentionally exercise only public service,
router, and persistence seams; they do not manufacture a successful download
or relax the authority chain to accommodate legacy behavior.

These are safety gates for 0025.  Until the complete capability chain is wired
through ``resource_inspect -> download_prepare -> download_start -> router``,
some runtime assertions are expected to expose implementation gaps.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from typing import Any, Mapping


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (  # noqa: E402
    AcquisitionRequest,
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.config import Settings  # noqa: E402
from education_resource_mcp.errors import DomainError  # noqa: E402
from education_resource_mcp.inspection import (  # noqa: E402
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
    source_fingerprint,
)
from education_resource_mcp.search import StaticSearchProvider  # noqa: E402
from education_resource_mcp.service import ResourceService  # noqa: E402


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "capability_truth_negative_cases.json"
FIXTURE_VERSION = "capability-truth-negative-v1"
EXPECTED_CASE_IDS = frozenset(
    {
        "search_only_cannot_prepare_primary",
        "landing_only_cannot_prepare_primary",
        "concrete_primary_requires_full_capability_chain",
        "missing_provider_is_not_generic_capability",
        "provider_failure_does_not_fall_back_to_generic",
        "auth_required_blocks_prepare",
        "policy_blocked_blocks_prepare",
        "descriptor_expiry_requires_reprepare",
        "readiness_expiry_requires_reprepare",
        "provider_version_drift_requires_reprepare",
        "source_fingerprint_drift_requires_reprepare",
        "implicit_generic_fallback_is_forbidden",
        "annas_libgen_landing_is_not_concrete_primary",
        "scope_escalation_from_landing_to_primary_is_rejected",
        "legacy_plan_without_capability_bindings_is_not_executable",
    }
)

# Public service errors may become more specific as the registry/readiness
# implementation matures, but every rejection must remain one of these stable
# capability/policy causes rather than returning a Plan or a generic fallback.
PREPARE_REJECTION_CODES = frozenset(
    {
        "CAPABILITY_NOT_DECLARED",
        "CAPABILITY_NOT_READY",
        "CAPABILITY_SCOPE_MISMATCH",
        "CAPABILITY_VERSION_CONFLICT",
        "ELIGIBILITY_EXPIRED",
        "ELIGIBILITY_REQUIRED",
        "POLICY_BLOCKED",
        "PROVIDER_SCOPE_MISMATCH",
        "PROVIDER_UNAVAILABLE",
        "REPRESENTATION_NOT_PRIMARY",
        "RESOLUTION_STALE",
    }
)


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _fixture_case(case_id: str) -> dict[str, Any]:
    for case in _load_fixture()["cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"fixture case is missing: {case_id}")


class _FixtureInspector:
    """Offline inspector that projects only the fixture's inspected facts."""

    inspector_id = "generic"
    version = "1.0.0"
    supported_scopes = ("primary_resource", "representation", "landing_page", "metadata")

    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case
        self.platform_id = str(case["candidate"]["platform"])

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        resolution = self.case["resolution"]
        representation = resolution.get("representation")
        if isinstance(representation, Mapping):
            inspected_representation = dict(representation)
            inspected_representation["scope"] = str(
                resolution.get("scope") or inspected_representation.get("scope") or "representation"
            )
            representations = [inspected_representation]
        else:
            representations = []
        availability = str(resolution["availability"])
        return InspectionResult(
            resolution_status="resolved" if availability != "unknown" else "unresolved",
            resolved_resource={
                "title": str(resource["title"]),
                "resource_type": str(resource["resource_type"]),
                "availability": {"status": availability},
                "representations": representations,
                "metadata": {"fixture_case": str(self.case["id"])},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="fixture",
                inspected_at="2026-08-08T00:00:00Z",
            ),
            failures=[],
        )


class _NeverNetworkDownloader:
    """A service seam that makes an accidental start deterministic and offline."""

    def __init__(self) -> None:
        self.calls = 0

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        self.calls += 1
        raise AssertionError("capability-truth test must not reach a network downloader")


class _CountingDirectProvider:
    """Records forbidden generic-provider attempts without touching the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        self.calls.append((str(resource.get("platform")), str(strategy)))
        raise AssertionError("generic direct provider fallback is forbidden")


class _FailingPlatformProvider:
    def __init__(self) -> None:
        self.calls = 0

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        self.calls += 1
        raise DomainError("UPSTREAM_UNAVAILABLE", "fixture platform provider failed", retryable=True)


class CapabilityTruthFixtureTests(unittest.TestCase):
    """Calibrate the negative corpus itself before using it as a safety gate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = _load_fixture()
        cls.cases = list(cls.fixture["cases"])
        cls.by_id = {case["id"]: case for case in cls.cases}

    def test_fixture_version_and_case_ids_are_exact(self) -> None:
        self.assertEqual(FIXTURE_VERSION, self.fixture["fixture_version"])
        self.assertEqual(EXPECTED_CASE_IDS, set(self.by_id))
        self.assertEqual(len(self.cases), len(self.by_id), "fixture IDs must be unique")

    def test_each_case_has_a_server_truth_expectation(self) -> None:
        for case in self.cases:
            with self.subTest(case_id=case["id"]):
                self.assertIn(case["layer"], {
                    "resolution", "prepare", "readiness", "router", "eligibility",
                    "revalidation", "migration",
                })
                self.assertIsInstance(case["candidate"], dict)
                self.assertIsInstance(case["resolution"], dict)
                self.assertIsInstance(case["expected"], dict)
                expected = case["expected"]
                self.assertIn(expected["prepare"], {"prepared", "rejected"})
                self.assertIn(expected["start"], {"allowed", "rejected", "not_reached"})
                self.assertEqual(expected["generic_fallback"], "forbidden")
                bindings = expected["required_bindings"]
                self.assertTrue(bindings)
                self.assertEqual(len(bindings), len(set(bindings)))

    def test_only_concrete_primary_is_allowed_to_start(self) -> None:
        allowed = [
            case for case in self.cases
            if case["expected"]["primary_allowed"]
        ]
        self.assertEqual(
            ["concrete_primary_requires_full_capability_chain"],
            [case["id"] for case in allowed],
        )
        concrete = allowed[0]
        representation = concrete["resolution"]["representation"]
        self.assertEqual("available", concrete["resolution"]["availability"])
        self.assertEqual("primary_resource", concrete["resolution"]["scope"])
        self.assertEqual("primary", representation["role"])
        self.assertTrue(representation["materializable"])
        self.assertEqual("prepared", concrete["expected"]["prepare"])
        self.assertEqual("allowed", concrete["expected"]["start"])

        for case in self.cases:
            if case is concrete:
                continue
            with self.subTest(case_id=case["id"]):
                self.assertFalse(case["expected"]["primary_allowed"])
                self.assertNotEqual("allowed", case["expected"]["start"])

    def test_fixture_has_distinct_landing_policy_revalidation_and_router_gates(self) -> None:
        landing_cases = {
            "landing_only_cannot_prepare_primary",
            "annas_libgen_landing_is_not_concrete_primary",
            "scope_escalation_from_landing_to_primary_is_rejected",
        }
        for case_id in landing_cases:
            case = self.by_id[case_id]
            representation = case["resolution"]["representation"]
            self.assertEqual("landing_page", case["resolution"]["scope"])
            self.assertEqual("landing", representation["role"])

        self.assertEqual(
            {"auth_required_blocks_prepare", "policy_blocked_blocks_prepare"},
            {
                case["id"]
                for case in self.cases
                if case["layer"] == "eligibility"
            },
        )
        self.assertEqual(
            {
                "descriptor_expiry_requires_reprepare",
                "readiness_expiry_requires_reprepare",
                "provider_version_drift_requires_reprepare",
                "source_fingerprint_drift_requires_reprepare",
            },
            {
                case["id"]
                for case in self.cases
                if case["layer"] == "revalidation"
            },
        )
        self.assertEqual(
            {
                "missing_provider_is_not_generic_capability",
                "provider_failure_does_not_fall_back_to_generic",
                "implicit_generic_fallback_is_forbidden",
            },
            {
                case["id"]
                for case in self.cases
                if case["layer"] in {"readiness", "router"}
                and "provider" in case["id"] or case["id"] == "implicit_generic_fallback_is_forbidden"
            },
        )


class _CapabilityTruthHarness:
    """Shared offline Flow -> Search -> Inspect -> Selection harness."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(
            data_dir=root,
            database_path=root / "database.sqlite",
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_download_bytes=1024 * 1024,
            max_search_results=20,
            max_workers=1,
            plan_ttl_seconds=3600,
        )
        self._services: list[ResourceService] = []

    def tearDown(self) -> None:
        for service in reversed(self._services):
            service.close()
        self.temp.cleanup()

    def _selection_for_case(
        self,
        case_id: str,
        *,
        inspect: bool,
    ) -> tuple[ResourceService, dict[str, Any], dict[str, Any], str]:
        case = _fixture_case(case_id)
        candidate = dict(case["candidate"])
        downloader = _NeverNetworkDownloader()
        provider_status = str((case.get("runtime") or {}).get("provider_status") or "ready")
        registrations = []
        if provider_status not in {"missing", "undeclared"}:
            registrations.append(
                ProviderRegistration(
                    provider_id="generic-direct",
                    provider_version="1.0.0",
                    provider=downloader,
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                )
            )
        service = ResourceService(
            self.settings,
            search_provider=StaticSearchProvider([candidate]),
            inspection_router=InspectionRouter([_FixtureInspector(case)]),
            acquisition_router=AcquisitionRouter(registrations),
        )
        self._services.append(service)
        key_suffix = case_id.replace("_", "-")
        flow = service.flow_start(
            f"captruth-flow-{key_suffix}-0001",
            {"goal": {"topic": candidate["title"]}, "constraints": []},
        )
        search = service.search(
            flow["flow_id"],
            f"captruth-search-{key_suffix}-001",
            [{"platform": candidate["platform"], "queries": [{"query": candidate["title"]}]}],
            filters={},
            limit=5,
        )
        self.assertEqual(1, len(search["candidates"]), case_id)
        resource_id = search["candidates"][0]["resource_id"]
        if inspect:
            service.inspect(
                flow["flow_id"],
                f"captruth-inspect-{key_suffix}-01",
                resource_id,
            )
        presentation = service.presentation_save(
            flow["flow_id"],
            search["result_set_id"],
            [resource_id],
            f"captruth-presentation-{key_suffix}",
        )
        selection = service.selection_save(
            flow["flow_id"],
            f"captruth-selection-{key_suffix}-001",
            presentation["presentation_id"],
            presentation["presented_version"],
            [1],
        )
        return service, flow, selection, resource_id

    def _prepare(self, service: ResourceService, flow: Mapping[str, Any], selection: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
        representation = case["resolution"].get("representation") or {}
        return service.download_prepare(
            str(flow["flow_id"]),
            f"captruth-prepare-{case['id'].replace('_', '-')}-001",
            int(selection["selection_version"]),
            presentation_id=str(selection["presentation_id"]),
            presented_version=int(selection["presented_version"]),
            selection_digest=str(selection["selection_digest"]),
            options={
                "preferred_container": str(representation.get("container") or "pdf"),
                "max_bytes_per_resource": 1024,
                "allow_safe_fallback": True,
            },
        )


class CapabilityTruthServiceGates(_CapabilityTruthHarness, unittest.TestCase):
    """Public preparation gates that must not promote unsafe candidates."""

    def test_search_landing_provider_and_policy_cases_are_structurally_rejected(self) -> None:
        rejected_cases = (
            "search_only_cannot_prepare_primary",
            "landing_only_cannot_prepare_primary",
            "missing_provider_is_not_generic_capability",
            "auth_required_blocks_prepare",
            "policy_blocked_blocks_prepare",
            "implicit_generic_fallback_is_forbidden",
            "annas_libgen_landing_is_not_concrete_primary",
            "scope_escalation_from_landing_to_primary_is_rejected",
        )
        for case_id in rejected_cases:
            with self.subTest(case_id=case_id):
                case = _fixture_case(case_id)
                service, flow, selection, _ = self._selection_for_case(
                    case_id,
                    inspect=case_id != "search_only_cannot_prepare_primary",
                )
                try:
                    outcome: object = self._prepare(service, flow, selection, case)
                except Exception as exc:  # assert structured rather than leak storage exceptions
                    outcome = exc
                self.assertIsInstance(
                    outcome,
                    DomainError,
                    "unsafe capability state must fail prepare as a structured DomainError, "
                    f"not {type(outcome).__name__}",
                )
                if isinstance(outcome, DomainError):
                    self.assertIn(outcome.code, PREPARE_REJECTION_CODES)

    def test_concrete_primary_prepare_binds_the_complete_authority_chain(self) -> None:
        case = _fixture_case("concrete_primary_requires_full_capability_chain")
        service, flow, selection, _ = self._selection_for_case(case["id"], inspect=True)
        try:
            outcome: object = self._prepare(service, flow, selection, case)
        except Exception as exc:
            outcome = exc
        self.assertIsInstance(
            outcome,
            dict,
            "a concrete primary must prepare only after the service creates a bound Plan",
        )
        if not isinstance(outcome, dict):
            return
        plan = outcome
        self.assertEqual("prepared", plan.get("stage"))
        self.assertEqual("capability-binding-v1", plan.get("capability_binding_version"))
        self.assertTrue(
            plan.get("authority_digest"),
            "a prepared Plan must expose its server-generated authority_digest",
        )
        stored_plan = service.store.get_plan(str(plan.get("plan_id") or ""))
        self.assertIsNotNone(stored_plan)
        if stored_plan is None:
            return
        capability_items = stored_plan.get("capability_items")
        self.assertIsInstance(capability_items, list)
        self.assertEqual(1, len(capability_items or []))
        if not capability_items:
            return
        item = capability_items[0]
        self.assertTrue(
            item.get("binding_digest"),
            "each executable Plan item must expose its server-generated binding_digest",
        )
        self.assertEqual("primary_resource", item.get("capability_scope"))
        representation = item.get("representation") or {}
        self.assertEqual("primary", representation.get("role"))
        self.assertTrue(representation.get("materializable"))
        aliases = {
            "resolution_id": ("resolution_id",),
            "representation_id": ("representation_id",),
            "planned_scope": ("planned_scope", "capability_scope"),
            "descriptor_id": ("descriptor_id", "capability_id"),
            "descriptor_digest": ("descriptor_digest",),
            "provider_id": ("provider_id",),
            "provider_version": ("provider_version",),
            "readiness_snapshot_id": ("readiness_snapshot_id", "readiness_id"),
            "eligibility_decision_id": ("eligibility_decision_id", "eligibility_id"),
            "source_fingerprint": ("source_fingerprint",),
        }
        for binding in case["expected"]["required_bindings"]:
            with self.subTest(binding=binding):
                candidates = aliases.get(binding, (binding,))
                self.assertTrue(
                    any(bool(item.get(candidate)) for candidate in candidates),
                    f"Plan authority item must bind {binding}",
                )


class CapabilityTruthRouterGates(unittest.TestCase):
    """Router must never silently let an unrelated provider take over."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.jobs_root = Path(self.temp.name).resolve()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _request(
        self,
        platform: str,
        *,
        provider_id: str,
        provider_version: str = "1.0.0",
    ) -> AcquisitionRequest:
        return AcquisitionRequest(
            job_id="job_capability_truth_router_001",
            resource={
                "resource_id": "res_capabilitytruthrouter0001",
                "platform": platform,
                "title": "Capability truth router fixture",
                "resource_type": "book",
                "source_url": "https://example.com/capability-truth.pdf",
            },
            strategy=AcquisitionStrategy.DIRECT_FILE,
            provider_id=provider_id,
            provider_version=provider_version,
            planned_scope="primary_resource",
            representation_id="repr_capability_truth001",
            binding_digest="a" * 64,
            source_fingerprint=_digest("router-source"),
            capability_id="cap_capability_truth_v1",
            descriptor_version="1.0.0",
            descriptor_digest=_digest("router-descriptor"),
            readiness_snapshot_id="ready_capability_truth_v1",
            readiness_digest=_digest("router-readiness"),
            eligibility_id="elig_capability_truth_v1",
            eligibility_digest=_digest("router-eligibility"),
            preferred_container="pdf",
            max_bytes=1024,
            cancel_event=threading.Event(),
            jobs_root=self.jobs_root,
        )

    @staticmethod
    def _registration(provider: object, provider_id: str) -> ProviderRegistration:
        return ProviderRegistration(
            provider_id=provider_id,
            provider_version="1.0.0",
            provider=provider,  # type: ignore[arg-type]
            strategies=(AcquisitionStrategy.DIRECT_FILE,),
            scopes=("primary_resource",),
        )

    def test_missing_exact_provider_is_not_taken_over_by_generic_direct(self) -> None:
        direct = _CountingDirectProvider()
        result = AcquisitionRouter([]).acquire(
            self._request("fixture-no-provider", provider_id="fixture-no-provider")
        )
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.failure)
        if result.failure is not None:
            self.assertEqual(result.failure.code, "PROVIDER_UNAVAILABLE")
        self.assertIsNone(result.provider_id)
        self.assertEqual([], direct.calls, "generic provider must not be an implicit fallback")

    def test_failed_exact_provider_does_not_fall_back_to_generic_direct(self) -> None:
        direct = _CountingDirectProvider()
        platform = _FailingPlatformProvider()
        result = AcquisitionRouter([
            self._registration(direct, "generic-direct"),
            self._registration(platform, "fixture-provider-fails"),
        ]).acquire(
            self._request("different-platform-is-irrelevant", provider_id="fixture-provider-fails")
        )
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.failure)
        if result.failure is not None:
            self.assertEqual(result.failure.code, "UPSTREAM_UNAVAILABLE")
        self.assertEqual(1, platform.calls)
        self.assertEqual([], direct.calls, "provider failure must not escalate to a generic direct route")
        self.assertEqual(result.provider_id, "fixture-provider-fails")


class CapabilityTruthPersistenceGates(_CapabilityTruthHarness, unittest.TestCase):
    """Plan/start checks for stale or legacy authority chains.

    These use the Store seam deliberately: revalidation lives at the durable
    plan/job boundary and must still reject a resumed or historical plan even
    if a caller never returns through the normal UI flow.
    """

    def _authority_plan(
        self,
        *,
        readiness_expires_at: str = "2030-01-01T00:00:00+00:00",
        eligibility_expires_at: str = "2090-01-01T00:00:00+00:00",
        readiness_provider_version: str = "1.0.0",
        plan_provider_version: str = "1.0.0",
        plan_descriptor_digest: str | None = None,
        plan_source_fingerprint: str | None = None,
    ) -> tuple[ResourceService, dict[str, Any], dict[str, Any]]:
        case = _fixture_case("concrete_primary_requires_full_capability_chain")
        service, flow, selection, resource_id = self._selection_for_case(case["id"], inspect=True)
        resource = service.store.get_resources(str(flow["flow_id"]), [resource_id])[0]
        fingerprint = "sha256:" + source_fingerprint(resource)
        descriptor_digest = _digest("capability-truth-descriptor")
        readiness_id = "ready_capability_truth_0001"
        eligibility_id = "elig_capability_truth_0001"
        readiness = service.store.save_capability_readiness_snapshot(
            {
                "readiness_snapshot_id": readiness_id,
                "capability_id": "capability_truth_primary",
                "descriptor_version": "1.0.0",
                "descriptor_digest": descriptor_digest,
                "registry_version": "1.0.0",
                "registry_digest": _digest("capability-truth-registry"),
                "platform_id": resource["platform"],
                "capability_scope": "primary_resource",
                "strategy": "direct_file",
                "provider_id": "fixture-primary-provider",
                "provider_version": readiness_provider_version,
                "status": "ready",
                "observed_at": "2026-08-08T00:00:00+00:00",
                "expires_at": readiness_expires_at,
                "issues": [],
            }
        )
        eligibility = service.store.save_eligibility_decision(
            {
                "eligibility_id": eligibility_id,
                "flow_id": flow["flow_id"],
                "resource_id": resource_id,
                "resolution_id": "resolve_capability_truth_0001",
                "representation_id": "repr_capability_truth_0001",
                "action": "download",
                "status": "eligible",
                "policy_class": "fixture-public",
                "reason_codes": [],
                "source_fingerprint": fingerprint,
                "capability_id": "capability_truth_primary",
                "descriptor_digest": descriptor_digest,
                "readiness_snapshot_id": readiness_id,
                "evaluated_at": "2026-08-08T00:00:00+00:00",
                "expires_at": eligibility_expires_at,
            }
        )
        item = {
            "resource_id": resource_id,
            "resolution_id": "resolve_capability_truth_0001",
            "representation_id": "repr_capability_truth_0001",
            "capability_scope": "primary_resource",
            "strategy": "direct_file",
            "provider_id": "fixture-primary-provider",
            "provider_version": plan_provider_version,
            "capability_id": "capability_truth_primary",
            "descriptor_version": "1.0.0",
            "descriptor_digest": plan_descriptor_digest or descriptor_digest,
            "registry_version": "1.0.0",
            "registry_digest": _digest("capability-truth-registry"),
            "readiness_snapshot_id": readiness_id,
            "readiness_digest": readiness["snapshot_digest"],
            "eligibility_id": eligibility_id,
            "eligibility_digest": eligibility["decision_digest"],
            "source_fingerprint": plan_source_fingerprint or fingerprint,
            "representation": {
                "kind": "document",
                "container": "pdf",
                "mime_type": "application/pdf",
                "role": "primary",
                "materializable": True,
                "requires_auth": False,
            },
            "position": 0,
        }
        plan = service.store.create_plan(
            str(flow["flow_id"]),
            str(selection["presentation_id"]),
            int(selection["presented_version"]),
            int(selection["selection_version"]),
            str(selection["selection_digest"]),
            {
                "strategy": "direct",
                "max_bytes": 1024,
                "preferred_container": "pdf",
                "allow_safe_fallback": False,
            },
            "fixture-confirmation-token",
            "fixture-confirmation-hash",
            "2099-01-01T00:00:00+00:00",
            idempotency_key="captruth-store-prepare-0001",
            request_hash=_digest("capability-truth-store-prepare"),
            capability_items=[item],
        )
        return service, plan, item

    @staticmethod
    def _start_bindings(plan: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "presentation_id": plan["presentation_id"],
            "presented_version": plan["presented_version"],
            "selection_version": plan["selection_version"],
            "selection_digest": plan["selection_digest"],
            "plan_digest": plan["plan_digest"],
            "authority_digest": plan["authority_digest"],
        }

    def _reserve(self, service: ResourceService, plan: Mapping[str, Any], *, now: str) -> tuple[dict[str, Any], bool]:
        # Store-level starts require an explicit fresh execution authority;
        # plan capability items remain historical confirmation evidence only.
        persisted_plan = service.store.get_plan(str(plan["plan_id"]))
        assert persisted_plan is not None
        execution_items = []
        for item in persisted_plan["capability_items"]:
            execution = dict(item)
            execution.pop("binding_digest", None)
            execution_items.append(execution)
        return service.store.reserve_job(
            str(plan["plan_id"]),
            "fixture-confirmation-hash",
            "captruth-store-start-0001",
            _digest("capability-truth-store-start"),
            now,
            bindings=self._start_bindings(plan),
            execution_bindings=execution_items,
        )

    def test_readiness_expiry_requires_reprepare_before_start(self) -> None:
        service, plan, _ = self._authority_plan(
            readiness_expires_at="2030-01-01T00:00:00+00:00"
        )
        with self.assertRaisesRegex(RuntimeError, "readiness_expired"):
            self._reserve(service, plan, now="2031-01-01T00:00:00+00:00")

    def test_descriptor_and_source_fingerprint_drift_require_reprepare_before_start(self) -> None:
        cases = (
            (
                "descriptor_expiry_requires_reprepare",
                {"plan_descriptor_digest": _digest("descriptor-after-drift")},
            ),
            (
                "source_fingerprint_drift_requires_reprepare",
                {"plan_source_fingerprint": _digest("source-after-drift")},
            ),
        )
        for case_id, mutation in cases:
            with self.subTest(case_id=case_id):
                service, plan, _ = self._authority_plan(**mutation)
                with self.assertRaisesRegex(RuntimeError, "capability_binding_conflict"):
                    self._reserve(service, plan, now="2027-01-01T00:00:00+00:00")

    def test_provider_version_drift_requires_reprepare_before_start(self) -> None:
        service, plan, _ = self._authority_plan(
            readiness_provider_version="2.0.0",
            plan_provider_version="1.0.0",
        )
        with self.assertRaisesRegex(RuntimeError, "capability_binding_conflict"):
            self._reserve(service, plan, now="2027-01-01T00:00:00+00:00")

    def test_legacy_plan_without_capability_items_is_not_executable(self) -> None:
        service, plan, _ = self._authority_plan()
        # Simulate a pre-migration record.  This direct test setup is not a
        # production API: it proves that an old persisted plan cannot become
        # executable merely because it still has a valid confirmation token.
        with service.store.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM download_plan_items WHERE plan_id = ?", (plan["plan_id"],)
            )
        with self.assertRaisesRegex(RuntimeError, "capability_binding_missing"):
            self._reserve(service, plan, now="2027-01-01T00:00:00+00:00")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
