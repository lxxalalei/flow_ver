"""Search-only adapter base for resource platform execution."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from html import unescape
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent.parent


class SearchAdapter(ABC):
    platform_name = ""

    @abstractmethod
    def search(self, query: str, max_results: int, params: dict[str, Any]) -> dict[str, Any]:
        """Return {results: [...], error: object|null}."""


class CLISearchAdapter(SearchAdapter):
    search_script: Path | None = None
    timeout_seconds = 60

    def _build_search_cmd(
        self, query: str, max_results: int, params: dict[str, Any], output_file: Path
    ) -> list[str] | None:
        if self.search_script is None or not self.search_script.is_file():
            return None
        return [
            sys.executable,
            str(self.search_script),
            "search",
            query,
            "--max",
            str(max_results),
            "-o",
            str(output_file),
        ]

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Platform CLIs live one directory below scripts/ but import the shared
        # package as a top-level module. Preserve any caller path and always
        # expose scripts/ to the child process.
        current = env.get("PYTHONPATH", "")
        entries = [str(SCRIPTS_DIR)]
        if current:
            entries.append(current)
        env["PYTHONPATH"] = os.pathsep.join(entries)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def search(self, query: str, max_results: int, params: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"lrs-{self.platform_name}-") as temp_dir:
            output_file = Path(temp_dir) / "result.json"
            cmd = self._build_search_cmd(query, max_results, params, output_file)
            if cmd is None:
                return self._error("SYSTEM_TOOL_NOT_FOUND", "搜索入口不存在", False)
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    env=self._subprocess_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return self._error("NETWORK_TIMEOUT", "平台搜索超时", True)
            except OSError as exc:
                return self._error("SYSTEM_EXECUTION_FAILED", str(exc), False)
            try:
                if output_file.is_file():
                    raw = json.loads(output_file.read_text(encoding="utf-8"))
                elif proc.stdout.strip():
                    raw = json.loads(proc.stdout)
                else:
                    if proc.returncode != 0:
                        return self._process_error(self._diagnostic(proc))
                    return self._error("PARSE_EMPTY_CONTENT", "平台没有返回搜索结果", False)
            except (OSError, json.JSONDecodeError) as exc:
                if proc.returncode != 0:
                    return self._process_error(self._diagnostic(proc) or str(exc))
                return self._error("PARSE_FORMAT_NOT_SUPPORTED", str(exc), False)
        normalized = self._normalize_response(raw)
        if (
            proc.returncode != 0
            and not normalized["results"]
            and not normalized["error"]
            and not self._has_result_container(raw)
        ):
            return self._process_error(self._diagnostic(proc))
        return normalized

    def _has_result_container(self, raw: Any) -> bool:
        return isinstance(raw, dict) and any(
            isinstance(raw.get(key), list) for key in ("results", "candidates", "items")
        )

    @staticmethod
    def _diagnostic(proc: subprocess.CompletedProcess[str]) -> str:
        return "\n".join(part.strip() for part in (proc.stderr, proc.stdout) if part and part.strip())

    def _process_error(self, output: str) -> dict[str, Any]:
        diagnostic = (output or "平台搜索失败").strip()
        dependency = re.search(r"No module named ['\"]([^'\"]+)", diagnostic)
        if dependency:
            return self._error(
                "SYSTEM_DEPENDENCY_MISSING",
                f"缺少搜索依赖: {dependency.group(1)}",
                False,
            )
        lowered = diagnostic.lower()
        if any(marker in lowered for marker in ("cookie", "login required", "需要登录", "未登录", "unauthorized")):
            return self._error("AUTH_REQUIRED", self._last_relevant_line(diagnostic, ("cookie", "login", "认证", "未登录")), False)
        if any(marker in lowered for marker in ("captcha", "验证码", "安全验证", "risk control", "风控", "http 412")):
            return self._error("SEARCH_BLOCKED", self._last_relevant_line(diagnostic, ("captcha", "验证码", "安全验证", "风控", "412")), True)
        if any(marker in lowered for marker in ("timed out", "timeout", "超时")):
            return self._error("NETWORK_TIMEOUT", self._last_relevant_line(diagnostic, ("timeout", "timed out", "超时")), True)
        return self._error("SEARCH_EXECUTION_FAILED", self._last_line(diagnostic), False)

    @staticmethod
    def _last_line(message: str) -> str:
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        return (lines[-1] if lines else "平台搜索失败")[:500]

    @staticmethod
    def _last_relevant_line(message: str, markers: tuple[str, ...]) -> str:
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        for line in reversed(lines):
            lowered = line.lower()
            if any(marker in lowered for marker in markers):
                return line[:500]
        return CLISearchAdapter._last_line(message)

    def _normalize_response(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return self._error("PARSE_FORMAT_NOT_SUPPORTED", "搜索结果根节点不是 object", False)
        items = raw.get("results") or raw.get("candidates") or raw.get("items") or []
        results = []
        if isinstance(items, list):
            for item in items:
                normalized = self._normalize_resource(item)
                if normalized is not None:
                    results.append(normalized)
        error = self._normalize_error(raw.get("error"))
        if not error and isinstance(raw.get("errors"), list) and raw["errors"]:
            error = self._normalize_error(raw["errors"][0])
        return {"results": results, "error": error}

    def _normalize_resource(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        platform = item.get("platform") or item.get("source_platform") or self.platform_name
        resource_id = item.get("resource_id") or item.get("id")
        title = self._clean_text(item.get("title"))
        source_url = item.get("source_url") or item.get("url")
        if resource_id and ":" not in str(resource_id):
            resource_id = f"{platform}:{resource_id}"
        if not all(isinstance(value, str) and value.strip() for value in (resource_id, platform, title, source_url)):
            return None
        result: dict[str, Any] = {
            "resource_id": resource_id,
            "platform": platform,
            "title": title,
            "source_url": source_url,
        }
        is_free = item.get("is_free")
        if is_free is None and isinstance(item.get("is_paid"), bool):
            is_free = not item["is_paid"]
        mapping = {
            "type": item.get("type") or item.get("resource_type"),
            "description": self._clean_text(item.get("description") or item.get("snippet")),
            "author": item.get("author") or item.get("provider"),
            "duration": item.get("duration"),
            "publish_time": item.get("publish_time") or item.get("created_at"),
            "is_free": is_free,
            "language": item.get("language"),
            "thumbnail_url": item.get("thumbnail_url") or item.get("cover_url"),
            "download_feasibility": item.get("download_feasibility"),
        }
        result.update({key: value for key, value in mapping.items() if value is not None and value != ""})
        allowed_signals = {
            "comments", "engine", "favorites", "is_verified", "lessons", "likes",
            "plays", "rank", "rating", "shares", "tracks_count", "views",
        }
        source_signals = item.get("platform_signals") or {}
        signals = {
            key: value for key, value in source_signals.items()
            if key in allowed_signals and value is not None
        } if isinstance(source_signals, dict) else {}
        for source, target in (
            ("view_count", "views"), ("play_count", "views"),
            ("like_count", "likes"), ("comment_count", "comments"),
            ("tracks_count", "tracks_count"), ("lessons_count", "lessons"),
            ("is_verified_anchor", "is_verified"),
        ):
            if item.get(source) is not None and target not in signals:
                signals[target] = item[source]
        if signals:
            result["platform_signals"] = signals
        raw_metadata = self._compact_raw_metadata(item.get("raw_metadata") or item.get("raw"))
        if isinstance(raw_metadata, dict) and raw_metadata:
            result["raw_metadata"] = raw_metadata
        return result

    @staticmethod
    def _clean_text(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = re.sub(r"<[^>]+>", " ", unescape(value))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.lstrip("-> ")

    @staticmethod
    def _compact_raw_metadata(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        # Legacy platform CLIs often place the complete response under `raw`.
        # Stage 3 only keeps stable identifiers needed to reopen the resource.
        allowed = {
            "bid", "bvid", "catalog", "category_id", "core", "detail_page",
            "mid", "pid", "rank", "search_method", "smartedu_catalog",
            "sub_catalog", "video_id",
            "doc_id", "file_type", "page_num", "sell_type", "quality_score",
            "download_count", "source_id", "baiduwenku_scene",
            "site", "ar_id", "classify", "business_type", "keywords", "query",
            "scope", "data_source", "source_database", "publisher",
            "document_type", "isbn", "file_path",
        }
        return {
            key: value
            for key, value in raw.items()
            if key in allowed and isinstance(value, (str, int, float, bool))
        }

    @staticmethod
    def _normalize_error(error: Any) -> dict[str, Any] | None:
        if not isinstance(error, dict):
            return None
        message = error.get("message") or error.get("error_message") or "平台搜索失败"
        lowered = str(message).lower()
        code = error.get("error_code") or error.get("code")
        retryable = bool(error.get("retryable", error.get("can_retry", False)))
        if not code and any(marker in lowered for marker in ("captcha", "验证码", "安全验证", "searchblockederror")):
            code = "SEARCH_BLOCKED"
            retryable = True
        return {
            "error_code": code or "SEARCH_EXECUTION_FAILED",
            "message": message,
            "retryable": retryable,
        }

    @staticmethod
    def _error(code: str, message: str, retryable: bool) -> dict[str, Any]:
        return {"results": [], "error": {"error_code": code, "message": message, "retryable": retryable}}
