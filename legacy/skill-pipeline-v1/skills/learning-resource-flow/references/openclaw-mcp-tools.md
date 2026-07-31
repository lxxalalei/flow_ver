# OpenClaw MCP 工具指南

本文是 `learning-resource-flow` 默认执行后端的操作参考。权威 JSON Schema 位于仓库 `contracts/v1/`；工具实际暴露名由 OpenClaw 加服务器前缀，例如 `education-resources__resource_flow_start`。

## 通用要求

- 每次调用使用 `contract_version: "1.0.0"`。
- 首次副作用请求生成 16–128 位 `idempotency_key`，只使用字母、数字、`.`、`_`、`:`、`-`。
- 网络超时或响应丢失后重试完全相同的请求时复用原幂等键；参数变化时使用新键。
- 只使用工具返回的 `flow_id`、`resource_id`、`plan_id`、`job_id` 和 `asset_id`。
- 任何结果 `ok=false` 时停止当前状态转换，读取 `error.code`、`error.retriable` 和 `error.context`。
- 不向工具传本地路径、URL、脚本、解释器、二进制或命令。资源 URL 只能来自服务端已持久化的搜索结果。

## 1. 建立 Flow

需求足以支持搜索后调用：

```json
{
  "contract_version": "1.0.0",
  "idempotency_key": "flow:20260729:unique-token",
  "intent": {
    "topic": "用户确认后的主题",
    "learning_goal": "可选",
    "audience": "primary",
    "resource_types": ["article", "video"],
    "language_preferences": ["zh-CN"],
    "platform_preferences": ["generic"]
  }
}
```

保存 `flow_id`。不要在澄清未完成时建立多个 Flow。

## 2. 搜索并展示候选

调用 `resource_search`，保存 `presented_version` 和所有返回的 `resource_id`。首版支持 Generic 公开网页搜索；未启用平台会出现在 `failures`，不要描述为“没有资源”。

只展示本次响应中的候选。解释标题、摘要、来源、适龄性和可用性，但不要替用户确认下载。

重新搜索会产生新的 `presented_version`；旧候选集合和选择不可继续使用。

## 3. 保存明确选择

用户明确选择后调用 `resource_selection_save`：

- 传本轮 `presented_version`。
- `selected_resource_ids` 只能来自本轮候选。
- 用户取消时传空数组；返回 `cancelled=true` 后停止下载流程。
- “这些都要”只解释为当前展示集合，不跨页、不跨恢复前的旧集合。

## 4. 准备下载

有非空选择时调用 `resource_download_prepare`，传返回的 `selection_version`。首版建议：

- 公开网页正文：`preferred_container=html`。
- 明确公开文件直链：`preferred_container=original`。
- `max_bytes_per_resource` 不得超过服务端上限。

把返回的每个 item、有效期、大小上限和 risks 告诉用户。此步骤不下载。

## 5. 用户确认并启动

只有用户在看过 prepare 结果后明确同意，才调用 `resource_download_start`：

- 原样传 `plan_id` 和 `confirmation_token`。
- 为 start 使用新的幂等键；网络重试时复用该键。
- 工具立即返回 `job_id`，不要同步等待整个文件下载。

用户拒绝、修改选择、Plan 过期或确认令牌无效时，不得调用或重试 start；重新 selection/prepare。

## 6. 状态与取消

使用 `resource_job_status(flow_id, job_id)` 查询：

- `queued`、`running`、`cancelling`：继续等待或稍后查询。
- `succeeded`：只使用返回的 validated Assets。
- `failed`：展示 failures；只有 `retriable=true` 且外部条件变化时才重试。
- `cancelled`：停止；不得归档该 Job 的文件。

用户要求取消时调用 `resource_job_cancel`。终态任务不可取消；取消请求也使用幂等键。

## 7. 归档和检索

只对 `succeeded` Job 返回的 `asset_id` 调用 `resource_archive`，同时传其 `job_id`。元数据可以包含标题、collection、tags 和 notes，不能包含目标路径。

归档本身幂等；`deduplicated=true` 表示该 Asset 已经归档。

使用 `resource_library_search` 查询资料库。v1 本地服务要求有效 `flow_id`；若用户从独立的资料库查询开始且没有可恢复的 Flow，先用查询主题调用 `resource_flow_start`，再把返回的 `flow_id` 用于检索。首版不支持 cursor 时，不要伪造分页游标。

## 状态冲突处理

| 错误码 | 处理 |
|---|---|
| `FLOW_NOT_FOUND` | 当前 Flow 无法恢复，向用户说明并新建 Flow。 |
| `RESOURCE_NOT_PRESENTED` | 重新展示当前候选，不接受任意 URL 替代。 |
| `SELECTION_VERSION_CONFLICT` | 重新搜索或展示最新候选，再保存选择。 |
| `PLAN_EXPIRED` / `PLAN_ALREADY_USED` | 使用当前选择重新 prepare。 |
| `CONFIRMATION_INVALID` | 不猜测令牌，重新 prepare 并确认。 |
| `IDEMPOTENCY_CONFLICT` | 参数已变化，使用新的幂等键；不要覆盖原请求。 |
| `NETWORK_BLOCKED` / `REDIRECT_BLOCKED` | 视为安全拒绝，不尝试绕过。 |
| `DOWNLOAD_TOO_LARGE` | 让用户缩小范围或选择更小资源，不提高服务端上限。 |
| `ASSET_NOT_ARCHIVABLE` | 查询 Job 状态，不从本地路径强行归档。 |
