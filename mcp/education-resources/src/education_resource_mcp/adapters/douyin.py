"""Douyin video search and creator adapter.

Uses Douyin's web APIs with hardcoded device parameters.  Auth is cookie-
based — the adapter pulls stored cookies from ``SessionStore`` at search
time.

Capabilities:
  - **search**: keyword search via /general/search/ (no signature needed)
  - **search_creator**: browse a creator's full video list via /aweme/post/
    (requires a_bogus signature, computed via Node.js)

msToken is not required (verified by A/B testing).  The search endpoint
does not require a_bogus; the creator/post endpoint does.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from ..config import Settings
from ..sessions import SessionStore
from .base import adapter_error, make_resource
from .http_client import urlopen_with_fallback


SEARCH_URL = "https://www.douyin.com/aweme/v1/web/general/search/single/"
POST_URL = "https://www.douyin.com/aweme/v1/web/aweme/post/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_SIGN_JS = Path(__file__).parent / "douyin_sign.js"
_AWEME_ID_RE = re.compile(r"/video/(\d+)")
_USER_ID_RE = re.compile(r"/user/([^/?]+)")

# Hardcoded device/environment parameters — Douyin does not validate these
# against the real browser environment (verified: searches succeed from a
# Windows host claiming to be MacIntel / Mac OS).
_COMMON_PARAMS: dict[str, str] = {
    "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
    "version_code": "190600", "version_name": "19.6.0",
    "update_version_code": "170400", "pc_client_type": "1",
    "cookie_enabled": "true", "browser_language": "zh-CN",
    "browser_platform": "MacIntel", "browser_name": "Chrome",
    "browser_version": "125.0.0.0", "browser_online": "true",
    "engine_name": "Blink", "os_name": "Mac OS", "os_version": "10.15.7",
    "cpu_core_num": "8", "device_memory": "8", "engine_version": "109.0",
    "platform": "PC", "screen_width": "2560", "screen_height": "1440",
    "effective_type": "4g", "round_trip_time": "50",
}


class _AdapterError(Exception):
    """Internal error carrying a stable code + retryable flag."""

    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def _strip_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _to_int(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_sec_user_id(creator_id: str) -> str:
    """Accept a full creator URL or a bare sec_user_id."""
    match = _USER_ID_RE.search(creator_id)
    return match.group(1) if match else creator_id


def sign_a_bogus(query_string: str, user_agent: str) -> str:
    """Compute a_bogus by executing douyin_sign.js through Node.js.

    Shared by the search-creator and download adapters — both need to sign
    non-search API calls (detail, post list).
    """
    js_path = json.dumps(str(_SIGN_JS))
    qs_arg = json.dumps(query_string)
    ua_arg = json.dumps(user_agent)
    script = (
        "const fs=require('fs'),vm=require('vm');"
        f"const c=fs.readFileSync({js_path},'utf8');"
        "const ctx=vm.createContext();"
        "vm.runInContext(c,ctx);"
        f"process.stdout.write(ctx.sign_datail({qs_arg},{ua_arg}));"
    )
    try:
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        raise _AdapterError("SIGN_FAILED", "系统未安装 Node.js，无法计算抖音签名", False)
    except subprocess.TimeoutExpired:
        raise _AdapterError("SIGN_FAILED", "抖音签名计算超时", True)
    if result.returncode != 0 or not result.stdout:
        raise _AdapterError("SIGN_FAILED", f"a_bogus 签名失败: {result.stderr[:200]}", False)
    return result.stdout.strip()


class DouyinSearchAdapter:
    """Search Douyin videos and browse creator homepages (cookie-based)."""

    platform_id = "douyin"

    def __init__(self, session_store: SessionStore, settings: Settings) -> None:
        self.session_store = session_store
        self.timeout = float(settings.search_timeout_seconds)

    # -- internal helpers ------------------------------------------------

    def _request_json(self, url: str, cookie: str) -> dict[str, Any]:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }
        if cookie:
            headers["Cookie"] = cookie
        request = Request(url, headers=headers)
        try:
            with urlopen_with_fallback(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise _AdapterError("AUTH_REQUIRED", f"抖音返回 HTTP {exc.code}", False)
            raise _AdapterError(
                "PARTIAL_FAILURE", f"抖音返回 HTTP {exc.code}", exc.code >= 500
            )
        except (TimeoutError, URLError) as exc:
            raise _AdapterError(
                "PARTIAL_FAILURE", f"抖音请求失败: {type(exc).__name__}", True
            )

        if not body or body == "blocked":
            raise _AdapterError("NETWORK_BLOCKED", "抖音被拦截（response 为空或 blocked）", True)
        if "json" not in content_type.lower():
            raise _AdapterError("NETWORK_BLOCKED", "抖音返回非 JSON 响应（可能触发风控）", True)
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            raise _AdapterError("PARTIAL_FAILURE", "抖音响应不是有效 JSON", False)
        if not isinstance(value, dict):
            raise _AdapterError("PARTIAL_FAILURE", "抖音响应根节点不是 object", False)
        return value

    @staticmethod
    def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
        aweme = item.get("aweme_info") or item
        aweme_id = str(aweme.get("aweme_id") or "").strip()
        title = _strip_text(aweme.get("desc") or aweme.get("preview_title"))
        if not aweme_id or not title:
            return None

        signals: dict[str, Any] = {}
        stats = aweme.get("statistics") or {}
        for key, raw in (
            ("likes", stats.get("digg_count")),
            ("comments", stats.get("comment_count")),
            ("shares", stats.get("share_count")),
            ("plays", stats.get("play_count")),
            ("collects", stats.get("collect_count")),
        ):
            val = _to_int(raw)
            if val is not None:
                signals[key] = val

        author = (aweme.get("author") or {}).get("nickname")
        create_time = _to_int(aweme.get("create_time"))
        published_at: str | None = None
        if create_time and create_time > 0:
            published_at = datetime.fromtimestamp(create_time).astimezone().isoformat()

        return make_resource(
            platform="douyin",
            title=title,
            source_url=f"https://www.douyin.com/video/{aweme_id}",
            resource_type="视频",
            summary=title[:120] if len(title) > 40 else None,
            author=author,
            published_at=published_at,
            download_feasibility="中",
            platform_signals=signals or None,
        )

    def _get_cookie(self) -> str:
        session_data = self.session_store.get_session_data("douyin")
        if not session_data:
            raise _AdapterError("AUTH_REQUIRED", "未保存抖音登录态，请先在浏览器中登录抖音", False)
        return SessionStore._cookie_header(session_data)

    # -- public API: keyword search --------------------------------------

    def search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            cookie = self._get_cookie()
        except _AdapterError as exc:
            return [], exc.to_dict()

        results: list[dict[str, Any]] = []
        offset = 0
        page_size = min(15, limit)

        try:
            while len(results) < limit:
                current_size = min(page_size, limit - len(results))
                params = {
                    **_COMMON_PARAMS,
                    "search_channel": "aweme_general",
                    "enable_history": "1",
                    "keyword": query,
                    "search_source": "tab_search",
                    "query_correct_type": "1",
                    "is_filter_search": "0",
                    "from_group_id": "7378810571505847586",
                    "offset": str(offset),
                    "count": str(current_size),
                    "need_filter_settings": "1",
                    "list_type": "multi",
                    "search_id": "",
                }
                url = f"{SEARCH_URL}?{urlencode(params)}"
                response = self._request_json(url, cookie)

                status_code = response.get("status_code")
                data = response.get("data")
                if not isinstance(data, list):
                    data = []

                if status_code not in (None, 0) and not data:
                    return [], adapter_error(
                        "PARTIAL_FAILURE",
                        f"抖音 API status_code={status_code}: "
                        f"{response.get('status_msg', '')}",
                        False,
                    )

                if not data:
                    break

                for item in data:
                    if isinstance(item, dict):
                        normalized = self._normalize_item(item)
                        if normalized:
                            results.append(normalized)
                            if len(results) >= limit:
                                break

                if not response.get("has_more"):
                    break
                offset += current_size
        except _AdapterError as exc:
            return results, exc.to_dict()

        return results, None

    # -- public API: creator homepage browse -----------------------------

    def search_creator(
        self, creator_id: str, limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Browse a creator's video list (paginated, a_bogus-signed).

        *creator_id* can be a full URL (``/user/MS4w...``) or a bare
        ``sec_user_id``.
        """
        try:
            cookie = self._get_cookie()
        except _AdapterError as exc:
            return [], exc.to_dict()

        sec_user_id = _parse_sec_user_id(creator_id)
        results: list[dict[str, Any]] = []
        max_cursor = ""

        try:
            while len(results) < limit:
                params = {
                    **_COMMON_PARAMS,
                    "sec_user_id": sec_user_id,
                    "count": "18",
                    "max_cursor": max_cursor,
                    "locate_query": "false",
                    "publish_video_strategy_type": "2",
                }
                query_string = urlencode(params)
                params["a_bogus"] = sign_a_bogus(query_string, USER_AGENT)

                url = f"{POST_URL}?{urlencode(params)}"
                response = self._request_json(url, cookie)

                aweme_list = response.get("aweme_list")
                if not isinstance(aweme_list, list) or not aweme_list:
                    break

                for item in aweme_list:
                    if isinstance(item, dict):
                        normalized = self._normalize_item(item)
                        if normalized:
                            results.append(normalized)
                            if len(results) >= limit:
                                break

                if not response.get("has_more"):
                    break
                max_cursor = str(response.get("max_cursor") or "")
        except _AdapterError as exc:
            return results, exc.to_dict()

        return results, None
