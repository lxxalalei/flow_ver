# 0074 — Skill 语义决策内核与真实 A/B

- 状态：in_progress
- 创建日期：2026-08-26
- 完成日期：未完成
- 范围：`skills/`、`.agent/plans/`、语义评测文档；MCP 公共能力面冻结
- 外部验证条件：当前执行环境只有 GitHub 仓库连接，无法直接运行本地 OpenClaw/Gateway；真实 old/new baseline 与 A/B 仍需在 Windows/OpenClaw 环境执行。

## Objective

在不修改 `education-resources` MCP 公共 Tool 面的前提下，提高 Main Agent 在学习资源任务中的需求理解、任务分类、搜索价值分解、来源派发、候选判断、Coverage/Gap 判断和停止质量，并用同模型、同 MCP、同输入的真实 OpenClaw A/B 验证新版 Skill。

## Non-goals

- 不新增或重构 MCP 公共 Tool；
- 不把语义判断重新下沉到 MCP/Adapter；
- 不创建 Flow、Plan、SemanticReview、CoverageState、Gap DTO 或其他持久语义状态；
- 不通过硬编码平台清单、固定搜索轮数、固定候选数量替代模型判断；
- 不默认启用多 Agent；
- 不以“更服从 Skill 文本”或“工具调用更少”代替真实资源质量；
- 不把平台优势写成排他内容边界或固定 best-platform router。

## Business invariants

- Agent 负责用户目标、来源派发、候选价值、Gap、继续/停止和选择语义；MCP 只负责真实平台事实、IO 和必要 Job/Session 状态；
- Search / Expand / Inspect / Download 仍是可组合能力，不是固定流水线；
- 用户未授权下载时不得产生下载副作用；用户已明确下载且对象明确时不得制造形式确认；
- 完整枚举任务不得用聊天页大小代替数据完整性；普通研究任务也不得因为来源还有下一页就机械全量枚举；
- 技术失败只表示当前能力失败，不得推导成“资源不存在”；
- 来源生态知识是搜索先验，不是内容边界；
- 对当前 Coverage 有直接价值匹配的多个来源可以共同参与召回，不要求互斥职责；
- “理论上可能有”“平台已接入”“用户是学生”都不能单独成为派发理由；
- 未搜索的平台本身不是 Gap，Gap 必须来自当前结果暴露出的缺失价值；
- active Skill 不持有平台 API、Cookie、分页、签名、端点和 Adapter 机械事实。

## Current architecture

旧 Skill 基线 commit：

```text
3a20c1e14358631201e99fb54e007ccfcf118d94
```

0073 已完成并验证：

- 12 个 Tool 的 stdio/gateway probe 一致；
- release 回归为 `278 passed + 1 skipped + 56 subtests`；
- 5 个真实 `openclaw agent` 任务闭环；
- 真实平台测试进一步修复 Ximalaya、Zjer、SmartEdu、Import/resource type 等 correctness 问题。

因此本计划把 MCP 视为稳定实验底座：后续仅接受真实平台变化、correctness bug、明确缺失能力或有证据的性能问题，不再为了语义实验重构 MCP。

当前语义层：

```text
User
  ↓
Main Agent
  ↓
learning-resource-flow Skill
  ├─ Host Web Search
  └─ education-resources MCP
        ↓
      Adapters / Jobs / Files
```

当前 `SKILL.md` 已经包含 semantic-first 原则，但来源派发存在两个相反风险：

1. 过早 routing：把平台典型优势误当内容边界，一个价值只挑一个“最佳平台”，损失 recall；
2. 无脑 fan-out：只因为平台可能有相关内容就全平台搜索。

当前要收敛为：

```text
Coverage Need
  ↓
Direct Value Match
  ↓
Eligible Sources
  ↓
Reasoned Fan-out
  ↓
Real-result Competition
  ↓
Coverage / Gap / Stop
```

## Expected change surface

Likely to change:

- `skills/SKILL.md`；
- `skills/references/retrieval.md`、`conversation.md`、`source-routing.md` 中与主决策重复或冲突的部分；
- `skills/examples/semantic-evaluation.md`；
- `skills/examples/semantic-regression-cases.json`、`semantic-baseline-cases.json`；
- 本计划和必要的 active 文档索引。

Should not change:

- `mcp/education-resources/src/**`；
- MCP Tool name/schema；
- Adapter 平台实现；
- Job/Session 持久结构；
- Archive taxonomy。

## Target decision kernel

这不是状态机，也不落盘。Agent 在每一轮只需能回答：

```text
Task      用户现在是 Research / Locate / Browse / Enumerate / Acquire / Transform 哪类任务？
Goal      真正要完成什么；must / prefer / exclude 是什么？
Coverage  要完成目标，需要哪些不同学习价值或证据角色？
Sources   哪些来源对当前 Coverage 有直接价值匹配？
Evidence  当前候选分别证明了什么；哪些是真正有用、哪些仍不确定？
Gap       还缺什么具体价值或关键事实？
Next      下一步 Search/Inspect 能新增什么价值；如果说不出来就停止。
```

候选运行时不要求多维打分表，只需要能区分：

```text
Reject         明显不能解决当前目标
Hold           可能有用，但存在会改变决策的未知事实
Recommendable  已有足够证据说明为什么值得给用户看
```

`Hold` 才自然触发必要 Inspect；`Recommendable` 才进入 Coverage；`Reject` 不继续占用上下文。

### Source routing rule

来源优势不是排他路由：

```text
Source role = prior, not boundary
```

派发标准：

