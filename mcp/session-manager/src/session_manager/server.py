"""Standalone MCP 2.0 stdio server for browser-assisted login sessions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from .store import SessionError, SessionStore


CONTRACT_VERSION = "1.0.0"
SERVICE_VERSION = "0.4.1"


class SessionCapture(BaseModel):
    """One browser capture or explicitly authorized canonical token import.

    Unknown fields pass through unchanged so the store keeps failing loudly
    on unexpected input; the MCP performs platform extraction server-side.
    """

    model_config = ConfigDict(extra="allow")

    cookies: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "浏览器 cookie 能力返回的 cookie 对象数组，逐个原样传入。"
            "不要筛选、转写、合并或重新编码任何值；服务端会按平台域名规则提取。"
        ),
    )
    storage_origin: str | None = Field(
        default=None,
        description=(
            "捕获 storage 时活动官方页面的 location.origin，"
            "如 https://basic.smartedu.cn；仅在传入 local_storage/session_storage 时需要。"
        ),
    )
    local_storage: dict[str, str] | None = Field(
        default=None,
        description=(
            "localStorage 快照，键与值都必须是字符串（浏览器 API 返回什么就传什么），"
            "不得嵌套对象。服务端只保留平台规则匹配的最小条目。"
        ),
    )
    session_storage: dict[str, str] | None = Field(
        default=None,
        description="同 local_storage，来自 sessionStorage。",
    )
    tokens: dict[str, str] | None = Field(
        default=None,
        description=(
            "规范 Token 直连导入（如 smartedu 的 accessToken）。仅当用户自愿提供"
            "合法取得的 Token 并明确授权保存时使用；它不是浏览器捕获的精简通道——"
            "捕获数据请走 cookies/local_storage/session_storage，由服务端提取。"
        ),
    )


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"contract_version": CONTRACT_VERSION, "ok": True, **data}


def _failure(
    code: str,
    message: str,
    *,
    retriable: bool = False,
    **identifiers: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "ok": False,
        "error": {"code": code, "message": message, "retriable": retriable},
    }
    result.update({key: value for key, value in identifiers.items() if value})
    return result


def _invoke(
    function: Callable[[], dict[str, Any]], **identifiers: str | None
) -> dict[str, Any]:
    try:
        return _ok(function())
    except SessionError as exc:
        return _failure(exc.code, str(exc), **identifiers)
    except ValueError as exc:
        return _failure("INVALID_ARGUMENT", str(exc), **identifiers)
    except Exception:  # pragma: no cover - defensive protocol boundary
        return _failure("INTERNAL_ERROR", "Unexpected server error", **identifiers)


def _data_dir() -> Path:
    configured = os.environ.get("SESSION_MANAGER_DATA_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "OpenClaw" / "session-manager"
        return Path.home() / "AppData" / "Local" / "OpenClaw" / "session-manager"
    return Path.home() / ".local" / "share" / "session-manager"


def create_server(store: SessionStore | None = None) -> MCPServer:
    session_store = store or SessionStore(_data_dir())
    server = MCPServer(
        name="session-manager",
        title="Session Manager",
        description="Guide browser login, securely store minimal cookies/tokens, and validate sessions",
        version=SERVICE_VERSION,
        instructions=(
            "Session Manager is an auxiliary authentication capability, not a preflight step. "
            "Do not call it before public search/download operations merely because a platform "
            "supports login. Use it when a resource capability has returned a concrete "
            "AUTH_REQUIRED result, or when the user explicitly asks to inspect/manage a saved "
            "platform session. A platform entry with requires_login=true means that the platform "
            "has authenticated capabilities; it does not mean every operation needs a session. "
            "If status says not_required/requires_login=false, do not initiate login. When a real "
            "login is required, open login_url with the host browser and ask the user to log in "
            "themselves. Wait for explicit confirmation before capturing browser cookies and "
            "same-origin storage. Pass the broad browser capture directly to resource_session_save; "
            "the MCP performs platform extraction and minimal persistence. Never request, accept, "
            "or autofill accounts, passwords, CAPTCHA, SMS codes, or MFA. If the user voluntarily "
            "supplies a legally obtained canonical Cookie or Token and explicitly names the supported "
            "platform, purpose, and permission to save it, send it once only as resource_session_save "
            "session_data. Never echo, narrate, log, forward, mix with browser capture, or "
            "automatically replay credential values."
        ),
    )

    @server.tool(structured_output=True)
    def resource_session_status(
        contract_version: Literal["1.0.0"],
        platforms: Annotated[
            list[str] | None,
            Field(
                description=(
                    "要查询的平台 id 列表；不传则返回全部。支持的平台以返回结果为准。"
                    "不要把此状态查询作为所有资源操作的前置步骤。"
                )
            ),
        ] = None,
        deep: Annotated[
            bool,
            Field(
                description=(
                    "是否真实探测远端（仅 probe_supported 平台有效）。默认 false 只看本地状态；"
                    "保存后的复验和“已保存登录态到底还能不能用”用 true。"
                )
            ),
        ] = False,
    ) -> dict[str, Any]:
        """Return stored-session state and login/capture metadata.

        ``needs_login`` means a fresh session would be needed for that platform's
        authenticated capabilities. It is not proof that the current resource
        operation requires login. Act on it only after a concrete AUTH_REQUIRED
        result or an explicit user request to manage login.
        """
        return _invoke(lambda: _session_status(session_store, platforms, deep))

    @server.tool(structured_output=True)
    def resource_session_login_guide(
        contract_version: Literal["1.0.0"],
        platform: Annotated[
            str,
            Field(description="平台 id，如 douyin、bilibili、zhihu、smartedu；以 status 返回列表为准。"),
        ],
    ) -> dict[str, Any]:
        """Return safe host-browser login steps after login is actually needed.

        Use this after a concrete AUTH_REQUIRED result, or when the user asks to
        manage the platform session. This tool never opens a browser and never
        returns credentials. Public/no-session platforms return no login steps.
        """
        return _invoke(
            lambda: session_store.login_guide(platform), platform=platform
        )

    @server.tool(structured_output=True)
    def resource_session_save(
        contract_version: Literal["1.0.0"],
        platform: Annotated[
            str,
            Field(description="平台 id；在已确认需要登录并取得用户授权后保存。"),
        ],
        session_data: SessionCapture,
        expires_at: Annotated[
            str | None,
            Field(
                description=(
                    "RFC3339 时间戳。仅当一个可靠过期时间覆盖整个平台会话时才传；"
                    "不确定就省略，由存储侧按平台规则处理。"
                )
            ),
        ] = None,
        idempotency_key: Annotated[
            str | None,
            Field(
                description=(
                    "幂等键，8-128 位字母/数字/点/下划线/冒号/连字符。每次捕获生成唯一值；"
                    "仅在确认上次请求确切结果后才可复用，绝不自动重放不确定的写入。"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Securely persist host-captured or explicitly authorized canonical session data.

        The browser may submit broad cookies and same-origin storage maps. Platform
        extractors enforce domains, key patterns, required fields, and minimal
        persistence server-side; unrelated captured entries are discarded. A trusted host
        may submit a user's explicitly authorized canonical Cookie/Token for the named
        platform. Responses never include credential values. Reuse an ``idempotency_key``
        only when the caller has established the prior request's exact outcome.
        """
        return _invoke(
            lambda: session_store.save(
                platform,
                session_data.model_dump(exclude_none=True),
                expires_at=expires_at,
                idempotency_key=idempotency_key,
            ),
            platform=platform,
        )

    @server.tool(structured_output=True)
    def resource_session_delete(
        contract_version: Literal["1.0.0"],
        platform: Annotated[
            str,
            Field(description="要删除本地登录态的平台 id。"),
        ],
        idempotency_key: Annotated[
            str | None,
            Field(description="幂等键；重试同一次删除时复用，规则同 resource_session_save。"),
        ] = None,
    ) -> dict[str, Any]:
        """Delete a locally stored platform session; supports idempotent retry."""
        return _invoke(
            lambda: session_store.delete(
                platform, idempotency_key=idempotency_key
            ),
            platform=platform,
        )

    return server


def _session_status(
    store: SessionStore, platforms: list[str] | None, deep: bool
) -> dict[str, Any]:
    statuses = store.get_status(platforms)
    entries = [status.to_dict() for status in statuses]
    needs_login: list[dict[str, Any]] = []

    for entry, status in zip(entries, statuses):
        if deep and status.status == "stored":
            probe = store.validate(status.platform)
            entry["probe_status"] = probe["probe_status"]
            entry["probed_at"] = probe["probed_at"]
            if probe.get("detail"):
                entry["probe_detail"] = probe["detail"]
        if status.status in {"missing", "expired", "invalid"} or entry.get("probe_status") == "invalid":
            if status.config.auth_kind != "none":
                needs_login.append(status.config.public_metadata())

    return {"sessions": entries, "needs_login": needs_login}


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
