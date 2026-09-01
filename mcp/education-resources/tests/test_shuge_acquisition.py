from __future__ import annotations

import unittest

from education_resource_mcp.acquisition import AcquisitionRouter, ProviderRegistration
from education_resource_mcp.acquisition.planner import AcquisitionPlanner


class _DirectProviderStub:
    def download(self, resource, job_id, strategy, cancel_event):  # pragma: no cover
        raise AssertionError("planner route test must not execute the provider")


class ShugeAcquisitionRouteTests(unittest.TestCase):
    def test_primary_pdf_routes_to_generic_direct(self) -> None:
        router = AcquisitionRouter(
            [ProviderRegistration("generic-direct", _DirectProviderStub())]
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
            "scope": "primary_resource",
            "technical_availability": "available",
            "materializable": True,
            "requires_auth": False,
        }
        resolution = {
            "resolution_id": "resolution-1",
            "resolved_resource": {"representations": [representation]},
        }

        plan = planner.route(
            resource,
            resolution,
            preferred_container="pdf",
        )

        self.assertEqual(plan["scope"], "primary_resource")
        self.assertEqual(plan["strategy"], "direct_file")
        self.assertEqual(plan["provider_id"], "generic-direct")
        self.assertEqual(plan["container"], "pdf")


if __name__ == "__main__":
    unittest.main()
