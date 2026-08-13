# 0046 Skill 语义层重构

- 状态：completed
- 创建日期：2026-08-14
- 完成日期：2026-08-14
- 实施分支：`codex/skill-semantic-refactor-0046`
- 范围：`skills/learning-resource-flow/`

## Objective

把 active `learning-resource-flow` 从 Flow/MCP 工作流说明书重构为强语义资源研究 Skill：Main Agent 优先负责需求还原、搜索角度、来源派发、query、结果判断和补搜决策；MCP 继续拥有 Flow/ResultSet/Presentation/Selection/Plan/Job/Asset 等事实和副作用。

## Non-goals / invariants

- 未修改 `education-resources` MCP、数据库、Provider 或 legacy。
- 未新增 Planner、AgentFlow、语义持久状态、新 source of truth、fallback 或截断。
- 单一 active Skill、Presentation 选择边界、`prepare -> confirm -> start`、资源 MCP 单一数据面均保持不变。

## 结果

1. `SKILL.md` 改为 semantic-first 主入口，优先顺序为：理解目标 -> 必要澄清 -> 互补角度 -> 内容/证据驱动来源 -> 自然 query -> 判断真实结果 -> 有明确缺口才补搜。主 Skill 保留最小 MCP choreography 和 4 个高区分度 few-shot。
2. `conversation.md` 只补复杂澄清/上层背景边界；`source-routing.md` 保留完整来源生态知识但不复制机器 Registry；`retrieval.md` 保留 ResultSet、可信度/互补性、公开访问、Presentation 等深度规则，但不再要求 `SemanticReview/Gap/StopDecision` 状态机。
3. `multi-agent.md` 标为 Experimental；普通 baseline 是一个强 Main Agent + Skill + MCP。`inspection.md` 对齐自然决策模型；acquisition/library 保持按需专业 reference。
4. `semantic-regression-cases.json` 升级到 4.0.0，主测 need reconstruction、clarification、search angles、source routing、query、result judgment、next action；workflow safety 仅作为 gate。新增 `semantic-evaluation.md` 定义真实 A/B 方法。

## 主要提交

- `466d257c` — semantic-first 主 Skill
- `d2952caa` — conversation guidance
- `7c970653` — 完整 source routing
- `539c2888` — retrieval 去状态机化
- `5aa0d13d` — multi-agent 实验化
- `a55fa1b8` — inspection 对齐
- `66564317` — semantic evaluation guide
- `d53dbf98` — semantic regression v4

## 验证

- Git compare `896fc844..codex/skill-semantic-refactor-0046`：仅 0046 plan 与 active Skill/reference/examples 变化，无 MCP/legacy 改动。
- 当前 Skill/reference 目录存在所有被主 Skill 引用的 reference。
- semantic regression v4 文件头、主体和闭合结构已回读检查；未在本环境执行独立 JSON parser。
- 当前 commit 无 GitHub CI/status checks，不能声称自动测试通过。
- 未运行真实 OpenClaw A/B；这仍是语义质量最终验收，方法见 `examples/semantic-evaluation.md`。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction/source of truth/fallback/truncation?: no
Unrelated files changed?: no
Scope drift detected?: no
```

## 剩余风险

需要用相同模型、相同 MCP、相同输入在真实 OpenClaw 中对旧 Skill 与 semantic-first Skill 做 A/B。若仍受 MCP choreography 干扰，优先评估让 MCP 内部维护 Search ResultSet lineage，而不是继续给 Skill 增加规则。