- 有直接、具体的价值匹配 → 可以参与召回；
- 多个来源对同一价值都匹配 → 可以共同搜索并由真实候选竞争；
- 只因为“可能有”或“平台已接入” → 不派发；
- 平台优势主要影响 query、候选预期和触发信号；
- 未搜索的平台不自动形成 Gap；
- 同一来源尽量合并相近 Coverage 的 query，减少重复搜索，而不是提前减少合理来源。

## Acceptance criteria

- [x] AC-01：冻结 MCP 公共能力面作为语义实验底座；0073 已提供真实运行证据。
- [x] AC-02：评测方法拆成 hard invariant / judgment benchmark / real retrieval 三层，不再把遵守某条 Skill 规则直接当作资源质量。
- [x] AC-03：建立不绑定固定平台路线的 baseline case suite，覆盖 Research / Locate / Browse / Enumerate / Acquire / Transform。
- [x] AC-04：保留 `3a20c1e` 作为 immutable old Skill baseline，并提供 worktree runner，使旧 baseline 可以在 current Skill 已修改后仍公平执行。
- [ ] AC-05：active Skill 收敛为 Task → Goal → Coverage → Sources → Evidence → Gap → Next 的即时 decision kernel，不新增后端状态模型。
- [x] AC-06：来源派发采用 Direct Value Match + Reasoned Fan-out；平台优势只作为 prior，不作为排他边界。
- [x] AC-07：平台触发信号与非触发信号明确；例如 SmartEdu 由教材/同步/课时信号触发，而不是“用户是学生”。
- [x] AC-08：一个合法 Gap 必须能推出一条实质不同、可解释的新路线；“还有平台没搜”“可能还有更好”不能单独驱动补搜。
- [x] AC-09：停止条件包含“下一轮是否仍有明确高信息增益”，不以候选数量或平台数量决定停止。
- [ ] AC-10：使用同模型、同 MCP、同输入做 old/new A/B；新版在多数真实 judgment/real retrieval case 上稳定更好，且 hard invariant 无回归。
- [ ] AC-11：最终真实 OpenClaw 用户链路验证通过；MCP schema 与实现没有因语义优化发生无关改动。

## Complexity exceptions

无。`Task/Goal/Coverage/Sources/Evidence/Gap/Next` 是模型当前轮的思考框架，不是代码 DTO、持久 source of truth 或工作流状态。

## 步骤

- [x] completed：确认 `3a20c1e` 的 MCP/OpenClaw 验收足以作为稳定语义实验底座。
- [x] completed：清理进入语义阶段前的文档边界漂移，建立 0074、三层评测方法和 baseline runner。
- [x] completed：修改 active Skill 的来源派发：Direct Value Match、Reasoned Fan-out、平台 trigger/non-trigger、未搜索平台不构成 Gap。
- [ ] pending：继续收敛 Task → Goal → Coverage → Sources → Evidence → Gap → Next 主 decision kernel，并压缩 references 重复规则。
- [ ] pending：在真实 OpenClaw 中分别运行 `3a20c1e` old worktree 与新版 Skill，记录 baseline/A-B。
- [ ] pending：根据真实 A/B 修正语义退化，不为测试结果修改正确业务目标。
- [ ] pending：真实用户链路最终验收；通过后归档 0074。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New backend abstraction introduced?: no
New persistent source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
MCP public surface changed?: no
Actual user flow affected?: yes, source dispatch semantics
Actual user flow validated?: not yet; real old/new OpenClaw A/B pending
Scope drift detected?: no
```

## Decision log

### Decision 001 — MCP public surface freeze

- Context: 0073 已完成真实 Tool/平台/OpenClaw 验收，当前主要不确定性从数据面转移到语义决策质量。
- Chosen: 0074 不以 Skill 优化为理由修改 MCP 公共面。
- Why: old/new Skill A/B 应保持同一工具底座。
- Complexity introduced: 无。

### Decision 002 — baseline commit immutable

- Context: 0046 已做过 semantic-first 重构，但当时没有真实 OpenClaw A/B。
- Chosen: 固定 `3a20c1e` 为 old Skill baseline，runner 支持指定独立 worktree。
- Why: 即使 current Skill 已继续修改，仍能在同一模型/MCP 下重放 old baseline。
- Complexity introduced: 仅测试 runner，不新增运行时架构。

### Decision 003 — 先改 source routing，再执行 old/new A/B

- Context: 用户明确指出当前强 routing 会漏掉同样有价值的平台，例如火山科普可能在 Bilibili、Douyin 都有优质内容；同时也指出 SmartEdu 不能仅因“学生/学习主题”就加入。
- Options considered:
  - 等 old baseline 跑完再改；
  - 直接全平台 fan-out；
  - 修改 routing，同时保留 immutable old commit 供后续 A/B。
- Chosen: 第三种。
- Why: 用户已明确改变实施顺序；old baseline 有独立 commit/worktree，可以后补而不污染对照组。
- Complexity introduced: 无新框架，仅修改 Skill 语义规则。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| MCP release baseline | inherited from 0073 | 数据面可作为稳定实验底座 | Skill 语义质量 |
| static Skill/evaluator audit | completed | 过早 routing 与无脑 fan-out 两类风险已识别 | 新版更好 |
| source-routing static alignment | completed | 主 Skill/reference/baseline case 已统一到 Direct Value Match + Reasoned Fan-out | 真实召回质量 |
| old/new OpenClaw A/B | pending | — | 新版语义收益 |

## 结果

尚未完成。当前已从“baseline-first 阻塞”切换为“immutable old baseline + current Skill 继续实施”；真实 old/new A/B 仍是最终语义验收门槛。