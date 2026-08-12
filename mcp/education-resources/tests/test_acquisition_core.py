from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (  # noqa: E402
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionRouter,
    AcquisitionStrategy,
    Artifact,
    ArtifactBundle,
    ProviderRegistration,
)
from education_resource_mcp.downloader import DownloadResult  # noqa: E402
from education_resource_mcp.errors import DomainError  # noqa: E402


def _download_result(path: Path, media_type: str = "text/plain") -> DownloadResult:
    payload = path.read_bytes()
    return DownloadResult(
        path=path,
        byte_size=len(payload),
        media_type=media_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        filename=path.name,
    )


def _registration(
    provider: object,
    *,
    provider_id: str = "test-provider",
    version: str = "1.0.0",
    strategies: tuple[AcquisitionStrategy, ...] = (AcquisitionStrategy.DIRECT_FILE,),
    scopes: tuple[str, ...] = ("primary_resource",),
) -> ProviderRegistration:
    return ProviderRegistration(
        provider_id=provider_id,
        provider_version=version,
        provider=provider,  # type: ignore[arg-type]
        strategies=strategies,
        scopes=scopes,
    )


class _DirectProvider:
    def __init__(self, root: Path, *, count: int = 1) -> None:
        self.root = root
        self.count = count
        self.calls: list[tuple[str, str]] = []

    def download(self, resource, job_id, strategy, cancel_event):
        self.calls.append((resource["title"], strategy))
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        outputs = []
        for index in range(self.count):
            path = job_dir / f"file-{index}.txt"
            path.write_text(f"{resource['title']}:{index}", encoding="utf-8")
            outputs.append(_download_result(path))
        return outputs[0] if len(outputs) == 1 else outputs


class _FailingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def download(self, resource, job_id, strategy, cancel_event):
        self.calls += 1
        raise DomainError("UPSTREAM_UNAVAILABLE", "platform unavailable", retryable=True)


class _AuthProvider:
    def download(self, resource, job_id, strategy, cancel_event):
        raise DomainError("AUTH_REQUIRED", "authentication required")


class _Materializer:
    def __init__(self, root: Path, *, fail: bool = False) -> None:
        self.root = root
        self.fail = fail
        self.calls = 0

    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult:
        self.calls += 1
        if self.fail:
            return AcquisitionResult.failed(
                AcquisitionStrategy.WEB_MATERIALIZE,
                "MATERIALIZE_FAILED",
                "静态内容不可提取",
            )
        job_dir = self.root / request.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "index.html"
        path.write_text("<p>safe</p>", encoding="utf-8")
        result = _download_result(path, "text/html")
        artifact = Artifact(
            artifact_id=f"{request.job_id}:html",
            role="bundle",
            primary=True,
            path=result.path,
            byte_size=result.byte_size,
            media_type=result.media_type,
            sha256=result.sha256,
            filename=result.filename,
            metadata={"renderer": "test", "provider": "untrusted"},
        )
        return AcquisitionResult.success(
            AcquisitionStrategy.WEB_MATERIALIZE,
            ArtifactBundle((artifact,)),
            metadata={
                "provider": "untrusted",
                "renderer": "test",
                "source_fingerprint": "sha256:" + "f" * 64,
            },
        )


class _CancellingMaterializer(_Materializer):
    def materialize(self, request: AcquisitionRequest) -> AcquisitionResult:
        result = super().materialize(request)
        request.cancel_event.set()
        return result


class _CancelAfterChecks(threading.Event):
    """Deterministically request cancellation at a validation boundary."""

    def __init__(self, threshold: int) -> None:
        super().__init__()
        self.threshold = threshold
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        if self.checks >= self.threshold:
            self.set()
        return super().is_set()


class _BrowserCapture:
    def __init__(self) -> None:
        self.calls = 0

    def capture(self, request: AcquisitionRequest) -> AcquisitionResult:
        self.calls += 1
        return AcquisitionResult.failed(
            AcquisitionStrategy.WEB_CAPTURE,
            "CAPTURE_EMPTY",
            "页面是空壳",
            retryable=True,
        )


