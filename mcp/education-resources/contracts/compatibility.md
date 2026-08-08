# Education Resource Contract — Historical Migration Notes

## 状态

- 历史教育资源 v1 契约已从工作区移除；本文件只保留历史 v1 到历史 v2 迁移阶段的差异和边界说明。
- 当前契约版本从 `1.0.0` 开始，是当前 Python stdio MCP 正在运行的公共控制面。
- 当前 catalog 为 `1.3.0`，包含 13 个教育资源工具；Session Cookie、Token 和登录工具不属于该 catalog。
- 下文的 v1/v2 是迁移记录标签，不是当前目录名或可调用的协议版本。当前公共契约只位于 `contracts/`。

## 破坏性差异

| 历史 v1（已移除） | 历史 v2（迁移阶段） |
|---|---|
| `intent.topic/learning_goal/audience` | `task.goal + user_role + resource_target + constraints` |
| Search 直接产生 `presented_version` | Search 绑定 `task_version` 并产生不可变 ResultSet |
| 搜索结果默认等同展示集合 | 实际展示后由 `resource_presentation_save` 保存 Presentation |
| Search 顶层平台参数 | `filters: SearchFilters` 对象 |
| Selection 接受 `resource_id` | Selection 接受当前 Presentation 的 1-based `selected_positions` |
| `selection_version` 与展示版本耦合 | `presented_version`、`selection_version` 独立递增 |
| Plan 主要绑定 Selection 版本 | Plan 绑定 Presentation、Selection 与 `plan_digest` |
| 无 Flow 恢复工具 | `resource_flow_status` 返回无确认秘密的 `current_*` 快照 |
| 9 个历史领域工具 | 11 个过渡领域工具，新增 Presentation 保存与 Flow 恢复 |

上表只描述历史迁移阶段，不代表当前工具数量。当前公共 `contract_version=1.0.0` 的
`tool-catalog.json` 精确包含 13 个工具，并额外包含
`resource_browse_creator`；当前目录不是 `contracts/v1/` 或 `contracts/v2/`。

历史 v1 的 `audience` 不能可靠转换为历史 v2 的 `user_role` 或 `resource_target`。迁移不得猜测；无法确定语义的旧任务应要求用户
重新建立 Flow。旧 Plan、旧确认材料和旧展示编号不能迁移为可执行状态。

## 工具名称与协商

历史 v2 迁移阶段保留九个教育业务工具名称，并增加：

- `resource_presentation_save`
- `resource_flow_status`

虽然部分名称与历史 v1 相同，但输入输出已经破坏性变化。当前调用方必须发送精确的
`contract_version: "1.0.0"`，不得混合不同版本 `oneOf`。

当前公共 catalog 的精确工具集合由 `tool-catalog.json` 定义；其中 `resource_browse_creator` 的输入、输出、
`platform_runs` 和独立幂等范围已由 Schema、运行时与契约测试共同约束。其他工具仍以各自 Schema 和测试为准。
Session Manager MCP 独立负责合法登录与会话保存。

## 当前 1.0.0 的 Inspection 加法

0019 将 `catalog_version` 从 `1.0.0` 增至 `1.1.0`，新增 `resource_inspect`；公共
`contract_version` 仍为 `1.0.0`，既有 12 个工具的输入输出语义不因该加法改变。

`resource_inspect` 输入严格只有：

```text
contract_version + flow_id + resource_id + idempotency_key
```

服务端从当前 Flow 的资源记录取得来源，不接受 URL、路径、批量 ID、检查深度、Cookie、Token
或其他凭据。Candidate、ResolvedResource、Representation 和 Resolution 是分层对象；
Resolution 由 migration 3 的 `resource_resolutions` 独立保存，不改写 immutable ResultSet。
输出不含 locator、文件字节或本地路径；Inspect 也不执行下载或归档。

幂等 scope 为 `resource_inspect:{flow_id}`。`resolved`/`partial` 结果按
`resource_id + source_fingerprint + inspect-v1` 缓存；`unresolved` 保留用于审计和恢复，但新
幂等键会重新检查。`resource_flow_status` 新增 `current_resolutions` 安全摘要。

Registry 只为 `generic`、`bilibili`、`nlc`、`annas-archive`、`ximalaya`、`zhihu`、`smartedu`
启用 inspect；其他平台返回结构化 `FEATURE_NOT_SUPPORTED`。Generic 的有界 GET、逐跳 SSRF、
1 MiB 和 MIME/魔数校验，以及七平台 Inspector 的当前固定夹具定向测试，属于 0019 当前实现事实，
尚不代表真实平台网络、全量测试或 OpenClaw 验收已完成。

