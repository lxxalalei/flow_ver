# 文档权威收敛与接手认知负担整理

- 状态：completed
- 创建日期：2026-08-10
- 完成日期：2026-08-10
- 范围：根 README/TOOLS、`docs/`、`.agent/plans/`、MCP README 与契约 Markdown
- 前提决策：`docs/DEVELOPMENT_PLAN.md` 是唯一长期路线图；active Skill 及其 references 本轮不修改
- 非目标：不改 MCP Python/runtime、JSON Schema、tool catalog、测试、Skill 语义或 Git 工作树中的无关改动

## 步骤

- [x] completed：检查工作树、AGENTS 约束、计划规范和目标文档跟踪状态
- [x] completed：归档历史设计和已完成计划，规范当前/后续计划可发现性与编号
- [x] completed：收敛根 README、CURRENT_ARCHITECTURE、DEVELOPMENT_PLAN 与 TOOLS 权威入口
- [x] completed：收敛 MCP README 和契约说明，保留当前真实兼容边界且不修改机器契约
- [x] completed：更新链接、归档索引和计划状态，运行 Markdown、diff 与一致性验证

## 验证

- 检查 Markdown 本地链接、UTF-8 与代码围栏。
- 检查根 README 默认阅读路径只指向当前权威文档和当前计划。
- 检查 active Skill 目录没有本轮改动。
- 检查 `git diff --check`。
- 不运行 Skill semantic regression；本轮不修改 active Skill。
- 不运行无关 MCP 全量测试；本轮不修改 runtime 或机器契约。

## 结果

- 根 README、TOOLS、当前架构、唯一 evergreen 路线图和 Retrieval Authority ADR 已收敛；默认阅读顺序为 AGENTS → 当前事实 → 长期路线 → 当前计划。
- 三份早期设计/阶段规划已移入 `docs/archive/`，27 份历史/完成计划已移入 `.agent/plans/archive/`；0014 保留 blocked 并明确 superseded。
- 当前技术计划唯一编号为 0027 → 0028 → 0029；0023 保留 blocked，历史计划使用完整文件名索引。
- MCP README 与契约 Markdown 已收敛；当前兼容只读行为和 Outcome `running` Schema 漂移被如实记录，本轮未修改机器契约。
- 全仓 Markdown 本地链接、UTF-8、围栏和 `git diff --check` 通过；active Skill 及 MCP Python/JSON 机器文件与本轮开始前哈希一致。
- 未运行 Skill semantic regression 或 MCP 全量测试，因为本轮未修改 active Skill、runtime 或机器契约。
- 剩余风险：工作树仍包含大量用户既有未提交代码/契约修改；Outcome `running` 与公共 Schema 的漂移需后续独立修复；0027–0029 产品路线尚未完成。
