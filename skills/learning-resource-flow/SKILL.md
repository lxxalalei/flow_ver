---
name: learning-resource-flow
description: 教育与学习资源的唯一对话入口。用户想寻找、推荐、比较、筛选、获取、归档或再次查找课程、视频、图书、文章、练习、教材、音频等资源时使用；也用于从模糊需求出发进行必要澄清、自适应检索、候选核验、展示、选择、确认、恢复和任务查询。通过 education-resources MCP 管理服务端权威状态，平台登录交给独立 session-manager。
---

# Learning Resource Flow

## 目标

帮助用户用自然语言获得真正符合当前目标和明确约束的教育/学习资源，并在用户明确选择和确认后安全获取或归档。

成功不等于“搜到很多链接”“Tool 调用成功”或“模型记住了状态”。成功意味着：候选经过必要审查，用户理解差异，选择和副作用可控，服务端事实可恢复。

## 分工

### Skill 负责语义与对话

- 理解 `goal`、`user_role`、`resource_target` 和显式 `constraints`；
- 判断是否需要澄清；
- 设计少量 `SearchDirection`，选择合适来源并执行有界检索；
- 对候选做私有 `SemanticReview`；
- 决定是否 Selective Inspect；
- 生成私有 `Gap`，并在每轮作出唯一 `StopDecision`；
- 实际向用户展示候选，解释差异、限制、计划、进度和失败；
- 读取 MCP 权威事实完成恢复。

### `education-resources` MCP 负责服务端事实与副作用

MCP 是 Flow、ResultSet、Presentation、Selection、Resolution/Representation、Capability/Readiness/Eligibility、Plan、Job Execution、Outcome、Asset/AssetBundle 和 Archive 的权威来源。

模型不得伪造业务 ID、状态、Provider、下载结果、本地路径或归档结果。

### 权威边界

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect / Resolution / Readiness / Eligibility / Job / Outcome / Asset -> independent facts
Skill reads facts + task context -> private SemanticReview -> private Gap -> StopDecision
```

`resource_search.coverage` 只说明服务端实际观察到的候选、来源、去重和失败事实，不代表任务已经语义满足。`SemanticReview`、Skill `Gap` 和 `StopDecision` 不写入公共 MCP 状态。

详细定义见 [`references/retrieval.md`](references/retrieval.md) 和 [`../../docs/RETRIEVAL_AUTHORITY.md`](../../docs/RETRIEVAL_AUTHORITY.md)。

## 任务模型

内部只维护：

- `goal`：用户真正想完成的学习/资源目标；
- `user_role`：当前对话者，可 unknown；
- `resource_target`：资源实际给谁或用于什么，可 unknown；
- `constraints`：用户明确表达或有充分证据支持的 must / prefer / exclude。

`user_role` 与 `resource_target` 相互独立，不能互相推导。未知保持 unknown，不为了补齐字段追问。

需求理解与澄清规则见 [`references/conversation.md`](references/conversation.md)。

## 核心控制流

正常任务使用同一条主链：

```text
Understand
  -> Clarify?                         # 仅缺失事实会改变结果时
  -> resource_flow_start / flow_status
  -> Plan SearchDirection
  -> resource_search / resource_browse_creator
  -> Evaluate MCP facts
  -> private SemanticReview
  -> Inspect?                         # 只检查会改变决策的高潜候选
  -> private Gap + one StopDecision
       ├─ Replan -> resource_search mode=extend -> Evaluate
       ├─ Clarify -> ask one minimal question
       ├─ StopWithGap -> explain limitation
       └─ Present
  -> 实际向用户展示有序子集
  -> resource_presentation_save       # 必须与实际展示顺序完全一致
  -> 等待用户选择
  -> resource_selection_save
  -> resource_download_prepare
  -> 向用户展示获取计划并等待明确确认
  -> resource_download_start
  -> resource_job_status / cancel
  -> optional resource_archive / resource_library_search
