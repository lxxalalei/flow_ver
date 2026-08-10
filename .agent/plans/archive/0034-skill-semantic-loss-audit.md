# Skill Semantic Loss Audit

- 状态：completed
- 创建日期：2026-08-11
- 完成日期：2026-08-11
- 范围：`skills/learning-resource-flow/SKILL.md` 与当前六个 references；对照 0031 前提交 `3c90806099dd13191b437c1ffb862f83182af47b` 的 Skill 运行规则

## Objective

确认 0031/0032 文档收敛是否误删仍然有效的 Skill 行为规则；只把能够影响真实对话/检索/候选判断/状态解释且仍符合当前架构的规则最小补回，不恢复旧 reference 结构或机器实现细节。

## Non-goals

- 不恢复 11 个已删除旧 reference 文件。
- 不恢复静态平台能力表、catalog 版本快照、taxonomy 常量、文件布局、Provider 内部映射等机器事实副本。
- 不修改 MCP runtime、contracts、Schema、Tool 或长期路线。
- 不以“旧文件曾经存在”为理由恢复已过时或与当前治理冲突的规则。

## Business invariants

- Skill 只拥有语义与对话判断，不建立第二套 MCP 事实来源。
- 用户明确约束、未知事实和服务端失败状态不得被模型乐观改写。
- ResultSet / Presentation / Selection、Inspect、Acquisition 和 Archive 的既有权威边界不变。
- 不新增 fallback、隐式平台路由或新的安全框架。

## Current architecture

- Current active Skill: `skills/learning-resource-flow/SKILL.md`
- Current references: `conversation.md`、`retrieval.md`、`source-routing.md`、`inspection.md`、`acquisition.md`、`library.md`
- Semantic authority: Skill owns task understanding / SemanticReview / Gap / StopDecision；MCP owns factual state and side effects.
- Audit baseline: commit `3c90806099dd13191b437c1ffb862f83182af47b`, before 0031 simplification.

## Expected change surface

实际修改：

- `skills/learning-resource-flow/references/conversation.md`
- `skills/learning-resource-flow/references/retrieval.md`
- `skills/learning-resource-flow/references/source-routing.md`
- `skills/learning-resource-flow/references/inspection.md`
- `skills/learning-resource-flow/references/acquisition.md`

未修改：

- `skills/learning-resource-flow/SKILL.md`
- `skills/learning-resource-flow/references/library.md`
- `mcp/education-resources/**`
- `contracts/**`
- `docs/DEVELOPMENT_PLAN.md`
- current 0027/0028/0029 product plans

## Acceptance criteria

- AC-01：旧规则逐类判断为 retained / intentionally removed / semantic loss，不以文本长度判断。
- AC-02：补回内容只包含仍有效的 Skill 行为，不复制机器事实或历史版本快照。
- AC-03：补回后当前六-reference 结构不变，不新增第二套规则来源。
- AC-04：diff 仅涉及必要 Skill reference 与本审计计划/归档索引。

## Complexity exceptions

无。此次没有新增 abstraction、source of truth、fallback、compatibility layer 或 generalized framework。

## 步骤

- [x] completed：A. 对照旧 `SKILL.md`、`intent-and-clarification.md`、`candidate-judgment.md`、`adaptive-retrieval.md`、`discovery-strategy.md`、`inspection-strategy.md`、`acquisition-strategy.md`、`mcp-workflow.md`、`library-structure.md` 与当前 Skill/六 references。
- [x] completed：B. 冻结 semantic-loss 清单与 intentionally-removed 清单。
- [x] completed：C. 只对确认遗失的当前 Skill 行为做最小补回。
- [x] completed：D. 回读差异，确认无机器事实副本、无新抽象、无 scope drift。
- [x] completed：E. 记录验证并归档本计划。

## 审计结论

### Confirmed semantic loss — 已最小补回

