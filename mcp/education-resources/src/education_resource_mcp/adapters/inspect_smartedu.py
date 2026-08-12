"""SmartEdu inspection backed by current platform detail facts."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request

from ..errors import DomainError
from ..inspection import INSPECTOR_VERSION, InspectionResult, build_representation_authority
from ..policy import NetworkPolicy, PolicyViolation
from .inspect_bilibili import _PlatformWebInspector
from .smartedu_download import (
    _ACTIVE_PRIMARY_FORMATS,
    _SMARTEDU_DETAIL_HOSTS,
    _SmartEduHttpClient,
    _close_response,
    _detail_api_url,
    _find_files,
    _primary_candidate,
    _raise_for_http_status,
    _resolve_content,
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
        elif resource_format in {"mp3", "m4a"}:
            kind = "audio"
            container = resource_format
        elif resource_format == "pdf":
            kind = "document"
            container = resource_format
        else:
            return None
        return kind, container, _MIME_TYPES.get(resource_format)

    def _primary_representation(
        self,
        resource: Mapping[str, Any],
        payload: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        shape = self._representation_shape(candidate)
        if shape is None:
            return None
        kind, container, mime_type = shape
        representation: dict[str, Any] = {
            "representation_id": _smartedu_representation_id(resource, candidate),
            "kind": kind,
            "container": container,
            "scope": "primary_resource",
            "role": "primary",
            "technical_availability": "available",
            "materializable": True,
        }
        if mime_type:
            representation["mime_type"] = mime_type
        size = candidate.get("size")
        if isinstance(size, int) and not isinstance(size, bool) and size > 0:
            representation["size_bytes"] = size
        inspected_at = payload.get("inspection", {}).get("inspected_at")
        representation.update(
            build_representation_authority(
                resource,
                scope="primary_resource",
                role="primary",
                technical_availability="available",
                source="provider",
                observed_at=inspected_at if isinstance(inspected_at, str) else None,
            )
        )
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
            primary = _primary_candidate(
                _find_files(detail),
                content_type,
                supported_formats=_ACTIVE_PRIMARY_FORMATS,
            )
            representation = (
                self._primary_representation(resource, payload, primary)
                if primary is not None
                else None
            )
            if representation is None:
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
                representations.insert(0, representation)
                resolved["availability"] = {"status": "available"}
                resolved["resource_type"] = {
                    "document": "document",
                    "video": "course" if content_type in {"national_lesson", "quality_course", "thematic_course"} else "video",
                    "audio": "audio",
                }[representation["kind"]]

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
