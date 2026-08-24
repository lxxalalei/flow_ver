"""Bilibili collection/series expansion without live network access."""

from __future__ import annotations

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
from education_resource_mcp.config import Settings
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


if __name__ == "__main__":
    unittest.main()
