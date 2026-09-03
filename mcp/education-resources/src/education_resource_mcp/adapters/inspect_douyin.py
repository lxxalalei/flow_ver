"""Douyin inspection backed by current platform detail facts.

Calls the a_bogus-signed detail API (the same endpoint the downloader uses)
to verify that a concrete muxed MP4 stream is obtainable for the aweme, then
emits a ``primary_resource / video / mp4`` representation with
``materializable=True``.  The Douyin landing page is JS-rendered, so — unlike
the generic web inspectors — this inspector does **not** fetch the HTML page;
it goes straight to the detail API.
"""

from __future__ import annotations

import re

from collections.abc import Callable, Mapping
import hashlib
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from ..errors import DomainError
from ..inspection import (
    INSPECTOR_VERSION,
    InspectionResult,
    build_default_inspection,
)
from .douyin import (
    USER_AGENT,
    _AdapterError,
    _AWEME_ID_RE,
    _COMMON_PARAMS,
    sign_a_bogus,
)
from .http_client import urlopen_with_fallback

DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

_CONTAINER_URL_RE = re.compile(r"/(?:user|collection|mix)/", re.IGNORECASE)


def _representation_id(resource: Mapping[str, Any], aweme_id: str) -> str:
    """Stable internal ID for the Douyin primary representation."""

    seed = f"douyin-detail|{aweme_id}|video|primary"
    return "repr_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


