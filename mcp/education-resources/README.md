# Education Resources MCP

`education-resources` 是当前唯一 active Python stdio MCP。它不管理用户研究工作流，只把真实的资源能力、文件副作用和辅助 Session 能力暴露给 Agent。

## 核心边界

```text
Main Agent / Skill
  需求理解 / 搜索任务 / 相关性判断 / 用户选择 / 归档分类
        ↓
education-resources MCP
  Resource Tools + Session Tools
        ↓
平台 Adapter / Downloader / SessionStore / 本地资料库
```

MCP 不维护 Flow、ResultSet、Presentation、Selection、Download Plan、confirmation token、AssetBundle、authority/binding/digest 链，也不保存“用户看过第几个候选”这类对话状态。

## 12 个 Tool

资源能力：

1. `resource_search`
2. `resource_expand`
3. `resource_import_url`
4. `resource_inspect`
5. `resource_download`
6. `resource_job_status`
7. `resource_job_cancel`
8. `resource_job_read`
9. `resource_html_design`
10. `resource_archive`

Session 辅助能力：

11. `resource_session_status`
12. `resource_session_manage`

每个 Tool 的用户意图、触发/非触发、输入身份、Job、副作用和失败边界集中记录在
[`../../docs/MCP_CAPABILITY_INVENTORY.md`](../../docs/MCP_CAPABILITY_INVENTORY.md)；
运行时 `tools/list` 仍是名称、description 和 input schema 的机器事实。

容器资源统一通过 `resource_expand` 完整展开，结果通过 `resource_job_read` 分页进入上下文。旧 `resource_browse_creator` / `resource_batch_collect` / `resource_batch_read` 及其 mode 不属于公共能力。

`resource_html_design` 只处理用户明确要求视觉优化的单网页 Download Job：`context` 返回有界且显式标记截断的设计摘要，`render` 接收受控 DesignSpec 并完整保留已经清洗的正文。默认网页下载仍直接产生稳定 Reader，不强制调用模型设计。

SmartEdu 教材 Expand 匿名读取连续 CDN 分片，以真实 404 或空分片结束。同步课、精品课写入结果；没有独立详情 URL 的类型、未知类型和无效项进入 `summary.smartedu`，不会伪造 URL 或静默消失。

Session Tool 不应在每次资源操作前调用。只有真实资源能力返回 `AUTH_REQUIRED`，或用户主动要求管理平台会话时才使用。

## Resource 与 File

当前资源模型明确允许：

```text
1 Resource -> 0..N files
```

Resource 是用户选中的逻辑资源；Representation 是 Inspect 确认的可获取形态/组成事实；最终 File 是 Downloader 真正产生的产物。一个资源产生多个文件不需要额外的 Bundle/Component 状态机。

`primary` 表示资源主交付入口，用于 exact Provider 路由；`attachment`、`companion`、`subtitle` 等可以描述同一逻辑资源自然附带的文件。`resource_download(..., preferred_container="original")` 表示按资源自身的自然交付方式获取，而不是“只能下载一个原始扩展名”。

例如 SmartEdu 一堂课程可以自然产生主视频 + PDF 资料 + 配套音频；Generic Web 页面也会自然产生 source/readable/metadata 等多个文件。Job 的 `files` / `failures` 才是最终交付事实。

只有用户明确要求某个特定主格式时才传 `preferred_container=pdf/mp4/...`；指定格式不存在时应显式失败，不能静默忽略要求或自动改成别的格式。

## SessionStore

