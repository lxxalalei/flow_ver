# 0040 — 搜索语义子 Agent 编排

- 状态：completed
- 创建日期：2026-08-12
- 完成日期：2026-08-12
- 范围：`skills/learning-resource-flow/` 与 OpenClaw 部署说明

## Objective

在不修改 `education-resources` MCP 状态模型和搜索接口的前提下，让 `learning-resource-flow` 在复杂、可并行拆解的检索任务中使用 OpenClaw 原生 sub-agent 并行规划互补 SearchDirection / 来源 / query，并由主 Agent 汇总后统一调用现有 `resource_search`。

## Non-goals

- 不让子 Agent 直接拥有或修改 Flow、ResultSet、Presentation、Selection、Resolution、Plan、Job、Asset 或 Archive。
- 不新增 MCP Tool、Agent 状态表、ResultSet merge、Branch Flow 或第二套搜索权威。
- 不把所有搜索默认改成多 Agent；普通窄任务继续单 Agent。
- 不启用嵌套 sub-agent；第一版保持 `maxSpawnDepth=1`。
- 不修改下载、Inspect、归档业务实现。

## Business invariants

- `education-resources` MCP 仍是全部资源业务事实与副作用的唯一服务端来源。
- 一个 Flow 的 Search/Extend 状态转换仍由主 Agent 串行提交。
- 子 Agent 输出只是临时建议/evidence，不是用户事实、业务状态或 MCP 结果。
- 用户背景由主 Agent按最小必要原则显式传入子任务；不能假定子 Agent自动继承 `USER.md` / `MEMORY.md`。
- 下载仍需 `prepare -> 用户明确确认 -> start`。

## Current architecture

- Relevant components: `skills/learning-resource-flow/SKILL.md`、其 references、`education-resources.resource_search(search_tasks[])`。
- Sources of truth: MCP 对资源业务状态负责；Skill 对私有 SemanticReview / Gap / StopDecision 负责。
- Upstream: OpenClaw 原生 `sessions_spawn` / `sessions_yield` sub-agent 机制。
- Downstream: 现有 `resource_search` 一次接收多个 SearchTask，并产生单一 immutable ResultSet。
- Known constraint: leaf sub-agent 默认不继承完整用户/记忆 bootstrap，上下文需由主 Agent最小化传递。

## Expected change surface

实际修改：
- `skills/learning-resource-flow/SKILL.md`
- `skills/learning-resource-flow/references/multi-agent.md`
- `skills/learning-resource-flow/examples/semantic-regression-cases.json`
- `TOOLS.md`

确认未修改：
- `mcp/education-resources/`
- 公共 MCP 契约和数据库
- 下载/Inspect/归档实现

## Acceptance criteria

- AC-01：普通、窄、1–2 个 SearchDirection 已足够的任务明确不 spawn。completed
- AC-02：只有存在 2 个以上相对独立且并行规划有实际收益的语义方向时，第一版最多 spawn 2 个 leaf sub-agent。completed
- AC-03：子 Agent只返回 SearchDirection / source role / query 等建议，不调用或伪造 `resource_*` 业务状态。completed
- AC-04：主 Agent过滤重复/冲突建议后，只提交少量互补 `search_tasks[]` 给现有 MCP；一个 Flow 内 Search/Extend 串行。completed
- AC-05：Gap 驱动的后续委派只针对当前缺口，不重跑已满足方向。completed
- AC-06：给出 OpenClaw 当前官方所需的 `sessions_spawn` / `sessions_yield` / `subagents` 工具配置与 `/tools` 验证说明，但不擅自覆盖用户 live config。completed
- AC-07：语义回归案例覆盖单 Agent、复杂任务多 Agent、多 Agent 输出去重、Gap worker、禁止子 Agent直接改 Flow。completed

## Complexity exceptions

无。新增的 `multi-agent.md` 只是 Skill 行为 reference，不是新运行时抽象或 source of truth。

## 步骤

- [x] completed：核对 OpenClaw 当前官方 sub-agent 行为、上下文和工具策略。
- [x] completed：实现 Skill 多 Agent 启用、委派、汇总与 Gap 规则。
- [x] completed：补部署/工具策略说明与语义回归案例。
- [x] completed：执行定向静态检查、检查 diff 和架构边界。
- [x] completed：完成计划并进入归档流程。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no runtime abstraction
New source of truth introduced?: no
Fallback added?: no resource fallback; only optional orchestration unavailable -> existing single-agent semantic planning
Data truncation added?: no
Unrelated files changed?: no
Actual user flow affected?: only complex search semantic orchestration
Actual user flow validated?: no; Windows OpenClaw live validation remains user-owned
Scope drift detected?: no
```

## Decision log

### Decision 001 — Agent 并行规划，MCP 串行执行

- Context: `resource_search` 已支持多个 `search_tasks[]`，而同 Flow 的 `extend` 依赖 current ResultSet。
- Options considered: 子 Agent各自建 Flow；多个子 Agent并发修改同一 Flow；子 Agent只规划后由主 Agent统一 Search。
- Chosen option: 第三种。
- Why: 不新增 merge/branch 状态，避免 ResultSet 并发冲突，保持 MCP 单一权威。
- Complexity introduced: 一份 Skill reference 与少量编排规则。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| OpenClaw 官方文档核对 | passed | 当前 `sessions_spawn`、`sessions_yield`、isolated context、tool policy 与 depth 规则有官方依据 | 用户 live config 已启用这些工具 |
| GitHub remote content checks | passed | 新 reference、Skill 主规则、TOOLS 运行说明和新增回归案例已写入远端分支 | 模型实际运行时一定遵守 |
| compare base `29663d...` -> branch | passed | 改动面只包含计划、Skill/TOOLS/回归文档，没有修改 MCP | OpenClaw live spawn 成功 |
| JSON parser | not executed | — | 当前执行容器无法解析 `github.com` DNS，无法 clone 远端后运行 `python -m json.tool`；已用 GitHub connector 分段回读完整开头/新增段/文件结尾 |
| real Windows OpenClaw flow | not executed / user-owned | — | `sessions_spawn`、announce、`sessions_yield` 在用户当前 Gateway/tool policy 下的真实行为 |

## 结果

第一版多 Agent 搜索规划已经落盘：普通搜索保持单 Agent；复杂搜索最多两个 leaf child；child 不触碰资源业务 Tool；Main Agent 汇总后使用现有 `resource_search(search_tasks[])`；Gap 只在规划复杂时使用一个定向 worker。MCP、数据库、下载、Inspect 和归档链保持不变。

部署后只需在真实 OpenClaw Main Agent 会话用 `/tools` 确认 `sessions_spawn` / `sessions_yield` / `subagents` 可用，再用一个复杂搜索请求做用户级验收。
