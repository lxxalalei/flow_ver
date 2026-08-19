# 已归档计划

本目录保存已经完成、被替代或只用于历史交接/证据追溯的计划文件。归档不表示可以把未完成工作伪装为已完成；对于实现已结束但仍需真实用户验收的历史计划，剩余验收会明确转交当前 active 计划。

## 阅读规则

- 顶层 `.agent/plans/` 只放当前仍需直接跟踪的 `in_progress`、`blocked` 和 `pending` 计划。
- `archive/` 不是默认必读目录。正常接手任务先看顶层当前计划，只有追溯历史决策、平台事实、验证证据、迁移边界或回滚信息时再进入本目录。
- 计划的唯一标识是完整文件名（含数字前缀和主题 slug）。
- 历史计划中的架构术语以其创建时为准；与当前代码/`CURRENT_ARCHITECTURE.md` 冲突时，不得用历史计划覆盖当前事实。

## 当前顶层计划

当前只保留两份直接执行计划：

- [0028-real-openclaw-platform-e2e.md](../0028-real-openclaw-platform-e2e.md) — `in_progress`，统一承接真实 Windows OpenClaw、平台、Session、Job、Batch 用户验收；
- [0058-system-convergence-and-resource-fidelity.md](../0058-system-convergence-and-resource-fidelity.md) — `in_progress`，系统收敛的最后 M7，最终由 0028 的真实用户证据完成验收。

## 2026-08-19 active 面收敛

以下计划从顶层移入归档。原文件内容保持不变，便于追溯当时实现和证据；其中出现的 `Prepare / Confirm / Start / Asset`、独立 session-manager、旧 Tool 数量或旧 pytest 基线均属于历史语境，不再是当前运行架构。

| 文件 | 原状态 | 归档说明 / 剩余事项 |
| --- | --- | --- |
| [0051-yixi-video-acquisition.md](0051-yixi-video-acquisition.md) | in_progress | Yixi 工程实现历史；旧 Prepare/Start/Asset 获取链已失效。剩余 `speech_id=1435` 真实 OpenClaw MP4 验收转交 0028 |
| [0052-zjer-course-video-acquisition.md](0052-zjer-course-video-acquisition.md) | in_progress | Zjer experimental 课程视频实现历史；旧确认/Start/Asset 与 broad Registry 收口要求不再作为当前架构门槛。剩余 `courseCateId=34941` 用户链转交 0028 |
| [0054-douyin-creator-id-exposure.md](0054-douyin-creator-id-exposure.md) | in_progress | `creator_sec_uid` 实现、聚焦测试、部署 probe 与底层真实调用已有证据；剩余 OpenClaw creator/compaction 复测统一转交 0028 |
| [0056-download-job-subprocess-durability.md](0056-download-job-subprocess-durability.md) | in_progress | detached worker / file-backed Job 实现和进程级验证历史；旧“51 failures 基线”已被最新 205 tests 全过取代。剩余 Windows gateway restart 验收转交 0028 |
| [0057-native-batch-capability-parity.md](0057-native-batch-capability-parity.md) | in_progress | Batch、SmartEdu tabs/catalog、Bilibili time range 等原生化实现历史；旧 9 Tool、独立 session-manager 复用和 51 failures 等描述只作历史。代表性真实 Batch 用户链转交 0028 |
| [0059-post-convergence-review-fixes.md](0059-post-convergence-review-fixes.md) | completed | release-ready 收尾已完成：205 tests、compileall、runtime verifier、14 Tool stdio probe；按计划管理规范归档 |

## 0058 已替代的计划

| 文件 | 原状态 | 归档说明 |
| --- | --- | --- |
| [0029-retrieval-benchmark-release-gate.md](0029-retrieval-benchmark-release-gate.md) | pending | 语义检索 benchmark 思路保留为历史参考；不再作为 active release gate，后续质量判断以真实 OpenClaw 与 `learning-resource-flow` 当前语义规则为准 |
| [0041-web-content-extraction-benchmark.md](0041-web-content-extraction-benchmark.md) | pending | benchmark-first 路线被 0058 的 raw source + Trafilatura 最小方案替代 |

