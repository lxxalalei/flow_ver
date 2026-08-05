# 产品级重置与 Fit-Gap 审计

- 状态：in_progress
- 创建日期：2026-08-04
- 完成日期：未完成
- 范围：`skills/learning-resource-flow/`、`mcp/education-resources/`、`legacy/skill-pipeline-v1/`、目标资料库架构与后续开发路线

## 步骤

- [x] completed：复核工作树状态、仓库边界和已有开发计划
- [ ] in_progress：审计 active Skill 与 MCP 的状态模型、搜索、选择、下载和归档边界
- [ ] pending：审计 legacy Skill 中可迁移领域经验与应淘汰补丁
- [ ] pending：推导目标领域模型、标准归档策略和 Windows/OpenClaw 端到端闭环
- [ ] pending：形成分阶段路线、golden journeys、验收标准与优先级结论

## 验证

- 检查引用的文件与行号存在。
- 检查计划与 `docs/DEVELOPMENT_PLAN.md`、active v2 契约和实现事实一致。
- 运行 `git diff --check -- .agent/plans/0014-product-reset-fit-gap.md`。

## 结果

- 待完成后填写审计结论、建议路线和剩余风险。
