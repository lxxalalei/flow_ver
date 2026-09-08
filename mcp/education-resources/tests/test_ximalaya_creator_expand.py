"""Focused offline tests for Ximalaya creator expansion."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from education_resource_mcp.adapters.expansion import expand_resource
from education_resource_mcp.errors import DomainError


class _Provider:
    def __init__(self) -> None:
        self._adapters = {"ximalaya": SimpleNamespace(timeout=5.0)}


class _Response:
    def __init__(self, payload: Any) -> None:
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _album(album_id: int, title: str) -> dict:
    return {
        "id": album_id,
        "title": title,
        "description": f"{title} 简介",
        "anchorNickName": "测试主播",
        "playCount": album_id * 10,
        "trackCount": album_id,
        "isPaid": False,
        "isFinished": True,
        "coverPath": f"//imagev2.xmcdn.com/{album_id}.jpg",
    }


class XimalayaCreatorExpandTests(unittest.TestCase):
    def test_creator_expands_all_pages_to_albums(self) -> None:
        requests = []
        payloads = [
            {
                "ret": 200,
                "data": {
                    "page": 1,
                    "pageSize": 2,
                    "totalCount": 3,
                    "maxCount": 2,
                    "albumList": [_album(11, "专辑一"), _album(12, "专辑二")],
                },
            },
            {
                "ret": 200,
                "data": {
                    "page": 2,
                    "pageSize": 1,
                    "totalCount": 3,
                    "maxCount": 2,
                    "albumList": [_album(13, "专辑三")],
                },
            },
        ]

        def transport(request, *, timeout):
            requests.append((request, timeout))
            return _Response(payloads.pop(0))

        target = {
            "platform": "ximalaya",
            "resource_type": "creator",
            "source_url": "https://www.ximalaya.com/zhubo/12345",
        }
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            side_effect=transport,
        ):
            results = list(expand_resource(_Provider(), target))

        self.assertEqual(
            ["专辑一", "专辑二", "专辑三"],
            [x["title"] for x in results],
        )
        self.assertTrue(all(x["resource_type"] == "album" for x in results))
        self.assertEqual(
            "https://www.ximalaya.com/album/11",
            results[0]["source_url"],
        )
        self.assertEqual(
            "https://imagev2.xmcdn.com/11.jpg",
            results[0]["metadata"]["platform_signals"]["cover_url"],
        )
        self.assertEqual(
            ["1", "2"],
            [parse_qs(urlsplit(req.full_url).query)["page"][0] for req, _ in requests],
        )
        self.assertEqual(
            ["100", "100"],
            [
                parse_qs(urlsplit(req.full_url).query)["pageSize"][0]
                for req, _ in requests
            ],
        )
        self.assertEqual(
            ["12345", "12345"],
            [parse_qs(urlsplit(req.full_url).query)["uid"][0] for req, _ in requests],
        )

    def test_creator_does_not_silently_accept_incomplete_pagination(self) -> None:
        payloads = [
            {
                "ret": 200,
                "data": {
                    "totalCount": 2,
                    "albumList": [_album(11, "专辑一")],
                },
            },
            {"ret": 200, "data": {"totalCount": 2, "albumList": []}},
        ]
        target = {
            "platform": "ximalaya",
            "resource_type": "creator",
            "source_url": "https://www.ximalaya.com/zhubo/12345",
        }
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            side_effect=lambda request, *, timeout: _Response(payloads.pop(0)),
        ):
            with self.assertRaises(DomainError) as ctx:
                list(expand_resource(_Provider(), target))
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)
        self.assertIn("1/2", ctx.exception.message)

    def test_creator_rejects_non_object_response(self) -> None:
        target = {
            "platform": "ximalaya",
            "resource_type": "creator",
            "source_url": "https://www.ximalaya.com/zhubo/12345",
        }
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            return_value=_Response([]),
        ):
            with self.assertRaises(DomainError) as ctx:
                list(expand_resource(_Provider(), target))
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)

    def test_album_signature_gate_is_not_a_login_problem(self) -> None:
        # getTracksList gates on the front-end xm-sign signature (ret=407
        # "webtk缺失"), not on login: even a signed request that still 407s is
        # a capability boundary, so it must surface as a non-retryable
        # PARTIAL_FAILURE - never as AUTH_REQUIRED (which would send the agent
        # chasing a login that cannot fix it).
        target = {
            "platform": "ximalaya",
            "resource_type": "album",
            "source_url": "https://www.ximalaya.com/album/20665610",
        }
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            return_value=_Response({"ret": 407, "msg": "webtk缺失", "code": 5}),
        ), mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand._generate_xm_sign",
            return_value="cadd&&sid",
        ):
            with self.assertRaises(DomainError) as ctx:
                list(expand_resource(_Provider(), target))
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("签名", ctx.exception.message)
        self.assertNotIn("AUTH_REQUIRED", str(ctx.exception.to_dict()))

    def test_album_expands_tracks_anonymously_when_available(self) -> None:
        payloads = [
            {
                "ret": 200,
                "data": {
                    "trackTotalCount": 2,
                    "tracks": [
                        {"trackId": 101, "title": "第一集", "duration": 300},
                        {"trackId": 102, "title": "第二集", "duration": 301},
                    ],
                },
            },
            {"ret": 200, "data": {"trackTotalCount": 2, "tracks": []}},
        ]
        requests: list = []

        def transport(request, *, timeout):
            requests.append(request)
            return _Response(payloads.pop(0))

        target = {
            "platform": "ximalaya",
            "resource_type": "album",
            "source_url": "https://www.ximalaya.com/album/20665610",
        }
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            side_effect=transport,
        ), mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand._generate_xm_sign",
            return_value="cadd&&sid",
        ):
            results = list(expand_resource(_Provider(), target))
        self.assertEqual(2, len(results))
        self.assertEqual("https://www.ximalaya.com/sound/101", results[0]["source_url"])
        self.assertTrue(requests)
        self.assertEqual("cadd&&sid", requests[0].get_header("Xm-sign"))

    def test_album_sends_saved_session_cookie_and_signature(self) -> None:
        class _Store:
            def get_session_data(self, platform):
                return {"platform": platform, "cookies": {"webtk": "abc123"}}

            def _cookie_header(self, data):
                return "webtk=abc123"

        seen = {}
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            side_effect=lambda request, *, timeout: _capture_cookie(seen, request),
        ), mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand._generate_xm_sign",
            return_value="cadd&&sid",
        ):
            with self.assertRaises(DomainError):
                list(
                    expand_resource(
                        _Provider(),
                        {
                            "platform": "ximalaya",
                            "resource_type": "album",
                            "source_url": "https://www.ximalaya.com/album/20665610",
                        },
                        session_store=_Store(),
                    )
                )
        self.assertEqual("webtk=abc123", seen.get("cookie"))
        self.assertEqual("cadd&&sid", seen.get("xm_sign"))

    def test_album_reports_signature_boundary_when_signer_unavailable(self) -> None:
        target = {
            "platform": "ximalaya",
            "resource_type": "album",
            "source_url": "https://www.ximalaya.com/album/20665610",
        }
        with mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand.urlopen_with_fallback",
            return_value=_Response({"ret": 407, "msg": "webtk缺失"}),
        ), mock.patch(
            "education_resource_mcp.adapters.ximalaya_expand._generate_xm_sign",
            side_effect=RuntimeError("signing service unreachable"),
        ):
            with self.assertRaises(DomainError) as ctx:
                list(expand_resource(_Provider(), target))
        self.assertEqual("PARTIAL_FAILURE", ctx.exception.code)
        self.assertIn("签名不可用", ctx.exception.message)
        self.assertIn("浏览器页面内完成枚举", ctx.exception.message)


    def test_creator_url_requires_numeric_uid(self) -> None:
        target = {
            "platform": "ximalaya",
            "resource_type": "creator",
            "source_url": "https://www.ximalaya.com/zhubo/not-a-uid",
        }
        with self.assertRaises(DomainError) as ctx:
            list(expand_resource(_Provider(), target))
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


def _capture_cookie(seen, request) -> _Response:
    seen["cookie"] = request.get_header("Cookie")
    # urllib capitalizes custom header names ("xm-sign" -> "Xm-sign").
    seen["xm_sign"] = request.get_header("Xm-sign")
    return _Response({"ret": 407, "msg": "webtk缺失"})


class XimalayaAlbumExpandTests(unittest.TestCase):
    def test_album_requires_numeric_album_id(self) -> None:
        target = {
            "platform": "ximalaya",
            "resource_type": "album",
            "source_url": "https://www.ximalaya.com/album/not-a-number",
        }
        with self.assertRaises(DomainError) as ctx:
            list(expand_resource(_Provider(), target))
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
