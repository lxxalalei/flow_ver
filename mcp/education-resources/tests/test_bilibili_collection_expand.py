"""Bilibili collection/series expansion without live network access."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters.bilibili import (
    BilibiliSearchAdapter,
    _AdapterError,
    _parse_collection_url,
)
from education_resource_mcp.batch import run_batch_collect
from education_resource_mcp.config import Settings
from education_resource_mcp.job_state import read_job, write_job, write_request
from education_resource_mcp.sessions import SessionStore


COLLECTION_URL = "https://space.bilibili.com/2142762/lists/3662502?type=season"
SERIES_URL = "https://space.bilibili.com/1958703906/lists/547718?type=series"


def _archive(index: int, *, mid: str = "2142762") -> dict:
    return {
        "bvid": f"BV1TEST{index:04d}",
        "title": f"视频 {index}",
        "desc": f"简介 {index}",
        "pubdate": 1700000000 + index,
        "owner": {"mid": int(mid), "name": "测试UP"},
        "stat": {"view": 100 + index, "danmaku": index, "favorite": 10 + index},
    }


class _NeverCancel:
    def is_set(self) -> bool:
        return False


class BilibiliCollectionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        settings = Settings(
            data_dir=root,
            jobs_dir=root / "jobs",
            library_dir=root / "library",
            max_workers=1,
        )
        self.adapter = BilibiliSearchAdapter(SessionStore(root), settings)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_parse_new_and_legacy_urls(self) -> None:
        self.assertEqual(("2142762", "3662502", "season"), _parse_collection_url(COLLECTION_URL))
        self.assertEqual(("1958703906", "547718", "series"), _parse_collection_url(SERIES_URL))
        self.assertEqual(
            ("2142762", "57445", "season"),
            _parse_collection_url(
                "https://space.bilibili.com/2142762/channel/collectiondetail?sid=57445"
            ),
        )
        self.assertEqual(
            ("1958703906", "547718", "series"),
            _parse_collection_url(
                "https://space.bilibili.com/1958703906/channel/seriesdetail?sid=547718"
            ),
        )

    def test_invalid_collection_url_is_loud(self) -> None:
        with self.assertRaises(_AdapterError) as ctx:
            _parse_collection_url("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)

    def test_collection_pages_until_reported_total(self) -> None:
        calls: list[str] = []

        def fake_request(url: str, *, referer: str, cookie: str) -> dict:
            del referer, cookie
            calls.append(url)
            query = parse_qs(urlparse(url).query)
            page = int(query["page_num"][0])
            archives = [_archive(i) for i in range(1, 31)] if page == 1 else [_archive(31)]
            return {
                "code": 0,
                "data": {
                    "archives": archives,
                    "page": {"page_num": page, "page_size": 30, "total": 31},
                },
            }

        self.adapter._request_json = fake_request  # type: ignore[method-assign]
        resources = list(self.adapter.iter_collection(COLLECTION_URL))

        self.assertEqual(31, len(resources))
        self.assertEqual("https://www.bilibili.com/video/BV1TEST0001", resources[0]["source_url"])
        self.assertEqual("测试UP", resources[0]["metadata"]["author"])
        self.assertEqual(2, len(calls))
        self.assertTrue(all("seasons_archives_list" in url for url in calls))

    def test_series_uses_series_archives_endpoint(self) -> None:
        calls: list[str] = []

        def fake_request(url: str, *, referer: str, cookie: str) -> dict:
            del referer, cookie
            calls.append(url)
            return {
                "code": 0,
                "data": {
                    "archives": [_archive(1, mid="1958703906"), _archive(2, mid="1958703906")],
                    "page": {"num": 1, "size": 30, "total": 2},
                },
            }

        self.adapter._request_json = fake_request  # type: ignore[method-assign]
        resources = list(self.adapter.iter_collection(SERIES_URL))

        self.assertEqual(2, len(resources))
        self.assertEqual(1, len(calls))
        self.assertIn("/x/series/archives", calls[0])
        query = parse_qs(urlparse(calls[0]).query)
        self.assertEqual(["547718"], query["series_id"])
        self.assertEqual(["1958703906"], query["mid"])


class BilibiliCollectionBatchTests(unittest.TestCase):
    def test_collection_expand_only_enumerates_candidates(self) -> None:
        class FakeAdapter:
            def iter_collection(self, source_url: str, *, cancel_event=None):
                self.source_url = source_url
                del cancel_event
                yield {
                    "platform": "bilibili",
                    "title": "视频 A",
                    "source_url": "https://www.bilibili.com/video/BV1AAAA",
                    "resource_type": "视频",
                    "metadata": {"author": "UP"},
                }
                yield {
                    "platform": "bilibili",
                    "title": "视频 B",
                    "source_url": "https://www.bilibili.com/video/BV1BBBB",
                    "resource_type": "视频",
                    "metadata": {"author": "UP"},
                }

        adapter = FakeAdapter()
        provider = type("Provider", (), {"_adapters": {"bilibili": adapter}})()
        service = type("Service", (), {"search_provider": provider})()

        with tempfile.TemporaryDirectory() as directory:
            job_dir = Path(directory)
            write_request(
                job_dir,
                {
                    "kind": "batch_collect",
                    "job_id": "job_test",
                    "mode": "collection_expand",
                    "platform": "bilibili",
                    # ResourceService currently persists the collection locator in this generic
                    # batch locator slot; the public MCP schema exposes it as collection_url.
                    "creator_id": COLLECTION_URL,
                    "max_items": None,
                },
            )
            write_job(
                job_dir,
                {
                    "job_id": "job_test",
                    "kind": "batch_collect",
                    "mode": "collection_expand",
                    "platform": "bilibili",
                    "status": "queued",
                    "total": 0,
                    "completed": 0,
                    "files": [],
                    "failures": [],
                    "pid": None,
                },
            )

            self.assertEqual(0, run_batch_collect(job_dir, service))
            status = read_job(job_dir)
            self.assertEqual("succeeded", status["status"])
            self.assertEqual(2, status["completed"])
            lines = (job_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
            items = [json.loads(line) for line in lines]

        self.assertEqual(["视频 A", "视频 B"], [item["title"] for item in items])
        self.assertEqual(COLLECTION_URL, adapter.source_url)
        # No download side effect exists in this batch worker; results are candidate URLs only.
        self.assertTrue(all(item["url"].startswith("https://www.bilibili.com/video/") for item in items))


if __name__ == "__main__":
    unittest.main()
