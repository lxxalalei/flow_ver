"""Focused regressions for public-access behavior reported from OpenClaw."""

from __future__ import annotations

from pathlib import Path
import tempfile

from education_resource_mcp.adapters.libgen import LibgenSearchAdapter
from education_resource_mcp.adapters.inspect_libgen import LibgenInspector
from education_resource_mcp.adapters.libgen_client import Book
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


def _settings(root: Path) -> Settings:
    return Settings(data_dir=root, jobs_dir=root / "jobs")


def test_libgen_search_exposes_anonymous_mirror_route() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        adapter = LibgenSearchAdapter(SessionStore(root), _settings(root))
        adapter._client.mirrors = ["https://libgen.example"]
        adapter._client.search = lambda query, limit: [
            Book(
                md5="a" * 32,
                title="公开镜像图书",
                author="作者",
                extension="pdf",
            )
        ]

        resources, error = adapter.search("公开镜像图书", 5)

    assert error is None
    assert len(resources) == 1
    resource = resources[0]
    assert resource["source_url"] == (
        "https://libgen.example/ads.php?md5=" + "a" * 32
    )
    assert resource["metadata"]["download_feasibility"] == "匿名镜像"
    signals = resource["metadata"]["platform_signals"]
    assert signals["md5"] == "a" * 32
    assert signals["acquisition_route"] == "libgen_mirror"


def test_libgen_inspection_explicitly_declares_no_authentication() -> None:
    resource = {
        "resource_id": "res_test",
        "platform": "libgen",
        "title": "公开镜像图书",
        "source_url": "https://libgen.example/ads.php?md5=" + "b" * 32,
        "resource_type": "book",
        "metadata": {
            "platform_signals": {
                "md5": "b" * 32,
                "format": "pdf",
                "acquisition_route": "libgen_mirror",
            }
        },
    }

    payload = LibgenInspector().inspect(resource).to_mapping()
    assert payload["resolution_status"] == "resolved"
    assert payload["resolved_resource"]["availability"]["status"] == "available"

    representations = payload["resolved_resource"]["representations"]
    primary = next(
        item
        for item in representations
        if item.get("scope") == "primary_resource" and item.get("role") == "primary"
    )
    assert primary["technical_availability"] == "available"
    assert primary["materializable"] is True
    assert primary["requires_auth"] is False
