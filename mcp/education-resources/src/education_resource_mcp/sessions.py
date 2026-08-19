"""Unified platform session storage used by the resource MCP.

The MCP accepts broad browser capture only at the public session tools, extracts
the small platform-specific credentials it actually needs, and stores only that
canonical subset. Resource adapters read the same SessionStore directly.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable, Literal
from urllib.error import URLError
from urllib.parse import urlparse

from .adapters.http_client import probe_with_cookies, probe_with_headers
from .errors import DomainError
from .windows_dpapi import WindowsDpapiError, WindowsDpapiProtector


AuthKind = Literal["cookie", "token", "none"]
CaptureMethod = Literal["browser_cookies", "browser_storage", "none"]
PROBE_TIMEOUT = 10.0
_SMARTEDU_STORAGE_KEY_RE = re.compile(r"^ND_UC_AUTH-[^&\s]+&ncet-xedu&token$")
_SMARTEDU_COOKIE_NAME_RE = re.compile(r"^UC_TOKEN-[A-Za-z0-9._:-]+-ncet-xedu$")


class SessionError(DomainError):
    """Expected session validation error returned through the normal MCP contract."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code=code, message=message, retryable=retryable)


@dataclass(frozen=True, slots=True)
class PlatformConfig:
    platform_id: str
    label: str
    login_url: str
    auth_kind: AuthKind
    capture_method: CaptureMethod
    cookie_domains: tuple[str, ...] = ()
    storage_keys: tuple[str, ...] = ()
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
        return result


