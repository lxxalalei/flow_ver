"""Thin stdio MCP exposing search, download and archive capabilities."""

from __future__ import annotations

from typing import Any, Callable

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from .errors import DomainError
from .service import ResourceService


class SearchTask(BaseModel):
    """One platform plus its search phrases for resource_search."""

    platform: str = Field(
        description=(
            "平台 id：bilibili、douyin、zhihu、smartedu、ximalaya、cctv、yixi、"
            "kepu、baiduwenku、runoob、nlc、open163、annas-archive、weibo、"
            "wechat、shuge、zjer、generic（下划线会自动归一为连字符）"
        )
    )
    queries: list[str] = Field(
        min_length=1,
        description="1-3 条真实搜索短语（像在平台搜索框里输入的完整短句），"
        '如 ["火山喷发 原理 动画"]',
    )
    tabs: list[str] | None = Field(
        default=None,
        description="仅 smartedu 有效：智慧教育平台分类代码子集，如 tchMaterial（教材）/"
        "qualityCourse（课程）/prepareLesson（备课）/sedu（德育）/specialEdu（特教）；"
        "不传则搜全部分类",
    )


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
        description="Search, inspect, download and archive learning resources",
        version="0.3.0",
        instructions=(
            "This MCP is a capability layer, not a workflow engine. "
            "Use resource_search/resource_browse_creator to discover platform resources. "
            "Use the host web search for general web discovery, then resource_import_url for a selected URL. "
            "Use resource_inspect only when details affect the decision. "
            "Call resource_download only after the user has explicitly asked to download selected resources. "
            "After a successful or partial download, classify the files and call resource_archive. "
            "Use resource_job_status for progress or resource_job_cancel to stop a job. "
            "For a creator's complete catalogue use resource_batch_collect without max_items and page it with resource_batch_read. "
            "Set max_items only when the user explicitly wants a bound. "
            "Resource handles are process-local. If one is lost after restart, re-import the selected URL when known; "
            "otherwise precisely relocate that resource instead of rerunning the whole research task. "
            "Download and batch jobs run in detached workers and survive an MCP restart; "
            "job_status reports interrupted for jobs whose worker died."
        ),
    )

    @server.tool(structured_output=True)
    def resource_search(
        search_tasks: list[SearchTask],
        limit: int = 8,
    ) -> dict[str, Any]:
        """Run configured platform search adapters and return resource handles."""
        return _call(
            lambda: resource_service.search(
                [task.model_dump() for task in search_tasks], limit=limit
            )
        )

    @server.tool(structured_output=True)
    def resource_browse_creator(
        platform: str,
        creator_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Preview resources published by one creator."""
        return _call(
            lambda: resource_service.browse_creator(
                platform,
                creator_id,
                limit=limit,
            )
        )

    @server.tool(structured_output=True)
    def resource_import_url(source_url: str) -> dict[str, Any]:
        """Register an external URL as a process-local resource handle and inspect it."""
        return _call(
            lambda: resource_service.import_url(source_url),
            source_url=source_url,
        )

    @server.tool(structured_output=True)
    def resource_inspect(resource_id: str) -> dict[str, Any]:
        """Inspect one resource for availability and concrete representations."""
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
        """Return progress, files and failures for one download or batch job."""
        return _call(
            lambda: resource_service.job_status(job_id),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_job_cancel(job_id: str) -> dict[str, Any]:
        """Cancel a queued or running job."""
        return _call(
            lambda: resource_service.job_cancel(job_id),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_batch_collect(
        platform: str,
        mode: str = "creator_full",
        creator_id: str = "",
        keyword: str = "",
        start_day: str = "",
        end_day: str = "",
        specs: list[str] | None = None,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        """Enumerate a large result set into ``results.jsonl``.

        Omit max_items for complete enumeration. Supply max_items only when
        the user explicitly requests a bound. Results are streamed to disk
        and read back with resource_batch_read.

        Modes:
        - creator_full: creator id, profile URL, or resource_id from one work
        - time_range_search: Bilibili keyword over [start_day, end_day]
        - catalog_expand: SmartEdu textbook specs
        """
        return _call(
            lambda: resource_service.batch_collect(
                platform,
                mode=mode,
                creator_id=creator_id,
                keyword=keyword,
                start_day=start_day,
                end_day=end_day,
                specs=specs,
                max_items=max_items,
            )
        )

    @server.tool(structured_output=True)
    def resource_batch_read(
        job_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Read one page (default 20, max 50) without truncating the stored result set."""
        return _call(
            lambda: resource_service.batch_read(job_id, offset=offset, limit=limit),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_archive(
        job_id: str,
        domain_id: str = "",
        topic: str = "",
    ) -> dict[str, Any]:
        """Move completed download files into the learning library by domain/topic."""
        return _call(
            lambda: resource_service.archive(
                job_id,
                domain_id=domain_id,
                topic=topic,
            ),
            job_id=job_id,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
