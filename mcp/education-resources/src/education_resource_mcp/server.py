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
            "Use resource_search/resource_browse_creator to discover resources. "
            "Use resource_inspect only when details affect the decision. "
            "Call resource_download only after the user has explicitly asked to download the selected resources. "
            "After a successful or partial download, classify the files and call resource_archive to move them into the learning library. "
            "Use resource_job_status for progress or resource_job_cancel to stop the job. "
            "For bulk enumeration (a creator's full works) use resource_batch_collect and "
            "page with resource_batch_read instead of browse_creator with a huge limit. "
            "For web pages found with the host's own web search, register them with "
            "resource_import_url to turn the URL into a downloadable resource handle. "
            "Resource handles are process-local; if the MCP process restarts, search again. "
            "Download and batch jobs run in detached workers and survive an MCP restart; "
            "job_status reports interrupted for jobs whose worker died, and re-downloading starts from scratch."
        ),
    )

    @server.tool(structured_output=True)
    def resource_search(
        search_tasks: list[SearchTask],
        limit: int = 8,
    ) -> dict[str, Any]:
        """Run the configured search adapters and return resource handles.

        Each task picks one platform and carries its queries, e.g.
        [{"platform": "bilibili", "queries": ["火山喷发 原理 动画"]}].
        """
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
        """List resources published by one creator when the platform supports it."""
        return _call(
            lambda: resource_service.browse_creator(
                platform,
                creator_id,
                limit=limit,
            )
        )

    @server.tool(structured_output=True)
    def resource_import_url(source_url: str) -> dict[str, Any]:
        """Register an external URL as a resource handle and inspect it.

        The bridge from host-side web search to the MCP pipeline: URLs the
        agent found with its own web search become resource_ids that can be
        downloaded, materialized and archived like any search candidate.
        """
        return _call(
            lambda: resource_service.import_url(source_url),
            source_url=source_url,
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

    @server.tool(structured_output=True)
    def resource_batch_collect(
        platform: str,
        mode: str = "creator_full",
        creator_id: str = "",
        keyword: str = "",
        start_day: str = "",
        end_day: str = "",
        specs: list[str] | None = None,
        max_items: int = 500,
    ) -> dict[str, Any]:
        """Enumerate resources in bulk into a results file (batch mode).

        Runs as a detached job that survives restarts; the response stays
        small (job handle only) and the full list lands in results.jsonl.
        Page through it with resource_batch_read instead of pulling the whole
        list into the conversation.

        Modes:
        - creator_full: a creator's full works; creator_id is the platform
          creator id (sec_uid / mid / profile URL) or a resource_id of one
          of that creator's works from a previous search (recommended)
        - time_range_search: a keyword's results day by day over
          [start_day, end_day] (YYYY-MM-DD), currently bilibili only
        - catalog_expand: a SmartEdu textbook's national-lesson courses via
          CDN JSON; specs like ["语文/一年级/上册/统编版"]
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
        """Read one page (default 20, max 50 items) of a batch_collect job."""
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
        """Move completed download files into the learning library by domain/topic.

        domain_id accepts a configured domain id such as natural_science. Leave it
        empty when classification is genuinely uncertain; the files go to 待分类.
        topic is a free topic folder such as 天文与宇宙.
        """
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
