# 0037 — 获取状态链简化

- 状态：in_progress
- 创建日期：2026-08-11
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`
- 接替关系：0036 已 superseded 并移入 archive；平台恢复目标后续继续，但不得恢复旧 Capability Authority 链

## Goal

把获取链从“权威证明系统”收敛为资源获取业务系统：

```text
Selection
  -> Resolution / Representation
  -> AcquisitionPlan
  -> 用户确认
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / Bundle
  -> Archive
```

Capability Descriptor、Readiness Snapshot、Eligibility Decision 不再作为运行时业务状态；Plan / Job / Outcome 不依赖多层 SHA-256 binding digest。

## Product decisions

### 保留

- `Resolution / Representation`；
- `AcquisitionPlan`；
- `Job` 与按资源的 `JobItem`；
- `Outcome`；
- `source_fingerprint`，只作资源身份和 Resolution cache key；
- exact Provider routing；
- Selection/Plan 版本、用户确认、幂等、取消；
- SSRF、逐跳重定向、受控目录、真实格式与访问控制边界；
- Asset / Bundle / Archive 关系。

### 删除

- Capability Descriptor binding；
- Deployment Readiness Snapshot 持久状态；
- Eligibility Decision 持久状态；
- `authority_digest`；
- `plan_binding_digest` / `binding_digest`；
- `execution_binding_digest`；
- `outcome_digest`；
- Provider 请求中仅用于证明上述链条的 descriptor/readiness/eligibility 字段；
- 独立 capability descriptor / deployment readiness / eligibility current contract 文件。

### 降级为运行时逻辑

- Capability → 小型 `ProviderSpec`；
- Readiness → exact Provider 当前是否注册、是否支持 strategy/scope；
- Eligibility → Prepare/Start 根据当前 Representation 直接允许或阻断，不生成实体 ID。

## Business invariants

1. Agent 不能提交任意本地路径、下载 URL 或 Provider 来替代服务端计划。
2. Prepare 只能基于当前 Selection 和已 Inspect 的 Resolution。
3. 有显式 Representation evidence 时，Prepare / Start 都要求其当前有效。
4. Start 重新读取当前 Resolution，确认 representation 仍存在、核心语义未漂移。
5. Start 只执行 Plan 保存的 exact Provider route；Router 不 silent fallback。
6. JobItem 是 PlanItem 在 Start 校验后的服务端快照，不额外生成执行凭证。
7. Outcome 只描述实际执行事实；Archive 根据 JobItem / Outcome / Bundle / Asset 关系判断。
8. 正文网页允许 `webpage + primary + primary_resource -> web_materialize`；landing page 保持 landing。
9. 文件 SHA-256 / byte_size 可作 Asset 元数据与去重信息，但 0030 已删除的通用大小/哈希验收门禁不得恢复。

## Current architecture checkpoint

当前 Active MCP 获取入口：

```text
server.py
  -> simple_service.ResourceService
     -> AcquisitionPlanner / ProviderSpec
     -> simple_storage.Store (migration 9)
     -> simplified AcquisitionRequest
     -> exact AcquisitionRouter
     -> Provider
