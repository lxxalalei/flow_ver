"""Standalone MCP 2.0 stdio server exposing only the session tools.

Tools:
    resource_session_status   — batch status; deep=true actively probes.
    resource_session_save     — persist a captured browser session.
    resource_session_delete   — remove a stored session.

Cookie capture itself is done by the host (OpenClaw browser tools); this
service only stores / queries / validates. Raw credential values are never
returned by any tool response.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Literal

from mcp.server.mcpserver import MCPServer

from .store import SessionStore


# ---------------------------------------------------------------------------
# Response helpers (mirror the education-resource MCP contract shape)
# ---------------------------------------------------------------------------

def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"contract_version": "1.0.0", "ok": True, **data}


def _failure(code: str, message: str, **identifiers: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": "1.0.0",
        "ok": False,
        "error": {"code": code, "message": message, "retriable": False},
    }
    result.update({k: v for k, v in identifiers.items() if v})
    return result


def _invoke(function: Callable[[], dict[str, Any]], **identifiers: str | None) -> dict[str, Any]:
    try:
        return _ok(function())
    except ValueError as exc:
        return _failure("INVALID_ARGUMENT", str(exc), **identifiers)
    except Exception as exc:  # pragma: no cover - defensive
        return _failure("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", **identifiers)


# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """Resolve the session data directory.

    Override with the ``SESSION_MANAGER_DATA_DIR`` env var; otherwise default
    to a platform-local dir under the user's home. Independent from any other
    MCP — point the env var at another data dir if you want to share.
    """
    env = os.environ.get("SESSION_MANAGER_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "session-manager"


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def create_server() -> MCPServer:
    store = SessionStore(_data_dir())
    server = MCPServer(
        name="session-manager",
        title="Session Manager",
        description="Capture, store and validate platform login cookies",
        version="0.1.0",
        instructions=(
            "Use resource_session_status to see which platforms need login. "
            "The host captures cookies via its browser tools, then calls "
            "resource_session_save. Use deep=true on status to actively verify "
            "a stored session is still accepted server-side. Raw cookies are "
            "never returned."
        ),
    )

    @server.tool(structured_output=True)
    def resource_session_status(
        contract_version: Literal["1.0.0"],
        platforms: list[str] | None = None,
        deep: bool = False,
    ) -> dict[str, Any]:
        """Check which platforms have valid, expired, or missing sessions.

        Returns a batch status for all known platforms or only the requested
        ones. ``needs_login`` lists platforms that require user login. Set
        ``deep`` to true to actively probe each stored session against its
        platform so a cookie that is still file-valid but rejected server-side
        is reported as ``probe_status="invalid"``.
        """
        return _invoke(lambda: _session_status(store, platforms, deep))

    @server.tool(structured_output=True)
    def resource_session_save(
        contract_version: Literal["1.0.0"],
        platform: str,
        session_data: dict[str, Any],
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist a captured browser session (cookies/tokens) for a platform.

        Called after the user completes login via the host's browser
        automation. The stored session is reused until it expires.
        ``session_data`` should be ``{"cookies": [...]}``.
        """
        return _invoke(
            lambda: store.save(platform, session_data, expires_at=expires_at),
            platform=platform,
        )

    @server.tool(structured_output=True)
    def resource_session_delete(
        contract_version: Literal["1.0.0"],
        platform: str,
    ) -> dict[str, Any]:
        """Remove a stored platform session."""
        return _invoke(lambda: store.delete(platform), platform=platform)

    return server


def _session_status(
    store: SessionStore,
    platforms: list[str] | None,
    deep: bool,
) -> dict[str, Any]:
    statuses = store.get_status(platforms)
    entries = [s.to_dict() for s in statuses]
    if deep:
        for entry, status in zip(entries, statuses):
            if status.status != "valid":
                continue
            probe = store.validate(status.platform)
            entry["probe_status"] = probe["probe_status"]
            entry["probed_at"] = probe["probed_at"]
            if probe.get("detail"):
                entry["probe_detail"] = probe["detail"]
    return {
        "sessions": entries,
        "needs_login": [
            {"platform": s.platform, "label": s.label, "login_url": s.login_url}
            for s in statuses
            if s.status in ("missing", "expired") and s.login_url
        ],
    }


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