class DouyinInspector:
    """Inspect a Douyin video via the current detail API record."""

    platform_id = "douyin"
    inspector_id = "douyin"
    version = INSPECTOR_VERSION
    supported_scopes = ("primary_resource", "representation", "metadata")
    host_suffixes = ("douyin.com",)
    # Wait before retrying a risk-blocked detail call; class attribute so
    # tests can shrink it.
    _RISK_RETRY_SECONDS = 3.0

    def __init__(
        self,
        *args: Any,
        session_store: Any | None = None,
        detail_transport: Callable[..., Any] | None = None,
        sign_func: Callable[[str, str], str] | None = None,
        **kwargs: Any,
    ) -> None:
        del args, kwargs  # accept-and-ignore for signature compatibility
        self.session_store = session_store
        self._detail_transport = detail_transport
        self._sign_func = sign_func or sign_a_bogus

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        source_url = str(resource.get("source_url") or "")
        inspected_at: str | None = None

        # Containers (creator / collection) are expand targets, not leaf
        # resources with a detail record; video inspection does not apply.
        # Mirror the Ximalaya album precedent: no fabricated failure, the
        # container simply stays unresolved until it is expanded.
        resource_type = str(resource.get("resource_type") or "").strip().lower()
        if resource_type in {"creator", "collection"} or _CONTAINER_URL_RE.search(
            source_url
        ):
            return self._container_result(resource)

        # Host gate
        host_error = self._validate_host(source_url)
        if host_error is not None:
            return host_error

        # Extract aweme_id
        match = _AWEME_ID_RE.search(source_url)
        if not match:
            return self._failure_result(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "无法从候选地址解析抖音视频 ID",
                False,
            )
        aweme_id = match.group(1)

        # Session gate
        cookie = self._cookie()
        if cookie is None:
            return self._failure_result(
                resource,
                "AUTH_REQUIRED",
                "未保存抖音登录态，请先登录",
                False,
            )

        # Detail API
        detail, failure = self._fetch_detail(aweme_id, cookie)
        if failure is not None:
            return failure

        aweme_detail = detail.get("aweme_detail") or {}
        video_url = self._extract_video_url(aweme_detail)
        if not video_url:
            return self._failure_result(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "抖音详情未返回可用视频地址",
                False,
            )

        # Build concrete primary representation
        from datetime import datetime, timezone

        inspected_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        representation: dict[str, Any] = {
            "representation_id": _representation_id(resource, aweme_id),
            "kind": "video",
            "container": "mp4",
            "mime_type": "video/mp4",
            "scope": "primary_resource",
            "role": "primary",
            "technical_availability": "available",
            "materializable": True,
        }

        return self._success_result(resource, representation, aweme_detail, inspected_at)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _validate_host(self, source_url: str) -> InspectionResult | None:
        if not source_url:
            return None  # handled by caller (no aweme_id)
        try:
            parsed = urlsplit(source_url)
        except ValueError:
            return None
        host = parsed.hostname
        if not host or parsed.scheme.casefold() not in {"http", "https"}:
            return None
        normalized = host.casefold().rstrip(".")
        if not any(
            normalized == suffix or normalized.endswith("." + suffix)
            for suffix in self.host_suffixes
        ):
            return None
        return None

    def _cookie(self) -> str | None:
        if self.session_store is None:
            return None
        from ..sessions import SessionStore

        session_data = self.session_store.get_session_data("douyin")
        if not session_data:
            return None
        return SessionStore._cookie_header(session_data)

    def _fetch_detail(
        self, aweme_id: str, cookie: str
    ) -> tuple[dict[str, Any] | None, InspectionResult | None]:
        """Call the signed detail API and return parsed JSON or a failure.

        Retryable risk-control blocks (rate limiting) are retried once after
        a short wait — the same block often passes seconds later.
        """
        for attempt in range(2):
            detail, failure = self._fetch_detail_once(aweme_id, cookie)
            if detail is not None or failure is None:
                return detail, failure
            retriable = bool(failure.failures) and all(
                item.get("retriable") for item in failure.failures if isinstance(item, dict)
            )
            if not retriable:
                return detail, failure
            if attempt == 0:
                time.sleep(self._RISK_RETRY_SECONDS)
        return detail, failure

    def _fetch_detail_once(
        self, aweme_id: str, cookie: str
    ) -> tuple[dict[str, Any] | None, InspectionResult | None]:
        params = {**_COMMON_PARAMS, "aweme_id": aweme_id}
        query_string = urlencode(params)
        try:
            params["a_bogus"] = self._sign_func(query_string, USER_AGENT)
        except _AdapterError as exc:
            return None, self._failure_result_raw(
                exc.code, exc.message, exc.retryable
            )

        url = f"{DETAIL_URL}?{urlencode(params)}"
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }
        if cookie:
            headers["Cookie"] = cookie
        request = Request(url, headers=headers)

        try:
            if self._detail_transport is not None:
                response = self._detail_transport(request)
            else:
                response = urlopen_with_fallback(request, timeout=20)
        except HTTPError as exc:
            # A valid session can still be risk-blocked; only 401 means the
            # login state itself is unusable.
            if exc.code == 401:
                code, retryable = "AUTH_REQUIRED", False
            elif exc.code == 403:
                code, retryable = "NETWORK_BLOCKED", True
            else:
                code, retryable = "DOWNLOAD_FAILED", exc.code >= 500
            message = (
                "抖音详情被风控拦截（HTTP 403）"
                if exc.code == 403
                else f"抖音详情 API HTTP {exc.code}"
            )
            return None, self._failure_result_raw(code, message, retryable)
        except (TimeoutError, URLError) as exc:
            return None, self._failure_result_raw(
                "DOWNLOAD_FAILED",
                f"抖音详情请求失败: {type(exc).__name__}",
                True,
            )

        try:
            body = response.read()
            if isinstance(body, bytes):
                body = body.decode("utf-8", "replace")
            if not body or body == "blocked":
                return None, self._failure_result_raw(
                    "DOWNLOAD_FAILED", "抖音详情被拦截", True
                )
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                return None, self._failure_result_raw(
                    "DOWNLOAD_FAILED", "抖音详情响应不是有效 JSON", False
                )
            return parsed, None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _extract_video_url(aweme_detail: Mapping[str, Any]) -> str:
        """Return the best muxed MP4 URL from the detail record."""

        video = aweme_detail.get("video") or {}
        for key in ("play_addr_h264", "play_addr_256", "play_addr"):
            urls = (video.get(key) or {}).get("url_list") or []
            if urls:
                return str(urls[-1])
        return ""

    # ------------------------------------------------------------------
    # result builders
    # ------------------------------------------------------------------

    def _container_result(
        self, resource: Mapping[str, Any]
    ) -> InspectionResult:
        """Neutral result for creator/collection URLs: no video detail applies."""

        return InspectionResult(
            resolution_status="unresolved",
            resolved_resource={
                "title": str(resource.get("title") or "抖音容器资源"),
                "resource_type": str(
                    resource.get("resource_type") or "collection"
                ),
                "availability": {"status": "unknown"},
                "representations": [],
                "metadata": {},
            },
            inspection={
                **build_default_inspection(
                    self.inspector_id, method="container_not_inspectable"
                ),
                "platform": self.platform_id,
            },
            failures=(),
        )

    def _failure_result(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        retriable: bool,
    ) -> InspectionResult:
        return self._failure_result_raw(code, message, retriable, resource=resource)

    def _failure_result_raw(
        self,
        code: str,
        message: str,
        retriable: bool,
        *,
        resource: Mapping[str, Any] | None = None,
    ) -> InspectionResult:
        from datetime import datetime, timezone

        inspected_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        safe_resource = resource if isinstance(resource, Mapping) else {}
        availability = (
            "auth_required"
            if code == "AUTH_REQUIRED"
            else "unavailable"
            if code == "RESOURCE_NOT_FOUND"
            else "unknown"
        )
        return InspectionResult(
            resolution_status="partial",
            resolved_resource={
                "title": str(safe_resource.get("title") or "抖音视频"),
                "resource_type": "video",
                "availability": {"status": availability},
                "representations": [],
                "metadata": {},
            },
            inspection={
                "inspector_id": self.inspector_id,
                "version": self.version,
                "method": "platform_detail_api",
                "cache_status": "miss",
                "inspected_at": inspected_at,
                "warnings": [],
            },
            failures=[
                {
                    "code": code,
                    "message": message,
                    "retriable": retriable,
                    "platform": self.platform_id,
                }
            ],
        )

    def _success_result(
        self,
        resource: Mapping[str, Any],
        representation: dict[str, Any],
        aweme_detail: Mapping[str, Any],
        inspected_at: str,
    ) -> InspectionResult:
        import re as _re

        title = str(aweme_detail.get("desc") or resource.get("title") or "")
        title = _re.sub(r"\s+", " ", title).strip()
        author = (aweme_detail.get("author") or {}).get("nickname") or ""

        resolved: dict[str, Any] = {
            "title": title[:200] if title else str(resource.get("title") or "抖音视频"),
            "resource_type": "video",
            "availability": {"status": "available"},
            "representations": [representation],
            "metadata": {},
        }
        if author:
            resolved["creator"] = author
        metadata: dict[str, Any] = {}
        aweme_id = str(aweme_detail.get("aweme_id") or "")
        if aweme_id:
            metadata["aweme_id"] = aweme_id
        # Expose the platform-native creator handle for creator expansion.
        sec_uid = str((aweme_detail.get("author") or {}).get("sec_uid") or "").strip()
        if sec_uid:
            metadata["creator_sec_uid"] = sec_uid
        stats = aweme_detail.get("statistics") or {}
        for key, raw in (
            ("play_count", stats.get("play_count")),
            ("digg_count", stats.get("digg_count")),
            ("comment_count", stats.get("comment_count")),
        ):
            if isinstance(raw, int) and raw >= 0:
                metadata[key] = raw
        if metadata:
            resolved["metadata"] = metadata

        return InspectionResult(
            resolution_status="resolved",
            resolved_resource=resolved,
            inspection={
                "inspector_id": self.inspector_id,
                "version": self.version,
                "method": "platform_detail_api",
                "cache_status": "miss",
                "inspected_at": inspected_at,
                "warnings": [],
            },
            failures=[],
        )


DouyinResourceInspector = DouyinInspector
DouyinPlatformInspector = DouyinInspector


__all__ = [
    "DETAIL_URL",
    "DouyinInspector",
    "DouyinPlatformInspector",
    "DouyinResourceInspector",
]
