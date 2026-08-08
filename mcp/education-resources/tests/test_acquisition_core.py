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


class _DirectProvider:
    def __init__(self, root: Path, *, count: int = 1) -> None:
        self.root = root
        self.count = count
        self.calls: list[tuple[str, str]] = []

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
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
    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
        raise DomainError("UPSTREAM_UNAVAILABLE", "platform unavailable", retryable=True)


class _AuthProvider:
    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
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
            metadata={"renderer": "test"},
        )
        return AcquisitionResult.success(
            AcquisitionStrategy.WEB_MATERIALIZE,
            ArtifactBundle((artifact,), request.max_bytes),
        )


class _BrowserCapture:
    def capture(self, request: AcquisitionRequest) -> AcquisitionResult:
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

    def download(self, resource, job_id, strategy, max_bytes, cancel_event):
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
        max_bytes: int = 1024,
        allow_safe_fallback: bool = True,
        resource: dict | None = None,
    ) -> AcquisitionRequest:
        return AcquisitionRequest(
            job_id="job-001",
            resource=resource or self.resource,
            strategy=strategy,
            preferred_container="html",
            max_bytes=max_bytes,
            allow_safe_fallback=allow_safe_fallback,
            cancel_event=threading.Event(),
            jobs_root=self.root,
        )

    def test_strategy_enum_maps_legacy_plan_values_without_browser_inference(self) -> None:
        self.assertIs(AcquisitionStrategy.from_plan("direct"), AcquisitionStrategy.DIRECT_FILE)
        self.assertIs(AcquisitionStrategy.from_plan("webpage"), AcquisitionStrategy.WEB_MATERIALIZE)
        self.assertIs(
            AcquisitionStrategy.from_plan(None, {"resource_type": "article"}),
            AcquisitionStrategy.WEB_MATERIALIZE,
        )
        self.assertIs(
            AcquisitionStrategy.from_plan(None, {"resource_type": "video"}),
            AcquisitionStrategy.DIRECT_FILE,
        )
        self.assertIs(
            AcquisitionRouter.select_strategy(None, {"resource_type": "article"}),
            AcquisitionStrategy.WEB_MATERIALIZE,
        )
        self.assertNotEqual(
            AcquisitionRouter.select_strategy(None, {"resource_type": "article"}),
            AcquisitionStrategy.WEB_CAPTURE,
        )

    def test_request_freezes_resource_and_requires_server_root(self) -> None:
        request = self._request("direct")
        self.resource["metadata"]["topics"].append("mutated")
        self.assertEqual(request.resource["metadata"]["topics"], ("safe",))
        with self.assertRaises((TypeError, AttributeError)):
            request.resource["title"] = "changed"  # type: ignore[index]
        self.assertEqual(request.jobs_root, self.root)
        with self.assertRaises(ValueError):
            AcquisitionRequest(
                "job-001",
                {"resource_id": "r"},
                "direct",
                "html",
                100,
                True,
                threading.Event(),
                jobs_root=Path("relative-root"),
            )

    def test_direct_provider_single_and_list_results_become_bounded_artifacts(self) -> None:
        provider = _DirectProvider(self.root, count=2)
        router = AcquisitionRouter(provider)
        result = router.acquire(self._request("direct_file", max_bytes=1024))
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.bundle)
        assert result.bundle is not None
        self.assertEqual(len(result.bundle.artifacts), 2)
        self.assertTrue(result.bundle.artifacts[0].primary)
        self.assertEqual(result.bundle.artifacts[0].role, "primary")
        self.assertFalse(result.bundle.artifacts[1].primary)
        self.assertEqual(provider.calls, [("测试资源", "direct")])
        self.assertTrue(result.to_json() == result.to_json())
        self.assertNotIn(str(self.root), result.to_json())

    def test_platform_provider_failure_uses_direct_provider_only_when_allowed(self) -> None:
        direct = _DirectProvider(self.root)
        router = AcquisitionRouter(
            direct,
            platform_providers={"generic": _FailingProvider()},
        )
        result = router.acquire(self._request("direct"))
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["fallback"], "direct_file")
        self.assertEqual(direct.calls, [("测试资源", "direct")])

        no_fallback = router.acquire(
            self._request("direct", allow_safe_fallback=False)
        )
        self.assertFalse(no_fallback.ok)
        self.assertEqual(no_fallback.failure.code, "UPSTREAM_UNAVAILABLE")  # type: ignore[union-attr]
        self.assertEqual(len(direct.calls), 1)

    def test_auth_failure_never_falls_back_to_direct_provider(self) -> None:
        direct = _DirectProvider(self.root)
        router = AcquisitionRouter(
            direct,
            platform_providers={"generic": _AuthProvider()},
        )
        result = router.acquire(self._request("direct", allow_safe_fallback=True))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "AUTH_REQUIRED")  # type: ignore[union-attr]
        self.assertEqual(direct.calls, [])

    def test_static_materializer_and_explicit_browser_safe_fallback(self) -> None:
        materializer = _Materializer(self.root)
        router = AcquisitionRouter(
            _DirectProvider(self.root),
            web_materializer=materializer,
            browser_capture=_BrowserCapture(),
        )
        result = router.acquire(self._request("webpage"))
        self.assertTrue(result.ok)
        self.assertEqual(result.strategy, AcquisitionStrategy.WEB_MATERIALIZE)
        self.assertEqual(result.bundle.artifacts[0].role, "bundle")  # type: ignore[union-attr]

        captured = router.acquire(self._request("web_capture"))
        self.assertTrue(captured.ok)
        self.assertEqual(captured.strategy, AcquisitionStrategy.WEB_MATERIALIZE)
        self.assertEqual(materializer.calls, 2)
        self.assertTrue(captured.warnings)

    def test_explicit_browser_capture_adapts_legacy_download_provider(self) -> None:
        legacy = _LegacyBrowser(self.root)
        result = AcquisitionRouter(
            _DirectProvider(self.root), browser_capture=legacy
        ).acquire(self._request("web_capture"))
        self.assertTrue(result.ok)
        self.assertEqual(result.strategy, AcquisitionStrategy.WEB_CAPTURE)
        self.assertEqual(legacy.calls, ["webpage"])
        self.assertTrue(result.bundle.artifacts[0].primary)  # type: ignore[union-attr]

    def test_browser_auth_failure_never_falls_back_to_static_fetch(self) -> None:
        materializer = _Materializer(self.root)
        router = AcquisitionRouter(
            _DirectProvider(self.root),
            web_materializer=materializer,
            browser_capture=_AuthBrowserCapture(),
        )
        result = router.acquire(
            self._request("web_capture", allow_safe_fallback=True)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "AUTH_REQUIRED")  # type: ignore[union-attr]
        self.assertEqual(materializer.calls, 0)

    def test_browser_capture_is_not_automatically_selected_or_raw_fallback(self) -> None:
        materializer = _Materializer(self.root, fail=True)
        browser = _BrowserCapture()
        router = AcquisitionRouter(
            _DirectProvider(self.root),
            web_materializer=materializer,
            browser_capture=browser,
        )
        result = router.acquire(self._request("web_materialize"))
        self.assertFalse(result.ok)
        self.assertEqual(result.failure.code, "MATERIALIZE_FAILED")  # type: ignore[union-attr]
        self.assertEqual(materializer.calls, 1)

    def test_provider_output_outside_jobs_root_is_structured_failure(self) -> None:
        outside = self.root.parent / "outside-acquisition-test.txt"
        outside.write_text("outside", encoding="utf-8")

        class OutsideProvider:
            def download(self, resource, job_id, strategy, max_bytes, cancel_event):
                return _download_result(outside)

        result = AcquisitionRouter(OutsideProvider()).acquire(self._request("direct"))
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
            ArtifactBundle(artifacts, 1024)


if __name__ == "__main__":
    unittest.main()
