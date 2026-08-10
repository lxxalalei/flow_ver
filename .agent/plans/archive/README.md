# 已归档计划

本目录保存已经完成、被替代或仅用于历史交接/证据追溯的计划文件。归档文件保留原始
计划内容和状态；归档不表示可以把未完成工作伪装为已完成。

## 阅读规则

- 顶层 `.agent/plans/` 只放当前仍需跟踪的 `in_progress`、`blocked` 和 `pending` 计划。
  已完成或已被替代的计划移入本目录。
- `archive/` **不是默认必读目录**。正常接手任务时先读取顶层当前计划；只有需要追溯
  历史决策、验证证据、迁移边界、接替关系或回滚信息时，才按本索引读取归档文件。
- 计划的唯一标识是**完整文件名**（包括数字前缀和主题 slug），不能只使用数字前缀。
  例如 `0025-capability-truth-audit.md` 与
  `0025-platform-capability-contract-alignment.md` 是两个不同计划。
- 计划重命名或移动后，所有 Markdown 链接必须指向新路径；正文中的计划引用也应使用
  完整文件名或明确的完整计划标题，避免重复编号造成歧义。

## 当前顶层计划

- [0023-retrieval-e2e-hardening.md](../0023-retrieval-e2e-hardening.md) — blocked
- [0027-platform-acquisition-enablement.md](../0027-platform-acquisition-enablement.md) — in_progress
- [0028-real-openclaw-platform-e2e.md](../0028-real-openclaw-platform-e2e.md) — pending
- [0029-retrieval-benchmark-release-gate.md](../0029-retrieval-benchmark-release-gate.md) — pending

## 归档索引

| 文件 | 原状态 | 归档说明 |
| --- | --- | --- |
| [0001-workspace-bootstrap.md](0001-workspace-bootstrap.md) | completed | 历史完成计划 |
| [0002-local-mcp-migration.md](0002-local-mcp-migration.md) | completed | 历史完成计划 |
| [0003-openclaw-glm-model.md](0003-openclaw-glm-model.md) | completed | 历史完成计划 |
| [0004-openclaw-browser-wsl.md](0004-openclaw-browser-wsl.md) | completed | 历史完成计划 |
| [0005-workspace-two-part-cleanup.md](0005-workspace-two-part-cleanup.md) | completed | 历史完成计划 |
| [0006-goal-first-semantic-rebuild.md](0006-goal-first-semantic-rebuild.md) | completed | 历史完成计划 |
| [0007-user-model-correction.md](0007-user-model-correction.md) | completed | 历史完成计划 |
| [0008-task-context-model.md](0008-task-context-model.md) | completed | 历史完成计划 |
| [0009-session-manager-distribution.md](0009-session-manager-distribution.md) | completed | 历史完成计划 |
| [0010-session-manager-native-windows.md](0010-session-manager-native-windows.md) | completed | 历史完成计划 |
| [0011-windows-openclaw-session-manager-install.md](0011-windows-openclaw-session-manager-install.md) | completed | 历史完成计划 |
| [0012-broad-browser-session-capture.md](0012-broad-browser-session-capture.md) | completed | 历史完成计划 |
| [0013-education-mcp-v2-control-plane.md](0013-education-mcp-v2-control-plane.md) | completed | 历史完成计划 |
| [0014-product-reset-fit-gap.md](0014-product-reset-fit-gap.md) | blocked | superseded；保留 blocked 状态并记录接替计划 |
| [0015-remove-education-v1-and-align-docs.md](0015-remove-education-v1-and-align-docs.md) | completed | 历史完成计划 |
| [0016-learning-resource-archive-foundation.md](0016-learning-resource-archive-foundation.md) | completed | 历史完成计划 |
| [0017-current-contract-and-doc-alignment.md](0017-current-contract-and-doc-alignment.md) | completed | 历史完成计划 |
| [0018-resource-model-and-platform-registry.md](0018-resource-model-and-platform-registry.md) | completed | 历史完成计划 |
| [0019-inspection-layer.md](0019-inspection-layer.md) | completed | 历史完成计划 |
| [0020-adaptive-retrieval-loop.md](0020-adaptive-retrieval-loop.md) | completed | 历史完成计划 |
| [0021-acquisition-core-and-web-materializer.md](0021-acquisition-core-and-web-materializer.md) | completed | 历史完成计划 |
| [0022-multimodal-asset-bundle.md](0022-multimodal-asset-bundle.md) | completed | 历史完成计划 |
| [0024-retrieval-authority-and-quality-calibration.md](0024-retrieval-authority-and-quality-calibration.md) | completed | 历史完成计划 |
| [0025-capability-truth-audit.md](0025-capability-truth-audit.md) | completed | 只读能力真相审计 |
| [0025-platform-capability-contract-alignment.md](0025-platform-capability-contract-alignment.md) | completed | 能力契约实施完成计划 |
| [0025-platform-capability-contract-alignment-handoff.md](0025-platform-capability-contract-alignment-handoff.md) | completed snapshot | 0025 完成快照与 0028 交接 |
| [0026-acquisition-call-site-migration.md](0026-acquisition-call-site-migration.md) | completed | 获取调用面迁移完成计划 |
| [0030-document-authority-consolidation.md](0030-document-authority-consolidation.md) | completed | 文档权威、归档和默认阅读面收敛 |
| [0031-document-surface-simplification.md](0031-document-surface-simplification.md) | completed | 默认阅读面与 Skill/reference 职责去重 |
