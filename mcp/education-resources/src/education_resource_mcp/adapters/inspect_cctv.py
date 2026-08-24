"""Bounded public inspection for CCTV column, series and episode pages.

Column (/lm/) and documentary series pages are containers: the inspector
returns guidance to expand first and never marks them materializable. A
single episode resolves to its 32-hex page guid plus the public detail-API
facts (status / copyright / stream presence) and a primary video/mp4
representation routed to the cctv-dl downloader.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from ..errors import DomainError
from ..inspection import (
    INSPECTOR_VERSION,
    InspectionResult,
    build_default_inspection,
)
from . import cctv

INSPECTOR_ID = "cctv"
_HOST_SUFFIXES = ("cctv.com", "cntv.cn")
_EPISODE_PATH_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/(VID[A-Za-z0-9]+)\.shtml")


def _representation_id(seed: str) -> str:
    digest = hashlib.sha256(
        f"cctv|{seed}|video|primary".encode("utf-8")
    ).hexdigest()[:32]
    return f"repr_{digest}"


class CctvInspector:
    """Inspect CCTV pages with page-guid plus detail-API facts."""

    platform_id = "cctv"
    inspector_id = INSPECTOR_ID
    version = INSPECTOR_VERSION

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout = float(timeout_seconds) if timeout_seconds else 30.0

    def inspect(self, resource: Mapping[str, Any]) -> InspectionResult:
        source_url = str(resource.get("source_url") or "").strip()
        try:
            parsed = urlsplit(source_url)
            host = (parsed.hostname or "").casefold().rstrip(".")
        except ValueError:
            host = ""
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not host
            or not any(
                host == suffix or host.endswith("." + suffix)
                for suffix in _HOST_SUFFIXES
            )
        ):
            return self._failure(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "候选不是央视网（cctv.com / cntv.cn）页面",
                False,
            )

        path = parsed.path or "/"
        kind = str(resource.get("resource_type") or "").strip().casefold()
        if kind == "column" or path.startswith("/lm/"):
            return self._container_result(resource, "column", "栏目")
        if not _EPISODE_PATH_RE.search(path) and kind not in {"视频", "video"}:
            return self._failure(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "央视网该 URL 形态当前不支持检查（仅栏目与单集/系列页）",
                False,
            )

        try:
            html = cctv.page_text(source_url, timeout=self.timeout)
        except Exception as exc:
            return self._failure(
                resource,
                "PARTIAL_FAILURE",
                f"央视网页面获取失败：{type(exc).__name__}: {exc}",
                True,
            )

        links = cctv.episode_links(html, source_url)
        if len(links) >= cctv.SERIES_MIN_LINKS:
            return self._container_result(resource, "series", "系列")

        guid = cctv.page_guid(html)
        if not guid:
            return self._failure(
                resource,
                "CONTENT_VALIDATION_FAILED",
                "无法从央视网页面解析视频 guid",
                False,
            )

        try:
            info = cctv.video_info(guid, timeout=self.timeout)
        except Exception:
            info = None

        vid_match = _EPISODE_PATH_RE.search(path)
        vid = vid_match.group(1) if vid_match else ""
        signals: dict[str, Any] = {"guid": guid}
        if vid:
            signals["vid"] = vid

        warnings: list[str] = []
        if info is None:
            warnings.append("视频详情接口不可用，仅页面事实")
            title = cctv.page_title(html) or str(
                resource.get("title") or guid
            )
        else:
            title = info.get("title") or cctv.page_title(html) or str(
                resource.get("title") or guid
            )
            for key in ("status", "is_protected", "is_invalid_copyright"):
                value = str(info.get(key) or "").strip()
                if value:
                    signals[key] = value
            if info.get("column"):
                signals["column"] = info["column"]
            has_stream = bool(
                info.get("hls_url") or info.get("h5e_url") or info.get("enc_url")
            )
            signals["stream_present"] = has_stream
            if not has_stream:
                warnings.append("详情未暴露任何可用流（hls/h5e/enc）")

        availability = (
            "unavailable"
            if info is not None and not signals.get("stream_present")
            else "available"
        )
        materializable = availability == "available"

        representation: dict[str, Any] = {
            "representation_id": _representation_id(guid),
            "kind": "video",
            "container": "mp4",
            "mime_type": "video/mp4",
            "scope": "primary_resource",
            "role": "primary",
            "technical_availability": availability,
            "materializable": materializable,
        }

        return InspectionResult(
            resolution_status="resolved",
            resolved_resource={
                "title": title[:200],
                "resource_type": "video",
                "availability": {"status": availability},
                "representations": [representation],
                "metadata": {"platform_signals": signals},
            },
            inspection=build_default_inspection(
                INSPECTOR_ID,
                method="platform_page_and_detail_api",
                warnings=warnings,
                version=self.version,
            ),
            failures=[],
        )

    def _container_result(
        self,
        resource: Mapping[str, Any],
        resource_type: str,
        label: str,
    ) -> InspectionResult:
        title = str(resource.get("title") or f"CCTV {label}").strip()
        return InspectionResult(
            resolution_status="partial",
            resolved_resource={
                "title": title[:200],
                "resource_type": resource_type,
                "availability": {"status": "unknown"},
                "representations": [],
                "metadata": {},
            },
            inspection=build_default_inspection(
                INSPECTOR_ID,
                method="page_structure",
                warnings=[f"央视网{label}是容器资源"],
                version=self.version,
            ),
            failures=[
                {
                    "code": "FEATURE_NOT_SUPPORTED",
                    "message": (
                        f"央视网{label}是容器资源：请先 resource_expand 展开为单集候选，"
                        "再由用户选择下载"
                    ),
                    "retriable": False,
                    "platform": self.platform_id,
                }
            ],
        )

    def _failure(
        self,
        resource: Mapping[str, Any],
        code: str,
        message: str,
        retriable: bool,
    ) -> InspectionResult:
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
                "title": str(safe_resource.get("title") or "央视网资源"),
                "resource_type": "video",
                "availability": {"status": availability},
                "representations": [],
                "metadata": {},
            },
            inspection=build_default_inspection(
                INSPECTOR_ID,
                method="platform_page_and_detail_api",
                version=self.version,
            ),
            failures=[
                {
                    "code": code,
                    "message": message,
                    "retriable": retriable,
                    "platform": self.platform_id,
                }
            ],
        )


__all__ = ["CctvInspector"]
