# 0031 Document Surface Simplification

- 状态：in_progress
- 创建日期：2026-08-10
- 完成日期：未完成
- 范围：根工作区上下文、`docs/` 导航、`skills/learning-resource-flow/` 运行文档

## 目标

减少同一知识在 README、根上下文、Skill、references、架构文档和执行计划之间的重复，建立更清楚的默认阅读面，同时不修改 MCP 机器契约、运行时代码、历史计划和归档内容。

## 边界

- 不修改 `mcp/education-resources/contracts/`、Schema、runtime 或公共 Tool。
- 不重命名、删除历史计划和 `docs/archive/`。
- 不改变 Retrieval Authority、Capability Authority、`prepare -> confirm -> start` 等既有产品语义。
- 旧 Skill reference 文件先保留为兼容跳转，避免现有链接断裂；新内容集中到更少的主题文档。

## 步骤

- [ ] in_progress：A. 新增 `docs/README.md`，建立人类文档唯一导航入口。
- [ ] pending：B. 精简 `TOOLS.md`、`CONTEXT.md`，统一根级产品用词。
- [ ] pending：C. 将 Skill references 收敛为 conversation / retrieval / source-routing / inspection / acquisition / library 六个主题。
- [ ] pending：D. 精简 `SKILL.md`，保留触发、任务模型、核心控制流、关键不变量和 reference 导航。
- [ ] pending：E. 把旧 reference 改成兼容跳转，检查相对链接和 Markdown 结构。
- [ ] pending：F. 更新计划结果并完成只读复核。

## 验证

- 检查所有新增/修改 Markdown 相对链接。
- 检查 UTF-8、代码围栏和明显重复导航。
- 不修改机器契约和运行时代码。

## 结果

- 实施中。
