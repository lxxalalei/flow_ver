from __future__ import annotations

import unittest

from education_resource_mcp.acquisition.download_dispatch import select_download_handler


class _DirectProviderStub:
    def download(self, resource, job_id, strategy, cancel_event):  # pragma: no cover
        raise AssertionError("handler selection test must not execute the provider")


class ShugeAcquisitionRouteTests(unittest.TestCase):
    def test_primary_pdf_selects_generic_direct_handler(self) -> None:
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

        route = select_download_handler(
            resource,
            resolution,
            preferred_container="pdf",
            handlers={"generic-direct": _DirectProviderStub()},
        )

        self.assertEqual(route["scope"], "primary_resource")
        self.assertEqual(route["strategy"], "direct_file")
        self.assertEqual(route["provider_id"], "generic-direct")
        self.assertEqual(route["container"], "pdf")


if __name__ == "__main__":
    unittest.main()
