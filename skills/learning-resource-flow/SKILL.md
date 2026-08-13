---
name: learning-resource-flow
description: 学习资源（图书、课程、视频、文章、教材、音频等）搜索与获取的唯一入口；用户找书、找课程、找视频、搜资料、下载或归档资源，或继续资源任务时，先按本技能流程用 education-resources 的 resource_* 工具执行。
---

# Learning Resource Flow

## 目标

帮助用户用自然语言获得真正符合当前目标和明确约束的教育/学习资源，并在用户明确选择和确认后获取或归档。

成功不等于“搜到很多链接”“Tool 调用成功”或“模型记住了状态”。成功意味着：候选经过必要审查，用户理解差异，选择和副作用可控，实际资源能正确获取，服务端事实可恢复。

## 分工

### Skill 负责语义与对话

- 理解 `goal`、`user_role`、`resource_target` 和显式 `constraints`；
- 判断是否需要澄清；
- 设计少量 `SearchDirection`，选择合适来源并执行有界检索；
- 必要时使用 OpenClaw leaf sub-agent 并行规划互补搜索方向，再由 Main Agent 统一汇总；
- 对候选做私有 `SemanticReview`；
- 决定是否 Selective Inspect；
- 生成私有 `Gap`，并在每轮作出唯一 `StopDecision`；
- 实际向用户展示候选，解释差异、限制、计划、进度和失败；
- 读取 MCP 当前事实完成恢复。

### `education-resources` MCP 负责服务端事实与副作用

MCP 是 Flow、ResultSet、Presentation、Selection、Resolution/Representation、Plan、Job/JobItem、Outcome、Asset/AssetBundle 和 Archive 的服务端来源。

模型不得伪造业务 ID、状态、Provider、下载结果、本地路径或归档结果。

获取层不再维护 Capability Descriptor → Readiness → Eligibility → digest 的持久状态链。Provider 能力由服务端轻量配置和当前运行时注册决定；Start 前重新核验 Representation 和 exact Provider route。

