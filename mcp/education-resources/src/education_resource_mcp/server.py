"""MCP 2.0 stdio adapter for the education resource domain service."""

from __future__ import annotations

from typing import Any, Callable, Literal

from mcp.server.mcpserver import MCPServer

from .errors import DomainError, failure, ok
from .models import (
    ArchiveMetadata,
    DownloadOptions,
    FlowTask,
    LibraryFilters,
    SearchFilters,
    SearchTask,
)
from .service import ResourceService


CONTRACT_VERSION = "1.0.0"


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
        description="Search, present, select, confirm, download, inspect, and archive education resources",
        version="0.2.0",
        instructions=(
            "Use contract 1.0.0. Start a FlowTask, search into a ResultSet, save the exact "
            "resources actually shown with resource_presentation_save, then save only the "
            "user-selected display positions. Downloads require prepare, explicit user "
            "confirmation, then start. Use resource_flow_status to recover durable state. "
            "Never invent IDs, positions, paths, commands, Providers, or download URLs."
        ),
    )

    @server.tool(structured_output=True)
    def resource_flow_start(
        contract_version: Literal["1.0.0"],
        idempotency_key: str,
        task: FlowTask,
    ) -> dict[str, Any]:
        """Start a durable education-resource FlowTask."""
        return _invoke(
            lambda: resource_service.flow_start(idempotency_key, task.model_dump())
        )

    @server.tool(structured_output=True)
    def resource_search(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        search_tasks: list[SearchTask],
        task_version: int | None = None,
        mode: Literal["replace", "extend"] = "replace",
        base_result_set_id: str | None = None,
        filters: SearchFilters | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search across multiple platforms in parallel into a durable ResultSet."""
        return _invoke(
            lambda: resource_service.search(
                flow_id,
                idempotency_key,
                [t.model_dump() for t in search_tasks],
                task_version=task_version,
                mode=mode,
                base_result_set_id=base_result_set_id,
                filters=filters.model_dump(exclude_none=True) if filters else None,
                limit=limit,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_browse_creator(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        platform: str,
        creator_id: str,
        task_version: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Browse a creator's content list when the platform supports it."""
        return _invoke(
            lambda: resource_service.browse_creator(
                flow_id,
                idempotency_key,
                platform,
                creator_id,
                task_version=task_version,
                limit=limit,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_inspect(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        resource_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Inspect one existing Flow resource through the active profile."""
        return _invoke(
            lambda: resource_service.inspect(
                flow_id,
                idempotency_key,
                resource_id,
            ),
            flow_id=flow_id,
            resource_id=resource_id,
        )

    @server.tool(structured_output=True)
    def resource_presentation_save(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        result_set_id: str,
        displayed_resource_ids: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Persist the exact ResultSet resources and order actually shown to the user."""
        return _invoke(
            lambda: resource_service.presentation_save(
                flow_id,
                result_set_id,
                displayed_resource_ids,
                idempotency_key,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_selection_save(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        presentation_id: str,
        presented_version: int,
        selected_positions: list[int],
    ) -> dict[str, Any]:
        """Save explicit user choices by position from the current Presentation."""
        return _invoke(
            lambda: resource_service.selection_save(
                flow_id,
                idempotency_key,
                presentation_id,
                presented_version,
                selected_positions,
            ),
            flow_id=flow_id,
        )

    @server.tool(structured_output=True)
    def resource_flow_status(
        contract_version: Literal["1.0.0"],
        flow_id: str,
    ) -> dict[str, Any]:
        """Recover the authoritative current Flow state and allowed next actions."""
        return _invoke(lambda: resource_service.flow_status(flow_id), flow_id=flow_id)

    @server.tool(structured_output=True)
    def resource_flow_list(
        contract_version: Literal["1.0.0"],
        limit: int = 20,
    ) -> dict[str, Any]:
        """List recent flows to discover or recover flow state after context loss.

        Returns flows ordered by most recently updated.  Use when the current
        flow_id is unknown, conversation context was compressed, or the user
        refers to a previous task without naming it.
        """
        return _invoke(lambda: resource_service.flow_list(limit=limit))

    @server.tool(structured_output=True)
    def resource_download_prepare(
        contract_version: Literal["1.0.0"],
        flow_id: str,
        idempotency_key: str,
        presentation_id: str,
        presented_version: int,
        selection_version: int,
        selection_digest: str,
        options: DownloadOptions | None = None,
    ) -> dict[str, Any]:
        """Prepare a Plan from the current Selection without downloading."""
        return _invoke(
            lambda: resource_service.download_prepare(
                flow_id,
                idempotency_key,
                selection_version,
                presentation_id=presentation_id,
                presented_version=presented_version,
                selection_digest=selection_digest,
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
        """Start an asynchronous Job after explicit user confirmation.

        Only flow_id, plan_id, confirmation_token and idempotency_key are
        required.  All binding values (presentation, selection, digests) are
        looked up from the stored Plan.
        """
        return _invoke(
            lambda: resource_service.download_start(
                flow_id,
                plan_id,
                confirmation_token,
                idempotency_key,
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
        """Return durable status and validated asset metadata for a download Job."""
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
        """Request cancellation; cancelled assets are quarantined."""
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
        """Archive a ready Asset by asset_id; local paths are never accepted."""
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
        """Search archived Assets by bounded metadata filters."""
        return _invoke(
            lambda: resource_service.library_search(
                flow_id,
                filters=filters.model_dump(exclude_none=True) if filters else None,
                cursor=cursor,
                limit=limit,
            ),
            flow_id=flow_id,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
