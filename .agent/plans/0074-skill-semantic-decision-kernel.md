# 0074 — Skill 语义决策内核与真实 A/B

- 状态：blocked
- 创建日期：2026-08-26
- 完成日期：未完成
- 范围：`skills/`、`.agent/plans/`、语义评测文档；MCP 公共能力面冻结
- 阻塞：当前执行环境只有 GitHub 仓库连接，无法直接运行本地 OpenClaw/Gateway。必须先在真实 OpenClaw 中记录当前 `SKILL.md` baseline，之后才能修改 active Skill 并做公平 A/B。

## Objective

在不修改 `education-resources` MCP 公共 Tool 面的前提下，提高 Main Agent 在学习资源任务中的需求理解、任务分类、搜索价值分解、候选判断、Coverage/Gap 判断和停止质量，并用同模型、同 MCP、同输入的真实 OpenClaw A/B 证明新版 Skill 比当前 baseline 更稳定。

## Non-goals

- 不新增或重构 MCP 公共 Tool；
- 不把语义判断重新下沉到 MCP/Adapter；
- 不创建 Flow、Plan、SemanticReview、CoverageState、Gap DTO 或其他持久语义状态；
- 不通过硬编码平台清单、固定搜索轮数、固定候选数量替代模型判断；
- 不默认启用多 Agent；
- 不以“更服从 Skill 文本”或“工具调用更少”代替真实资源质量；
- baseline 未记录前不改 active `skills/SKILL.md`。

## Business invariants

- Agent 负责用户目标、来源职责、候选价值、Gap、继续/停止和选择语义；MCP 只负责真实平台事实、IO 和必要 Job/Session 状态；
- Search / Expand / Inspect / Download 仍是可组合能力，不是固定流水线；
- 用户未授权下载时不得产生下载副作用；用户已明确下载且对象明确时不得制造形式确认；
- 完整枚举任务不得用聊天页大小代替数据完整性；普通研究任务也不得因为来源还有下一页就机械全量枚举；
- 技术失败只表示当前能力失败，不得推导成“资源不存在”；
- 评测不指定某个平台或某条固定路线为唯一正确答案，除非用户输入本身明确限定；
- active Skill 不持有平台 API、Cookie、分页、签名、端点和 Adapter 机械事实。

## Current architecture

基线 commit：`3a20c1e14358631201e99fb54e007ccfcf118d94`。

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

当前 `SKILL.md` 已经包含 semantic-first 原则，但规则较分散，缺少足够突出的即时 decision kernel；下一阶段验证的不是“规则有没有写到”，而是模型是否稳定做出更好的实际决策。

## Expected change surface

Likely to change:

- `skills/SKILL.md`（仅 baseline 记录完成后）；
- `skills/references/retrieval.md`、`conversation.md`、`source-routing.md` 中与主决策重复的部分；
- `skills/examples/semantic-evaluation.md`；
- `skills/examples/semantic-regression-cases.json` 或新的 baseline suite；
- 本计划和必要的 active 文档索引。

Should not change:

- `mcp/education-resources/src/**`；
- MCP Tool name/schema；
- Adapter 平台实现；
- Job/Session 持久结构；
- Archive taxonomy。

## Target decision kernel

这不是状态机，也不落盘。Agent 在每一轮只需能回答以下即时问题：

```text
Task      用户现在是 Research / Locate / Browse / Enumerate / Acquire / Transform 哪类任务？
Goal      真正要完成什么；must / prefer / exclude 是什么？
Coverage  要完成目标，需要哪些不同学习价值或证据角色？
Evidence  当前候选分别证明了什么；哪些是真正有用、哪些仍不确定？
Gap       还缺什么具体价值或关键事实？
Next      下一步搜索/Inspect 能新增什么价值；如果说不出来就停止。
```

候选运行时不要求多维打分表，只需要能区分：

```text
Reject         明显不能解决当前目标
Hold           可能有用，但存在会改变决策的未知事实
Recommendable  已有足够证据说明为什么值得给用户看
```

`Hold` 才自然触发必要 Inspect；`Recommendable` 才进入 Coverage；`Reject` 不继续占用上下文。

