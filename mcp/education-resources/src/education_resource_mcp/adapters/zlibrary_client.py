"""Small synchronous client for Z-Library's authenticated EAPI.

The public MCP never accepts an email or password.  A user logs in in their
browser and SessionStore retains only the two canonical EAPI cookies.  The
client sends them only to one configured domain from its small trusted EAPI
allowlist; it does not discover or silently rotate credential-bearing requests
onto advertised or third-party mirrors.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request

from .http_client import urlopen_with_fallback


ZLIBRARY_COOKIE_NAMES = ("remix_userid", "remix_userkey")
ZLIBRARY_COOKIE_DOMAINS = ("z-library.ec", "z-library.sk", "1lib.sk")
_BOOK_HASH_RE = re.compile(r"^[0-9A-Za-z_-]{4,128}$")
_EXTENSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,15}$")


class ZlibraryError(RuntimeError):
    pass


class ZlibraryAuthRequired(ZlibraryError):
    pass


class ZlibraryUnavailable(ZlibraryError):
    pass


class ZlibraryLimitReached(ZlibraryError):
    pass


class ZlibraryNotFound(ZlibraryError):
    pass


@dataclass(frozen=True, slots=True)
class ZlibraryCredentials:
    domain: str
    remix_userid: str
    remix_userkey: str

    @property
    def cookie_header(self) -> str:
        return (
            f"remix_userid={self.remix_userid}; "
            f"remix_userkey={self.remix_userkey}; siteLanguageV2=zh"
        )


@dataclass(frozen=True, slots=True)
class ZlibraryBook:
    book_id: str
    book_hash: str
    title: str
    author: str = ""
    year: str = ""
    language: str = ""
    extension: str = ""
    size: str = ""
    isbn: str = ""
    publisher: str = ""
    pages: str = ""
    description: str = ""
    cover: str = ""


def _normalized_cookie_domain(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold().lstrip(".").rstrip(".")


def _allowed_cookie_domain(domain: str) -> bool:
    return any(
        domain == allowed or domain.endswith(f".{allowed}")
        for allowed in ZLIBRARY_COOKIE_DOMAINS
    )


def credentials_from_session_data(
    session_data: Mapping[str, Any] | None,
) -> ZlibraryCredentials:
    """Extract one complete canonical cookie pair from stored browser data."""

    grouped: dict[str, dict[str, str]] = {}
    cookies = session_data.get("cookies") if isinstance(session_data, Mapping) else None
    if isinstance(cookies, list):
        for cookie in cookies:
            if not isinstance(cookie, Mapping):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            domain = _normalized_cookie_domain(cookie.get("domain"))
            if (
                name not in ZLIBRARY_COOKIE_NAMES
                or not isinstance(value, str)
                or not value
                or not _allowed_cookie_domain(domain)
            ):
                continue
            grouped.setdefault(domain, {})[str(name)] = value
    for domain, values in grouped.items():
        if all(values.get(name) for name in ZLIBRARY_COOKIE_NAMES):
            return ZlibraryCredentials(
                domain=domain,
                remix_userid=values["remix_userid"],
                remix_userkey=values["remix_userkey"],
            )
    raise ZlibraryAuthRequired(
        "缺少 Z-Library 登录态，请先在浏览器中登录并保存会话"
    )


def resource_identity(resource: Mapping[str, Any]) -> tuple[str, str] | None:
    mappings: list[Mapping[str, Any]] = [resource]
    metadata = resource.get("metadata")
    if isinstance(metadata, Mapping):
        mappings.append(metadata)
        signals = metadata.get("platform_signals")
        if isinstance(signals, Mapping):
            mappings.append(signals)
    signals = resource.get("platform_signals")
    if isinstance(signals, Mapping):
        mappings.append(signals)
    for mapping in mappings:
        book_id = str(mapping.get("book_id") or mapping.get("id") or "").strip()
        book_hash = str(
            mapping.get("book_hash") or mapping.get("hash") or ""
        ).strip()
        if book_id.isdigit() and int(book_id) > 0 and _BOOK_HASH_RE.fullmatch(book_hash):
            return book_id, book_hash
    url = str(resource.get("source_url") or "")
    match = re.search(r"/book/(\d+)/([0-9A-Za-z_-]{4,128})(?:[/?#]|$)", url)
    if match:
        return match.group(1), match.group(2)
    return None


def _clean_scalar(value: Any, maximum: int = 512) -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return " ".join(str(value).split())[:maximum]
    return ""


def _book_from_mapping(value: Mapping[str, Any]) -> ZlibraryBook | None:
    book_id = _clean_scalar(value.get("id"), 32)
    book_hash = _clean_scalar(value.get("hash") or value.get("book_hash"), 128)
    if not book_id.isdigit() or not _BOOK_HASH_RE.fullmatch(book_hash):
        return None
    extension = _clean_scalar(value.get("extension"), 16).lstrip(".").lower()
    if extension and _EXTENSION_RE.fullmatch(extension) is None:
        extension = ""
    return ZlibraryBook(
        book_id=book_id,
        book_hash=book_hash,
        title=_clean_scalar(value.get("title") or value.get("name")) or f"Book {book_id}",
        author=_clean_scalar(value.get("author")),
        year=_clean_scalar(value.get("year"), 32),
        language=_clean_scalar(value.get("language"), 64),
        extension=extension,
        size=_clean_scalar(value.get("filesize") or value.get("size"), 64),
        isbn=_clean_scalar(value.get("isbn"), 128),
        publisher=_clean_scalar(value.get("publisher"), 256),
        pages=_clean_scalar(value.get("pages"), 32),
        description=_clean_scalar(value.get("description"), 2000),
        cover=_clean_scalar(value.get("cover"), 1000),
    )


def _payload_error(payload: Mapping[str, Any]) -> ZlibraryError | None:
    if payload.get("success") not in (0, "0", False):
        return None
    raw = payload.get("message") or payload.get("error") or payload.get("errors")
    message = _clean_scalar(raw, 500) or "Z-Library 请求失败"
    lowered = message.casefold()
    if any(word in lowered for word in ("login", "auth", "cookie", "user")):
        return ZlibraryAuthRequired(message)
    if any(word in lowered for word in ("limit", "daily", "quota")):
        return ZlibraryLimitReached(message)
    if "not found" in lowered:
        return ZlibraryNotFound(message)
    return ZlibraryError(message)


class ZlibraryClient:
    def __init__(self, session_store: Any, timeout: float = 30.0) -> None:
        self.session_store = session_store
        self.timeout = float(timeout)
        configured = os.environ.get(
            "EDUCATION_RESOURCE_MCP_ZLIBRARY_EAPI_DOMAIN", "z-library.ec"
        )
        self.eapi_domain = _normalized_cookie_domain(configured)
        if self.eapi_domain not in ZLIBRARY_COOKIE_DOMAINS:
            raise ValueError(
                "EDUCATION_RESOURCE_MCP_ZLIBRARY_EAPI_DOMAIN must be a trusted "
                "Z-Library EAPI domain"
            )

    def credentials(self) -> ZlibraryCredentials:
        getter = getattr(self.session_store, "get_session_data", None)
        data = getter("zlibrary") if callable(getter) else None
        return credentials_from_session_data(data)

    def _request_json(
        self,
        path: str,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ZlibraryCredentials]:
        captured = self.credentials()
        credentials = ZlibraryCredentials(
            domain=self.eapi_domain,
            remix_userid=captured.remix_userid,
            remix_userkey=captured.remix_userkey,
        )
        url = f"https://{self.eapi_domain}{path}"
        encoded = urlencode(data or {}, doseq=True).encode("utf-8") if data is not None else None
        request = Request(
            url,
            data=encoded,
            headers={
                "User-Agent": "EducationResourceMCP/0.4",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": credentials.cookie_header,
            },
            method="POST" if data is not None else "GET",
        )
        try:
            with urlopen_with_fallback(
                request, timeout=self.timeout, follow_redirects=False
            ) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in (401,):
                raise ZlibraryAuthRequired("Z-Library 登录态已失效") from exc
            if exc.code == 429:
                raise ZlibraryLimitReached("Z-Library 请求或下载额度已用尽") from exc
            if exc.code in (307, 403, 513, 517):
                raise ZlibraryUnavailable(
                    f"Z-Library 当前域名拒绝程序访问（HTTP {exc.code}）"
                ) from exc
            if exc.code == 404:
                raise ZlibraryNotFound("Z-Library 资源不存在") from exc
            raise ZlibraryUnavailable(f"Z-Library HTTP {exc.code}") from exc
        except URLError as exc:
            raise ZlibraryUnavailable(f"Z-Library 网络不可用：{exc.reason}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ZlibraryUnavailable("Z-Library 返回了非 JSON 页面，可能被反爬拦截") from exc
        if not isinstance(payload, dict):
            raise ZlibraryUnavailable("Z-Library 返回结构不是对象")
        error = _payload_error(payload)
        if error is not None:
            raise error
        return payload, credentials

    def search(self, query: str, limit: int = 10) -> list[ZlibraryBook]:
        payload, _ = self._request_json(
            "/eapi/book/search",
            data={"message": query, "limit": str(max(1, min(limit, 50))), "page": "1"},
        )
        books = payload.get("books")
        if not isinstance(books, list):
            raise ZlibraryUnavailable("Z-Library 搜索响应缺少 books 数组")
        result: list[ZlibraryBook] = []
        for item in books:
            if isinstance(item, Mapping) and (book := _book_from_mapping(item)) is not None:
                result.append(book)
        return result

    def get_book(self, book_id: str, book_hash: str) -> ZlibraryBook:
        if not book_id.isdigit() or _BOOK_HASH_RE.fullmatch(book_hash) is None:
            raise ZlibraryError("无效的 Z-Library 图书身份")
        payload, _ = self._request_json(f"/eapi/book/{book_id}/{book_hash}")
        raw = payload.get("book") if isinstance(payload.get("book"), Mapping) else payload
        book = _book_from_mapping(raw)
        if book is None:
            raise ZlibraryNotFound("Z-Library 没有返回有效图书详情")
        return book

    def get_download_url(self, book_id: str, book_hash: str) -> tuple[str, ZlibraryCredentials]:
        payload, credentials = self._request_json(
            f"/eapi/book/{book_id}/{book_hash}/file"
        )
        file_value = payload.get("file")
        nested = file_value if isinstance(file_value, Mapping) else {}
        raw_url = (
            nested.get("downloadLink")
            or payload.get("downloadLink")
            or payload.get("url")
            or payload.get("link")
        )
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise ZlibraryLimitReached(
                "Z-Library 没有返回下载地址，可能已达到每日额度"
            )
        return urljoin(f"https://{credentials.domain}/", raw_url.strip()), credentials


__all__ = [
    "ZLIBRARY_COOKIE_DOMAINS",
    "ZLIBRARY_COOKIE_NAMES",
    "ZlibraryAuthRequired",
    "ZlibraryBook",
    "ZlibraryClient",
    "ZlibraryCredentials",
    "ZlibraryError",
    "ZlibraryLimitReached",
    "ZlibraryNotFound",
    "ZlibraryUnavailable",
    "credentials_from_session_data",
    "resource_identity",
]
