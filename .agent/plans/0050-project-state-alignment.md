# 0050 — 当前项目事实与后续验收收口

- 状态：in_progress
- 创建日期：2026-08-14
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`

## Objective

把仓库中已经实现的 Skill、Shuge/Anna 获取路线、Provider 批次调度与当前真实验收阶段同步到计划、平台契约和架构文档；同时把 0029 从旧状态机指标改为与 semantic-first Skill 一致的决策质量 benchmark，避免后续开发继续依据过时事实。

## Non-goals

- 不修改 Search/Inspect/Download/Archive 的生产行为，除非只是修复明确的契约事实漂移。
- 不新增平台、Planner、Agent、状态机、digest、fallback 或并发框架。
- 不代替用户执行真实 Windows OpenClaw / 平台下载验收。
- 不执行 0041 网页抽取 benchmark。
- 不在本计划顺手删除 `retrieval/registry.py` 中仍存在的历史 compatibility 代码；若后续引用扫描证明为 dead code，单独建立小清理任务。

## Business invariants

- Skill 继续以需求理解、搜索角度、来源派发、query、结果判断为主；MCP 状态不重新变成模型思考协议。
- `prepare -> 用户明确确认 -> start`、exact Provider、no silent fallback 保持不变。
- Platform Registry 描述平台宽能力类别；Planner/Service 才描述具体 `direct_file` / exact provider 执行路线。两层事实不互相复制。
- 离线测试和 benchmark 不冒充真实 OpenClaw E2E。

## Expected change surface

- `.agent/plans/` 与 `archive/README.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `contracts/schemas/platform-registry.schema.json` 与直接 Registry 测试
- `0029-retrieval-benchmark-release-gate.md`

不改生产下载器、搜索适配器、数据库和公共 Tool。

## Acceptance criteria

- AC-01：0039、0043、0044、0049 从顶层移入 archive，归档索引与当前顶层计划准确；真实平台验收统一由 0028 跟踪。
- AC-02：Platform Registry 的 17 个 active platform 与 JSON Schema 数量约束一致；测试直接断言 schema 数量跟随 `EXPECTED_PLATFORM_IDS`。Shuge 的 exact `direct_file -> generic-direct` 只由 Planner/Provider 维护，不复制进宽能力 Registry。
- AC-03：CURRENT_ARCHITECTURE 反映 semantic-first Skill、Anna/Shuge ProviderSpec、Platform Registry 与 exact Provider 的职责边界，以及当前 exact Provider 批次调度。
- AC-04：0029 不再以 `SemanticReview/Gap/StopDecision` 或已废弃 authority/readiness/eligibility 链作为主要 benchmark 对象，改为需求还原、搜索角度、来源派发、query、结果判断与下一步决策质量；安全业务边界仍作为 critical gates。
- AC-05：只执行与改动匹配的契约/Registry/JSON/Markdown 静态或定向验证，不跑全量回归。

## Steps

- [x] completed：归档 0039/0043/0044/0049，并把真实平台验收统一收回 0028。
- [x] completed：修正 Platform Registry schema 16→17 的事实漂移，并补 schema/platform 数量一致性测试。
- [x] completed：同步 CURRENT_ARCHITECTURE 到 semantic-first Skill、当前 ProviderSpec 和 Provider batch 调度。
- [ ] in_progress：重写 0029 semantic-first benchmark 计划。
- [ ] pending：最小验证、归档 0050。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no
Actual user flow affected?: no
Actual user flow validated?: no — 仍由 0028 用户验收
Scope drift detected?: no
```

## Complexity exceptions

无。此次只删除漂移和同步事实，不引入新抽象或 source of truth。
