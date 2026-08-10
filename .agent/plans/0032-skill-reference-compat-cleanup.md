# 0032 Skill Reference Compatibility Cleanup

- 状态：completed
- 创建日期：2026-08-11
- 完成日期：2026-08-11
- 范围：`skills/learning-resource-flow/references/` 兼容壳与历史路径迁移说明

## 目标

删除 0031 后已不再承担 active 规则职责的 11 个旧 reference 兼容壳，使 `references/` 只保留六个正式主题文档；同时保留历史审计/规划中“当时确实存在这些旧路径”的事实，并提供现行接替入口。

## 边界

- 不修改 MCP contracts、Schema、runtime 或公共 Tool。
- 不改写历史设计结论；历史正文保持原样，迁移说明集中记录在归档索引。
- 不删除六个正式 reference：`conversation.md`、`retrieval.md`、`source-routing.md`、`inspection.md`、`acquisition.md`、`library.md`。

## 步骤

- [x] completed：A. 在 `docs/archive/README.md` 与 `.agent/plans/archive/README.md` 集中记录旧 reference → 现行入口映射，不回写历史正文。
- [x] completed：B. 删除 11 个旧 reference 兼容壳。
- [x] completed：C. 复核 `references/` 最终仅保留六个正式文档，并确认 active Skill / active plans 不依赖旧路径。
- [x] completed：D. 记录验证结果并归档本计划。

## 验证

- 当前分支目录复核确认 `skills/learning-resource-flow/references/` 只剩：`acquisition.md`、`conversation.md`、`inspection.md`、`library.md`、`retrieval.md`、`source-routing.md`。
- 当前 `SKILL.md` 的 Reference 导航只指向上述六个正式文件。
- 当前 0023/0027/0028/0029 active plans 不引用旧 11 个 reference。
- 历史扫描发现的旧路径只存在于归档审计/规划语境；`docs/archive/README.md` 已集中说明迁移映射，`.agent/plans/archive/README.md` 明确这些旧路径是历史证据。
- 本轮只修改 Markdown/删除兼容壳，未修改 MCP contracts、Schema、runtime 或公共 Tool。
- 通过 GitHub connector 完成目录与内容复核；未在本地工作树运行 Markdown link checker 或 `git diff --check`。

## 结果

- 删除：`intent-and-clarification.md`、`response-guidelines.md`、`adaptive-retrieval.md`、`candidate-judgment.md`、`discovery-strategy.md`、`platform-capabilities.md`、`site-whitelist.md`、`inspection-strategy.md`、`acquisition-strategy.md`、`mcp-workflow.md`、`library-structure.md`。
- active references 最终收敛为六个职责明确的主题文件。
- 历史文档仍保留当时旧路径文字，不把历史事实重写成现行架构；读者可从归档索引看到现行接替入口。