### 事实与语义边界

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> Resolution / Representation facts
MCP Plan / Job / Outcome / Asset -> acquisition facts
Skill reads facts + task context -> private SemanticReview -> private Gap -> StopDecision
```

`resource_search.coverage` 只说明服务端实际观察到的候选、来源、去重和失败事实，不代表任务已经语义满足。`SemanticReview`、Skill `Gap` 和 `StopDecision` 不写入公共 MCP 状态。

详细定义见 [`references/retrieval.md`](references/retrieval.md) 和 [`../../docs/RETRIEVAL_AUTHORITY.md`](../../docs/RETRIEVAL_AUTHORITY.md)。

## 封闭工具面

进入本 Skill 后，资源候选的搜索、核验、展示、选择、获取、归档和恢复只使用 `education-resources` 的 14 个业务 `resource_*` Tool。OpenClaw 通用能力不能成为第二条资源数据面：

- `read` 只允许在 `resource_flow_start` 前读取本 Skill 及其 reference；Flow 建立后不得再读工作区、运行时目录、Registry、合同、日志或 Tool spill 文件；
- 同一路径和 offset 的成功 `read` 不重复读取；只有明确截断时才使用新 offset 继续；
- 不调用 MCP protocol 的 `prompts_list` / `prompts_get` / `resources_list` / `resources_read` 旁路业务契约；
- 不得用 `web_search`、`web_fetch`、browser、`exec`、curl、其他 MCP 或直接 URL 请求来发现、补充、打开、核验或重排候选；
- MCP Search 为空、partial、失败或 Inspector 只能给出部分事实时，只能在当前 Flow 内 Replan、Clarify、StopWithGap 或按证据强度 Present；
- 通用工具调用成功不算本产品证据，失败也不能成为继续旁路的理由。

OpenClaw 的 `sessions_spawn` / `sessions_yield` / `subagents` 是唯一例外：它们可以用于**搜索语义规划编排**，但不能成为资源数据面。leaf child 只返回 SearchDirection、来源职责、query 和不确定性建议，不直接调用或伪造任何 `resource_*` 业务状态；详细边界见 [`references/multi-agent.md`](references/multi-agent.md)。

当前 native `search_tasks[].platform` 命名空间只有：

`generic`、`bilibili`、`douyin`、`zhihu`、`smartedu`、`ximalaya`、`cctv`、`yixi`、`kepu`、`baiduwenku`、`runoob`、`nlc`、`open163`、`annas-archive`、`weibo`、`wechat`。

不得猜测未注册 native ID。用户目标允许公开网页发现时，把来源名或 `site:` 放进 query 且 `platform=generic`；否则 StopWithGap。命名空间变化必须先同步机器 Registry、契约与本 Skill。

这是 Agent 行为约束，不是 OpenClaw 的硬权限沙箱；部署级强制隔离应由 Agent/tool policy 实现。

## 任务模型

内部只维护：

- `goal`：用户真正想完成的学习/资源目标；
- `user_role`：当前对话者，可 unknown；
- `resource_target`：资源实际给谁或用于什么，可 unknown；
- `constraints`：用户明确表达或有充分证据支持的 must / prefer / exclude。

`user_role` 与 `resource_target` 相互独立，不能互相推导。未知保持 unknown，不为了补齐字段追问。

需求理解与澄清见 [`references/conversation.md`](references/conversation.md)。

## 核心控制流

```text
Understand
  ┌─> Need reconstruction           # 还原用户真正要解决什么
  │   -> ambiguity found?
  │      ├─ yes -> Clarify -> user answers -> back to Need reconstruction
  │      └─ no  -> proceed
  └── (progressive: each answer updates understanding, may reveal new questions)
  -> resource_flow_start / flow_status
  -> Plan SearchDirection
       └─ optional leaf sub-agents    # 只规划，Main Agent 汇总
  -> resource_search / resource_browse_creator
  -> Evaluate MCP facts
  -> private SemanticReview
  -> Inspect?                         # 只检查会改变决策的高潜候选
  -> 结果是否真正匹配用户需求？       # 不只是"有没有结果"，而是"这些结果对用户有用吗"
  -> private Gap + one StopDecision
       ├─ Replan -> optional Gap worker -> resource_search mode=extend -> Evaluate
       ├─ Clarify -> ask one minimal question
       ├─ StopWithGap -> explain limitation
       └─ Present
  -> 实际向用户展示有序子集
  -> resource_presentation_save       # 与实际展示顺序完全一致
  -> 等待用户选择
  -> resource_selection_save
  -> 必要时确认当前 Resolution / Representation
  -> resource_download_prepare
  -> 向用户展示获取计划并等待明确确认
  -> resource_download_start
  -> resource_job_status / cancel
  -> optional resource_archive / resource_library_search
