#!/usr/bin/env python3
"""Targeted fixture tests for NLC Yuewen search and EPUB download."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
PLATFORM_SCRIPTS = HERE.parent
if str(PLATFORM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLATFORM_SCRIPTS))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import nlc_search
from yuewen_search import parse_yuewen_page, yuewen_search_url


DOWNLOAD_PATH = HERE.parents[2] / "resource-downloader/scripts/platforms/nlc_download.py"
SPEC = importlib.util.spec_from_file_location("nlc_download", DOWNLOAD_PATH)
assert SPEC is not None and SPEC.loader is not None
nlc_download = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nlc_download)


SEARCH_FIXTURE = """
<ul class="WLWX2023_home_list">
  <li><a class="book" href="/yuewen/detail?id=1441793">
    <span class="pic"><img src="https://example.test/cover.webp"></span>
    <span class="right">
      <span class="tt">陈宝明医案医论集粹</span>
      <span class="txt1"><i class="lab">中医</i>陈江华主编</span>
      <span class="txt2">公开电子书简介。</span>
    </span>
  </a></li>
  <li><a class="book" href="/yuewen/detail?id=1441793"><span class="tt">重复项</span></a></li>
</ul>
"""


def epub_bytes(valid_mimetype: bool = True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip" if valid_mimetype else "application/zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr("META-INF/container.xml", "<container/>")
    return output.getvalue()


class FakeHeaders(dict):
    def get_content_charset(self) -> str:
        return "utf-8"


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self.buffer = io.BytesIO(body)
        self.headers = FakeHeaders(headers or {})

    def read(self, size: int = -1) -> bytes:
        return self.buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeOpener:
    def __init__(self, epub: bytes):
        self.epub = epub
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        path = urllib.parse.urlsplit(request.full_url).path
        if path == "/yuewen/read":
            return FakeResponse(b"cbid:'32062738804861106',ccid:'',supportFormat:'2'")
        if path == "/yuewen/readContent":
            payload = urllib.parse.parse_qs(request.data.decode("ascii"))
            if payload.get("supportFormat") != ["2"]:
                raise AssertionError("supportFormat was not preserved")
            body = json.dumps(
                {"success": True, "msg": "", "obj": "fixture.epub"}
            ).encode("utf-8")
            return FakeResponse(body)
        if path == "/yuewen/download/fixture.epub":
            return FakeResponse(self.epub, {"Content-Length": str(len(self.epub))})
        raise AssertionError(f"unexpected request: {request.full_url}")


class YuewenSearchTests(unittest.TestCase):
    def test_parse_public_search_result(self):
        results = parse_yuewen_page(SEARCH_FIXTURE)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["resource_id"], "nlc:yuewen:1441793")
        self.assertEqual(
            item["source_url"], "http://read.nlc.cn/yuewen/detail?id=1441793"
        )
        self.assertEqual(item["title"], "陈宝明医案医论集粹")
        self.assertEqual(item["author"], "陈江华主编")
        self.assertEqual(item["raw_metadata"]["classify"], "中医")
        self.assertTrue(item["is_free"])

    def test_search_url_uses_title_and_page_number(self):
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(yuewen_search_url("红楼梦", 2)).query
        )
        self.assertEqual(query, {"title": ["红楼梦"], "pageNo": ["2"]})

    def test_digital_and_ebook_scopes_use_yuewen(self):
        original = nlc_search.search_yuewen
        calls = []

        def fake_search(query, max_results, timeout, request_text):
            calls.append((query, max_results, timeout, request_text))
            return parse_yuewen_page(SEARCH_FIXTURE)

        nlc_search.search_yuewen = fake_search
        try:
            for scope in ("digital", "ebook"):
                document = nlc_search.search("中医", scope, 5, 10)
                self.assertEqual(document["results"][0]["resource_id"], "nlc:yuewen:1441793")
                self.assertEqual(document["scope"], scope)
        finally:
            nlc_search.search_yuewen = original
        self.assertEqual(len(calls), 2)

    def test_catalog_and_site_dispatch_remain_unchanged(self):
        original_catalog = nlc_search.search_catalog
        original_site = nlc_search.search_site
        calls = []

        def fake_catalog(query, max_results, timeout):
            calls.append(("catalog", query, max_results, timeout))
            return []

        def fake_site(query, max_results, timeout):
            calls.append(("site", query, max_results, timeout))
            return []

        nlc_search.search_catalog = fake_catalog
        nlc_search.search_site = fake_site
        try:
            nlc_search.search("馆藏", "catalog", 3, 9)
            nlc_search.search("展览", "site", 4, 8)
        finally:
            nlc_search.search_catalog = original_catalog
            nlc_search.search_site = original_site
        self.assertEqual(
            calls,
            [("catalog", "馆藏", 3, 9), ("site", "展览", 4, 8)],
        )


class YuewenDownloadTests(unittest.TestCase):
    def test_download_uses_three_step_flow_and_validates_epub(self):
        opener = FakeOpener(epub_bytes())
        with tempfile.TemporaryDirectory() as output_dir:
            path = nlc_download.download_epub(
                "http://read.nlc.cn/yuewen/detail?id=1441793",
                output_dir,
                opener=opener,
            )
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "nlc-yuewen-1441793.epub")
            nlc_download.validate_epub(path)
        self.assertEqual(
            [urllib.parse.urlsplit(item.full_url).path for item in opener.requests],
            ["/yuewen/read", "/yuewen/readContent", "/yuewen/download/fixture.epub"],
        )
        self.assertEqual(opener.requests[1].get_method(), "POST")

    def test_invalid_epub_is_removed(self):
        opener = FakeOpener(epub_bytes(valid_mimetype=False))
        with tempfile.TemporaryDirectory() as output_dir:
            with self.assertRaises(nlc_download.DownloadError):
                nlc_download.download_epub(
                    "http://read.nlc.cn/yuewen/detail?id=1441793",
                    output_dir,
                    opener=opener,
                )
            self.assertEqual(list(Path(output_dir).iterdir()), [])

    def test_rejects_non_yuewen_hosts(self):
        with self.assertRaises(nlc_download.DownloadError):
            nlc_download.parse_source("https://example.com/yuewen/detail?id=1")


if __name__ == "__main__":
    unittest.main()
