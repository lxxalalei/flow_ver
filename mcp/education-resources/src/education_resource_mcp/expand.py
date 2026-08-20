"""Generic structural expansion for container resources.

The public MCP exposes one ``resource_expand`` capability.  Platform adapters
keep the mechanical details: creator paging, collection/album traversal,
textbook bindings, and course lesson enumeration.  Expansion discovers child
resources only; it never authorizes a download.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from itertools import islice
import json
import os
from pathlib import Path
import re
import urllib.parse
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request
from typing import Any

from .errors import DomainError
from .job_state import (
    CANCEL_FLAG_NAME,
    FileCancelEvent,
    TERMINAL_STATUSES,
    job_dir,
    read_job,
    read_request,
    utc_now_iso,
    write_job,
    write_request,
)
from .jobs import spawn_worker
from .search import canonical_http_url


RESULTS_NAME = "results.jsonl"
_XIMALAYA_TRACKS_URL = "https://www.ximalaya.com/revision/album/v1/getTracksList"
_XIMALAYA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_MD5_RE = re.compile(r"[0-9a-fA-F]{32}")


def _raw_resource_from_url(source_url: str) -> dict[str, Any]:
    """Recognize a known URL into the smallest factual Resource shape.

    Platform-specific path parsing belongs here rather than in the public Tool
    schema.  Unknown URLs remain generic web resources.
    """

    url = canonical_http_url(str(source_url or "").strip())
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    path = parsed.path or "/"
    query = urllib.parse.parse_qs(parsed.query)

    def resource(platform: str, kind: str, title: str | None = None, **metadata: Any) -> dict[str, Any]:
        return {
            "platform": platform,
            "title": title or (path.rstrip("/").rsplit("/", 1)[-1] or host or url)[:120],
            "source_url": url,
            "resource_type": kind,
            "metadata": metadata,
        }

    if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"} and path.startswith("/video/"):
        return resource("bilibili", "视频")
    if host == "space.bilibili.com":
        if "/lists/" in path or "/channel/collectiondetail" in path or "/channel/seriesdetail" in path:
            return resource("bilibili", "collection", "Bilibili collection")
        return resource("bilibili", "creator", "Bilibili creator")

    if host in {"douyin.com", "www.douyin.com"}:
        if path.startswith("/video/"):
            return resource("douyin", "视频")
        if path.startswith("/user/"):
            return resource("douyin", "creator", "Douyin creator")
        if path.startswith("/collection/"):
            return resource("douyin", "collection", "Douyin collection")

    if host in {"ximalaya.com", "www.ximalaya.com"}:
        if re.search(r"/sound/\d+", path):
            return resource("ximalaya", "音频")
        if re.search(r"/album/\d+", path):
            return resource("ximalaya", "album", "Ximalaya album")
        if re.search(r"/zhubo/\d+", path):
            return resource("ximalaya", "creator", "Ximalaya creator")

    if host == "basic.smartedu.cn":
        if "/tchMaterial/" in path:
            return resource("smartedu", "教材", "SmartEdu textbook")
        if "activityId" in query or "courseId" in query:
            return resource("smartedu", "课程", "SmartEdu course")
        return resource("smartedu", "网页")

    if host == "k.zjer.cn" and ("/courseAfter/" in path or "courseCateId" in query or "id" in query):
        return resource("zjer", "课程", "Zjer course")

    if host.startswith("libgen."):
        md5_match = _MD5_RE.search(url)
        signals = {"md5": md5_match.group(0).lower()} if md5_match else {}
        # Internally the existing inspector/downloader still use the historical
        # provider id.  The public MCP rewrites the label to ``libgen``.
        return resource(
            "annas-archive",
            "图书",
            "LibGen book",
            platform_signals=signals,
        )

    if host in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
        return resource("zhihu", "文章")

    return resource("generic", "网页")


def import_resource_url(service: Any, source_url: str) -> dict[str, Any]:
    """Register and inspect a known URL, including platforms absent from the old importer."""

    raw = _raw_resource_from_url(source_url)
    registered = service._remember_resources([raw])  # noqa: SLF001 - same capability package
    if not registered:
        raise DomainError("RESOURCE_NOT_FOUND", "无法建立资源句柄")
    resource_id = str(registered[0]["resource_id"])
    inspected = service.inspect(resource_id)
    return {"resource_id": resource_id, **{k: v for k, v in inspected.items() if k != "resource_id"}}


def start_expand(
    service: Any,
    *,
    resource_id: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    """Start a persistent full structural expansion job."""

    resource_id = str(resource_id or "").strip()
    source_url = str(source_url or "").strip()
    if bool(resource_id) == bool(source_url):
        raise DomainError(
            "INVALID_ARGUMENT",
            "resource_id 与 source_url 必须且只能提供一种展开目标",
        )
    if resource_id:
        target = service._get_resource(resource_id)  # noqa: SLF001
    else:
        target = _raw_resource_from_url(source_url)

    # Keep Job identity aligned with ResourceService without importing
    # service.py here (which would form a worker import cycle).
    import secrets

    job_id = f"job_{secrets.token_hex(16)}"
    directory = job_dir(service.settings.jobs_dir, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    write_request(
        directory,
        {
            "kind": "resource_expand",
            "job_id": job_id,
            "target": target,
        },
    )
    write_job(
        directory,
        {
            "job_id": job_id,
            "kind": "resource_expand",
            "status": "queued",
            "total": 0,
            "completed": 0,
            "files": [],
            "failures": [],
            "pid": None,
            "created_at": utc_now_iso(),
        },
    )

    def _spawn() -> Any:
        if (directory / CANCEL_FLAG_NAME).exists():
            write_job(directory, {**read_job(directory), "status": "cancelled"})
            return None
        return spawn_worker(directory)

    service.job_runner.submit(job_id, _spawn)
    return {"job_id": job_id, "status": "queued"}


def read_expand(service: Any, job_id: str, *, offset: int = 0, limit: int = 20) -> dict[str, Any]:
    """Read one page of a completed/running expansion without truncating its dataset."""

    directory, job = service._load_job(job_id)  # noqa: SLF001
    job = service._reconcile(directory, job)  # noqa: SLF001
    if str(job.get("kind") or "") != "resource_expand":
        raise DomainError("INVALID_ARGUMENT", "该任务不是资源展开任务")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise DomainError("INVALID_ARGUMENT", "offset 必须 >= 0")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise DomainError("INVALID_ARGUMENT", "limit 必须 >= 1")
    limit = min(limit, 50)

    path = directory / RESULTS_NAME
    items: list[dict[str, Any]] = []
    line_count = 0
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            lines = list(islice(handle, offset, offset + limit))
        line_count = len(lines)
        for index, line in enumerate(lines, start=offset + 1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    "JOB_STATE_INVALID",
                    "资源展开结果文件损坏",
                    details={"job_id": job_id, "line": index},
                ) from exc
            if not isinstance(raw, dict):
                raise DomainError("JOB_STATE_INVALID", "资源展开结果项格式无效")
            registered = service._remember_resources([raw])  # noqa: SLF001
            if registered:
                items.append(registered[0])

    total = max(int(job.get("total") or 0), int(job.get("completed") or 0))
    status = str(job.get("status") or "")
    return {
        "job_id": job_id,
        "kind": "resource_expand",
        "status": status,
        "total": total,
        "offset": offset,
        "items": items,
        "complete": status in TERMINAL_STATUSES and offset + line_count >= total,
        "failures": [dict(item) for item in job.get("failures") or []],
    }


def download_expanded(service: Any, expand_job_id: str, *, preferred_container: str = "original") -> dict[str, Any]:
    """Download every child only after the caller explicitly selected the whole expansion."""

    directory, job = service._load_job(expand_job_id)  # noqa: SLF001
    job = service._reconcile(directory, job)  # noqa: SLF001
    if str(job.get("kind") or "") != "resource_expand":
        raise DomainError("INVALID_ARGUMENT", "expand_job_id 不是资源展开任务")
    if str(job.get("status") or "") != "succeeded":
        raise DomainError(
            "EXPAND_INCOMPLETE",
            "展开结果尚未完整成功，不能把部分结果当成用户选择的全部资源",
        )
    path = directory / RESULTS_NAME
    if not path.is_file():
        raise DomainError("JOB_STATE_INVALID", "资源展开结果文件不存在")
    raw_resources = _read_all_results(path)
    registered = service._remember_resources(raw_resources)  # noqa: SLF001
    resource_ids = [str(item["resource_id"]) for item in registered]
    if not resource_ids:
        raise DomainError("RESOURCE_NOT_FOUND", "资源展开任务没有可下载子资源")
    result = service.download(resource_ids, preferred_container=preferred_container)
    result["source_expand_job_id"] = expand_job_id
    return result


def run_expand(directory: Path, service: Any = None) -> int:
    """Worker entry: enumerate the structural children into ``results.jsonl``."""

    request = read_request(directory)
    target = request.get("target")
    if not isinstance(target, dict):
        write_job(
            directory,
            {
                **read_job(directory),
                "status": "failed",
                "failures": [{"code": "INVALID_ARGUMENT", "message": "展开目标无效", "retryable": False}],
            },
        )
        return 1

    if service is None:
        from .service import ResourceService

        service = ResourceService(recover_jobs=False)

    cancel = FileCancelEvent(directory / CANCEL_FLAG_NAME)
    write_job(directory, {**read_job(directory), "status": "running", "pid": os.getpid()})
    results_path = directory / RESULTS_NAME
    results_path.unlink(missing_ok=True)
    failures: list[dict[str, Any]] = []
    count = 0

    try:
        iterator = iter_expand(service, target, cancel_event=cancel)
        seen: set[tuple[str, str]] = set()
        with results_path.open("w", encoding="utf-8") as handle:
            for resource in iterator:
                if cancel.is_set():
                    break
                if not isinstance(resource, dict):
                    continue
                url = str(resource.get("source_url") or "").strip()
                platform = str(resource.get("platform") or "generic")
                title = str(resource.get("title") or "").strip()
                if not url or not title:
                    continue
                key = (platform, url)
                if key in seen:
                    continue
                seen.add(key)
                persisted = _persistable_resource(resource)
                handle.write(json.dumps(persisted, ensure_ascii=False) + "\n")
                handle.flush()
                count += 1
                if count % 20 == 0:
                    write_job(
                        directory,
                        {
                            **read_job(directory),
                            "status": "running",
                            "pid": os.getpid(),
                            "completed": count,
                            "total": count,
                        },
                    )
    except Exception as exc:  # record provider/domain facts; do not hide partial output
        failures.append(_failure_from_exception(exc))

    if cancel.is_set():
        final = "cancelled"
    elif failures and count:
        final = "partial"
    elif count:
        final = "succeeded"
    else:
        final = "failed"

    files: list[dict[str, Any]] = []
    if count and results_path.is_file():
        files = [{"filename": RESULTS_NAME, "path": str(results_path), "lines": count}]
    else:
        results_path.unlink(missing_ok=True)
    write_job(
        directory,
        {
            **read_job(directory),
            "status": final,
            "pid": os.getpid(),
            "total": count,
            "completed": count,
            "files": files,
            "failures": failures,
        },
    )
    return 0


def iter_expand(service: Any, target: Mapping[str, Any], *, cancel_event: Any = None) -> Iterator[dict[str, Any]]:
    """Dispatch one container Resource to the platform's deterministic expander."""

    platform = str(target.get("platform") or "").strip()
    url = str(target.get("source_url") or "").strip()
    rtype = str(target.get("resource_type") or "").strip().lower()
    metadata = target.get("metadata") if isinstance(target.get("metadata"), Mapping) else {}
    adapters = getattr(service.search_provider, "_adapters", None) or {}
    adapter = adapters.get(platform)

    if platform == "bilibili":
        if adapter is None:
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili adapter 不可用")
        creator_id = metadata.get("creator_mid") if isinstance(metadata, Mapping) else None
        if creator_id and rtype in {"video", "视频"}:
            iterator = getattr(adapter, "iter_creator", None)
            if callable(iterator):
                yield from iterator(str(creator_id), cancel_event=cancel_event)
                return
        if "space.bilibili.com" in url and (
            "/lists/" in url or "/channel/collectiondetail" in url or "/channel/seriesdetail" in url
        ):
            iterator = getattr(adapter, "iter_collection", None)
        elif "space.bilibili.com" in url:
            iterator = getattr(adapter, "iter_creator", None)
        else:
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili 单个视频没有可展开子资源")
        if not callable(iterator):
            raise DomainError("FEATURE_NOT_SUPPORTED", "Bilibili 当前不支持该结构展开")
        yield from iterator(url, cancel_event=cancel_event)
        return

    if platform == "douyin":
        if adapter is None:
            raise DomainError("FEATURE_NOT_SUPPORTED", "Douyin adapter 不可用")
        creator_id = metadata.get("creator_sec_uid") if isinstance(metadata, Mapping) else None
        if creator_id and rtype in {"video", "视频"}:
            iterator = getattr(adapter, "iter_creator", None)
            if callable(iterator):
                yield from iterator(str(creator_id), cancel_event=cancel_event)
                return
        if "/user/" in url:
            iterator = getattr(adapter, "iter_creator", None)
            if not callable(iterator):
                raise DomainError("FEATURE_NOT_SUPPORTED", "Douyin 创作者展开不可用")
            yield from iterator(url, cancel_event=cancel_event)
            return
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "Douyin 合集完整枚举接口尚未确认；当前只支持创作者主页展开为视频",
        )

    if platform == "ximalaya":
        if re.search(r"/album/\d+", url):
            yield from _iter_ximalaya_album(url, cancel_event=cancel_event)
            return
        if re.search(r"/zhubo/\d+", url):
            raise DomainError(
                "FEATURE_NOT_SUPPORTED",
                "Ximalaya 创作者全部专辑的稳定分页接口尚未确认",
            )
        raise DomainError("FEATURE_NOT_SUPPORTED", "Ximalaya 单集声音没有可展开子资源")

    if platform == "smartedu":
        if "/tchMaterial/" in url:
            if adapter is None:
                raise DomainError("FEATURE_NOT_SUPPORTED", "SmartEdu adapter 不可用")
            yield from _iter_smartedu_textbook(adapter, url, cancel_event=cancel_event)
            return
        raise DomainError(
            "FEATURE_NOT_SUPPORTED",
            "SmartEdu 课程当前支持自然完整资源包下载；独立附件子资源尚未形成稳定 Resource 身份",
        )

    if platform == "zjer":
        yield from _iter_zjer_course(service, url, cancel_event=cancel_event)
        return

    raise DomainError("FEATURE_NOT_SUPPORTED", f"平台 {platform or 'generic'} 当前没有结构展开能力")


