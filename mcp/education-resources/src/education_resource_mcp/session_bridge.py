"""Read-only bridge to the standalone session-manager credential store.

The public login/capture tools live in the independent session-manager MCP.  When
its data directory is configured here, education-resources imports that package's
SessionStore so both processes use the same secure on-disk format (including
Windows DPAPI).  The legacy in-package store remains only for isolated tests and
explicit deployments that do not configure the standalone store.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .config import Settings
from .sessions import SessionStore as LegacySessionStore


def create_session_store(settings: Settings) -> Any:
    """Create the credential reader selected by trusted process configuration.

    Never silently fall back when a standalone store path was explicitly set:
    doing so would make login appear successful while authenticated adapters read
    a different empty store.
    """

    data_dir = settings.session_manager_data_dir
    if data_dir is None:
        return LegacySessionStore(settings.data_dir)

    try:
        module = import_module("session_manager.store")
        store_type = getattr(module, "SessionStore")
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR is configured, "
            "but openclaw-session-manager is not installed in this MCP environment"
        ) from exc
    return store_type(data_dir)
