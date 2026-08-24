"""SmartEdu inspection backed by current platform detail facts."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request

from ..errors import DomainError
from ..inspection import INSPECTOR_VERSION, InspectionResult
from ..policy import NetworkPolicy, PolicyViolation
from .inspect_bilibili import _PlatformWebInspector
from .smartedu_download import (
    _ACTIVE_PRIMARY_FORMATS,
    _COURSE_TYPES,
    _SMARTEDU_DETAIL_HOSTS,
    _SmartEduHttpClient,
    _close_response,
    _detail_api_url,
    _find_files,
    _primary_candidate,
    _raise_for_http_status,
    _resolve_content,
    _role_for_candidate,
    _select_course_files,
    _smartedu_representation_id,
    _smartedu_headers,
)


_DETAIL_MAX_BYTES = 4 * 1024 * 1024
_MIME_TYPES: dict[str, str] = {
    "mp4": "video/mp4",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "pdf": "application/pdf",
}


class SmartEduInspector(_PlatformWebInspector):
    """Inspect a SmartEdu landing page and its current detail record."""

    platform_id = "smartedu"
    inspector_id = "smartedu"
    version = INSPECTOR_VERSION
    supported_scopes = (
        "primary_resource",
        "representation",
        "landing_page",
        "metadata",
    )
    host_suffixes = ("basic.smartedu.cn",)
    metadata_allowlist = (
        "content_id",
        "course_id",
        "resource_id",
        "grade",
        "subject",
        "resource_format",
        "provider",
    )

    def __init__(
        self,
        *args: Any,
        session_store: Any | None = None,
        detail_transport: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.session_store = session_store
        self.landing_policy = NetworkPolicy(
            allowed_hosts={"basic.smartedu.cn"},
            resolver=self.resolver,
            max_redirects=min(self.max_redirects, 5),
        )
        self.detail_client = _SmartEduHttpClient(
            resolver=self.resolver,
            transport=detail_transport,
            max_redirects=min(self.max_redirects, 5),
            allowed_hosts=_SMARTEDU_DETAIL_HOSTS,
        )

    def _validate_network_url(self, url: str) -> None:
        if urlsplit(url).scheme.casefold() != "https":
            raise PolicyViolation(
                "unsupported_scheme",
                "SmartEdu landing requests require HTTPS",
            )
        self.landing_policy.validate_url(url)

    def _session_token(self) -> str:
        if self.session_store is None:
            return ""
        session_data = self.session_store.get_session_data("smartedu") or {}
        tokens = session_data.get("tokens") or {}
        raw_token = str(tokens.get("accessToken") or "")
        return raw_token[7:].strip() if raw_token.casefold().startswith("bearer ") else raw_token

    def _detail_result(
        self,
        resource: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
        source_url = str(resource.get("source_url") or "")
        try:
            content_id, content_type = _resolve_content(source_url)
            detail_url = _detail_api_url(content_id, content_type, source_url)
        except Exception:
            return None, None, self._failure(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "SmartEdu 资源标识无法解析",
                False,
            )

        response: Any | None = None
        try:
            response = self.detail_client.open(
                Request(detail_url, headers=_smartedu_headers(self._session_token())),
                timeout=self.timeout,
            )
            _raise_for_http_status(response)
        except DomainError as exc:
            _close_response(response)
            code = exc.code
            return None, None, self._failure(
                resource,
                code if code in {
                    "AUTH_REQUIRED",
                    "NETWORK_BLOCKED",
                    "REDIRECT_BLOCKED",
                    "RESOURCE_NOT_FOUND",
                    "RATE_LIMITED",
                    "PLATFORM_UNAVAILABLE",
                } else "PARTIAL_FAILURE",
                {
                    "AUTH_REQUIRED": "SmartEdu 资源详情需要授权",
                    "NETWORK_BLOCKED": "SmartEdu 资源详情请求被网络策略阻止",
                    "REDIRECT_BLOCKED": "SmartEdu 资源详情重定向被阻止",
                    "RESOURCE_NOT_FOUND": "SmartEdu 资源详情当前不可用",
                    "RATE_LIMITED": "SmartEdu 资源详情暂时不可用",
                    "PLATFORM_UNAVAILABLE": "SmartEdu 资源详情暂时不可用",
                }.get(code, "SmartEdu 资源详情检查失败"),
                bool(exc.retryable),
            )
        except Exception:
            return None, None, self._failure(
                resource,
                "PARTIAL_FAILURE",
                "SmartEdu 资源详情检查失败",
                True,
            )

        try:
            try:
                body = response.read(_DETAIL_MAX_BYTES + 1)
            except TypeError:
                body = response.read()
            if not isinstance(body, (bytes, bytearray, memoryview)) or not body:
                raise ValueError("empty detail")
            if len(body) > _DETAIL_MAX_BYTES:
                raise ValueError("oversized detail")
            parsed = json.loads(bytes(body).decode("utf-8", "replace"))
            if not isinstance(parsed, dict):
                raise ValueError("invalid detail")
            return parsed, content_type, None
        except Exception:
            return None, None, self._failure(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "SmartEdu 资源详情格式无效",
                False,
            )
        finally:
            _close_response(response)

    @staticmethod
    def _representation_shape(candidate: Mapping[str, Any]) -> tuple[str, str, str | None] | None:
        resource_format = str(candidate.get("format") or "").casefold()
        if resource_format == "mp4":
            kind = "video"
            container = resource_format
        elif resource_format == "m3u8":
            # HLS 流的交付物是经 ffmpeg 无损封装的 MP4。
            kind = "video"
            container = resource_format
        elif resource_format in {"mp3", "m4a"}:
            kind = "audio"
            container = resource_format
        elif resource_format == "pdf":
            kind = "document"
            container = resource_format
        else:
            return None
        mime = "video/mp4" if resource_format == "m3u8" else _MIME_TYPES.get(resource_format)
        return kind, container, mime

    def _representation(
        self,
        resource: Mapping[str, Any],
        payload: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        role: str,
        scope: str,
    ) -> dict[str, Any] | None:
        shape = self._representation_shape(candidate)
        if shape is None:
            return None
        kind, container, mime_type = shape
        representation: dict[str, Any] = {
            "representation_id": _smartedu_representation_id(resource, candidate),
            "kind": kind,
            "container": container,
            "scope": scope,
            "role": role,
            "technical_availability": "available",
            "materializable": True,
        }
        if mime_type:
            representation["mime_type"] = mime_type
        size = candidate.get("size")
        if isinstance(size, int) and not isinstance(size, bool) and size > 0:
            representation["size_bytes"] = size
        return representation

    def _enrich_payload(
        self, resource: Mapping[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        payload = super()._enrich_payload(resource, payload)
        if not self._can_add_representation(payload):
            return payload

        detail, content_type, failure = self._detail_result(resource)
        resolved = dict(payload["resolved_resource"])
        representations = [
            dict(item) for item in resolved.get("representations", [])
            if not (item.get("kind") == "webpage" and item.get("role") == "primary")
        ]
        for item in representations:
            if item.get("kind") == "webpage":
                item["scope"] = "landing_page"
                item["role"] = "landing"

        if failure is not None:
            payload["resolution_status"] = "partial"
            resolved["availability"] = {
                "status": "auth_required"
                if failure["code"] == "AUTH_REQUIRED"
                else "unavailable"
                if failure["code"] == "RESOURCE_NOT_FOUND"
                else "unknown"
            }
            payload["failures"] = [*payload.get("failures", []), failure]
        else:
            assert detail is not None and content_type is not None
            active_files = [
                candidate
                for candidate in _find_files(detail)
                if str(candidate.get("format") or "").casefold()
                in _ACTIVE_PRIMARY_FORMATS
            ]
            selected = (
                _select_course_files(active_files)
                if content_type in _COURSE_TYPES
                else list(active_files)
            )
            primary = _primary_candidate(
                selected,
                content_type,
                supported_formats=_ACTIVE_PRIMARY_FORMATS,
            )
            if primary is None:
                payload["resolution_status"] = "partial"
                resolved["availability"] = {"status": "unknown"}
                payload["failures"] = [
                    *payload.get("failures", []),
                    self._failure(
                        resource,
                        "CONTENT_VALIDATION_FAILED",
                        "SmartEdu 资源详情未提供受支持的主文件",
                        False,
                    ),
                ]
            else:
                # 非课程资源继续只公开主文件；课程资源则公开自然交付包中的
                # 主视频/主文件 + 文档附件 + 伴随音频。一个 Resource 可以自然
                # 物化成多个文件，不要求 Agent 先猜一个扩展名。
                if content_type not in _COURSE_TYPES:
                    selected = [primary]
                primary_key = str(primary.get("item_key") or "")
                concrete: list[dict[str, Any]] = []
                for candidate in selected:
                    role = _role_for_candidate(
                        candidate,
                        primary_key=primary_key,
                        content_type=content_type,
                    )
                    scope = "primary_resource" if role == "primary" else "representation"
                    representation = self._representation(
                        resource,
                        payload,
                        candidate,
                        role=role,
                        scope=scope,
                    )
                    if representation is not None:
                        concrete.append(representation)
                if not any(item.get("role") == "primary" for item in concrete):
                    payload["resolution_status"] = "partial"
                    resolved["availability"] = {"status": "unknown"}
                    payload["failures"] = [
                        *payload.get("failures", []),
                        self._failure(
                            resource,
                            "CONTENT_VALIDATION_FAILED",
                            "SmartEdu 主文件无法形成可下载表示",
                            False,
                        ),
                    ]
                else:
                    representations = [*concrete, *representations]
                    resolved["availability"] = {"status": "available"}
                    primary_representation = next(
                        item for item in concrete if item.get("role") == "primary"
                    )
                    if content_type in _COURSE_TYPES:
                        resolved["resource_type"] = "course"
                    else:
                        resolved["resource_type"] = {
                            "document": "document",
                            "video": "video",
                            "audio": "audio",
                        }[primary_representation["kind"]]

        resolved["representations"] = representations
        payload["resolved_resource"] = resolved
        payload["inspection"]["method"] = "platform_detail_api"
        return payload


SmartEduResourceInspector = SmartEduInspector
SmartEduPlatformInspector = SmartEduInspector


__all__ = [
    "SmartEduInspector",
    "SmartEduPlatformInspector",
    "SmartEduResourceInspector",
]
