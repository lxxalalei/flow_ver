#!/usr/bin/env python3
"""Execute a constrained download-plan/v1 and write download/v1 output."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from content_validation import validate_download_file
from http_client import urlopen_with_fallback
from validate_output import validate as validate_output
from webpage_archive import ArchiveSizeLimitError, archive_webpage


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_SCRIPTS = {
    "bilibili": SKILL_ROOT / "scripts/platforms/bilibili_download.py",
    "cctv": SKILL_ROOT / "scripts/platforms/cctv_download.py",
    "douyin": SKILL_ROOT / "scripts/platforms/douyin_download.py",
    "nlc": SKILL_ROOT / "scripts/platforms/nlc_download.py",
    "open163": SKILL_ROOT / "scripts/platforms/open163_download.py",
    "smartedu": SKILL_ROOT / "scripts/platforms/smartedu_download.py",
    "yixi": SKILL_ROOT / "scripts/platforms/yixi_download.py",
    "zhihu": SKILL_ROOT / "scripts/platforms/zhihu_download.py",
}
ALLOWED_STRATEGIES = {"auto", "platform", "direct", "webpage", "metadata"}
DIRECT_FILE_EXTENSIONS = {
    ".7z", ".aac", ".avi", ".csv", ".doc", ".docx", ".epub", ".flac",
    ".avif", ".bmp", ".gif", ".gz", ".heic", ".heif", ".jpeg", ".jpg", ".json", ".m4a", ".mkv", ".mov",
    ".mp3", ".mp4", ".odp", ".ods", ".odt", ".pdf", ".png", ".ppt",
    ".pptx", ".rar", ".rtf", ".tar", ".txt", ".wav", ".webm", ".webp",
    ".svg", ".tif", ".tiff", ".ts", ".xls", ".xlsx", ".xml", ".zip",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_component(value: str, fallback: str = "resource", limit: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (cleaned or fallback)[:limit]


def validate_plan(plan: dict[str, Any], selection: dict[str, Any], stage3: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(plan) != {"_meta", "data"}:
        errors.append("download plan 根节点只能包含 _meta 和 data")
    meta = plan.get("_meta")
    data = plan.get("data")
    if not isinstance(meta, dict) or meta.get("schema_version") != "download-plan/v1":
        errors.append("download plan schema_version 必须为 download-plan/v1")
        meta = {}
    elif set(meta) != {"schema_version", "session_id"}:
        errors.append("download plan _meta 只能包含 schema_version 和 session_id")
    session_id = selection.get("_meta", {}).get("session_id")
    if meta.get("session_id") != session_id:
        errors.append("download plan session_id 必须继承 Stage 4")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return errors + ["download plan data.items 必须是 array"]
    if set(data) != {"items"}:
        errors.append("download plan data 只能包含 items")
    expected_ids = [
        item.get("resource_id")
        for item in selection.get("data", {}).get("selected", [])
        if isinstance(item, dict)
    ]
    stage3_ids = {
        item.get("resource_id")
        for item in stage3.get("data", {}).get("resources", [])
        if isinstance(item, dict)
    }
    actual_ids: list[Any] = []
    for index, item in enumerate(data["items"]):
        prefix = f"data.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是 object")
            continue
        allowed = {"resource_id", "strategy", "allow_metadata_fallback", "filename", "formats", "expected_formats", "max_bytes", "timeout_seconds"}
        extra = set(item) - allowed
        if extra:
            errors.append(f"{prefix} 存在未定义字段: {sorted(extra)}")
        resource_id = item.get("resource_id")
        actual_ids.append(resource_id)
        if not isinstance(resource_id, str) or not resource_id.strip():
            errors.append(f"{prefix}.resource_id 必须是非空字符串")
        elif resource_id not in stage3_ids:
            errors.append(f"{prefix}.resource_id 不存在于 Stage 3")
        if item.get("strategy", "auto") not in ALLOWED_STRATEGIES:
            errors.append(f"{prefix}.strategy 非法")
        if "allow_metadata_fallback" in item and not isinstance(item["allow_metadata_fallback"], bool):
            errors.append(f"{prefix}.allow_metadata_fallback 必须是 boolean")
        for field in ("formats", "expected_formats"):
            if field in item and (
                not isinstance(item[field], list)
                or any(not isinstance(value, str) or not value.strip() for value in item[field])
            ):
                errors.append(f"{prefix}.{field} 必须是字符串数组")
        for field in ("max_bytes", "timeout_seconds"):
            if field in item and (
                not isinstance(item[field], int) or isinstance(item[field], bool) or item[field] <= 0
            ):
                errors.append(f"{prefix}.{field} 必须是正整数")
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
        errors.append("download plan 必须与 Stage 4 选择一一对应")
    return errors


def error_object(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"error_code": code, "message": message[:1000], "retryable": retryable}


def classify_process_error(output: str, returncode: int) -> dict[str, Any]:
    message = (output or f"下载命令退出码 {returncode}").strip()
    lowered = message.lower()
    dependency = re.search(r"no module named ['\"]([^'\"]+)", lowered)
    if dependency:
        return error_object("SYSTEM_DEPENDENCY_MISSING", f"缺少下载依赖: {dependency.group(1)}")
    if any(marker in lowered for marker in ("cookie", "unauthorized", "需要登录", "认证", "login")):
        return error_object("AUTH_REQUIRED", message)
    if any(marker in lowered for marker in ("timeout", "timed out", "超时")):
        return error_object("NETWORK_TIMEOUT", message, True)
    if any(marker in lowered for marker in ("drm", "付费", "会员", "premium")):
        return error_object("CONTENT_PREMIUM_OR_DRM", message)
    return error_object("DOWNLOAD_EXECUTION_FAILED", message)


def exception_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ArchiveSizeLimitError):
        return error_object("DOWNLOAD_TOO_LARGE", str(exc))
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in {401, 403}:
            return error_object("AUTH_REQUIRED", f"HTTP {exc.code}")
        if exc.code == 404:
            return error_object("CONTENT_NOT_FOUND", "HTTP 404")
        if exc.code == 429:
            return error_object("NETWORK_RATE_LIMITED", "HTTP 429", True)
        return error_object("NETWORK_HTTP_ERROR", f"HTTP {exc.code}", 500 <= exc.code < 600)
    if isinstance(exc, (urllib.error.URLError, TimeoutError)):
        return error_object("NETWORK_CONNECTION_FAILED", str(exc), True)
    message = str(exc)
    if "超过下载计划允许的大小" in message:
        return error_object("DOWNLOAD_TOO_LARGE", message)
    code, separator, detail = message.partition(": ")
    if separator and re.fullmatch(r"[A-Z0-9_]+", code):
        return error_object(code, detail, code in {"NETWORK_TIMEOUT", "NETWORK_CONNECTION_FAILED", "NETWORK_RATE_LIMITED"})
    return error_object("DOWNLOAD_EXECUTION_FAILED", message)


def validation_message(validation: dict[str, Any]) -> str:
    errors = validation.get("errors")
    if isinstance(errors, list):
        messages = [str(item.get("message")) for item in errors if isinstance(item, dict) and item.get("message")]
        if messages:
            return "; ".join(messages)
    return "下载文件格式或内容校验失败"


def platform_command(platform: str, source_url: str, output_dir: Path, item: dict[str, Any]) -> list[str]:
    script = PLATFORM_SCRIPTS.get(platform)
    if script is None or not script.is_file():
        raise ValueError(f"平台没有单资源下载入口: {platform}")
    if platform == "bilibili":
        command = [sys.executable, str(script), "download", source_url, "-o", str(output_dir)]
        cookie_file = os.environ.get("BILIBILI_COOKIE_FILE")
        cdp = os.environ.get("BILIBILI_CDP_URL")
        if cookie_file:
            command.extend(["--cookie", cookie_file])
        if cdp:
            command.extend(["--cdp", cdp])
        return command
    if platform == "douyin":
        command = [sys.executable, str(script), "download", source_url, "-o", str(output_dir)]
        cdp = os.environ.get("DOUYIN_CDP_URL")
        if cdp:
            command.extend(["--cdp", cdp])
        cookie_file = os.environ.get("DOUYIN_COOKIE_FILE")
        if cookie_file:
            command.extend(["--cookie", cookie_file])
        return command
    if platform == "smartedu":
        command = [sys.executable, str(script), "download", source_url, "-o", str(output_dir)]
        formats = item.get("formats")
        if isinstance(formats, list) and formats:
            command.extend(["--formats", ",".join(formats)])
        return command
    if platform == "nlc":
        return [
            sys.executable,
            str(script),
            "download",
            source_url,
            "-o",
            str(output_dir),
            "--timeout",
            str(min(int(item.get("timeout_seconds", 30)), 300)),
            "--max-bytes",
            str(min(int(item.get("max_bytes", 1024 * 1024 * 1024)), 4 * 1024 * 1024 * 1024)),
        ]
    if platform == "cctv":
        timeout = min(int(item.get("timeout_seconds", 60)), 300)
        return [
            sys.executable,
            str(script),
            "download",
            source_url,
            "-o",
            str(output_dir),
            "--timeout",
            str(timeout),
            "--total-timeout",
            str(min(max(timeout * 5, 60), 1800)),
            "--max-bytes",
            str(min(int(item.get("max_bytes", 2 * 1024 * 1024 * 1024)), 4 * 1024 * 1024 * 1024)),
        ]
    if platform == "open163":
        return [
            sys.executable,
            str(script),
            "download",
            source_url,
            "-o",
            str(output_dir),
            "--timeout",
            str(min(int(item.get("timeout_seconds", 60)), 600)),
            "--max-bytes",
            str(min(int(item.get("max_bytes", 2 * 1024 * 1024 * 1024)), 4 * 1024 * 1024 * 1024)),
        ]
    if platform == "yixi":
        return [
            sys.executable,
            str(script),
            "download",
            source_url,
            "-o",
            str(output_dir),
            "--timeout",
            str(min(int(item.get("timeout_seconds", 60)), 300)),
            "--max-bytes",
            str(min(int(item.get("max_bytes", 2 * 1024 * 1024 * 1024)), 4 * 1024 * 1024 * 1024)),
        ]
    return [sys.executable, str(script), "download", source_url, "-o", str(output_dir)]


def platform_is_applicable(platform: str, resource: dict[str, Any]) -> bool:
    script = PLATFORM_SCRIPTS.get(platform)
    if script is None or not script.is_file():
        return False
    if platform == "nlc":
        return str(resource.get("resource_id") or "").startswith("nlc:yuewen:")
    if platform == "cctv":
        return (urllib.parse.urlsplit(str(resource.get("source_url") or "")).hostname or "").lower() == "tv.cctv.com"
    if platform == "open163":
        return (urllib.parse.urlsplit(str(resource.get("source_url") or "")).hostname or "").lower() == "open.163.com"
    if platform == "yixi":
        return (urllib.parse.urlsplit(str(resource.get("source_url") or "")).hostname or "").lower() in {"yixi.tv", "www.yixi.tv"}
    return True


def looks_like_direct_file(resource: dict[str, Any]) -> bool:
    source_url = str(resource.get("source_url") or "")
    suffix = Path(urllib.parse.unquote(urllib.parse.urlsplit(source_url).path)).suffix.lower()
    if suffix in DIRECT_FILE_EXTENSIONS:
        return True
    raw_metadata = resource.get("raw_metadata")
    if isinstance(raw_metadata, dict):
        for key in ("download_url", "file_url", "pdf_url", "epub_url"):
            value = raw_metadata.get(key)
            if isinstance(value, str) and value.strip() == source_url:
                return True
    return False


def strategy_chain(resource: dict[str, Any], requested: str) -> list[str]:
    if requested != "auto":
        return [requested]
    platform = str(resource.get("platform") or "")
    if platform_is_applicable(platform, resource):
        return ["platform", "webpage"]
    if looks_like_direct_file(resource):
        return ["direct", "webpage"]
    return ["webpage", "direct"]


def run_platform_download(platform: str, source_url: str, output_dir: Path, item: dict[str, Any]) -> str | None:
    command = platform_command(platform, source_url, output_dir, item)
    env = dict(os.environ)
    scripts_dir = str(SKILLS_ROOT / "resource-platforms/scripts")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [scripts_dir, env.get("PYTHONPATH", "")]))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    timeout = min(int(item.get("timeout_seconds", 900)), 3600)
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("NETWORK_TIMEOUT: 下载命令超时") from exc
    output = "\n".join(part.strip() for part in (completed.stderr, completed.stdout) if part and part.strip())
    if completed.returncode != 0:
        detail = classify_process_error(output, completed.returncode)
        raise RuntimeError(f"{detail['error_code']}: {detail['message']}")
    if platform == "yixi":
        level = re.search(r"\b(Level [123])\b", output)
        return level.group(1) if level else None
    return None


def direct_download(source_url: str, output_dir: Path, item: dict[str, Any]) -> Path:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("direct 策略只允许 http/https URL")
    request = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0 learning-resource-flow/1.0"})
    timeout = min(int(item.get("timeout_seconds", 60)), 300)
    max_bytes = min(int(item.get("max_bytes", 1024 * 1024 * 1024)), 4 * 1024 * 1024 * 1024)
    with urlopen_with_fallback(request, timeout=timeout) as response:
        final_url = response.geturl()
        if urllib.parse.urlsplit(final_url).scheme not in {"http", "https"}:
            raise ValueError("下载重定向到了不允许的协议")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("文件超过下载计划允许的大小")
        filename = item.get("filename") or response.headers.get_filename()
        if not isinstance(filename, str) or not filename.strip():
            filename = Path(urllib.parse.unquote(urllib.parse.urlsplit(final_url).path)).name
        if not filename:
            extension = mimetypes.guess_extension(response.headers.get_content_type()) or ".bin"
            filename = f"download{extension}"
        elif not Path(str(filename)).suffix:
            extension = mimetypes.guess_extension(response.headers.get_content_type())
            if extension:
                filename = f"{filename}{extension}"
        destination = output_dir / safe_component(filename, "download.bin", 120)
        total = 0
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("文件超过下载计划允许的大小")
                handle.write(chunk)
        if total == 0:
            raise ValueError("下载结果为空文件")
    validation = validate_download_file(destination, item.get("expected_formats"))
    if not validation.get("valid"):
        raise RuntimeError(f"DOWNLOAD_FILE_CORRUPTED: {validation_message(validation)}")
    if validation.get("detected_format") == "html" and not item.get("expected_formats"):
        raise RuntimeError("DOWNLOAD_NOT_DIRECT_FILE: URL 返回网页而不是独立文件")
    return destination


def webpage_download(source_url: str, output_dir: Path, item: dict[str, Any]) -> None:
    metadata = archive_webpage(
        source_url,
        output_dir,
        timeout_seconds=min(int(item.get("timeout_seconds", 60)), 300),
        max_bytes=min(int(item.get("max_bytes", 20 * 1024 * 1024)), 100 * 1024 * 1024),
    )
    for filename, expected in (("source.html", "html"), ("content.md", "text"), ("metadata.json", "text")):
        validation = validate_download_file(output_dir / filename, expected)
        if not validation.get("valid"):
            raise RuntimeError(f"PARSE_FORMAT_NOT_SUPPORTED: {filename}: {validation_message(validation)}")
    markdown = (output_dir / "content.md").read_text(encoding="utf-8", errors="replace")
    if int(metadata.get("content_characters") or 0) < 40:
        raise RuntimeError("PARSE_EMPTY_CONTENT: 网页没有提取到足够的可读正文")
    probe = markdown[:4000].lower()
    if any(marker in probe for marker in ("请登录", "登录后查看", "login required", "sign in to continue")):
        raise RuntimeError("AUTH_REQUIRED: 网页正文实际是登录提示")
    if any(marker in probe for marker in ("验证码", "captcha", "人机验证")):
        raise RuntimeError("ANTI_CRAWL_CAPTCHA: 网页正文实际是验证页面")
    if any(marker in probe for marker in ("enable javascript", "请启用 javascript", "javascript is required")):
        raise RuntimeError("PARSE_EMPTY_CONTENT: 页面需要浏览器脚本渲染，静态归档没有取得正文")


def write_metadata(resource: dict[str, Any], output_dir: Path, error: dict[str, Any] | None) -> None:
    title = str(resource.get("title") or resource.get("resource_id") or "资源")
    lines = [
        f"# {title}",
        "",
        f"- 资源 ID：{resource.get('resource_id', '')}",
        f"- 来源平台：{resource.get('platform', '')}",
        f"- 来源链接：{resource.get('source_url', '')}",
    ]
    if resource.get("description"):
        lines.extend(["", "## 已知简介", "", str(resource["description"])])
    if error:
        lines.extend(["", "## 降级原因", "", error["message"]])
    (output_dir / "source.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def clear_directory(path: Path) -> None:
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            shutil.rmtree(child)


def commit_download(
    temp_dir: Path,
    downloads_root: Path,
    resource_id: str,
    expected_formats: list[str] | None = None,
) -> list[str]:
    unsafe_links = [path for path in temp_dir.rglob("*") if path.is_symlink()]
    if unsafe_links:
        raise ValueError("下载结果包含不允许的符号链接")
    files = [path for path in temp_dir.rglob("*") if path.is_file() and not path.is_symlink()]
    if not files:
        raise ValueError("下载命令没有产生可用文件")
    detected_formats: list[str] = []
    for path in files:
        validation = validate_download_file(path)
        if not validation.get("valid"):
            raise RuntimeError(f"DOWNLOAD_FILE_CORRUPTED: {path.name}: {validation_message(validation)}")
        detected_formats.append(str(validation.get("detected_format") or "unknown"))
    if expected_formats:
        matches_expected = any(validate_download_file(path, expected_formats).get("valid") for path in files)
        if not matches_expected:
            raise RuntimeError(
                "DOWNLOAD_UNEXPECTED_FORMAT: "
                f"下载结果格式为 {sorted(set(detected_formats))}，未匹配期望格式 {expected_formats}"
            )
    base = safe_component(resource_id.replace(":", "-"), "resource")
    destination = downloads_root / base
    counter = 2
    while destination.exists():
        destination = downloads_root / f"{base}-{counter}"
        counter += 1
    os.replace(temp_dir, destination)
    return [str(path.resolve()) for path in destination.rglob("*") if path.is_file() and not path.is_symlink()]


def execute_item(resource: dict[str, Any], item: dict[str, Any], downloads_root: Path, partial_root: Path) -> dict[str, Any]:
    resource_id = str(resource["resource_id"])
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{safe_component(resource_id)}-", dir=partial_root))
    requested_strategy = item.get("strategy", "auto")
    allow_fallback = item.get("allow_metadata_fallback", True)
    failure: dict[str, Any] | None = None
    try:
        if requested_strategy == "metadata":
            failure = error_object("METADATA_ONLY_REQUESTED", "下载计划明确要求只保存元数据")
            write_metadata(resource, temp_dir, failure)
            return {
                "resource_id": resource_id,
                "download_status": "degraded",
                "degraded_level": "Level 3",
                "files": commit_download(temp_dir, downloads_root, resource_id),
                "error": failure,
            }
        completed_strategy = ""
        completed_level: str | None = None
        for strategy in strategy_chain(resource, requested_strategy):
            for attempt in range(2):
                try:
                    if strategy == "platform":
                        completed_level = run_platform_download(
                            str(resource.get("platform") or ""),
                            str(resource.get("source_url") or ""),
                            temp_dir,
                            item,
                        )
                    elif strategy == "direct":
                        direct_download(str(resource.get("source_url") or ""), temp_dir, item)
                    else:
                        webpage_download(str(resource.get("source_url") or ""), temp_dir, item)
                    failure = None
                    completed_strategy = strategy
                    break
                except Exception as exc:
                    failure = exception_error(exc)
                    if failure["retryable"] and attempt == 0:
                        clear_directory(temp_dir)
                        time.sleep(2)
                        continue
                    break
            if failure is None:
                break
            clear_directory(temp_dir)
        if failure is not None:
            raise RuntimeError(f"{failure['error_code']}: {failure['message']}")
        if completed_strategy == "webpage":
            return {
                "resource_id": resource_id,
                "download_status": "degraded",
                "degraded_level": "Level 2",
                "files": commit_download(temp_dir, downloads_root, resource_id),
                "error": error_object("DOWNLOAD_DEGRADED_TO_WEBPAGE", "未取得独立原文件，已保存来源网页和可读正文"),
            }
        if completed_level is not None:
            return {
                "resource_id": resource_id,
                "download_status": "degraded",
                "degraded_level": completed_level,
                "files": commit_download(temp_dir, downloads_root, resource_id, item.get("expected_formats")),
                "error": error_object("DOWNLOAD_PLATFORM_DEGRADED", "平台只提供公开预览、视频版本或完整文稿，未取得 Level 0 原资源"),
            }
        return {
            "resource_id": resource_id,
            "download_status": "success",
            "files": commit_download(temp_dir, downloads_root, resource_id, item.get("expected_formats")),
        }
    except Exception as exc:
        failure = exception_error(exc)
        if allow_fallback:
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = Path(tempfile.mkdtemp(prefix=f"{safe_component(resource_id)}-", dir=partial_root))
            write_metadata(resource, temp_dir, failure)
            return {
                "resource_id": resource_id,
                "download_status": "degraded",
                "degraded_level": "Level 3",
                "files": commit_download(temp_dir, downloads_root, resource_id),
                "error": failure,
            }
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"resource_id": resource_id, "download_status": "failed", "files": [], "error": failure}


def run(session_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    selection = load_object(session_dir / "stage4_selection.json")
    stage3 = load_object(session_dir / "stage3_search_results.json")
    plan_errors = validate_plan(plan, selection, stage3)
    if plan_errors:
        raise ValueError("; ".join(plan_errors))
    resources = {
        item["resource_id"]: item
        for item in stage3.get("data", {}).get("resources", [])
        if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
    }
    downloads_root = (session_dir / "downloads").resolve()
    partial_root = downloads_root / ".partial"
    partial_root.mkdir(parents=True, exist_ok=True)
    results = [execute_item(resources[item["resource_id"]], item, downloads_root, partial_root) for item in plan["data"]["items"]]
    if partial_root.exists() and not any(partial_root.iterdir()):
        partial_root.rmdir()
    counts = {status: sum(result["download_status"] == status for result in results) for status in ("success", "degraded", "failed")}
    return {
        "_meta": {
            "schema_version": "download/v1",
            "session_id": selection.get("_meta", {}).get("session_id"),
            "created_at": now_iso(),
        },
        "_summary": {
            "success_count": counts["success"],
            "degraded_count": counts["degraded"],
            "failed_count": counts["failed"],
        },
        "data": {"results": results},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="执行受限下载计划并写入 Stage 5")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        session_dir = args.session_dir.resolve()
        plan_path = args.plan or session_dir / "download_plan.json"
        output_path = args.output or session_dir / "stage5_download.json"
        selection = load_object(session_dir / "stage4_selection.json")
        stage3 = load_object(session_dir / "stage3_search_results.json")
        document = run(session_dir, load_object(plan_path))
        errors = validate_output(session_dir, selection, stage3, document)
        if errors:
            raise ValueError("; ".join(errors))
        atomic_write(output_path, document)
        print(json.dumps(document["_summary"], ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
