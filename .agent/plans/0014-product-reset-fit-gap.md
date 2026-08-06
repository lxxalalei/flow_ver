# 产品级重置与 Fit-Gap 审计

- 状态：blocked
- 创建日期：2026-08-04
- 完成日期：未完成
- 范围：`skills/learning-resource-flow/`、`mcp/education-resources/`、`legacy/skill-pipeline-v1/`、目标资料库架构与后续开发路线

## 步骤

- [x] completed：复核工作树状态、仓库边界和已有开发计划
- [ ] blocked：active Skill 与 MCP 的综合审计已部分完成；其中归档边界由 `0016-learning-resource-archive-foundation.md` 接替，其余控制面审计因产品优先级调整停止推进
- [ ] blocked：legacy Skill 迁移审计不属于 0016 范围，0014 停止推进期间不继续修改 legacy
- [ ] blocked：归档领域模型和标准归档策略由 0016 重新推导；Windows/OpenClaw 完整闭环不属于 0016，等待后续独立计划
- [ ] blocked：0016 将更新归档阶段路线和验收标准；其余 golden journeys 与产品级优先级结论等待后续重新立项

## 验证

- 检查引用的文件与行号存在。
- 检查计划与 `docs/DEVELOPMENT_PLAN.md`、active v2 契约和实现事实一致。
- 运行 `git diff --check -- .agent/plans/0014-product-reset-fit-gap.md`。

## 结果

- 2026-08-06：本计划因“学习资料归档体系重构”成为新的明确优先级而停止推进。
  历史已完成项保持不变，未完成项没有被伪造为完成。0016 只接替分类、Archive、
  文件目录、SQLite 归档索引、Library Search、迁移和恢复；搜索、选择、下载、legacy
  审计及完整 OpenClaw 闭环仍未完成，需要后续独立计划继续。
