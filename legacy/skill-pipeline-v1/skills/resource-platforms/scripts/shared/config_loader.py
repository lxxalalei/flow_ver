"""shared.config_loader — 统一配置加载器。

从 ``config/settings.yaml`` 读取项目配置，并支持环境变量覆盖。

环境变量覆盖规则：
  - 前缀 ``LRS_``（Learning Resource Suite）
  - 嵌套层级用双下划线 ``__`` 分隔
  - 自动类型推断：数字 → int/float，``true``/``false`` → bool

示例::

    LRS_LOG__LEVEL=DEBUG                      → log.level = "DEBUG"
    LRS_DOWNLOAD__OUTPUT_DIR=/data/dl         → download.output_dir = "/data/dl"
    LRS_PLATFORMS__BILIBILI__MIN_REQUEST_INTERVAL=2.0
                                             → platforms.bilibili.min_request_interval = 2.0
    LRS_DEFAULTS__RETRY_COUNT=5               → defaults.retry_count = 5

用法::

    from shared.config_loader import get_config, ConfigLoader

    # 方式一：单例（推荐，全局只加载一次）
    cfg = get_config()
    timeout = cfg.get("defaults.request_timeout", 120)
    interval = cfg.get_platform_param("bilibili", "min_request_interval", 1.5)

    # 方式二：显式实例（用于测试或自定义路径）
    loader = ConfigLoader("/custom/path/settings.yaml")
    val = loader.get("log.level", "INFO")
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# ── YAML 加载（优先 PyYAML，回退到内置实现） ─────────────────────

_yaml_available = False
try:
    import yaml as _yaml  # type: ignore

    _yaml_available = True
except ImportError:
    _yaml_available = False


def _parse_yaml(text: str) -> dict[str, Any]:
    """解析 YAML 文本为字典。

    优先使用 PyYAML；若未安装，使用内置的简易 YAML 解析器
    （支持缩进式 key: value、注释、列表）。
    """
    if _yaml_available:
        data = _yaml.safe_load(text)
        return data if isinstance(data, dict) else {}

    return _SimpleYAMLParser(text).parse()


class _SimpleYAMLParser:
    """简易 YAML 解析器（不依赖第三方库）。

    支持的语法子集：
      - 缩进式嵌套字典（2 空格缩进）
      - ``key: value`` 键值对（值自动类型推断）
      - ``# 注释``
      - 列表项 ``- item``（仅支持简单标量列表）
      - 空行忽略

    不支持：锚点、多行字符串、Flow Style、复杂引用。
    用于 settings.yaml 无 PyYAML 时的兜底。
    """

    _BOOL_TRUE = {"true", "yes", "on"}
    _BOOL_FALSE = {"false", "no", "off"}

    def __init__(self, text: str) -> None:
        # 去除注释行和尾部空行
        self._lines: list[tuple[int, str]] = []
        for raw_line in text.splitlines():
            stripped = raw_line.rstrip()
            if not stripped or stripped.lstrip().startswith("#"):
                continue
            # 去除行内注释（# 前有空格且不在引号内）
            stripped = self._strip_inline_comment(stripped)
            if not stripped:
                continue
            indent = len(stripped) - len(stripped.lstrip())
            self._lines.append((indent, stripped.lstrip()))
        self._pos = 0

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        """去除行内注释（# 前有空格，且不在引号内）。"""
        in_single = False
        in_double = False
        for i, ch in enumerate(line):
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "#" and not in_single and not in_double:
                if i > 0 and line[i - 1] in (" ", "\t"):
                    return line[:i].rstrip()
        return line

    def parse(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        self._parse_block(result, 0)
        return result

    def _parse_block(self, parent: dict[str, Any], min_indent: int) -> None:
        while self._pos < len(self._lines):
            indent, line = self._lines[self._pos]
            if indent < min_indent:
                break

            # 列表项
            if line.startswith("- "):
                # 简单标量列表，跳过（settings.yaml 目前不使用列表值）
                self._pos += 1
                continue

            if ":" not in line:
                self._pos += 1
                continue

            key, _, value_part = line.partition(":")
            key = key.strip()
            value_part = value_part.strip()

            self._pos += 1

            if value_part:
                # 叶子节点（有值）
                parent[key] = self._cast_value(value_part)
            else:
                # 子块（无值，期望缩进更大的子节点）
                child: dict[str, Any] = {}
                if self._pos < len(self._lines):
                    next_indent = self._lines[self._pos][0]
                    if next_indent > indent:
                        self._parse_block(child, next_indent)
                parent[key] = child

    def _cast_value(self, raw: str) -> Any:
        """将字符串值转为适当的 Python 类型。"""
        # 去引号
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            return raw[1:-1]

        low = raw.lower()
        if low in self._BOOL_TRUE:
            return True
        if low in self._BOOL_FALSE:
            return False

        # 整数
        try:
            return int(raw)
        except ValueError:
            pass

        # 浮点数
        try:
            return float(raw)
        except ValueError:
            pass

        return raw


# ═══════════════════════════════════════════════════════════════
#  ConfigLoader 核心类
# ═══════════════════════════════════════════════════════════════

# 环境变量前缀
_ENV_PREFIX = "LRS_"
# 层级分隔符（双下划线）
_ENV_SEP = "__"


class ConfigLoader:
    """统一配置加载器。

    从 YAML 文件加载配置，并叠加环境变量覆盖。

    线程安全（只读操作无需加锁，首次加载在模块级完成）。
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        env_prefix: str = _ENV_PREFIX,
    ) -> None:
        """初始化配置加载器。

        Args:
            config_path: settings.yaml 的路径。
                         传 None 时自动查找（见 _find_config_path()）。
            env_prefix: 环境变量前缀，默认 ``LRS_``。
        """
        self._env_prefix = env_prefix
        self._config_path: Path | None = None
        self._data: dict[str, Any] = {}

        if config_path is not None:
            self._config_path = Path(config_path)
        else:
            self._config_path = self._find_config_path()

        if self._config_path and self._config_path.exists():
            raw_text = self._config_path.read_text(encoding="utf-8")
            self._data = _parse_yaml(raw_text)

        # 叠加环境变量覆盖
        self._apply_env_overrides()

    # ── 路径查找 ──────────────────────────────────────────

    @staticmethod
    def _find_config_path() -> Path | None:
        """按优先级查找 settings.yaml。

        查找顺序：
          1. 环境变量 ``LRS_CONFIG_PATH``
          2. 项目根 ``config/settings.yaml``
             （项目根 = shared/ 的上一级目录）
          3. 当前工作目录 ``./config/settings.yaml``
        """
        # 环境变量
        env_path = os.environ.get("LRS_CONFIG_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return p

        # 项目根 config/settings.yaml
        project_root = Path(__file__).resolve().parent.parent
        candidates = [
            project_root / "config" / "settings.yaml",
            Path.cwd() / "config" / "settings.yaml",
        ]
        for cand in candidates:
            if cand.exists():
                return cand

        return None

    @property
    def config_path(self) -> Path | None:
        """当前加载的配置文件路径（未找到则为 None）。"""
        return self._config_path

    @property
    def has_config_file(self) -> bool:
        """是否成功加载了配置文件。"""
        return self._config_path is not None and self._config_path.exists()

    # ── 环境变量覆盖 ──────────────────────────────────────

    def _apply_env_overrides(self) -> None:
        """扫描所有 LRS_ 前缀的环境变量，叠加到配置树。"""
        prefix_upper = self._env_prefix.upper()
        for key, val in os.environ.items():
            if not key.startswith(prefix_upper):
                continue
            # 去掉前缀
            stripped = key[len(prefix_upper):]
            if not stripped:
                continue
            # 特殊：LRS_CONFIG_PATH 是加载器自身用的，跳过
            if stripped.upper() == "CONFIG_PATH":
                continue
            # 按双下划线分割层级
            parts = stripped.split(_ENV_SEP)
            # 全部转小写（YAML 键名约定为小写）
            parts = [p.lower() for p in parts if p]
            if not parts:
                continue
            self._set_nested(self._data, parts, self._cast_env_value(val))

    @staticmethod
    def _cast_env_value(raw: str) -> Any:
        """将环境变量字符串值转为适当的 Python 类型。"""
        low = raw.lower()
        if low in ("true", "yes", "on", "1"):
            # 注意："1" 在某些场景下应该是整数，但布尔语义更常见
            # 如果需要整数 1，用 LRS_XXX="1" 会被覆盖——这里优先 bool
            if low in ("true", "yes", "on"):
                return True
        if low in ("false", "no", "off"):
            return False
        # 整数
        try:
            return int(raw)
        except ValueError:
            pass
        # 浮点数
        try:
            return float(raw)
        except ValueError:
            pass
        return raw

    @staticmethod
    def _set_nested(
        data: dict[str, Any], keys: list[str], value: Any
    ) -> None:
        """递归设置嵌套字典值，沿途创建不存在的中间字典。"""
        node = data
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value

    # ── 公开查询接口 ──────────────────────────────────────

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """通过点分路径获取配置值。

        Args:
            dotted_key: 点分层级路径，如 ``"log.level"``、
                        ``"platforms.bilibili.min_request_interval"``
            default: 键不存在时返回的默认值

        Returns:
            配置值（自动类型），或 default
        """
        parts = dotted_key.split(".")
        node: Any = self._data
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def get_or_none(self, dotted_key: str) -> Any:
        """获取配置值，不存在返回 None。"""
        return self.get(dotted_key, None)

    def has(self, dotted_key: str) -> bool:
        """检查配置键是否存在。"""
        sentinel = object()
        return self.get(dotted_key, sentinel) is not sentinel

    def get_platform_config(self, platform_name: str) -> dict[str, Any]:
        """获取指定平台的完整配置（合并 defaults + 平台专属）。

        平台配置中未设置的键回退到 defaults 段。

        Args:
            platform_name: 平台名（如 ``"bilibili"``）

        Returns:
            合并后的配置字典
        """
        defaults = self.get("defaults", {})
        platform_cfg = self.get(f"platforms.{platform_name}", {})
        if not isinstance(defaults, dict):
            defaults = {}
        if not isinstance(platform_cfg, dict):
            platform_cfg = {}
        merged = dict(defaults)
        merged.update(platform_cfg)
        return merged

    def get_platform_param(
        self,
        platform_name: str,
        param_name: str,
        default: Any = None,
    ) -> Any:
        """获取指定平台的某个参数（自动回退到 defaults）。

        查找顺序：platforms.<name>.<param> → defaults.<param> → default

        Args:
            platform_name: 平台名
            param_name: 参数名（如 ``"min_request_interval"``）
            default: 完全找不到时的回退值

        Returns:
            参数值
        """
        platform_cfg = self.get_platform_config(platform_name)
        return platform_cfg.get(param_name, default)

    def get_platform_params_dict(self, platform_name: str) -> dict[str, Any]:
        """获取平台初始化参数（映射到 CLIBasedPlatformSkill.__init__）。

        将配置中的平台参数映射为 ``CLIBasedPlatformSkill.__init__`` 的
        keyword-only 参数，便于直接 ``**kwargs` 传入。

        Returns的键名与 __init__ 参数完全一致：
        - min_request_interval
        - failure_threshold (← circuit_breaker_failure_threshold)
        - recovery_timeout (← circuit_breaker_recovery_timeout)
        - enable_rate_limit
        - enable_circuit_breaker
        - request_timeout
        - download_timeout
        - retry_count
        """
        cfg = self.get_platform_config(platform_name)
        return {
            "min_request_interval": cfg.get("min_request_interval", 1.0),
            "failure_threshold": cfg.get(
                "circuit_breaker_failure_threshold", 5
            ),
            "recovery_timeout": cfg.get(
                "circuit_breaker_recovery_timeout", 300.0
            ),
            "enable_rate_limit": cfg.get("enable_rate_limit", True),
            "enable_circuit_breaker": cfg.get("enable_circuit_breaker", True),
            # 以下为扩展参数（基类可用但当前 __init__ 未直接消费，
            # 调度器/适配器可按需读取）
            "request_timeout": cfg.get("request_timeout", 120),
            "download_timeout": cfg.get("download_timeout", 600),
            "retry_count": cfg.get("retry_count", 2),
        }

    def get_download_dir(self) -> str:
        """获取下载目录路径（相对路径解析为项目根下的绝对路径）。"""
        raw = self.get("download.output_dir", "./downloads")
        if Path(raw).is_absolute():
            return raw
        project_root = Path(__file__).resolve().parent.parent
        return str(project_root / raw)

    def get_log_config(self) -> dict[str, Any]:
        """获取日志配置。"""
        return self.get("log", {})

    def get_search_config(self) -> dict[str, Any]:
        """获取搜索配置。"""
        return self.get("search", {})

    def dump(self) -> dict[str, Any]:
        """返回完整的配置树（调试用）。"""
        return dict(self._data)


# ═══════════════════════════════════════════════════════════════
#  模块级单例
# ═══════════════════════════════════════════════════════════════

_instance: ConfigLoader | None = None


def get_config() -> ConfigLoader:
    """获取全局 ConfigLoader 单例。

    首次调用时自动加载（延迟初始化）。
    后续调用直接返回缓存实例。
    """
    global _instance
    if _instance is None:
        _instance = ConfigLoader()
    return _instance


def reload_config(config_path: str | Path | None = None) -> ConfigLoader:
    """重新加载配置（用于测试或运行时热更新）。

    Args:
        config_path: 指定新配置路径，None 则重新查找。

    Returns:
        新的 ConfigLoader 实例
    """
    global _instance
    _instance = ConfigLoader(config_path)
    return _instance
