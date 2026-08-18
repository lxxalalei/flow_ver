"""Secure local session storage and platform login metadata.

Browser interaction belongs to the OpenClaw host. This module accepts broad
browser cookies and same-origin Web Storage snapshots, extracts only the selected
platform's required credentials, persists that canonical minimum with protected
local storage, and never exposes credential values in public results.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Literal, Protocol
from urllib.error import URLError
from urllib.parse import urlparse

from .http_client import probe_with_cookies, probe_with_headers
from .windows_dpapi import WindowsDpapiError, WindowsDpapiProtector


AuthKind = Literal["cookie", "token", "none"]
CaptureMethod = Literal["browser_cookies", "browser_storage", "none"]
PROBE_TIMEOUT = 10.0
MAX_SESSION_BYTES = 1024 * 1024
MAX_COOKIE_COUNT = 128
MAX_CAPTURE_COOKIE_COUNT = MAX_COOKIE_COUNT * 4
MAX_COOKIE_NAME = 256
MAX_COOKIE_VALUE = 16 * 1024
MAX_TOKEN_VALUE = 64 * 1024
MAX_STORAGE_ENTRY_COUNT = 512
MAX_STORAGE_KEY = 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_STORED_RECORD_BYTES = MAX_RECORD_BYTES * 2
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SMARTEDU_STORAGE_KEY_RE = re.compile(
    r"^ND_UC_AUTH-[^&\s]{1,256}&ncet-xedu&token$"
)
_SMARTEDU_COOKIE_NAME_RE = re.compile(
    r"^UC_TOKEN-[A-Za-z0-9._:-]{1,256}-ncet-xedu$"
)
_FORBIDDEN_FIELDS = {"password", "passwd", "pwd", "username", "user_name"}
_CAPTURE_FIELDS = {
    "cookies",
    "tokens",
    "storage_origin",
    "local_storage",
    "session_storage",
}
_COOKIE_FIELDS = {
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
    "partitionKey",
}


class SessionError(ValueError):
    """Expected business validation error with a stable public code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CredentialProtector(Protocol):
    """Byte protection interface used by native Windows and security tests."""

    format_name: str

    def protect(self, plaintext: bytes, *, purpose: str) -> bytes: ...

    def unprotect(self, ciphertext: bytes, *, purpose: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PlatformConfig:
    platform_id: str
    label: str
    login_url: str
    auth_kind: AuthKind
    capture_method: CaptureMethod
    cookie_domains: tuple[str, ...] = ()
    storage_keys: tuple[str, ...] = ()
    storage_key_patterns: tuple[str, ...] = ()
    required_storage_keys: tuple[str, ...] = ()
    probe_url: str | None = None

    @property
    def probe_supported(self) -> bool:
        return bool(self.probe_url)

    def public_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "platform": self.platform_id,
            "label": self.label,
            "requires_login": self.auth_kind != "none",
            "auth_kind": self.auth_kind,
            "login_url": self.login_url or None,
            "capture_method": self.capture_method,
            "probe_supported": self.probe_supported,
        }
        if self.cookie_domains:
            result["cookie_domains"] = list(self.cookie_domains)
        if self.storage_keys:
            result["storage_keys"] = list(self.storage_keys)
        if self.storage_key_patterns:
            result["storage_key_patterns"] = list(self.storage_key_patterns)
        return result


_PLATFORM_LIST = [
    PlatformConfig(
        "douyin",
        "抖音",
        "https://www.douyin.com/",
        "cookie",
        "browser_cookies",
        cookie_domains=("douyin.com",),
        storage_keys=("xmst",),  # msToken lives in localStorage under "xmst"
    ),
    PlatformConfig(
        "bilibili",
        "B站",
        "https://passport.bilibili.com/login",
        "cookie",
        "browser_cookies",
        cookie_domains=("bilibili.com",),
        probe_url="https://api.bilibili.com/x/web-interface/nav",
    ),
    PlatformConfig(
        "zhihu",
        "知乎",
        "https://www.zhihu.com/signin",
        "cookie",
        "browser_cookies",
        cookie_domains=("zhihu.com",),
        probe_url="https://www.zhihu.com/api/v4/me",
    ),
    PlatformConfig(
        "smartedu",
        "智慧教育",
        "https://basic.smartedu.cn/",
        "token",
        "browser_storage",
        cookie_domains=("smartedu.cn",),
        storage_keys=("accessToken", "x-nd-auth"),
        storage_key_patterns=("ND_UC_AUTH-*&ncet-xedu&token",),
        required_storage_keys=("accessToken",),
    ),
    PlatformConfig(
        "open163",
        "网易公开课",
        "https://open.163.com/",
        "cookie",
        "browser_cookies",
        cookie_domains=("163.com",),
    ),
    PlatformConfig(
        "wechat",
        "微信公众号",
        "https://weixin.sogou.com/",
        "cookie",
        "browser_cookies",
        cookie_domains=("sogou.com",),
    ),
    PlatformConfig(
        "weibo",
        "微博",
        "https://passport.weibo.com/sso/signin",
        "cookie",
        "browser_cookies",
        cookie_domains=("weibo.com", "sina.com.cn"),
    ),
    PlatformConfig(
        "ximalaya",
        "喜马拉雅",
        "https://www.ximalaya.com/login",
        "cookie",
        "browser_cookies",
        cookie_domains=("ximalaya.com",),
    ),
    PlatformConfig(
        "baiduwenku",
        "百度文库",
        "https://wenku.baidu.com/",
        "cookie",
        "browser_cookies",
        cookie_domains=("baidu.com",),
    ),
    PlatformConfig(
        "nlc",
        "国家图书馆",
        "https://read.nlc.cn/",
        "cookie",
        "browser_cookies",
        cookie_domains=("nlc.cn",),
    ),
    PlatformConfig("annas-archive", "安娜的档案", "", "none", "none"),
    PlatformConfig("cctv", "央视网", "", "none", "none"),
    PlatformConfig("kepu", "科普中国", "", "none", "none"),
    PlatformConfig("yixi", "一席", "", "none", "none"),
    PlatformConfig("runoob", "菜鸟教程", "", "none", "none"),
]
PLATFORM_REGISTRY: dict[str, PlatformConfig] = {
    item.platform_id: item for item in _PLATFORM_LIST
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SessionError("SESSION_PAYLOAD_INVALID", f"{field_name} 必须是 ISO 8601 时间")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SessionError(
            "SESSION_PAYLOAD_INVALID", f"{field_name} 必须是合法 ISO 8601 时间"
        ) from exc
    if parsed.tzinfo is None:
        raise SessionError(
            "SESSION_PAYLOAD_INVALID", f"{field_name} 必须包含时区"
        )
    return parsed.astimezone(timezone.utc)


def _bilibili_probe_ok(status: int, body: str) -> bool:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False
    data = payload.get("data") if isinstance(payload, dict) else None
    return bool(isinstance(data, dict) and data.get("isLogin"))


def _status_2xx_ok(status: int, body: str) -> bool:
    return 200 <= status < 300


_PROBE_CHECKS: dict[str, Callable[[int, str], bool]] = {
    "bilibili": _bilibili_probe_ok,
}


def _smartedu_auth_headers(session_data: dict[str, Any]) -> dict[str, str]:
    tokens = session_data.get("tokens") or {}
    token = tokens.get("accessToken")
    if not token:
        return {}
    headers = {
        "Authorization": f"Bearer {token}",
        "accessToken": token,
    }
    if tokens.get("x-nd-auth"):
        headers["x-nd-auth"] = tokens["x-nd-auth"]
    return headers


_AUTH_HEADER_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, str]]] = {
    "smartedu": _smartedu_auth_headers,
}


