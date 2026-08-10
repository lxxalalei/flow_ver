# Skill Semantic Loss Audit

- 状态：in_progress
- 创建日期：2026-08-11
- 完成日期：未完成
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

Likely to change:

- `skills/learning-resource-flow/references/conversation.md`
- `skills/learning-resource-flow/references/retrieval.md`
- `skills/learning-resource-flow/references/source-routing.md`
- `skills/learning-resource-flow/references/inspection.md`
- only if audit proves necessary: `acquisition.md` / `SKILL.md`

Should not change:

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

默认：无。此次不新增 abstraction、source of truth、fallback、compatibility layer 或 generalized framework。

## 步骤

- [x] completed：A. 对照旧 `SKILL.md`、`intent-and-clarification.md`、`candidate-judgment.md`、`adaptive-retrieval.md`、`discovery-strategy.md`、`inspection-strategy.md`、`acquisition-strategy.md`、`mcp-workflow.md`、`library-structure.md` 与当前 Skill/六 references。
- [ ] in_progress：B. 冻结 semantic-loss 清单与 intentionally-removed 清单。
- [ ] pending：C. 只对确认遗失的当前 Skill 行为做最小补回。
- [ ] pending：D. 回读差异，确认无机器事实副本、无新抽象、无 scope drift。
- [ ] pending：E. 记录验证并归档本计划。

## 初步审计结论

### Confirmed semantic loss candidates

1. Conversation：`explicit / inferred / defaulted` 证据强度及“不得把推断/默认复述成用户事实”。
2. Conversation：must / prefer / exclude 语气强度保持，避免把偏好升级为硬约束或反向弱化。
3. Conversation：使用载体 / 内容形态 / 文件格式三层语义，以及“电子版/可打印/高清/可下载是约束而不是文件格式”。
4. Retrieval：候选可信度与互补性没有保留为明确比较维度；官方来源、热度和平台名不能替代任务适配证据。
5. Retrieval / Presentation：`presentation_save` 失败后不能邀请用户按当前文本编号选择。
6. Source routing：何时用 `resource_browse_creator`（创作者主页/浏览创作者内容）在当前 references 中缺少明确触发规则。
7. Inspection：`FEATURE_NOT_SUPPORTED` 表示当前缺少 Inspector，不等于资源不存在/不可用；`partial/unresolved` 应降低证据强度而不是乐观补齐。

### Intentionally removed / should stay removed

- 平台静态能力表、catalog/registry 版本快照与 exact route 清单：机器 contracts/runtime 才是权威。
- 站点白名单副本：避免 Skill 维护第二套来源真相。
- taxonomy 固定 ID、物理归档目录、文件命名、Provider/Artifact 内部映射：属于 MCP/contract 实现事实。
- 默认登录提醒与固定平台认证表：容易过时且会诱导不必要的用户打断；AUTH_REQUIRED 按真实服务端状态处理即可。
- 旧安全/儿童主题扩展性护栏：除当前产品/任务已有明确需求外不重新扩写，避免借审计新增泛化安全规则。

## 验证

- 逐文件回读旧/新语义差异。
- 修改后使用 GitHub compare 确认仅修改审计允许的 Skill reference / plan 文件。
- 本任务只修改 Markdown Skill 运行规则，不运行 MCP 全量测试；不声称执行本地 link checker 或 `git diff --check`，除非实际执行。

## 结果

- 实施中。
