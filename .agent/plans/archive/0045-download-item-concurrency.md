# 0045 Download Job 资源并发执行

> 2026-08-14：本计划记录的“Service 执行 Provider 声明并发上限”设计已被 `0047-downloader-owned-concurrency.md` 替代。保留本文只用于历史审计；当前事实是 Service 不施加 JobItem/Provider 并发限制，获取实现内部拥有并发策略。

- 状态：completed（历史设计；并发所有权已由 0047 替代）
- 创建日期：2026-08-13
- 完成日期：2026-08-14
- 范围：`mcp/education-resources` 下载 Job 执行层

## Objective

一个已确认的 Download Job 包含多个资源时，资源项可以并发进入各自已绑定的 exact Provider；不同平台不再被单个 `for item in job_items` 强制串行。同一 exact Provider 的资源并发数由对应 Downloader 声明自己的 `max_concurrent_items`，Service 只负责执行该声明并提供全局资源执行上限，不维护平台并发表。

## Non-goals

- 不改变 Search / Presentation / Selection / Inspect / Prepare / Confirm 流程。
- 不新增平台级并发配置表、调度器服务、队列系统或新的 Provider 抽象。
- 不在本任务中为 Bilibili、Douyin 等 Downloader 预设未经并发安全验证的并发数。
- 不改变现有 `ACQUISITION_ABORT_CODES`、普通 item failure、Job cancellation 和 Asset/Bundle 业务语义。
- 不处理 0041 网页抽取或其他平台接入问题。

## Business invariants

- Job 仍由 `JobRunner` 异步启动；本任务只改变一个 Job 内部的资源执行方式。
- 每个 JobItem 仍使用 Plan 已绑定的 `(provider_id, provider_version, strategy, scope, representation)`，不重新选路。
- 普通资源失败只完成该资源的失败 Outcome，不阻止其他资源完成。
- Job 级 fatal error 仍按现有规则结束 Job；取消必须以持久化 `cancelling` 状态为权威，process-local event 只用于唤醒。
- Service 提供总的资源执行上限，并执行 Downloader 自己声明的同 Provider 并发能力；未声明时默认 `1`。
- Downloader 若声明 `max_concurrent_items > 1`，必须先保证自身临时文件、输出文件、Session/API 调用可并发安全。
- 不静默丢弃任何 JobItem。

## Current architecture

- `JobRunner(max_workers)` 控制同时运行的 Job 数。
- `ResourceService._run_download_job()` 当前对 `job_items` 使用单一串行 `for` 循环。
- `AcquisitionRouter.acquire(request)` 是单资源同步调用。
- 当前 Generic Downloader 固定使用 `jobs/<job>/payload.part`，Bilibili/Douyin 也存在按标题生成临时/输出文件名的行为，因此不能默认放开同 Provider 多资源并发。
- Store 的 Job/Outcome/Bundle 写入均通过独立 SQLite 事务完成；Job progress 更新已有单调写保护。

## Expected change surface

Likely to change:

- `mcp/education-resources/src/education_resource_mcp/service.py`
- 一个直接覆盖 JobItem 并发行为的窄测试文件
- 必要时同步 `docs/CURRENT_ARCHITECTURE.md` 的执行说明

Should not change:

- Downloader 公共 `download(...)` 签名
- Acquisition Planner / Router 路由规则
- 数据库 Schema / migration
- MCP Tool Schema
- 搜索并发实现

## Acceptance criteria

### AC-01 跨 Provider 不再串行

Given: 一个 Job 有至少两个绑定到不同 exact Provider 的 JobItem，两个 Provider 都会阻塞直到对方开始
When: Job 启动
Then: 两个 Provider 都能在任一方结束前进入 `download/acquire`，证明 Service 不再按列表顺序串行。

### AC-02 Provider 自己拥有同平台并发能力

Given: 一个 Job 有多个绑定到同一 exact Provider 的 JobItem
When: Downloader 未声明 `max_concurrent_items`
Then: Service 默认最多同时进入该 Provider 1 个资源，避免现有临时文件/输出文件竞争。

Given: Downloader 明确声明 `max_concurrent_items = N` 且自身实现已并发安全
When: 同一 Job 有多个该 Provider 的 JobItem
Then: Service 最多允许 N 个资源同时进入该 Provider，不另外维护平台并发配置。

### AC-03 不因同 Provider 排队饿死其他 Provider

Given: JobItem 列表前面有多个同 Provider 资源，后面还有其他 Provider 资源
When: 全局 worker 数有限
Then: 等待该 Provider 并发槽的资源不占用实际执行 worker；其他 Provider 仍能及时进入执行。

### AC-04 失败与成功可独立完成

Given: 并发资源中一个返回普通 `DOWNLOAD_FAILED`，另一个成功
When: Job 执行结束
Then: 成功资源仍产生 ready Asset/成功 Outcome，失败资源产生失败 Outcome，Job 保持现有 partial-success 终态语义。

### AC-05 取消与 fatal 语义不退化

Given: Job 正在并发执行多个资源
When: 用户取消，或某资源触发现有 Job 级 fatal error
Then: 不再启动可取消的排队工作；运行中的 Provider 共享原 Job cancel event；最终状态仍由现有持久化 Job 状态规则决定。

## Validation scope

- Level 1/2：新增并发行为单元/Service 级测试 + `test_acquisition_service.py` / 直接相关 acquisition tests。
- 不跑全量测试；本 diff 不涉及 Search、Archive、Session 或第三方平台实现。

## 步骤

- [x] completed：读取最新 HEAD、`AGENTS.md` 和当前下载执行链，确认最新修改未实现 JobItem 并发。
- [ ] in_progress：实现 Job 内资源受限并发，同时保持现有 item/Job failure 与 cancellation 语义。
- [ ] pending：新增窄回归，覆盖跨 Provider、Provider 默认串行/显式放宽、普通失败继续执行和取消/fatal。
- [ ] pending：执行最小充分验证并静态复核 diff。
- [ ] pending：完成后归档本计划并同步必要文档。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: pending implementation
New abstraction introduced?: no planned
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no planned
Actual user flow affected?: download execution only
Actual user flow validated?: pending
Scope drift detected?: no
```