class _AuthBrowserCapture:
    def capture(self, request: AcquisitionRequest) -> AcquisitionResult:
        return AcquisitionResult.failed(
            AcquisitionStrategy.WEB_CAPTURE,
            "AUTH_REQUIRED",
            "页面需要授权",
        )


class _LegacyBrowser:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def download(self, resource, job_id, strategy, cancel_event):
        self.calls.append(strategy)
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / "rendered.mhtml"
        path.write_text("From legacy renderer", encoding="utf-8")
        return _download_result(path, "multipart/related")


class AcquisitionCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.resource = {
            "resource_id": "generic:resource-1",
            "platform": "generic",
            "title": "测试资源",
            "resource_type": "article",
            "source_url": "https://example.com/resource",
            "metadata": {"topics": ["safe"]},
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _request(
        self,
        strategy: AcquisitionStrategy | str,
        *,
        resource: dict | None = None,
        provider_id: str = "test-provider",
        provider_version: str = "1.0.0",
        planned_scope: str = "primary_resource",
        source_fingerprint: str = "sha256:" + "e" * 64,
        cancel_event: threading.Event | None = None,
    ) -> AcquisitionRequest:
        return AcquisitionRequest(
            job_id="job-001",
            resource=resource or self.resource,
            strategy=strategy,
            provider_id=provider_id,
            provider_version=provider_version,
            planned_scope=planned_scope,
            representation_id="repr_acquisition_core_0001",
            preferred_container="html",
            cancel_event=cancel_event or threading.Event(),
            jobs_root=self.root,
        )

    def test_strategy_enum_requires_explicit_plan_value(self) -> None:
        self.assertIs(AcquisitionStrategy.from_plan("direct"), AcquisitionStrategy.DIRECT_FILE)
        self.assertIs(AcquisitionStrategy.from_plan("webpage"), AcquisitionStrategy.WEB_MATERIALIZE)
        with self.assertRaisesRegex(ValueError, "explicitly planned"):
            AcquisitionStrategy.from_plan(None, {"resource_type": "article"})
        with self.assertRaisesRegex(ValueError, "explicitly planned"):
            AcquisitionStrategy.from_plan(None, {"resource_type": "video"})
        with self.assertRaisesRegex(ValueError, "explicitly planned"):
            AcquisitionRouter.select_strategy(None, {"resource_type": "article"})

    def test_request_freezes_resource_requires_server_root_and_authority_refs(self) -> None:
        request = self._request("direct")
        self.resource["metadata"]["topics"].append("mutated")
        self.assertEqual(request.resource["metadata"]["topics"], ("safe",))
        with self.assertRaises((TypeError, AttributeError)):
            request.resource["title"] = "changed"  # type: ignore[index]
        self.assertEqual(request.jobs_root, self.root)
        self.assertEqual(request.to_dict()["planned_provider"], {
            "provider_id": "test-provider", "version": "1.0.0"
        })
        self.assertEqual(request.to_dict()["planned_scope"], "primary_resource")
        with self.assertRaises(TypeError):
            AcquisitionRequest(
                job_id="job-001",
                resource={"resource_id": "r"},
                strategy="direct",
                provider_id="test-provider",
                provider_version="1.0.0",
                planned_scope="primary_resource",
                representation_id="repr_acquisition_core_0001",
                jobs_root=Path("/tmp/jobs"),
            )
        with self.assertRaisesRegex(ValueError, "source_fingerprint"):
            self._request("direct", source_fingerprint="sha256:" + "F" * 64)
        with self.assertRaises(ValueError):
            AcquisitionRequest(
                job_id="job-001",
                resource={"resource_id": "r"},
                strategy="direct",
                provider_id="test-provider",
                provider_version="1.0.0",
                planned_scope="primary_resource",
                representation_id="repr_acquisition_core_0001",
                jobs_root=Path("relative-root"),
            )