## 历史归档索引

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
| [0009-session-manager-distribution.md](0009-session-manager-distribution.md) | completed | 独立 session-manager 的历史设计；0058 已将部署边界合回 education-resources |
| [0010-session-manager-native-windows.md](0010-session-manager-native-windows.md) | completed | Windows 本机凭据保护历史实现；必要 DPAPI 能力由 0058 迁入 education-resources |
| [0011-windows-openclaw-session-manager-install.md](0011-windows-openclaw-session-manager-install.md) | completed | 独立 MCP 安装历史，不再是当前部署方式 |
| [0012-broad-browser-session-capture.md](0012-broad-browser-session-capture.md) | completed | 宽浏览器捕获领域知识保留；0058 改为同一 MCP 内先筛选后保存 canonical session |
| [0013-education-mcp-v2-control-plane.md](0013-education-mcp-v2-control-plane.md) | completed | 历史控制面设计 |
| [0014-product-reset-fit-gap.md](0014-product-reset-fit-gap.md) | blocked | superseded；保留 blocked 状态和接替说明 |
| [0015-remove-education-v1-and-align-docs.md](0015-remove-education-v1-and-align-docs.md) | completed | 历史完成计划 |
| [0016-learning-resource-archive-foundation.md](0016-learning-resource-archive-foundation.md) | completed | 历史完成计划 |
| [0017-current-contract-and-doc-alignment.md](0017-current-contract-and-doc-alignment.md) | completed | 历史完成计划 |
| [0018-resource-model-and-platform-registry.md](0018-resource-model-and-platform-registry.md) | completed | 历史资源模型/平台 Registry 设计 |
| [0019-inspection-layer.md](0019-inspection-layer.md) | completed | Inspection 历史实现 |
| [0020-adaptive-retrieval-loop.md](0020-adaptive-retrieval-loop.md) | completed | 旧检索状态化实现历史 |
| [0021-acquisition-core-and-web-materializer.md](0021-acquisition-core-and-web-materializer.md) | completed | Acquisition/Web Materializer 历史基础 |
| [0022-multimodal-asset-bundle.md](0022-multimodal-asset-bundle.md) | completed | 旧 AssetBundle 设计历史 |
| [0024-retrieval-authority-and-quality-calibration.md](0024-retrieval-authority-and-quality-calibration.md) | completed | 旧 authority/quality 设计历史 |
| [0025-capability-truth-audit.md](0025-capability-truth-audit.md) | completed | 旧能力真相审计 |
| [0025-platform-capability-contract-alignment.md](0025-platform-capability-contract-alignment.md) | completed | 旧能力契约实施证据 |
| [0025-platform-capability-contract-alignment-handoff.md](0025-platform-capability-contract-alignment-handoff.md) | completed snapshot | 0025 完成快照与历史交接 |
| [0026-acquisition-call-site-migration.md](0026-acquisition-call-site-migration.md) | completed | 获取调用面历史迁移 |
| [0027-platform-acquisition-enablement.md](0027-platform-acquisition-enablement.md) | completed | 保留 exact Provider / no-silent-fallback 原则；旧 authority chain 已废弃 |
| [0030-document-authority-consolidation.md](0030-document-authority-consolidation.md) | completed | 文档权威与默认阅读面收敛 |
| [0031-document-surface-simplification.md](0031-document-surface-simplification.md) | completed | Skill/reference 职责去重 |
| [0032-skill-reference-compat-cleanup.md](0032-skill-reference-compat-cleanup.md) | completed | 删除旧 reference 兼容壳 |
| [0033-project-governance-integration.md](0033-project-governance-integration.md) | completed | 最小修改、复杂度举证、scope checkpoint 与分级验证规则 |
| [0034-skill-semantic-loss-audit.md](0034-skill-semantic-loss-audit.md) | completed | Skill 语义守恒审计 |
| [0035-deleted-skill-reference-complete-audit.md](0035-deleted-skill-reference-complete-audit.md) | completed | 旧 Skill/reference 完整审计 |
| [0036-platform-acquisition-capability-recovery.md](0036-platform-acquisition-capability-recovery.md) | superseded | 平台恢复目标保留；旧 Capability Authority / 大小哈希门禁路线被后续简化 |
| [0039-download-platform-active-expansion.md](0039-download-platform-active-expansion.md) | completed | SmartEdu/Douyin/Ximalaya/Bilibili exact route 工程接入历史 |
| [0040-search-subagent-orchestration.md](0040-search-subagent-orchestration.md) | completed | OpenClaw leaf sub-agent 搜索规划实验历史 |
| [0042-web-resource-current-path-fix.md](0042-web-resource-current-path-fix.md) | completed | Generic HTML primary/landing 与早期自包含 HTML 路线；0058 已改为 raw source + Trafilatura |
| [0043-shuge-guji-source.md](0043-shuge-guji-source.md) | completed engineering scope | Shuge 搜索/Inspect/公开文件链 |
| [0044-shuge-detail-url-search.md](0044-shuge-detail-url-search.md) | completed engineering scope | Shuge 详情页/短链解析 |
| [0045-download-item-concurrency.md](0045-download-item-concurrency.md) | completed / superseded | 历史 Provider 并发设计 |
| [0046-skill-semantic-refactor.md](0046-skill-semantic-refactor.md) | completed | active Skill semantic-first 重构 |
| [0047-downloader-owned-concurrency.md](0047-downloader-owned-concurrency.md) | completed / superseded | 历史 downloader 并发方案 |
| [0048-provider-batch-dispatch-simplification.md](0048-provider-batch-dispatch-simplification.md) | completed | exact Provider 批次派发 |
| [0049-annas-metadata-inspection.md](0049-annas-metadata-inspection.md) | completed | Anna MD5 元数据 Inspect 修复；真实用户 E2E 继续由 0028 跟踪 |
| [0050-project-state-alignment.md](0050-project-state-alignment.md) | completed | 历史状态/文档对齐 |
| [0053-browser-cookie-capture-chain.md](0053-browser-cookie-capture-chain.md) | superseded | 登录事故保留；自建 CDP/WebSocket 捕获已撤销 |
