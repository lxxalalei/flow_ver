# 资源能力公共面收敛与平台对象化重构

- 状态：in_progress
- 创建日期：2026-08-21
- 完成日期：未完成
- 范围：`mcp/education-resources/`、`skills/`、`TOOLS.md`、`docs/CURRENT_ARCHITECTURE.md`

## Objective

把当前按平台/模式暴露的资源能力收敛成模型可稳定组合的通用能力：`Search / Expand / Inspect / Download`。平台内部保留真实机械细节，模型只接触有语义意义的资源对象与通用动作。

## Non-goals

- 不恢复 Flow / ResultSet / Selection / Plan / authority / digest 等持久工作流状态。
- 不增加新的平台级 MCP Tool。
- 不实现用户未要求的时间范围搜索、复杂筛选、排序、推荐或评分能力。
- 不为尚未确认真实接口的平台能力编造 API；未确认的能力显式保留为暂不支持。
- 不改造 Archive、Session、Web Materializer 的内部实现。

## Business invariants

- Agent/Skill 负责理解用户目标、语义筛选、是否继续、用户选择；MCP 只负责事实和执行。
- 完整枚举不因聊天上下文大小被截断；大结果继续落 JSONL + Job，由分页读取控制上下文规模。
- Search/Expand 只发现/枚举候选，不自动授权下载。
- 用户给出的已知资源 URL 可以直接导入/识别后 Inspect/Download，不要求先 Search。
- 容器资源的 Expand 是结构展开，不做语义筛选。
- 叶子资源下载必须精确，不偷偷替换成“第一项”等 fallback。

## Current architecture

- Public MCP 当前同时存在 `resource_browse_creator`、`resource_batch_collect(mode=creator_full|time_range_search|catalog_expand|collection_expand)`，把平台结构和模式泄漏给模型。
- `batch.py` 已有稳定的 Job + `results.jsonl` 完整枚举承载机制，可以复用。
- Bilibili / Douyin 已有 creator 枚举；Bilibili 已有 collection 枚举。
- SmartEdu 当前通过 `catalog_expand + specs` 暴露教材展开，Search 还暴露 `tabs`。
- Ximalaya 当前只搜 album；Downloader 对 album 会退化为第一 track，需要移除该行为并补 album 展开。
- Anna's Archive 实际 Search/Download 已由 LibGen mirror + MD5 驱动，应统一改名为 `libgen`。

## Expected change surface

Likely to change:
- `server.py`：公共 Tool schema。
- `service.py`：URL 识别、Expand Job 创建、Job 结果读取、下载来源命名。
- `batch.py`：从 mode 分发改为基于目标 Resource 的 expand worker。
- 平台 adapters：Bilibili / Douyin / Ximalaya / SmartEdu / Zjer 的资源对象识别与 expand；LibGen 命名。
- `inspection_registry.py`、search provider 注册、相关 tests/docs。

Should not change:
- Acquisition Router/Planner 的整体结构。
- SessionStore 语义。
- Archive 文件移动逻辑。
- Generic Web Materializer。

## Acceptance criteria

- AC-01：公共资源 Tool 不再暴露 `creator_full`、`time_range_search`、`catalog_expand`、`collection_expand`、`start_day/end_day/specs/tabs`。
- AC-02：存在 `resource_expand`，接受已知 resource handle 或支持的 URL；完整枚举以 Job 承载。
- AC-03：存在通用 Job 结果分页读取能力，不再使用 `resource_batch_read` 作为业务术语。
- AC-04：Bilibili：`creator -> video[]`、`collection -> video[]`；video 可直接下载。
- AC-05：Douyin：`creator -> video[]`；video 可直接下载；collection 只有在真实接口已确认后才实现，否则显式不支持。
- AC-06：Ximalaya：`creator -> album[]`、`album -> track[]`、`track -> audio`；album 不再偷偷下载第一 track。
- AC-07：SmartEdu：公共面不再暴露 tabs/specs；教材/课程对象通过 Resource/URL 展开，内部平台 tag/API 细节不暴露给模型。
- AC-08：Zjer：课程对象可展开为 video[]；video 可精确下载。
- AC-09：Anna's Archive active 平台标识统一为 `libgen`，Search/Inspect/Download 继续以 MD5 + LibGen mirrors 为事实路径，不保留 Anna 域名作为下载候选。
- AC-10：相关 targeted tests 和 MCP tool-schema probe 通过；未执行真实 OpenClaw 用户链路时明确记录未验证。

## Complexity exceptions

无。复用现有 Adapter、Job、JSONL、Inspector、Downloader；不新增通用容器框架、Registry 或持久状态模型。

## 步骤

- [x] completed：核对当前 Tool schema、Service、Batch 与主要平台实现。
- [ ] in_progress：重构公共 Tool 与 Service/Batch 为通用 Expand/Job Read。
- [ ] pending：补齐/调整主要平台资源对象与 Expand 行为。
- [ ] pending：Anna's Archive -> LibGen active 命名迁移。
- [ ] pending：更新 Skill/TOOLS/当前架构文档。
- [ ] pending：运行最小充分测试与 Tool schema probe，修复回归。
- [ ] pending：完成 checkpoint、结果记录并归档计划。

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
Actual user flow affected?: yes, public MCP capability surface
Actual user flow validated?: not yet
Scope drift detected?: no
```

## Decision log

### Decision 001 — 用 Expand 取代平台 mode

- Context：当前 `resource_batch_collect` 让模型选择平台内部 mode，参数互斥且不断膨胀。
- Options considered：继续增加 mode；为每个平台新增 Tool；统一 `resource_expand`。
- Chosen option：统一 `resource_expand`，平台 Adapter 根据资源事实决定机械分支。
- Why：模型只需要表达“展开这个资源”；season/series、分页、tag、API 等都属于平台机械事实。
- Complexity introduced：无新持久模型，复用现有 Job/JSONL。

### Decision 002 — 数据完整性与上下文分页分离

- Context：creator/album/textbook 展开可能产生大量结果。
- Chosen option：Expand 始终允许完整枚举落盘，`resource_job_read` 只控制模型每次读取的页大小。
- Why：避免把 UI/上下文限制变成业务数据截断。

### Decision 003 — 平台资源视图

- Bilibili：creator / collection / video。
- Douyin：creator / collection / video（collection 仅真实接口确认后实现）。
- Ximalaya：creator / album / track。
- SmartEdu：textbook / course / file（课程可以自然交付多个文件）。
- Zjer：course / video。
- LibGen：book。
- Generic Web：webpage。
- Generic Direct：file。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted unit | pending | 受影响 adapter/service 行为 | real Agent/user flow |
| MCP tool schema probe | pending | 模型看到的 Tool 已收敛 | 平台线上接口长期稳定 |
| real platform smoke | pending/按可用环境执行 | 真实平台当前路径 | 全平台全面回归 |
| real Agent/user flow | not run yet | - | - |
| full regression | not planned by default | - | - |

## 结果

未完成。