```

### 通用 Tool 调用不变量

- 对所有要求 `idempotency_key` 的逻辑操作：同一个请求因超时、响应丢失或连接问题重试时复用原 key；参数、目标、选择或动作语义发生变化时使用新 key。
- Tool 返回 `ok=false`、结构化失败或响应结果不确定时，不假定状态已经成功转换；优先读取 `resource_flow_status` / `resource_job_status` 等权威事实后再决定下一步。
- 业务 ID、版本、position、digest、confirmation token、Provider、路径等只使用 MCP 实际返回值，不从聊天文本、标题、URL 或模型记忆重建。
- 核心 `goal`、`resource_target` 或会改变任务语义的硬约束发生实质变化时建立新 Flow；同一核心任务下只是换 SearchDirection、来源或查询角度时继续当前 Flow。
- 已经产生网络/文件副作用的操作不因上下文压缩或模型不确定而自动重放；先恢复真实 Job/Flow 状态。

### 不允许跳步

- ResultSet 不是 Presentation；未实际展示的候选不能被选择。
- 不在实际展示前调用 `resource_presentation_save`。
- 不把 ResultSet 全量候选默认记成已展示。
- 不根据聊天文本猜 position、版本、Plan、Job 或当前状态。
- 不在用户明确确认当前获取计划之前调用 `resource_download_start`。
- 不把登录/认证失败转成 Generic Provider 或其他路线的静默成功。

## 自适应检索

检索不是一次查询。每轮执行：

```text
Plan -> Search -> Evaluate -> SemanticReview -> Inspect? -> Gap -> StopDecision
```

`SearchDirection` 描述要覆盖的目标/证据，不是 query、platform 或 resource type。首轮通常 1–2 个方向，只选少量直接相关来源；常规任务最多 3 轮，明确要求全面横向比较时最多 4 轮。

首轮 `resource_search` 使用 `replace`；只有 Replan 且有当前 `base_result_set_id` 时使用 `extend`。跨轮合并与去重由 MCP 创建新的不可变 ResultSet，Skill 不手工拼接候选。

候选数量、标题命中、平台数量、`coverage.status` 或 SearchDirection 都不能单独触发 Present。只有当前事实和私有语义审查足以支持用户决策时才展示。

完整规则见 [`references/retrieval.md`](references/retrieval.md)。来源选择见 [`references/source-routing.md`](references/source-routing.md)。

## Selective Inspect

只对会改变推荐、版本判断、约束判断或后续获取的少量高潜候选执行 `resource_inspect`。

`resource_inspect` 只使用当前 Flow 中已有的 `resource_id`。不要向 MCP 提交任意 URL、Cookie、Token 或本地路径。

Inspection 只产生/刷新 Resolution 和 Representation 事实，不自动把候选变成“推荐”或“可下载”。Inspect 后必须重新读取事实并重做 SemanticReview / Gap 判断。

详细规则见 [`references/inspection.md`](references/inspection.md)。

## 展示与选择

展示前先完成必要的候选审查。向用户说明真正有决策价值的差异，例如：

- 内容和目标为什么匹配；
- 来源和证据强度；
- search-only 还是 inspected；
- 资源本体、representation、landing page、metadata 的区别；
- 版本、格式、认证或获取限制。

展示后立即把完全相同的有序子集保存为 Presentation。用户只能选择当前 Presentation 中的项。

不要替用户选择，不因为“明显更好”就直接进入下载。

## 获取与确认

获取执行必须沿服务端权威链：

```text
Capability Descriptor
  -> Deployment Readiness
  -> Resolution / Representation
  -> Eligibility
  -> PlanItem + authority_digest
  -> fresh ExecutionItem
  -> exact Provider
  -> Actual Outcome
  -> Asset / AssetBundle
```

Platform Registry、平台名、资源类型、文件扩展名或旧 options 都不能单独证明当前可获取。

必须区分 `primary_resource`、`representation`、`landing_page`、`metadata`；不能把网页落地页/书目元数据说成视频、图书正文或其他 primary resource 已成功获取。

`resource_download_prepare` 之后向用户解释当前计划和已知限制，获得明确确认后才能 `resource_download_start`。Provider 失败时保留真实失败，不静默改用 Generic/其他 Provider、strategy 或 scope。

完整规则见 [`references/acquisition.md`](references/acquisition.md)。

## 认证

登录不属于本 Skill 或 `education-resources` 的公共控制面。遇到 AUTH_REQUIRED 时暂停当前获取/核验路径，交给独立 session-manager 的合法登录流程；会话准备好后重新读取 Flow/Resolution/Readiness 并按当前服务端事实继续。

不要在 Skill、Tool JSON、日志或仓库中复制 Cookie、Token、Secret 或浏览器档案。不绕过登录、验证码、付费墙、DRM 或明确访问控制。

## Job、恢复与取消

Job 是异步资源。使用 `resource_job_status` 查询，用户要求取消时使用 `resource_job_cancel`。

不要把 queued/running/partial 描述为全部完成。中断、上下文压缩或 MCP/OpenClaw 重启后优先读取 `resource_flow_status` / `resource_job_status`；不要从聊天记录猜状态，也不要自动重放已确认的网络副作用。

## 归档与资料库

只归档 MCP 已验证并返回稳定 `asset_id` 的 Asset。AssetBundle 是同一 Resource 的多资产关系，不等于 ZIP 或文件夹。

资源语义类型（book/video/article/course）与资产格式（PDF/EPUB/MP4/HTML）分层处理。分类、Bundle、去重和 Library 规则见 [`references/library.md`](references/library.md)。

## Reference 导航

| 问题 | 阅读 |
| --- | --- |
| 如何理解需求、什么时候澄清、如何回复用户 | [`conversation.md`](references/conversation.md) |
| 如何搜索、审查候选、判断 Gap 和停止 | [`retrieval.md`](references/retrieval.md) |
| 去哪些平台/来源、如何避免全平台乱搜 | [`source-routing.md`](references/source-routing.md) |
| 什么时候 Inspect、Inspect 后如何处理 | [`inspection.md`](references/inspection.md) |
| 用户选择后如何安全获取、解释 scope/provider/outcome | [`acquisition.md`](references/acquisition.md) |
| Asset/Bundle、归档、分类和资料库 | [`library.md`](references/library.md) |

旧版细分 reference 仅保留兼容跳转，不再作为新的规则来源。

## 面向用户的最终原则

用户看到的是资源、差异、限制和下一步，不是内部架构。只有在开发/调试语境才解释 Agent、Skill、MCP、业务 ID 和权威链。

对不确定、未核验、未就绪、需认证、策略阻断和失败保持准确；不要用乐观措辞掩盖证据不足。
