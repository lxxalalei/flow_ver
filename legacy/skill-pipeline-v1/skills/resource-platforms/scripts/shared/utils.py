"""shared.utils — 通用工具函数。"""

from __future__ import annotations

import re
from pathlib import Path


_WIN_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_SPACE = re.compile(r'\s+')


def safe_filename(name: str, max_length: int = 80) -> str:
    """将任意字符串转为安全的文件名。

    - 替换 Windows 非法字符为下划线
    - 合并连续空白为单个空格
    - 去除首尾空白和点号
    - 限制最大长度（默认 80 字符）
    - 空字符串返回 'untitled'
    """
    if not name or not name.strip():
        return "untitled"
    cleaned = _WIN_ILLEGAL.sub("_", name)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(".")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rsplit(" ", 0)[0].strip()
    return cleaned if cleaned else "untitled"
