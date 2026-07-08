#!/usr/bin/env python3
"""Wechat public-account article search adapter."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from shared.search_adapter import CLISearchAdapter, SCRIPTS_DIR


class WechatSearchAdapter(CLISearchAdapter):
    """Run the Sogou Weixin article search script and normalize articles."""

    platform_name = "wechat"
    search_script = SCRIPTS_DIR / "wechat" / "search_wechat.js"
    timeout_seconds = 75

    def _build_search_cmd(self, query: str, max_results: int, params: dict[str, Any], output_file: Path) -> list[str] | None:
        if self.search_script is None or not self.search_script.is_file():
            return None
        node = str(params.get("node_binary") or os.environ.get("NODE_BINARY") or "node")
        if shutil.which(node) is None and not Path(node).is_file():
            return None
        limit = max(1, min(int(max_results or 10), 50))
        cmd = [node, str(self.search_script), query, "--num", str(limit), "--output", str(output_file)]
        if self._truthy(params.get("resolve_url") or params.get("resolve_real_url") or params.get("real_url")):
            cmd.append("--resolve-url")
        return cmd

    def _subprocess_env(self) -> dict[str, str]:
        env = super()._subprocess_env()
        node_options = env.get("NODE_OPTIONS", "")
        if "--use-system-ca" not in node_options:
            env["NODE_OPTIONS"] = f"{node_options} --use-system-ca".strip()
        return env

    def _normalize_response(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return self._error("PARSE_FORMAT_NOT_SUPPORTED", "微信搜索结果根节点不是 object", False)
        articles = raw.get("articles") or []
        if not isinstance(articles, list):
            return self._error("PARSE_FORMAT_NOT_SUPPORTED", "微信搜索结果缺少 articles[]", False)

        results = []
        for index, item in enumerate(articles, 1):
            normalized = self._normalize_article(item, raw.get("query"), index)
            if normalized is not None:
                results.append(normalized)

        return {"results": results, "error": self._normalize_error(raw.get("error"))}

    def _normalize_article(self, item: Any, query: Any, fallback_rank: int) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        title = self._clean_text(item.get("title"))
        source_url = item.get("url")
        if not isinstance(title, str) or not title or not isinstance(source_url, str) or not source_url:
            return None

        stable = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
        rank = item.get("rank") if isinstance(item.get("rank"), int) else fallback_rank
        result: dict[str, Any] = {
            "resource_id": f"wechat:{stable}",
            "platform": self.platform_name,
            "title": title,
            "source_url": source_url,
            "type": "文章",
            "download_feasibility": "低",
            "platform_signals": {"engine": "sogou-weixin", "rank": rank},
        }

        description = self._clean_text(item.get("summary"))
        if isinstance(description, str) and description:
            result["description"] = description
        source = self._clean_text(item.get("source"))
        if isinstance(source, str) and source:
            result["author"] = source
        if isinstance(item.get("datetime"), str) and item["datetime"]:
            result["publish_time"] = item["datetime"]

        raw_metadata: dict[str, Any] = {}
        if isinstance(query, str) and query:
            raw_metadata["query"] = query
        for key in ("date_text", "date_description", "url_resolved"):
            value = item.get(key)
            if isinstance(value, (str, bool)) and value != "":
                raw_metadata[key] = value
        if raw_metadata:
            result["raw_metadata"] = raw_metadata
        return result

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)

    def _process_error(self, output: str) -> dict[str, Any]:
        diagnostic = (output or "").strip()
        lowered = diagnostic.lower()
        if "search_blocked" in lowered or "antispider" in lowered or "captcha" in lowered:
            return self._error("SEARCH_BLOCKED", self._last_line(diagnostic), True)
        return super()._process_error(output)


ADAPTER = WechatSearchAdapter()
