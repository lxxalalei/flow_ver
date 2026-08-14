# 0050 — 当前项目事实与后续验收收口

- 状态：in_progress
- 创建日期：2026-08-14
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`

## Objective

把仓库中已经实现的 Skill、Shuge/Anna 获取路线、Provider 批次调度与当前真实验收阶段同步到计划、平台契约和架构文档；同时把 0029 从旧状态机指标改为与 semantic-first Skill 一致的决策质量 benchmark，避免后续开发继续依据过时事实。

## Non-goals

- 不修改 Search/Inspect/Download/Archive 的生产行为，除非只是修复平台 Registry 与实际能力不一致。
- 不新增平台、Planner、Agent、状态机、digest、fallback 或并发框架。
- 不代替用户执行真实 Windows OpenClaw / 平台下载验收。
- 不执行 0041 网页抽取 benchmark。

## Business invariants

- Skill 继续以需求理解、搜索角度、来源派发、query、结果判断为主；MCP 状态不重新变成模型思考协议。
- `prepare -> 用户明确确认 -> start`、exact Provider、no silent fallback 保持不变。
- Platform Registry 描述平台能力类别；Planner/Provider 才描述具体 `direct_file` / exact provider 执行路线。
- 离线测试和 benchmark 不冒充真实 OpenClaw E2E。

## Expected change surface

- `.agent/plans/` 与 `archive/README.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `contracts/platforms/platform-registry.json` 与 schema/直接测试
- `0029-retrieval-benchmark-release-gate.md`

不改生产下载器、搜索适配器、数据库和公共 Tool。

## Acceptance criteria

- AC-01：0043、0044、0049 从顶层移入 archive，归档索引与当前顶层计划准确。
- AC-02：Registry 覆盖 17 个平台且 schema 数量一致；Shuge 同时声明 `webpage` 与 `platform_book`，专用策略允许集包含 Shuge。
- AC-03：CURRENT_ARCHITECTURE 反映 semantic-first Skill、Anna/Shuge ProviderSpec 和 exact Provider 批次调度。
- AC-04：0029 不再以 `SemanticReview/Gap/StopDecision` 或已删除 authority/readiness/eligibility 链作为主要 benchmark 对象，改为需求还原、搜索角度、来源派发、query、结果判断与下一步决策质量；安全业务边界仍作为 critical gates。
- AC-05：只运行与改动匹配的契约/Registry/JSON/Markdown 静态验证，不跑全量回归。

## Steps

- [ ] in_progress：归档已完成计划并修正平台 Registry/schema 漂移。
- [ ] pending：同步 CURRENT_ARCHITECTURE。
- [ ] pending：重写 0029 semantic-first benchmark 计划。
- [ ] pending：最小验证、归档 0050。

## Complexity exceptions

无。此次只删除漂移和同步事实，不引入新抽象或 source of truth。
