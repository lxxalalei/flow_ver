# 0056 — Download Job Subprocess Durability

- 状态：in_progress
- 创建日期：2026-08-16
- 范围：`mcp/education-resources` 下载 Job 的执行模型与状态存放

## Objective

让下载 Job 不随 MCP / 网关进程重启而丢失：下载逻辑移入脱离父进程生命周期的 worker 子进程执行，Job 状态以 `jobs/<job_id>/job.json` 文件为唯一权威，`resource_job_status` / `resource_job_cancel` / `resource_archive` 改为读写文件状态。消除「每次 sync 后 `openclaw gateway restart` 必杀在途下载」这一被运维循环放大的真实退化。

## Motivation

- 现状：`jobs.py` 是 46 行进程内 ThreadPoolExecutor；`_run_download_job`（service.py:426）在 MCP 进程线程里执行，网关/计划任务重启即丢进度；半截文件不可续（全库无 Range/resume）；重启后 `job_status` 只能报 `JOB_NOT_FOUND`。
- 「低频」假设被低估：`scripts/sync-to-openclaw.ps1` 的标准流程每次同步后重启网关，运维循环本身就会触发该场景。
- README 当前写明「Job 不做进程重启恢复」。本计划有意识地推翻这一条；0055 的其余减法边界全部不动。

## Non-goals

- 不做 HTTP Range 断点续传（见 Complexity exceptions）。
- 不恢复 SQLite / Flow / ResultSet / Selection / Plan / Token 等已删除状态机。
- 不持久化 `resource_id -> 候选` 映射；重启后重新搜索的口径不变。
- 不改 Search / Inspect / Browse Creator，不改 Provider / Downloader 的下载实现。
- 不新增通用 projection / canonical / readiness 框架。

## Business invariants

- 「用户明确表达下载意图后才调用 resource_download」的 SKILL 纪律不变。
- exact Provider 路由、真实 `AUTH_REQUIRED`、真实失败不隐藏、不静默换源不变。
- `jobs/<job_id>/job.json` 是 Job 状态唯一权威；进程内结构只是缓存或句柄。
- 取消必须真实生效（flag + 强杀兜底），不得假装取消；半截文件不得进入 `files`。
- archive 只消费 job.json 记录且真实存在的文件。
- job.json 写入原子（临时文件 + rename）；损坏的状态文件如实报错，不静默重建。

## Current architecture（2026-08-16）

- `download()`（service.py:323）：内存 job dict → `JobRunner.submit` → 线程内 `_run_download_job` → `_download_one`：fresh inspect → `planner.route` → `acquisition_router.acquire`（产物写 `jobs/<job_id>/`）。
- `job_status`（service.py:352）读内存字典；`job_cancel` 走 `threading.Event`；`archive` 读内存 files 后做磁盘移动。
- `jobs.py`：ThreadPoolExecutor + cancel events，无任何落盘。
- 公共 7 工具签名不变。

## Expected change surface

- 新增 `job_worker.py`：`python -m education_resource_mcp.job_worker <job_dir>`，读 `request.json`（job_id、resources 快照、preferred_container），执行现有 route/acquire 流程，原子更新 `job.json`，stdout/stderr 落 `worker.log`。
- `download()`：先写 `request.json` + 初始 `job.json`，再 detached spawn worker（`sys.executable`，`DETACHED_PROCESS`，stdio 只指向日志文件，无管道依赖父进程）。
- cancel：父进程写 `jobs/<job_id>/cancel.flag`；worker 侧用 `is_set()` 兼查 flag 文件的 `threading.Event` 子类替换原 Event，下载器 / planner / router 零改动；PID 已死则直接置 `cancelled`。
- 启动恢复：`ResourceService` init 扫 `jobs/*/job.json`；非终态且 PID 已死（ctypes OpenProcess 探活）→ 置 `interrupted`（新状态，公共输出如实暴露）；PID 存活 → 保持 `running`，父进程仅作为文件状态的读者。
- `job_status` / `archive` 改为读文件状态；archive 移动文件后回写 job.json 的最终路径。
- `jobs.py` 线程 runner 退役；并发上限沿用 `EDUCATION_RESOURCE_MCP_MAX_WORKERS` 语义（父进程按活跃 worker 计数控制）。
- 文档：README「最小内部状态」「MCP 重启」两节、SKILL.md §8 同步改口径。
- Windows 风险：若网关把 MCP 放进不允许 breakaway 的 Job Object，detached 子进程会被连坐；AC-05 用计划任务网关真实验证，必要时加 `CREATE_BREAKAWAY_FROM_JOB`。

## Acceptance criteria

- AC-01：真实大文件（SmartEdu 大 PDF / 视频）下载中执行 `openclaw gateway restart`，重启后 `resource_job_status(job_id)` 持续返回 running/progress，最终 `succeeded` 且文件完整可用。
- AC-02：MCP 被硬杀（模拟崩溃）后重启，非终态 job 显示 `interrupted` 并如实列出已完成子文件；终态 job 的 status / files / archive 仍可用（archive 跨重启可完成）。
- AC-03：`resource_job_cancel` 对运行中 worker 真实生效：当前资源中止、状态 `cancelled`、半截文件不进 `files`。
- AC-04：公共 7 工具签名与调用方式不变；job.json 等内部字段不进入公共输出。
- AC-05：计划任务网关 + 真实 `sync-to-openclaw.ps1` → restart 流程下复测 AC-01（覆盖 Job Object 连坐风险）。
- AC-06：定向测试通过：worker 往返（fake provider）、启动恢复扫描、cancel flag、跨「重启」（新 `ResourceService` 挂同一 data_dir）的 status / archive。

