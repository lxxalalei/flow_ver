"""Thin stdio MCP exposing resource and session capabilities."""

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


def _session_status(
    service: ResourceService,
    platforms: list[str] | None,
    deep: bool,
) -> dict[str, Any]:
    statuses = service.session_store.get_status(platforms)
    sessions: list[dict[str, Any]] = []
    needs_login: list[dict[str, Any]] = []
    for status in statuses:
        entry = status.to_dict()
        if deep and status.status == "stored" and status.config.probe_supported:
            probe = service.session_store.validate(status.platform)
            entry["probe_status"] = probe["probe_status"]
            entry["probed_at"] = probe["probed_at"]
            if probe.get("detail"):
                entry["probe_detail"] = probe["detail"]
        sessions.append(entry)
        if (
            status.config.auth_kind != "none"
            and (
                status.status in {"missing", "expired", "invalid"}
                or entry.get("probe_status") == "invalid"
            )
        ):
            needs_login.append(status.config.public_metadata())
    return {"sessions": sessions, "needs_login": needs_login}


def create_server(service: ResourceService | None = None) -> MCPServer:
    resource_service = service or ResourceService()
    server = MCPServer(
        name="education-resources",
        title="Education Resources",
        description=(
            "Learning-resource search, inspection, download, batch/archive and "
            "platform session capabilities"
        ),
        version="0.4.0",
        instructions=(
            "This MCP exposes factual resource capabilities and a small auxiliary session store; "
            "it does not own user intent, search strategy, candidate ranking, selection semantics "
            "or classification decisions. Session tools are not a preflight step: use them only "
            "after a concrete AUTH_REQUIRED result or when the user explicitly asks to manage a "
            "platform session. Public operations must not be forced through login merely because "
            "the platform also has authenticated capabilities. Authentication field selection is "
            "owned by the MCP: pass browser session capture through without manually choosing or "
            "reconstructing cookies/tokens. A logical resource may naturally materialize to more "
            "than one file; do not infer that a landing webpage is the only downloadable form or "
            "invent a file format to make it downloadable. Batch collection only enumerates "
            "candidates and never grants download intent: download a complete batch_job_id only "
            "after the user explicitly selects all of that batch; use resource_ids for an explicitly "
            "selected subset. Resource handles are process-local; download and batch operations "
            "return persistent job handles."
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
        return _call(
            lambda: resource_service.search(
                [task.model_dump() for task in search_tasks], limit=limit
            )
        )

    @server.tool(structured_output=True)
    def resource_browse_creator(
        platform: Annotated[
            str,
            Field(description="创作者所在平台 id；仅支持 creator browse 的平台有效。"),
        ],
        creator_id: Annotated[
            str,
            Field(
                description=(
                    "优先传已发现作品 resource_id；也可传平台原生 creator id "
                    "或支持的完整主页 URL。"
                )
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "交互式预览数量，默认 50；完整枚举使用 resource_batch_collect。"
                ),
            ),
        ] = 50,
    ) -> dict[str, Any]:
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
                    "会识别已接入平台 URL，否则按 generic 网页处理。"
                )
            ),
        ]
    ) -> dict[str, Any]:
        return _call(lambda: resource_service.import_url(source_url), source_url=source_url)

    @server.tool(structured_output=True)
    def resource_inspect(
        resource_id: Annotated[
            str,
            Field(
                description=(
                    "Search/Browse/Import/BatchRead 返回的当前进程内 resource_id；"
                    "只在未知事实会影响选择或获取时调用，返回当前可访问性、可获取内容及已解析资源事实。"
                )
            ),
        ]
    ) -> dict[str, Any]:
        return _call(lambda: resource_service.inspect(resource_id), resource_id=resource_id)

    @server.tool(structured_output=True)
    def resource_download(
        resource_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "用户已经明确选中的当前进程内 resource_id 列表。选择批量结果中的部分资源时，"
                    "先用 resource_batch_read 获取这些候选的 resource_id。与 batch_job_id 二选一。"
                    "一个 resource_id 可能自然产生一个或多个真实文件。"
                ),
            ),
        ] = None,
        batch_job_id: Annotated[
            str,
            Field(
                description=(
                    "仅当用户明确选择一个已完整 succeeded 的 batch_collect 结果中的全部资源时传入；"
                    "MCP 会把该 results.jsonl 作为下载来源，无需 Agent 分页搬运所有 URL。"
                    "批量枚举完成本身不等于用户选择了全部。与 resource_ids 二选一。"
                )
            ),
        ] = "",
        preferred_container: Annotated[
            str,
            Field(
                description=(
                    '主表示容器偏好，默认 "original"，表示按资源本身的自然交付方式获取；'
                    "自然交付可以包含多个文件。只有用户确实要求某个当前已有主表示时才指定 "
                    "pdf/mp4/mp3/html 等；不要因 landing URL 是网页而自行猜格式，也不是任意格式转换请求。"
                )
            ),
        ] = "original",
    ) -> dict[str, Any]:
        return _call(
            lambda: resource_service.download(
                resource_ids,
                batch_job_id=batch_job_id,
                preferred_container=preferred_container,
            ),
            batch_job_id=batch_job_id,
        )

    @server.tool(structured_output=True)
    def resource_job_status(
        job_id: Annotated[
            str,
            Field(description="resource_download 或 resource_batch_collect 返回的 job_id。"),
        ]
    ) -> dict[str, Any]:
        return _call(lambda: resource_service.job_status(job_id), job_id=job_id)

    @server.tool(structured_output=True)
    def resource_job_cancel(
        job_id: Annotated[
            str,
            Field(description="要取消的 queued/running/cancelling 下载或批量 job_id。"),
        ]
    ) -> dict[str, Any]:
        return _call(lambda: resource_service.job_cancel(job_id), job_id=job_id)

    @server.tool(structured_output=True)
    def resource_batch_collect(
        platform: Annotated[
            str,
            Field(description="批量枚举目标平台 id；具体 mode 只在支持的平台有效。"),
        ],
        mode: Annotated[
            Literal[
                "creator_full",
                "time_range_search",
                "catalog_expand",
                "collection_expand",
            ],
            Field(
                description=(
                    "creator_full=完整枚举创作者；time_range_search=Bilibili 日期范围搜索；"
                    "catalog_expand=SmartEdu 教材规格展开；collection_expand=Bilibili 合集/系列完整展开。"
                    "只负责候选完整枚举，不自动下载。"
                )
            ),
        ] = "creator_full",
        creator_id: Annotated[
            str,
            Field(description="creator_full 使用：resource_id、原生 creator id 或主页 URL。"),
        ] = "",
        collection_url: Annotated[
            str,
            Field(
                description=(
                    "collection_expand 使用：Bilibili 合集/系列完整 URL，例如 "
                    "https://space.bilibili.com/<mid>/lists/<sid>?type=season|series。"
                )
            ),
        ] = "",
        keyword: Annotated[
            str, Field(description="time_range_search 使用：Bilibili 搜索关键词。")
        ] = "",
        start_day: Annotated[
            str, Field(description="time_range_search 使用：起始日期 YYYY-MM-DD。")
        ] = "",
        end_day: Annotated[
            str, Field(description="time_range_search 使用：结束日期 YYYY-MM-DD。")
        ] = "",
        specs: Annotated[
            list[str] | None,
            Field(description="catalog_expand 使用：SmartEdu 教材规格标识列表。"),
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
        return _call(
            lambda: resource_service.batch_collect(
                platform,
                mode=mode,
                creator_id=(collection_url if mode == "collection_expand" else creator_id),
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
            int, Field(ge=0, description="从第几个结果开始读取，0-based，默认 0。")
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "本页读取条数，默认 20，单页最多返回 50；分页大小不截断磁盘上的完整结果集。"
                    "每个返回候选会获得当前进程内 resource_id，供用户选择其中一部分后直接下载。"
                ),
            ),
        ] = 20,
    ) -> dict[str, Any]:
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
                    "纯 batch Job 没有可归档下载文件。"
                )
            ),
        ],
        domain_id: Annotated[
            str,
            Field(
                description=(
                    "学习资料库顶层语义领域 id，由调用方根据内容选择；"
                    "不确定可留空进入待分类。"
                )
            ),
        ] = "",
        topic: Annotated[
            str,
            Field(description="自由文本学习主题，例如“天文与宇宙”“自然拼读”；可留空。"),
        ] = "",
    ) -> dict[str, Any]:
        return _call(
            lambda: resource_service.archive(job_id, domain_id=domain_id, topic=topic),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_session_status(
        platforms: Annotated[
            list[str] | None,
            Field(description="查询已保存登录态；仅在 AUTH_REQUIRED 或用户主动管理会话时使用。"),
        ] = None,
        deep: Annotated[
            bool,
            Field(description="是否对支持远端检查的平台验证当前登录态。"),
        ] = False,
    ) -> dict[str, Any]:
        return _call(lambda: _session_status(resource_service, platforms, deep))

    @server.tool(structured_output=True)
    def resource_session_login_guide(
        platform: Annotated[
            str,
            Field(description="需要登录的平台；仅在 AUTH_REQUIRED 或用户主动登录时使用。"),
        ]
    ) -> dict[str, Any]:
        return _call(
            lambda: resource_service.session_store.login_guide(platform),
            platform=platform,
        )

    @server.tool(structured_output=True)
    def resource_session_save(
        platform: Annotated[
            str,
            Field(description="需要保存登录态的平台 id。"),
        ],
        capture: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "浏览器会话捕获对象，按捕获结果原样传入；不要由 Agent 手工挑选、"
                    "改写或拼接 Cookie/Token。MCP 按平台规则提取需要的认证字段。"
                )
            ),
        ],
        expires_at: Annotated[
            str | None,
            Field(description="可选 ISO 8601 过期时间；未知时省略。"),
        ] = None,
    ) -> dict[str, Any]:
        return _call(
            lambda: resource_service.session_store.save(
                platform,
                capture,
                expires_at=expires_at,
            ),
            platform=platform,
        )

    @server.tool(structured_output=True)
    def resource_session_delete(
        platform: Annotated[
            str,
            Field(description="删除该平台本地保存的登录态。"),
        ]
    ) -> dict[str, Any]:
        return _call(
            lambda: resource_service.session_store.delete(platform),
            platform=platform,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