SessionStore 与资源 Adapter 位于同一个 MCP 和同一个数据目录：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/sessions/
```

`resource_session_status` 在指定平台的登录态缺失、过期或失效时直接返回登录步骤；全量查询不重复展开步骤。`resource_session_manage` 使用 `action=save|delete`；save 接收 `platform + capture + expires_at?`，delete 只接收 `platform`。`capture` 是 opaque browser-session capture object：Agent 原样传递，不需要理解或手工筛选 Cookie、localStorage、sessionStorage、Token 的具体字段。

MCP 内部 `PlatformConfig` / SessionStore 才拥有平台认证契约。浏览器捕获可以较宽，MCP 再按已验证的平台规则筛选，只保存真正需要的 canonical subset。SmartEdu 当前明确需要 `accessToken`；Cookie 平台在未实测出最小 Cookie 名集合前继续按内部域名边界筛选，不凭经验硬编码白名单。

Session Tool 不公开 `cookie_domains` / `storage_keys` 等内部认证字段；只返回登录 URL、捕获方式、probe 能力、状态和必要登录步骤。

Windows 使用当前用户 DPAPI 保护本地登录态。没有 standalone `session-manager`、`session_bridge.py`、双 Store 路径、operation ledger 或 idempotency fingerprint/revision 链。

从旧独立 session-manager 升级时不做长期双读兼容，已有登录态可能需要重新捕获一次。

SmartEdu 公共 Search / Catalog 不使用已保存 token；LibGen 当前不需要登录。

## Web Search 与 Import URL

普通网页发现默认由宿主 OpenClaw Web Search 完成。挑中具体 URL 后：

```text
resource_import_url(source_url="https://...")
```

Import 会对明确的 URL 形态恢复专门平台身份：Bilibili、Douyin、Ximalaya、SmartEdu、Zjer、CCTV、LibGen 和 Zhihu；其他或无法明确识别的 URL 进入 `generic`。

这只是通用发现到现有专门 Inspector/Downloader 的薄桥接，不是第二套平台 Registry。

## SmartEdu 课程资源

SmartEdu 的课程 URL 是 landing page，同时也是一个逻辑 Course Resource 的稳定入口；它不等于单一网页文件。

Inspect 会从当前 detail JSON 中确定主视频/主文件，并把自然交付中当前受支持的 PDF 附件、伴随音频等一并暴露为 Representation。多码率视频仍只选一个当前主版本，不把同一视频的 HLS/MP4 变体误当成两份课程内容。

默认 `preferred_container="original"` 时，SmartEdu Downloader 按同一 detail 事实下载自然交付包；因此 Agent 不需要、也不应该为了“让课程可下载”先猜 `mp4`。具体 Detail / Download 如果真实返回 `AUTH_REQUIRED` 才进入 Session；IP/出口限制不能自动解释为登录问题。

用户需要查看或筛选课程内部文件时，`resource_expand` 会把具有平台稳定 item/group ID 的视频、文档和音频作为逻辑子资源返回。子资源只保存课程详情入口和稳定文件键；Inspect/Download fresh Detail 后解析当前 CDN 地址并只下载所选文件。无稳定平台键的附件不会用文件名、数组序号或签名 URL 伪造身份，仍随课程整体交付。

## Generic Web Resource

Generic HTML 获取继续使用 `BoundedWebFetcher`。保存流程：

```text
HTTP response
  -> source.html
  -> Trafilatura
       -> index.html
       -> content.md
       -> metadata.json
```

`source.html` 保存 fetch 成功取得的原始 HTML 响应，正文抽取是衍生视图。Trafilatura 抽取失败时 Job 可以是 partial，但 source snapshot 不会因此丢失。

默认 `index.html` 使用稳定 `clean-reader-v2`。用户明确要求精美或内容感知的 HTML 时，`resource_html_design(action=context)` 返回有界设计摘要，Agent 的 HTML Design Skill 产生受控 DesignSpec，再由 `action=render` 把完整清洗正文原样注入 `adaptive-reader-v1`。模型不接收或重写全文，`source.html` 与 `content.md` 不变。

当前不下载并重写所有 CDN 资产，也不接 Monolith / SingleFile / ArchiveBox；目标不是浏览器级网页克隆。以后如果出现明确的“离线打开仍要尽量完整还原”需求，再单独评估 Monolith。

网络层仍保留单响应获取上限，超限显式失败，不静默截断成看似完整的资源。

## `resource_id` 只在当前进程有效

Search / Import / JobRead 返回的 `resource_id` 是临时操作句柄：

```text
resource_id -> 当前 MCP 进程里的资源对象
```

不写持久资源数据库。句柄失效时优先根据已知 URL / 平台稳定 ID 重新定位同一资源。

一旦调用 `resource_download`，完整资源快照写入 Job 的 `request.json`，worker 不依赖旧 `resource_id`。

## Download / Job

普通已选资源：

```text
resource_download(
  resource_ids=["res_..."],
  preferred_container="original"
)
```

用户明确选择一个完整 Expand Job 的全部结果时：

```text
resource_download(
  expand_job_id="job_...",
  preferred_container="original"
)
```

两种输入二选一。下载前 fresh Inspect，再按当前真实 primary Representation 路由到 exact Provider。默认 `original` 允许 Provider 为一个 Resource 产生一个或多个真实文件；附件/伴随文件的成功与失败分别进入 Job 结果。Provider 失败时返回真实失败，不静默换成不等价 Provider。

Job 使用薄文件状态：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  request.json
  job.json
  worker.log
  cancel.flag        # 取消后才出现
  results.jsonl      # Expand 才出现
  ...下载产物
```

