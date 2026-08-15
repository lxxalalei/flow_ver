"""Standalone MCP 2.0 stdio server for browser-assisted login sessions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Literal

from mcp.server.mcpserver import MCPServer

from .browser_capture import BrowserUnavailableError, CdpProtocolError, fetch_browser_cookies
from .store import SessionError, SessionStore


CONTRACT_VERSION = "1.0.0"
SERVICE_VERSION = "0.4.1"


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
    except BrowserUnavailableError as exc:
        return _failure("BROWSER_UNAVAILABLE", str(exc), retriable=True, **identifiers)
    except CdpProtocolError as exc:
        return _failure("BROWSER_CDP_ERROR", str(exc), **identifiers)
    except ValueError as exc:
        return _failure("INVALID_ARGUMENT", str(exc), **identifiers)
    except Exception:  # pragma: no cover - defensive protocol boundary
        # Unexpected exception strings can accidentally include request data.
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
            "First call resource_session_status or resource_session_login_guide. "
            "When login is required, open login_url with the host browser and ask "
            "the user to log in themselves. Wait for explicit confirmation before "
            "capturing. For cookie platforms prefer resource_session_capture_browser: "
            "it reads the full browser cookie store server-side (including httpOnly "
            "cookies) and never routes credential bytes through the conversation. "
            "Only if that tool reports BROWSER_UNAVAILABLE and the browser cannot be "
            "started, fall back to a browser-context cookie read passed to "
            "resource_session_save; never use document.cookie, which cannot see "
            "httpOnly login cookies. Storage platforms still capture same-origin "
            "storage through resource_session_save. Then check status. "
            "Never request, accept, or autofill accounts, passwords, CAPTCHA, SMS codes, "
            "or MFA. If the user voluntarily supplies a legally obtained canonical Cookie "
            "or Token and explicitly names the supported platform, purpose, and permission "
            "to save it, send it once only as resource_session_save session_data. Never "
            "echo, narrate, log, forward, mix with browser capture, or automatically replay "
            "credential values."
        ),
    )

    @server.tool(structured_output=True)
    def resource_session_status(
        contract_version: Literal["1.0.0"],
        platforms: list[str] | None = None,
        deep: bool = False,
    ) -> dict[str, Any]:
        """Return session state plus machine-readable login/capture metadata.

        ``needs_login`` contains only platforms that require a fresh user login.
        With ``deep=true``, supported platforms are actively probed; an invalid
        probe is also included in ``needs_login``.
        """
        return _invoke(lambda: _session_status(session_store, platforms, deep))

    @server.tool(structured_output=True)
    def resource_session_login_guide(
        contract_version: Literal["1.0.0"], platform: str
    ) -> dict[str, Any]:
        """Return safe host-browser login steps and allowed capture scope.

        This tool never opens a browser and never returns credentials. The host
        agent must open ``login_url``, wait for the user to finish login, then use
        the declared ``capture_method`` and scope.
        """
        return _invoke(
            lambda: session_store.login_guide(platform), platform=platform
        )

    @server.tool(structured_output=True)
    def resource_session_capture_browser(
        contract_version: Literal["1.0.0"],
        platform: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Capture cookies server-side from the managed browser and save them.

        Reads the OpenClaw-managed browser's full cookie store over the local
        CDP endpoint (``Storage.getCookies``, includes httpOnly cookies) and
        hands the broad capture straight to the store.  Credential values never
        enter the conversation; the response only carries counts.  Call it after
        the user confirmed login in the opened browser.  ``BROWSER_UNAVAILABLE``
        means the managed browser is not running: open it and retry.
        """
        def capture() -> dict[str, Any]:
            cookies = fetch_browser_cookies()
            result = session_store.save(
                platform, {"cookies": cookies}, idempotency_key=idempotency_key
            )
            return {**result, "captured_cookie_count": len(cookies)}

        return _invoke(capture, platform=platform)

    @server.tool(structured_output=True)
    def resource_session_save(
        contract_version: Literal["1.0.0"],
        platform: str,
        session_data: dict[str, Any],
        expires_at: str | None = None,
        idempotency_key: str | None = None,
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
                session_data,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
            ),
            platform=platform,
        )

    @server.tool(structured_output=True)
    def resource_session_delete(
        contract_version: Literal["1.0.0"],
        platform: str,
        idempotency_key: str | None = None,
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
