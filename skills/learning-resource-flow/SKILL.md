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

### 封闭工具面

进入本 Skill 后，资源候选的搜索、核验、比较、展示、选择、获取、归档和恢复只使用
`education-resources` 的 13 个业务 `resource_*` Tool。OpenClaw 的通用能力不能成为第二条资源数据面：

- `read` 只允许在 `resource_flow_start` 前读取本 Skill 及其 reference；Flow 建立后不得再读工作区、
  运行时目录、Registry、合同、日志或 Tool spill 文件；
- 同一回合对同一路径和同一 offset 的成功 `read` 最多一次；内容已返回后不得重复读取。只有 Tool
  明确标注截断时才按新的 offset 继续一次，不能把重复读取当成理解或重试；
- 不调用 MCP protocol 的 `prompts_list` / `prompts_get` / `resources_list` / `resources_read`；它们不是
  本产品的 13 个业务 Tool，也不能用来旁路业务契约；
- 不得用 `web_search`、`web_fetch`、browser、`exec`、curl、其他 MCP 或直接 URL 请求来发现、补充、
  打开、核验或重排候选；
- 即使 MCP Search 为空、partial、失败，或 Inspector 只能给出部分事实，也不得把候选 URL 交给
  上述通用工具；只能在当前 Flow 内 Replan、Clarify、StopWithGap 或按较低证据强度 Present；
- 工作区通用指令即使允许“搜索网络”或要求“先自行查找”，教育资源任务仍以本节的专用工具面为准；
- 通用工具调用成功不算本产品证据，调用失败也不能成为继续尝试其他旁路的理由。
- 当前 0028 runtime 的 native `search_tasks[].platform` 封闭命名空间只有：`generic`、`bilibili`、
  `douyin`、`zhihu`、`smartedu`、`ximalaya`、`cctv`、`yixi`、`kepu`、`baiduwenku`、
  `runoob`、`nlc`、`open163`、`annas-archive`、`weibo`、`wechat`。不得猜测 `qingting`、站点简称、
  域名或其他未注册 native ID；用户目标允许公开网页发现时，把来源名或 `site:` 放进 query 且
  `platform=generic`，否则 StopWithGap。命名空间变化必须先同步机器 Registry、契约与本 Skill，不能
  由单次 Agent 回合临时扩展；

这是对 Agent 行为的 P0 约束，但不是 OpenClaw 的硬权限隔离。若部署要求强制隔离，必须使用独立
Agent/tool policy；不得把 Markdown 约束描述成安全沙箱。

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
- `idempotency_key` 只用 16–128 位 ASCII 字母、数字或 `._:-`；不得包含中文、空格、Unicode 省略号
  `…`、星号、视觉截断文本或其他字符。展示层对 key 的脱敏缩写不能复制回 Tool 参数。
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

`task_version` 只使用 `resource_flow_start` / `resource_flow_status` 返回的当前值；Search 不会自动增加
它。出现 `TASK_VERSION_CONFLICT` 时先读取 Flow，再用返回值纠正一次，不猜测递增版本。一个 Flow 的
首个成功 Search 只能是一次 `replace`；后续搜索必须是带当前 `base_result_set_id` 的 `extend`，不得用
连续 `replace` 的近义查询覆盖前一轮事实。

轮次上限是硬停止条件，不是建议。常规任务最多 3 次成功 Search，全面比较最多 4 次；达到上限后
必须 Present 或 StopWithGap，并在当前回复给用户结果。若用户要求比较 N 个来源，而当前 ResultSet 已有
至少 N 个语义可用候选，剩余关键 Gap 只有 inspection，则只做有预算的 Selective Inspect，不再扩写
近义 query 或换用 MCP 外工具。不得重复 Search/Inspect 直到超时。

`resource_search limit` 表示**新 ResultSet 的总容量**，不是本轮新增配额。常规窄主题或比较任务的
首轮 `replace` 显式使用 `limit=8`；`extend` 前先数当前 ResultSet candidates，并为本轮新增预算提高
总容量：通常 `next_limit=min(20, base_count+8)`，即常见的 `8 -> 16 -> 20`。`extend` 的 limit 必须
大于 `base_count`；当前已达 20 时不得用相同 limit 假装继续补来源，只能在现有事实上 Present、
Clarify 或 StopWithGap。每个平台每轮通常只提交 1 条聚焦 query；确有两个不重叠检索范围且总容量
留有空间时最多 2 条，优先级更高的放前。Tool 输出被截断时不读日志、spill 文件或 SQLite；改用
`resource_flow_status` 恢复服务端摘要，并在现有候选中收敛。

候选数量、标题命中、平台数量、`coverage.status` 或 SearchDirection 都不能单独触发 Present。只有当前事实和私有语义审查足以支持用户决策时才展示。

