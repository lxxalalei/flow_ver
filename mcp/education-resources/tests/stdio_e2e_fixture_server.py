"""Offline fixture MCP used by process-level E2E tests only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import threading
import time


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.acquisition import (
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.acquisition.web_fetch import FetchResult
from education_resource_mcp.acquisition.web_materializer import WebMaterializer
from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import (
    DownloadBatchResult,
    DownloadItemFailure,
    DownloadResult,
)
from education_resource_mcp.errors import DomainError
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.retrieval.registry import (
    build_registry_snapshot,
    canonical_descriptor_digest,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.server import create_server
from education_resource_mcp.service import ResourceService


_CAPABILITY_VERSION = "1.1.0"
_FIXTURE_SOURCE = {
    "kind": "deployment",
    "name": "stdio-e2e-fixture",
    "published_at": "2026-08-08T00:00:00Z",
}
_FIXTURE_COMPATIBILITY = {
    "read_min": "1.0.0",
    "write_version": _CAPABILITY_VERSION,
    "breaking_major": 1,
}
_FIXTURE_PREREQUISITES = {
    "required_fields": [],
    "auth_mode": "none",
    "network_policy": "public_http",
    "max_bytes": 512 * 1024,
    "max_retries": 0,
    "requires_session": False,
}


def _fixture_descriptor(
    *,
    descriptor_id: str,
    resource_type: str,
    scope: str,
    kind: str,
    role: str,
    container: str,
    mime_type: str,
    strategy: str,
    provider_id: str,
    policy_class: str,
) -> dict:
    """Build one isolated E2E deployment route and bind its canonical digest."""

    descriptor = {
        "descriptor_id": descriptor_id,
        "descriptor_version": _CAPABILITY_VERSION,
        "descriptor_digest": "",
        "registry_version": _CAPABILITY_VERSION,
        "platform_id": "generic",
        "resource_types": [resource_type],
        "scope": scope,
        "representation": {
            "kind": kind,
            "role": role,
            "containers": [container],
            "mime_types": [mime_type],
            "materializable": True,
        },
        "strategy": strategy,
        "provider": {
            "provider_id": provider_id,
            "version": "1.0.0",
            "scope": scope,
        },
        "inspector": {
            "inspector_id": "e2e-fixture-inspector",
            "version": "1.0.0",
        },
        "prerequisites": dict(_FIXTURE_PREREQUISITES),
        "policy_class": policy_class,
        "fallback": {
            "allowed": False,
            "max_scope": scope,
            "allowed_scopes": [],
            "on_errors": [],
            "scope_preserving": True,
        },
        "source": dict(_FIXTURE_SOURCE),
        "compatibility": dict(_FIXTURE_COMPATIBILITY),
        "deprecated": False,
    }
    descriptor["descriptor_digest"] = (
        "sha256:" + canonical_descriptor_digest(descriptor)
    )
    return descriptor


def fixture_capability_registry_snapshot():
    """Return the exact deployment truth for the isolated E2E fixture.

    The fixture uses a specialized offline inspector and executes video, book,
    course, and landing-page routes.  It therefore must not impersonate the
    built-in generic deployment catalog, whose inspector identity and supported
    representations are intentionally different.
    """

    return build_registry_snapshot(
        {
            "$schema": "../schemas/capability-descriptors.schema.json",
            "catalog_version": _CAPABILITY_VERSION,
            "registry_version": _CAPABILITY_VERSION,
            "descriptors": [
                _fixture_descriptor(
                    descriptor_id="cap_e2e_video_primary_mp4_v1",
                    resource_type="video",
                    scope="primary_resource",
                    kind="video",
                    role="primary",
                    container="mp4",
                    mime_type="video/mp4",
                    strategy="direct_file",
                    provider_id="generic-direct",
                    policy_class="e2e_public_direct_file",
                ),
                _fixture_descriptor(
                    descriptor_id="cap_e2e_book_primary_pdf_v1",
                    resource_type="book",
                    scope="primary_resource",
                    kind="document",
                    role="primary",
                    container="pdf",
                    mime_type="application/pdf",
                    strategy="direct_file",
                    provider_id="generic-direct",
                    policy_class="e2e_public_direct_file",
                ),
                _fixture_descriptor(
                    descriptor_id="cap_e2e_course_primary_mp4_v1",
                    resource_type="course",
                    scope="primary_resource",
                    kind="video",
                    role="primary",
                    container="mp4",
                    mime_type="video/mp4",
                    strategy="direct_file",
                    provider_id="generic-direct",
                    policy_class="e2e_public_direct_file",
                ),
                _fixture_descriptor(
                    descriptor_id="cap_e2e_article_landing_html_v1",
                    resource_type="article",
                    scope="landing_page",
                    kind="webpage",
                    role="landing",
                    container="html",
                    mime_type="text/html",
                    strategy="web_materialize",
                    provider_id="generic-web-materializer",
                    policy_class="e2e_public_web_materialization",
                ),
            ],
        }
    )


class FixtureInspector:
    platform_id = "generic"
    inspector_id = "e2e-fixture-inspector"
    version = "1.0.0"
    supported_scopes = ("primary_resource", "landing_page", "representation")

    def inspect(self, resource: dict) -> InspectionResult:
        resource_type = str(resource["resource_type"])
        representations: list[dict] = []
        if resource_type == "video":
            representations.append(
                {
                    "scope": "primary_resource",
                    "kind": "video",
                    "container": "mp4",
                    "mime_type": "video/mp4",
                    "role": "primary",
                    "materializable": True,
                    "requires_auth": False,
                }
            )
        elif resource_type == "article":
            representations.append(
                {
                    "scope": "landing_page",
                    "kind": "webpage",
                    "container": "html",
                    "mime_type": "text/html",
                    "role": "landing",
                    "materializable": True,
                    "requires_auth": False,
                }
            )
        elif resource_type == "book":
            representations.append(
                {
                    "scope": "primary_resource",
                    "kind": "document",
                    "container": "pdf",
                    "mime_type": "application/pdf",
                    "role": "primary",
                    "materializable": True,
                    "requires_auth": False,
                }
            )
        else:
            representations.extend(
                [
                    {
                        "scope": "primary_resource",
                        "kind": "video",
                        "container": "mp4",
                        "mime_type": "video/mp4",
                        "role": "primary",
                        "materializable": True,
                        "requires_auth": False,
                    },
                    {
                        "scope": "representation",
                        "kind": "document",
                        "container": "pdf",
                        "mime_type": "application/pdf",
                        "role": "attachment",
                        "materializable": True,
                        "requires_auth": False,
                    },
                ]
            )
        metadata = resource.get("metadata") or {}
        public_metadata = {}
        if metadata.get("edition"):
            public_metadata["edition"] = str(metadata["edition"])
        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": resource["title"],
                "resource_type": resource_type,
                "availability": {"status": "available"},
                "representations": representations,
                "metadata": public_metadata,
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-08T00:00:00+00:00",
            ),
            failures=[],
        )


class FixtureFetcher:
    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        body = (
            "<html><body><article><h1>恐龙网页资料</h1>"
            "<p>这是完全离线的 E2E 静态网页夹具。</p>"
            "</article></body></html>"
        ).encode("utf-8")
        return FetchResult(url, 200, "text/html", body, {})

    def fetch_image(self, url: str, *, cancel_event=None):
        raise AssertionError("the E2E HTML fixture contains no images")


class FixtureDownloader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _write(
        path: Path,
        payload: bytes,
        media_type: str,
        *,
        role: str,
        required: bool,
        item_key: str,
    ) -> DownloadResult:
        path.write_bytes(payload)
        return DownloadResult(
            path,
            len(payload),
            media_type,
            hashlib.sha256(payload).hexdigest(),
            path.name,
            role=role,
            required=required,
            item_key=item_key,
            metadata={"fixture_relation": item_key},
        )

    def download(
        self,
        resource: dict,
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult | DownloadBatchResult:
        kind = str((resource.get("metadata") or {}).get("fixture_kind") or "video")
        if kind == "blocking":
            while not cancel_event.wait(0.05):
                pass
            raise DomainError("JOB_CANCELLED", "阻塞夹具已取消")
        if kind == "auth" and not (self.settings.data_dir / "fixture-auth-ready").is_file():
            raise DomainError("AUTH_REQUIRED", "需要合法平台会话")
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "夹具任务已取消")

        directory = self.settings.jobs_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        prefix = str(resource["resource_id"])[-8:]
        if kind == "book":
            primary = self._write(
                directory / f"{prefix}-book.pdf",
                b"%PDF-1.4\nE2E book edition 2024",
                "application/pdf",
                role="primary",
                required=True,
                item_key=f"{prefix}:pdf",
            )
            cover = self._write(
                directory / f"{prefix}-cover.png",
                b"\x89PNG\r\n\x1a\nE2E-cover",
                "image/png",
                role="cover",
                required=False,
                item_key=f"{prefix}:cover",
            )
            return DownloadBatchResult(results=[primary, cover])

        primary = self._write(
            directory / f"{prefix}-video.mp4",
            b"\x00\x00\x00\x18ftypmp42E2E-video-fixture",
            "video/mp4",
            role="primary",
            required=True,
            item_key=f"{prefix}:video",
        )
        if kind != "partial-course":
            return primary
        attachment = self._write(
            directory / f"{prefix}-worksheet.pdf",
            b"%PDF-1.4\nE2E worksheet",
            "application/pdf",
            role="attachment",
            required=False,
            item_key=f"{prefix}:worksheet",
        )
        return DownloadBatchResult(
            results=[primary, attachment],
            failures=[
                DownloadItemFailure(
                    item_key=f"{prefix}:transcript",
                    code="DOWNLOAD_FAILED",
                    message="离线夹具字幕不可用",
                    role="transcript",
                    required=False,
                    retryable=True,
                )
            ],
        )


STANDARD_RESOURCES = [
    {
        "platform": "generic",
        "title": "恐龙视频课",
        "source_url": "https://example.com/e2e/video",
        "resource_type": "video",
        "summary": "单视频夹具",
        "metadata": {"fixture_kind": "video", "language": "zh-CN"},
    },
    {
        "platform": "generic",
        "title": "恐龙网页图文",
        "source_url": "https://example.com/e2e/article",
        "resource_type": "article",
        "summary": "网页物化夹具",
        "metadata": {"fixture_kind": "article", "language": "zh-CN"},
    },
    {
        "platform": "generic",
        "title": "恐龙百科 2024 版",
        "source_url": "https://example.com/e2e/book",
        "resource_type": "book",
        "summary": "明确版本图书夹具",
        "metadata": {"fixture_kind": "book", "edition": "2024"},
    },
    {
        "platform": "generic",
        "title": "恐龙综合课程",
        "source_url": "https://example.com/e2e/course",
        "resource_type": "course",
        "summary": "带逐项失败的课程夹具",
        "metadata": {"fixture_kind": "partial-course"},
    },
    {
        "platform": "generic",
        "title": "授权恐龙课程",
        "source_url": "https://example.com/e2e/auth-course",
        "resource_type": "course",
        "summary": "认证恢复夹具",
        "metadata": {"fixture_kind": "auth"},
    },
]

RESTART_RESOURCES = [
    {
        "platform": "generic",
        "title": "重启前快速视频",
        "source_url": "https://example.com/e2e/restart-fast",
        "resource_type": "video",
        "summary": "先产生 ready Asset",
        "metadata": {"fixture_kind": "video"},
    },
    {
        "platform": "generic",
        "title": "重启阻塞图书",
        "source_url": "https://example.com/e2e/restart-blocking",
        "resource_type": "book",
        "summary": "等待进程被终止",
        "metadata": {"fixture_kind": "blocking", "edition": "2024"},
    },
]


def main() -> None:
    settings = Settings.from_env()
    mode = os.environ.get("EDUCATION_RESOURCE_E2E_MODE", "standard").strip()
    if mode not in {"standard", "restart"}:
        raise ValueError("EDUCATION_RESOURCE_E2E_MODE must be standard or restart")
    downloader = FixtureDownloader(settings)
    acquisition_router = AcquisitionRouter(
        [
            ProviderRegistration(
                provider_id="generic-direct",
                provider_version="1.0.0",
                provider=downloader,
                strategies=(AcquisitionStrategy.DIRECT_FILE,),
                scopes=("primary_resource",),
            ),
            ProviderRegistration(
                provider_id="generic-web-materializer",
                provider_version="1.0.0",
                provider=WebMaterializer(fetcher=FixtureFetcher()),
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                scopes=("landing_page",),
            ),
        ]
    )
    inspection_router = InspectionRouter([FixtureInspector()])
    service = ResourceService(
        settings,
        search_provider=StaticSearchProvider(
            RESTART_RESOURCES if mode == "restart" else STANDARD_RESOURCES
        ),
        acquisition_router=acquisition_router,
        inspection_router=inspection_router,
        capability_registry_snapshot=fixture_capability_registry_snapshot(),
    )
    try:
        create_server(service).run("stdio")
    finally:
        service.close()


if __name__ == "__main__":
    main()
