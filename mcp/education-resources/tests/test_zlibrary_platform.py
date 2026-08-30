from __future__ import annotations

import email.message
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs
from urllib.request import Request

import pytest

from education_resource_mcp.adapters.inspect_zlibrary import ZlibraryInspector
from education_resource_mcp.adapters.resource_urls import identify_resource_url
from education_resource_mcp.adapters.zlibrary import ZlibrarySearchAdapter
from education_resource_mcp.adapters.zlibrary_client import (
    ZlibraryAuthRequired,
    ZlibraryBook,
    ZlibraryClient,
    ZlibraryCredentials,
)
from education_resource_mcp.adapters.zlibrary_download import (
    ZlibraryDownloader,
    _CredentialSafeRedirectHandler,
)
from education_resource_mcp.config import Settings
from education_resource_mcp.sessions import SessionError, SessionStore


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        jobs_dir=root / "jobs",
        library_dir=root / "library",
        max_workers=1,
    )


def _cookies(*, noise: bool = True) -> list[dict[str, object]]:
    values: list[dict[str, object]] = [
        {
            "name": "remix_userid",
            "value": "42",
            "domain": ".z-library.sk",
            "path": "/",
        },
        {
            "name": "remix_userkey",
            "value": "secret-key",
            "domain": ".z-library.sk",
            "path": "/",
        },
    ]
    if noise:
        values.append(
            {
                "name": "analytics",
                "value": "discard-me",
                "domain": ".z-library.sk",
                "path": "/",
            }
        )
    return values


class _Headers(email.message.Message):
    def get_content_type(self) -> str:
        return self.get("Content-Type", "application/octet-stream").split(";", 1)[0]


