# 已归档计划

本目录保存已经完成、被替代或仅用于历史交接/证据追溯的计划文件。归档不表示可以把未完成工作伪装为已完成。

## 阅读规则

- 顶层 `.agent/plans/` 只放当前仍需跟踪的 `in_progress`、`blocked` 和 `pending` 计划；已完成或已被替代的计划移入本目录。
- `archive/` 不是默认必读目录。正常接手任务先看顶层当前计划，只有追溯历史决策、验证证据、迁移边界或回滚信息时再进入本目录。
- 计划的唯一标识是完整文件名（含数字前缀和主题 slug），不能只用数字前缀。
- 计划移动或重命名后，所有 Markdown 链接应指向新路径。
- 0031/0032 收敛了 active Skill references；归档材料中的旧 reference 路径只代表当时审计证据，现行映射见 [`docs/archive/README.md`](../../../docs/archive/README.md#历史-skill-reference-路径)。

## 当前顶层计划

- [0028-real-openclaw-platform-e2e.md](../0028-real-openclaw-platform-e2e.md) — in_progress，用户执行真实 OpenClaw/平台验收
- [0029-retrieval-benchmark-release-gate.md](../0029-retrieval-benchmark-release-gate.md) — pending，等待按 semantic-first Skill 收口
- [0041-web-content-extraction-benchmark.md](../0041-web-content-extraction-benchmark.md) — pending
- [0050-project-state-alignment.md](../0050-project-state-alignment.md) — in_progress，当前事实/文档/benchmark 收口

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
| [0014-product-reset-fit-gap.md](0014-product-reset-fit-gap.md) | blocked | superseded；保留 blocked 状态和接替说明 |
| [0015-remove-education-v1-and-align-docs.md](0015-remove-education-v1-and-align-docs.md) | completed | 历史完成计划 |
| [0016-learning-resource-archive-foundation.md](0016-learning-resource-archive-foundation.md) | completed | 历史完成计划 |
| [0017-current-contract-and-doc-alignment.md](0017-current-contract-and-doc-alignment.md) | completed | 历史完成计划 |
| [0018-resource-model-and-platform-registry.md](0018-resource-model-and-platform-registry.md) | completed | 历史完成计划 |
| [0019-inspection-layer.md](0019-inspection-layer.md) | completed | 历史完成计划 |
| [0020-adaptive-retrieval-loop.md](0020-adaptive-retrieval-loop.md) | completed | 历史完成计划 |
| [0021-acquisition-core-and-web-materializer.md](0021-acquisition-core-and-web-materializer.md) | completed | 历史完成计划 |
| [0022-multimodal-asset-bundle.md](0022-multimodal-asset-bundle.md) | completed | 历史完成计划 |
| [0024-retrieval-authority-and-quality-calibration.md](0024-retrieval-authority-and-quality-calibration.md) | completed | 历史完成计划 |
| [0025-capability-truth-audit.md](0025-capability-truth-audit.md) | completed | 旧能力真相审计；0037 后不再是 Active 获取架构 |
| [0025-platform-capability-contract-alignment.md](0025-platform-capability-contract-alignment.md) | completed | 旧能力契约实施证据；0037 已简化其运行时模型 |
| [0025-platform-capability-contract-alignment-handoff.md](0025-platform-capability-contract-alignment-handoff.md) | completed snapshot | 0025 完成快照与历史交接 |
| [0026-acquisition-call-site-migration.md](0026-acquisition-call-site-migration.md) | completed | 获取调用面历史迁移 |
| [0027-platform-acquisition-enablement.md](0027-platform-acquisition-enablement.md) | completed | 保留 exact Provider / no-silent-fallback 业务原则；旧 authority chain 已被 0037 废弃 |
| [0030-document-authority-consolidation.md](0030-document-authority-consolidation.md) | completed | 文档权威、归档和默认阅读面收敛 |
| [0031-document-surface-simplification.md](0031-document-surface-simplification.md) | completed | 默认阅读面与 Skill/reference 职责去重 |
| [0032-skill-reference-compat-cleanup.md](0032-skill-reference-compat-cleanup.md) | completed | 删除旧 reference 兼容壳并保留历史路径迁移说明 |
| [0033-project-governance-integration.md](0033-project-governance-integration.md) | completed | 最小修改、复杂度举证、scope checkpoint 与分级验证规则 |
| [0034-skill-semantic-loss-audit.md](0034-skill-semantic-loss-audit.md) | completed | 对照 0031 前 Skill 语义补回仍有效规则 |
| [0035-deleted-skill-reference-complete-audit.md](0035-deleted-skill-reference-complete-audit.md) | completed | 旧 Skill/reference 逐文件语义守恒审计 |
| [0036-platform-acquisition-capability-recovery.md](0036-platform-acquisition-capability-recovery.md) | superseded | 平台恢复目标保留；旧 Capability Authority 和重新引入大小/哈希门禁的路线被 0037 覆盖 |
| [0039-download-platform-active-expansion.md](0039-download-platform-active-expansion.md) | completed | SmartEdu 之后的 Douyin/Ximalaya/Bilibili active exact route 工程接入已完成；真实平台验收继续由 0028 跟踪 |
| [0040-search-subagent-orchestration.md](0040-search-subagent-orchestration.md) | completed | OpenClaw leaf sub-agent 并行规划 SearchDirection；MCP 继续统一串行执行搜索与业务状态 |
| [0042-web-resource-current-path-fix.md](0042-web-resource-current-path-fix.md) | completed | 修正当前 Generic HTML primary/landing 语义，并将网页主归档物改为图片自包含 HTML；0041 benchmark 继续 pending |
| [0043-shuge-guji-source.md](0043-shuge-guji-source.md) | completed engineering scope | Shuge OpenList 搜索、Inspect 与公开 `/d/` 文件链已实现；真实用户 E2E 继续由 0028 跟踪 |
| [0044-shuge-detail-url-search.md](0044-shuge-detail-url-search.md) | completed engineering scope | Shuge 详情页/短链可解析书名并回查公开存储；真实用户 E2E 继续由 0028 跟踪 |
| [0045-download-item-concurrency.md](0045-download-item-concurrency.md) | completed / superseded | 历史 Service 执行 Provider 并发声明设计；0047 已将并发所有权下沉到获取实现 |
| [0046-skill-semantic-refactor.md](0046-skill-semantic-refactor.md) | completed | 将 active Skill 重构为 semantic-first；主测需求还原、来源派发、query 和结果判断，multi-agent 降级为实验能力 |
| [0047-downloader-owned-concurrency.md](0047-downloader-owned-concurrency.md) | completed / superseded | 历史“一 Item 一 worker + Downloader 锁”方案；0048 已改为 exact Provider 批次派发 |
| [0048-provider-batch-dispatch-simplification.md](0048-provider-batch-dispatch-simplification.md) | completed | Service 按 exact Provider 批次派发；保留逐项结果但不再为每个 JobItem 创建 worker |
| [0049-annas-metadata-inspection.md](0049-annas-metadata-inspection.md) | completed | Anna's Archive Inspect 改为合法 MD5 元数据通道，避免合成详情页 403 阻断；等待 0028 用户复测 |
