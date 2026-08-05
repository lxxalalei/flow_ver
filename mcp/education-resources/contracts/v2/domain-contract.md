# Education Resource Domain Contract v2

协议版本：`2.0.0`

## 1. 当前公共控制面

Python stdio MCP 当前运行 v2，公共 catalog **仅包含 11 个工具**：

1. `resource_flow_start`
2. `resource_flow_status`
3. `resource_search`
4. `resource_presentation_save`
5. `resource_selection_save`
6. `resource_download_prepare`
7. `resource_download_start`
8. `resource_job_status`
9. `resource_job_cancel`
10. `resource_archive`
11. `resource_library_search`

Session Cookie、Token、浏览器登录和会话落盘不属于本 catalog。平台需要认证时，由独立
`session-manager` 负责合法登录和本地会话管理；education-resources 只消费受控授权状态，不能把凭据放进工具结果。

## 2. 权威状态链

MCP 服务端拥有以下权威状态：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive
```

Skill 负责需求理解、候选审查、实际展示、用户确认和结果解释，但不得伪造稳定 ID、位置、版本、摘要或状态。

`resource_search` 只产生 ResultSet 候选。只有模型实际展示后由 `resource_presentation_save` 保存的有序集合，才是
可供用户选择的 Presentation。ResultSet 中未进入当前 Presentation 的隐藏候选不得被选择。

## 3. FlowTask

FlowTask 必须包含 `goal.topic`，可以包含 `goal.outcome`。`user_role` 与 `resource_target` 独立取值为
`child` 或 `parent`，两者均可缺省且不得相互推导。其他有证据支持的用户条件写入 `constraints`；不得为了补齐模型
虚构年龄、年级、教材版本、平台或格式。

输入与持久化任务使用不同 Schema：`input_flow_task` 的每个 constraint 只接受客户端提供的 `kind` 和字符串 `value`；
`persisted_flow_task` 在成功输出和恢复快照中为每项增加服务端生成的 `constraint_id`。客户端不得提交或伪造
`constraint_id`。

`task_version` 由服务端产生。`resource_search` 必须提交当前 `task_version`；过期版本返回稳定的版本冲突错误。
当前 Flow stage 枚举与 runtime 对齐为 `task_ready`、`reviewing`、`presented`、`selected`、`cancelled`、`prepared`、
`downloading`、`downloaded`、`failed`。

## 4. SearchFilters 与 ResultSet

`resource_search` 输入使用 `search_tasks` 数组和可选的 `filters` 对象。

`search_tasks` 是平台任务列表，每个元素包含 `platform` 和 `queries`。模型决定搜哪些平台、每个平台搜什么；
MCP 负责跨平台并行执行和同平台内串行执行。`SearchFilters` 支持 `resource_types`、`languages`、
`published_after` 和 `max_duration_seconds` 作为信息性过滤字段，不包含 `platforms`（平台由 `search_tasks` 指定）。

成功输出固定包含：

```text
task_version
search_run_id
result_set_id
result_version
stage = reviewing
status
platform_runs
candidates
failures
has_more
created_at
```

此外包含通用的 `contract_version`、`ok` 和 `flow_id`。`candidates` 只是待审查候选，不代表已展示集合。
`platform_runs` 如实报告每个平台和每条查询的执行结果（候选数、失败数和状态）；服务端不得把未执行或失败的
搜索伪装成成功。

## 5. Presentation

`resource_presentation_save` 引用同一 Flow 的当前 `result_set_id`。`displayed_resource_ids` 的顺序必须与模型刚刚实际
展示给用户的顺序完全一致，且每个 ID 都必须属于该 ResultSet。

`displayed_resource_ids` **允许空数组**，用于权威记录“本轮没有适合展示的候选”。成功输出：

- `stage = presented`
- `presentation_id`
- `presented_version`
- 有序 `items`，每项包含 1-based `display_position` 和 `resource_id`
- `empty`
- `created_at`

`empty=true` 时 `items` 必须为空；`empty=false` 时至少有一个 item。空 Presentation 不允许产生非空 Selection。
新 Presentation 会使旧 Selection 和尚未消费的旧 Plan 失效。

## 6. Selection

`resource_selection_save` 只接受当前 `presentation_id`、`presented_version` 和 `selected_positions`。客户端不得提交
隐藏候选的 `resource_id`，也不得沿用旧 Presentation 的位置。

成功输出的 `stage` 只能是：

- `selected`：至少选择一个当前可见位置；
- `cancelled`：`selected_positions` 为空，表示用户明确取消。

输出同时包含独立单调递增的 `selection_version`、`selection_digest`、解析后的资源 ID 和 `updated_at`。
A -> B -> A 的选择变化仍必须产生更大的版本和新的摘要，旧 Plan 不得恢复有效。

## 7. DownloadPlan、确认与完整绑定

Prepare 输入必须提交完整 Selection 绑定：

```text
presentation_id + presented_version + selection_version + selection_digest
```

`resource_download_prepare` 重新校验当前 Presentation、Selection、来源、大小、格式和授权策略。成功输出除上述绑定外，
还返回服务端产生的 `plan_id`、`plan_digest`、有期限的确认材料和 `items`。每个 Plan item 必须包含其
`selected_position`，防止下载计划与用户看到的位置脱节。

Start 输入必须提交：

```text
plan_id
+ presentation_id
+ presented_version
+ selection_version
+ selection_digest
+ plan_digest
+ confirmation_token
```

`resource_download_start` 输出必须回显 `plan_id` 与完整不可变绑定：

```text
presentation_id + presented_version + selection_version + selection_digest + plan_digest
```

任意绑定字段不一致都必须拒绝启动，不能自动改用“当前”选择。确认令牌只是 prepare 到 start 的短期过渡秘密，
不等价于可信宿主审批。

## 8. Job 与状态查询

`resource_job_status` 输出必须包含 `plan_id` 和完整绑定：

```text
presentation_id + presented_version + selection_version + selection_digest + plan_digest
```

Job 状态机为 `queued -> running -> succeeded|failed`，以及
`queued|running -> cancelling -> cancelled`。只有成功 Job 返回的 validated Asset 才能归档。

## 9. Flow 恢复与信息最小化

`resource_flow_status` 是恢复权威来源，字段固定使用：

- `current_result_set`
- `current_presentation`
- `current_selection`
- `current_plan`
- `current_job`

不存在的当前对象使用 `null`。不得使用含义模糊的 `latest_result_set`、`latest_job`、`active_plan` 等公共字段名。

Flow 状态输出不得暴露：

- `confirmation_token` 或其 hash；
- Cookie、Token 或浏览器会话秘密；
- 数据库路径、临时目录、下载目录、归档本地路径；
- 可用于绕过服务端校验的内部存储键。

状态快照只返回恢复所需的稳定 ID、版本、摘要、公开元数据和受控 Asset 引用。状态提示与
`allowed_next_actions` 不替代各变更工具的服务端重新校验。

## 10. 稳定 ID、幂等与错误

| 字段 | 格式 | 含义 |
|---|---|---|
| `flow_id` | `flow_<opaque>` | 一次资源任务 |
| `search_run_id` | `search_<opaque>` | 一次搜索执行 |
| `result_set_id` | `rset_<opaque>` | 一次不可变搜索结果集 |
| `presentation_id` | `pres_<opaque>` | 实际展示的有序集合 |
| `resource_id` | `res_<opaque>` | 服务端规范化候选 |
| `plan_id` | `plan_<opaque>` | 有期限的下载准备结果 |
| `job_id` | `job_<opaque>` | 异步下载任务 |
| `asset_id` | `asset_<opaque>` | 服务端受控且已校验资产 |

所有状态写入和 Job 控制工具都必须使用幂等键。相同范围、相同键和相同规范请求返回原结果；同一键配合不同请求返回
`IDEMPOTENCY_CONFLICT`。业务错误使用结构化结果；协议损坏和不可恢复内部错误才抛出异常。

v2 错误码目录在同一 major 内 append-only。runtime 产生的 item failure 包括 `DOWNLOAD_FAILED` 和
`JOB_CANCELLED`，两者均已进入稳定错误码目录；消费者必须按 `retriable` 字段决定恢复策略，不得依赖未登记字符串。

## 11. 安全边界

- 只允许受策略控制的 `http`/`https` 来源。
- 阻断本机、私网、链路本地、云元数据和非预期重定向目标。
- 强制超时、重试上限、并发限制、`max_bytes`、内容类型和真实文件格式校验。
- 不绕过登录、验证码、付费墙、DRM 或明确访问控制。
- `resource_archive` 只接受 `asset_id` 与所属 `job_id`，不接受本地路径、任意 URL 或文件字节。
- 大文件和二进制不得进入 Tool JSON 或模型上下文。