```

## 通用 Tool 调用不变量

- 对所有要求 `idempotency_key` 的逻辑操作：同一个请求因超时、响应丢失或连接问题重试时复用原 key；参数、目标、选择或动作语义变化时使用新 key。
- `idempotency_key` 只使用 16–128 位 ASCII 字母、数字或 `._:-`；不得把展示层缩写复制回 Tool 参数。
- Tool 返回 `ok=false`、结构化失败或结果不确定时，不假定状态已经成功转换；优先读取 `resource_flow_status` / `resource_job_status`。
- 业务 ID、版本、position、selection/plan digest、confirmation token、Provider、路径等只使用 MCP 实际返回值，不从聊天文本、标题、URL 或模型记忆重建。
- `selection_digest` / `plan_digest` 等绑定值由 MCP 从 Plan 记录内部查取，模型不需要携带或传递。
- 核心 `goal`、`resource_target` 或硬约束发生实质变化时建立新 Flow；只是换 SearchDirection、来源或查询角度时继续当前 Flow。
- 当前 `flow_id` 不确定时（上下文压缩、用户提及之前的任务、对话中存在多个并行 Flow），先调 `resource_flow_list` 发现现有 Flow，再用 `resource_flow_status` 恢复；不要猜 flow_id。
- 已产生网络/文件副作用的操作不因上下文压缩或模型不确定而自动重放；先恢复真实 Job/Flow 状态。

## 不允许跳步

- ResultSet 不是 Presentation；未实际展示的候选不能被选择。
- 不在实际展示前调用 `resource_presentation_save`。
- 不把 ResultSet 全量候选默认记成已展示。
- 不根据聊天文本猜 position、版本、Plan、Job 或当前状态。
- 不在用户明确确认当前获取计划之前调用 `resource_download_start`。
- 不把登录/认证失败转成 Generic Provider 或其他路线的静默成功。
- 不生成或补造 `authority_digest`、Readiness ID、Eligibility ID、binding digest；当前公共获取契约不需要这些字段。

## 自适应检索

检索不是一次查询。每轮执行：

```text
Plan -> Search -> Evaluate -> SemanticReview -> Inspect? -> Gap -> StopDecision
```

`SearchDirection` 描述要覆盖的目标/证据，不是 query、platform 或 resource type。首轮通常 1–2 个方向，只选少量直接相关来源；常规任务最多 3 轮，明确要求全面横向比较时最多 4 轮。

首轮 `resource_search` 使用 `replace`；只有 Replan 且有当前 `base_result_set_id` 时使用 `extend`。跨轮合并与去重由 MCP 创建新的不可变 ResultSet，Skill 不手工拼接候选。

一个 Flow 的首个成功 Search 只能是一次 `replace`；后续搜索必须是带当前 `base_result_set_id` 的 `extend`，不得用连续 `replace` 的近义查询覆盖前一轮事实。

### 可选多 Agent 搜索规划

多 Agent 只用于**复杂搜索的语义规划**，不改变 MCP 搜索执行和状态所有权。默认不 spawn；普通、窄、Main Agent 可以直接形成 1–2 个高质量 SearchDirection 的任务继续使用单 Agent。

只有存在至少两个相对独立、真正互补的语义方向，并且并行规划有实际收益时，第一版最多同时 spawn 2 个 leaf sub-agent。不要按平台拆 Agent，不为同义 query、平台数量或形式多样性使用多 Agent。

Main Agent 给 child 传递完成该方向所需的最小上下文，优先 isolated context；不能假定 child 自动拥有 `USER.md` / `MEMORY.md`。Child 只提出方向、来源职责、聚焦 query 和不确定性，不能执行 `resource_search` / Inspect / 下载 / 归档，也不能生成业务 ID 或可获取性事实。

Child 返回后 Main Agent 必须重新审查、去重和裁剪，再形成当前预算内的少量 `search_tasks[]`，由 Main Agent 对同一 Flow **一次或有序串行**提交 MCP。禁止多个 child 并发 Extend 同一个 Flow，也不为 child 建 Branch Flow 或跨 Flow merge。

如果本轮已经 spawn 所需 child 且 `sessions_yield` 可用，用它等待完成事件，不建立 session 轮询循环。Sub-agent 不可用、失败或建议低价值时，Main Agent 继续使用自身语义能力；这不改变资源后端，也不能解释为“没有资源”。

Replan 时只有当前 Gap 的搜索规划本身仍复杂才使用 1 个 Gap worker，并明确哪些方向已经满足、不得重做。简单 Gap 由 Main Agent 直接 Replan。

完整规则、任务模板和部署边界见 [`references/multi-agent.md`](references/multi-agent.md)。

### 轮次与容量

轮次上限是硬停止条件。常规任务最多 3 次成功 Search，全面比较最多 4 次；达到上限后必须 Present 或 StopWithGap，并在当前回复给用户结果。

若用户要求比较 N 个来源，而当前 ResultSet 已有至少 N 个语义可用候选，剩余关键 Gap 只有 inspection，则只做有预算的 Selective Inspect，不再扩写近义 query 或换 MCP 外工具。

`resource_search` 的 `limit` 控制每平台适配器的返回量（默认 20），不截断合并后的 ResultSet。各平台结果合并去重后全部进入 ResultSet，由 Presentation 层精选展示。

每个平台每轮通常只提交 1 条聚焦 query；确有两个不重叠范围时最多 2 条。

候选数量、标题命中、平台数量、`coverage.status` 或 SearchDirection 都不能单独触发 Present。只有当前事实和私有语义审查足以支持用户决策时才展示。

低相关、偏题或字典页结果只能描述为”当前结果相关性不足”。

### 公开/无需登录约束

用户明确要求“公开”“无需登录”或“可直接阅读”时，这是 must constraint。准备计入用户要求的 N 个来源前必须 Inspect；只有当前 Resolution/availability 证明 `available` 的候选才计数。

`AUTH_REQUIRED`、paywall、blocked 或 unresolved 候选可以作为 Gap/备选说明，但不能冒充公开来源、不能用于凑足 N 项，也不进入这组满足条件的 Presentation。

`technical_availability=unknown`、unresolved 或只有 landing available 必须原样描述为“尚未证实本体”。只有当前 Search/Inspect/session Tool 明确返回 `AUTH_REQUIRED` 或等价当前状态，才能断言“当前需要登录”。Registry 的 `auth_mode`、平台常识或模型记忆不能把 unknown 改写成登录墙。

完整规则见 [`references/retrieval.md`](references/retrieval.md)；来源选择见 [`references/source-routing.md`](references/source-routing.md)。

## Selective Inspect

只对会改变推荐、版本判断、约束判断或后续获取的少量高潜候选执行 `resource_inspect`。

`resource_inspect` 只使用当前 Flow 中已有的 `resource_id`。不要提交任意 URL、Cookie、Token 或本地路径。

Inspection 只产生/刷新 Resolution 和 Representation 事实，不自动把候选变成“推荐”或“可获取”。Inspect 后必须等待 MCP 结果，重新做 SemanticReview / Gap 判断。

每次成功 `extend` 都会生成新的 immutable ResultSet 和当前 public `resource_id` 绑定。extend 前的 Resolution 只能作为历史证据；若仍需使用该候选，找到当前 `resource_id` 后重新 Inspect。常规流程应先收敛 Search，再做最终 Selective Inspect。

详细规则见 [`references/inspection.md`](references/inspection.md)。

## 展示与选择

展示前完成必要候选审查。向用户说明真正有决策价值的差异，例如：

- 内容和目标为什么匹配；
- 来源和证据强度；
- search-only 还是 inspected；
- 资源本体、representation、landing page、metadata 的区别；
- 版本、格式、认证或获取限制。

完整、用户可见、带编号的候选列表必须已经输出后，才能调用 `resource_presentation_save`，并且保存完全相同的有序子集。

违反用户 must/exclude、`AUTH_REQUIRED`、blocked、unresolved 或只有未证实本体的项，只能在候选列表外作为 Gap/受限事实解释，不进入要求被满足的 Presentation。

用户只能选择当前 Presentation 中的项。不要替用户选择，不因为“明显更好”就直接进入获取。

`resource_presentation_save` 只记录实际展示，不是下载、保存本地文件或归档。用户说“先不要下载/保存/归档”时，仍可保存 Presentation。

## 获取与确认

获取链保持简单：

```text
Selection
  -> Resolution / Representation
  -> AcquisitionPlan
  -> 用户明确确认
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / AssetBundle
```

必须区分 `primary_resource`、`representation`、`landing_page`、`metadata`；不能把网页落地页/书目元数据说成视频、图书正文或其他 primary resource 已成功获取。

网页本身如果就是文章/教程/图文正文，可以作为 `primary_resource` 通过 `web_materialize` 获取；只有导航、预览、详情、跳转入口才是 landing page。

`resource_download_prepare` 成功后，只解释当前 Plan 实际返回的 scope、预期形式、限制、风险和有效期。用户明确确认当前 Plan 后才能调用 `resource_download_start`。

Start 由服务端重新核验 Selection、Plan、当前 Resolution/Representation 和 exact Provider route。若 Representation 漂移、Plan 过期或 Provider 不再可用，重新 Inspect/Prepare/Confirm；不要补造旧 Capability/Readiness/Eligibility 状态。

Provider 失败时保留真实失败，不静默改用 Generic/其他 Provider、strategy 或 scope。需要换路线时重新 Prepare 并重新确认。

完整规则见 [`references/acquisition.md`](references/acquisition.md)。

## 认证

登录不属于本 Skill 或 `education-resources` 的公共控制面。只有当前 Tool 明确返回 `AUTH_REQUIRED` 时，才暂停当前路径并交给独立 session-manager。

默认使用受控浏览器。用户主动提供合法 Cookie/Token、明确指定受支持平台、用途并授权保存时，可由 session-manager 执行一次 canonical direct import。

会话准备好后重新执行当前业务所需的 Search/Inspect，并生成新的 Plan；不恢复旧 Readiness/Eligibility 或旧确认。

不要索取或代填账号、密码、验证码、短信码或 MFA。Cookie/Token 原值不得进入本 Skill、`education-resources` Tool、其他 Tool、日志、计划或仓库；唯一例外是明确授权后的一次 `resource_session_save.session_data` 输入，且不得回显、失败后自动重放或与同一次 browser capture 混用。

## Job、恢复与取消

Job 是异步资源。使用 `resource_job_status` 查询，用户要求取消时使用 `resource_job_cancel`。

不要把 queued/running 描述为全部完成。Bundle 可以 partial，但 partial 不等于新的 Job 状态。

中断、上下文压缩或 MCP/OpenClaw 重启后优先读取 `resource_flow_status` / `resource_job_status`；不要从聊天记录猜状态，也不要自动重放已确认的网络副作用。

## 归档与资料库

只归档 MCP 返回的 ready `asset_id`。AssetBundle 是同一 Resource 的多资产关系，不等于 ZIP 或文件夹。

资源语义类型（book/video/article/course）与资产格式（PDF/EPUB/MP4/HTML）分层处理。分类、Bundle、去重和 Library 规则见 [`references/library.md`](references/library.md)。

文件 `sha256` / `byte_size` 是 Asset 元数据和可能的去重信息，不是 Agent 用来判断获取“可信”的额外门禁，也不要求用户确认这些值。

## Reference 导航

| 问题 | 阅读 |
| --- | --- |
| 如何理解需求、什么时候澄清、如何回复用户 | [`conversation.md`](references/conversation.md) |
| 如何搜索、审查候选、判断 Gap 和停止 | [`retrieval.md`](references/retrieval.md) |
| 复杂搜索何时并行规划、如何委派和汇总 sub-agent | [`multi-agent.md`](references/multi-agent.md) |
| 去哪些平台/来源、如何避免全平台乱搜 | [`source-routing.md`](references/source-routing.md) |
| 什么时候 Inspect、Inspect 后如何处理 | [`inspection.md`](references/inspection.md) |
| 用户选择后如何获取、解释 scope/provider/outcome | [`acquisition.md`](references/acquisition.md) |
| Asset/Bundle、归档、分类和资料库 | [`library.md`](references/library.md) |

旧版细分 reference 仅保留兼容跳转，不作为新的规则来源。

## 面向用户的最终原则

用户看到的是资源、差异、限制和下一步，不是内部架构。只有在开发/调试语境才解释 Agent、Skill、MCP 和业务 ID。

对不确定、未核验、需认证、策略阻断、Provider 不可用和失败保持准确；不要用乐观措辞掩盖证据不足，也不要为了“安全感”给服务端自己的状态重新增加多层摘要或防伪流程。
