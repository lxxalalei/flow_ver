# Project Governance Integration

- 状态：completed
- 创建日期：2026-08-11
- 完成日期：2026-08-11
- 范围：根 `AGENTS.md`、`.agent/TASK_TEMPLATE.md`、`.agent/plans/README.md`、`.agent/REPORT_TEMPLATE.md`

## 目标

把 `gpt56-project-governance` 中与本项目现有治理缺口直接相关的规则融合进现有治理入口，重点约束最小正确修改、复杂度举证、范围漂移和按风险分级验证；不建立第二套平行 governance 文档体系。

## 非目标

- 不修改 MCP runtime、contracts、Skill 或测试实现。
- 不新增 `docs/ENGINEERING_GUARDRAILS.md`、`docs/TESTING_POLICY.md`、`docs/PRODUCT_CONTRACT.md` 等平行权威文档。
- 不重写现有产品架构、长期路线或历史计划。

## 步骤

- [x] completed：A. 将 12 条硬规则、复杂度举证和验证分级融合进根 `AGENTS.md`。
- [x] completed：B. 新增轻量 `.agent/TASK_TEMPLATE.md`，冻结 Goal/Non-goals/Invariants/Change Surface/Acceptance/Validation/Complexity Exception。
- [x] completed：C. 扩充 `.agent/plans/README.md` 的长任务模板与 milestone checkpoint，避免目标和范围漂移。
- [x] completed：D. 扩充 `.agent/REPORT_TEMPLATE.md`，区分 targeted/integration/backend E2E/user-flow/full regression 等实际验证等级。
- [x] completed：E. 复核差异仅涉及治理文档，完成并归档本计划。

## 验证

- 回读 `AGENTS.md`，确认包含 12 条硬规则、复杂度举证、第三方调查要求和四级验证预算。
- 回读 `.agent/TASK_TEMPLATE.md`、`.agent/plans/README.md`、`.agent/REPORT_TEMPLATE.md`，确认 Goal/Non-goals/Invariants、scope drift checkpoint 和验证等级均已落盘。
- 修正 `.agent/plans/README.md` 推荐模板的 Markdown 嵌套围栏，避免模板本身破坏渲染。
- 以任务开始前提交 `4153fe0b319ded8e397ac76cb8c0eec91a2aad91` 为基线执行分支 compare：只出现 `AGENTS.md`、`.agent/TASK_TEMPLATE.md`、`.agent/plans/README.md`、`.agent/REPORT_TEMPLATE.md` 和本计划文件，没有 runtime、contracts、Skill 或测试代码变化。
- 未运行 MCP/Skill 全量测试：本任务只修改 Markdown 治理文档，没有对应的运行时回归风险；未声称运行过本地 Markdown link checker 或 `git diff --check`，因为本次通过 GitHub connector 修改，未执行本地 shell 验证。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes; no product/runtime authority changed
New abstraction introduced?: no runtime abstraction; one task template added to existing .agent governance surface
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no, confirmed by branch compare
Actual user flow affected?: no
Actual user flow validated?: not applicable
Scope drift detected?: no
```

## 结果

- 根 `AGENTS.md` 现在直接承担工程硬规则，不再依赖另一个 Guardrails 文档。
- `.agent/TASK_TEMPLATE.md` 为局部非平凡任务提供最小 Task Spec；长任务继续使用现有 `.agent/plans/`。
- `.agent/plans/README.md` 从单纯步骤 tracker 升级为目标/边界/不变量/复杂度/验证可审查的 execution plan 规范。
- `.agent/REPORT_TEMPLATE.md` 明确区分实现、静态检查、targeted、integration、backend E2E、真实 Agent/user-flow、visual 和 full regression，禁止验证等级冒充。
- 没有复制 `gpt56-project-governance` 的平行文档树，因此没有新增第二套产品或架构真相源。
