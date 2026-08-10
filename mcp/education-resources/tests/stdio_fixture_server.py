from __future__ import annotations

from pathlib import Path
import sys

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
from education_resource_mcp.inspection import (
    InspectionResult,
    InspectionRouter,
    build_default_inspection,
)
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.server import create_server
from education_resource_mcp.service import ResourceService


class FixtureInspector:
    """Offline, catalog-compatible evidence for a generic landing page."""

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
                        "requires_auth": False,
                    }
                ],
                "metadata": {},
            },
            inspection=build_default_inspection(
                self.inspector_id,
                method="offline-fixture",
                cache_status="miss",
                inspected_at="2026-08-09T00:00:00Z",
            ),
            failures=[],
        )


class FixtureFetcher:
    def fetch_html(self, url: str, *, cancel_event=None) -> FetchResult:
        body = (
            "<html><body><article><h1>恐龙入门资料</h1>"
            "<p>这是仅用于 MCP stdio 契约回归的离线网页夹具。</p>"
            "</article></body></html>"
        ).encode("utf-8")
        return FetchResult(url, 200, "text/html", body, {})

    def fetch_image(self, url: str, *, cancel_event=None):
        raise AssertionError("the stdio HTML fixture contains no images")


def main() -> None:
    settings = Settings.from_env()
    provider = StaticSearchProvider(
        [
            {
                "platform": "generic",
                "title": "恐龙入门资料",
                "source_url": "https://example.com/dinosaur-a",
                "resource_type": "article",
                "summary": "适合入门",
                "metadata": {"language": "zh-CN"},
            },
            {
                "platform": "generic",
                "title": "恐龙化石资料",
                "source_url": "https://example.com/dinosaur-b",
                "resource_type": "article",
                "summary": "化石资料",
                "metadata": {},
            },
        ]
    )
    acquisition_router = AcquisitionRouter(
        [
            ProviderRegistration(
                provider_id="generic-web-materializer",
                provider_version="1.0.0",
                provider=WebMaterializer(fetcher=FixtureFetcher()),
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                scopes=("landing_page",),
            )
        ]
    )
    inspection_router = InspectionRouter([FixtureInspector()])
    service = ResourceService(
        settings,
        search_provider=provider,
        acquisition_router=acquisition_router,
        inspection_router=inspection_router,
    )
    try:
        create_server(service).run("stdio")
    finally:
        service.close()


if __name__ == "__main__":
    main()