def _iter_ximalaya_album(source_url: str, *, cancel_event: Any = None) -> Iterator[dict[str, Any]]:
    match = re.search(r"/album/(\d+)", source_url)
    if not match:
        raise DomainError("INVALID_ARGUMENT", "Ximalaya 专辑 URL 缺少 album id")
    album_id = match.group(1)
    page_num = 1
    page_size = 100
    seen = 0
    total: int | None = None

    from .adapters.http_client import urlopen_with_fallback

    while total is None or seen < total:
        if cancel_event is not None and cancel_event.is_set():
            return
        params = urlencode({"albumId": album_id, "pageNum": page_num, "pageSize": page_size})
        request = Request(
            f"{_XIMALAYA_TRACKS_URL}?{params}",
            headers={"User-Agent": _XIMALAYA_UA, "Referer": source_url, "Accept": "application/json, text/plain, */*"},
        )
        with urlopen_with_fallback(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise DomainError("PARTIAL_FAILURE", "Ximalaya 专辑曲目响应结构异常", retryable=True)
        tracks = data.get("tracks") or []
        if not isinstance(tracks, list) or not tracks:
            break
        if total is None:
            try:
                total = int(data.get("trackTotalCount"))
            except (TypeError, ValueError):
                total = None
        for track in tracks:
            if not isinstance(track, dict):
                continue
            track_id = str(track.get("trackId") or track.get("track_id") or "").strip()
            title = str(track.get("title") or "").strip()
            if not track_id or not title:
                continue
            metadata: dict[str, Any] = {"platform_signals": {"album_id": album_id, "track_id": track_id}}
            duration = track.get("duration")
            if isinstance(duration, (int, float)) and duration >= 0:
                metadata["duration_seconds"] = int(duration)
            yield {
                "platform": "ximalaya",
                "title": title,
                "source_url": f"https://www.ximalaya.com/sound/{track_id}",
                "resource_type": "音频",
                "summary": str(track.get("intro") or "").strip() or None,
                "metadata": metadata,
            }
            seen += 1
        if len(tracks) < page_size:
            break
        page_num += 1


def _iter_smartedu_textbook(adapter: Any, source_url: str, *, cancel_event: Any = None) -> Iterator[dict[str, Any]]:
    parsed = urlsplit(source_url)
    params = urllib.parse.parse_qs(parsed.query)
    textbook_id = str((params.get("contentId") or [""])[0]).strip()
    if not textbook_id:
        raise DomainError("INVALID_ARGUMENT", "SmartEdu 教材 URL 缺少 contentId")

    from .adapters.smartedu import CDN_MATERIAL_PARTS_TMPL

    headers = adapter._build_headers()  # noqa: SLF001 - adapter owns current platform headers
    for part_no in range(100, 150):
        if cancel_event is not None and cancel_event.is_set():
            return
        try:
            values = adapter._cdn_json(  # noqa: SLF001 - deterministic platform shard read
                CDN_MATERIAL_PARTS_TMPL.format(mid=textbook_id, n=part_no), headers
            )
        except HTTPError as exc:
            if exc.code == 404:
                break
            raise
        if not isinstance(values, list):
            raise DomainError("PARTIAL_FAILURE", "SmartEdu 教材资源分片格式异常", retryable=True)
        for entry in values:
            if not isinstance(entry, dict):
                continue
            resource_type = str(entry.get("resource_type_code") or "").strip()
            child_id = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not child_id or not title or resource_type not in {"national_lesson", "elite_lesson"}:
                continue
            if resource_type == "national_lesson":
                child_url = (
                    "https://basic.smartedu.cn/syncClassroom/classActivity?activityId="
                    + urllib.parse.quote(child_id)
                )
            else:
                child_url = "https://basic.smartedu.cn/qualityCourse?courseId=" + urllib.parse.quote(child_id)
            yield {
                "platform": "smartedu",
                "title": title,
                "source_url": child_url,
                "resource_type": "课程",
                "metadata": {
                    "platform_signals": {
                        "textbook_id": textbook_id,
                        "resource_type_code": resource_type,
                    }
                },
            }


def _iter_zjer_course(service: Any, source_url: str, *, cancel_event: Any = None) -> Iterator[dict[str, Any]]:
    from .adapters.zjer import (
        _course_id_from_query,
        _detail_url,
        _safe_media_facts,
        best_mp4,
        fetch_course_detail,
        lessons,
    )

    course_id = _course_id_from_query(source_url)
    if course_id is None:
        raise DomainError("INVALID_ARGUMENT", "Zjer 课程 URL 缺少 courseCateId")
    data = fetch_course_detail(course_id, timeout=float(service.settings.search_timeout_seconds))
    course_name = str(data.get("cateName") or "").strip()
    org_name = str(data.get("teacherOrgName") or data.get("orgName") or "").strip()
    course_uuid = str(data.get("uuid") or "").strip()
    for lesson in lessons(data):
        if cancel_event is not None and cancel_event.is_set():
            return
        try:
            video_id = int(lesson.get("videoId") or 0)
            course_info_id = int(lesson.get("id") or 0)
        except (TypeError, ValueError):
            continue
        lesson_name = str(lesson.get("courseName") or "").strip()
        media = best_mp4(lesson)
        if not video_id or not course_info_id or not lesson_name or media is None:
            continue
        signals: dict[str, Any] = {
            "course_cate_id": course_id,
            "course_info_id": course_info_id,
            "video_id": video_id,
            "course_cate_uuid": course_uuid or None,
            "course_info_uuid": str(lesson.get("uuid") or "").strip() or None,
        }
        signals.update(_safe_media_facts(media))
        yield {
            "platform": "zjer",
            "title": f"{course_name}｜{lesson_name}" if course_name else lesson_name,
            "source_url": _detail_url(course_id, video_id=video_id),
            "resource_type": "视频",
            "metadata": {
                "author": org_name or None,
                "platform_signals": signals,
            },
        }


def _persistable_resource(resource: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "platform": str(resource.get("platform") or "generic"),
        "title": str(resource.get("title") or ""),
        "source_url": str(resource.get("source_url") or ""),
        "resource_type": resource.get("resource_type") or "其他",
        "summary": resource.get("summary"),
        "metadata": dict(resource.get("metadata") or {}) if isinstance(resource.get("metadata"), Mapping) else {},
    }


def _read_all_results(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    "JOB_STATE_INVALID",
                    "资源展开结果文件损坏",
                    details={"line": index},
                ) from exc
            if not isinstance(item, dict):
                raise DomainError("JOB_STATE_INVALID", "资源展开结果项格式无效")
            values.append(item)
    return values


def _failure_from_exception(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, DomainError):
        return {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
    code = str(getattr(exc, "code", "PARTIAL_FAILURE"))
    message = str(getattr(exc, "message", str(exc)))
    retryable = bool(getattr(exc, "retryable", True))
    return {"code": code, "message": message, "retryable": retryable}


__all__ = [
    "download_expanded",
    "import_resource_url",
    "iter_expand",
    "read_expand",
    "run_expand",
    "start_expand",
]