@dataclass(slots=True)
class SessionStatus:
    config: PlatformConfig
    status: Literal["stored", "expired", "missing", "invalid", "not_required"]
    captured_at: str | None = None
    expires_at: str | None = None

    @property
    def platform(self) -> str:
        return self.config.platform_id

    @property
    def label(self) -> str:
        return self.config.label

    def to_dict(self) -> dict[str, Any]:
        result = self.config.public_metadata()
        result["status"] = self.status
        if self.captured_at is not None:
            result["captured_at"] = self.captured_at
        if self.expires_at is not None:
            result["expires_at"] = self.expires_at
        return result


class SessionStore:
    """File-backed credential store under a dedicated local data directory.

    POSIX systems enforce owner-only filesystem permissions. Native Windows
    additionally encrypts every credential record with current-user DPAPI.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        _credential_protector: CredentialProtector | None = None,
    ) -> None:
        self._credential_protector = _credential_protector
        if os.name == "nt" and self._credential_protector is None:
            try:
                self._credential_protector = WindowsDpapiProtector()
            except WindowsDpapiError as exc:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "无法初始化当前 Windows 用户的 DPAPI 安全存储",
                ) from exc
        if os.name == "nt" and self._credential_protector is None:
            raise SessionError(
                "SECURE_STORAGE_UNAVAILABLE",
                "原生 Windows 必须启用当前用户范围 DPAPI",
            )
        if os.name == "nt":
            try:
                self_test = b"openclaw-session-manager-dpapi-self-test"
                protected = self._credential_protector.protect(
                    self_test, purpose="self-test"
                )
                if (
                    self._credential_protector.unprotect(
                        protected, purpose="self-test"
                    )
                    != self_test
                ):
                    raise WindowsDpapiError("DPAPI self-test mismatch")
            except WindowsDpapiError as exc:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "当前 Windows 用户的 DPAPI 安全存储自检失败",
                ) from exc
        self.data_dir = data_dir.expanduser()
        if not self.data_dir.is_absolute():
            raise SessionError("UNSAFE_DATA_PATH", "SESSION_MANAGER_DATA_DIR 必须是绝对路径")
        if os.name == "nt" and str(self.data_dir).startswith(("\\\\", "//")):
            raise SessionError("UNSAFE_DATA_PATH", "Windows 凭据目录不能使用 UNC 网络路径")
        self.sessions_dir = self.data_dir / "sessions"
        self.operations_dir = self.data_dir / "idempotency"
        self.lock_path = self.data_dir / ".store.lock"
        self._lock = threading.RLock()
        self._reject_symlink_components(self.data_dir)
        self._secure_directory(self.data_dir)
        self._secure_directory(self.sessions_dir)
        self._secure_directory(self.operations_dir)

    @staticmethod
    def _is_link_or_reparse_point(path: Path) -> bool:
        try:
            if path.is_symlink():
                return True
            is_junction = getattr(path, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            return False
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
        return bool(attributes & reparse_flag)

    @classmethod
    def _reject_symlink_components(cls, path: Path) -> None:
        for component in (path, *path.parents):
            if cls._is_link_or_reparse_point(component):
                raise SessionError(
                    "UNSAFE_DATA_PATH",
                    f"拒绝使用包含符号链接或重解析点的目录：{component}",
                )

    @staticmethod
    def _verify_owner_only(path: Path, expected_mode: int) -> None:
        if os.name != "posix":
            return
        info = path.stat()
        actual = stat.S_IMODE(info.st_mode)
        if actual != expected_mode:
            raise SessionError(
                "UNSAFE_DATA_PATH",
                f"权限设置未生效：{path} 当前为 {oct(actual)}，要求 {oct(expected_mode)}",
            )
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise SessionError("UNSAFE_DATA_PATH", f"当前用户不拥有数据路径：{path}")

    @classmethod
    def _secure_directory(cls, path: Path) -> None:
        try:
            if cls._is_link_or_reparse_point(path):
                raise SessionError(
                    "UNSAFE_DATA_PATH", f"拒绝使用链接或重解析点目录：{path}"
                )
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not path.is_dir() or cls._is_link_or_reparse_point(path):
                raise SessionError(
                    "UNSAFE_DATA_PATH", f"数据目录不是安全的普通目录：{path}"
                )
            if os.name != "posix":
                return
            path.chmod(0o700)
            cls._verify_owner_only(path, 0o700)
        except SessionError:
            raise
        except OSError as exc:
            raise SessionError(
                "UNSAFE_DATA_PATH", f"无法创建或保护数据目录：{path}"
            ) from exc

    def _platform(self, platform: str) -> PlatformConfig:
        if not isinstance(platform, str) or not platform.strip():
            raise SessionError("UNKNOWN_PLATFORM", "platform 不能为空")
        normalized = platform.strip().lower()
        config = PLATFORM_REGISTRY.get(normalized)
        if config is None:
            raise SessionError(
                "UNKNOWN_PLATFORM",
                f"未知平台：{platform}；可用值：{', '.join(PLATFORM_REGISTRY)}",
            )
        return config

    def _path(self, platform: str) -> Path:
        return self.sessions_dir / f"{platform}.json"

    def _decode_record(
        self, encoded: bytes, *, sensitive: bool, purpose: str | None = None
    ) -> dict[str, Any] | None:
        try:
            outer = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if sensitive and self._credential_protector is not None:
            if purpose is None:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE", "加密凭据记录缺少用途绑定"
                )
            if not isinstance(outer, dict) or set(outer) != {"format", "ciphertext"}:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "凭据记录不是受支持的 Windows DPAPI 加密格式",
                )
            if outer.get("format") != self._credential_protector.format_name:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "凭据记录的加密格式与当前安全存储后端不匹配",
                )
            ciphertext = outer.get("ciphertext")
            if not isinstance(ciphertext, str):
                return None
            try:
                protected = base64.b64decode(ciphertext, validate=True)
                plaintext = self._credential_protector.unprotect(
                    protected, purpose=purpose
                )
                payload = json.loads(plaintext.decode("utf-8"))
            except (
                ValueError,
                binascii.Error,
                UnicodeDecodeError,
                json.JSONDecodeError,
                WindowsDpapiError,
            ) as exc:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "当前 Windows 用户无法解密本地 session 记录",
                ) from exc
            return payload if isinstance(payload, dict) else None
        return outer if isinstance(outer, dict) else None

    def _read(
        self,
        path: Path,
        *,
        sensitive: bool = False,
        purpose: str | None = None,
    ) -> dict[str, Any] | None:
        if self._is_link_or_reparse_point(path):
            raise SessionError("UNSAFE_DATA_PATH", f"拒绝读取链接或重解析点：{path}")
        if not path.exists():
            return None
        if not path.is_file():
            raise SessionError("UNSAFE_DATA_PATH", f"拒绝读取非普通文件：{path}")
        try:
            self._verify_owner_only(path, 0o600)
            limit = MAX_STORED_RECORD_BYTES if sensitive else MAX_RECORD_BYTES
            if path.stat().st_size > limit:
                return None
            return self._decode_record(
                path.read_bytes(), sensitive=sensitive, purpose=purpose
            )
        except SessionError:
            raise
        except OSError:
            return None

    def _encode_record(
        self,
        payload: dict[str, Any],
        *,
        sensitive: bool,
        purpose: str | None = None,
    ) -> bytes:
        plaintext = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if len(plaintext) > MAX_RECORD_BYTES:
            raise SessionError("SESSION_PAYLOAD_TOO_LARGE", "本地记录超过大小上限")
        if not sensitive or self._credential_protector is None:
            return plaintext
        if purpose is None:
            raise SessionError(
                "SECURE_STORAGE_UNAVAILABLE", "加密凭据记录缺少用途绑定"
            )
        try:
            protected = self._credential_protector.protect(
                plaintext, purpose=purpose
            )
        except WindowsDpapiError as exc:
            raise SessionError(
                "SECURE_STORAGE_UNAVAILABLE",
                "Windows DPAPI 无法加密本地 session 记录",
            ) from exc
        envelope = {
            "format": self._credential_protector.format_name,
            "ciphertext": base64.b64encode(protected).decode("ascii"),
        }
        encoded = json.dumps(envelope, ensure_ascii=True, indent=2).encode("ascii")
        if len(encoded) > MAX_STORED_RECORD_BYTES:
            raise SessionError("SESSION_PAYLOAD_TOO_LARGE", "加密后的本地记录超过大小上限")
        return encoded

    def _atomic_write(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        sensitive: bool = False,
        purpose: str | None = None,
    ) -> None:
        encoded = self._encode_record(
            payload, sensitive=sensitive, purpose=purpose
        )
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            if os.name == "posix":
                path.chmod(0o600)
                self._verify_owner_only(path, 0o600)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _is_expired(record: dict[str, Any]) -> bool:
        expires_at = record.get("expires_at")
        if not expires_at:
            return False
        try:
            return _parse_timestamp(expires_at, "expires_at") <= datetime.now(timezone.utc)
        except SessionError:
            return True

    @contextmanager
    def _process_lock(self):
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise SessionError("UNSAFE_DATA_PATH", "无法安全打开 session 存储锁文件") from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise SessionError("UNSAFE_DATA_PATH", "session 存储锁必须是普通文件")
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        actual = stat.S_IMODE(info.st_mode)
        owner_mismatch = (
            os.name == "posix"
            and hasattr(os, "geteuid")
            and info.st_uid != os.geteuid()
        )
        if (os.name == "posix" and actual != 0o600) or owner_mismatch:
            os.close(fd)
            raise SessionError("UNSAFE_DATA_PATH", "session 存储锁权限或所有者不安全")
        handle = os.fdopen(fd, "a+b", buffering=0)
        locked = False
        try:
            if os.name == "nt":  # pragma: no cover - Windows-specific
                import msvcrt

                if self.lock_path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                    os.fsync(handle.fileno())
                deadline = time.monotonic() + 10.0
                while True:
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise SessionError(
                                "UNSAFE_DATA_PATH", "session 存储锁获取超时"
                            ) from exc
                        time.sleep(0.05)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                locked = True
            yield
        finally:
            try:
                if locked and os.name == "nt":  # pragma: no cover - Windows-specific
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                elif locked:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _validated_record(
        self, config: PlatformConfig
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        path = self._path(config.platform_id)
        if self._is_link_or_reparse_point(path):
            raise SessionError("UNSAFE_DATA_PATH", f"拒绝读取链接或重解析点：{path}")
        if not path.exists():
            return "missing", None, None
        record = self._read(
            path,
            sensitive=True,
            purpose=f"session:{config.platform_id}",
        )
        if record is None:
            return "invalid", None, None
        if (
            record.get("platform") != config.platform_id
            or record.get("auth_kind") != config.auth_kind
            or not isinstance(record.get("session_data"), dict)
        ):
            return "invalid", record, None
        if self._is_expired(record):
            return "expired", record, None
        try:
            clean, _counts = self._sanitize_session_data(
                config, record["session_data"]
            )
        except SessionError as exc:
            state = "expired" if exc.code == "SESSION_EMPTY" else "invalid"
            return state, record, None
        return "stored", record, clean

    @staticmethod
    def _reject_forbidden_fields(value: Any, path: str = "session_data") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                if key_text.lower() in _FORBIDDEN_FIELDS:
                    raise SessionError(
                        "SESSION_PAYLOAD_INVALID",
                        f"{path}.{key_text} 不允许保存账号或密码字段",
                    )
                SessionStore._reject_forbidden_fields(child, f"{path}.{key_text}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                SessionStore._reject_forbidden_fields(child, f"{path}[{index}]")

    @staticmethod
    def _domain_matches(domain: str, allowed_domains: tuple[str, ...]) -> bool:
        normalized = domain.strip().lower().lstrip(".").rstrip(".")
        return any(
            normalized == allowed or normalized.endswith(f".{allowed}")
            for allowed in allowed_domains
        )

    @staticmethod
    def _validate_storage_map(source: str, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise SessionError("SESSION_PAYLOAD_INVALID", f"{source} 必须是对象")
        if len(value) > MAX_STORAGE_ENTRY_COUNT:
            raise SessionError(
                "SESSION_PAYLOAD_TOO_LARGE",
                f"{source} 最多允许 {MAX_STORAGE_ENTRY_COUNT} 项",
            )
        clean: dict[str, str] = {}
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > MAX_STORAGE_KEY
                or any(ord(char) < 32 or ord(char) == 127 for char in key)
            ):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID", f"{source} 含非法存储键"
                )
            if (
                not isinstance(item, str)
                or len(item) > MAX_TOKEN_VALUE
                or any(ord(char) == 0 for char in item)
            ):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID",
                    f"{source} 的存储值必须是字符串且不能过长",
                )
            clean[key] = item
        return clean

    @staticmethod
    def _validate_storage_origin(value: Any, config: PlatformConfig) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 2048:
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                "storage_origin 必须是当前浏览器页面的 HTTP(S) origin",
            )
        parsed = urlparse(value.strip())
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                "storage_origin 必须是当前浏览器页面的 HTTP(S) origin",
            )
        if not SessionStore._domain_matches(parsed.hostname, config.cookie_domains):
            raise SessionError(
                "SESSION_EMPTY",
                f"storage_origin 不属于 {config.label} 官方域名范围",
            )
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"

    @staticmethod
    def _validate_token_value(key: str, value: Any) -> str:
        if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_VALUE:
            raise SessionError(
                "SESSION_PAYLOAD_INVALID", f"tokens.{key} 必须是非空字符串且不能过长"
            )
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise SessionError(
                "SESSION_PAYLOAD_INVALID", f"tokens.{key} 含非法控制字符"
            )
        return value

    @staticmethod
    def _nested_string_fields(value: Any, names: set[str], depth: int = 0) -> dict[str, str]:
        if depth > 16:
            return {}
        found: dict[str, str] = {}
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str) and key in names and isinstance(child, str) and child:
                    found.setdefault(key, child)
                for nested_key, nested_value in SessionStore._nested_string_fields(
                    SessionStore._decode_json_container(child), names, depth + 1
                ).items():
                    found.setdefault(nested_key, nested_value)
        elif isinstance(value, list):
            for child in value:
                for nested_key, nested_value in SessionStore._nested_string_fields(
                    SessionStore._decode_json_container(child), names, depth + 1
                ).items():
                    found.setdefault(nested_key, nested_value)
        return found

    @staticmethod
    def _decode_json_container(child: Any) -> Any:
        """Descend through JSON-encoded string values inside a parsed document.

        Storage records may serialize an inner object as a JSON string inside
        the outer JSON (real SmartEdu capture, 2026-08-18); the token walker
        must parse those to reach credential fields.
        """
        if isinstance(child, (dict, list)):
            return child
        if isinstance(child, str) and child[:1] in ("{", "["):
            try:
                decoded = json.loads(child)
            except ValueError:
                return None
            return decoded if isinstance(decoded, (dict, list)) else None
        return None

    def _sanitize_cookie_payload(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        cookies = session_data.get("cookies")
        if not isinstance(cookies, list):
            raise SessionError(
                "SESSION_EMPTY", "浏览器捕获中没有可供平台提取的 Cookie"
            )
        if len(cookies) > MAX_CAPTURE_COOKIE_COUNT:
            raise SessionError(
                "SESSION_PAYLOAD_TOO_LARGE",
                f"浏览器捕获 cookies 最多允许 {MAX_CAPTURE_COOKIE_COUNT} 条",
            )

        discarded = 0
        retained_storage: dict[str, dict[str, str]] = {}
        for source in ("local_storage", "session_storage"):
            values = self._validate_storage_map(source, session_data.get(source))
            # Some platforms (douyin msToken in "xmst") need specific storage
            # keys on every API call; keep only what the config declares.
            if config.storage_keys and source == "local_storage":
                retained = {
                    key: value
                    for key, value in values.items()
                    if key in config.storage_keys
                }
                discarded += len(values) - len(retained)
                if retained:
                    retained_storage[source] = retained
            else:
                discarded += len(values)
        raw_tokens = session_data.get("tokens")
        if raw_tokens is not None:
            if not isinstance(raw_tokens, dict):
                raise SessionError("SESSION_PAYLOAD_INVALID", "tokens 必须是对象")
            discarded += len(raw_tokens)

        now_epoch = datetime.now(timezone.utc).timestamp()
        clean: list[dict[str, Any]] = []
        for index, cookie in enumerate(cookies):
            if not isinstance(cookie, dict):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID", f"cookies[{index}] 必须是对象"
                )
            domain = cookie.get("domain")
            if not isinstance(domain, str) or not domain.strip():
                discarded += 1
                continue
            if not self._domain_matches(domain, config.cookie_domains):
                discarded += 1
                continue
            if len(clean) >= MAX_COOKIE_COUNT:
                raise SessionError(
                    "SESSION_PAYLOAD_TOO_LARGE", f"目标域名 Cookie 最多允许 {MAX_COOKIE_COUNT} 条"
                )
            name = cookie.get("name")
            value = cookie.get("value")
            # 空名/非法名 cookie 是浏览器捕获序列化的常见垃圾（真实样本：CDP
            # Storage.getCookies 会返回 name 为空的条目）。它们不是凭据，
            # 按越域条目同样丢弃计数，而不是让整次保存失败。
            if not isinstance(name, str) or not name or len(name) > MAX_COOKIE_NAME:
                discarded += 1
                continue
            if not _COOKIE_NAME_RE.fullmatch(name):
                discarded += 1
                continue
            if not isinstance(value, str) or len(value) > MAX_COOKIE_VALUE:
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID", f"cookies[{index}].value 非法或过长"
                )
            if any(ord(char) < 32 or ord(char) == 127 or char == ";" for char in value):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID", f"cookies[{index}].value 含非法字符"
                )
            normalized_domain = domain.strip().lower()
            if len(normalized_domain) > 255 or any(
                ord(char) < 33 or ord(char) == 127 for char in normalized_domain
            ):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID", f"cookies[{index}].domain 非法"
                )
            raw_path = cookie.get("path", "/")
            if (
                not isinstance(raw_path, str)
                or not raw_path.startswith("/")
                or len(raw_path) > 1024
                or any(ord(char) < 32 or ord(char) == 127 for char in raw_path)
            ):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID", f"cookies[{index}].path 非法"
                )

            item: dict[str, Any] = {
                "name": name,
                "value": value,
                "domain": normalized_domain,
                "path": raw_path,
            }
            expires = cookie.get("expires")
            if expires is not None:
                if (
                    isinstance(expires, bool)
                    or not isinstance(expires, (int, float))
                    or not math.isfinite(expires)
                ):
                    raise SessionError(
                        "SESSION_PAYLOAD_INVALID", f"cookies[{index}].expires 必须是 Unix 秒数"
                    )
                if expires > 0 and expires <= now_epoch:
                    discarded += 1
                    continue
                item["expires"] = expires
            for flag in ("httpOnly", "secure"):
                if flag in cookie:
                    if not isinstance(cookie[flag], bool):
                        raise SessionError(
                            "SESSION_PAYLOAD_INVALID", f"cookies[{index}].{flag} 必须是布尔值"
                        )
                    item[flag] = cookie[flag]
            if "sameSite" in cookie:
                same_site = cookie["sameSite"]
                if not isinstance(same_site, str) or len(same_site) > 32:
                    raise SessionError(
                        "SESSION_PAYLOAD_INVALID", f"cookies[{index}].sameSite 非法"
                    )
                item["sameSite"] = same_site
            clean.append(item)

        if not clean:
            raise SessionError(
                "SESSION_EMPTY",
                f"没有属于 {config.label} 域名范围的有效 Cookie，未保存",
            )
        clean_result: dict[str, Any] = {"cookies": clean}
        for source, values in retained_storage.items():
            clean_result[source] = values
        return clean_result, {
            "stored_credential_count": len(clean) + sum(
                len(v) for v in retained_storage.values()
            ),
            "discarded_credential_count": discarded,
        }

    def _smartedu_storage_candidates(
        self, source_name: str, storage: dict[str, str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        candidates: dict[str, list[tuple[str, str]]] = {
            "accessToken": [],
            "x-nd-auth": [],
        }
        for key in ("accessToken", "x-nd-auth"):
            if storage.get(key):
                candidates[key].append(
                    (key, self._validate_token_value(key, storage[key]))
                )
        for storage_key, raw_value in storage.items():
            if not _SMARTEDU_STORAGE_KEY_RE.fullmatch(storage_key):
                continue
            try:
                decoded = json.loads(raw_value)
            except (TypeError, ValueError) as exc:
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID",
                    f"{source_name} 中匹配 SmartEdu 规则的存储项不是合法 JSON",
                ) from exc
            fields = self._nested_string_fields(
                decoded, {"access_token", "accessToken", "x-nd-auth"}
            )
            access_token = fields.get("access_token") or fields.get("accessToken")
            if access_token:
                candidates["accessToken"].append(
                    (
                        storage_key,
                        self._validate_token_value("accessToken", access_token),
                    )
                )
            if fields.get("x-nd-auth"):
                candidates["x-nd-auth"].append(
                    (
                        storage_key,
                        self._validate_token_value("x-nd-auth", fields["x-nd-auth"]),
                    )
                )

        selected: dict[str, str] = {}
        sources: dict[str, str] = {}
        for key, values in candidates.items():
            distinct = {value for _storage_key, value in values}
            if len(distinct) > 1:
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID",
                    f"{source_name} 中存在冲突的 SmartEdu {key} 候选",
                )
            if values:
                sources[key] = values[0][0]
                selected[key] = values[0][1]
        return selected, sources

    def _sanitize_smartedu_payload(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        local_storage = self._validate_storage_map(
            "local_storage", session_data.get("local_storage")
        )
        session_storage = self._validate_storage_map(
            "session_storage", session_data.get("session_storage")
        )
        if local_storage or session_storage:
            self._validate_storage_origin(session_data.get("storage_origin"), config)
        elif session_data.get("storage_origin") is not None:
            self._validate_storage_origin(session_data.get("storage_origin"), config)

        raw_tokens = session_data.get("tokens")
        if raw_tokens is None:
            tokens: dict[str, Any] = {}
        elif not isinstance(raw_tokens, dict):
            raise SessionError("SESSION_PAYLOAD_INVALID", "tokens 必须是对象")
        else:
            tokens = raw_tokens
            self._reject_forbidden_fields(tokens, "session_data.tokens")
            unknown = set(tokens) - set(config.storage_keys)
            if unknown:
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID",
                    f"tokens 含不支持字段：{', '.join(sorted(unknown))}",
                )

        cookies = session_data.get("cookies")
        if cookies is None:
            cookies = []
        if not isinstance(cookies, list):
            raise SessionError("SESSION_PAYLOAD_INVALID", "cookies 必须是数组")
        if len(cookies) > MAX_CAPTURE_COOKIE_COUNT:
            raise SessionError(
                "SESSION_PAYLOAD_TOO_LARGE",
                f"浏览器捕获 cookies 最多允许 {MAX_CAPTURE_COOKIE_COUNT} 条",
            )

        raw_count = len(tokens) + len(local_storage) + len(session_storage) + len(cookies)
        used_sources: set[tuple[str, str]] = set()
        extracted: dict[str, str] = {}

        for key in config.storage_keys:
            value = tokens.get(key)
            if value:
                extracted[key] = self._validate_token_value(key, value)
                used_sources.add(("tokens", key))

        local_candidates, local_sources = self._smartedu_storage_candidates(
            "local_storage", local_storage
        )
        session_candidates, session_sources = self._smartedu_storage_candidates(
            "session_storage", session_storage
        )
        for key in config.storage_keys:
            if key in extracted:
                continue
            if key in local_candidates:
                extracted[key] = local_candidates[key]
                used_sources.add(("local_storage", local_sources[key]))
            elif key in session_candidates:
                extracted[key] = session_candidates[key]
                used_sources.add(("session_storage", session_sources[key]))

        if "accessToken" not in extracted:
            now_epoch = datetime.now(timezone.utc).timestamp()
            for index, cookie in enumerate(cookies):
                if not isinstance(cookie, dict):
                    continue
                name = cookie.get("name")
                value = cookie.get("value")
                domain = cookie.get("domain")
                expires = cookie.get("expires")
                if (
                    isinstance(expires, (int, float))
                    and not isinstance(expires, bool)
                    and expires > 0
                    and expires <= now_epoch
                ):
                    continue
                if (
                    isinstance(name, str)
                    and _SMARTEDU_COOKIE_NAME_RE.fullmatch(name)
                    and isinstance(value, str)
                    and isinstance(domain, str)
                    and self._domain_matches(domain, config.cookie_domains)
                ):
                    extracted["accessToken"] = self._validate_token_value(
                        "accessToken", value
                    )
                    used_sources.add(("cookies", str(index)))
                    break

        missing = [key for key in config.required_storage_keys if not extracted.get(key)]
        if missing:
            raise SessionError(
                "SESSION_EMPTY", f"缺少必要存储项：{', '.join(missing)}"
            )
        clean = {key: extracted[key] for key in config.storage_keys if key in extracted}
        return {"tokens": clean}, {
            "stored_credential_count": len(clean),
            "discarded_credential_count": max(0, raw_count - len(used_sources)),
        }

    def _sanitize_token_payload(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        if config.platform_id == "smartedu":
            return self._sanitize_smartedu_payload(config, session_data)
        tokens = session_data.get("tokens")
        if not isinstance(tokens, dict):
            raise SessionError("SESSION_PAYLOAD_INVALID", "tokens 必须是对象")
        unknown = set(tokens) - set(config.storage_keys)
        if unknown:
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                f"tokens 含不支持字段：{', '.join(sorted(unknown))}",
            )
        missing = [key for key in config.required_storage_keys if not tokens.get(key)]
        if missing:
            raise SessionError(
                "SESSION_EMPTY", f"缺少必要存储项：{', '.join(missing)}"
            )
        clean = {
            key: self._validate_token_value(key, value)
            for key, value in tokens.items()
        }
        return {"tokens": clean}, {
            "stored_credential_count": len(clean),
            "discarded_credential_count": 0,
        }

    def _sanitize_session_data(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        if config.auth_kind == "none":
            raise SessionError("LOGIN_NOT_REQUIRED", f"{config.label} 不需要保存登录态")
        if not isinstance(session_data, dict):
            raise SessionError("SESSION_PAYLOAD_INVALID", "session_data 必须是对象")
        unknown = set(session_data) - _CAPTURE_FIELDS
        if unknown:
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                f"session_data 含不支持字段：{', '.join(sorted(unknown))}",
            )
        if not session_data:
            raise SessionError("SESSION_EMPTY", "浏览器捕获结果为空")
        try:
            raw_size = len(
                json.dumps(session_data, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        except (TypeError, ValueError) as exc:
            raise SessionError("SESSION_PAYLOAD_INVALID", "session_data 不是合法 JSON") from exc
        if raw_size > MAX_SESSION_BYTES:
            raise SessionError(
                "SESSION_PAYLOAD_TOO_LARGE",
                f"session_data 不能超过 {MAX_SESSION_BYTES} 字节",
            )
        if config.auth_kind == "cookie":
            return self._sanitize_cookie_payload(config, session_data)
        return self._sanitize_token_payload(config, session_data)

    @staticmethod
    def _validate_idempotency_key(idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise SessionError(
                "INVALID_IDEMPOTENCY_KEY",
                "idempotency_key 必须为 8-128 位字母、数字、点、下划线、冒号或连字符",
            )
        return idempotency_key

    def _run_idempotent(
        self,
        action: str,
        idempotency_key: str | None,
        fingerprint_payload: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        key = self._validate_idempotency_key(idempotency_key)
        if key is None:
            with self._lock, self._process_lock():
                return {**operation(), "idempotent_replay": False}

        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        operation_id = hashlib.sha256(f"{action}:{key}".encode("utf-8")).hexdigest()
        ledger_path = self.operations_dir / f"{operation_id}.json"
        with self._lock, self._process_lock():
            existing = self._read(ledger_path)
            if ledger_path.exists() and existing is None:
                raise SessionError("IDEMPOTENCY_CONFLICT", "幂等记录损坏")
            if existing is not None:
                if existing.get("fingerprint") != fingerprint:
                    raise SessionError(
                        "IDEMPOTENCY_CONFLICT",
                        "同一个 idempotency_key 已用于不同请求",
                    )
                result = existing.get("result")
                if not isinstance(result, dict):
                    raise SessionError("IDEMPOTENCY_CONFLICT", "幂等记录损坏")
                result_platform = str(result.get("platform", ""))
                current_path = self._path(result_platform)
                current = self._read(
                    current_path,
                    sensitive=True,
                    purpose=f"session:{result_platform}",
                )
                current_state = None
                if action == "save" and result_platform in PLATFORM_REGISTRY:
                    current_state, _record, _clean = self._validated_record(
                        PLATFORM_REGISTRY[result_platform]
                    )
                if action == "save" and (
                    current is None
                    or current_state != "stored"
                    or current.get("revision") != result.get("session_revision")
                ):
                    raise SessionError(
                        "IDEMPOTENCY_STALE",
                        "幂等保存记录对应的当前 session 已被删除或替换",
                    )
                if action == "delete" and current_path.exists():
                    raise SessionError(
                        "IDEMPOTENCY_STALE",
                        "幂等删除后平台已保存了新的 session",
                    )
                return {**result, "idempotent_replay": True}
            result = operation()
            self._atomic_write(
                ledger_path,
                {
                    "action": action,
                    "fingerprint": fingerprint,
                    "completed_at": _utc_now(),
                    "result": result,
                },
            )
            return {**result, "idempotent_replay": False}

    def login_guide(self, platform: str) -> dict[str, Any]:
        config = self._platform(platform)
        metadata = config.public_metadata()
        if config.auth_kind == "none":
            return {
                **metadata,
                "steps": [],
                "message": f"{config.label} 是公开来源，不需要登录或保存会话。",
            }
        capture_action = (
            "读取当前浏览器上下文可见的全部 Cookie，不在 Agent 侧预筛选；由 MCP 按平台域名提取并只保存需要项"
            if config.auth_kind == "cookie"
            else "读取当前浏览器上下文可见的全部 Cookie，以及当前官方站点的 localStorage/sessionStorage；不在 Agent 侧预筛选，由 MCP 按平台规则提取并最小保存"
        )
        return {
            **metadata,
            "steps": [
                {
                    "order": 1,
                    "action": "open_login_url",
                    "actor": "agent",
                    "requires_user_confirmation": False,
                },
                {
                    "order": 2,
                    "action": "user_login",
                    "actor": "user",
                    "requires_user_confirmation": True,
                    "message": "请用户自行完成登录；不要索取或代填账号、密码、验证码。",
                },
                {
                    "order": 3,
                    "action": config.capture_method,
                    "actor": "agent",
                    "requires_user_confirmation": False,
                    "message": capture_action,
                },
                {
                    "order": 4,
                    "action": "resource_session_save",
                    "actor": "agent",
                    "requires_user_confirmation": False,
                },
                {
                    "order": 5,
                    "action": "resource_session_status",
                    "actor": "agent",
                    "requires_user_confirmation": False,
                    "deep": config.probe_supported,
                },
            ],
            "security_notes": [
                "使用浏览器路径时，用户必须在浏览器中自行登录。",
                "不得索取或代填账号、密码、验证码、短信码或 MFA。",
                (
                    "用户主动提供合法 Cookie/Token，并明确指定平台、用途和保存授权时，只能"
                    "一次性直送 resource_session_save；不得与浏览器捕获混用或失败后自动重放。"
                ),
                "不要向用户或其他工具回显捕获到的凭据原文。",
                "浏览器捕获可以是宽范围输入，但 MCP 只持久化平台注册规则命中的最小凭据。",
            ],
        }

    def get_status(self, platforms: list[str] | None = None) -> list[SessionStatus]:
        if platforms is None or platforms == []:
            configs = list(PLATFORM_REGISTRY.values())
        else:
            if not isinstance(platforms, list):
                raise SessionError("INVALID_ARGUMENT", "platforms 必须是数组")
            configs = [self._platform(platform) for platform in platforms]

        results: list[SessionStatus] = []
        for config in configs:
            if config.auth_kind == "none":
                results.append(SessionStatus(config=config, status="not_required"))
                continue
            state, record, _clean = self._validated_record(config)
            results.append(
                SessionStatus(
                    config=config,
                    status=state,
                    captured_at=record.get("captured_at") if record else None,
                    expires_at=record.get("expires_at") if record else None,
                )
            )
        return results

    def get_session_data(self, platform: str) -> dict[str, Any] | None:
        config = self._platform(platform)
        if config.auth_kind == "none":
            return None
        with self._lock:
            state, _record, clean = self._validated_record(config)
            return clean if state == "stored" else None

    def validate(self, platform: str) -> dict[str, Any]:
        config = self._platform(platform)
        now = _utc_now()
        if config.auth_kind == "none":
            return {
                "platform": config.platform_id,
                "probe_status": "not_required",
                "probed_at": now,
                "detail": f"{config.label} 不需要登录",
            }
        state, record, clean_session_data = self._validated_record(config)
        if state == "missing":
            return {
                "platform": config.platform_id,
                "probe_status": "missing",
                "probed_at": now,
                "detail": "无已存储的 session",
            }
        if state in {"expired", "invalid"}:
            return {
                "platform": config.platform_id,
                "probe_status": "invalid",
                "probed_at": now,
                "detail": "session 已过期或本地记录无效",
            }
        if not config.probe_url:
            return {
                "platform": config.platform_id,
                "probe_status": "no_probe",
                "probed_at": now,
                "detail": f"{config.label} 暂无可靠探针，只能确认本地会话已保存且未过期",
            }

        session_data = clean_session_data or {}
        check = _PROBE_CHECKS.get(config.platform_id, _status_2xx_ok)
        try:
            if config.auth_kind == "token":
                builder = _AUTH_HEADER_BUILDERS.get(config.platform_id)
                headers = builder(session_data) if builder else {}
                if not headers:
                    return {
                        "platform": config.platform_id,
                        "probe_status": "invalid",
                        "probed_at": now,
                        "detail": f"{config.label} 已存储 session 中无可用 token",
                    }
                status, body = probe_with_headers(
                    config.probe_url, headers, timeout=PROBE_TIMEOUT
                )
            else:
                cookie_header = self._cookie_header(session_data, config.probe_url)
                if not cookie_header:
                    return {
                        "platform": config.platform_id,
                        "probe_status": "invalid",
                        "probed_at": now,
                        "detail": f"{config.label} 已存储 session 中无可用 Cookie",
                    }
                status, body = probe_with_cookies(
                    config.probe_url, cookie_header, timeout=PROBE_TIMEOUT
                )
        except (URLError, TimeoutError, OSError) as exc:
            detail = getattr(exc, "reason", str(exc))
            return {
                "platform": config.platform_id,
                "probe_status": "probe_error",
                "probed_at": now,
                "detail": f"探针请求失败：{detail}",
            }
        accepted = check(status, body)
        return {
            "platform": config.platform_id,
            "probe_status": "valid" if accepted else "invalid",
            "probed_at": now,
            "detail": (
                f"{config.label} session 有效（HTTP {status}）"
                if accepted
                else f"{config.label} session 被拒绝（HTTP {status}）"
            ),
        }

    @staticmethod
    def _cookie_header(session_data: dict[str, Any], request_url: str) -> str:
        parsed = urlparse(request_url)
        host = (parsed.hostname or "").lower()
        request_path = parsed.path or "/"
        secure_request = parsed.scheme.lower() == "https"
        now_epoch = datetime.now(timezone.utc).timestamp()
        candidates: list[tuple[int, str, str]] = []
        for cookie in session_data.get("cookies") or []:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            raw_domain = cookie.get("domain")
            cookie_path = cookie.get("path") or "/"
            if not all(isinstance(item, str) for item in (name, value, raw_domain, cookie_path)):
                continue
            normalized_domain = raw_domain.lower().lstrip(".")
            domain_match = (
                host == normalized_domain
                if not raw_domain.startswith(".")
                else host == normalized_domain or host.endswith(f".{normalized_domain}")
            )
            if not domain_match:
                continue
            path_match = request_path == cookie_path or (
                request_path.startswith(cookie_path)
                and (cookie_path.endswith("/") or request_path[len(cookie_path) :].startswith("/"))
            )
            if not path_match:
                continue
            if cookie.get("secure") and not secure_request:
                continue
            expires = cookie.get("expires")
            if isinstance(expires, (int, float)) and expires > 0 and expires <= now_epoch:
                continue
            candidates.append((len(cookie_path), name, value))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return "; ".join(f"{name}={value}" for _length, name, value in candidates)

    def save(
        self,
        platform: str,
        session_data: dict[str, Any],
        *,
        expires_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        config = self._platform(platform)
        clean_data, counts = self._sanitize_session_data(config, session_data)
        normalized_expires: str | None = None
        if expires_at is not None:
            parsed = _parse_timestamp(expires_at, "expires_at")
            if parsed <= datetime.now(timezone.utc):
                raise SessionError("SESSION_PAYLOAD_INVALID", "expires_at 必须晚于当前时间")
            normalized_expires = parsed.isoformat()

        def operation() -> dict[str, Any]:
            now = _utc_now()
            revision = uuid.uuid4().hex
            record = {
                "platform": config.platform_id,
                "revision": revision,
                "auth_kind": config.auth_kind,
                "session_data": clean_data,
                "captured_at": now,
                "updated_at": now,
                "expires_at": normalized_expires,
            }
            with self._lock:
                self._atomic_write(
                    self._path(config.platform_id),
                    record,
                    sensitive=True,
                    purpose=f"session:{config.platform_id}",
                )
            return {
                "platform": config.platform_id,
                "status": "stored",
                "auth_kind": config.auth_kind,
                "session_revision": revision,
                "captured_at": now,
                "expires_at": normalized_expires,
                **counts,
            }

        return self._run_idempotent(
            "save",
            idempotency_key,
            {
                "platform": config.platform_id,
                "session_data": clean_data,
                "expires_at": normalized_expires,
            },
            operation,
        )

    def delete(
        self, platform: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        config = self._platform(platform)

        def operation() -> dict[str, Any]:
            with self._lock:
                path = self._path(config.platform_id)
                existed = path.exists()
                if existed:
                    path.unlink()
            return {"platform": config.platform_id, "deleted": existed}

        return self._run_idempotent(
            "delete",
            idempotency_key,
            {"platform": config.platform_id},
            operation,
        )
