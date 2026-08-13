"""Platform session store for cookies and access tokens.

Sessions are stored as JSON files in the MCP data directory (outside the repo).
The MCP never returns raw credential values—only status and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Callable
from urllib.error import URLError

from .adapters.http_client import probe_with_cookies, probe_with_headers


# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PlatformConfig:
    """Static metadata for a known platform."""

    platform_id: str
    label: str
    login_url: str
    cookie_domains: list[str]
    probe_url: str | None = None
    # How this platform authenticates. Keep this registry minimal — detailed
    # per-operation credential requirements (which exact cookie/token each
    # search or download needs) live in each platform's adapter, not here.
    #   "cookie" = browser cookies; capture reads `browser cookies`.
    #   "token"  = bearer token / custom headers; capture must read storage
    #              state or request headers, not just cookies.
    #   "none"   = public, no login needed.
    auth_kind: str = "cookie"


PLATFORM_REGISTRY: dict[str, PlatformConfig] = {
    platform.platform_id: platform
    for platform in [
        PlatformConfig(
            "douyin",
            "抖音",
            "https://www.douyin.com/",
            ["douyin.com", ".douyin.com"],
            None,
        ),
        PlatformConfig(
            "bilibili",
            "B站",
            "https://passport.bilibili.com/login",
            ["bilibili.com", ".bilibili.com"],
            "https://api.bilibili.com/x/web-interface/nav",
        ),
        PlatformConfig(
            "zhihu",
            "知乎",
            "https://www.zhihu.com/signin",
            ["zhihu.com", ".zhihu.com"],
            "https://www.zhihu.com/api/v4/me",
        ),
        PlatformConfig(
            "smartedu",
            "智慧教育",
            "https://basic.smartedu.cn/",
            ["smartedu.cn", ".smartedu.cn", "eduyun.cn", ".eduyun.cn"],
            auth_kind="token",
        ),
        PlatformConfig(
            "open163",
            "网易公开课",
            "https://open.163.com/",
            ["163.com", ".163.com"],
        ),
        PlatformConfig(
            "wechat",
            "微信公众号",
            "https://weixin.sogou.com/",
            ["sogou.com", ".sogou.com"],
        ),
        PlatformConfig(
            "weibo",
            "微博",
            "https://passport.weibo.com/sso/signin",
            ["weibo.com", ".weibo.com", "sina.com.cn"],
        ),
        PlatformConfig(
            "ximalaya",
            "喜马拉雅",
            "https://www.ximalaya.com/login",
            ["ximalaya.com", ".ximalaya.com"],
        ),
        PlatformConfig(
            "baiduwenku",
            "百度文库",
            "https://wenku.baidu.com/",
            ["baidu.com", ".baidu.com"],
        ),
        PlatformConfig(
            "nlc",
            "国家图书馆",
            "https://read.nlc.cn/",
            ["nlc.cn", ".nlc.cn"],
        ),
        PlatformConfig(
            "annas-archive",
            "安娜的档案",
            "",
            ["annas-archive.org"],
            auth_kind="none",
        ),
        PlatformConfig(
            "cctv",
            "央视网",
            "",
            ["cctv.com", ".cctv.com"],
            auth_kind="none",
        ),
        PlatformConfig(
            "kepu",
            "科普中国",
            "",
            ["kepuchina.cn", ".kepuchina.cn"],
            auth_kind="none",
        ),
        PlatformConfig(
            "yixi",
            "一席",
            "",
            ["yixi.tv", ".yixi.tv"],
            auth_kind="none",
        ),
        PlatformConfig(
            "runoob",
            "菜鸟教程",
            "",
            ["runoob.com", ".runoob.com"],
            auth_kind="none",
        ),
    ]
}


# ---------------------------------------------------------------------------
# Active session probing
# ---------------------------------------------------------------------------

PROBE_TIMEOUT = 10.0


def _bilibili_probe_ok(status: int, body: str) -> bool:
    """Bilibili nav API returns HTTP 200 even when logged out, so the
    ``data.isLogin`` flag in the JSON body is the real signal."""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False
    data = payload.get("data") if isinstance(payload, dict) else None
    return bool(isinstance(data, dict) and data.get("isLogin"))


def _status_2xx_ok(status: int, body: str) -> bool:
    """Default probe: any 2xx response means the session was accepted."""
    return 200 <= status < 300


# Per-platform response interpreters. Platforms without an entry fall back to
# ``_status_2xx_ok``. Add entries here as probe_url coverage grows.
_PROBE_CHECKS: dict[str, Callable[[int, str], bool]] = {
    "bilibili": _bilibili_probe_ok,
}


def _smartedu_auth_headers(session_data: dict[str, Any]) -> dict[str, str]:
    """Build the request headers that carry a stored SmartEdu access token.

    SmartEdu authenticates with a Bearer token sent as BOTH ``Authorization``
    and a custom ``accessToken`` header, plus an optional ``x-nd-auth``.
    The token is captured from the browser's localStorage (not cookies).
    """
    tokens = session_data.get("tokens") or {}
    headers: dict[str, str] = dict(session_data.get("headers") or {})
    token = tokens.get("accessToken")
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")
        headers.setdefault("accessToken", token)
    return headers


# Per-platform auth-header builders for token-type platforms. Used by
# ``validate()`` to construct the headers a probe request must carry.
# Add entries here as token platforms grow.
_AUTH_HEADER_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, str]]] = {
    "smartedu": _smartedu_auth_headers,
}


# ---------------------------------------------------------------------------
# Session status
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SessionStatus:
    platform: str
    label: str
    status: str  # "valid" | "expired" | "missing"
    login_url: str
    captured_at: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "platform": self.platform,
            "label": self.label,
            "status": self.status,
            "login_url": self.login_url,
        }
        if self.captured_at is not None:
            result["captured_at"] = self.captured_at
        if self.expires_at is not None:
            result["expires_at"] = self.expires_at
        return result


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """File-based session store under the MCP data directory.

    Each platform gets one JSON file: ``sessions/<platform>.json``
    containing ``session_data`` (cookies/storage_state), timestamps and
    a human-readable status.  Credential values are never returned by
    public methods—only status and metadata.
    """

    def __init__(self, data_dir: Path) -> None:
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # -- internal helpers ------------------------------------------------

    def _path(self, platform: str) -> Path:
        return self.sessions_dir / f"{platform}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _is_expired(record: dict[str, Any]) -> bool:
        expires_at = record.get("expires_at")
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    # -- public API ------------------------------------------------------

    def get_status(self, platforms: list[str] | None = None) -> list[SessionStatus]:
        """Return batch status for the requested platforms (or all known)."""
        if platforms:
            ids = [p for p in platforms if p in PLATFORM_REGISTRY]
        else:
            ids = list(PLATFORM_REGISTRY)

        results: list[SessionStatus] = []
        for pid in ids:
            cfg = PLATFORM_REGISTRY[pid]
            record = self._read(self._path(pid))
            if record is None:
                results.append(SessionStatus(
                    platform=pid, label=cfg.label, status="missing",
                    login_url=cfg.login_url,
                ))
            elif self._is_expired(record):
                results.append(SessionStatus(
                    platform=pid, label=cfg.label, status="expired",
                    login_url=cfg.login_url,
                    captured_at=record.get("captured_at"),
                    expires_at=record.get("expires_at"),
                ))
            else:
                results.append(SessionStatus(
                    platform=pid, label=cfg.label, status="valid",
                    login_url=cfg.login_url,
                    captured_at=record.get("captured_at"),
                    expires_at=record.get("expires_at"),
                ))
        return results

    def get_session_data(self, platform: str) -> dict[str, Any] | None:
        """Return raw session data for internal use by adapters.

        This is the only method that returns credential values.
        It must never be exposed through a public MCP tool response.
        """
        with self._lock:
            record = self._read(self._path(platform))
            if record is None or self._is_expired(record):
                return None
            return record.get("session_data")

    def validate(self, platform: str) -> dict[str, Any]:
        """Actively probe whether the stored session for *platform* is still
        accepted by the platform.

        Returns a dict with ``probe_status`` (``valid`` | ``invalid`` |
        ``no_probe`` | ``probe_error`` | ``missing``), ``probed_at`` and a
        human-readable ``detail``.  Credential values are never returned.
        The base ``status`` (from the stored record) is included separately
        so callers can show both the file state and the live probe result.
        """
        cfg = PLATFORM_REGISTRY.get(platform)
        if cfg is None:
            raise ValueError(f"Unknown platform: {platform}")

        now = _utc_now()

        if cfg.auth_kind == "none":
            return {
                "platform": platform,
                "probe_status": "no_probe",
                "probed_at": now,
                "detail": f"{cfg.label} 不需要登录",
            }

        record = self._read(self._path(platform))
        if record is None:
            return {
                "platform": platform,
                "probe_status": "missing",
                "probed_at": now,
                "detail": "无已存储的 session",
            }
        if self._is_expired(record):
            return {
                "platform": platform,
                "probe_status": "invalid",
                "probed_at": now,
                "detail": "session 已过期（按本地时间戳）",
            }
        if not cfg.probe_url:
            return {
                "platform": platform,
                "probe_status": "no_probe",
                "probed_at": now,
                "detail": f"{cfg.label} 未配置探针 URL，无法主动校验",
            }

        session_data = record.get("session_data") or {}
        check = _PROBE_CHECKS.get(platform, _status_2xx_ok)
        try:
            if cfg.auth_kind == "token":
                builder = _AUTH_HEADER_BUILDERS.get(platform)
                if builder is None:
                    return {
                        "platform": platform,
                        "probe_status": "no_probe",
                        "probed_at": now,
                        "detail": f"{cfg.label} 未配置 token 构造器，无法主动校验",
                    }
                headers = builder(session_data)
                if not headers:
                    return {
                        "platform": platform,
                        "probe_status": "invalid",
                        "probed_at": now,
                        "detail": f"{cfg.label} 已存储 session 中无可用 token",
                    }
                status, body = probe_with_headers(
                    cfg.probe_url, headers, timeout=PROBE_TIMEOUT
                )
            else:
                cookie_header = self._cookie_header(session_data)
                status, body = probe_with_cookies(
                    cfg.probe_url, cookie_header, timeout=PROBE_TIMEOUT
                )
        except URLError as exc:
            return {
                "platform": platform,
                "probe_status": "probe_error",
                "probed_at": now,
                "detail": f"探针请求失败：{exc.reason}",
            }
        accepted = check(status, body)
        return {
            "platform": platform,
            "probe_status": "valid" if accepted else "invalid",
            "probed_at": now,
            "detail": (
                f"{cfg.label} session 有效（HTTP {status}）"
                if accepted
                else f"{cfg.label} session 被拒绝（HTTP {status}）"
            ),
        }

    @staticmethod
    def _cookie_header(session_data: dict[str, Any]) -> str:
        """Build a ``name=value; …`` Cookie header from stored session data."""
        cookies = session_data.get("cookies") or []
        parts: list[str] = []
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value is not None:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    def save(
        self,
        platform: str,
        session_data: dict[str, Any],
        *,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist a captured session for *platform*."""
        if platform not in PLATFORM_REGISTRY:
            raise ValueError(f"Unknown platform: {platform}")
        now = _utc_now()
        record = {
            "platform": platform,
            "session_data": session_data,
            "captured_at": now,
            "updated_at": now,
            "expires_at": expires_at,
        }
        with self._lock:
            self._path(platform).write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return {
            "platform": platform,
            "status": "valid",
            "captured_at": now,
            "expires_at": expires_at,
        }

    def delete(self, platform: str) -> dict[str, Any]:
        """Remove a stored session."""
        with self._lock:
            path = self._path(platform)
            existed = path.exists()
            if existed:
                path.unlink()
        return {"platform": platform, "deleted": existed}