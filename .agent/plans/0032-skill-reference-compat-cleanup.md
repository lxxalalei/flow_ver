# 0032 Skill Reference Compatibility Cleanup

- 状态：in_progress
- 创建日期：2026-08-11
- 完成日期：未完成
- 范围：`skills/learning-resource-flow/references/` 兼容壳与少量历史路径注释

## 目标

删除 0031 后已不再承担 active 规则职责的 11 个旧 reference 兼容壳，使 `references/` 只保留六个正式主题文档；同时保留历史审计/规划中“当时确实存在这些旧路径”的事实，并补充其现行接替入口。

## 边界

- 不修改 MCP contracts、Schema、runtime 或公共 Tool。
- 不改写历史设计结论，只在发现旧 reference 路径的归档文档中补充迁移注释。
- 不删除六个正式 reference：`conversation.md`、`retrieval.md`、`source-routing.md`、`inspection.md`、`acquisition.md`、`library.md`。

## 步骤

- [ ] in_progress：A. 补充两份历史文档中的旧路径迁移说明。
- [ ] pending：B. 删除 11 个旧 reference 兼容壳。
- [ ] pending：C. 复核 `references/` 最终仅保留六个正式文档，并确认 active 文档无旧路径依赖。
- [ ] pending：D. 记录验证结果并归档本计划。

## 验证

- GitHub 当前分支目录复核。
- 当前 `SKILL.md` 与 active plans 不引用旧 11 个 reference。
- 历史旧路径仅作为历史事实保留，并标注 0031 后的现行入口。
