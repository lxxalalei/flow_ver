# Multi-Agent Search Planning

本文件只负责 `learning-resource-flow` 的 OpenClaw sub-agent 搜索语义编排。它不改变 `education-resources` MCP 的 Tool、Flow、ResultSet 或获取状态模型。

## 核心边界

多 Agent 是**语义规划优化**，不是第二条资源数据面。

```text
Main Agent
  -> optional leaf sub-agents: plan SearchDirection / source role / query
  -> Main Agent reviews + merges suggestions
  -> one ordered MCP Search/Extend mutation
  -> ResultSet
  -> Main Agent SemanticReview / Gap / StopDecision
```

保持以下所有权：

- Main Agent / Skill：用户目标理解、是否并行、最终 SearchDirection、预算、SemanticReview、Gap、StopDecision、Presentation 与用户交互；
- leaf sub-agent：只提供当前搜索规划建议；
- `education-resources` MCP：Flow、ResultSet、Presentation、Selection、Resolution/Representation、Plan、Job、Outcome、Asset、Archive 与真实搜索/Inspect/获取事实。

Sub-agent 输出不是业务状态、用户事实或工具证据。不得把 sub-agent 的自然语言结果写成 `resource_id`、ResultSet、Resolution、availability、Provider 或 Asset 事实。

## 什么时候启用

默认不 spawn。普通窄任务由 Main Agent 直接规划。

只有同时满足以下条件时才考虑第一版并行规划：

1. 当前请求已经足够 Ready，不需要先向用户澄清；
2. 存在至少两个**相对独立、真正互补**的 SearchDirection，分别规划有明显价值；
3. 这些方向不是平台拆分、近义 query 或形式凑数；
4. 并行规划能减少主 Agent 一次性展开过多来源/证据路线的负担；
5. 当前 OpenClaw session 实际提供 `sessions_spawn`；若不可用，直接使用现有单 Agent 规划，不把它视为资源搜索失败。

典型适合：

- 用户明确要求较全面的横向比较；
- 用户希望系统覆盖理解、观察、实践、巩固等多个独立学习价值；
- 复杂主题同时需要不同证据路线，例如专业原始资料与可视化过程材料；
- 当前 Gap 有两个彼此独立、都值得继续探索的缺口。

典型不适合：

- 一个方向就足够的窄主题；
- 首轮 1–2 个 SearchDirection 很容易由 Main Agent 直接形成；
- 只是想多搜几个平台；
- 只是同义词、标题写法或 query 改写；
- 当前真正问题是缺用户必需信息，应先 Clarify；
- 当前剩余 Gap 只有 Inspect、登录、版本核验或获取状态，不需要重新规划搜索。

不要为了“已经有多 Agent 能力”而默认使用它。

## 第一版并发预算

第一版最多同时 spawn **2 个 leaf sub-agent**。不启用嵌套编排，不让 child 再 spawn child。

一个 child 通常只负责一个语义方向；不要按平台建立 Bilibili Agent、Zhihu Agent、Generic Agent 等固定角色。

如果一个方向本身很简单，Main Agent 直接规划，不为了达到两个 child 而拆分。

Sub-agent token/上下文成本属于搜索预算的一部分。多 Agent 不提高 MCP 的成功 Search 轮次上限，也不放宽 ResultSet `limit`。

## 子任务上下文

优先使用 OpenClaw 默认 isolated sub-agent，并把本次真正需要的最小上下文写进 task。不要用 `context=fork` 代替清晰委派；只有当前任务高度依赖无法合理摘要的近期对话/工具证据时才考虑 fork。

任务描述按需包含：

- 当前资源目标/核心问题；
- 当前 `resource_target`；
- 与该对象明确对应、且确实会影响搜索的上层用户背景；
- 显式 must / prefer / exclude；
- child 负责的 SearchDirection 或当前 Gap；
- 已经覆盖的方向，避免重复；
- 输出边界：只给规划建议，不执行资源搜索、Inspect、下载或归档。

不要把整个 `USER.md`、`MEMORY.md`、完整家庭画像或不相关 transcript 复制给 child。

## 子 Agent 任务模板

可以用自然语言，不要求 JSON，不建立持久 Schema。一个合格任务可类似：

