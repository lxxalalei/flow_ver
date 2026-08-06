# Education Resource Contract v1 / v2 Compatibility

## 状态

- 历史教育资源 v1 契约已从工作区移除；本文件保留 v1/v2 的迁移差异和边界说明。
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

## learning-v1 归档形状扩展

学习资料归档在 v2 major 内继续使用 `contract_version: "2.0.0"`，但 Archive 与 Library Search 的
Tool Schema 增加了机器可校验的 `learning-v1` 分类形状。这是经明确记录的 additive v2 shape 扩展，
不是 v1 兼容层，也不改变已有字段的合法含义。

输入兼容规则：

- `resource_archive.metadata` 继续接受 `title`、`collection`、`tags`、`notes`。
- tools/list 曾经暴露的平铺 `primary_domain`、`topics`、`source_name` 继续接受，但标记为兼容字段。
- 新调用应提交 `metadata.classification`；服务端对所有新归档持久化规范化后的嵌套分类。
- 平铺值与嵌套值同时出现时必须一致，否则返回参数错误。
- 已知旧中文领域按 `taxonomy/learning-v1.json` 显式映射；不能可靠映射的原值保留在旧元数据或
  `legacy_classification_raw` 中，并转为 `needs_review`。
- `primary_domain: "待分类"` 和 `primary_domain: "亲子陪伴"` 不会被当作新的合法领域。

Library Search 保留已暴露的单值 `primary_domain` 过滤，并增加规范数组过滤。旧 Archive 记录在前向迁移后
仍可查询；无法分类的旧记录以 `needs_review` 返回，不会删除原 `metadata_json`。

输出的 `classification`、`primary_domain_display_name`、`resource_format` 和 `relative_path` 是新增字段。
`library_path` 作为兼容别名可以继续返回，但其含义被收紧为安全相对路径，不再允许绝对路径。

由于旧输出 Schema 使用 `additionalProperties: false`，固定缓存旧 Schema 并对输出做严格校验的消费者
会将新字段视为不兼容。本地 MCP 消费者必须在 initialize/tools/list 时刷新当前 Schema；不得将此风险
描述为对任意离线 v2 客户端的完全无感兼容。
