# Education Resource Contract v1 / v2 Compatibility

## 状态

- `contracts/v1/` 冻结在 `1.0.0`，仅作为历史兼容、审计和显式回滚依据；不再增加字段、工具或运行语义。
- `contracts/v2/` 从 `2.0.0` 开始，是当前 Python stdio MCP 正在运行的公共控制面。
- 当前 v2 catalog 仅包含 11 个教育资源工具；Session Cookie、Token 和登录工具不属于该 catalog。

## 破坏性差异

| v1 | v2 |
|---|---|
| `intent.topic/learning_goal/audience` | `task.goal + user_role + resource_target + constraints` |
| Search 直接产生 `presented_version` | Search 绑定 `task_version` 并产生不可变 ResultSet |
| 搜索结果默认等同展示集合 | 实际展示后由 `resource_presentation_save` 保存 Presentation |
| Search 顶层平台参数 | `filters: SearchFilters` 对象 |
| Selection 接受 `resource_id` | Selection 接受当前 Presentation 的 1-based `selected_positions` |
| `selection_version` 与展示版本耦合 | `presented_version`、`selection_version` 独立递增 |
| Plan 主要绑定 Selection 版本 | Plan 绑定 Presentation、Selection 与 `plan_digest` |
| 无 Flow 恢复工具 | `resource_flow_status` 返回无确认秘密的 `current_*` 快照 |
| 9 个领域工具 | 11 个领域工具，新增 Presentation 保存与 Flow 恢复 |

v1 的 `audience` 不能可靠转换为 v2 的 `user_role` 或 `resource_target`。迁移不得猜测；无法确定语义的旧任务应要求用户
重新建立 v2 Flow。旧 Plan、旧确认材料和旧展示编号不能迁移为可执行 v2 状态。

## 工具名称与协商

v2 保留九个教育业务工具名称，并增加：

- `resource_presentation_save`
- `resource_flow_status`

虽然部分名称与 v1 相同，但输入输出已经破坏性变化。调用方必须发送精确的
`contract_version: "2.0.0"`，不得在同一个模型可见 Tool Schema 中混合 v1/v2 `oneOf`。

当前公共 catalog 的精确工具集合由 `tool-catalog.json` 定义，并由 `schemas/tool-catalog.schema.json` 限制为 11 项。
Session Manager MCP 独立负责合法登录与会话保存；v1 遗留 Session Schema 不复制到 v2。

## 数据和恢复要求

v2 持久化 ResultSet、Presentation 顺序、独立 Selection 版本、Selection 摘要和 Plan 摘要。旧 Flow 数据不得原地静默
改写；迁移必须可审计、可回滚，并保证旧 Plan 不会在 A -> B -> A 后重新有效。

`resource_flow_start` 的输入任务与成功输出任务使用不同 Schema。客户端 constraint 只提交 `kind/value`；服务端持久化
后增加 `constraint_id`，该 ID 不属于可由客户端回填的输入字段。v2 错误码保持 append-only，runtime item failure 使用的
`DOWNLOAD_FAILED` 与 `JOB_CANCELLED` 已登记。

`resource_flow_status` 的公共恢复键只能使用：

```text
current_result_set
current_presentation
current_selection
current_plan
current_job
```

不得返回 `latest_*`、`active_*`、确认 token/hash 或本地路径。
