# Education Resources MCP 工作流

## 通用规则

- 使用 `contract_version: "1.0.0"`。
- 有副作用的首次调用生成 16–128 位 `idempotency_key`；同一请求重试复用原键，参数变化使用新键。
- 业务结果 `ok=false` 时读取结构化错误，不继续假定状态转换成功。
- 内部 ID、版本、position 和确认令牌只用于工具调用，不向用户复述。
- 状态不确定时调用 `resource_flow_status`，不从对话文本恢复权威状态。
- 当前公共 catalog 为 `1.5.0`，仍精确包含 13 个工具；Capability Descriptor catalog 的
  `catalog_version=1.1.0` / `registry_version=1.1.0` 是独立版本域，不能混同。

## Task 映射

`resource_flow_start` 使用独立任务模型：

| 字段 | 规则 |
|---|---|
| `goal` | 保留用户核心主题、问题或希望完成的学习行为。 |
| `user_role` | 当前对话者是孩子、家长或未知；不能从资源对象推导。 |
| `resource_target` | 资源给孩子使用、给家长参考或未知；不能从对话者身份推导。 |
| `constraints` | 只保存有证据支持的 must、prefer、exclude、背景和具体使用条件。 |

未知值按 Schema 省略或使用明确的 unknown，不为补齐模型追问。不得把 `user_role` 与 `resource_target` 合并成 audience，也不得虚构用户背景、动机、平台或格式。

## 唯一合法主链路

```text
resource_flow_start
-> resource_search 或 resource_browse_creator
-> 实际展示审查后的有序子集
-> resource_presentation_save
-> 等待用户选择
-> resource_selection_save(selected_positions)
-> resource_download_prepare
-> 展示计划并等待明确确认
-> resource_download_start
```

搜索、展示提交和选择是三个独立状态转换。

## Search：只产生 ResultSet

### 搜索前的 session 检查（可选）

大部分搜索平台无需登录即可使用。少数平台（bilibili、zhihu）有登录态时结果更全面，
weibo 必须登录才能搜索。

搜索前可以调用 session-manager 的 `session_status` 检查目标平台的登录状态，
但不要把检查作为搜索的前置阻塞条件。推荐流程：

1. 直接提交 `resource_search`——MCP 自动从 SessionStore 读取已有 Cookie。
2. 如果返回的 `platform_runs` 中某平台结果为 0 且不是"免登录"平台，提醒用户登录。
3. 用户选择登录时，引导通过 session-manager 完成，然后用相同 `flow_id` 重新搜索。

同一会话中对同一平台只提醒一次。

### 搜索调用

调用 `resource_search` 后保存：

- `flow_id`
- `result_set_id`
- `result_version`
- 候选 `resource_id`

返回的 `candidates` 只是 ResultSet，不是已展示集合，不能直接用于 Selection。模型可以审查和过滤，但不能创建候选、修改 ID 或混合不同 ResultSet。

同一目标换搜索角度时可创建新 ResultSet。新结果出现后仍要重新审查、实际展示并提交 Presentation；不能沿用旧编号指向新候选。

### Creator 浏览（社媒主页抓取）

当用户提供**创作者主页 URL** 或明确想浏览某创作者的全部内容时（如"把这个人发的视频都找出来"），使用 `resource_browse_creator` 代替 `resource_search`：

```json
{
  "contract_version": "1.0.0",
  "flow_id": "flow_...",
  "task_version": 1,
  "idempotency_key": "browse-...",
  "platform": "douyin",
  "creator_id": "https://www.douyin.com/user/MS4wLjAB...",
  "limit": 50
}
```

规则：

- `creator_id` 接受完整主页 URL 或裸 ID（sec_user_id / mid / url_token，取决于平台）。
- **只支持社媒平台**：`douyin`、`bilibili`、`weibo`、`zhihu`。教育/资源平台（smartedu、cctv、nlc 等）返回 `FEATURE_NOT_SUPPORTED`。
- 返回的也是 ResultSet，后续走相同的 Presentation → Selection → Download 主链路。
- creator ResultSet 和 keyword ResultSet 一样是独立候选集，不混合。
- 社媒平台同样适用搜索前的 session 检查规则（weibo 必须登录，bilibili/zhihu 有登录更全面）。

判断用 search 还是 browse_creator：

| 用户意图 | 工具 |
|---------|------|
| "搜一下编程副业的视频" | `resource_search`（关键词） |
| "把这个 UP 主的视频都下载了" | `resource_browse_creator`（主页 URL） |
| "这个人发的内容有什么" | `resource_browse_creator`（主页 URL） |

## Presentation：实际展示后提交

先形成最终有序子集并实际向用户展示，再调用 `resource_presentation_save`：

