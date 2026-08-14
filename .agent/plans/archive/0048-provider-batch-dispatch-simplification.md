# 0048 — Provider batch dispatch simplification

- 状态：completed
- 创建日期：2026-08-14
- 完成日期：2026-08-14
- 范围：Download Job 的 Service 调度、相关窄测试与架构说明

## Objective

- 一个 Download Job 不再按 JobItem 创建线程；ResourceService 按已绑定的 exact Provider 分组形成批次，几百个同平台资源不会演变成几百个 Service worker。

## Non-goals

- 本阶段不删除 `job_items`、`execution_outcomes` 或数据库 migration；它们继续作为逐资源结果和恢复记录。
- 不改变 `prepare -> 用户确认 -> start`、Job/Asset/Archive 公共契约。
- 不猜测或统一配置各平台并发数；当前单资源 Provider 接口先以批次内顺序执行保持行为，后续平台可在自己的批次入口内放宽。
- 不修改搜索、Inspect、Archive，也不触碰工作区已有 Windows stdio E2E 调试文件。

## Business invariants

- 每项仍执行 Plan 绑定的 exact `(provider_id, provider_version, strategy, scope, representation)`，不 silent fallback。
- 普通单项失败不阻塞同批其他项；取消与 Job 级 fatal 继续收口为既有状态。
- Service 保持 Job 生命周期、进度、Outcome、Bundle 和 Asset 的权威。

## Current architecture

- 当前 `_run_download_job()` 使用 `ThreadPoolExecutor(max_workers=total_items)`，一个 JobItem 对应一个 future/thread 配额。
- 当前内置 Downloader 为避免共享 Job 路径冲突又增加实例锁，形成“Service 大量线程 + Downloader 锁等待”的反模式。
- 当前 Router/Provider 公共内部接口仍是单资源 `acquire/download`；本阶段不引入新的公共 Tool 或数据库状态。

## Expected change surface

Likely to change:

- `mcp/education-resources/src/education_resource_mcp/service.py`
- `mcp/education-resources/tests/test_download_item_concurrency.py`
- `docs/CURRENT_ARCHITECTURE.md`
- `mcp/education-resources/README.md`
- 撤销仅为旧“一 Item 一线程”模型增加的 Downloader 实例锁改动

Should not change:

- MCP contracts、storage migrations、搜索/Inspect/Archive
- Windows stdio E2E 调试文件

## Acceptance criteria

- AC-01：500 个同一 exact Provider 的 JobItem 只使用一个 Provider 批次 worker，不创建 500 个 Service worker。
- AC-02：不同 exact Provider 的批次可以独立并行，`settings.max_workers` 不作为平台下载并发配置。
- AC-03：普通失败后同 Provider 后续项继续；fatal/cancel 保持既有 Job 收口语义。
- AC-04：所有已处理项继续更新进度和逐项 Outcome/Asset 结果，不静默丢项。

## Complexity exceptions

默认：无。此次删除逐 Item 调度复杂度，不新增 source of truth、公共状态机、fallback 或通用框架。

## 步骤

- [x] completed：调查当前一 Item 一线程与 Downloader 实例锁实现。
- [x] completed：实现按 exact Provider 分组的批次派发。
- [x] completed：更新窄测试和架构文档。
- [x] completed：执行 Level 2 定向验证并记录结果。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted unit | 5 passed | Provider 分组、500 项规模、失败/取消/fatal/进度 | 真实平台吞吐 |
| related service/acquisition tests | 30 passed | 直接相关 Service、Acquisition、Outcome/Asset 回归 | 全仓功能 |
| compile + diff check | passed | active package 语法和补丁格式 | 运行时平台行为 |
| real Agent/user flow | not run | | 真实 OpenClaw 用户链路 |

## 结果

- `_run_download_job()` 按 exact `(provider_id, provider_version)` 分组；单平台批次直接在 Job worker 内执行，多平台时每个平台最多一个批次 worker。
- 删除 `max_workers=total_items` 的一 JobItem 一 worker 模型，也不再读取 Provider 的统一并发声明。
- 撤销为旧模型增加的 Downloader 实例锁；逐项 Outcome/Asset 记录和公共契约不变。
- Level 2 定向验证通过；未运行全量回归、stdio E2E、真实 OpenClaw 或真实平台批量下载。
- 剩余风险：当前 Provider 内部仍是单资源接口，同平台批次目前顺序执行；提高同平台吞吐需要后续在具体 Downloader 内增加真正的批次执行和 item 目录隔离。