1. **Conversation evidence**：恢复 `explicit / inferred / defaulted` 证据强度，以及“不得把推断/默认复述成用户事实”。
2. **Constraint strength**：恢复 must / prefer / exclude 的语气强度保持，防止偏好升级为硬约束或硬约束被弱化。
3. **Resource semantics**：恢复使用载体 / 内容形态 / 文件格式三层语义；“电子版/可打印/高清/可下载”保留为约束而非格式。
4. **Candidate comparison**：恢复可信度与互补性的比较边界，但放入 reasons/排序，不新增第二套评分模型或公共字段；官方来源/热度不能替代任务证据。
5. **Presentation failure**：恢复 `resource_presentation_save` 失败后不能让用户按当前文本编号继续选择。
6. **Creator browse routing**：恢复“按主题搜索”和“浏览某创作者/账号已有内容”的工具选择边界；creator browse 仍只产生 ResultSet，不是批量下载入口。
7. **Inspection semantics**：恢复 unsupported/`FEATURE_NOT_SUPPORTED` 不等于资源不存在；partial/未形成 Resolution 时保持 unknown/未核验；历史 Resolution 不能说成刚刚重新检查。
8. **Acquisition retry semantics**：恢复同逻辑请求重试复用 idempotency key、请求变化换新 key、结构化失败不视为状态转换成功，以及 Selection/Presentation/Plan 变化后重新 prepare 并重新确认。

### Retained elsewhere — 无需重复补回

- ResultSet / Presentation / Selection 不可混用、实际展示顺序必须与 Presentation 一致：当前 `SKILL.md` / `retrieval.md` 已保留。
- SemanticReview / Gap / StopDecision 与 factual coverage 的唯一权威边界：当前 `SKILL.md` / `retrieval.md` / Retrieval ADR 已保留。
- Inspect 只检查会改变决策的少量高潜候选：当前 `SKILL.md` / `inspection.md` 已保留。
- Capability → Readiness → Resolution/Representation → Eligibility → Plan/Execution → exact Provider → Outcome → Asset：当前 `SKILL.md` / `acquisition.md` 已保留。
- AUTH_REQUIRED 使用 session-manager、禁止凭据进入 Tool/Skill、禁止静默 Generic fallback：当前 Skill/reference 已保留。
- Archive 只使用 validated `asset_id`、Bundle 与 ZIP/文件夹区分、Resource type 与 Asset format 分层：当前 `library.md` 已保留。

### Intentionally removed — 保持删除

- 平台静态能力表、catalog/registry 版本快照与 exact route 清单：机器 contracts/runtime 才是权威。
- 站点白名单副本：避免 Skill 维护第二套来源真相。
- taxonomy 固定 ID、物理归档目录、文件命名、Provider/Artifact 内部映射：属于 MCP/contract 实现事实。
- 默认登录提醒与固定平台认证表：容易过时且会诱导不必要的用户打断；AUTH_REQUIRED 按真实服务端状态处理即可。
- 旧文件中大段服务端安全校验、Artifact/Bundle 持久化细节和历史测试/版本数字：不属于 Skill 语义职责。
- 旧安全/儿童主题扩展性护栏：除当前产品/任务已有明确需求外不重新扩写，避免借审计新增泛化安全规则。
- 推荐固定 3–5 个、固定平台数量等表现层默认不额外恢复为强规则；当前有界预算和用户目标已经足够约束，不把历史经验升级成新业务要求。

## 验证

- 回读旧 `intent-and-clarification.md`、`candidate-judgment.md`、`adaptive-retrieval.md`、`discovery-strategy.md`、`inspection-strategy.md`、`acquisition-strategy.md`、`mcp-workflow.md`、`library-structure.md` 及 0031 前 `SKILL.md`，与当前六 references 对照。
- 修改后逐文件回读 `conversation.md`、`retrieval.md`、`source-routing.md`、`inspection.md`、`acquisition.md`。
- 以本任务开始前提交 `f5e8aee7fc2cd4a24a7729168e42680820de31ff` 为基线执行 GitHub compare：除本计划外，只修改上述 5 个现有 reference；未修改 MCP runtime、contracts、Schema、Tool、`SKILL.md`、`library.md` 或产品路线。
- 五个 reference 合计只新增 57 行，没有恢复旧 reference、平台表或机器事实副本。
- 本任务只修改 Markdown Skill 运行规则，因此未运行 MCP/Skill 全量测试；未执行本地 Markdown link checker 或 `git diff --check`，不声称这些验证已完成。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no, branch compare confirmed
Actual user flow affected?: yes, only by restoring previously lost Skill decision guidance
Actual user flow validated?: no real OpenClaw round executed in this doc-only audit
Scope drift detected?: no
```

## 结果

0031 的确存在“语义压缩过头”，但并非所有被删文本都应恢复。本轮只把仍然有效且会直接影响 Agent 对话/检索/候选/Inspect/获取行为的规则补进现有五个 reference；旧的 11-reference 结构和机器事实副本继续保持删除。当前六-reference 架构不变。
