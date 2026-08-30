"""Thin stdio MCP exposing generic resource actions and session capabilities."""

from __future__ import annotations

from typing import Annotated, Any, Callable, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from .errors import DomainError
from .expand import (
    download_expanded,
    import_resource_url,
    read_expand,
    start_expand,
)
from .service import ResourceService


PLATFORM_CAPABILITY_GUIDANCE = (
    "主要平台 id：bilibili、douyin、smartedu、ximalaya、libgen、zlibrary、zjer、zhihu、"
    "shuge、yixi、nlc、cctv、kepu、baiduwenku、runoob、open163、weibo、"
    "wechat、generic。平台是否支持 Search/Expand/Inspect/Download 以真实返回为准；"
    "不要因为平台存在某功能就猜测 MCP 已实现。"
)


class SearchTask(BaseModel):
    """One platform plus natural search phrases."""

    platform: str = Field(
        description=(
            "搜索平台 id。不要传平台内部分类代码、分页参数或 API 参数。"
            + PLATFORM_CAPABILITY_GUIDANCE
        )
    )
    queries: list[str] = Field(
        min_length=1,
        description=(
            "可直接输入对应平台搜索框的自然搜索短语列表，例如 "
            '["火山喷发 原理 动画"]。'
        ),
    )


class HtmlDesignPalette(BaseModel):
    """Complete palette for one viewer theme."""

    model_config = ConfigDict(extra="forbid")

    background: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    surface: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    muted: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_soft: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    border: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class HtmlDesignSpec(BaseModel):
    """Semantic design decision; never carries page content or arbitrary CSS."""

    model_config = ConfigDict(extra="forbid")

    theme_name: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=160)
    audience: str = Field(min_length=1, max_length=160)
    page_purpose: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=600)
    treatment: Literal["utilitarian", "editorial"] = "utilitarian"
    light_palette: HtmlDesignPalette
    dark_palette: HtmlDesignPalette
    type_system: Literal["editorial", "humanist", "technical", "rounded", "classical"] = "humanist"
    layout: Literal["focused", "standard", "wide", "visual"] = "standard"
    hero: Literal["understated", "editorial", "banner", "poster"] = "editorial"
    section_style: Literal["plain", "ruled", "banded", "cards"] = "plain"
    image_style: Literal["natural", "framed", "full_bleed", "gallery"] = "natural"
    density: Literal["compact", "comfortable", "spacious"] = "comfortable"
    signature: Literal["accent_rule", "corner_mark", "side_rail", "none"] = "accent_rule"


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
            needs_login.append(
                service.session_store.login_guide(status.platform)
                if platforms
                else status.config.public_metadata()
            )
    return {"sessions": sessions, "needs_login": needs_login}


def _session_manage(
    service: ResourceService,
    action: Literal["save", "delete"],
    platform: str,
    capture: dict[str, Any] | None,
    expires_at: str | None,
) -> dict[str, Any]:
    if action == "save":
        if capture is None:
            raise DomainError("INVALID_ARGUMENT", "save 操作需要 capture")
        return service.session_store.save(
            platform,
            capture,
            expires_at=expires_at,
        )
    if action == "delete":
        if capture is not None or expires_at is not None:
            raise DomainError(
                "INVALID_ARGUMENT",
                "delete 操作不接受 capture 或 expires_at",
            )
        return service.session_store.delete(platform)
    raise DomainError("INVALID_ARGUMENT", f"未知 Session 操作：{action}")


def _search(service: ResourceService, tasks: list[SearchTask], limit: int) -> dict[str, Any]:
    return service.search(
        [task.model_dump() for task in tasks],
        limit=limit,
    )


