"""SmartEdu course-detail access used by structural expansion.

This module owns the one network read needed to turn a known course URL into
current platform facts. It deliberately does not own file materialization.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

from ..errors import DomainError
from .http_client import urlopen_with_fallback
from .smartedu_resource import _COURSE_TYPES, _detail_api_url, _resolve_content


_DETAIL_HOSTS = frozenset(
    {
        "s-file-1.ykt.cbern.com.cn",
        "s-file-2.ykt.cbern.com.cn",
        "s-file-3.ykt.cbern.com.cn",
    }
)
_DETAIL_MAX_BYTES = 4 * 1024 * 1024
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _token_from_adapter(adapter: Any) -> str:
    session_store = getattr(adapter, "session_store", None)
    if session_store is None:
        return ""
    session_data = session_store.get_session_data("smartedu") or {}
    tokens = session_data.get("tokens") or {}
    raw = str(tokens.get("accessToken") or "")
    return raw[7:].strip() if raw.casefold().startswith("bearer ") else raw


def _headers(token: str) -> dict[str, str]:
    value = token or "0"
    return {
        "User-Agent": _UA,
        "Origin": "https://basic.smartedu.cn",
        "Referer": "https://basic.smartedu.cn/",
        "x-nd-auth": f'MAC id="{value}",nonce="0",mac="0"',
    }


def _status_error(code: int) -> DomainError:
    if code in {401, 403}:
        return DomainError("AUTH_REQUIRED", "读取课程详情需要认证", retryable=False)
    if code in {404, 410}:
        return DomainError("RESOURCE_NOT_FOUND", "SmartEdu 课程当前不可用", retryable=False)
    if code in {408, 429}:
        return DomainError("RATE_LIMITED", "SmartEdu 暂时不可用", retryable=True)
    if code >= 500:
        return DomainError("PLATFORM_UNAVAILABLE", "SmartEdu 暂时不可用", retryable=True)
    return DomainError("PARTIAL_FAILURE", f"SmartEdu 课程详情返回 HTTP {code}", retryable=False)


def read_course_detail(
    adapter: Any,
    source_url: str,
) -> tuple[str, str, dict[str, Any]]:
    """Read current detail JSON for one known SmartEdu course."""

    content_id, content_type = _resolve_content(source_url)
    if content_type not in _COURSE_TYPES:
        raise DomainError("FEATURE_NOT_SUPPORTED", "SmartEdu 当前资源不是可展开课程")
    detail_url = _detail_api_url(content_id, content_type, source_url)
    if (urlsplit(detail_url).hostname or "").casefold() not in _DETAIL_HOSTS:
        raise DomainError("NETWORK_BLOCKED", "SmartEdu 课程详情地址不在允许域名内")

    request = Request(detail_url, headers=_headers(_token_from_adapter(adapter)))
    try:
        with urlopen_with_fallback(
            request,
            timeout=float(getattr(adapter, "timeout", 30.0)),
        ) as response:
            payload = response.read(_DETAIL_MAX_BYTES + 1)
    except HTTPError as exc:
        raise _status_error(int(exc.code)) from exc
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "PARTIAL_FAILURE",
            "SmartEdu 课程文件详情读取失败",
            retryable=True,
        ) from exc

    if len(payload) > _DETAIL_MAX_BYTES:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "SmartEdu 课程详情响应超过解析上限",
            retryable=False,
        )
    try:
        detail = json.loads(payload.decode("utf-8", "replace"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "SmartEdu 课程详情格式无效",
            retryable=False,
        ) from exc
    if not isinstance(detail, dict):
        raise DomainError(
            "CONTENT_VALIDATION_FAILED",
            "SmartEdu 课程详情格式无效",
            retryable=False,
        )
    return content_id, content_type, detail


__all__ = ["read_course_detail"]