## 当前 1.0.0 的 Adaptive Retrieval 加法

0020 将 `catalog_version` 从 `1.1.0` 增至 `1.2.0`，公共工具仍为 13 个，
`contract_version` 仍为 `1.0.0`。旧 `resource_search` 请求省略 `mode` 时继续按
`replace` 运行；新增的 `extend` 必须绑定当前 `base_result_set_id`，不会修改旧 ResultSet。

`direction` 是非权威语义目的；`mode`、`base_result_set_id`、`round`、`provenance` 和
`coverage` 是可选兼容字段。服务端持久化并恢复实际运行事实，模型不能把这些字段作为输入
伪造。幂等请求哈希包含 mode 与 base；同一键的历史重放先于 stale-base 校验。

由于既有 Schema 使用 `additionalProperties: false`，缓存当时 `1.1.0`/`1.2.0` 输出 Schema 的严格客户端
可能拒绝新增输出字段。客户端应在 initialize/tools/list 时刷新当前 `1.3.0` catalog；若未来
必须支持不能刷新 Schema 的离线客户端，需要显式输出投影或新的协商版本，不能宣称完全无感。

## 当前 1.0.0 的 AssetBundle 加法

0022 将 `catalog_version` 从 `1.2.0` 升至 `1.3.0`，公共 `contract_version` 仍为 `1.0.0`，
工具仍精确为 13 个。此版本只做输出兼容加法：不删除或改名既有字段，不改变既有 required、ID
含义或 Job 状态机，不新增 Bundle Tool。

服务端在确实形成 Bundle 关系时，可在以下输出对象中追加可选字段：

- `asset_summary`、`resource_archive.success`、`resource_library_search.library_asset`：
  `bundle_id`、`role`、`order`、`bundle_completion`；
- `item_failure`：`bundle_id`、`role`、`order`、`item_key`；
- `resource_job_status.success`：`completion`，值为 `complete|partial`；
- `resource_flow_status.current_job`：`completion` 与 `bundle_ids`。

公共 `role` 的固定枚举为 `primary`、`subtitle`、`cover`、`metadata`、`attachment`、
`transcript`、`companion`。`completion` 是结果完整度，不是新的 Job `status`；Job 仍只使用
`queued`、`running`、`cancelling`、`succeeded`、`failed`、`cancelled`。`partial` 只允许在
已有可用 primary、同时存在失败 BundleItem 时表达，不能把取消或无 primary 的失败伪装为 partial。

Archive 的输入仍只接受服务端校验的 `asset_id` 和原有绑定，Library 仍以 Asset 为返回粒度；
Bundle 关系由服务端生成，`bundle_id`/`item_key` 不是客户端可提交的路径或业务关系。严格缓存旧
`1.2.0` Schema 的客户端必须刷新 `tools/list` 后再消费 `1.3.0` 的可选输出字段；不能刷新时应
使用服务端提供的旧字段投影或显式拒绝未知字段。

## 数据和恢复要求

持久化 ResultSet、Presentation 顺序、独立 Selection 版本、Selection 摘要和 Plan 摘要。旧 Flow 数据不得原地静默
改写；迁移必须可审计、可回滚，并保证旧 Plan 不会在 A -> B -> A 后重新有效。

`resource_flow_start` 的输入任务与成功输出任务使用不同 Schema。客户端 constraint 只提交 `kind/value`；服务端持久化
后增加 `constraint_id`，该 ID 不属于可由客户端回填的输入字段。错误码保持 append-only，runtime item failure 使用的
`DOWNLOAD_FAILED` 与 `JOB_CANCELLED` 已登记。

`resource_flow_status` 的公共恢复键只能使用：

```text
current_result_set
current_presentation
current_selection
current_plan
current_job
current_resolutions
```

不得返回 `latest_*`、`active_*`、确认 token/hash 或本地路径。

## `learning-v1` 归档形状扩展

学习资料归档在当前 `1.0.0` 契约内继续使用 `learning-v1` 分类注册表，但 Archive 与 Library Search 的
Tool Schema 增加了机器可校验的 `learning-v1` 分类形状。这是经明确记录的 additive shape 扩展，
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

由于输出 Schema 使用 `additionalProperties: false`，固定缓存旧 Schema 并对输出做严格校验的消费者
会将新字段视为不兼容。本地 MCP 消费者必须在 initialize/tools/list 时刷新当前 Schema；不得将此风险
描述为对任意离线客户端的完全无感兼容。
