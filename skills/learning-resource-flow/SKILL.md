---
name: learning-resource-flow
description: 面向孩子和家长的教育资源唯一对话入口。用户想寻找、推荐、比较、筛选、下载、收藏或再次查找课程、视频、图书、文章、练习、活动方案等资源时使用；也用于从模糊的学习或成长问题出发澄清目标、审查搜索候选、提交实际展示集、保存用户选择，以及恢复、确认、取消或查询资源任务。通过 education-resources v2 MCP 控制 Flow、ResultSet、Presentation、Selection、Plan、Job 和 Asset；平台登录交给独立 session-manager。
---

# Learning Resource Flow

## 结果

帮助用户获得真正符合当前目标和明确约束的教育资源，并在明确选择和确认后安全下载或归档。让用户始终用自然语言交流，不要求用户理解 Skill、MCP、平台参数或业务 ID。

不要把搜索召回、完成工具调用、返回很多链接或模型自己记住状态当成成功。

## 分工

由本 Skill 负责：

- 理解需求，区分用户事实、可靠推断和低风险默认。
- 判断是否需要澄清，设计搜索方向。
- 审查 ResultSet 候选的相关性、内容门槛、儿童安全、证据、可用性和组合价值。
- 实际向用户展示经过审查的有序子集，并把完全相同的顺序提交为 Presentation。
- 解释选择、计划、风险、进度、失败和下一步。

由 `education-resources` v2 MCP 负责：

- Flow、ResultSet、Presentation、Selection、Plan、Job 和 Asset 的权威状态。
- 结果集和展示集成员校验、位置映射、版本、幂等、恢复、下载、取消和归档。

搜索结果不是已展示结果。模型不得把 ResultSet 自动称为 Presentation，也不得让用户选择未进入当前 Presentation 的隐藏候选。

平台登录不属于本 Skill 或 `education-resources` 控制面。需要认证时暂停当前流程，交给独立 `session-manager` 和 `session-login-flow` 完成合法登录与会话保存；登录成功后调用 `resource_flow_status` 恢复，不在本 Skill 中复制 Cookie 捕获逻辑。

## 当前任务模型

内部维护一个独立三部分任务模型：

- `user_role`：当前对话者是孩子、家长或未知。
- `resource_target`：资源给孩子使用、给家长参考或未知。
- `constraints`：用户明示或有充分证据支持的 must、prefer、exclude 及具体使用条件。

同时保存核心目标 `goal`。`user_role` 与 `resource_target` 相互独立，不能互相推导；未知保持未知。年龄和年级不是默认必填信息。把该模型按 v2 Task Schema 传给 `resource_flow_start`，不得回退为混合的 audience 字段。

处理模糊请求、冲突、短回答或敏感儿童主题时读取 `references/intent-and-clarification.md`。

## 强制控制流

正常流程严格使用：

```text
resource_flow_start
-> resource_search                    # 只产生 ResultSet 候选
-> 模型审查并实际向用户展示有序子集
-> resource_presentation_save         # 提交刚才实际展示的完全相同集合和顺序
-> 等待用户选择
-> resource_selection_save            # 只提交当前 Presentation 的 positions
-> resource_download_prepare
-> 向用户展示计划并等待明确确认
-> resource_download_start
```

之后使用 `resource_job_status`、`resource_job_cancel`、`resource_archive` 和 `resource_library_search`。

不得省略、交换或合并 `search -> 实际展示 -> presentation_save -> 用户选择 -> selection_save`。尤其禁止：

- 搜索成功后直接调用 `selection_save`。
- 在实际展示前调用 `presentation_save`。
- 把 ResultSet 全量候选默认记为已展示。
- 把未展示候选、旧 Presentation 项或模型生成的资源放入选择。
- 根据对话文本猜测 position、版本或当前状态。

## 对话决策循环

### 1. 理解并判断是否澄清

理解核心目标、`user_role`、`resource_target` 和显式 `constraints`。只有核心主题、搜索路线、硬约束或资源对象歧义会实质改变结果时才澄清；一次只问一个容易回答的问题。

不要为了补齐用户角色、资源对象、年龄、年级、平台、格式或数量而追问。只有教材同步等确实必须定位范围时才询问年级或册次。需求足够时直接搜索；搜索本身不需要确认。

### 2. 设计搜索方向

搜索前读取 `references/discovery-strategy.md`。查询只由目标、`resource_target` 和显式 `constraints` 驱动；`user_role` 只影响交互方式。不要用“优质、权威、适合孩子、高赞”等评价词替代后续审查。

### 3. 建立或恢复 Flow

首次任务调用 `education-resources__resource_flow_start`。如果已有 `flow_id` 但状态不确定、上下文被压缩、工具响应丢失、OpenClaw 或 MCP 重启，先调用 `education-resources__resource_flow_status`，不要重新创建 Flow 或从聊天记录猜测状态。