```json
{
  "flow_id": "flow_...",
  "result_set_id": "rset_...",
  "idempotency_key": "presentation-...",
  "displayed_resource_ids": ["res_a", "res_c", "res_f"]
}
```

必须满足：

- 所有 ID 来自同一个当前 ResultSet。
- 数组顺序与用户刚看到的编号完全一致。
- 不补入未展示项，不遗漏已展示且可选择的项。
- 不在实际展示前预先保存。

成功后保存 `presentation_id`、`presented_version` 和 MCP 返回的有序 items。只有此时才能邀请用户选择。失败时当前文本列表不是可选择的权威 Presentation；先 `resource_flow_status`，必要时重新展示并重试。

## Selection：只提交 positions

用户明确选择后调用 `resource_selection_save`：

```json
{
  "flow_id": "flow_...",
  "presentation_id": "pres_...",
  "presented_version": 4,
  "idempotency_key": "selection-...",
  "selected_positions": [1, 3]
}
```

规则：

- position 只来自当前 Presentation。
- 不向 Selection 传 ResultSet 的隐藏资源 ID。
- “全部”只展开为当前 Presentation 的全部位置。
- 修改选择时使用新幂等键并提交完整 positions。
- 空数组表示明确取消；取消后不 prepare。

保存成功后使用 MCP 返回的真实 `selection_version`，不要把它等同于 `presented_version`。

## 下载准备和确认

非空选择后原样携带当前 `presentation_id`、`presented_version`、`selection_version` 和 `selection_digest` 调用 `resource_download_prepare`。

服务端在 prepare 时建立以下 authority chain，Skill 不生成其中任何业务 ID、Provider 或摘要：

```text
Capability Descriptor
-> Runtime Readiness
-> persisted Resolution / Representation
-> Eligibility
-> Plan capability binding + authority_digest
-> fresh Execution binding
-> exact Provider
-> persisted Acquisition Outcome
-> Asset / AssetBundle
-> sanitized Job status projection
```

向用户展示：

- 当前选择；
- 计划格式或容器；
- 大小上限和有效期；
- 风险、访问限制，以及 Plan 明确声明的 capability fallback（若有）。

只有用户看过当前计划并明确确认后，才调用 `resource_download_start`。原样传递当前 `plan_id`、
`plan_digest`、完整 Presentation/Selection 绑定元组和 `confirmation_token`，start 使用新的幂等键；
网络重试复用该键。`authority_digest` 是可选兼容校验输入：可以省略并让服务端读取不可变 Plan
中的真实摘要；若传递，只能原样回显 prepare 返回值。`plan_digest` 已绑定该摘要，Skill 不生成、
重算或替换任何 digest。

start 时服务端必须重新校验 readiness、Resolution/Representation、Eligibility、Selection 和精确
Provider/strategy/scope，并保存 fresh immutable Execution binding。省略 `authority_digest` 不是
fallback；平台 Registry、旧 options、扩展名和 generic Provider 都不能替代已绑定路线。

用户拒绝、修改选择、创建新 Presentation、Plan 过期或状态冲突时，不得 start；重新 prepare 并再次确认。

## Flow 恢复

以下情况先调用 `resource_flow_status`：

- OpenClaw、MCP 或会话重启；
- 上下文被压缩；
- 工具响应超时或丢失；
- 不确定当前 ResultSet、Presentation、Selection、Plan 或 Job；
- 登录流程完成后返回资源任务。

按状态恢复：

| 权威状态 | 动作 |
|---|---|
| 只有 ResultSet | 继续审查；实际展示后提交 Presentation。 |
| 当前 Presentation，无 Selection | 使用返回 items 的 position 恢复编号，等待用户选择。 |
| 当前 Selection，无 Plan | 原样携带当前 Presentation/Selection 绑定元组 prepare。 |
| 当前有效 Plan，未确认 | 再次展示计划，等待明确确认。 |
| 已有 Job | 查询真实状态；不重复 start。 |
| Presentation/Selection/Plan 已失效 | 丢弃旧编号、position、版本和令牌，从状态允许的阶段继续。 |

`flow_status` 返回内容与聊天记忆冲突时，以 MCP 为准。

## 独立 Session Manager

平台登录由独立 `session-manager` / `session-login-flow` 处理，不属于 education-resources 主链路。

### 主动检查（推荐）

搜索前如果计划使用 bilibili、zhihu 或 weibo 等登录增强/必需平台，可以先调 session-manager
检查状态。未登录时不阻塞搜索，但在搜索结果返回后根据 `platform_runs` 判断是否提醒用户。

### 被动处理

当搜索或下载返回 `AUTH_REQUIRED`、会话失效或明确要求登录时：

