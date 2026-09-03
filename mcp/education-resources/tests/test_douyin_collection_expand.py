"""Focused tests for Douyin collection enumeration (browser-driven).

No live network and no real browser: page behaviour is faked at the boundary
of ``douyin_browser`` (goto/redirect, fired mix responses, keyboard presses).
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.adapters import douyin as douyin_mod
from education_resource_mcp.adapters import douyin_browser
from education_resource_mcp.adapters.douyin import DouyinSearchAdapter, _AdapterError
from education_resource_mcp.config import Settings
from education_resource_mcp.errors import DomainError
from education_resource_mcp.sessions import SessionStore


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        jobs_dir=root / "jobs",
        library_dir=root / "library",
        max_workers=1,
    )


def _aweme(aweme_id: str, title: str, mix_name: str | None = None) -> dict:
    item = {
        "aweme_id": aweme_id,
        "desc": title,
        "author": {
            "nickname": "creator",
            "sec_uid": "sec_user_1",
        },
        "statistics": {},
        "create_time": 1700000000,
    }
    if mix_name:
        item["mix_info"] = {"mix_id": "123", "mix_name": mix_name}
    return item


def _mix_payload(items: list[dict], has_more: bool) -> dict:
    return {"aweme_list": items, "has_more": has_more}


def _detail(sec_uid: str = "MS4wLjABAAAA-test") -> dict:
    return {
        "author": {"sec_uid": sec_uid, "nickname": "creator"},
        "mix_info": {"mix_id": "123", "mix_name": "测试合集"},
    }


class _FakeResponse:
    def __init__(self, url: str, payload: dict) -> None:
        self.url = url
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeKeyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    def press(self, key: str) -> None:
        self.presses.append(key)


class _FakePage:
    """Plays a scripted sequence of goto stages.

    Each stage is ``(final_url, responses)``: ``goto`` adopts ``final_url`` as
    the page URL (simulating the collection redirect) and fires each response
    through the registered handler. ``dom_sec_uid`` is what the author-link
    lookup script "finds" in the DOM.
    """

    def __init__(
        self,
        stages: list[tuple[str, list[_FakeResponse]]],
        dom_sec_uid: str | None = None,
    ) -> None:
        self.stages = list(stages)
        self.url = ""
        self.handlers: list = []
        self.keyboard = _FakeKeyboard()
        self.dom_sec_uid = dom_sec_uid

    def on(self, event: str, handler) -> None:
        self.handlers.append(handler)

    def goto(self, url: str, **_kwargs) -> None:
        self.url = url
        stage = self.stages.pop(0) if self.stages else (url, [])
        self.url, responses = stage
        for response in responses:
            for handler in self.handlers:
                handler(response)

    def evaluate(self, script: str) -> object:
        if '"/user/"' in script:
            return self.dom_sec_uid
        return 0

    def wait_for_url(self, _pattern: object, timeout: int = 0) -> None:
        return None


def _saved_session(root: Path) -> SessionStore:
    store = SessionStore(root)
    store.save(
        "douyin",
        {
            "cookies": [
                {
                    "name": "sessionid",
                    "value": "abc",
                    "domain": ".douyin.com",
                }
            ]
        },
    )
    return store


_ORIGINAL_TIMING = (
    douyin_browser.INITIAL_PAGE_WAIT_SECONDS,
    douyin_browser.MODAL_OPEN_WAIT_SECONDS,
    douyin_browser.KEY_PRESS_INTERVAL_SECONDS,
    douyin_browser.STALE_STOP_ROUNDS,
)


def _zero_timing() -> None:
    douyin_browser.INITIAL_PAGE_WAIT_SECONDS = 0.0
    douyin_browser.MODAL_OPEN_WAIT_SECONDS = 0.0
    douyin_browser.KEY_PRESS_INTERVAL_SECONDS = (0.0, 0.0)


def _restore_timing() -> None:
    (
        douyin_browser.INITIAL_PAGE_WAIT_SECONDS,
        douyin_browser.MODAL_OPEN_WAIT_SECONDS,
        douyin_browser.KEY_PRESS_INTERVAL_SECONDS,
        douyin_browser.STALE_STOP_ROUNDS,
    ) = _ORIGINAL_TIMING


class DouyinBrowserEnumerationTests(unittest.TestCase):
    def setUp(self) -> None:
        _zero_timing()

    def tearDown(self) -> None:
        _restore_timing()

    def test_happy_path_collects_playlist_order_and_confirms_complete(self) -> None:
        page = _FakePage(
            [
                # collection URL redirects to an episode (seed)
                ("https://www.douyin.com/video/900", []),
                # modal open fires two mix batches, last one has_more=0
                (
                    "https://www.douyin.com/user/MS4wLjABAAAA-test",
                    [
                        _FakeResponse(
                            "https://www.douyin.com/aweme/v1/web/mix/aweme/?x=1",
                            _mix_payload(
                                [_aweme("101", "part 1", mix_name="穿越合集")],
                                has_more=True,
                            ),
                        ),
                        _FakeResponse(
                            "https://www.douyin.com/aweme/v1/web/mix/aweme/?x=2",
                            _mix_payload([_aweme("102", "part 2")], has_more=False),
                        ),
                    ],
                ),
            ],
            dom_sec_uid="MS4wLjABAAAA-test",
        )

        def _fail_detail(_aweme_id: str) -> dict:
            raise AssertionError("DOM lookup succeeded; detail API must not be called")

        items, info = douyin_browser.enumerate_collection(
            {"cookies": []},
            mix_id="123",
            fetch_detail=_fail_detail,
            page=page,
        )

        self.assertEqual(["101", "102"], [item["aweme_id"] for item in items])
        self.assertTrue(info["confirmed_complete"])
        # mix_name comes from the harvested items when the detail API is skipped
        self.assertEqual("穿越合集", info["mix_name"])
        self.assertEqual("MS4wLjABAAAA-test", info["creator_sec_uid"])

    def test_dom_lookup_miss_falls_back_to_detail_api(self) -> None:
        page = _FakePage(
            [
                ("https://www.douyin.com/video/900", []),
                (
                    "https://www.douyin.com/user/MS4wLjABAAAA-test",
                    [
                        _FakeResponse(
                            "https://www.douyin.com/aweme/v1/web/mix/aweme/?x=1",
                            _mix_payload([_aweme("101", "part 1")], has_more=False),
                        )
                    ],
                ),
            ],
            dom_sec_uid=None,
        )
        items, info = douyin_browser.enumerate_collection(
            {"cookies": []},
            mix_id="123",
            fetch_detail=lambda _aid: _detail("MS4wLjABAAAA-from-detail"),
            page=page,
        )
        self.assertEqual(1, len(items))
        self.assertEqual("MS4wLjABAAAA-from-detail", info["creator_sec_uid"])
        self.assertEqual("测试合集", info["mix_name"])

    def test_dedupes_replayed_aweme_ids(self) -> None:
        replay = _FakeResponse(
            "https://www.douyin.com/aweme/v1/web/mix/aweme/?x=1",
            _mix_payload([_aweme("101", "part 1")], has_more=False),
        )
        page = _FakePage(
            [
                ("https://www.douyin.com/video/900", []),
                (
                    "https://www.douyin.com/user/u",
                    [replay, replay],
                ),
            ]
        )
        items, info = douyin_browser.enumerate_collection(
            {"cookies": []}, mix_id="123", fetch_detail=lambda _a: _detail(), page=page
        )
        self.assertEqual(1, len(items))
        self.assertTrue(info["confirmed_complete"])

    def test_stale_without_has_more_zero_reports_incomplete(self) -> None:
        douyin_browser.STALE_STOP_ROUNDS = 3
        try:
            page = _FakePage(
                [
                    ("https://www.douyin.com/video/900", []),
                    (
                        "https://www.douyin.com/user/u",
                        [
                            _FakeResponse(
                                "https://www.douyin.com/aweme/v1/web/mix/aweme/?x=1",
                                _mix_payload([_aweme("101", "part 1")], has_more=True),
                            )
                        ],
                    ),
                ]
            )
            items, info = douyin_browser.enumerate_collection(
                {"cookies": []},
                mix_id="123",
                fetch_detail=lambda _a: _detail(),
                page=page,
            )
        finally:
            douyin_browser.STALE_STOP_ROUNDS = 20
        self.assertEqual(1, len(items))
        self.assertFalse(info["confirmed_complete"])

    def test_no_mix_responses_raises(self) -> None:
        page = _FakePage(
            [
                ("https://www.douyin.com/video/900", []),
                ("https://www.douyin.com/user/u", []),
            ]
        )
        with self.assertRaises(DomainError) as ctx:
            douyin_browser.enumerate_collection(
                {"cookies": []},
                mix_id="123",
                fetch_detail=lambda _a: _detail(),
                page=page,
            )
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)

    def test_missing_redirect_seed_raises(self) -> None:
        page = _FakePage(
            [("https://www.douyin.com/somewhere-else", [])]
        )
        with self.assertRaises(DomainError) as ctx:
            douyin_browser.enumerate_collection(
                {"cookies": []},
                mix_id="123",
                fetch_detail=lambda _a: _detail(),
                page=page,
            )
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)

    def test_missing_playwright_raises_dependency_error(self) -> None:
        with mock.patch.dict(sys.modules, {"playwright": None}):
            with self.assertRaises(DomainError) as ctx:
                douyin_browser.enumerate_collection(
                    {"cookies": []},
                    mix_id="123",
                    fetch_detail=lambda _a: _detail(),
                )
        self.assertEqual("DEPENDENCY_MISSING", ctx.exception.code)


class DouyinAdapterCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = _saved_session(self.root)
        self.adapter = DouyinSearchAdapter(self.store, _settings(self.root))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_iter_collection_yields_normalized_and_complete(self) -> None:
        raw = [_aweme("101", "part 1"), _aweme("102", "part 2")]
        with mock.patch.object(
            douyin_mod,
            "enumerate_collection",
            return_value=(raw, {"confirmed_complete": True, "cancelled": False}),
        ) as fake:
            resources = list(
                self.adapter.iter_collection("https://www.douyin.com/collection/123")
            )
        self.assertEqual(["part 1", "part 2"], [r["title"] for r in resources])
        self.assertEqual("https://www.douyin.com/video/101", resources[0]["source_url"])
        self.assertEqual("123", fake.call_args.kwargs["mix_id"])

    def test_iter_collection_incomplete_raises_partial_after_yield(self) -> None:
        raw = [_aweme("101", "part 1")]
        with mock.patch.object(
            douyin_mod,
            "enumerate_collection",
            return_value=(raw, {"confirmed_complete": False, "cancelled": False}),
        ):
            generator = self.adapter.iter_collection(
                "https://www.douyin.com/collection/123"
            )
            yielded = []
            with self.assertRaises(_AdapterError) as ctx:
                for resource in generator:
                    yielded.append(resource)
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(1, len(yielded))

    def test_iter_collection_cancelled_yields_without_failure(self) -> None:
        raw = [_aweme("101", "part 1")]
        with mock.patch.object(
            douyin_mod,
            "enumerate_collection",
            return_value=(raw, {"confirmed_complete": False, "cancelled": True}),
        ):
            resources = list(
                self.adapter.iter_collection("https://www.douyin.com/collection/123")
            )
        self.assertEqual(1, len(resources))

    def test_collection_rejects_missing_mix_id(self) -> None:
        with self.assertRaises(Exception) as ctx:
            list(
                self.adapter.iter_collection(
                    "https://www.douyin.com/collection/not-a-number"
                )
            )
        self.assertEqual("INVALID_ARGUMENT", getattr(ctx.exception, "code", None))

    def test_collection_requires_saved_session(self) -> None:
        empty_root = Path(tempfile.mkdtemp())
        try:
            adapter = DouyinSearchAdapter(
                SessionStore(empty_root), _settings(empty_root)
            )
            with self.assertRaises(Exception) as ctx:
                list(adapter.iter_collection("https://www.douyin.com/collection/123"))
        finally:
            import shutil

            shutil.rmtree(empty_root, ignore_errors=True)
        self.assertEqual("AUTH_REQUIRED", getattr(ctx.exception, "code", None))


if __name__ == "__main__":
    unittest.main()
