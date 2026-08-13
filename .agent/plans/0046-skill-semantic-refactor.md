# 0046 Skill 语义层重构

- 状态：in_progress
- 创建日期：2026-08-14
- 完成日期：未完成
- 范围：`skills/learning-resource-flow/`

## Objective

把 active `learning-resource-flow` 从“Flow/MCP 工作流说明书”重构为“强语义资源研究 Skill”：优先释放 Main Agent 的需求理解、搜索方向设计、来源选择、query 生成、结果判断和迭代搜索能力；MCP 继续拥有 Flow/ResultSet/Presentation/Selection/Plan/Job/Asset 等服务端事实与副作用。

## Non-goals

- 不修改 `education-resources` MCP 公共 Tool 契约或数据库状态模型。
- 不恢复 legacy 六阶段/多 Skill 文件流水线。
- 不新增 Planner 服务、AgentFlow、语义持久状态或新的 source of truth。
- 不在本任务执行 0041 网页正文抽取、平台接入、0045 下载并发或其他无关修复。
- 不删除 `legacy/`；历史对比继续依赖 Git 历史和既有 legacy 快照。

## Business invariants

- `skills/learning-resource-flow/` 仍是唯一 active 用户入口 Skill。
- Main Agent 负责语义决策；MCP 负责业务事实、状态校验和副作用。
- 模型不伪造 Flow/Resource/Plan/Job/Asset ID、Provider、下载或归档结果。
- 用户实际展示的候选仍需记录 Presentation；用户选择只针对实际展示内容。
- 下载仍保持 `prepare -> 用户明确确认 -> start`。
- 资源发现/核验仍只使用 `education-resources` 业务工具，不引入第二条资源数据面。
- 未知用户背景保持未知；不为补字段追问，不建立资源系统用户画像。

## Current architecture

- 主 `SKILL.md` 约 19KB，直接承载大量 Flow、ResultSet、Presentation、Selection、幂等、Plan/Job、StopDecision 和 multi-agent 协议规则。
- 需求理解和来源路由的高价值语义知识主要分散在 `references/conversation.md`、`references/source-routing.md`、`references/retrieval.md`。
- `examples/semantic-regression-cases.json` 同时测试语义与大量 workflow compliance，容易出现“流程合规但决策质量下降”仍看不出来的问题。
- MCP 已能作为服务端事实来源并拒绝非法状态转换，因此 Skill 不需要重复充当 workflow validator。

## Expected change surface

Likely to change:

- `skills/learning-resource-flow/SKILL.md`
- `skills/learning-resource-flow/references/conversation.md`
- `skills/learning-resource-flow/references/source-routing.md`
- `skills/learning-resource-flow/references/retrieval.md`
- `skills/learning-resource-flow/references/multi-agent.md`（降级为实验/高级参考）
- `skills/learning-resource-flow/examples/semantic-regression-cases.json`
- 必要时新增一个面向决策质量的轻量语义评测说明/样例文件

Should not change:

- `mcp/education-resources/` 公共契约和生产实现
- `legacy/skill-pipeline-v1/`
- 归档/下载真实业务边界

## Acceptance criteria

- AC-01：主 `SKILL.md` 首要内容是需求理解、搜索角度、来源路由、query 和结果判断，不再以 MCP 状态协议为思考主轴。
- AC-02：主 Skill 不再要求模型理解 `SemanticReview/Gap/StopDecision` 形式状态机；保留等价的自然判断能力。
- AC-03：平台派发由“用户目标 -> 所需内容/证据 -> 来源生态 -> 自然 query”驱动，不按平台数量机械扩散。
- AC-04：主路径默认单 Agent；multi-agent 仅保留为可选高级参考，不参与普通搜索 baseline。
- AC-05：MCP 操作说明压缩为最小 choreography；详细 acquisition/inspection/library 边界按阶段引用 reference。
- AC-06：语义回归重点覆盖 need reconstruction、互补搜索方向、平台职责、query 质量、结果不匹配识别和下一轮搜索质量；workflow safety 只保留关键不可破坏项。
- AC-07：至少包含 4 个高区分度 few-shot，展示“机械关键词/机械平台派发”与“目标驱动搜索”的差异。
- AC-08：不引入新持久状态、fallback、截断、额外 active Skill 或 MCP 改动。

## Validation scope

- Level 1：Markdown/JSON 结构、链接与语法检查。
- Level 2：对 active Skill/reference 的静态一致性检查；确认不存在旧术语/平台机器事实的重复权威。
- Level 3：用语义回归案例做结构化人工/Agent A-B baseline；若当前环境不能真实运行 OpenClaw，则明确记录未验证，不用后端测试冒充。
- 不运行全量 MCP 回归；本任务不改 MCP。

## Complexity exceptions

默认：无。此次重构目标就是删除协议性复杂度，不新增抽象。

## 步骤

- [ ] in_progress：Milestone 1 — 重写主 `SKILL.md` 为薄协议、强语义 baseline，并单独提交推送。
- [ ] pending：Milestone 2 — 重构 conversation/source-routing/retrieval references，删除与主 Skill 重复或协议化内容，并单独提交推送。
- [ ] pending：Milestone 3 — 将 multi-agent 降级为实验参考，保留 acquisition/inspection/library 按需边界，检查 reference 链接与职责，并单独提交推送。
- [ ] pending：Milestone 4 — 重构 semantic regression 为决策质量优先的用例，补 few-shot/评测说明并单独提交推送。
- [ ] pending：Milestone 5 — 最小充分验证、整体 diff 复核、完成计划并归档。

## Milestone checkpoint

每阶段完成后核对：

```text
Original goal still unchanged?: yes
Non-goals still respected?:
Business invariants still true?:
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no
Actual user flow affected?: semantic planning and interaction only
Actual user flow validated?: pending
Scope drift detected?:
```

## Decision log

### Decision 001 — 厚后端、薄协议、强语义

- Context：实测发现当前 Skill 流程合规但需求分析、平台派发和 query 质量下降。
- Options considered：继续给现有 Flow Skill 增加规则；恢复 legacy 多 Skill；重构为强语义单 Skill + 现有 MCP。
- Chosen option：强语义单 Skill + 现有 MCP。
- Why：保留服务端真实业务边界，同时把模型注意力重新放回用户目标和资源研究。
- Complexity introduced：无；目标是减少现有复杂度。

### Decision 002 — 单 Agent 先作为 baseline

- Context：当前语义质量尚未稳定，multi-agent 规则本身增加主上下文负担。
- Chosen option：普通路径不讲 sub-agent；multi-agent 仅保留 reference 中作为后续实验能力。
- Why：先证明一个强 Main Agent + 强语义 Skill + MCP 的基线质量。
- Complexity introduced：无。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| Markdown/JSON static | pending | 文件结构和语法 | 实际 Agent 语义质量 |
| reference consistency | pending | 主 Skill/reference 职责一致 | 搜索结果质量 |
| semantic cases review | pending | 决策规则覆盖目标场景 | 真实 OpenClaw runtime |
| real Agent A/B | pending | 新旧 Skill 实际体验差异 | 所有平台实时质量 |

## 结果

待完成。