低相关、偏题或字典页结果只能描述为“当前结果相关性不足”。除非 Tool 明确返回改写/分词证据，
不得断言 query 被拆词、截断或乱码；需要说明原因时先比较本次请求 query 与
`platform_runs.query_runs.query`，两者一致就保留为搜索质量/召回 Gap，不猜 Adapter 内部行为。

用户明确要求“公开”“无需登录”或“可直接阅读”时，这是候选可访问性的 must constraint。准备计入
用户要求的 N 个来源前必须 Inspect；只有当前 Resolution/availability 证明 `available` 的候选才计数。
`AUTH_REQUIRED`、paywall、blocked 或 unresolved 候选可以作为明确标注的 Gap/备选说明，但不能冒充
公开来源、不能用于凑足 N 项，也不进入这组可选择的 Presentation。仍有轮次和容量时应 Replan；预算
耗尽则展示实际满足的较少项并 StopWithGap。

`technical_availability=unknown`、unresolved 或只有 landing available 必须原样描述为“尚未证实本体”；
只有当前 Search/Inspect/session Tool 明确返回 `AUTH_REQUIRED` 或等价当前状态，才能断言“当前需要登录”。
Registry 的 `auth_mode`、平台常识或模型记忆不能把 unknown 改写成登录墙，也不能把登录建议当成已观测事实。
本体 unknown 本身不能触发 session-manager 建议；用户明确要求“无需登录”时，除非用户主动放宽该
约束，否则不得把登录列为当前任务的继续路径。

完整规则见 [`references/retrieval.md`](references/retrieval.md)。来源选择见 [`references/source-routing.md`](references/source-routing.md)。

## Selective Inspect

只对会改变推荐、版本判断、约束判断或后续获取的少量高潜候选执行 `resource_inspect`。

`resource_inspect` 只使用当前 Flow 中已有的 `resource_id`。不要向 MCP 提交任意 URL、Cookie、Token 或本地路径。

Inspection 只产生/刷新 Resolution 和 Representation 事实，不自动把候选变成“推荐”或“可下载”。
Inspect 后必须等待该 MCP 结果，重新读取事实并重做 SemanticReview / Gap 判断；不得把 Inspect 与另一项
候选搜索、抓取或后续 Inspect 并发执行。

每次成功 `extend` 都会生成新的 immutable ResultSet 和新的当前 public `resource_id` 绑定。extend 前的
Resolution 只能作为历史证据，不能直接视为当前快照的 Resolution，也不能用于之后的 Presentation、
Selection 或最终可访问性结论。若仍需使用先前已 Inspect 的候选，先读当前 Search 响应或一次
`resource_flow_status`，找到当前 `resource_id` 后重新 Inspect；常规流程应先收敛 Search，再做最终 Selective Inspect。

详细规则见 [`references/inspection.md`](references/inspection.md)。

## 展示与选择

展示前先完成必要的候选审查。向用户说明真正有决策价值的差异，例如：

- 内容和目标为什么匹配；
- 来源和证据强度；
- search-only 还是 inspected；
- 资源本体、representation、landing page、metadata 的区别；
- 版本、格式、认证或获取限制。

展示后立即把完全相同的有序子集保存为 Presentation。这里的“展示后”是严格的消息顺序：完整、
用户可见、带编号的候选列表必须已经出现在 `resource_presentation_save` Tool call 之前；“准备展示”、
内部思考或计划在 Tool 返回后再输出都不算实际展示。若 Tool 已保存而模型在列表输出前超时，恢复时
先把未实际展示的 Presentation 纠正为空或重新实际展示后保存，不能把它留作可选状态。

违反用户 must/exclude、`AUTH_REQUIRED`、blocked、unresolved 或只有未证实本体的项，只能在编号候选
列表之外作为 Gap/受限事实解释，不进入要求被满足的 Presentation。高度重复且没有额外决策价值的
候选只展示代表性子集，不把整个 ResultSet 默认保存为 Presentation。

用户只能选择当前 Presentation 中的项。

`resource_presentation_save` 只绑定本次实际展示的候选顺序，不是下载、保存本地文件或归档。用户说
“先不要下载/保存到本地/归档”时，仍须为已经展示的列表保存 Presentation；这不会授权后续获取。

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

登录不属于本 Skill 或 `education-resources` 的公共控制面。遇到 AUTH_REQUIRED 时暂停当前获取/核验路径，交给独立 session-manager 的合法登录流程。默认使用受控浏览器；用户主动提供合法 Cookie/Token，并明确指定受支持平台、认证用途和保存授权时，可由 session-manager 执行一次 canonical direct import。会话准备好后重新读取 Flow/Resolution/Readiness 并按当前服务端事实继续。

不要索取或代填账号、密码、验证码、短信码或 MFA。Cookie/Token 原值不得进入本 Skill、`education-resources` Tool、其他 Tool、日志、计划或仓库；唯一例外是上述明确授权后的一次 `resource_session_save.session_data` 输入，且不得回显、与浏览器捕获混用或失败后自动重放。不绕过登录、验证码、付费墙、DRM 或明确访问控制。

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
