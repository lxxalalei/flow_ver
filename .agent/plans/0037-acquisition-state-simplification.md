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

Capability Descriptor、Readiness Snapshot、Eligibility Decision 不再作为新运行时持久状态；Plan / Job / Outcome 不依赖多层 SHA-256 binding digest。

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

### 删除/退出 Active 新写入

- Capability Descriptor binding；
- Deployment Readiness Snapshot 持久状态；
- Eligibility Decision 持久状态；
- `authority_digest`；
- `plan_binding_digest` / `binding_digest`；
- `execution_binding_digest`；
- `outcome_digest`；
- Provider 请求中仅用于证明上述链条的 descriptor/readiness/eligibility 字段。

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

当前 Active MCP 入口：

```text
server.py
  -> simple_service.ResourceService
     -> AcquisitionPlanner / ProviderSpec
     -> simple_storage.Store (migration 8)
     -> simplified AcquisitionRequest / exact Router
```

为降低一次性重写风险，`simple_service` / `simple_storage` 仍复用 0037 前 Service/Store 的成熟 Search、Inspect、Job lifecycle、Asset/Archive 辅助逻辑。这是兼容期，不是最终文件布局。

旧 `capability.py` 的约 71KB authority 实现已物理删除，只剩 tiny fail-fast shim 给旧 Service 基座解析 import；Active `simple_service` 不创建或调用 `CapabilityCoordinator`。

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
- [x] Router 继续 exact routing；Provider-facing `to_dict()` 不暴露旧 authority 字段。
- [x] 旧 `capability.py` authority implementation 删除并改为 fail-fast shim。
- [ ] 将继承的旧 `_run_download_job` 改成直接消费 `job_items` 的纯简化实现，移除内部兼容参数名和旧 Request slot。

### Phase B — Persistence simplification

migration 8 已新增：

```text
acquisition_plan_items
job_items
execution_outcomes
```

- [x] 新 PlanItem 不含 capability/readiness/eligibility/binding digest。
- [x] JobItem 只保存执行快照与 `revalidated_at`。
- [x] 新 Outcome 不含 plan/execution/outcome digest。
- [x] v7 Plan/Job/Outcome 可降维 backfill 到新表。
- [x] 新 Archive 关系校验使用 JobItem / Outcome / Bundle / Asset graph。
- [ ] 兼容期结束后用 cleanup migration 删除 `capability_readiness_snapshots`、`eligibility_decisions`、旧 `download_plan_items` / `job_execution_items` / `acquisition_outcomes` 中不再需要的 authority 面。

### Phase C — Public contract / Agent / docs

- [x] `resource_download_start` 删除 `authority_digest`。
- [x] PlanItem Schema 删除 capability / eligibility / binding digest 组。
- [x] JobStatus Outcome projection 删除 plan/execution/outcome digest 与 capability/readiness/eligibility 结构。
- [x] `actual-outcome.schema.json` 简化。
- [x] `resource_flow_status.schema.json` 删除旧可选 `authority_digest`。
- [x] Tool catalog 升至 `1.6.0`，Tool 数仍为 13。
- [x] README / MCP README / Contracts README / CURRENT_ARCHITECTURE / DEVELOPMENT_PLAN / compatibility 同步。
- [x] `learning-resource-flow/SKILL.md` 与 `references/acquisition.md` 改为新获取链，同时保留原有 Search/SemanticReview/Gap/StopDecision/Selective Inspect 规则。
- [x] 0036 superseded 并归档，避免后续 Agent 按旧架构继续。

### Phase D — Tests

已从 Active 测试面删除只验证旧实现的测试：

- `test_capability_authority.py`；
- `test_authority_error_contract.py`；
- `test_capability_contracts.py`；
- `test_capability_truth_negative.py` 与其 fixture；
- `test_job_execution_authority_storage.py`；
- `test_registry_readiness.py`。

平台 Search/Inspect 注册类测试（如 AdapterDescriptor）保留，因为它们仍约束真实平台业务能力。

`test_mcp_stdio.py` 已迁移为新契约，继续验证完整业务闭环，而不是删除测试绕过问题。

## Validation

已经完成两级验证。

### Milestone 1 — simplified state

隔离 GitHub Actions：

| Validation | Result |
| --- | --- |
| Python 3.12 package install | pass |
| `compileall` active package | pass |
| parse all contract JSON | pass |
| `test_acquisition_simplification_0037.py` | pass |
| Active Service initializes after CapabilityCoordinator retirement | pass |

### Milestone 2 — MCP business round trip

最终临时 GitHub Actions run `31514845872`：

| Validation | Result | What it proves |
| --- | --- | --- |
| install current service | pass | 当前依赖可安装 |
| compile active package | pass | 当前 Python 代码可导入/编译 |
| parse all contract JSON | pass | current JSON contract 无语法断裂 |
| simplified acquisition tests | pass | migration 8 / Planner / request / public schema 关键行为 |
| `test_mcp_stdio.py` | pass | 13 Tool + Flow → Search → Inspect → Present → Select → Prepare → Start → Job → Archive → Library 完整离线业务闭环 |

临时 workflow 已删除，避免后续每个小 push 重复跑里程碑测试。

该验证仍不能证明真实互联网平台、合法会话或默认 OpenClaw Agent 已通过。

## Remaining validation / cleanup

1. v7 → 8 带真实旧数据升级和 cleanup migration；
2. inherited `_run_download_job` / old AcquisitionRequest compatibility slot 彻底简化；
3. 旧 authority 表和兼容 capability schema/catalog 物理删除；
4. 根据剩余 diff 跑必要的 acquisition/storage 定向 regression；
5. 真实 OpenClaw generic article primary webpage：Search → Inspect → Select → Confirm → Acquire → Archive → Recover；
6. 完成后回到 0028 平台真实 E2E。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: offline business E2E passed; real platform pending
New abstraction introduced?: one small ProviderSpec/Planner replacing several state entities
New source of truth introduced?: no; migration 8 simplifies acquisition persistence
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no; docs/contracts/tests aligned with acquisition decision
Actual user flow affected?: yes
Actual user flow validated?: offline MCP full round trip yes; real OpenClaw no
Scope drift detected?: compatibility cleanup remains explicitly staged
```

## Completion record

```text
[x] Active path cutover
[x] persistence migration 8 active tables
[x] public current schema cleanup
[x] Agent Skill aligned
[x] obsolete authority implementation tests removed
[x] acquisition offline integration / stdio business E2E
[x] main docs aligned
[x] old CapabilityCoordinator implementation removed
[ ] inherited runner/request compatibility removed
[ ] old authority tables/schema compatibility physically cleaned up
[ ] real Agent/user-flow revalidated
```

## Completion condition

本计划只有在以下都满足后才改为 `completed`：

- Active acquisition code不再依赖旧 CapabilityCoordinator 实现；
- 公共 current Schema 不再暴露 authority/readiness/eligibility digest；
- 兼容期旧表/旧 Request 有明确 cleanup；
- 关键 acquisition integration 测试通过；
- 至少一个真实 generic 用户回合完成 Search → Inspect → Select → Confirm → Acquire → Archive → Recover。