class _Response:
    def __init__(self, body: bytes, *, content_type: str = "application/json") -> None:
        self._body = body
        self._offset = 0
        self.status = 200
        self.url = "https://z-library.sk/eapi/test"
        self.headers = _Headers()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        result = self._body[self._offset : self._offset + amount]
        self._offset += len(result)
        return result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_session_store_retains_only_canonical_zlibrary_cookies(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    result = store.save("zlibrary", {"cookies": _cookies()})

    assert result["stored_credential_count"] == 2
    stored = store.get_session_data("zlibrary")
    assert stored is not None
    assert {cookie["name"] for cookie in stored["cookies"]} == {
        "remix_userid",
        "remix_userkey",
    }


def test_session_store_rejects_incomplete_zlibrary_cookie_pair(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    with pytest.raises(SessionError) as caught:
        store.save("zlibrary", {"cookies": _cookies(noise=False)[:1]})
    assert caught.value.code == "SESSION_EMPTY"


def test_client_search_uses_eapi_and_normalizes_books(monkeypatch) -> None:
    class _Store:
        def get_session_data(self, platform: str):
            assert platform == "zlibrary"
            return {"cookies": _cookies(noise=False)}

    captured: dict[str, object] = {}

    def fake_open(request: Request, **kwargs):
        captured["url"] = request.full_url
        captured["cookie"] = request.get_header("Cookie")
        captured["data"] = parse_qs((request.data or b"").decode())
        captured["kwargs"] = kwargs
        return _Response(
            json.dumps(
                {
                    "success": 1,
                    "books": [
                        {
                            "id": 123,
                            "hash": "abcDEF_123",
                            "title": "三体",
                            "author": "刘慈欣",
                            "extension": "EPUB",
                            "filesize": "2 MB",
                        }
                    ],
                }
            ).encode()
        )

    monkeypatch.setattr(
        "education_resource_mcp.adapters.zlibrary_client.urlopen_with_fallback",
        fake_open,
    )
    books = ZlibraryClient(_Store(), timeout=7).search("三体", 10)

    assert books == [
        ZlibraryBook(
            book_id="123",
            book_hash="abcDEF_123",
            title="三体",
            author="刘慈欣",
            extension="epub",
            size="2 MB",
        )
    ]
    assert captured["url"] == "https://z-library.ec/eapi/book/search"
    assert captured["data"] == {"message": ["三体"], "limit": ["10"], "page": ["1"]}
    assert "remix_userkey=secret-key" in str(captured["cookie"])
    assert captured["kwargs"] == {"timeout": 7.0, "follow_redirects": False}


def test_search_adapter_returns_auth_required_without_session(tmp_path: Path) -> None:
    adapter = ZlibrarySearchAdapter(SessionStore(tmp_path), _settings(tmp_path))
    resources, error = adapter.search("三体", 10)
    assert resources == []
    assert error is not None
    assert error["code"] == "AUTH_REQUIRED"


def test_inspector_rechecks_detail_and_emits_authenticated_document() -> None:
    class _Client:
        def get_book(self, book_id: str, book_hash: str) -> ZlibraryBook:
            assert (book_id, book_hash) == ("123", "abcDEF_123")
            return ZlibraryBook(
                book_id=book_id,
                book_hash=book_hash,
                title="三体",
                author="刘慈欣",
                extension="epub",
            )

    resource = {
        "platform": "zlibrary",
        "title": "三体",
        "source_url": "https://z-library.sk/book/123/abcDEF_123",
        "resource_type": "book",
        "metadata": {
            "platform_signals": {"book_id": "123", "book_hash": "abcDEF_123"}
        },
    }
    result = ZlibraryInspector(session_store=None, client=_Client()).inspect(resource)
    mapped = result.to_mapping()
    assert mapped["resolution_status"] == "resolved"
    representation = mapped["resolved_resource"]["representations"][0]
    assert representation["container"] == "epub"
    assert representation["requires_auth"] is True
    assert representation["materializable"] is True


def test_downloader_writes_real_file_from_eapi_link(tmp_path: Path, monkeypatch) -> None:
    payload = b"PK\x03\x04epub-content"

    class _Client:
        def get_download_url(self, book_id: str, book_hash: str):
            assert (book_id, book_hash) == ("123", "abcDEF_123")
            return (
                "https://files.z-library.sk/download/123",
                ZlibraryCredentials("z-library.sk", "42", "secret-key"),
            )

    class _Opener:
        def open(self, request: Request, timeout: float):
            assert request.full_url == "https://files.z-library.sk/download/123"
            assert "remix_userid=42" in str(request.get_header("Cookie"))
            assert timeout == 90.0
            return _Response(payload, content_type="application/epub+zip")

    monkeypatch.setattr(
        "education_resource_mcp.adapters.zlibrary_download.build_opener",
        lambda *_handlers: _Opener(),
    )
    downloader = ZlibraryDownloader(
        SessionStore(tmp_path), _settings(tmp_path), client=_Client()
    )
    result = downloader.download(
        {
            "platform": "zlibrary",
            "title": "三体",
            "source_url": "https://z-library.sk/book/123/abcDEF_123",
            "metadata": {
                "platform_signals": {
                    "book_id": "123",
                    "book_hash": "abcDEF_123",
                    "format": "epub",
                }
            },
        },
        "job-1",
        "direct",
        threading.Event(),
    )
    assert result.path.read_bytes() == payload
    assert result.filename == "三体.epub"
    assert result.media_type == "application/epub+zip"


def test_redirect_handler_removes_cookie_for_external_host() -> None:
    handler = _CredentialSafeRedirectHandler("z-library.sk")
    original = Request(
        "https://z-library.sk/download/123",
        headers={"Cookie": "remix_userkey=secret", "User-Agent": "test"},
    )
    redirected = handler.redirect_request(
        original,
        None,
        302,
        "Found",
        {},
        "https://cdn.example/download/123",
    )
    assert redirected is not None
    assert redirected.get_header("Cookie") is None


def test_known_zlibrary_url_restores_platform_identity() -> None:
    resource = identify_resource_url(
        "https://z-library.sk/book/123/abcDEF_123"
    )
    assert resource["platform"] == "zlibrary"
    assert resource["metadata"]["platform_signals"] == {
        "book_id": "123",
        "book_hash": "abcDEF_123",
    }
