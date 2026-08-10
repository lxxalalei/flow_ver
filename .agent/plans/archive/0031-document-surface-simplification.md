# 0031 Document Surface Simplification

- 状态：completed
- 创建日期：2026-08-10
- 完成日期：2026-08-10
- 范围：根工作区上下文、`docs/` 导航、`skills/learning-resource-flow/` 运行文档

## 目标

减少同一知识在 README、根上下文、Skill、references、架构文档和执行计划之间的重复，建立更清楚的默认阅读面，同时不修改 MCP 机器契约、运行代码、历史计划和归档内容。

## 边界

- 不修改 `mcp/education-resources/contracts/`、Schema、runtime 或公共 Tool。
- 不重命名、删除历史计划和 `docs/archive/`。
- 不改变 Retrieval Authority、Capability Authority、`prepare -> confirm -> start` 等既有产品语义。
- 旧 Skill reference 文件保留为兼容跳转，避免现有链接断裂；新内容集中到更少的主题文档。

## 步骤

- [x] completed：A. 新增 `docs/README.md`，建立人类文档唯一导航入口。
- [x] completed：B. 精简 `TOOLS.md`、`CONTEXT.md`，统一根级产品用词。
- [x] completed：C. 将 Skill references 收敛为 conversation / retrieval / source-routing / inspection / acquisition / library 六个主题。
- [x] completed：D. 精简 `SKILL.md`，保留触发、任务模型、核心控制流、关键不变量和 reference 导航。
- [x] completed：E. 把旧 reference 改成兼容跳转，检查相对链接和 Markdown 结构。
- [x] completed：F. 更新计划结果并完成只读复核。

## 验证

- GitHub compare 确认本计划只修改根 Markdown、`docs/README.md`、active Skill 和 references；未修改 MCP contracts、Schema 或 runtime。
- 新 `SKILL.md` 只引用已创建的六个主题 reference，并保留到 `docs/RETRIEVAL_AUTHORITY.md` 的权威链接。
- 旧 11 个 reference 文件均保留且改为短兼容入口，因此历史相对链接不会因本轮直接失效。
- `docs/README.md` 的主要导航目标均为当前已存在路径。
- 本轮通过 GitHub connector 执行，未在本地工作树运行仓库 Markdown link checker 或 `git diff --check`；后续本地开发会话仍应按 `AGENTS.md` 正常执行这些检查。

## 结果

- 新增统一文档导航 `docs/README.md`。
- 根 README/TOOLS/CONTEXT 与 IDENTITY/SOUL/USER 完成第一轮职责和产品用词收口。
- active `SKILL.md` 从“大而全规则副本”调整为主控流程 + 不变量 + reference 索引。
- Skill 运行规则集中到六个主题：`conversation.md`、`retrieval.md`、`source-routing.md`、`inspection.md`、`acquisition.md`、`library.md`。
- 旧细分 reference 不删除，改为兼容跳转，后续不应继续在旧文件新增规则。
- 当前架构文档、DEVELOPMENT_PLAN、MCP README、contracts README 和历史 archive 均保持原职责，不再在本轮重复重写。