用户改变核心目标、资源对象或硬约束时建立新 Flow。同一目标下换搜索角度时可继续当前 Flow。

### 4. 搜索只获得 ResultSet

调用 `education-resources__resource_search`，保存 `result_set_id`、结果版本和候选 `resource_id`。把返回项称为“搜索候选”或“待审查候选”，不能称为“已展示候选”。

需要认证的平台返回 `AUTH_REQUIRED` 或同类登录状态时，按 `references/mcp-workflow.md` 委托独立 session-manager；登录成功后先 `resource_flow_status` 再继续。

### 5. 审查、实际展示并提交 Presentation

读取 `references/candidate-judgment.md` 和 `references/response-guidelines.md`：

1. 从一个 ResultSet 中排除偏题、不安全、违反硬约束、不可定位或无实际价值的项。
2. 形成少量、有序、可解释的展示子集。
3. 按最终顺序实际向用户展示并编号；记录每个位置对应的 `resource_id`。
4. 展示后立即调用 `education-resources__resource_presentation_save`，提交该 `result_set_id` 和刚才实际展示的完整有序 `displayed_resource_ids`。
5. 只有保存成功后，才邀请或接受用户按编号选择。

`presentation_save` 的集合和顺序必须与用户刚看到的列表完全一致。保存失败时，不接受选择；解释列表尚未建立为可选择状态，恢复状态后重新展示并提交。

### 6. 按 positions 保存选择

用户选择后调用 `education-resources__resource_selection_save`：

- 传当前 `presentation_id`、`presented_version` 和用户选择的 `selected_positions`。
- position 必须来自当前 Presentation，不能由模型映射到隐藏资源 ID。
- “这些都要”只表示当前 Presentation 的全部位置。
- 用户修改选择时提交完整的新 positions 集合，不在旧 Selection 上隐式增删。
- 用户取消时提交空 positions；取消后停止下载流程。

### 7. Prepare、确认和 Start

非空 Selection 必须原样携带当前 `presentation_id`、`presented_version`、`selection_version` 和 `selection_digest` 调用 `resource_download_prepare`。向用户展示计划中的资源、格式或容器、大小上限、有效期、风险和降级，不展示确认令牌或内部 JSON。

只有用户看过当前有效计划并明确确认后，才原样使用 MCP 返回的 `plan_id`、`plan_digest`、完整 Presentation/Selection 绑定元组和 `confirmation_token` 调用 `resource_download_start`。用户拒绝、修改选择、Presentation 变化或 Plan 过期后必须重新 prepare 和确认。

## 恢复规则

`resource_flow_status` 是恢复权威来源：

- `reviewing` 且只有 ResultSet：继续审查；实际展示后再保存 Presentation。
- 存在当前 Presentation、尚无 Selection：只按状态返回的有序 items 恢复编号并等待选择。
- 存在 Selection、尚无 Plan：原样携带当前 Presentation/Selection 绑定元组 prepare。
- 存在有效 Plan、尚未确认：重新展示当前计划并等待确认，不能自动 start。
- 存在 Job：按真实状态查询、取消或报告；`queued`、`running`、`cancelling` 都不是成功。
- Presentation、Selection 或 Plan 已 superseded/expired：不得沿用旧编号、positions、版本或令牌。

如果状态返回的 Presentation 与对话记忆不一致，以 MCP 为准，并向用户简短说明候选列表已更新。

## 强制边界

- 只使用 MCP 返回的 ID、版本、position、Plan、Job 和 Asset，不猜测、不伪造。
- ResultSet 只能用于审查；只有当前 Presentation 可用于用户选择。
- 不向工具传本地路径、脚本、二进制、shell 命令、任意 URL、Cookie 或 Token。
- 不绕过登录、验证码、付费墙、DRM、版权或访问控制。
- 不把标题宣传、平台热度、平台名气或模型常识写成已核验事实。
- MCP 返回 `ok=false` 时停止当前状态转换，按结构化错误恢复。
- 大文件和二进制不进入对话上下文，只展示 Asset 元数据或受控访问结果。

## 按需资料

- `references/intent-and-clarification.md`：独立的 user_role、resource_target、constraints 模型和澄清。
- `references/discovery-strategy.md`：搜索方向、查询设计、来源策略和停止条件。
- `references/site-whitelist.md`：可信站点定向搜索参考。
- `references/candidate-judgment.md`：ResultSet 审查、展示子集和证据护栏。
- `references/mcp-workflow.md`：v2 工具顺序、幂等、Presentation、恢复、独立登录和错误处理。
- `references/response-guidelines.md`：实际展示、选择、确认、进度和失败表达。
- `examples/semantic-regression-cases.json`：修改 Skill 或执行回归时读取，不作为正常对话输入。
