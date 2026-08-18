# 当前架构

> 快照日期：2026-08-18  
> 只描述当前 active 运行事实。旧 Flow / ResultSet / Presentation / Selection / Plan / authority / digest 设计只保留在 Git 历史或 legacy 中。

## 1. 当前定位

这个项目由一个语义 Skill 和两个能力 MCP 组成：

```text
用户自然语言
  ↓
learning-resource-flow Skill / Main Agent
  │  理解目标、设计搜索任务、判断候选、理解用户选择、决定是否获取与归档分类
  │
  ├──────────────→ session-manager MCP
  │                 登录引导 / 浏览器捕获 / 最小会话保存 / 状态验证
  │
  ↓
education-resources MCP
  │  Platform Search / Import URL / Inspect / Download / Batch / Archive
  ↓
平台 Adapter / Downloader / 本地资料库
```

核心边界：

> Agent 负责语义判断；MCP 负责真实能力、IO 和必要的运行状态。

`education-resources` 不是资源工作流后端，`session-manager` 也不是用户流程状态机。两者都不拥有“用户看过哪些候选、选择第几个、目标是否满足”这类对话语义。

## 2. 当前 active 组件

### `skills/learning-resource-flow/`

唯一用户入口和语义决策层，负责：

- 需求理解与必要澄清；
- 搜索任务设计与来源职责；
- 候选质量、内容 Gap、Coverage Gap 和停止判断；
- 用户选择语义；
- 获取意图；
- 归档语义分类。

Skill 不复制 MCP 参数说明，也不把搜索、Inspect、下载、归档写成固定流水线。

### `mcp/education-resources/`

资源能力 MCP，负责平台调用、URL 导入、候选事实检查、下载、批量枚举、Job 状态和真实文件归档。

### `mcp/session-manager/`

独立登录态 MCP，负责：

- 返回平台登录页面和捕获要求；
- 让宿主浏览器在用户本人完成登录后捕获 cookie / same-origin storage；
- 服务端按平台规则提取最小必要会话数据；
- 保存、删除和按需验证登录态。

它不向模型返回原始凭据值，也不负责资源搜索与下载。

## 3. education-resources 当前 10 个 Tool

1. `resource_search`
2. `resource_browse_creator`
3. `resource_import_url`
4. `resource_inspect`
5. `resource_download`
6. `resource_job_status`
7. `resource_job_cancel`
8. `resource_batch_collect`
9. `resource_batch_read`
10. `resource_archive`

已移除且不应恢复为主链的状态/Tool：Flow、ResultSet lineage、Presentation、Selection、Download Plan、confirmation token、ArchiveRecord、AssetBundle、authority/binding/digest 链。

## 4. session-manager 当前 Tool

1. `resource_session_status`
2. `resource_session_login_guide`
3. `resource_session_save`
4. `resource_session_delete`

登录由用户本人在宿主浏览器完成。Agent 不索取、代填或保存账号密码、验证码、短信码或 MFA。

浏览器捕获的数据直接交给 `resource_session_save`，由 session-manager 自己做平台域名、字段和最小保存规则；Agent 不手工从浏览器结果拼接 canonical Cookie/Token。

只有用户主动提供合法取得的 canonical Cookie/Token 且明确授权保存时，才按 Tool schema 直接导入。

## 5. 两个 MCP 的会话数据关系

`education-resources` 本身不提供公开登录 Tool。

当配置 `EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR` 时，`education-resources` 通过 `session_bridge.py` 以只读方式使用 standalone session-manager 的 `SessionStore`，因此搜索 Adapter 和 session-manager 读取同一份受控会话数据。

```text
session-manager
  ↓ 写入
受控 SessionStore
  ↑ 只读
education-resources adapters
```

如果明确配置了 standalone store 路径但运行环境没有安装 session-manager，bridge 直接失败，不静默切回另一份空 store；否则会出现“登录显示成功，但搜索进程读不到登录态”的假成功。

`education-resources` 内部旧 `sessions.py` 只保留给隔离测试和未配置 standalone store 的显式部署，不是新的第二套产品登录系统。

## 6. 搜索与外部 Web 的分工

专门平台搜索走：

```text
resource_search
```

普通网页发现默认走宿主 OpenClaw Web Search。开放式学习资源任务通常应把 Host Web Search 作为首轮发现路线之一，除非用户明确限定单一平台/形态，或单一专门生态已经完整覆盖一个非常窄的目标。

Agent 选中具体 URL 后：

```text
resource_import_url(source_url="https://...")
```

MCP 对该 URL 建立当前进程内的 `resource_id`，可继续 Inspect / Download。

`platform="generic"` 只作为宿主 Web Search 召回不足时的补充能力，不机械加入每轮搜索计划。

## 7. `resource_id` 是临时句柄

MCP 只在当前进程内保留：

```text
resource_id -> 当前搜索/导入得到的资源对象
```