    def test_direct_provider_single_and_list_results_become_artifacts(self) -> None:
        provider = _DirectProvider(self.root, count=2)
        router = AcquisitionRouter([_registration(provider)])
        result = router.acquire(self._request("direct_file"))
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.bundle)
        assert result.bundle is not None
        self.assertEqual(len(result.bundle.artifacts), 2)
        self.assertTrue(result.bundle.artifacts[0].primary)
        self.assertEqual(result.bundle.artifacts[0].role, "primary")
        self.assertFalse(result.bundle.artifacts[1].primary)
        self.assertEqual(provider.calls, [("测试资源", "direct")])
        facts = result.to_dict()
        self.assertEqual(facts["planned_provider"], {
            "provider_id": "test-provider", "version": "1.0.0"
        })
        self.assertEqual(facts["provider"], facts["planned_provider"])
        self.assertEqual(facts["planned_scope"], "primary_resource")
        self.assertEqual(facts["actual_scope"], "primary_resource")
        self.assertEqual(facts["representation_id"], "repr_acquisition_core_0001")
        self.assertTrue(result.to_json() == result.to_json())
        self.assertNotIn(str(self.root), result.to_json())

    def test_router_records_actual_file_metadata_without_declared_integrity_gate(self) -> None:
        payload = b"provider metadata is advisory"

        class AdvisoryMetadataProvider:
            def download(self, resource, job_id, strategy, cancel_event):
                job_dir = self.root / job_id
                job_dir.mkdir(parents=True, exist_ok=True)
                path = job_dir / "advisory.bin"
                path.write_bytes(payload)
                return DownloadResult(
                    path,
                    1,
                    "application/octet-stream",
                    "0" * 64,
                    path.name,
                )

            def __init__(self, root: Path) -> None:
                self.root = root

        result = AcquisitionRouter([
            _registration(AdvisoryMetadataProvider(self.root)),
        ]).acquire(self._request("direct_file"))
        self.assertTrue(result.ok)
        assert result.bundle is not None
        artifact = result.bundle.primary
        assert artifact is not None
        self.assertEqual(artifact.byte_size, len(payload))
        self.assertEqual(artifact.sha256, hashlib.sha256(payload).hexdigest())

    def test_cancellation_is_polled_during_direct_artifact_hashing(self) -> None:
        provider = _DirectProvider(self.root)
        cancel_event = _CancelAfterChecks(threshold=5)
        result = AcquisitionRouter([_registration(provider)]).acquire(
            self._request(
                "direct_file",
                cancel_event=cancel_event,
            )
        )
        self.assertFalse(result.ok)
        self.assertEqual("JOB_CANCELLED", result.failure.code)  # type: ignore[union-attr]
        self.assertEqual([("测试资源", "direct")], provider.calls)
        self.assertGreaterEqual(cancel_event.checks, 5)

    def test_result_provider_cancellation_wins_before_bundle_validation(self) -> None:
        provider = _CancellingMaterializer(self.root)
        result = AcquisitionRouter([
            _registration(
                provider,
                provider_id="static-cancelling",
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
            )
        ]).acquire(
            self._request("web_materialize", provider_id="static-cancelling")
        )
        self.assertFalse(result.ok)
        self.assertEqual("JOB_CANCELLED", result.failure.code)  # type: ignore[union-attr]
        self.assertEqual(1, provider.calls)

    def test_exact_provider_failure_never_falls_back_to_generic_direct(self) -> None:
        direct = _DirectProvider(self.root)
        failing = _FailingProvider()
        router = AcquisitionRouter([
            _registration(direct, provider_id="generic-direct"),
            _registration(failing, provider_id="platform-exact"),
        ])
        result = router.acquire(self._request("direct", provider_id="platform-exact"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "UPSTREAM_UNAVAILABLE")  # type: ignore[union-attr]
        self.assertEqual(failing.calls, 1)
        self.assertEqual(direct.calls, [])
        self.assertEqual(result.provider_id, "platform-exact")
        self.assertEqual(result.provider_version, "1.0.0")
        self.assertEqual(result.actual_scope, "primary_resource")

    def test_auth_failure_never_falls_back_to_direct_provider(self) -> None:
        direct = _DirectProvider(self.root)
        router = AcquisitionRouter([
            _registration(direct, provider_id="generic-direct"),
            _registration(_AuthProvider(), provider_id="auth-exact"),
        ])
        result = router.acquire(self._request("direct", provider_id="auth-exact"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "AUTH_REQUIRED")  # type: ignore[union-attr]
        self.assertEqual(direct.calls, [])

    def test_static_materializer_and_capture_failure_stay_with_exact_provider(self) -> None:
        materializer = _Materializer(self.root)
        browser = _BrowserCapture()
        router = AcquisitionRouter([
            _registration(
                materializer,
                provider_id="static-exact",
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
            ),
            _registration(
                browser,
                provider_id="capture-exact",
                strategies=(AcquisitionStrategy.WEB_CAPTURE,),
            ),
        ])
        request = self._request("webpage", provider_id="static-exact")
        result = router.acquire(request)
        self.assertTrue(result.ok)
        self.assertEqual(result.strategy, AcquisitionStrategy.WEB_MATERIALIZE)
        self.assertEqual(result.bundle.artifacts[0].role, "bundle")  # type: ignore[union-attr]
        self.assertEqual(result.metadata, {"renderer": "test"})

        captured = router.acquire(self._request("web_capture", provider_id="capture-exact"))
        self.assertFalse(captured.ok)
        self.assertEqual(captured.strategy, AcquisitionStrategy.WEB_CAPTURE)
        self.assertEqual(captured.failure.code, "CAPTURE_EMPTY")  # type: ignore[union-attr]
        self.assertEqual(materializer.calls, 1)
        self.assertEqual(browser.calls, 1)
        self.assertEqual(captured.provider_id, "capture-exact")

    def test_explicit_browser_capture_adapts_legacy_download_provider(self) -> None:
        legacy = _LegacyBrowser(self.root)
        result = AcquisitionRouter([
            _registration(
                legacy,
                provider_id="legacy-capture",
                strategies=(AcquisitionStrategy.WEB_CAPTURE,),
            )
        ]).acquire(self._request("web_capture", provider_id="legacy-capture"))
        self.assertTrue(result.ok)
        self.assertEqual(result.strategy, AcquisitionStrategy.WEB_CAPTURE)
        self.assertEqual(legacy.calls, ["webpage"])
        self.assertTrue(result.bundle.artifacts[0].primary)  # type: ignore[union-attr]

    def test_browser_auth_failure_never_falls_back_to_static_fetch(self) -> None:
        materializer = _Materializer(self.root)
        router = AcquisitionRouter([
            _registration(
                materializer,
                provider_id="static-exact",
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
            ),
            _registration(
                _AuthBrowserCapture(),
                provider_id="capture-auth",
                strategies=(AcquisitionStrategy.WEB_CAPTURE,),
            ),
        ])
        result = router.acquire(self._request("web_capture", provider_id="capture-auth"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "AUTH_REQUIRED")  # type: ignore[union-attr]
        self.assertEqual(materializer.calls, 0)

    def test_browser_capture_is_not_automatically_selected_or_raw_fallback(self) -> None:
        materializer = _Materializer(self.root, fail=True)
        browser = _BrowserCapture()
        router = AcquisitionRouter([
            _registration(
                materializer,
                provider_id="static-exact",
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
            ),
            _registration(
                browser,
                provider_id="capture-exact",
                strategies=(AcquisitionStrategy.WEB_CAPTURE,),
            ),
        ])
        result = router.acquire(self._request("web_materialize", provider_id="static-exact"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "MATERIALIZE_FAILED")  # type: ignore[union-attr]
        self.assertEqual(materializer.calls, 1)
        self.assertEqual(browser.calls, 0)

    def test_missing_generic_materializer_does_not_cross_route_to_generic_direct(self) -> None:
        direct = _DirectProvider(self.root)
        router = AcquisitionRouter([
            _registration(direct, provider_id="generic-direct"),
        ])

        result = router.acquire(
            self._request(
                "web_materialize",
                provider_id="generic-web-materializer",
                planned_scope="landing_page",
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual("PROVIDER_UNAVAILABLE", result.failure.code)  # type: ignore[union-attr]
        self.assertEqual([], direct.calls)
        self.assertIsNone(result.provider_id)

    def test_missing_generic_direct_does_not_cross_route_to_materializer(self) -> None:
        materializer = _Materializer(self.root)
        router = AcquisitionRouter([
            _registration(
                materializer,
                provider_id="generic-web-materializer",
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                scopes=("landing_page",),
            ),
        ])

        result = router.acquire(
            self._request("direct_file", provider_id="generic-direct")
        )

        self.assertFalse(result.ok)
        self.assertEqual("PROVIDER_UNAVAILABLE", result.failure.code)  # type: ignore[union-attr]
        self.assertEqual(0, materializer.calls)
        self.assertIsNone(result.provider_id)

    def test_registry_gates_unknown_version_and_scope_without_provider_calls(self) -> None:
        provider = _DirectProvider(self.root)
        router = AcquisitionRouter([
            _registration(provider, provider_id="registered-exact", version="1.0.0"),
        ])
        unknown = router.acquire(self._request("direct", provider_id="missing-exact"))
        self.assertEqual(unknown.failure.code, "PROVIDER_UNAVAILABLE")  # type: ignore[union-attr]
        self.assertIsNone(unknown.provider_id)

        drifted = router.acquire(
            self._request(
                "direct",
                provider_id="registered-exact",
                provider_version="2.0.0",
            )
        )
        self.assertEqual(drifted.failure.code, "CAPABILITY_VERSION_CONFLICT")  # type: ignore[union-attr]
        self.assertIsNone(drifted.provider_id)

        scope = router.acquire(
            self._request(
                "direct",
                provider_id="registered-exact",
                planned_scope="landing_page",
            )
        )
        self.assertEqual(scope.failure.code, "PROVIDER_SCOPE_MISMATCH")  # type: ignore[union-attr]
        self.assertIsNone(scope.provider_id)
        self.assertEqual(provider.calls, [])

    def test_resource_platform_cannot_change_exact_provider_routing(self) -> None:
        provider = _DirectProvider(self.root)
        router = AcquisitionRouter([
            _registration(provider, provider_id="bound-exact"),
        ])
        foreign_platform = dict(self.resource, platform="totally-unregistered-platform")
        result = router.acquire(
            self._request("direct", resource=foreign_platform, provider_id="bound-exact")
        )
        self.assertTrue(result.ok)
        self.assertEqual(provider.calls, [("测试资源", "direct")])

    def test_registry_rejects_mismatched_or_nonexplicit_registration(self) -> None:
        provider = _DirectProvider(self.root)
        registration = _registration(provider, provider_id="bound-exact")
        with self.assertRaises(ValueError):
            AcquisitionRouter({("other-provider", "1.0.0"): registration})
        empty = AcquisitionRouter([])
        unavailable = empty.acquire(self._request("direct", provider_id="unregistered-exact"))
        self.assertEqual(unavailable.failure.code, "PROVIDER_UNAVAILABLE")  # type: ignore[union-attr]
        with self.assertRaises(TypeError):
            AcquisitionRouter([provider])  # type: ignore[list-item]

    def test_provider_output_outside_jobs_root_is_structured_failure(self) -> None:
        outside = self.root.parent / "outside-acquisition-test.txt"
        outside.write_text("outside", encoding="utf-8")

        class OutsideProvider:
            def download(self, resource, job_id, strategy, cancel_event):
                return _download_result(outside)

        result = AcquisitionRouter([
            _registration(OutsideProvider()),
        ]).acquire(self._request("direct"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "ACQUISITION_OUTPUT_INVALID")  # type: ignore[union-attr]
        outside.unlink(missing_ok=True)

    def test_bundle_rejects_more_than_fifty_artifacts(self) -> None:
        artifacts = tuple(
            Artifact(
                artifact_id=f"a-{index}",
                role="attachment",
                primary=index == 0,
                path=self.root / f"{index}.bin",
                byte_size=0,
                media_type="application/octet-stream",
                sha256="0" * 64,
                filename=f"{index}.bin",
            )
            for index in range(51)
        )
        with self.assertRaises(ValueError):
            ArtifactBundle(artifacts)


if __name__ == "__main__":
    unittest.main()
