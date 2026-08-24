"""CCTV (央视网) search and structural expansion adapter.

Discovery uses two public, login-free endpoints:
  * search.cctv.com/ifsearch.php — site video search (leaf episodes);
  * api.cntv.cn/lanmu/columnSearch — column directory (JSONP).

Column episode listing delegates to the local cctv-dl binary (see
``cctv_download.run_cctv_dl_list``); documentary series pages embed their
full episode list in HTML and expand without the binary. Single episodes
resolve to a 32-hex guid embedded in the page, which is also the download
key used by cctv-dl.
"""

from __future__ import annotations

import json
import re
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request

from ..config import Settings
from ..errors import DomainError
from ..sessions import SessionStore
from .base import adapter_error, descriptor_for_platform, make_resource
from .http_client import urlopen_with_fallback


SEARCH_API = "https://search.cctv.com/ifsearch.php"
SEARCH_PAGE = "https://search.cctv.com/search.php"
COLUMN_SEARCH_API = "https://api.cntv.cn/lanmu/columnSearch"
COLUMN_SEARCH_REFERER = "https://tv.cctv.com/lm/index.shtml"
COLUMN_INDEX_URL = "https://tv.cctv.com/lm/index.shtml"
VIDEO_INFO_API = "https://vdn.apps.cntv.cn/api/getHttpVideoInfo.do"
PAGE_REFERER = "https://tv.cctv.com/"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Episode page shape: /2012/12/10/VIDA1360523007111240.shtml
EPISODE_PATH_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/VID[A-Za-z0-9]+\.shtml")
_EPISODE_LINK_RE = re.compile(
    r"(?:https?://tv\.cctv\.com)?(/\d{4}/\d{2}/\d{2}/(VID[A-Za-z0-9]+)\.shtml)"
)
_GUID_RE = re.compile(r"\b[0-9a-f]{32}\b")
_TITLE_RE = re.compile(r"<title>([^<]*)</title>")

COLUMN_MAX_RESULTS = 10
_EPISODE_RESOLVE_WORKERS = 6
_LETTER_WORKERS = 8
SERIES_MIN_LINKS = 2


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


