"""Tests for platform-specific search adapters and the multi-platform dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import threading
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from education_resource_mcp.adapters.base import make_resource, adapter_error
from education_resource_mcp.adapters.wbi import wbi_sign, _get_mixin_key
from education_resource_mcp.adapters.bilibili import BilibiliSearchAdapter
from education_resource_mcp.adapters.douyin import DouyinSearchAdapter
from education_resource_mcp.adapters.zhihu import ZhihuSearchAdapter
from education_resource_mcp.adapters.smartedu import SmartEduSearchAdapter
from education_resource_mcp.adapters.annas_archive import AnnasArchiveSearchAdapter
from education_resource_mcp.adapters.annas_archive_download import AnnasArchiveDownloader
from education_resource_mcp.adapters.libgen_client import LibgenDownloadResult, LibgenError
from education_resource_mcp.errors import DomainError
from education_resource_mcp.config import Settings
from education_resource_mcp.search import (
    MultiPlatformSearchProvider,
    GenericWebSearchProvider,
    default_search_provider,
)
from education_resource_mcp.sessions import SessionStore


def _settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "database.sqlite",
        jobs_dir=data_dir / "jobs",
        library_dir=data_dir / "library",
    )


def _mock_response(body: dict | str, status: int = 200, content_type: str = "application/json"):
    """Build a context-manager mock matching urlopen_with_fallback's interface."""
    resp = MagicMock()
    if isinstance(body, str):
        resp.read.return_value = body.encode("utf-8")
    else:
        resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.status = status
    resp.headers = {"Content-Type": content_type}
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# WBI signing
# ---------------------------------------------------------------------------

class WbiSignTests(unittest.TestCase):
    # Real WBI keys are 32 chars each; combined length must be >= 64
    # because WBI_KEY_TABLE indices go up to 63.
    _IMG_KEY = "7cd084941338484aae1ad9425b84077c"
    _SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

    def test_sign_adds_wts_and_wrid(self) -> None:
        params = {"keyword": "test", "page": 1}
        signed = wbi_sign(params, self._IMG_KEY, self._SUB_KEY)
        self.assertIn("wts", signed)
        self.assertIn("w_rid", signed)
        self.assertEqual(len(signed["w_rid"]), 32)  # MD5 hex

    def test_mixin_key_is_32_chars(self) -> None:
        key = _get_mixin_key(self._IMG_KEY + self._SUB_KEY)
        self.assertEqual(len(key), 32)

    def test_sign_is_deterministic_for_same_inputs(self) -> None:
        import time
        t = int(time.time())
        with patch("education_resource_mcp.adapters.wbi.time.time", return_value=t):
            s1 = wbi_sign({"q": "x"}, self._IMG_KEY, self._SUB_KEY)
            s2 = wbi_sign({"q": "x"}, self._IMG_KEY, self._SUB_KEY)
        self.assertEqual(s1["w_rid"], s2["w_rid"])


# ---------------------------------------------------------------------------
# make_resource / adapter_error helpers
# ---------------------------------------------------------------------------

class MakeResourceTests(unittest.TestCase):
    def test_minimal_fields(self) -> None:
        r = make_resource(platform="test", title="T", source_url="https://example.com")
        self.assertEqual(r["platform"], "test")
        self.assertEqual(r["title"], "T")
        self.assertEqual(r["resource_type"], "其他")
        self.assertIsNone(r["summary"])
        self.assertEqual(r["metadata"]["platform_signals"], {})

    def test_full_fields(self) -> None:
        r = make_resource(
            platform="bilibili", title="T", source_url="https://example.com",
            resource_type="视频", summary="desc", author="UP主",
            published_at="2024-01-01", language="zh", download_feasibility="中",
            platform_signals={"views": 100},
        )
        self.assertEqual(r["metadata"]["author"], "UP主")
        self.assertEqual(r["metadata"]["platform_signals"]["views"], 100)


# ---------------------------------------------------------------------------
# Bilibili adapter
# ---------------------------------------------------------------------------

class BilibiliAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> BilibiliSearchAdapter:
        return BilibiliSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_search_works_without_session(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            # Without a session the adapter should still attempt search
            # (cookie is optional for B站). It will fail on the network
            # call, but should NOT return AUTH_REQUIRED.
            results, error = adapter.search("test", 10)
        # No session → empty cookie, but NOT AUTH_REQUIRED
        if error:
            self.assertNotEqual(error["code"], "AUTH_REQUIRED")

    def test_search_returns_normalized_results(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("bilibili", {"cookies": [{"name": "SESSDATA", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            nav_response = {
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                    }
                },
            }
            search_response = {
                "code": 0,
                "data": {
                    "result": [
                        {
                            "bvid": "BV1xx411c7mD",
                            "title": "<em class=\"keyword\">英语</em>启蒙动画",
                            "description": "幼儿英语启蒙",
                            "author": "UP主",
                            "play": 12345,
                            "video_review": 100,
                            "pubdate": 1700000000,
                        }
                    ]
                },
            }

            responses = [_mock_response(nav_response), _mock_response(search_response)]
            with patch(
                "education_resource_mcp.adapters.bilibili.urlopen_with_fallback",
                side_effect=responses,
            ):
                results, error = adapter.search("英语启蒙", 10)

        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "bilibili")
        self.assertEqual(r["title"], "英语启蒙动画")  # HTML stripped
        self.assertEqual(r["source_url"], "https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(r["resource_type"], "视频")
        self.assertEqual(r["metadata"]["platform_signals"]["views"], 12345)

    def test_api_auth_error_returns_auth_required(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("bilibili", {"cookies": [{"name": "SESSDATA", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            nav_response = {
                "code": 0,
                "data": {"wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }},
            }
            search_response = {"code": -101, "message": "账号未登录"}

            responses = [_mock_response(nav_response), _mock_response(search_response)]
            with patch(
                "education_resource_mcp.adapters.bilibili.urlopen_with_fallback",
                side_effect=responses,
            ):
                results, error = adapter.search("test", 10)

        self.assertEqual(results, [])
        self.assertEqual(error["code"], "AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# Douyin adapter
# ---------------------------------------------------------------------------

class DouyinAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> DouyinSearchAdapter:
        return DouyinSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_no_session_returns_auth_required(self) -> None:
        """Without a stored session the adapter must return AUTH_REQUIRED."""
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            results, error = adapter.search("test", 10)
        self.assertEqual(results, [])
        self.assertEqual(error["code"], "AUTH_REQUIRED")
        self.assertFalse(error["retryable"])

    def test_search_returns_normalized_results(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("douyin", {"cookies": [{"name": "sessionid", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            search_response = {
                "status_code": 0,
                "has_more": False,
                "data": [
                    {
                        "aweme_info": {
                            "aweme_id": "7300000000000000001",
                            "desc": "幼儿英语启蒙动画",
                            "statistics": {
                                "digg_count": 5200,
                                "comment_count": 88,
                                "play_count": 120000,
                            },
                            "author": {"nickname": "教育小课堂"},
                            "create_time": 1700000000,
                        }
                    }
                ],
            }

            with patch(
                "education_resource_mcp.adapters.douyin.urlopen_with_fallback",
                return_value=_mock_response(search_response),
            ):
                results, error = adapter.search("英语启蒙", 10)

        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "douyin")
        self.assertEqual(r["title"], "幼儿英语启蒙动画")
        self.assertEqual(r["source_url"], "https://www.douyin.com/video/7300000000000000001")
        self.assertEqual(r["resource_type"], "视频")
        self.assertEqual(r["metadata"]["platform_signals"]["likes"], 5200)
        self.assertEqual(r["metadata"]["platform_signals"]["plays"], 120000)
        self.assertEqual(r["metadata"]["author"], "教育小课堂")

    def test_api_error_status_code(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("douyin", {"cookies": [{"name": "sessionid", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            # Non-zero status_code with no data → PARTIAL_FAILURE
            search_response = {
                "status_code": 8,
                "status_msg": "访问过于频繁",
                "has_more": False,
                "data": [],
            }

            with patch(
                "education_resource_mcp.adapters.douyin.urlopen_with_fallback",
                return_value=_mock_response(search_response),
            ):
                results, error = adapter.search("test", 10)

        self.assertEqual(results, [])
        self.assertEqual(error["code"], "PARTIAL_FAILURE")

    def test_http_403_returns_auth_required(self) -> None:
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("douyin", {"cookies": [{"name": "sessionid", "value": "abc"}]})
            adapter = self._adapter(data_dir)

            with patch(
                "education_resource_mcp.adapters.douyin.urlopen_with_fallback",
                side_effect=HTTPError("url", 403, "Forbidden", {}, None),
            ):
                results, error = adapter.search("test", 10)

        self.assertEqual(results, [])
        self.assertEqual(error["code"], "AUTH_REQUIRED")
        self.assertFalse(error["retryable"])


# ---------------------------------------------------------------------------
# Zhihu adapter
# ---------------------------------------------------------------------------

class ZhihuAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> ZhihuSearchAdapter:
        return ZhihuSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_no_session_degrades_to_html_then_engine(self) -> None:
        """Without session, the adapter should not crash — it tries HTML/engine fallback."""
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            # All HTTP returns empty.
            with patch(
                "education_resource_mcp.adapters.zhihu.urlopen_with_fallback",
                return_value=_mock_response("<html></html>", content_type="text/html"),
            ):
                results, error = adapter.search("test", 5)
        self.assertEqual(results, [])
        # Should report either AUTH_REQUIRED or PARTIAL_FAILURE.
        self.assertIn(error["code"], ("AUTH_REQUIRED", "PARTIAL_FAILURE"))

    def test_api_search_with_valid_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("zhihu", {"cookies": [
                {"name": "z_c0", "value": "session_token"},
                {"name": "d_c0", "value": "device_token"},
            ]})
            adapter = self._adapter(data_dir)

            api_response = {
                "data": [
                    {
                        "object": {
                            "type": "answer",
                            "id": "12345",
                            "title": "如何教孩子<em>学英语</em>",
                            "excerpt": "英语启蒙方法",
                            "author": {"name": "教育专家"},
                            "question": {"id": "67890"},
                        }
                    }
                ],
                "paging": {"is_end": True},
            }

            with patch(
                "education_resource_mcp.adapters.zhihu.urlopen_with_fallback",
                return_value=_mock_response(api_response),
            ):
                results, error = adapter.search("学英语", 10)

        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "zhihu")
        self.assertEqual(r["title"], "如何教孩子学英语")
        self.assertEqual(r["resource_type"], "问答")
        self.assertIn("/question/67890/answer/12345", r["source_url"])


# ---------------------------------------------------------------------------
# SmartEdu adapter
# ---------------------------------------------------------------------------

class SmartEduAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> SmartEduSearchAdapter:
        return SmartEduSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_search_returns_normalized_results(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("smartedu", {"tokens": {"accessToken": "test_token_abc"}})
            adapter = self._adapter(data_dir)

            search_response = {
                "data": {
                    "list": [
                        {
                            "id": "res-001",
                            "title": "三年级数学上册",
                            "description": "人教版三年级数学",
                            "tab_code": "qualityCourse",
                            "search_resource_type": "course",
                            "resource_type": "elite_lesson",
                            "tab_code": "qualityCourse",
                            "tags": [
                                {"dimension_id": "zxxnj", "title": "三年级"},
                                {"dimension_id": "zxxbb", "title": "人教版"},
                            ],
                        }
                    ]
                }
            }

            with patch(
                "education_resource_mcp.adapters.smartedu.urlopen_with_fallback",
                return_value=_mock_response(search_response),
            ):
                results, error = adapter.search("三年级数学", 10)

        self.assertIsNone(error)
        self.assertGreaterEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["platform"], "smartedu")
        self.assertEqual(r["title"], "三年级数学上册")
        self.assertTrue(r["source_url"].startswith("https://basic.smartedu.cn/"))

    def test_all_endpoints_fail_returns_partial_failure(self) -> None:
        from urllib.error import URLError
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store = SessionStore(data_dir)
            store.save("smartedu", {"tokens": {"accessToken": "token"}})
            adapter = self._adapter(data_dir)

            with patch(
                "education_resource_mcp.adapters.smartedu.urlopen_with_fallback",
                side_effect=URLError("connection refused"),
            ):
                results, error = adapter.search("test", 10)

        self.assertEqual(results, [])
        self.assertEqual(error["code"], "PARTIAL_FAILURE")
        self.assertTrue(error["retryable"])


# ---------------------------------------------------------------------------
# MultiPlatformSearchProvider dispatcher
# ---------------------------------------------------------------------------

class MultiPlatformSearchProviderTests(unittest.TestCase):
    def test_dispatches_to_platform_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            generic = GenericWebSearchProvider(settings)
            provider = MultiPlatformSearchProvider(settings, store, generic)

            # Register a stub adapter.
            stub = MagicMock()
            stub.platform_id = "bilibili"
            stub.search.return_value = (
                [make_resource(platform="bilibili", title="T", source_url="https://bilibili.com/v/1")],
                None,
            )
            provider.register_adapter(stub)

            resources, platform_runs = provider.search(
                [{"platform": "bilibili", "queries": [{"query": "test"}]}], 10
            )

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["platform"], "bilibili")
        self.assertEqual(len(platform_runs), 1)
        self.assertEqual(platform_runs[0]["platform"], "bilibili")
        self.assertEqual(platform_runs[0]["status"], "succeeded")
        stub.search.assert_called_once_with("test", 10)

    def test_unknown_platform_returns_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            generic = GenericWebSearchProvider(settings)
            provider = MultiPlatformSearchProvider(settings, store, generic)

            resources, platform_runs = provider.search(
                [{"platform": "nonexistent", "queries": [{"query": "test"}]}], 10
            )

        self.assertEqual(resources, [])
        self.assertEqual(len(platform_runs), 1)
        self.assertEqual(platform_runs[0]["platform"], "nonexistent")
        self.assertEqual(platform_runs[0]["status"], "skipped")
        self.assertEqual(
            platform_runs[0]["query_runs"][0]["error"]["code"],
            "PLATFORM_UNAVAILABLE",
        )

    def test_generic_path_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            generic = GenericWebSearchProvider(settings, engines=["duckduckgo"])
            provider = MultiPlatformSearchProvider(settings, store, generic)

            response = {
                "results": [
                    {"platform": "generic", "title": "网页", "source_url": "https://example.com/a", "type": "网页"},
                ],
                "errors": [],
            }
            with patch(
                "education_resource_mcp.search.generic_web.search",
                return_value=response,
            ):
                resources, platform_runs = provider.search(
                    [{"platform": "generic", "queries": [{"query": "test"}]}], 5
                )

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["platform"], "generic")

    def test_default_search_provider_returns_multi_when_session_store_given(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            store = SessionStore(data_dir)
            provider = default_search_provider(settings, store)
        self.assertIsInstance(provider, MultiPlatformSearchProvider)

    def test_default_search_provider_returns_generic_without_session_store(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            settings = _settings(data_dir)
            provider = default_search_provider(settings)
        self.assertIsInstance(provider, GenericWebSearchProvider)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Anna's Archive adapter (Libgen-backed)
# ---------------------------------------------------------------------------

_LIBGEN_SEARCH_HTML = """<html><body><table>
<tr>
<td><a href="edition.php?id=123">Python Programming Guide<font color="green">9781234567890</font></a></td>
<td>Guido van Rossum</td>
<td>O'Reilly Media</td>
<td>2023</td>
<td>English</td>
<td>500</td>
<td><a href="file.php?id=456">15 MB</a></td>
<td>pdf</td>
<td><a href="ads.php?md5=abcdef0123456789abcdef0123456789" title="Mirror 1">1</a></td>
</tr>
<tr>
<td><a href="edition.php?id=124">Machine Learning Basics</a></td>
<td>Tom Mitchell</td>
<td>MIT Press</td>
<td>2022</td>
<td>English</td>
<td>320</td>
<td><a href="file.php?id=457">8 MB</a></td>
<td>epub</td>
<td><a href="ads.php?md5=bbcddef0123456789abcdef0123456789" title="Mirror 1">1</a></td>
</tr>
</table></body></html>"""

_LIBGEN_PATCH = "education_resource_mcp.adapters.libgen_client.urlopen_with_fallback"


class AnnasArchiveAdapterTests(unittest.TestCase):
    def _adapter(self, data_dir: Path) -> AnnasArchiveSearchAdapter:
        return AnnasArchiveSearchAdapter(SessionStore(data_dir), _settings(data_dir))

    def test_search_returns_normalized_results(self) -> None:
        """Libgen HTML search → normalized make_resource with full metadata."""
        resp = _mock_response(_LIBGEN_SEARCH_HTML, content_type="text/html")
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            with patch(_LIBGEN_PATCH, return_value=resp):
                results, error = adapter.search("python", 10)
        self.assertIsNone(error)
        self.assertEqual(len(results), 2)
        first = results[0]
        self.assertEqual(first["platform"], "annas-archive")
        self.assertIn("Python Programming Guide", first["title"])
        self.assertEqual(first["resource_type"], "图书")
        self.assertIn("abcdef0123456789abcdef0123456789", first["source_url"])
        signals = first["metadata"]["platform_signals"]
        self.assertEqual(signals["md5"], "abcdef0123456789abcdef0123456789")
        self.assertEqual(signals["format"], "pdf")
        self.assertEqual(signals["language"], "English")
        self.assertEqual(first["metadata"].get("author"), "Guido van Rossum")

    def test_search_all_mirrors_fail(self) -> None:
        """All mirrors unreachable → PARTIAL_FAILURE."""
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            with patch(_LIBGEN_PATCH, side_effect=URLError("all mirrors down")):
                results, error = adapter.search("python", 10)
        self.assertEqual(results, [])
        self.assertEqual(error["code"], "PARTIAL_FAILURE")
        self.assertTrue(error["retryable"])

    def test_search_empty_page(self) -> None:
        """Empty HTML page (no matching rows) → empty results, no error."""
        resp = _mock_response("<html><body>No results found</body></html>", content_type="text/html")
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            with patch(_LIBGEN_PATCH, return_value=resp):
                results, error = adapter.search("nonexistent", 10)
        self.assertIsNone(error)
        self.assertEqual(results, [])

    def test_mirror_failover(self) -> None:
        """First mirror fails, second succeeds → results returned."""
        ok_resp = _mock_response(_LIBGEN_SEARCH_HTML, content_type="text/html")
        with tempfile.TemporaryDirectory() as d:
            adapter = self._adapter(Path(d))
            with patch(_LIBGEN_PATCH, side_effect=[URLError("503"), ok_resp]):
                results, error = adapter.search("python", 10)
        self.assertIsNone(error)
        self.assertEqual(len(results), 2)


class AnnasArchiveDownloaderTests(unittest.TestCase):
    def _downloader(self, data_dir: Path) -> AnnasArchiveDownloader:
        return AnnasArchiveDownloader(SessionStore(data_dir), _settings(data_dir))

    def _resource(self, md5: str = "abcdef0123456789abcdef0123456789") -> dict:
        return {
            "source_url": f"https://annas-archive.gl/md5/{md5}",
            "title": "Test Book",
            "metadata": {"platform_signals": {"md5": md5}},
        }

    def test_download_extracts_md5_from_signals(self) -> None:
        """Download reads md5 from platform_signals."""
        with tempfile.TemporaryDirectory() as d:
            dl = self._downloader(Path(d))
            job = Path(d) / "jobs" / "job1"
            job.mkdir(parents=True)
            (job / "test.pdf").write_bytes(b"x" * 1024)
            fake = LibgenDownloadResult(
                path=job / "test.pdf", size_bytes=1024,
                mirror="https://libgen.bz",
                url="https://libgen.bz/get.php?md5=abc",
                filename="test.pdf",
            )
            with patch.object(dl._client, "download", return_value=fake):
                result = dl.download(
                    self._resource(), "job1", "direct",
                    cancel_event=threading.Event(),
                )
        self.assertEqual(result.media_type, "application/pdf")
        self.assertEqual(result.byte_size, 1024)
        self.assertEqual(result.filename, "test.pdf")
        self.assertEqual(len(result.sha256), 64)

    def test_download_extracts_md5_from_url(self) -> None:
        """Download falls back to md5 from source_url when signals missing."""
        with tempfile.TemporaryDirectory() as d:
            dl = self._downloader(Path(d))
            job = Path(d) / "jobs" / "job1"
            job.mkdir(parents=True)
            (job / "book.epub").write_bytes(b"y" * 512)
            fake = LibgenDownloadResult(
                path=job / "book.epub", size_bytes=512,
                mirror="https://libgen.bz",
                url="https://libgen.bz/get.php?md5=xyz",
                filename="book.epub",
            )
            resource = {"source_url": "https://anns-archive.gl/md5/bbcd1234567890abcdef1234567890ab",
                        "title": "Book", "metadata": {}}
            with patch.object(dl._client, "download", return_value=fake):
                result = dl.download(resource, "job1", "direct", threading.Event())
        self.assertEqual(result.media_type, "application/epub+zip")

    def test_download_no_md5_raises(self) -> None:
        """Resource without md5 anywhere → DOWNLOAD_FAILED."""
        with tempfile.TemporaryDirectory() as d:
            dl = self._downloader(Path(d))
            with self.assertRaises(DomainError) as ctx:
                dl.download(
                    {"source_url": "https://example.com/no-md5-here",
                     "title": "X", "metadata": {}},
                    "job1", "direct", threading.Event(),
                )
            self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")

    def test_download_cancel(self) -> None:
        """LibgenError(JOB_CANCELLED) → DomainError(JOB_CANCELLED)."""
        with tempfile.TemporaryDirectory() as d:
            dl = self._downloader(Path(d))
            with patch.object(dl._client, "download",
                              side_effect=LibgenError("JOB_CANCELLED")):
                with self.assertRaises(DomainError) as ctx:
                    dl.download(self._resource(), "job1", "direct",
                                threading.Event())
            self.assertEqual(ctx.exception.code, "JOB_CANCELLED")

    def test_download_failure_is_mapped(self) -> None:
        """Libgen failures remain structured download failures."""
        with tempfile.TemporaryDirectory() as d:
            dl = self._downloader(Path(d))
            with patch.object(dl._client, "download",
                              side_effect=LibgenError("mirror failed")):
                with self.assertRaises(DomainError) as ctx:
                    dl.download(self._resource(), "job1", "direct",
                                threading.Event())
            self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
