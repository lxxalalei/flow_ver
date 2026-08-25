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

    def test_creator_url_requires_numeric_uid(self) -> None:
        target = {
            "platform": "ximalaya",
            "resource_type": "creator",
            "source_url": "https://www.ximalaya.com/zhubo/not-a-uid",
        }
        with self.assertRaises(DomainError) as ctx:
            list(expand_resource(_Provider(), target))
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
