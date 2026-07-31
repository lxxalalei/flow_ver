# MCP 工作流

## 通用规则

- 使用 `contract_version: "1.0.0"`。
- 有副作用的首次调用生成 16–128 位 `idempotency_key`，只使用字母、数字、`.`、`_`、`:`、`-`。
- 同一请求因超时或响应丢失而重试时复用原键；参数改变时使用新键。
- 业务结果 `ok=false` 时读取 `error.code`、`error.retriable` 和 `error.context`，不要继续假定阶段成功。
- 内部 ID 只用于后续工具调用，不向用户复述。

## 把任务理解映射到 Flow

调用 `resource_flow_start` 时只传有证据支持的值：

| MCP 字段 | 映射规则 |
|---|---|
| `topic` | 保留用户核心主题或要解决的问题，避免只写上位分类。 |
| `learning_goal` | 简洁写明资源对象、希望发生的学习行为和关键约束；当前对话者身份不写入该字段。资源对象已知时不得仅因具体学习行为宽泛而留空。 |
| `audience` | 这是 MCP v1 的旧内容受众字段，不是当前对话者身份。仅按 `resource_target` 映射：给家长参考的内容可用 `parent`；用户主动给出明确学段时可映射对应学段；其他情况省略。 |
| `resource_types` | 只写用户明确要求或由明确形态可靠推出的 MCP 类型，不因主题自动补齐。 |
| `language_preferences` | 只写明确偏好或不会改变用户意图的透明低风险默认。 |
| `platform_preferences` | 只写用户明确提出且当前 MCP 可执行的平台；当前通常为 `generic`。 |

`learning_goal` 可以承载当前 v1 Schema 尚未独立建模的资源对象和用户明确约束。具体行为
尚宽泛时，使用“给孩子使用，了解恐龙基础内容”这类克制表达保留资源对象，不补写资源
形态。不要写成长篇对话记录，不要用“家长想给孩子找”等叙述重复当前对话者身份，也
不要把资源请求改写成“孩子感兴趣”“孩子想学习”等未表达的动机，不要使用“适合儿童”
等未经审查的评价语，也不要伪造年级、版本或格式。

## Session 管理

部分平台的搜索和下载需要用户登录态（cookie/token）。通过 session 工具在搜索前批量检查，避免逐个提示。

### 搜索前检查

当本轮搜索可能涉及需要认证的平台时，先调用 `resource_session_status`：

```
resource_session_status(platforms=["bilibili", "zhihu", "generic"])
```

返回 `needs_login` 列出所有需要登录的平台。如果列表为空，直接继续搜索。

### 引导登录

`needs_login` 非空时：

1. 一次性告诉用户所有需要登录的平台，不要逐个提示。
2. 用 browser 工具打开各平台的 `login_url`（`browser navigate` 或 `browser open`，可同时打开多个标签页）。
3. 告诉用户："请在打开的页面中登录，完成后告诉我。"
4. 用户确认登录后，用 `browser cookies` 读取当前会话 cookie，按 `cookie_domains` 筛出该平台的 cookie。
5. 对每个刚登录的平台调用 `resource_session_save`，传入 `{ "cookies": [...] }`。
6. 用 `resource_session_status(platforms=[...], deep=true)` 主动探活，确认 `probe_status="valid"`；返回 `invalid` 或 `probe_error` 时重新捕获。
7. 继续搜索。

> 浏览器由 OpenClaw 宿主驱动（Win 端原生 Chrome）。MCP 自身不打开浏览器、不读取 cookie；cookie 由 agent 读取后通过 `resource_session_save` 传入。

### 过期处理

`resource_session_status` 返回 `status=expired` 的平台，按同样的登录流程重新捕获。已 `valid` 的平台不需要重复登录；但服务端可能已失效而本地时间戳未到期，重要操作前可传 `deep=true` 复核真实有效性。

### 安全边界

- `resource_session_save` 的 `session_data` 只包含 cookie/token，不包含用户名、密码或其他凭据。
- 不在对话文本中展示 cookie 原文。
- 不代用户执行登录操作（填写账密、点击登录按钮）；用户必须自己完成登录。
- 浏览器关闭后 session 仍然有效，直到过期或被显式删除。

## 搜索

调用 `resource_search`：