## Acceptance criteria

- [x] AC-01：冻结 MCP 公共能力面作为语义实验底座；0073 已提供真实运行证据。
- [x] AC-02：评测方法拆成 hard invariant / judgment benchmark / real retrieval 三层，不再把遵守某条 Skill 规则直接当作资源质量。
- [x] AC-03：建立不绑定固定平台路线的 baseline case suite，覆盖 Research / Locate / Browse / Enumerate / Acquire / Transform。
- [ ] AC-04：在真实 OpenClaw 中用当前 `3a20c1e` Skill 执行 baseline suite，并保存用户输入、关键判断、实际 Tool trace、候选、Gap/stop 和最终回复。
- [ ] AC-05：baseline 后再将 active Skill 收敛为 Task → Goal → Coverage → Evidence → Gap → Next 的 decision kernel，不新增后端状态模型。
- [ ] AC-06：新版能明确区分 Research、Locate、Browse、Enumerate、Acquire、Transform，避免已知 URL/已选资源仍重启研究、普通浏览误升级为全量等错误。
- [ ] AC-07：一个合法 Gap 必须能推出一条实质不同、可解释的新路线；“可能还有更好”“还有平台没搜”不能单独驱动补搜。
- [ ] AC-08：停止条件包含“下一轮是否仍有明确高信息增益”，不以候选数量或平台数量决定停止。
- [ ] AC-09：使用同模型、同 MCP、同输入做 old/new A/B；新版在多数真实 judgment/real retrieval case 上稳定更好，且 hard invariant 无回归。
- [ ] AC-10：最终真实 OpenClaw 用户链路验证通过；MCP schema 与实现没有因语义优化发生无关改动。

## Complexity exceptions

无。`Task/Goal/Coverage/Evidence/Gap/Next` 是模型当前轮的思考框架，不是代码 DTO、持久 source of truth 或工作流状态。

## 步骤

- [x] completed：确认 `3a20c1e` 的 MCP/OpenClaw 验收足以作为稳定语义实验底座。
- [x] completed：清理进入语义阶段前的文档边界漂移，建立 0074 和新的三层评测方法/baseline suite。
- [ ] blocked：在真实 OpenClaw 中执行当前 Skill baseline；当前 GitHub-only 环境无 OpenClaw/Gateway 执行入口。
- [ ] pending：根据 baseline 的系统性失败重写 active Skill decision kernel，而不是按预想方案盲改。
- [ ] pending：压缩主 Skill 与 references 的重复规则，保证主 Skill 只保留高频决策内核。
- [ ] pending：同环境运行新版 A/B，记录质量改进与退化。
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
Actual user flow affected?: not yet; active SKILL intentionally unchanged before baseline
Actual user flow validated?: baseline pending
Scope drift detected?: no
```

## Decision log

### Decision 001 — MCP public surface freeze

- Context: 0073 已完成真实 Tool/平台/OpenClaw 验收，当前主要不确定性从数据面转移到语义决策质量。
- Chosen: 0074 不以 Skill 优化为理由修改 MCP 公共面。
- Why: 否则 old/new Skill A/B 同时改变工具底座，无法归因语义收益。
- Complexity introduced: 无。

### Decision 002 — baseline first

- Context: 0046 已做过 semantic-first 重构，但当时没有真实 OpenClaw A/B。
- Chosen: 先冻结并真实执行当前 Skill baseline，再修改 active Skill。
- Why: 避免“先改 Prompt，再用新规则证明自己正确”的自判卷。
- Complexity introduced: 仅新增评测样例与记录，不新增运行时架构。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| MCP release baseline | inherited from 0073 | 数据面可作为稳定实验底座 | Skill 语义质量 |
| static Skill/evaluator audit | completed | 当前重复与 self-judging 风险已识别 | 新版更好 |
| current Skill real baseline | blocked | — | 当前真实行为分布 |
| old/new OpenClaw A/B | pending | — | 新版语义收益 |

## 结果

尚未完成。当前只建立公平实验基线和评测边界，active `skills/SKILL.md` 在 baseline 执行前保持 `3a20c1e` 行为不变。