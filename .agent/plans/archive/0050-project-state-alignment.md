# 0050 — 当前项目事实与后续验收收口

- 状态：completed
- 创建日期：2026-08-14
- 完成日期：2026-08-14
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

## Acceptance criteria

- [x] AC-01：0039、0043、0044、0049 从顶层移入 archive，归档索引与当前顶层计划准确；真实平台验收统一由 0028 跟踪。
- [x] AC-02：Platform Registry 的 17 个 active platform 与 JSON Schema 数量约束一致；测试直接断言 schema 数量跟随 `EXPECTED_PLATFORM_IDS`。Shuge 的 exact `direct_file -> generic-direct` 只由 Planner/Provider 维护，不复制进宽能力 Registry。
- [x] AC-03：CURRENT_ARCHITECTURE 反映 semantic-first Skill、Anna/Shuge ProviderSpec、Platform Registry 与 exact Provider 的职责边界，以及当前 exact Provider 批次调度。
- [x] AC-04：0029 不再以 `SemanticReview/Gap/StopDecision` 或已废弃 authority/readiness/eligibility 链作为主要 benchmark 对象，改为需求还原、搜索角度、来源派发、query、结果判断与下一步决策质量；安全业务边界继续作为 hard gates。
- [x] AC-05：改动范围保持在计划/文档/Registry schema/直接测试，没有修改 Search/Inspect/Downloader/Service/数据库/公共 Tool。

## Steps

- [x] completed：归档 0039/0043/0044/0049，并把真实平台验收统一收回 0028。
- [x] completed：修正 Platform Registry schema 16→17 的事实漂移，并补 schema/platform 数量一致性测试。
- [x] completed：同步 CURRENT_ARCHITECTURE 到 semantic-first Skill、当前 ProviderSpec 和 Provider batch 调度。
- [x] completed：重写 0029 semantic-first benchmark 计划。
- [x] completed：完成 Connector 回读、提交范围 compare 和计划归档。

## Validation

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| branch/file readback | passed | 顶层计划、schema、架构与 0029 已在正式工作分支 | Python 运行时行为 |
| schema readback | passed | `platforms.minItems=maxItems=17` | 完整 Registry loader 测试执行 |
| compare `79817c0...92f2ac8` | passed | 前 5 个提交只改计划/文档/schema/直接测试，无生产业务实现 scope drift | 测试逻辑运行结果 |
| targeted pytest | not run | — | 当前执行环境无法解析 `github.com`，无法 clone 工作分支到本地运行 |
| GitHub status checks | none configured | 没有 CI 结果可冒充验证 | 任何运行时正确性 |
| real OpenClaw / platform E2E | not run | — | 继续由 0028 用户验收 |

本计划修改的唯一可执行契约变化是 schema 平台数量约束 16→17；对应测试已补防回归断言，但当前工具环境没有可执行仓库副本，因此不把该测试声明为已运行通过。

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
Actual user flow validated?: no — 继续由 0028 用户验收
Scope drift detected?: no
```

## Result

- 顶层计划收敛为真实未完成工作：0028、0029、0041。
- 0039/0043/0044/0049 已归档；平台工程完成与真实用户验收不再混为同一个状态。
- CURRENT_ARCHITECTURE 已反映 semantic-first Skill、17 平台 Registry、Anna/Shuge exact acquisition route、Provider batch 调度和真实验收边界。
- 0029 已改为 semantic decision quality benchmark：不再以旧状态机、固定 case 数或 digest 链驱动实现。
- 发现但未纳入本任务：`retrieval/registry.py` 仍保留历史 CapabilityDescriptor/Readiness compatibility 代码。后续只有在引用扫描确认无 active 调用后，才应单独清理。
