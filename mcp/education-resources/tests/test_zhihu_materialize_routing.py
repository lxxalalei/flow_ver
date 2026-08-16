"""0057 M0: Zhihu answers/articles route to the web materializer.

The Zhihu inspector now marks the webpage as the primary representation and
the planner spec table allows zhihu to use generic-web-materializer, so a
知乎 candidate can be "downloaded" as a materialized page.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters.inspect_zhihu import ZhihuInspector
from education_resource_mcp.acquisition.planner import AcquisitionPlanner
from education_resource_mcp.acquisition import AcquisitionRouter, ProviderRegistration
from education_resource_mcp.acquisition.models import AcquisitionStrategy
from education_resource_mcp.downloader import DownloadProvider


class _FakeMaterializer:
    provider_id = "generic-web-materializer"

    def download(self, *args, **kwargs):  # pragma: no cover - routing only
        raise AssertionError("not reached")


def _planner() -> AcquisitionPlanner:
    router = AcquisitionRouter(
        (
            ProviderRegistration(
                provider_id="generic-web-materializer",
                provider=_FakeMaterializer(),
                strategies=(AcquisitionStrategy.WEB_MATERIALIZE,),
                scopes=("primary_resource", "landing_page"),
            ),
        )
    )
    return AcquisitionPlanner(router)


class ZhihuMaterializeRoutingTests(unittest.TestCase):
    def test_primary_webpage_routes_to_materializer(self) -> None:
        route = _planner().route(
            {
                "platform": "zhihu",
                "resource_type": "article",
                "source_url": "https://zhuanlan.zhihu.com/p/123",
            },
            {
                "resolved_resource": {
                    "representations": [
                        {
                            "representation_id": "repr_1",
                            "scope": "primary_resource",
                            "kind": "webpage",
                            "role": "primary",
                            "container": "article",
                            "materializable": True,
                        }
                    ]
                }
            },
        )
        self.assertEqual("generic-web-materializer", route["provider_id"])
        self.assertEqual(AcquisitionStrategy.WEB_MATERIALIZE.kind, route["strategy"])

    def test_answer_container_routes_too(self) -> None:
        route = _planner().route(
            {
                "platform": "zhihu",
                "resource_type": "article",
                "source_url": "https://www.zhihu.com/question/1/answer/2",
            },
            {
                "resolved_resource": {
                    "representations": [
                        {
                            "representation_id": "repr_2",
                            "scope": "primary_resource",
                            "kind": "webpage",
                            "role": "primary",
                            "container": "webpage",
                            "materializable": True,
                        }
                    ]
                }
            },
        )
        self.assertEqual("generic-web-materializer", route["provider_id"])

    def test_inspector_appends_primary_webpage_representation(self) -> None:
        inspector = ZhihuInspector.__new__(ZhihuInspector)  # skip HTTP init
        payload = {
            "resolution_status": "resolved",
            "resolved_resource": {
                "availability": {"status": "available"},
                "metadata": {"article_id": "p-123"},
                "representations": [],
            },
        }
        enriched = inspector._enrich_payload(
            {"platform": "zhihu", "source_url": "https://zhuanlan.zhihu.com/p/123"},
            payload,
        )
        (rep,) = enriched["resolved_resource"]["representations"]
        self.assertEqual("webpage", rep["kind"])
        self.assertEqual("primary", rep["role"])
        self.assertEqual("primary_resource", rep["scope"])
        self.assertEqual("article", rep["container"])


if __name__ == "__main__":
    unittest.main()