def _download(
    service: ResourceService,
    resource_ids: list[str] | None,
    expand_job_id: str,
    preferred_container: str,
) -> dict[str, Any]:
    ids = list(resource_ids or [])
    expand_job_id = str(expand_job_id or "").strip()
    if ids and expand_job_id:
        raise DomainError(
            "INVALID_ARGUMENT",
            "resource_ids 与 expand_job_id 必须且只能选择一种下载来源",
        )
    if expand_job_id:
        return download_expanded(
            service,
            expand_job_id,
            preferred_container=preferred_container,
        )
    return service.download(ids, preferred_container=preferred_container)


def _html_design(
    service: ResourceService,
    action: Literal["context", "render"],
    job_id: str,
    design_spec: HtmlDesignSpec | None,
) -> dict[str, Any]:
    if action == "context":
        if design_spec is not None:
            raise DomainError("INVALID_ARGUMENT", "context 操作不接受 design_spec")
        return service.html_design_context(job_id)
    if action == "render":
        if design_spec is None:
            raise DomainError("INVALID_ARGUMENT", "render 操作需要 design_spec")
        return service.html_design_render(job_id, design_spec.model_dump())
    raise DomainError("INVALID_ARGUMENT", f"未知 HTML 设计操作：{action}")


def create_server(service: ResourceService | None = None) -> MCPServer:
    resource_service = service or ResourceService()
    server = MCPServer(
        name="education-resources",
        title="Education Resources",
        description=(
            "Learning-resource Search, Expand, Inspect, Download, Archive and "
            "auxiliary platform session capabilities"
        ),
        version="0.5.0",
        instructions=(
            "The Agent owns user intent, search strategy, semantic relevance, stopping decisions, "
            "candidate ranking and user selection. This MCP owns factual platform access and file "
            "side effects. Search finds candidates. Expand structurally enumerates a known container "
            "resource and may persist a large complete result set in a Job; resource_job_read only "
            "controls how many children enter the conversation at once and never caps the underlying "
            "enumeration. Inspect is optional and should be used only when current resource facts affect "
            "selection or acquisition. Download acts only on resources the user selected; completion of "
            "Search or Expand is never implicit download authorization. A logical resource may naturally "
            "materialize into multiple files. Resource handles are process-local; Download and Expand Job "
            "handles are persistent. Session tools are not a preflight step: use them after AUTH_REQUIRED "
            "or when the user explicitly asks to manage a platform session. HTML Design is optional and "
            "runs only after the user asks for a visually designed single-page Generic Web deliverable."
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
                    "每条 query 本次返回的候选数量，默认 8；它只控制交互响应规模，"
                    "不是完整枚举上限。"
                ),
            ),
        ] = 8,
    ) -> dict[str, Any]:
        """Search explicitly chosen MCP platforms for candidate resources.

        Use for platform-native discovery with natural queries. Open-web discovery
        normally belongs to the host Web Search. Do not use for a known URL,
        structural container enumeration, or as implicit download authorization.
        """
        return _call(lambda: _search(resource_service, search_tasks, limit))

    @server.tool(structured_output=True)
    def resource_expand(
        resource_id: Annotated[
            str,
            Field(
                description=(
                    "要展开的容器 resource_id。也可以直接传 source_url，二者只能选一个。"
                    "Expand 只向下展开结构；video/track/file 等叶子资源不可通过创作者元数据反向展开。"
                )
            ),
        ] = "",
        source_url: Annotated[
            str,
            Field(
                description=(
                    "已知容器资源 URL，例如创作者主页、Bilibili/Douyin 合集、Ximalaya 专辑、"
                    "SmartEdu 教材或 Zjer 课程。平台内部结构由 MCP 识别。"
                )
            ),
        ] = "",
    ) -> dict[str, Any]:
        """Start complete structural enumeration of one known container resource.

        Use for creators, collections, albums, textbooks or courses when their
        children are required. This starts a persistent Expand Job; it is not
        search, leaf-to-parent discovery, or permission to download the children.
        """
        return _call(
            lambda: start_expand(
                resource_service,
                resource_id=resource_id,
                source_url=source_url,
            ),
            resource_id=resource_id,
            source_url=source_url,
        )

    @server.tool(structured_output=True)
    def resource_import_url(
        source_url: Annotated[
            str,
            Field(
                description=(
                    "已经明确知道的 HTTP(S) 资源/网页 URL。该工具不负责搜索；"
                    "会识别已接入平台的单资源 URL，否则按 generic 网页处理。"
                )
            ),
        ]
    ) -> dict[str, Any]:
        """Turn one already-known HTTP(S) URL into a process-local Resource.

        Use after the user supplies or selects a concrete URL and MCP facts or
        file actions are needed. The URL is classified and inspected, but this
        tool does not search the web or download the resource.
        """
        return _call(
            lambda: import_resource_url(resource_service, source_url),
            source_url=source_url,
        )

    @server.tool(structured_output=True)
    def resource_inspect(
        resource_id: Annotated[
            str,
            Field(
                description=(
                    "Search/Import/JobRead 返回的当前进程内 resource_id；"
                    "仅在未知事实会影响选择或获取时调用。"
                )
            ),
        ]
    ) -> dict[str, Any]:
        """Resolve current facts for one process-local Resource without downloading.

        Use only when availability, identity, format or composition can change a
        recommendation or acquisition decision. Do not inspect every candidate
        merely to complete a fixed workflow.
        """
        return _call(lambda: resource_service.inspect(resource_id), resource_id=resource_id)

    @server.tool(structured_output=True)
    def resource_download(
        resource_ids: Annotated[
            list[str] | None,
            Field(
                description=(
                    "用户明确选中的当前进程内 resource_id 列表。选择 Expand 结果中的部分资源时，"
                    "先用 resource_job_read 获取对应 resource_id。与 expand_job_id 二选一。"
                )
            ),
        ] = None,
        expand_job_id: Annotated[
            str,
            Field(
                description=(
                    "仅当用户明确选择某个完整 succeeded 的 Expand 结果中的全部子资源时传入；"
                    "MCP 直接读取完整 results.jsonl，不要求 Agent 把所有子资源搬进上下文。"
                )
            ),
        ] = "",
        preferred_container: Annotated[
            str,
            Field(
                description=(
                    '主表示容器偏好，默认 "original"，表示按资源自然交付方式获取。'
                    "只有用户明确要求且资源确实存在对应主表示时才指定 pdf/mp4/mp3/html 等。"
                )
            ),
        ] = "original",
    ) -> dict[str, Any]:
        """Start a persistent Download Job for resources the user explicitly selected.

        Pass resource_ids for selected individual Resources, or expand_job_id only
        when the user chose every child of one fully succeeded Expand Job. Search,
        Expand or recommendation alone never authorizes this file side effect.
        """
        return _call(
            lambda: _download(
                resource_service,
                resource_ids,
                expand_job_id,
                preferred_container,
            ),
            expand_job_id=expand_job_id,
        )

    @server.tool(structured_output=True)
    def resource_job_status(
        job_id: Annotated[
            str,
            Field(description="resource_expand 或 resource_download 返回的持久 job_id。"),
        ]
    ) -> dict[str, Any]:
        """Read progress or final file/failure facts for an Expand or Download Job.

        Use the persistent job_id returned by resource_expand or resource_download.
        For pages of expanded children, use resource_job_read instead.
        """
        return _call(lambda: resource_service.job_status(job_id), job_id=job_id)

    @server.tool(structured_output=True)
    def resource_job_cancel(
        job_id: Annotated[
            str,
            Field(description="取消 queued/running/cancelling 的 Expand 或 Download Job。"),
        ]
    ) -> dict[str, Any]:
        """Request cancellation of one active Expand or Download Job.

        Use when the user asks to stop or the active operation is no longer wanted;
        terminal Jobs are returned unchanged.
        """
        return _call(lambda: resource_service.job_cancel(job_id), job_id=job_id)

    @server.tool(structured_output=True)
    def resource_job_read(
        job_id: Annotated[
            str,
            Field(description="resource_expand 返回的 job_id。"),
        ],
        offset: Annotated[
            int,
            Field(ge=0, description="从第几个子资源开始读取，0-based，默认 0。"),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "本页读取条数，默认 20，单页最多 50；只控制上下文页大小，"
                    "不截断磁盘上的完整展开结果。"
                ),
            ),
        ] = 20,
    ) -> dict[str, Any]:
        """Read one context-sized page from a persistent Expand Job result.

        Paging never limits the complete on-disk enumeration. Use returned
        resource_id values when the user selects individual children. This tool
        does not read Download Job files; use resource_job_status for those.
        """
        return _call(
            lambda: read_expand(resource_service, job_id, offset=offset, limit=limit),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_html_design(
        action: Annotated[
            Literal["context", "render"],
            Field(
                description=(
                    "context 从单个已完成 Generic Web Download Job 读取有界设计摘要；"
                    "render 使用 HTML Design Skill 根据该摘要产生的 DesignSpec 重绘 index.html。"
                )
            ),
        ],
        job_id: Annotated[
            str,
            Field(description="包含单个 Generic Web 清洗产物的 succeeded/partial Download Job。"),
        ],
        design_spec: Annotated[
            HtmlDesignSpec | None,
            Field(
                description=(
                    "仅 render 使用。它只描述主题、受众、页面任务和受控视觉 token；"
                    "不得包含正文、HTML、CSS 或脚本。"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Optionally redesign one completed Generic Web download as polished HTML.

        Use only after the user explicitly requests visual optimization. Call
        context first, create a controlled DesignSpec with the HTML Design Skill,
        then call render. It is not part of ordinary webpage download.
        """
        return _call(
            lambda: _html_design(resource_service, action, job_id, design_spec),
            job_id=job_id,
        )

    @server.tool(structured_output=True)
    def resource_archive(
        job_id: Annotated[
            str,
            Field(description="已产生真实文件且状态为 succeeded/partial 的 Download Job。"),
        ],
        domain_id: Annotated[
            str,
            Field(description="学习资料库顶层语义领域 id；不确定可留空进入待分类。"),
        ] = "",
        topic: Annotated[
            str,
            Field(description="自由文本学习主题，例如“天文与宇宙”“自然拼读”；可留空。"),
        ] = "",
    ) -> dict[str, Any]:
        """Move real files from a finished Download Job into the learning library.

        Use only after a succeeded or partial Download Job has produced files and
        archiving is wanted. The Agent chooses domain/topic; the MCP moves files
        and reports real archive failures.
        """
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
        """Read saved platform-session status and, when needed, login guidance.

        Use after a real AUTH_REQUIRED result or when the user explicitly manages
        sessions. It is not a preflight step before ordinary Search or Download.
        """
        return _call(lambda: _session_status(resource_service, platforms, deep))

    @server.tool(structured_output=True)
    def resource_session_manage(
        action: Annotated[
            Literal["save", "delete"],
            Field(description="save 保存登录态；delete 删除本地登录态。"),
        ],
        platform: Annotated[str, Field(description="需要管理登录态的平台 id。")],
        capture: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "仅 save 使用：浏览器会话捕获对象按捕获结果原样传入；"
                    "不要由 Agent 手工挑选、改写或拼接 Cookie/Token。"
                )
            ),
        ] = None,
        expires_at: Annotated[
            str | None,
            Field(description="仅 save 使用：可选 ISO 8601 过期时间；未知时省略。"),
        ] = None,
    ) -> dict[str, Any]:
        """Save an opaque browser-session capture or delete one platform session.

        The user completes login. For save, pass the captured object unchanged;
        never ask for or reconstruct passwords, MFA codes, Cookie headers or
        canonical tokens. Use delete only when session removal is requested.
        """
        return _call(
            lambda: _session_manage(
                resource_service,
                action,
                platform,
                capture,
                expires_at,
            ),
            platform=platform,
        )

    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