不写 `resources.jsonl`，不为临时 handle 建数据库恢复链。

真正稳定的资源身份是 URL、平台原生资源 ID 等。

MCP 重启导致旧 `resource_id` 失效时：

```text
已知原 URL
  → resource_import_url(URL)

已知平台稳定 ID
  → 精确重新定位

只有标题/作者/平台
  → 针对该具体资源做最小搜索

无法确定原资源
  → 最后才回到原始主题重新发现
```

不要因为一个临时句柄失效就重跑整套研究。

## 8. Inspect 与 Download

Inspect 只在未知事实会改变推荐、选择或获取决策时使用，不是固定步骤。

用户已经明确选定资源并明确要求下载后：

```text
resource_download(resource_ids=[...])
```

可以直接执行，不增加 `prepare -> confirm -> start` 的形式化二次确认。

下载内部可执行 fresh Inspect 和一次性 Provider 路由，但这些是执行细节，不创建持久 Plan、eligibility、fingerprint、digest 或 revalidation snapshot。

成功与否只依据真实 Job/文件结果。

## 9. Job：只为真实长任务持久

下载和批量枚举需要进度、取消以及 MCP / Gateway 重启后的真实状态，因此 Job 使用薄文件状态：

```text
$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/<job_id>/
  request.json
  job.json
  worker.log
  cancel.flag        # 只有取消后才出现
  results.jsonl      # 只有 batch job 才出现
  ...下载产物
```

`job_id` 是持久的运行身份，不是工作流业务身份。

这不是 durable workflow：没有 Flow、Selection、Plan、JobItem、Outcome、checkpoint、resume token、execution binding 或 job version。Interrupted 任务重新发起即可，不做复杂断点状态机。

## 10. Batch：完整数据不进入对话

`resource_browse_creator` 是交互式预览。

需要“全部作品”“完整时间段”等数据完整性任务时使用 `resource_batch_collect`。

默认不传 `max_items`，枚举到来源真实结束；只有用户明确要求“最多 N 条”时才传上限。

当前 Creator / time-range 等支持的平台使用 generator 按页 yield，Batch 一边采集一边写入 `results.jsonl`，不先把全部结果堆进内存。

读取使用：

```text
resource_batch_read(job_id=..., offset=0, limit=20)
```

单页大小只控制 Tool Result，不得成为完整采集上限。

去重优先使用 URL / 平台稳定资源身份，不按标题去重。

## 11. Archive

下载 Job 到达 `succeeded` 或 `partial` 后，可按 Agent 已判断的语义分类执行：

```text
resource_archive(
  job_id=...,
  domain_id="natural_science",
  topic="天文与宇宙"
)
```

Agent 决定分类；MCP 只移动真实下载文件。

没有 `asset_id`、ArchiveRecord、AssetBundle、archive digest/version 或 ready state。

默认资料库根目录为 `~/Documents/学习资料库/`，可通过 `EDUCATION_RESOURCE_MCP_LIBRARY_DIR` 覆盖。

## 12. 当前应保留的必要检查

只保留直接保护真实能力正确性的边界：

- URL / 本地路径合法性；
- 平台实际登录态；
- Provider 必须产生真实文件；
- exact Provider 路由；
- 下载 / Batch 取消；
- 下载器实际需要的格式 / MIME 校验；
- 平台真实存在的身份格式要求。

不恢复与业务无关的证明链、哈希绑定、任意输入输出截断或人为资源大小上限。

## 13. 当前核心目录

```text
skills/learning-resource-flow/

mcp/education-resources/
└── src/education_resource_mcp/
    ├── server.py
    ├── service.py
    ├── search.py
    ├── batch.py
    ├── inspection.py
    ├── archive.py
    ├── jobs.py
    ├── job_worker.py
    ├── job_state.py
    ├── session_bridge.py
    ├── sessions.py          # legacy/local fallback for tests or explicit deployment
    ├── adapters/
    └── acquisition/

mcp/session-manager/
└── src/session_manager/
    ├── server.py
    ├── store.py
    ├── http_client.py
    └── windows_dpapi.py
```

## 14. 当前验证重点

1. Skill 是否能把用户目标拆成有职责的搜索任务，而不是只搜几个同类视频就停；
2. Host Web Search 与专门平台搜索是否真正互补；
3. Search / Web Search → Import URL 是否返回真实可用资源；
4. Inspect 是否只在决策需要时补事实；
5. Download 是否产生正确文件；
6. Batch 是否真正翻页到平台结束、结果不被硬截断；
7. Archive 是否移动到正确资料库目录并返回最终路径；
8. session-manager 保存的登录态是否能被 education-resources 正确读取；
9. 平台真实失败是否诚实暴露，而不是被 fallback 或 crash 掩盖；
10. 真实 OpenClaw 用户链路是否与后端单测结论一致。

验证重点是真实业务行为，不让旧状态契约测试迫使实现重新复杂化。
