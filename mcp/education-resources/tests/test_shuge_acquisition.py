from __future__ import annotations

import unittest

from education_resource_mcp.acquisition import (
    AcquisitionRouter,
    AcquisitionStrategy,
    ProviderRegistration,
)
from education_resource_mcp.acquisition.planner import AcquisitionPlanner
from education_resource_mcp.inspection import build_representation_authority


class _DirectProviderStub:
    def download(self, resource, job_id, strategy, cancel_event):  # pragma: no cover
        raise AssertionError("planner route test must not execute the provider")


class ShugeAcquisitionRouteTests(unittest.TestCase):
    def test_primary_pdf_routes_to_generic_direct(self) -> None:
        router = AcquisitionRouter(
            [
                ProviderRegistration(
                    provider_id="generic-direct",
                    provider_version="1.0.0",
                    provider=_DirectProviderStub(),
                    strategies=(AcquisitionStrategy.DIRECT_FILE,),
                    scopes=("primary_resource",),
                )
            ]
        )
        planner = AcquisitionPlanner(router)
        resource = {
            "resource_id": "res_abcdefghijklmnop",
            "platform": "shuge",
            "title": "天工开物.pdf",
            "resource_type": "book",
            "source_url": "https://shuge.hanjihebi.com/d/example.pdf",
        }
        representation = {
            "representation_id": "repr_abcdefghijklmnop",
            "kind": "document",
            "role": "primary",
            "container": "pdf",
            "mime_type": "application/pdf",
            "materializable": True,
            "requires_auth": False,
            **build_representation_authority(
                resource,
                scope="primary_resource",
                role="primary",
                technical_availability="available",
            ),
        }
        resolution = {
            "resolution_id": "resolution-1",
            "resolved_resource": {"representations": [representation]},
        }

        items = planner.plan_selection(
            [resource],
            [resolution],
            preferred_container="pdf",
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["planned_scope"], "primary_resource")
        self.assertEqual(item["strategy"], "direct_file")
        self.assertEqual(item["provider_id"], "generic-direct")
        self.assertEqual(item["provider_version"], "1.0.0")
        self.assertEqual(item["representation"]["selected_container"], "pdf")


if __name__ == "__main__":
    unittest.main()
