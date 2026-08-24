"""Focused tests for Douyin collection enumeration."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from education_resource_mcp.adapters.douyin import DouyinSearchAdapter, MIX_URL
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionStore


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        jobs_dir=root / "jobs",
        library_dir=root / "library",
        max_workers=1,
    )


def _aweme(aweme_id: str, title: str) -> dict:
    return {
        "aweme_id": aweme_id,
        "desc": title,
        "author": {
            "nickname": "creator",
            "sec_uid": "sec_user_1",
        },
        "statistics": {},
        "create_time": 1700000000,
    }


class DouyinCollectionExpandTests(unittest.TestCase):
    def test_collection_paginates_until_has_more_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
            adapter = DouyinSearchAdapter(store, _settings(root))
            responses = [
                {
                    "aweme_list": [_aweme("101", "part 1")],
                    "has_more": True,
                    "cursor": 12,
                },
                {
                    "aweme_list": [_aweme("102", "part 2")],
                    "has_more": False,
                    "cursor": 24,
                },
            ]

            with patch(
                "education_resource_mcp.adapters.douyin.sign_a_bogus",
                return_value="signed",
            ), patch.object(
                adapter,
                "_request_json",
                side_effect=responses,
            ) as request_json:
                resources = list(
                    adapter.iter_collection(
                        "https://www.douyin.com/collection/123"
                    )
                )

        self.assertEqual(["part 1", "part 2"], [item["title"] for item in resources])
        self.assertEqual(2, request_json.call_count)
        first_url = request_json.call_args_list[0].args[0]
        second_url = request_json.call_args_list[1].args[0]
        self.assertTrue(first_url.startswith(MIX_URL))
        self.assertIn("mix_id=123", first_url)
        self.assertIn("cursor=0", first_url)
        self.assertIn("cursor=12", second_url)

    def test_collection_rejects_missing_mix_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
            adapter = DouyinSearchAdapter(store, _settings(root))
            with self.assertRaises(Exception) as ctx:
                list(adapter.iter_collection("https://www.douyin.com/collection/not-a-number"))

        self.assertEqual("INVALID_ARGUMENT", getattr(ctx.exception, "code", None))


if __name__ == "__main__":
    unittest.main()
