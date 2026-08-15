"""Thin stdio MCP exposing search and download capabilities."""

from __future__ import annotations

from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

from .errors import DomainError
from .service import ResourceService


def _call(function: Callable[[], dict[str, Any]], **ids: str) -> dict[str, Any]:
    try:
        return {"ok": True, **function()}
    except DomainError as exc:
        result: dict[str, Any] = {"ok": False, "error": exc.to_dict()}
        result.update({key: value for key, value in ids.items() if value})
        return result


def create_server(service: ResourceService | None = None) -> MCPServer:
    resource_service = service or ResourceService()
    server = MCPServer(
        name="education-resources",
        title="Education Resources",
        description="Search, inspect and download learning resources",
        version="0.3.0",
        instructions=(
            "This MCP is a capability layer, not a workflow engine. "
            "Use resource_search/resource_browse_creator to discover resources. "
            "Use resource_inspect only when details affect the decision. "
            "Call resource_download only after the user has explicitly asked to download the selected resources. "
            "Then use resource_job_status for progress or resource_job_cancel to stop the job. "
            "Resource handles are process-local; if the MCP process restarts, search again."
        ),
    )

    @server.tool(structured_output=True)
    def resource_search(
        search_tasks: list[dict[str, Any]],
        limit: int = 8,
    ) -> dict[str, Any]:
        """Run the configured search adapters and return resource handles."""
        return _call(lambda: resource_service.search(search_tasks, limit=limit))

    @server.tool(structured_output=True)
    def resource_browse_creator(
        platform: str,
        creator_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List resources published by one creator when the platform supports it."""
        return _call(
            lambda: resource_service.browse_creator(
                platform,
                creator_id,
                limit=limit,
            )
        )

    @server.tool(structured_output=True)
    def resource_inspect(resource_id: str) -> dict[str, Any]:
        """Inspect one search result for availability and concrete representations."""
        return _call(
            lambda: resource_service.inspect(resource_id),
            resource_id=resource_id,
        )

    @server.tool(structured_output=True)
    def resource_download(
        resource_ids: list[str],
        preferred_container: str = "original",
    ) -> dict[str, Any]:
        """Start downloading resources the user has explicitly chosen."""
        return _call(
            lambda: resource_service.download(
                resource_ids,
                preferred_container=preferred_container,
            )
        )

    @server.tool(structured_output=True)
    def resource_job_status(job_id: str) -> dict[str, Any]:
        """Return progress, downloaded files and failures for one download job."""
        return _call(
            lambda: resource_service.job_status(job_id),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_job_cancel(job_id: str) -> dict[str, Any]:
        """Cancel a queued or running download job."""
        return _call(
            lambda: resource_service.job_cancel(job_id),
            job_id=job_id,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