_PLATFORM_LIST = [
    PlatformConfig(
        "douyin", "抖音", "https://www.douyin.com/", "cookie", "browser_cookies",
        cookie_domains=("douyin.com",), storage_keys=("xmst",),
    ),
    PlatformConfig(
        "bilibili", "B站", "https://passport.bilibili.com/login",
        "cookie", "browser_cookies", cookie_domains=("bilibili.com",),
        probe_url="https://api.bilibili.com/x/web-interface/nav",
    ),
    PlatformConfig(
        "zhihu", "知乎", "https://www.zhihu.com/signin",
        "cookie", "browser_cookies", cookie_domains=("zhihu.com",),
        probe_url="https://www.zhihu.com/api/v4/me",
    ),
    PlatformConfig(
        "smartedu", "智慧教育", "https://basic.smartedu.cn/",
        "token", "browser_storage", cookie_domains=("smartedu.cn",),
        storage_keys=("accessToken", "x-nd-auth"),
        required_storage_keys=("accessToken",),
    ),
    PlatformConfig(
        "open163", "网易公开课", "https://open.163.com/",
        "cookie", "browser_cookies", cookie_domains=("163.com",),
    ),
    PlatformConfig(
        "wechat", "微信公众号", "https://weixin.sogou.com/",
        "cookie", "browser_cookies", cookie_domains=("sogou.com",),
    ),
    PlatformConfig(
        "weibo", "微博", "https://passport.weibo.com/sso/signin",
        "cookie", "browser_cookies", cookie_domains=("weibo.com", "sina.com.cn"),
    ),
    PlatformConfig(
        "ximalaya", "喜马拉雅", "https://www.ximalaya.com/login",
        "cookie", "browser_cookies", cookie_domains=("ximalaya.com",),
    ),
    PlatformConfig(
        "baiduwenku", "百度文库", "https://wenku.baidu.com/",
        "cookie", "browser_cookies", cookie_domains=("baidu.com",),
    ),
    PlatformConfig(
        "nlc", "国家图书馆", "https://read.nlc.cn/",
        "cookie", "browser_cookies", cookie_domains=("nlc.cn",),
    ),
    PlatformConfig("annas-archive", "安娜的档案", "", "none", "none"),
    PlatformConfig("cctv", "央视网", "", "none", "none"),
    PlatformConfig("kepu", "科普中国", "", "none", "none"),
    PlatformConfig("yixi", "一席", "", "none", "none"),
    PlatformConfig("runoob", "菜鸟教程", "", "none", "none"),
    PlatformConfig("shuge", "书格", "", "none", "none"),
    PlatformConfig("zjer", "之江汇", "", "none", "none"),
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
        raise SessionError("SESSION_PAYLOAD_INVALID", f"{field_name} 必须包含时区")
    return parsed.astimezone(timezone.utc)


def _bilibili_probe_ok(status: int, body: str) -> bool:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False
    data = payload.get("data") if isinstance(payload, dict) else None
    return bool(isinstance(data, dict) and data.get("isLogin"))


def _status_2xx_ok(status: int, body: str) -> bool:
    del body
    return 200 <= status < 300


_PROBE_CHECKS: dict[str, Callable[[int, str], bool]] = {
    "bilibili": _bilibili_probe_ok,
}


def _domain_matches(domain: str, allowed_domains: tuple[str, ...]) -> bool:
    normalized = domain.strip().lower().lstrip(".").rstrip(".")
    return any(
        normalized == allowed or normalized.endswith(f".{allowed}")
        for allowed in allowed_domains
    )


@dataclass(slots=True)
class SessionStatus:
    config: PlatformConfig
    status: str
    captured_at: str | None = None
    expires_at: str | None = None

    @property
    def platform(self) -> str:
        return self.config.platform_id

    def to_dict(self) -> dict[str, Any]:
        result = {
            **self.config.public_metadata(),
            "status": self.status,
        }
        if self.captured_at is not None:
            result["captured_at"] = self.captured_at
        if self.expires_at is not None:
            result["expires_at"] = self.expires_at
        return result


class SessionStore:
    """One file-backed session store shared by resource and session capabilities."""

    def __init__(self, data_dir: Path) -> None:
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._protector = None
        if os.name == "nt":
            try:
                self._protector = WindowsDpapiProtector()
            except WindowsDpapiError as exc:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "Windows DPAPI 无法初始化，拒绝以明文保存登录态",
                ) from exc

    def _platform(self, platform: str) -> PlatformConfig:
        normalized = str(platform or "").strip().replace("_", "-")
        config = PLATFORM_REGISTRY.get(normalized)
        if config is None:
            raise SessionError("INVALID_ARGUMENT", f"未知平台：{platform}")
        return config

    def _path(self, platform: str) -> Path:
        return self.sessions_dir / f"{platform}.json"

    def _decode_record(self, raw: bytes, *, platform: str) -> dict[str, Any] | None:
        try:
            outer = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(outer, dict):
            return None
        if outer.get("format") == "windows-dpapi-v1":
            if self._protector is None:
                return None
            encoded = outer.get("ciphertext")
            if not isinstance(encoded, str):
                return None
            try:
                protected = base64.b64decode(encoded, validate=True)
                plaintext = self._protector.unprotect(
                    protected, purpose=f"session:{platform}"
                )
                value = json.loads(plaintext.decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError, WindowsDpapiError):
                return None
            return value if isinstance(value, dict) else None
        return outer

    def _read(self, platform: str) -> dict[str, Any] | None:
        path = self._path(platform)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        return self._decode_record(raw, platform=platform)

    def _atomic_write(self, platform: str, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
        if self._protector is not None:
            try:
                protected = self._protector.protect(
                    payload, purpose=f"session:{platform}"
                )
            except WindowsDpapiError as exc:
                raise SessionError(
                    "SECURE_STORAGE_UNAVAILABLE",
                    "Windows DPAPI 无法加密登录态",
                ) from exc
            payload = json.dumps(
                {
                    "format": self._protector.format_name,
                    "ciphertext": base64.b64encode(protected).decode("ascii"),
                },
                ensure_ascii=True,
                indent=2,
            ).encode("ascii")
        path = self._path(platform)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            if os.name == "posix":
                path.chmod(0o600)
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

    @staticmethod
    def _validate_storage_origin(value: Any, config: PlatformConfig) -> None:
        if not isinstance(value, str) or not value.strip():
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                "storage_origin 必须是当前官方页面的 HTTP(S) origin",
            )
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                "storage_origin 必须是当前官方页面的 HTTP(S) origin",
            )
        if config.cookie_domains and not _domain_matches(parsed.hostname, config.cookie_domains):
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                f"storage_origin 不属于 {config.label} 官方域名",
            )

    @staticmethod
    def _storage_map(value: Any, name: str) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise SessionError("SESSION_PAYLOAD_INVALID", f"{name} 必须是对象")
        clean: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID",
                    f"{name} 的键和值都必须是字符串",
                )
            clean[key] = item
        return clean

    @staticmethod
    def _cookie_list(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise SessionError("SESSION_PAYLOAD_INVALID", "cookies 必须是数组")
        return [item for item in value if isinstance(item, dict)]

    def _sanitize_cookie_payload(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> dict[str, Any]:
        cookies = self._cookie_list(session_data.get("cookies"))
        now_epoch = datetime.now(timezone.utc).timestamp()
        clean: list[dict[str, Any]] = []
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            domain = cookie.get("domain")
            if not isinstance(name, str) or not name:
                continue
            if not isinstance(value, str):
                continue
            if not isinstance(domain, str) or not _domain_matches(domain, config.cookie_domains):
                continue
            expires = cookie.get("expires")
            if (
                isinstance(expires, (int, float))
                and not isinstance(expires, bool)
                and expires > 0
                and expires <= now_epoch
            ):
                continue
            item: dict[str, Any] = {
                "name": name,
                "value": value,
                "domain": domain.strip().lower(),
                "path": cookie.get("path") if isinstance(cookie.get("path"), str) else "/",
            }
            if expires is not None:
                item["expires"] = expires
            for flag in ("httpOnly", "secure", "sameSite"):
                if flag in cookie:
                    item[flag] = cookie[flag]
            clean.append(item)

        if not clean:
            raise SessionError(
                "SESSION_EMPTY",
                f"没有属于 {config.label} 域名范围的有效 Cookie，未保存",
            )

        result: dict[str, Any] = {"cookies": clean}
        if config.storage_keys:
            local_storage = self._storage_map(
                session_data.get("local_storage"), "local_storage"
            )
            session_storage = self._storage_map(
                session_data.get("session_storage"), "session_storage"
            )
            if local_storage or session_storage:
                self._validate_storage_origin(session_data.get("storage_origin"), config)
            retained: dict[str, str] = {}
            for key in config.storage_keys:
                if key in local_storage:
                    retained[key] = local_storage[key]
                elif key in session_storage:
                    retained[key] = session_storage[key]
            if retained:
                result["local_storage"] = retained
        return result

    @staticmethod
    def _nested_strings(value: Any, wanted: set[str], depth: int = 0) -> dict[str, str]:
        found: dict[str, str] = {}
        if isinstance(value, str):
            # SmartEdu 的 token 会再包一层 JSON 字符串（{"value": "{...}"}），
            # access_token 在字符串内部：只按结构递归解不到，字符串也要剥。
            stripped = value.strip()
            if depth >= 3 or stripped[:1] not in "{[":
                return found
            try:
                value = json.loads(stripped)
            except ValueError:
                return found
        if isinstance(value, dict):
            for key, child in value.items():
                if key in wanted and isinstance(child, str) and child:
                    found.setdefault(key, child)
                found.update(SessionStore._nested_strings(child, wanted, depth + 1))
        elif isinstance(value, list):
            for child in value:
                found.update(SessionStore._nested_strings(child, wanted, depth + 1))
        return found

    def _sanitize_smartedu_payload(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> dict[str, Any]:
        extracted: dict[str, str] = {}
        direct = session_data.get("tokens")
        if direct is not None:
            if not isinstance(direct, dict):
                raise SessionError("SESSION_PAYLOAD_INVALID", "tokens 必须是对象")
            unknown = set(direct) - set(config.storage_keys)
            if unknown:
                raise SessionError(
                    "SESSION_PAYLOAD_INVALID",
                    f"tokens 含不支持字段：{', '.join(sorted(unknown))}",
                )
            for key in config.storage_keys:
                value = direct.get(key)
                if isinstance(value, str) and value:
                    extracted[key] = value

        local_storage = self._storage_map(
            session_data.get("local_storage"), "local_storage"
        )
        session_storage = self._storage_map(
            session_data.get("session_storage"), "session_storage"
        )
        if local_storage or session_storage:
            self._validate_storage_origin(session_data.get("storage_origin"), config)

        for storage in (local_storage, session_storage):
            for key in config.storage_keys:
                if key not in extracted and storage.get(key):
                    extracted[key] = storage[key]
            for storage_key, raw_value in storage.items():
                if not _SMARTEDU_STORAGE_KEY_RE.fullmatch(storage_key):
                    continue
                try:
                    decoded = json.loads(raw_value)
                except (TypeError, ValueError):
                    continue
                nested = self._nested_strings(
                    decoded, {"access_token", "accessToken", "x-nd-auth"}
                )
                access_token = nested.get("access_token") or nested.get("accessToken")
                if access_token and "accessToken" not in extracted:
                    extracted["accessToken"] = access_token
                if nested.get("x-nd-auth") and "x-nd-auth" not in extracted:
                    extracted["x-nd-auth"] = nested["x-nd-auth"]

        if "accessToken" not in extracted:
            now_epoch = datetime.now(timezone.utc).timestamp()
            for cookie in self._cookie_list(session_data.get("cookies")):
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
                    and value
                    and isinstance(domain, str)
                    and _domain_matches(domain, config.cookie_domains)
                ):
                    extracted["accessToken"] = value
                    break

        missing = [
            key for key in config.required_storage_keys if not extracted.get(key)
        ]
        if missing:
            raise SessionError(
                "SESSION_EMPTY",
                f"缺少必要存储项：{', '.join(missing)}",
            )
        return {
            "tokens": {
                key: extracted[key]
                for key in config.storage_keys
                if extracted.get(key)
            }
        }

    def _sanitize_session_data(
        self, config: PlatformConfig, session_data: dict[str, Any]
    ) -> dict[str, Any]:
        if config.auth_kind == "none":
            raise SessionError(
                "LOGIN_NOT_REQUIRED", f"{config.label} 不需要保存登录态"
            )
        if not isinstance(session_data, dict):
            raise SessionError("SESSION_PAYLOAD_INVALID", "session_data 必须是对象")
        allowed = {
            "cookies", "tokens", "storage_origin", "local_storage", "session_storage"
        }
        unknown = set(session_data) - allowed
        if unknown:
            raise SessionError(
                "SESSION_PAYLOAD_INVALID",
                f"session_data 含不支持字段：{', '.join(sorted(unknown))}",
            )
        if config.auth_kind == "token":
            return self._sanitize_smartedu_payload(config, session_data)
        return self._sanitize_cookie_payload(config, session_data)

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
            record = self._read(config.platform_id)
            if record is None:
                status = "missing"
            elif record.get("platform") != config.platform_id or not isinstance(
                record.get("session_data"), dict
            ):
                status = "invalid"
            elif self._is_expired(record):
                status = "expired"
            else:
                status = "stored"
            results.append(
                SessionStatus(
                    config=config,
                    status=status,
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
            record = self._read(config.platform_id)
            if (
                record is None
                or record.get("platform") != config.platform_id
                or self._is_expired(record)
            ):
                return None
            value = record.get("session_data")
            return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def _cookie_header(session_data: dict[str, Any]) -> str:
        cookies = session_data.get("cookies") or []
        parts: list[str] = []
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if isinstance(name, str) and name and isinstance(value, str):
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    def save(
        self,
        platform: str,
        session_data: dict[str, Any],
        *,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        config = self._platform(platform)
        canonical = self._sanitize_session_data(config, session_data)
        if expires_at is not None:
            _parse_timestamp(expires_at, "expires_at")
        now = _utc_now()
        record = {
            "platform": config.platform_id,
            "auth_kind": config.auth_kind,
            "session_data": canonical,
            "captured_at": now,
            "updated_at": now,
            "expires_at": expires_at,
        }
        with self._lock:
            self._atomic_write(config.platform_id, record)
        return {
            "platform": config.platform_id,
            "status": "stored",
            "captured_at": now,
            "expires_at": expires_at,
            "stored_credential_count": (
                len(canonical.get("cookies") or [])
                + len(canonical.get("tokens") or {})
                + len(canonical.get("local_storage") or {})
            ),
        }

    def delete(self, platform: str) -> dict[str, Any]:
        config = self._platform(platform)
        with self._lock:
            path = self._path(config.platform_id)
            existed = path.exists()
            if existed:
                path.unlink()
        return {"platform": config.platform_id, "deleted": existed}

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
            "browser_storage"
            if config.capture_method == "browser_storage"
            else "browser_cookies"
        )
        return {
            **metadata,
            "steps": [
                {"order": 1, "action": "open_login_url", "actor": "agent"},
                {
                    "order": 2,
                    "action": "user_login",
                    "actor": "user",
                    "message": "请用户自行完成登录；不要索取或代填账号、密码、验证码。",
                },
                {
                    "order": 3,
                    "action": capture_action,
                    "actor": "agent",
                    "message": "把浏览器捕获原样交给 resource_session_save，由 MCP 按平台规则筛选。",
                },
                {"order": 4, "action": "resource_session_save", "actor": "agent"},
            ],
        }

    def validate(self, platform: str) -> dict[str, Any]:
        config = self._platform(platform)
        now = _utc_now()
        if config.auth_kind == "none":
            return {
                "platform": config.platform_id,
                "probe_status": "no_probe",
                "probed_at": now,
                "detail": f"{config.label} 不需要登录",
            }
        session_data = self.get_session_data(config.platform_id)
        if session_data is None:
            return {
                "platform": config.platform_id,
                "probe_status": "missing",
                "probed_at": now,
                "detail": "无可用 session",
            }
        if not config.probe_url:
            return {
                "platform": config.platform_id,
                "probe_status": "no_probe",
                "probed_at": now,
                "detail": f"{config.label} 未配置远端探针",
            }
        try:
            if config.auth_kind == "token":
                tokens = session_data.get("tokens") or {}
                token = tokens.get("accessToken")
                headers = {}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    headers["accessToken"] = token
                if tokens.get("x-nd-auth"):
                    headers["x-nd-auth"] = tokens["x-nd-auth"]
                status, body = probe_with_headers(
                    config.probe_url, headers, timeout=PROBE_TIMEOUT
                )
            else:
                status, body = probe_with_cookies(
                    config.probe_url,
                    self._cookie_header(session_data),
                    timeout=PROBE_TIMEOUT,
                )
        except URLError as exc:
            return {
                "platform": config.platform_id,
                "probe_status": "probe_error",
                "probed_at": now,
                "detail": f"探针请求失败：{exc.reason}",
            }
        accepted = _PROBE_CHECKS.get(config.platform_id, _status_2xx_ok)(status, body)
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
