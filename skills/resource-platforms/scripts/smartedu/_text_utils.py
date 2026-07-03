#!/usr/bin/env python3
"""SmartEdu 纯文本与 URL 工具。

Phase 3E 从 smartedu_resources.py 拆出的底层工具模块：字符串归一化、HTML 清洗、
短 ID、URL 拼接/扩展/编码、字典取值。无副作用、无 SmartEdu 业务依赖，仅依赖标准库。
smartedu_resources.py 通过 import 复用，行为与拆分前完全一致。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any


def norm(value: Any) -> str:
    return str(value or "").strip()


def load_json(path: str) -> Any:
    """读取 JSON 文件；'-' 读 stdin。通用工具，主文件和各域模块共用。"""
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean_html_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return norm(re.sub(r"\s+", " ", text))


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def absolute_url(base_url: str, url: str) -> str:
    return urllib.parse.urljoin(base_url, html.unescape(url))


def resource_extension(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
    return "jpg" if suffix == "jpeg" else suffix


# 已知学习资源文件扩展名集合（search 域和 page 域共用，故放底层工具模块）。
RESOURCE_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "json", "srt", "superboard", "jpg", "jpeg", "png", "webp", "gif", "mp3", "wav", "m4a", "mp4", "mov", "m3u8", "zip", "rar", "7z"}


def quote_url_path(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/:")
    return urllib.parse.urlunparse(parsed._replace(path=path))


def first_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""