- 涉及需要认证的平台时，先按上方 Session 管理检查登录状态。
- `query` 使用本轮最重要的发现方向，保留核心主题和真正改善召回的限定。
- 当前 v1 只有 `filters.platforms` 被 Search Provider 可靠强制执行。不要把
  `resource_types`、`languages`、`published_after` 或 `max_duration_seconds` 当成服务端
  已执行的硬过滤；把用户已提供的相关约束用于查询和候选审查，等待下一版 MCP 补齐。
- `limit` 根据任务宽度选择，普通推荐不为追求数量直接拉满 50。
- 当前搜索通过 SearXNG 执行，覆盖百度、搜狗、Bing 等通用引擎；`generic` 平台不需要认证。

成功后保存 `presented_version` 和本轮候选 `resource_id`。每次重新搜索都会生成新的展示版本，旧候选、编号和 Selection 不再有效。当前 v1 不支持把多条查询原子合并到同一展示集合；需要新角度时完成一次新的搜索并重新展示。

## 展示与选择

- 模型可以从 MCP 候选中排除不适合展示的项目，但不能创造候选或更改 `resource_id`。
- 用户选择前不调用 `resource_selection_save`。
- 保存选择时，`selected_resource_ids` 只能来自当前版本中实际展示给用户的候选。
- 用户取消时传空数组；返回 `cancelled=true` 后停止下载流程。
- 用户修改选择时保存完整的新集合，不在旧 Selection 上做隐式增删。

## 下载准备和确认

非空选择后使用当前 `selection_version` 调用 `resource_download_prepare`。

- 公开网页通常使用 `preferred_container=html`。
- 明确的公开文件直链可使用 `preferred_container=original`。
- 不提高服务端大小上限。
- 向用户展示资源、容器、有效期、大小上限和 `risks`。

只有用户看过当前计划并明确确认后，才调用 `resource_download_start`：

- 原样传递 MCP 返回的 `plan_id` 和 `confirmation_token`。
- start 使用新的幂等键；网络重试复用该键。
- 返回 `job_id` 后立即回复，不在同一次工具调用中等待长任务完成。

“继续”“可以”“就这样”只有在紧接当前有效计划且语义明确时才算确认。用户拒绝、改变选择或计划过期时重新 prepare。

## Job、取消、归档和检索

- `queued`、`running`：仍在执行。
- `cancelling`：取消处理中。
- `succeeded`：只使用返回的 validated Assets。
- `failed`：解释结构化原因；仅在 `retriable=true` 且外部条件发生变化时重试。
- `cancelled`：停止，不归档该 Job 的文件。

用户要求取消时调用 `resource_job_cancel`。终态 Job 不重复取消。

`resource_archive` 只接受成功 Job 返回的 `job_id` 和 `asset_id`。元数据可以包含标题、collection、tags 和 notes，不包含目标路径。`deduplicated=true` 表示已有同一资产，不是失败。

`resource_library_search` 当前要求有效 `flow_id`；没有可恢复 Flow 时，先以查询主题建立 Flow。

## 错误恢复

| 错误码 | 处理 |
|---|---|
| `FLOW_NOT_FOUND` | 说明当前流程无法恢复，根据仍有效的需求建立新 Flow。 |
| `PLATFORM_UNAVAILABLE` | 说明该平台尚未迁移，提议使用 `generic`，不声称无资源。 |
| `RESOURCE_NOT_PRESENTED` | 重新展示或重新搜索，不接受任意 URL 替代。 |
| `SELECTION_VERSION_CONFLICT` | 使用最新展示集合重新选择。 |
| `PLAN_EXPIRED` / `PLAN_ALREADY_USED` | 以当前 Selection 重新 prepare。 |
| `CONFIRMATION_INVALID` | 不猜测令牌，重新 prepare 并确认。 |
| `IDEMPOTENCY_CONFLICT` | 参数已变化时使用新键，不覆盖原请求。 |
| `NETWORK_BLOCKED` / `REDIRECT_BLOCKED` | 视为安全拒绝，不尝试绕过。 |
| `DOWNLOAD_TOO_LARGE` | 缩小范围或换资源，不提高服务端限制。 |
| `ASSET_NOT_ARCHIVABLE` | 查询 Job 状态，不从本地路径强行归档。 |
