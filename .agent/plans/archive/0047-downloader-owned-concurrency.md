# 0047 — Downloader-owned acquisition concurrency

## Goal（必填）

用户/系统能够：让每个已确认 Download Job 的所有 JobItem 直接进入各自绑定的获取实现，由 Downloader / Provider 实现自行决定平台内部并发、串行或限流；`ResourceService` 不再读取 Provider 并发声明，也不再对 JobItem 施加统一 worker 上限。

## Non-goals（必填）

- 不修改 `JobRunner` 对同时运行 Job 数量的进程资源控制；它不决定单个 Downloader 的内部并发。
- 不为具体平台猜测或新增并发数、限流参数、重试策略。
- 不修改 MCP Tool、数据库 Schema、Plan/Job/Outcome/Asset 契约。
- 不处理当前工作区已有的 Windows stdio E2E 未提交修改和 probe 文件。

## Acceptance Criteria（必填）

### AC-01 — Service 不限制同 Provider 并发

```text
Given: 一个 Job 含多个绑定同一 exact Provider 的 JobItem
When: ResourceService 执行该 Job
Then: Service 不读取 max_concurrent_items，也不因 Provider 相同而串行这些调用。
```

### AC-02 — Service 不施加统一 JobItem worker 上限

```text
Given: settings.max_workers 小于 JobItem 数量
When: ResourceService 执行该 Job
Then: settings.max_workers 不限制 JobItem 进入获取实现；全部 JobItem 都被提交，具体并发由实现自行控制。
```

### AC-03 — Downloader 可自行限制

```text
Given: 一个 Downloader / Provider 实现内部使用自己的锁、semaphore 或 limiter
When: Service 并发调用它
Then: 实现自己的限制生效，Service 不读取或复制该限制。
```

### AC-04 — 业务语义不退化

```text
Given: 并发资源发生普通失败、用户取消或 Job 级 fatal error
When: Job 收口
Then: 现有 partial success、取消、fatal、进度、Outcome 和 Asset 语义保持不变。
```

## Business Invariants

- 每个 JobItem 仍执行 Plan 已绑定的 exact `(provider_id, provider_version, strategy, scope, representation)`。
- 不 silent fallback，不重新选 Provider。
- Downloader/Provider 拥有平台内部并发与资源隔离责任。
- Service 继续拥有 Job 生命周期、取消、进度和最终状态。

## Expected Change Surface

Likely to change:

- `mcp/education-resources/src/education_resource_mcp/service.py`
- `mcp/education-resources/tests/test_download_item_concurrency.py`
- `docs/CURRENT_ARCHITECTURE.md`
- `.agent/plans/0045-download-item-concurrency.md`（记录旧设计被替代）

Should not change:

- 具体平台 Downloader 的 API 和平台并发参数
- MCP Tool Schema、数据库 migration、搜索/Inspect/Archive
- 用户现有未提交的 Windows E2E 调试文件

## Validation Plan

Smallest useful validation:

- `pytest -q tests/test_download_item_concurrency.py`
- 直接相关 acquisition/service 测试
- active package AST/compile 检查
- `git diff --check`

Full regression required?

- No。改动局限于 JobItem 调度，不涉及搜索、Inspect、Archive 或公共契约。

## Steps

- [x] completed：冻结 Goal、Non-goals、Acceptance Criteria 和最小修改面。
- [x] completed：移除 Service 的 Provider 级和统一 JobItem 并发限制。
- [x] completed：更新窄测试，证明 Service 放行且实现可自行限流。
- [x] completed：同步架构文档和旧计划替代关系。
- [x] completed：执行定向验证、审查 diff 并归档计划。

## Completion Record

- [x] Level 1 — 小改动：直接受影响单元测试、语法/静态检查
- [x] Level 2 — 子系统改动：受影响模块测试和直接相关 integration
- [x] 未执行真实 Agent/用户流程验证

Not validated:

- 未运行全量 pytest、stdio E2E、真实 OpenClaw/平台下载。

Known remaining risks:

- Service 不再限制 JobItem 数量；超大 Job 会按 Item 数创建执行线程，这是本次明确要求的职责边界。
- 当前会共享 Job 输出路径的内置 Downloader/Materializer 在自身实例内选择并发 1；后续只有在各自完成 item 路径隔离和平台验证后才能独立放宽。

## Result

- `ResourceService` 不再读取 `max_concurrent_items` 或使用 `settings.max_workers` 限制单 Job 的 JobItem。
- 所有 JobItem 直接进入 exact Provider；fatal 时共享事件会唤醒实现内部等待。
- 内置 Downloader/WebMaterializer 自己拥有可取消互斥，跨 Job 生效。
- 未新增公共契约、数据库状态、fallback 或第二数据真实来源。
