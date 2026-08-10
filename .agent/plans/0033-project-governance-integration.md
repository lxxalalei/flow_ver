# Project Governance Integration

- 状态：in_progress
- 创建日期：2026-08-11
- 完成日期：未完成
- 范围：根 `AGENTS.md`、`.agent/TASK_TEMPLATE.md`、`.agent/plans/README.md`、`.agent/REPORT_TEMPLATE.md`

## 目标

把 `gpt56-project-governance` 中与本项目现有治理缺口直接相关的规则融合进现有治理入口，重点约束最小正确修改、复杂度举证、范围漂移和按风险分级验证；不建立第二套平行 governance 文档体系。

## 非目标

- 不修改 MCP runtime、contracts、Skill 或测试实现。
- 不新增 `docs/ENGINEERING_GUARDRAILS.md`、`docs/TESTING_POLICY.md`、`docs/PRODUCT_CONTRACT.md` 等平行权威文档。
- 不重写现有产品架构、长期路线或历史计划。

## 步骤

- [ ] in_progress：A. 将 12 条硬规则、复杂度举证和验证分级融合进根 `AGENTS.md`。
- [ ] pending：B. 新增轻量 `.agent/TASK_TEMPLATE.md`，冻结 Goal/Non-goals/Invariants/Change Surface/Acceptance/Validation/Complexity Exception。
- [ ] pending：C. 扩充 `.agent/plans/README.md` 的长任务模板与 milestone checkpoint，避免目标和范围漂移。
- [ ] pending：D. 扩充 `.agent/REPORT_TEMPLATE.md`，区分 targeted/integration/backend E2E/user-flow/full regression 等实际验证等级。
- [ ] pending：E. 复核差异仅涉及治理文档，完成并归档本计划。

## 验证

- 逐文件回读新增规则与模板。
- 检查新增规则没有建立第二套业务/架构真相源。
- 通过分支 compare 确认本任务没有修改 runtime、contracts、Skill 或测试代码。
- 本任务仅修改 Markdown 治理文档，不运行 MCP/Skill 全量测试。

## 结果

- 实施中。
