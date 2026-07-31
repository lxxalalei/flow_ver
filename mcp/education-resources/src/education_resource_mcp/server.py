"""MCP 2.0 stdio adapter for the education resource domain service."""

from __future__ import annotations

from typing import Any, Callable, Literal

from mcp.server.mcpserver import MCPServer

from .errors import DomainError, failure, ok
from .models import ArchiveMetadata, DownloadOptions, FlowIntent, LibraryFilters, SearchFilters
from .service import ResourceService


def _invoke(
    function: Callable[[], dict[str, Any]], **identifiers: str | None
) -> dict[str, Any]:
    try:
        return ok(function())
    except DomainError as exc:
        return failure(exc, **identifiers)


def create_server(service: ResourceService | None = None) -> MCPServer:
    resource_service = service or ResourceService()
    server = MCPServer(
        name="education-resources",
        title="Education Resources",
        description="Search, select, confirm, download, inspect, and archive education resources",
        version="0.1.0",
        instructions=(
            "Start a flow before searching. Save only explicitly selected resource IDs. "
            "Downloads require prepare, user confirmation, then start. Never invent IDs."
        ),
    )

    @server.tool(structured_output=True)
    def resource_flow_start(
        contract_version: Literal["1.0.0"],
        idempotency_key: str,
        intent: FlowIntent,
    ) -> dict[str, Any]:
        """Start a durable education-resource flow and return its flow_id."""
        return _invoke(
            lambda: resource_service.flow_start(idempotency_key, intent.model_dump())
        )

    @server.tool(structured_output=True)
    def resource_search(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        query: str,
        filters: SearchFilters | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search and persist the exact candidate set presented for this flow."""
        return _invoke(
            lambda: resource_service.search(
                flow_id,
                idempotency_key,
                query,
                filters=filters.model_dump(exclude_none=True) if filters else None,
                cursor=cursor,
                limit=limit,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_selection_save(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        presented_version: int,
        selected_resource_ids: list[str],
    ) -> dict[str, Any]:
        """Persist the user's explicit selection from the current presented set."""
        return _invoke(
            lambda: resource_service.selection_save(
                flow_id, idempotency_key, presented_version, selected_resource_ids
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_download_prepare(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        selection_version: int,
        options: DownloadOptions | None = None,
    ) -> dict[str, Any]:
        """Prepare a bounded download plan without downloading anything."""
        return _invoke(
            lambda: resource_service.download_prepare(
                flow_id,
                idempotency_key,
                selection_version,
                options=options.model_dump(exclude_none=True) if options else None,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_download_start(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        plan_id: str,
        confirmation_token: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Start an asynchronous download only after explicit user confirmation."""
        return _invoke(
            lambda: resource_service.download_start(
                flow_id, plan_id, confirmation_token, idempotency_key
            ),
            flow_id=flow_id,
            plan_id=plan_id,
        )

    @server.tool(structured_output=True)
    def resource_job_status(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        """Return durable status and validated asset metadata for a download job."""
        return _invoke(
            lambda: resource_service.job_status(flow_id, job_id),
            flow_id=flow_id,
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_job_cancel(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        job_id: str,
        idempotency_key: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Request cancellation; cancelled assets are quarantined and cannot be archived."""
        return _invoke(
            lambda: resource_service.job_cancel(
                flow_id, job_id, idempotency_key, reason
            ),
            flow_id=flow_id,
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_archive(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        job_id: str,
        asset_id: str,
        idempotency_key: str,
        metadata: ArchiveMetadata | None = None,
    ) -> dict[str, Any]:
        """Archive a ready asset by asset_id; local paths are never accepted."""
        return _invoke(
            lambda: resource_service.archive(
                flow_id,
                job_id,
                asset_id,
                idempotency_key=idempotency_key,
                metadata=metadata.model_dump(exclude_none=True) if metadata else None,
            ),
            flow_id=flow_id,
            job_id=job_id,
            asset_id=asset_id,
        )

    @server.tool(structured_output=True)
    def resource_library_search(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        filters: LibraryFilters | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search archived assets by title or metadata."""
        return _invoke(
            lambda: resource_service.library_search(
                flow_id,
                filters=filters.model_dump(exclude_none=True) if filters else None,
                cursor=cursor,
                limit=limit,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_session_status(
        contract_version: Literal["1.0.0"],
        platforms: list[str] | None = None,
        deep: bool = False,
    ) -> dict[str, Any]:
        """Check which platforms have valid, expired, or missing sessions.

        Returns a batch status for all known platforms or only the requested
        ones.  ``needs_login`` lists platforms that require user login before
        search or download can proceed.  Set ``deep`` to true to actively
        probe each stored session against the platform so a cookie that is
        still file-valid but rejected server-side is reported as
        ``probe_status="invalid"``.
        """
        return _invoke(
            lambda: resource_service.session_status(platforms, deep=deep)
        )

    @server.tool(structured_output=True)
    def resource_session_save(
        contract_version: Literal["1.0.0"],
        platform: str,
        session_data: dict[str, Any],
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist a captured browser session (cookies/tokens) for a platform.

        Called after the user completes login via browser automation.  The
        stored session is reused for subsequent search and download requests
        until it expires.
        """
        return _invoke(
            lambda: resource_service.session_save(
                platform, session_data, expires_at=expires_at
            ),
            platform=platform,
        )

    @server.tool(structured_output=True)
    def resource_session_delete(
        contract_version: Literal["1.0.0"],
        platform: str,
    ) -> dict[str, Any]:
        """Remove a stored platform session."""
        return _invoke(
            lambda: resource_service.session_delete(platform),
            platform=platform,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