```text
你只负责为当前学习资源任务规划一个互补搜索方向，不执行任何资源 Tool。

当前目标：让小学阶段孩子系统了解火山。
当前对象：孩子自己使用。
显式约束：中文优先；用户未限定平台或载体。
你负责：过程观察方向。
已覆盖：火山形成与喷发原理。

请返回：
- 这个方向要解决的具体学习问题；
- 1 个主力来源及其独特贡献；
- 必要时 1 个补充来源；
- 每个来源最多 1 条聚焦 query；
- 主要不确定性。

不要调用 resource_*、web/browser/exec，不要生成 resource_id、ResultSet、可下载性或其他业务事实。
```

输出字段只是沟通提示，不是 contract。Main Agent 必须自行复核。

## 汇总规则

Child 完成后，Main Agent 不能直接拼接所有输出。必须重新做一次轻量规划审查：

1. 是否真的对应当前用户目标与对象；
2. 是否违反 must/exclude；
3. 两个方向是否语义互补，而不是同义或平台重复；
4. source 是否有独特贡献；
5. query 是否聚焦且没有模型虚构的版本/年龄/偏好；
6. 是否仍符合本轮 MCP 搜索预算。

重复方向合并；较弱或偏离方向直接丢弃。Child 建议不会自动升级成用户 preference/constraint。

最终仍由 Main Agent 形成少量 `search_tasks[]`，并**一次或有序串行**调用现有 `resource_search`。

## Flow 并发边界

禁止多个 child 对同一 Flow 并发执行 `resource_search mode=extend`。

当前 Flow 的 Search 状态是串行的：一次成功 Search/Extend 会产生新的 current immutable ResultSet；下一次 Extend 必须基于最新 `base_result_set_id`。因此：

- child 不直接调用 `resource_flow_start`、`resource_search`、`resource_inspect`、Presentation/Selection、download 或 archive；
- 不为每个 child 创建 Branch Flow；
- 不新增跨 Flow ResultSet merge；
- MCP mutation 始终由 Main Agent 基于当前 Flow 状态有序提交。

这不是临时限制，而是第一版的明确架构边界。

## 等待与完成

如果当前 OpenClaw 提供 `sessions_yield`，Main Agent 在已经 spawn 本轮所需 children 后使用它让完成事件自然返回；不要用 `sessions_list` / `sessions_history` 建轮询循环。

Child 超时、失败或只返回低价值建议时：

- 记录该规划输入未产生可用建议；
- 使用其他已返回建议和 Main Agent 自己的语义能力继续；
- 不因为 sub-agent 失败改走 web/browser/exec 或第二个资源后端；
- 不把规划失败解释成“网上没有资源”。

多 Agent 是可选语义优化；其不可用不会改变 MCP 的事实边界。

## Gap 驱动的二次委派

首轮 ResultSet 出来后，仍按正常 `SemanticReview -> Gap -> StopDecision`。

如果 `Replan` 的 Gap 很明确且规划本身复杂，可以只 spawn **1 个 Gap worker**，并明确告诉它：

- 当前具体缺什么；
- 哪些方向已经满足，不得重做；
- 需要规划的唯一缺口；
- 当前来源/query 已经尝试过什么。

例如首轮已经有足够视频和图文，但缺“可打印练习”，Gap worker 只规划练习/文档路线。不得重新 spawn 原理和视频 worker。

如果 Gap 很简单，Main Agent 直接 Replan，不使用 child。

## 与用户背景的关系

OpenClaw 上层用户背景仍由上层记忆负责。Main Agent只把当前 child 完成任务所需的可靠背景显式传入任务。

多孩子场景先由 Main Agent确定本次对象；child 不负责从家庭记忆猜当前 target，也不负责写回用户画像。

Sub-agent 的召回假设、资源形态建议和推断不能自动进入长期用户记忆。

## 部署要求

运行时 Main Agent 需要实际可用的 `sessions_spawn`；希望在同一 turn 等待结果时还需要 `sessions_yield`。`subagents` 仅用于按需查看/取消任务，不应拿来轮询等待。

OpenClaw 工具策略可能在 profile、agent、provider、channel/sender 或 sandbox 层移除这些工具。部署时从真实会话执行 `/tools` 确认有效工具面。

第一版推荐：

- `maxSpawnDepth=1`；
- 单个 Main Agent最多 2 个当前搜索规划 child；
- leaf child 不需要 `education-resources` MCP、session-manager、web/browser/exec 等资源数据或副作用工具；能在部署 tool policy 中收窄时应收窄。

如果 live config 已有显式 `tools.allow`，不要同时新增同层 `tools.alsoAllow`；应把需要的 session tool 合入既有 allow。具体配置以当前 OpenClaw live schema 为准，不由本 Skill 写入或猜测用户配置。
