from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import threading

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.config import Settings
from education_resource_mcp.downloader import DownloadResult
from education_resource_mcp.search import StaticSearchProvider
from education_resource_mcp.server import create_server
from education_resource_mcp.service import ResourceService


class FixtureDownloader:
    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir

    def download(
        self,
        resource: dict,
        job_id: str,
        strategy: str,
        max_bytes: int,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        payload = f"<html>{resource['title']}</html>".encode()
        directory = self.jobs_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "fixture.html"
        path.write_bytes(payload)
        return DownloadResult(
            path=path,
            byte_size=len(payload),
            media_type="text/html",
            sha256=hashlib.sha256(payload).hexdigest(),
            filename=path.name,
        )


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
    service = ResourceService(
        settings,
        search_provider=provider,
        download_provider=FixtureDownloader(settings.jobs_dir),
    )
    create_server(service).run("stdio")


if __name__ == "__main__":
    main()