worker 已死但 Job 未到终态时标记 `interrupted`；重新发起即可，不实现 checkpoint/resume/Outcome/执行绑定状态机。

## Expand

创作者、合集、专辑、教材、课程等容器统一使用 `resource_expand`。平台 Adapter 根据资源事实选择真实分页与结构展开方式，公共 Tool 不暴露平台 mode。

Expand 完整枚举到来源真实结束；`resource_job_read` 单页大小只控制 Tool Result，不截断磁盘上的完整结果。

Expand 只产生候选，不产生下载授权：

- 用户选择部分结果 → `resource_job_read` 返回的候选附带当前进程 `resource_id`，再调用 `resource_download(resource_ids=[...])`；
- 用户明确选择完整 `succeeded` Expand Job 的全部结果 → `resource_download(expand_job_id="...")`，MCP 直接读取完整 `results.jsonl` 并复用现有多资源 Download Job；
- `partial` / `failed` / `cancelled` Expand Job 不能冒充“全部”。

这里没有新增 Selection 状态；只是把已选择资源的机械循环留在 MCP 后台。

## Archive

```text
resource_archive(
  job_id="job_...",
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

Agent 判断 `domain_id/topic`，MCP 只移动下载 Job 已产生的真实文件。分类不确定时可留空进入待分类区域。

默认资料库：

```text
~/Documents/学习资料库/
```

可通过 `EDUCATION_RESOURCE_MCP_LIBRARY_DIR` 覆盖。

## 配置

```text
EDUCATION_RESOURCE_MCP_DATA_DIR
EDUCATION_RESOURCE_MCP_LIBRARY_DIR
EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT
EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT
EDUCATION_RESOURCE_MCP_MAX_WORKERS
EDUCATION_RESOURCE_MCP_SEARXNG_URL
EDUCATION_RESOURCE_MCP_PREFER_SEARXNG
```

不再使用 `EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR`。

## 安装与启动

```bash
cd mcp/education-resources
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/education-resource-mcp
```

Windows：

```powershell
.venv\Scripts\python -m pip install -e .
.venv\Scripts\education-resource-mcp.exe
```

## 当前目录重点

```text
src/education_resource_mcp/
├── server.py              # 11 个 MCP Tool
├── service.py
├── search.py
├── expand.py
├── inspection.py
├── inspection_registry.py
├── archive.py
├── sessions.py            # 单一 SessionStore
├── windows_dpapi.py
├── adapters/
│   ├── expansion.py          # 仅做平台 Expand 路由
│   ├── *_expand.py           # 平台专属展开实现
│   ├── smartedu_resource.py  # SmartEdu 共享纯资源事实
│   └── smartedu_download.py  # SmartEdu 网络与文件物化
├── acquisition/
│   ├── web_fetch.py
│   └── web_materializer.py
├── jobs.py
├── job_worker.py
└── job_state.py
```

当前最重要的验收仍是真实 OpenClaw 场景：能否完成发现/展开 → 判断 → 选择 → 下载 → 文件，以及需要登录时能否在同一个 MCP 中按 `AUTH_REQUIRED → 浏览器 capture → Session save → 重试` 完成闭环。