## Complexity exceptions

- 不引入任务队列 / 调度框架；一个 worker 模块 + 状态文件 + 恢复扫描即全部新增。
- Range 断点续传明确不做：抖音 / B站分段流恢复语义复杂；本计划先用「进程存活」消掉主退化。`interrupted` job 重下从 0 开始的现状如实保留，未来如需续传另立计划。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes（无 Range 续传、无 SQLite/Flow、resource_id 仍进程内）
Business invariants still true?: yes（job.json 唯一权威；取消 flag+强杀；archive 只消费 job.json 记录文件）
New abstraction introduced?: no（一个 worker 模块 + 状态文件 + 恢复扫描）
New source of truth introduced?: no（状态文件即唯一真相，进程内只剩 resource 句柄）
Fallback added?: cancel 对不响应 flag 的 worker 强杀兜底；spawn breakaway 被拒时退化为普通 detached
Data truncation added?: no
Unrelated files changed?: README/SKILL 口径更新与本计划直接相关
Actual user flow affected?: download/job_status/job_cancel/archive 行为不变，签名不变；新增 interrupted 状态语义
Actual user flow validated?: 进程级已验（AC-01/AC-02）；网关级 AC-05 待部署后执行
Scope drift detected?: no
```

## 实施结果

### 新增模块

- `job_state.py`：job.json 原子读写（tmp+replace）、request.json 读写、job_id 路径校验（防目录穿越）、`process_alive`（Windows ctypes OpenProcess / POSIX kill 0）、`terminate_process` 强杀兜底、`FileCancelEvent`（`is_set()` 兼查 cancel.flag，下载链路零改动接入）、`SPAWN_GRACE_SECONDS=30` 启动宽限窗。
- `job_worker.py`：`python -m education_resource_mcp.job_worker <job_dir>`；读 request.json 资源快照 → 逐资源执行既有 inspect→route→acquire 流程 → 每资源后原子更新 job.json → 终态写入；未捕获异常落 `WORKER_CRASHED` failure，绝不停留在 running。
- `jobs.py`：原 46 行线程 runner 退役，改为 `JobSpawner`（≤ max_workers 个 detached worker 并发，超出排队，语义对齐旧 executor）+ `spawn_worker`（DETACHED_PROCESS、stdio 只指向 worker.log、优先 CREATE_BREAKAWAY_FROM_JOB，被拒则降级普通 detached）。

### service.py 改造

- `download()`：写 request.json + 初始 job.json（queued）→ 经 spawner detached spawn；cancel.flag 已存在则直接置 cancelled 不启动 worker。
- `job_status()`：读 job.json + `_reconcile`（非终态且 pid 已死且超过宽限窗 → 如实标 `interrupted`；同进程队列内任务不受影响）。
- `job_cancel()`：写 cancel.flag；pid 活 → 返回 cancelling（worker 在检查点自行终止）；重复 cancel → taskkill 强杀兜底并置 cancelled；无活 worker → 直接置 cancelled。
- `archive()`：读文件状态，移动后回写 job.json 最终路径——归档跨 MCP 重启可用。
- `_recover_interrupted_jobs()`：init 扫描 jobs/*/job.json。
- `_download_one` 更名 `download_resource`（worker 复用，无行为变化）。

### 文档

README「最小内部状态与 Job 持久化」「目录重点」、SKILL.md §8「MCP 重启」、server instructions 全部改为：resource_id 进程内、Job 文件态跨重启存活、interrupted 如实暴露。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| `tests/test_job_durability.py` 7 项 | 全过 | FileCancelEvent；恢复扫描（孤儿→interrupted、存活 pid 不动、终态不动）；queued 无 worker 的 cancel；重复 cancel 强杀顽固 worker 并置 cancelled；malformed job_id 拒绝；本地 HTTP 真实 worker 往返：spawn 后销毁父 service，新实例继续读到 succeeded + 字节级校验，第三个实例完成跨重启 archive | — |
| 全量 pytest | 51 失败 = 分支既有基线（改动前后同命令两次统计，一致），零新回归 | 既有 51 个失败是 0055 减法后的陈旧 fixture（引用已删除的 Settings.database_path/evidence 等），非本计划引入 | — |
| AC-01 进程级 | 通过：本地 32MB 慢速流（~75s）下载中 taskkill 父进程 → worker 存活 → 新 ResourceService 读到 succeeded、文件 33554432 字节完整 | detached worker 脱离父进程生命周期；文件状态跨进程可读 | 网关计划任务环境的 Job Object 行为（归 AC-05） |
| AC-02 进程级 | 通过：下载中 taskkill worker → 新实例 status=`interrupted`、completed=0、files 空、无伪造失败记录 | 崩溃语义诚实 | — |
| AC-03 | 单测覆盖（重复 cancel 强杀 + cancelled 终态） | flag 与强杀兜底 | 真平台下载中途取消 |
| AC-04 | 工具签名未动；job.json/pid 不进公共输出 | 公共表面不变 | — |
| AC-05 网关级 | pending：待 sync 部署后在计划任务网关 + 真实 restart 流程下复测 AC-01 | — | — |

验收脚本：`%TEMP%\0056-accept\accept.py`（serve/parent/status 三模式，本地慢速 32MB 流）。

## 结果

0056 代码与定向测试完成，AC-01/AC-02 进程级验收通过，公共表面不变、全量测试零回归。剩余动作：sync 部署后执行 AC-05（计划任务网关真实 restart 复测），以及后续把 51 个陈旧 fixture 基线单独立计划清理或删除。
