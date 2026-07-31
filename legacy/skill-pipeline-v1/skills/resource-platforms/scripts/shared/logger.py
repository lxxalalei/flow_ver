"""shared.logger — 统一日志模块。

提供 ``getLogger()`` 工厂函数，各平台脚本用它获取带平台前缀的 logger。

核心特性
========

1. **统一日志格式**::

       [时间] [级别] [模块] 消息内容

   即 ``%(asctime)s [%(levelname)s] [%(name)s] %(message)s``。

2. **统一日志级别规范**（详见 ``logging-convention.md``）::

       DEBUG     — 调试信息（详细变量值、内部状态）
       INFO      — 正常流程（启动、搜索完成、下载进度）
       WARNING   — 降级 / 可恢复异常（CDP 不可用→独立模式、API 限流退避）
       ERROR     — 操作失败（单条下载失败、API 报错），流程继续
       CRITICAL  — 系统级故障（熔断、核心依赖缺失），流程终止

3. **敏感信息脱敏**：``SanitizingFilter`` 自动检测并遮掩
   Cookie、Token、密码等字段，防止泄露到日志。

4. **日志轮转**：支持按大小（``RotatingFileHandler``）
   和按日期（``TimedRotatingFileHandler``）轮转，
   通过 ``config/settings.yaml`` 的 ``log`` 段配置。

5. **配置集成**：自动读取 ``shared/config_loader.py`` 单例配置，
   优先级：环境变量 ``LRS_LOG__*`` > 配置文件 > 代码默认值。

用法
====

::

    from shared.logger import getLogger

    log = getLogger("bilibili")
    log.info("搜索第 %d 页...", page_num)
    log.warning("CDP 端口 %s 不可用 → 独立模式", port)

所有日志输出到 **stderr**，不影响 stdout 上的 JSON 结果管道。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════
#  默认配置常量
# ═══════════════════════════════════════════════════════════════

_DEFAULT_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_LEVEL = "INFO"
_DEFAULT_OUTPUT = "stderr"          # stderr / file / both
_DEFAULT_FILE_PATH = "./logs/lrs.log"
_DEFAULT_MAX_SIZE_MB = 10
_DEFAULT_BACKUP_COUNT = 5
_DEFAULT_ROTATE_BY = "size"         # size / time
_DEFAULT_ROTATE_WHEN = "midnight"   # TimedRotatingFileHandler: midnight / h / d 等

_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}


# ═══════════════════════════════════════════════════════════════
#  敏感信息脱敏过滤器
# ═══════════════════════════════════════════════════════════════

class SanitizingFilter(logging.Filter):
    """敏感信息脱敏过滤器。

    自动检测日志消息中的敏感字段（Cookie、Token、密码、密钥等）
    并将值替换为 ``***REDACTED***``，防止泄露到日志文件。

    检测规则（大小写不敏感）::

        cookie=xxx       → cookie=***REDACTED***
        token: "xxx"     → token: "***REDACTED***"
        password=xxx     → password=***REDACTED***
        Authorization: Bearer xxx → Authorization: Bearer ***REDACTED***
        set-cookie: xxx  → set-cookie: ***REDACTED***

    以及 ``SESSDATA=xxx``、``bili_jct=xxx``、``SUB=xxx``、``z_c0=xxx``
    等平台专用凭证字段。
    """

    # 敏感键名（用于 key=value / key: value 模式匹配）
    _SENSITIVE_KEYS: tuple[str, ...] = (
        "cookie", "cookies", "set-cookie", "set_cookie",
        "token", "access_token", "refresh_token", "auth_token",
        "msToken", "mstoken", "ttwid", "webid",
        "password", "passwd", "pwd",
        "secret", "api_key", "apikey", "api-key",
        "authorization", "auth",
        # 平台专用凭证
        "SESSDATA", "bili_jct", "DedeUserID",
        "SUB", "SUBP", "sslvk",
        "z_c0", "d_c0",
        "sessionid", "session_id",
        "access-token", "acw_tc",
        "ndvideo-key",
    )

    # 预编译正则：匹配 key=value 或 key: value 或 key: "value"
    # value 可以是引号包裹或裸文本（到下一个空白/引号/逗号/分号为止）
    _PATTERNS: list[re.Pattern[str]]

    def __init__(self) -> None:
        super().__init__()
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """为每个敏感键编译匹配正则。"""
        self._PATTERNS = []
        for key in self._SENSITIVE_KEYS:
            escaped = re.escape(key)
            # 模式1: key=value 或 key=value; 或 key=value,
            # 匹配等号后的裸值（到空白/分号/逗号/引号结束）
            p1 = re.compile(
                rf"({escaped}\s*[:=]\s*)([^\s;,\"'\]]+)",
                re.IGNORECASE,
            )
            # 模式2: key: "value" 或 key: 'value'（引号包裹的值）
            p2 = re.compile(
                rf'({escaped}\s*[:=]\s*)("[^"]*"|\'[^\']*\')',
                re.IGNORECASE,
            )
            self._PATTERNS.append((p1, p2))

    def filter(self, record: logging.LogRecord) -> bool:
        """对日志记录的消息进行脱敏处理。"""
        # Third-party libraries commonly keep secrets in formatting args
        # (for example httpx logs a complete signed URL as ``%s``). Sanitize
        # the fully rendered message rather than only the format template.
        sanitized = record.getMessage()
        for p1, p2 in self._PATTERNS:
            # 先处理引号包裹的值
            sanitized = p2.sub(r'\1"***REDACTED***"', sanitized)
            # 再处理裸值
            sanitized = p1.sub(r"\1***REDACTED***", sanitized)

        record.msg = sanitized
        record.args = None

        return True


# ═══════════════════════════════════════════════════════════════
#  配置加载
# ═══════════════════════════════════════════════════════════════

def _load_log_config() -> dict[str, Any]:
    """从 config_loader 读取 log 配置段（安全降级）。

    优先级：环境变量（LRS_LOG__*，由 config_loader 自动处理）
    > 配置文件 > 代码默认值。
    """
    defaults: dict[str, Any] = {
        "level": _DEFAULT_LEVEL,
        "output": _DEFAULT_OUTPUT,
        "file_path": _DEFAULT_FILE_PATH,
        "max_size_mb": _DEFAULT_MAX_SIZE_MB,
        "backup_count": _DEFAULT_BACKUP_COUNT,
        "rotate_by": _DEFAULT_ROTATE_BY,
        "rotate_when": _DEFAULT_ROTATE_WHEN,
        "format": _DEFAULT_FORMAT,
        "datefmt": _DEFAULT_DATEFMT,
    }
    try:
        from shared.config_loader import get_config
        cfg = get_config()
        log_cfg = cfg.get_log_config()
        if isinstance(log_cfg, dict):
            defaults.update(log_cfg)
    except Exception:
        # 配置加载失败时使用默认值（不阻断日志初始化）
        pass
    return defaults


def _resolve_level(level_str: str) -> int:
    """将字符串日志级别转为 logging 常量。"""
    if isinstance(level_str, int):
        return level_str
    return _LEVEL_MAP.get(str(level_str).upper(), logging.INFO)


def _resolve_file_path(raw_path: str) -> Path:
    """将日志文件路径解析为绝对路径（相对路径基于项目根）。"""
    p = Path(raw_path)
    if p.is_absolute():
        return p
    project_root = Path(__file__).resolve().parent.parent
    return project_root / raw_path


# ═══════════════════════════════════════════════════════════════
#  核心初始化
# ═══════════════════════════════════════════════════════════════

_CONFIGURED = False
_SANITIZER: SanitizingFilter | None = None


def _get_sanitizer() -> SanitizingFilter:
    """获取全局脱敏过滤器单例。"""
    global _SANITIZER
    if _SANITIZER is None:
        _SANITIZER = SanitizingFilter()
    return _SANITIZER


def configure_logging(
    *,
    level: str | int | None = None,
    output: str | None = None,
    file_path: str | Path | None = None,
    format_str: str | None = None,
    datefmt: str | None = None,
    max_size_mb: int | None = None,
    backup_count: int | None = None,
    rotate_by: str | None = None,
    rotate_when: str | None = None,
) -> None:
    """显式配置（或重新配置）全局日志。

    所有参数可选，传 None 时从配置文件读取默认值。
    通常不需要手动调用——首次 ``getLogger()`` 会自动初始化。
    """
    global _CONFIGURED

    cfg = _load_log_config()

    # 合并显式参数
    level_val = _resolve_level(level) if level is not None else _resolve_level(cfg["level"])
    output_val = (output or cfg["output"]).lower()
    fmt = format_str or cfg["format"]
    dtfmt = datefmt or cfg["datefmt"]
    max_sz = max_size_mb if max_size_mb is not None else int(cfg["max_size_mb"])
    backup = backup_count if backup_count is not None else int(cfg["backup_count"])
    rotate = (rotate_by or cfg.get("rotate_by", _DEFAULT_ROTATE_BY)).lower()
    when = rotate_when or cfg.get("rotate_when", _DEFAULT_ROTATE_WHEN)

    # 格式化器
    formatter = logging.Formatter(fmt=fmt, datefmt=dtfmt)

    # 脱敏过滤器
    sanitizer = _get_sanitizer()

    # 清理 root logger 上可能残留的 handler（防止重复输出）
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(level_val)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # ── stderr handler（默认） ──────────────────────────
    if output_val in ("stderr", "both"):
        sh = logging.StreamHandler(stream=sys.stderr)
        sh.setFormatter(formatter)
        sh.addFilter(sanitizer)
        root.addHandler(sh)

    # ── file handler（含轮转） ──────────────────────────
    if output_val in ("file", "both"):
        fpath = _resolve_file_path(str(file_path)) if file_path else _resolve_file_path(cfg["file_path"])
        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)

            if rotate == "time":
                fh: logging.Handler = logging.handlers.TimedRotatingFileHandler(
                    filename=str(fpath),
                    when=when,
                    interval=1,
                    backupCount=backup,
                    encoding="utf-8",
                )
            else:
                # 默认按大小轮转
                max_bytes = max_sz * 1024 * 1024
                fh = logging.handlers.RotatingFileHandler(
                    filename=str(fpath),
                    maxBytes=max_bytes,
                    backupCount=backup,
                    encoding="utf-8",
                )

            fh.setFormatter(formatter)
            fh.addFilter(sanitizer)
            root.addHandler(fh)
        except OSError:
            # 文件不可写时回退到 stderr
            if output_val == "file":
                sh = logging.StreamHandler(stream=sys.stderr)
                sh.setFormatter(formatter)
                sh.addFilter(sanitizer)
                root.addHandler(sh)

    _CONFIGURED = True


def _ensure_configured() -> None:
    """首次调用时自动初始化日志配置。"""
    if _CONFIGURED:
        return
    configure_logging()


def getLogger(name: str) -> logging.Logger:
    """获取带平台名称前缀的 logger。

    所有日志输出到 stderr（默认），不影响 stdout 的 JSON 结果管道。
    敏感信息自动脱敏。

    Args:
        name: 模块/平台名称（如 ``"bilibili"``、``"smartedu"``）。

    Returns:
        配置好的 ``logging.Logger`` 实例。
    """
    _ensure_configured()
    return logging.getLogger(f"platform.{name}")


# ═══════════════════════════════════════════════════════════════
#  便捷函数：手动脱敏（用于非 logging 场景）
# ═══════════════════════════════════════════════════════════════

def sanitize(text: str) -> str:
    """对任意字符串进行敏感信息脱敏。

    用于非 logging 场景（如写入文件、输出到 stdout 前的脱敏）。

    Args:
        text: 待脱敏的字符串。

    Returns:
        脱敏后的字符串。
    """
    sanitizer = _get_sanitizer()
    result = text
    for p1, p2 in sanitizer._PATTERNS:
        result = p2.sub(r'\1"***REDACTED***"', result)
        result = p1.sub(r"\1***REDACTED***", result)
    return result