1. 暂停当前资源状态转换，保留 `flow_id`。
2. 调用独立 session-manager 检查所需平台。
3. 让用户在 OpenClaw 受控浏览器中自行登录；不代填账号、验证码或 MFA。
4. 按独立登录 Skill 完成捕获、最小化处理和本地保存；不在对话中展示 Cookie/Token。
5. 登录成功后调用 `resource_flow_status`，从权威阶段继续搜索或下载。

本 Skill 不直接设计 Cookie 名称、Storage 键、浏览器脚本或凭据落盘方式，也不把 Cookie/Token 传入 education-resources 业务工具。

## Job、取消、归档和检索

- `queued`、`running`：仍在执行。
- `cancelling`：取消处理中。
- `succeeded`：只使用返回的 validated Assets。
- `failed`：解释结构化原因；只在可重试且外部条件变化时重试。
- `cancelled`：停止，不归档该 Job 的文件。

Job 没有 `partial` 状态。`ActualOutcome.status="partial"` 是服务端按资源持久化的 acquisition
outcome 事实；缺少 Bundle 成员时由 `AssetBundle.completion="partial"` 和逐项失败事实表达，
非取消 Job 仍终结为 `succeeded` 或 `failed`，取消仍为 `cancelled`。
`resource_job_status.outcomes` 只是 canonical `ActualOutcome` 的脱敏公共 projection；Skill
只能解释其中的 planned、可用时的 execution、actual、
Asset/Bundle 引用和失败，不能把该 projection 回填为持久化对象或补造 locator、路径与凭据。
legacy Outcome 省略 execution 时保持“未知”，不得从 planned 或 Provider metadata 推导。

归档或检索前读取 `library-structure.md`。`resource_archive` 只接受成功 Job 返回的
`job_id`、ready `asset_id`、幂等键和经过证据判断的归档元数据，不接受本地路径。

- 新归档提交 `learning-v1` 嵌套分类，只从固定领域注册表选择主领域和次领域；证据不足时使用 `needs_review` 或 `unclassified`。
- 不提交格式目录、文件名或来源事实。标题、来源、媒体类型、扩展名、大小和 SHA-256 以服务端 Resource/Asset 为准。
- MCP 决定安全相对目录、内容去重和 `pending -> ready` 提交；只有工具返回成功后才能向用户说明已归档或已去重。
- 同一幂等键只重放完全相同的请求；分类或辅助元数据变化时使用新键，不用旧键覆盖请求。

`resource_library_search` 按 Flow/身份边界调用。结构化字段精确过滤，同字段多值为 OR、
跨字段为 AND；自由关键词只对标题、主题、标签和备注做受控模糊匹配。继续翻页时原样提交
MCP 返回的不透明 `next_cursor`，不猜测游标或排序。只解释 ready 结果；不得展示数据库路径、
任务目录或绝对路径，只能使用 MCP 返回的资料库内安全相对路径。

## 错误恢复

| 错误码或状态 | 处理 |
|---|---|
| `FLOW_NOT_FOUND` | 说明无法恢复，根据仍有效需求建立新 Flow。 |
| `AUTH_REQUIRED` | 委托独立 session-manager；成功后 `flow_status`。 |
| `RESULT_SET_NOT_FOUND` / `RESULT_SET_SUPERSEDED` | 调用 `flow_status`，重新搜索或使用当前 ResultSet。 |
| `PRESENTATION_REQUIRED` | 审查 ResultSet，实际展示后调用 `presentation_save`。 |
| `PRESENTATION_NOT_FOUND` / `PRESENTATION_VERSION_CONFLICT` | 使用 `flow_status` 返回的当前 Presentation，重新编号并等待选择。 |
| `PRESENTATION_ITEM_INVALID` / `RESOURCE_NOT_PRESENTED` | 不替换成隐藏 ID；重新提交正确展示集或让用户重选。 |
| `SELECTION_VERSION_CONFLICT` / `SELECTION_CHANGED` | 恢复当前 Presentation 和 Selection，重新保存选择或 prepare。 |
| `PLAN_EXPIRED` / `PLAN_ALREADY_USED` | 使用当前 Selection 重新 prepare。 |
| `CAPABILITY_*` / `READINESS_*` / `ELIGIBILITY_*` / `RESOLUTION_STALE` | 不换用 generic Provider；重新读取 Flow/Resolution，必要时重新 Inspect、prepare 和确认。 |
| `PLAN_BINDING_CONFLICT` / `PROVIDER_*` / `OUTCOME_MISMATCH` | 停止当前转换并解释服务端绑定失败；不得重算摘要或自行替换 Provider/strategy/scope。 |
| `CONFIRMATION_INVALID` | 不猜令牌，重新 prepare 并确认。 |
| `IDEMPOTENCY_CONFLICT` | 参数变化时使用新键，不覆盖原请求。 |
| `NETWORK_BLOCKED` / `REDIRECT_BLOCKED` | 视为安全拒绝，不尝试绕过。 |