def page_text(page_url: str, *, timeout: float) -> str:
    """Fetch one tv.cctv.com page as text (follows redirects)."""

    request = Request(
        page_url,
        headers={"User-Agent": UA, "Referer": PAGE_REFERER},
    )
    with urlopen_with_fallback(request, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def page_guid(html: str) -> str:
    """First 32-hex token in the page is the video guid used by cctv-dl."""

    match = _GUID_RE.search(html)
    return match.group(0) if match else ""


def page_title(html: str) -> str:
    match = _TITLE_RE.search(html)
    return _clean(match.group(1)) if match else ""


def episode_links(html: str, page_url: str) -> list[str]:
    """Absolute episode URLs embedded in a page, deduped, excluding the page itself."""

    try:
        own_path = urlsplit(page_url).path
    except ValueError:
        own_path = ""
    links: list[str] = []
    seen: set[str] = set()
    for match in _EPISODE_LINK_RE.finditer(html):
        path, vid = match.group(1), match.group(2)
        if path == own_path or vid in seen:
            continue
        seen.add(vid)
        links.append(f"https://tv.cctv.com{path}")
    return links


def series_episode_links(series_url: str, *, timeout: float) -> list[str] | None:
    """Return the episode list when the URL is a documentary series page.

    A page embedding at least ``_SERIES_MIN_LINKS`` other episodes is treated
    as a series container; single-episode pages return ``None``. The decision
    is based on the real page content, never on URL guessing.
    """

    try:
        html = page_text(series_url, timeout=timeout)
    except Exception as exc:
        raise DomainError(
            "PARTIAL_FAILURE",
            f"央视网页面获取失败，无法判断单集/系列：{type(exc).__name__}: {exc}",
            retryable=True,
        ) from exc
    links = episode_links(html, series_url)
    return links if len(links) >= SERIES_MIN_LINKS else None


def resolve_episode(page_url: str, *, timeout: float) -> dict[str, Any] | None:
    """Resolve one episode page to its guid/title facts (None if unusable)."""

    try:
        html = page_text(page_url, timeout=timeout)
    except Exception:
        return None
    guid = page_guid(html)
    if not guid:
        return None
    return {"guid": guid, "title": page_title(html) or guid, "page_url": page_url}


def video_info(guid: str, *, timeout: float) -> dict[str, Any] | None:
    """Query the public detail API for status/copyright/stream facts."""

    params = urlencode({"pid": guid})
    request = Request(
        f"{VIDEO_INFO_API}?{params}",
        headers={"User-Agent": UA, "Referer": PAGE_REFERER},
    )
    try:
        with urlopen_with_fallback(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    manifest = data.get("manifest") or {}

    def norm(value: Any) -> str:
        return str(value or "").strip()

    return {
        "guid": guid,
        "title": _clean(data.get("title")),
        "status": norm(data.get("status")),
        "is_protected": norm(data.get("is_protected")),
        "is_invalid_copyright": norm(data.get("is_invalid_copyright")),
        "hls_url": norm(data.get("hls_url")),
        "h5e_url": norm(manifest.get("hls_h5e_url")),
        "enc_url": norm(manifest.get("hls_enc_url")),
        "column": _clean(data.get("column")),
        "image_url": norm(data.get("image")),
    }


def iter_episodes(
    episode_urls: list[str],
    *,
    timeout: float,
    cancel_event: Any = None,
) -> "list[dict[str, Any]]":
    """Resolve episode pages to concrete video resources, preserving order.

    Episodes whose page cannot be resolved are still emitted with their URL
    VID token as the placeholder identity, so nothing disappears silently.
    """

    resolved: list[dict[str, Any] | None] = [None] * len(episode_urls)
    with ThreadPoolExecutor(max_workers=_EPISODE_RESOLVE_WORKERS) as pool:
        futures = {
            pool.submit(resolve_episode, url, timeout=timeout): index
            for index, url in enumerate(episode_urls)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                resolved[index] = future.result()
            except Exception:
                resolved[index] = None

    resources: list[dict[str, Any]] = []
    for index, item in enumerate(resolved):
        if cancel_event is not None and cancel_event.is_set():
            break
        if item is not None:
            resources.append(
                make_resource(
                    platform="cctv",
                    title=item["title"],
                    source_url=item["page_url"],
                    resource_type="视频",
                    platform_signals={"guid": item["guid"]},
                )
            )
            continue
        vid = _EPISODE_LINK_RE.search(episode_urls[index])
        vid_token = vid.group(2) if vid else ""
        resources.append(
            make_resource(
                platform="cctv",
                title=f"CCTV 视频 {vid_token}".strip(),
                source_url=episode_urls[index],
                resource_type="视频",
                platform_signals=({"vid": vid_token} if vid_token else {}),
            )
        )
    return resources


def _jsonp_json(text: str) -> dict[str, Any]:
    """Strip a JSONP callback shell and parse the JSON object inside."""

    text = text.strip().rstrip(";")
    match = re.match(r"^[A-Za-z_$]*\((.*)\)$", text, re.S)
    if match:
        text = match.group(1).strip()
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _normalize_column(item: dict[str, Any]) -> dict[str, Any]:
    def first(*keys: str) -> Any:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return value
        return ""

    website = str(first("column_website", "website", "url", "column_url") or "").strip()
    if website and not website.startswith(("http://", "https://")):
        website = urljoin("https://tv.cctv.com/", website)
    return {
        "column_id": str(first("column_id", "id", "columnId") or "").strip(),
        "title": _clean(first("column_name", "name", "title")),
        "channel": _clean(first("channel_name", "channel")),
        "column_url": website,
        "description": _clean(first("column_desc", "description", "brief")),
    }


def _column_directory_keyword(keyword: str, *, timeout: float) -> list[dict[str, Any]]:
    """Scan the A-Z column directory in parallel and filter locally by keyword.

    The directory API has no keyword parameter, so a keyword search must pull
    the full listing; letters that fail are skipped, but all letters failing
    raises so the caller can report a real partial failure.
    """

    def fetch_letter(letter: str) -> list[dict[str, Any]]:
        params = urlencode(
            {
                "fl": letter,
                "fc": "",
                "cid": "",
                "p": "1",
                "n": "100",
                "serviceId": "tvcctv",
                "t": "json",
                "cb": "x",
            }
        )
        request = Request(
            f"{COLUMN_SEARCH_API}?{params}",
            headers={"User-Agent": UA, "Referer": COLUMN_SEARCH_REFERER},
        )
        with urlopen_with_fallback(request, timeout=timeout) as resp:
            data = _jsonp_json(resp.read().decode("utf-8", "replace"))
        docs = ((data.get("response") or {}).get("docs")) or []
        return [
            _normalize_column(doc)
            for doc in docs
            if isinstance(doc, dict)
        ]

    results: dict[int, list[dict[str, Any]] | None] = {}
    letters = string.ascii_uppercase
    with ThreadPoolExecutor(max_workers=_LETTER_WORKERS) as pool:
        futures = {
            pool.submit(fetch_letter, letter): index
            for index, letter in enumerate(letters)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception:
                results[index] = None

    if all(value is None for value in results.values()):
        raise RuntimeError("column directory unreachable for all letters")

    columns: list[dict[str, Any]] = []
    for index in range(len(letters)):
        for column in results[index] or []:
            if keyword in column["title"] or keyword in column["channel"]:
                columns.append(column)
    return columns


class CctvSearchAdapter:
    platform_id = "cctv"
    descriptor = descriptor_for_platform(platform_id)

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.timeout = float(settings.search_timeout_seconds)

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        resources, video_error = self._search_videos(query, limit)
        columns, column_error = self._search_columns(query, limit)
        resources.extend(columns)
        return resources, video_error or column_error

    def _search_videos(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        params = urlencode({
            "page": "1",
            "qtext": query,
            "sort": "relevance",
            "pageSize": str(min(limit, 20)),
            "type": "video",
            "datepid": "1",
            "channel": "",
            "vtime": "-1",
        })
        url = f"{SEARCH_API}?{params}"
        request = Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*",
            "Referer": f"{SEARCH_PAGE}?{urlencode({'type': 'video', 'qtext': query})}",
        })
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            return [], adapter_error("PARTIAL_FAILURE", f"央视网搜索失败：{type(exc).__name__}: {exc}", True)

        items = data.get("list") or []
        resources: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "").strip()
            title = _clean(item.get("all_title") or item.get("title"))
            source_url = _clean(item.get("urllink"))
            if not video_id or not title or not source_url:
                continue
            if not source_url.startswith("http"):
                source_url = urljoin("https://tv.cctv.com", source_url)
            desc_parts = []
            channel = _clean(item.get("channel"))
            if channel:
                desc_parts.append(f"频道: {channel}")
            pub_time = _clean(item.get("uploadtime"))
            if pub_time:
                desc_parts.append(f"发布: {pub_time}")
            resources.append(make_resource(
                platform="cctv",
                title=title,
                source_url=source_url,
                resource_type="视频",
                summary="；".join(desc_parts) or None,
                author=channel or None,
                platform_signals={
                    "duration": item.get("durations"),
                    "publish_time": pub_time or None,
                    "thumbnail": _clean(item.get("imglink")) or None,
                },
            ))
            if len(resources) >= limit:
                break
        return resources, None

    def _search_columns(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            columns = _column_directory_keyword(query, timeout=self.timeout)
        except Exception as exc:
            return [], adapter_error(
                "PARTIAL_FAILURE",
                f"央视网栏目搜索失败：{type(exc).__name__}: {exc}",
                True,
            )

        resources: list[dict[str, Any]] = []
        for column in columns[: max(1, min(limit, COLUMN_MAX_RESULTS))]:
            if not column["title"] or not column["column_url"].startswith("http"):
                continue
            signals = {"column_id": column["column_id"]} if column["column_id"] else {}
            resources.append(make_resource(
                platform="cctv",
                title=column["title"],
                source_url=column["column_url"],
                resource_type="column",
                summary=column["description"] or None,
                author=column["channel"] or None,
                platform_signals=signals or None,
            ))
        return resources, None

    def iter_column(
        self, column_url: str, *, cancel_event: Any = None
    ) -> list[dict[str, Any]]:
        """List all episodes of a column via the cctv-dl binary."""

        from .cctv_download import run_cctv_dl_list

        events = run_cctv_dl_list(column_url, cancel_event=cancel_event)
        resources: list[dict[str, Any]] = []
        for event in events:
            guid = str(event.get("guid") or event.get("id") or "").strip()
            title = _clean(event.get("title") or event.get("videoTitle"))
            source_url = str(event.get("url") or event.get("page_url") or "").strip()
            if not guid or not title:
                continue
            if not source_url.startswith("http"):
                source_url = ""
            resources.append(make_resource(
                platform="cctv",
                title=title,
                source_url=source_url or f"https://tv.cctv.com/v/{guid}",
                resource_type="视频",
                summary=_clean(event.get("brief") or event.get("description")) or None,
                platform_signals={
                    "guid": guid,
                    "duration": str(event.get("length") or event.get("duration_sec") or "") or None,
                    "publish_time": str(event.get("time") or event.get("pgmtime") or "") or None,
                },
            ))
        return resources


__all__ = [
    "COLUMN_INDEX_URL",
    "CctvSearchAdapter",
    "EPISODE_PATH_RE",
    "SERIES_MIN_LINKS",
    "episode_links",
    "iter_episodes",
    "page_guid",
    "page_text",
    "page_title",
    "resolve_episode",
    "series_episode_links",
    "video_info",
]
