"""Thin stdio MCP exposing resource capability contracts and execution."""

from __future__ import annotations

from typing import Annotated, Any, Callable, Literal

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
            "wechat、shuge、zjer、generic（下划线会自动归一为连字符）。"
            "普通网页发现通常由宿主 Web Search 完成；generic 是 MCP 内补充网页搜索。"
        )
    )
    queries: list[str] = Field(
        min_length=1,
        description=(
            "平台搜索短语列表。每项应是可直接输入对应平台搜索框的自然 query，"
            '如 ["火山喷发 原理 动画"]。'
        ),
    )
    tabs: list[str] | None = Field(
        default=None,
        description=(
            "仅 smartedu 有效：分类代码子集，如 tchMaterial（教材）/qualityCourse（课程）/"
            "prepareLesson（备课）/sedu（德育）/specialEdu（特教）；不传则搜全部分类。"
        ),
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
        description=(
            "Learning-resource capabilities for platform search, creator browsing, URL import, "
            "inspection, download jobs, batch enumeration/paging, cancellation and archive"
        ),
        version="0.3.0",
        instructions=(
            "This MCP exposes resource capabilities and execution facts; it does not own user intent, "
            "search strategy, candidate ranking, selection semantics or classification decisions. "
            "Platform search, creator preview, known-URL import, inspection, download jobs, large-result "
            "batch enumeration, paging, cancellation and archive are exposed as separate tools. "
            "Resource handles are process-local. Download and batch operations return persistent job handles; "
            "batch items are paged back with resource_batch_read. Use each tool's schema for accepted identifiers, "
            "mode-specific inputs and result handling."
        ),
    )

    @server.tool(structured_output=True)
    def resource_search(
        search_tasks: Annotated[
            list[SearchTask],
            Field(description="一个或多个平台搜索任务；返回候选及当前进程内 resource_id。"),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "每条平台 query 请求的候选数，默认 8。只控制本次响应规模，"
                    "不表示平台总结果数，也不是完整枚举上限。"
                ),
            ),
        ] = 8,
    ) -> dict[str, Any]:
        """Search configured platforms and return candidate resource handles."""
        return _call(
            lambda: resource_service.search(
                [task.model_dump() for task in search_tasks], limit=limit
            )
        )

    @server.tool(structured_output=True)
    def resource_browse_creator(
        platform: Annotated[
            str,
            Field(description="创作者所在平台 id；仅当前支持 creator browse 的平台有效。"),
        ],
        creator_id: Annotated[
            str,
            Field(
                description=(
                    "创作者定位符。优先传之前发现的该创作者任一作品 resource_id（res_...），"
                    "MCP 会自行解析创作者；也可传平台原生 creator id 或支持的完整主页 URL。"
                    "已有 resource_id 时不要手工重建很长的平台 creator id。"
                )
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "本次预览请求的作品数，默认 50。它是交互式预览规模，不是全部作品上限；"
                    "完整枚举使用 resource_batch_collect。"
                ),
            ),
        ] = 50,
    ) -> dict[str, Any]:
        """Preview a limited set of works from one creator."""
        return _call(
            lambda: resource_service.browse_creator(platform, creator_id, limit=limit)
        )

    @server.tool(structured_output=True)
    def resource_import_url(
        source_url: Annotated[
            str,
            Field(
                description=(
                    "已经明确知道的 HTTP(S) 资源/网页 URL。该工具不负责搜索网页；"
                    "它注册当前进程内 resource_id，并立即解析资源事实。"
                )
            ),
        ]
    ) -> dict[str, Any]:
        """Register a known external URL as a process-local resource handle and inspect it."""
        return _call(lambda: resource_service.import_url(source_url), source_url=source_url)

    @server.tool(structured_output=True)
    def resource_inspect(
        resource_id: Annotated[
            str,
            Field(
                description=(
                    "Search/Browse/Import 返回的当前进程内 resource_id；"
                    "返回当前可访问性、可获取表示及已解析资源事实。"
                )
            ),
        ]
    ) -> dict[str, Any]:
        """Resolve current availability and concrete representations for one resource handle."""
        return _call(lambda: resource_service.inspect(resource_id), resource_id=resource_id)

    @server.tool(structured_output=True)
    def resource_download(
        resource_ids: Annotated[
            list[str],
            Field(
                min_length=1,
                description="要下载的当前进程内 resource_id 列表；调用返回 download job_id。",
            ),
        ],
        preferred_container: Annotated[
            str,
            Field(
                description=(
                    '表示容器偏好，默认 "original"，通常保持默认。只有确实需要某个已有表示时'
                    "才指定 pdf/mp4/mp3/html 等；它不是任意格式转换请求。"
                )
            ),
        ] = "original",
    ) -> dict[str, Any]:
        """Start a download job for the supplied resource handles."""
        return _call(
            lambda: resource_service.download(
                resource_ids, preferred_container=preferred_container
            )
        )

    @server.tool(structured_output=True)
    def resource_job_status(
        job_id: Annotated[
            str,
            Field(description="resource_download 或 resource_batch_collect 返回的 job_id。"),
        ]
    ) -> dict[str, Any]:
        """Return status/progress for a download or batch job.

        Download jobs may include files. Batch items are not returned here; read
        collected batch items with resource_batch_read.
        """
        return _call(lambda: resource_service.job_status(job_id), job_id=job_id)

    @server.tool(structured_output=True)
    def resource_job_cancel(
        job_id: Annotated[
            str,
            Field(description="要取消的 queued/running/cancelling 下载或批量 job_id。"),
        ]
    ) -> dict[str, Any]:
        """Cancel a queued or running download or batch job."""
        return _call(lambda: resource_service.job_cancel(job_id), job_id=job_id)

    @server.tool(structured_output=True)
    def resource_batch_collect(
        platform: Annotated[
            str,
            Field(description="批量枚举目标平台 id；具体 mode 只在支持的平台有效。"),
        ],
        mode: Annotated[
            Literal["creator_full", "time_range_search", "catalog_expand"],
            Field(
                description=(
                    "creator_full=完整枚举一个创作者；time_range_search=Bilibili 关键词按日期范围枚举；"
                    "catalog_expand=SmartEdu 教材规格展开。"
                )
            ),
        ] = "creator_full",
        creator_id: Annotated[
            str,
            Field(
                description=(
                    "仅 creator_full 使用。优先传该创作者任一已发现作品 resource_id（res_...）；"
                    "也可传平台原生 creator id 或支持的完整主页 URL。"
                )
            ),
        ] = "",
        keyword: Annotated[
            str,
            Field(description="仅 time_range_search 使用：Bilibili 搜索关键词。"),
        ] = "",
        start_day: Annotated[
            str,
            Field(description="仅 time_range_search 使用：起始日期 YYYY-MM-DD，包含当天。"),
        ] = "",
        end_day: Annotated[
            str,
            Field(description="仅 time_range_search 使用：结束日期 YYYY-MM-DD，包含当天。"),
        ] = "",
        specs: Annotated[
            list[str] | None,
            Field(description="仅 catalog_expand 使用：SmartEdu 教材规格标识列表。"),
        ] = None,
        max_items: Annotated[
            int | None,
            Field(
                description=(
                    "可选显式结果上限。None 表示枚举到来源真实结束；"
                    "只有确实需要最多 N 条时才传正整数。"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Start a large-result enumeration job with items stored outside the conversation.

        creator_full uses creator_id; time_range_search uses keyword plus start_day/end_day;
        catalog_expand uses specs. Read collected items with resource_batch_read.
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
        job_id: Annotated[
            str,
            Field(description="resource_batch_collect 返回的 batch job_id。"),
        ],
        offset: Annotated[
            int,
            Field(ge=0, description="从第几个结果开始读取，0-based，默认 0。"),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "本页读取条数，默认 20，服务端单页最多返回 50。"
                    "分页大小不截断磁盘上的完整结果集。"
                ),
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """Read one page from a batch job's stored result set."""
        return _call(
            lambda: resource_service.batch_read(job_id, offset=offset, limit=limit),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_archive(
        job_id: Annotated[
            str,
            Field(
                description=(
                    "已产生真实文件且状态为 succeeded/partial 的 download job_id；"
                    "纯 batch 枚举 Job 没有可归档下载文件。"
                )
            ),
        ],
        domain_id: Annotated[
            str,
            Field(
                description=(
                    "学习资料库顶层语义领域 id，由调用方根据资源内容选择；"
                    "分类不确定可留空进入待分类区域。"
                )
            ),
        ] = "",
        topic: Annotated[
            str,
            Field(description="自由文本学习主题，例如“天文与宇宙”“自然拼读”；可留空。"),
        ] = "",
    ) -> dict[str, Any]:
        """Move real files from a completed download job into the learning library."""
        return _call(
            lambda: resource_service.archive(
                job_id, domain_id=domain_id, topic=topic
            ),
            job_id=job_id,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
