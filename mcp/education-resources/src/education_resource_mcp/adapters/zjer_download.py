"""Zjer (之江汇) video downloader.

Zjer course detail responses expose MP4 files through expiring OSS-signed URLs.
This provider therefore re-reads the stable course detail at Job start, binds
the selected ``videoId`` again, and delegates the fresh public MP4 to the
shared HTTP downloader. The signed locator never becomes durable Resource or
Representation state.
"""

from __future__ import annotations

from collections.abc import Mapping
import threading
from typing import Any, Callable

from ..config import Settings
from ..downloader import DownloadProvider, DownloadResult, PublicHttpDownloader
from ..errors import DomainError
from ..sessions import SessionStore
from .zjer import best_mp4, fetch_course_detail, find_lesson, resource_video_identity


class ZjerVideoDownloader:
    def __init__(
        self,
        session_store: SessionStore,
        settings: Settings,
        *,
        detail_fetcher: Callable[..., dict[str, Any]] = fetch_course_detail,
        direct_downloader: DownloadProvider | None = None,
    ) -> None:
        self.settings = settings
        self.timeout = float(settings.download_timeout_seconds)
        self.detail_fetcher = detail_fetcher
        self.direct_downloader = direct_downloader or PublicHttpDownloader(settings)

    def download(
        self,
        resource: Mapping[str, Any],
        job_id: str,
        strategy: str,
        cancel_event: threading.Event,
    ) -> DownloadResult:
        if strategy != "direct":
            raise DomainError("INVALID_ARGUMENT", "之江汇视频只支持 direct 获取")
        if cancel_event.is_set():
            raise DomainError("JOB_CANCELLED", "下载已取消")
        identity = resource_video_identity(resource)
        if identity is None:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "之江汇视频缺少稳定 courseCateId、courseInfoId 或 videoId",
                retryable=False,
            )
        course_cate_id, course_info_id, video_id = identity
        try:
            data = self.detail_fetcher(course_cate_id, timeout=self.timeout)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "PLATFORM_UNAVAILABLE",
                "之江汇课程详情刷新失败",
                retryable=True,
            ) from exc
        lesson = find_lesson(
            data,
            video_id=video_id,
            course_info_id=course_info_id,
        )
        if lesson is None:
            raise DomainError("RESOURCE_NOT_FOUND", "之江汇课时已经不存在", retryable=False)
        media = best_mp4(lesson)
        if media is None:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "之江汇课时当前未提供可获取的 MP4",
                retryable=False,
            )
        fresh_url = media.get("_fresh_url")
        if not isinstance(fresh_url, str) or not fresh_url:
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "之江汇没有返回有效的 MP4 获取地址",
                retryable=False,
            )
        download_resource = dict(resource)
        download_resource["source_url"] = fresh_url
        result = self.direct_downloader.download(
            download_resource,
            job_id,
            "direct",
            cancel_event,
        )
        if not isinstance(result, DownloadResult):
            raise DomainError(
                "CONTENT_VALIDATION_FAILED",
                "之江汇视频获取没有产生单一 MP4 文件",
                retryable=False,
            )
        return result


__all__ = ["ZjerVideoDownloader"]