```

`simple_service` / `simple_storage` 仍复用旧 Service/Store 中成熟的 Search、Inspect、通用 Job 生命周期、Asset/Bundle 和 Archive 辅助能力，但 **Active acquisition 的 Prepare / Start / Runner / JobStatus / PlanItem / JobItem / Outcome 已不再依赖旧 authority 状态链**。

旧 `capability.py` 的大型实现已删除，仅保留 fail-fast shim 防止旧获取入口被误用。当前轻量 `AcquisitionRequest` 是独立 DTO，不继承旧 Request，也没有 capability/readiness/eligibility/digest slot。

## Implemented

### Phase A — Active path cutover

- [x] 新增 `AcquisitionPlanner` 与轻量 `ProviderSpec`。
- [x] generic document primary → direct Provider。
- [x] generic primary webpage → web materializer。
- [x] generic landing webpage → web materializer。
- [x] SmartEdu document primary → exact SmartEdu Provider（仅当前部署实际注册时可用）。
- [x] Active `ResourceService.__init__` 不再创建 `CapabilityCoordinator`。
- [x] `download_prepare` 生成简单 PlanItem。
- [x] `download_start` 删除 `authority_digest`，重验证 Selection / Plan / Resolution / Representation / Provider route。
- [x] `_run_download_job` 直接消费 `job_items`，不再构造 capability/readiness/eligibility 兼容字段。
- [x] `job_status` 读取 `job_items` / `execution_outcomes`。
- [x] `AcquisitionRequest` 改为只含执行业务事实的独立 DTO。
- [x] `WebMaterializer` 不再要求旧 Request concrete class。
- [x] Router 保持 exact routing；Provider 失败不 silent fallback。

### Phase B — Persistence cleanup

migration 8 创建并 backfill：

```text
acquisition_plan_items
job_items
execution_outcomes
```

migration 9 在 backfill 完成后物理删除旧 acquisition authority 表：

```text
job_execution_items
acquisition_outcomes
download_plan_items
eligibility_decisions
capability_readiness_snapshots
```

- [x] 新 PlanItem 不含 capability/readiness/eligibility/binding digest。
- [x] JobItem 只保存执行快照与 `revalidated_at`。
- [x] 新 Outcome 不含 plan/execution/outcome digest。
- [x] v7 Plan/Job/Outcome 先降维 backfill，再删除旧表。
- [x] Archive 关系校验使用 JobItem / Outcome / Bundle / Asset graph。
- [x] Active Job success/failure/cancellation recovery 使用新 Outcome 表。

说明：`storage.py` 仍保留历史 migration 代码，使旧数据库可以升级；它不是 migration 9 后的 Active acquisition source of truth。

### Phase C — Public contract / Agent / docs

- [x] `resource_download_start` 删除 `authority_digest`。
- [x] PlanItem Schema 删除 capability / eligibility / binding digest 组。
- [x] FlowStatus current Plan/Job 不暴露 `authority_digest`。
- [x] JobStatus Outcome projection 删除 plan/execution/outcome digest 与 capability/readiness/eligibility 结构。
- [x] `actual-outcome.schema.json` 简化。
- [x] Tool catalog 为 `1.6.0`，Tool 数仍为 13。
- [x] Skill 与 acquisition reference 使用 `Representation -> Plan -> JobItem -> exact Provider -> Outcome`。
- [x] 删除 current contract 中独立的：
  - `contracts/capabilities/capability-descriptors.json`；
  - `capability-descriptor.schema.json`；
  - `capability-descriptors.schema.json`；
  - `deployment-readiness.schema.json`；
  - `eligibility-decision.schema.json`。
- [x] `contracts/platforms/README.md` 改为 ProviderSpec / Representation / exact Provider 路由说明。

### Phase D — Tests

已删除只验证旧 authority 实现的专项测试；平台 Search/Inspect Adapter 注册类测试继续保留。

`test_mcp_stdio.py` 保留并迁移为新契约，因为它验证真实业务控制面，而不是内部实现细节。

## Validation

### Milestone 1 — simplified state

已通过：

- Python 3.12 package install；
- active package `compileall`；
- current JSON contract parse；
- `test_acquisition_simplification_0037.py`；
- Active Service 在 CapabilityCoordinator 退役后正常初始化。

### Milestone 2 — first full MCP round trip

GitHub Actions run `31514845872` 已通过：

```text
13 Tool discovery
-> Flow
-> Search
-> Inspect
-> Present
-> Select
-> Prepare
-> Start
-> Job
-> Archive
-> Library Search
```

### Milestone 3 — compatibility cleanup / migration 9

GitHub Actions run `31517757764` 已通过，且只有全部检查成功后才提交 `ff2a7044fa26a48491e5c3dac9fed5ee7ffd380d`。

| Validation | Result | What it proves |
| --- | --- | --- |
| patch/cutover application | pass | 第二阶段修改可完整应用 |
| current package install | pass | 当前依赖和包结构可安装 |
| `compileall` | pass | Active Python 代码可编译 |
| parse all current contract JSON | pass | 删除旧 contract 后引用面无 JSON 语法断裂 |
| `test_acquisition_simplification_0037.py` | 7/7 pass | standalone Request、migration 9、旧表删除、Planner/contract 关键行为 |
| `test_mcp_stdio.py` | 2/2 pass | 简化后仍能完成完整离线 MCP 业务闭环 |
| obsolete contract checks | pass | 五个旧 capability/readiness/eligibility current contract artifacts 已物理删除 |

验证过程中发现并修正了一个真实兼容问题：`WebMaterializer` 曾通过 `isinstance` 强制要求旧 `AcquisitionRequest` concrete class。该检查已删除；Router 负责请求边界，Provider 只消费执行事实。

临时 GitHub Actions workflow 已随成功 cutover 提交一起删除，不会在后续小改动中重复运行。

## Remaining work

第二阶段兼容清理已经完成。0037 目前只剩真实用户链验收：

1. 在实际 OpenClaw 环境重新部署当前 MCP/Skill；
2. 用 generic 正文网页完成真实：
   `Search -> Inspect -> Present -> Select -> Prepare -> 用户确认 -> Start -> Job -> Archive -> Recover`；
3. 核对正文网页确实走 `primary_resource + web_materialize`，而非 landing page；
4. 成功后关闭 0037，回到 0028 的真实平台 E2E / Provider 恢复。

不在 0037 中继续为了清理名称而重写成熟 Search/Inspect/Asset/Archive 基座；只有真实调用仍能触发旧 authority 行为时才继续删除对应代码。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes; offline full round trip passed after physical cleanup
New abstraction introduced?: no new abstraction in part 2
New source of truth introduced?: no; migration 9 removes the obsolete one
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no
Actual user flow affected?: yes, acquisition execution boundary simplified
Actual user flow validated?: offline MCP yes; real OpenClaw pending
Scope drift detected?: no
```

## Completion record

```text
[x] Active path cutover
[x] persistence migration 8 business tables
[x] migration 9 legacy authority table cleanup
[x] public current schema cleanup
[x] Agent Skill aligned
[x] obsolete authority implementation tests removed
[x] acquisition offline integration / stdio business E2E
[x] main docs aligned
[x] old CapabilityCoordinator implementation removed
[x] inherited runner/request compatibility removed
[x] old acquisition authority tables/current schemas physically cleaned up
[ ] real Agent/user-flow revalidated
```

## Completion condition

0037 在以下最后条件满足后改为 `completed`：

- 至少一个真实 generic 用户回合在当前部署完成：
  `Search -> Inspect -> Present -> Select -> Confirm -> Acquire -> Archive -> Recover`；
- 该回合的正文网页语义为 `primary_resource`，并由 exact web materializer 执行；
- 真实验证没有暴露仍可触发的旧 authority 路径。
