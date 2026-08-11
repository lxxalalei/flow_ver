# 0037 — 获取状态链简化

- 状态：in_progress
- 创建日期：2026-08-11
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`
- 优先级：高于 0036 中“恢复平台后再决定是否减法”的顺序；0036 的平台恢复目标保留，但不得继续扩展 Capability Authority 链

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

当前 Active MCP 入口已变为：

```text
server.py
  -> simple_service.ResourceService
     -> AcquisitionPlanner / ProviderSpec
     -> simple_storage.Store (migration 8)
     -> simplified AcquisitionRequest / exact Router
```

为降低一次性重写风险，`simple_service` / `simple_storage` 仍复用 0037 前 Service/Store 的成熟 Search、Inspect、Job lifecycle、Asset/Archive 辅助逻辑。旧 `capability.py` 和旧 v6/v7 authority 表暂时仍存在于源码/升级库中，但新 acquisition 写入路径不再使用它们。

这是一段明确的兼容期，不是最终状态。

## Implemented

### Phase A — Active path cutover

- [x] 新增 `AcquisitionPlanner` 与轻量 `ProviderSpec`。
- [x] generic document primary → direct Provider。
- [x] generic primary webpage → web materializer。
- [x] generic landing webpage → web materializer。
- [x] SmartEdu document primary → exact SmartEdu Provider（仅当前部署实际注册时可用）。
- [x] `ResourceService.__init__` Active 路径不再创建 `CapabilityCoordinator`。
- [x] `download_prepare` 生成简单 PlanItem。
- [x] `download_start` 删除 `authority_digest`，重验证 Selection / Plan / Resolution / Representation / Provider route。
- [x] Router 继续 exact routing；Provider-facing `to_dict()` 不暴露旧 authority 字段。
- [ ] 将继承的旧 `_run_download_job` 改成直接消费 `job_items` 的纯简化实现，移除内部兼容参数名。

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

### Phase C — Public contract / docs

- [x] `resource_download_start` 删除 `authority_digest`。
- [x] PlanItem Schema 删除 capability / eligibility / binding digest 组。
- [x] JobStatus Outcome projection 删除 plan/execution/outcome digest 与 capability/readiness/eligibility 结构。
- [x] `actual-outcome.schema.json` 简化。
- [x] Tool catalog 升至 `1.6.0`，Tool 数仍为 13。
- [x] README / MCP README / Contracts README / CURRENT_ARCHITECTURE / DEVELOPMENT_PLAN / compatibility 已同步。
- [ ] `resource_flow_status.schema.json` 中仍有旧 `authority_digest` 可选属性，需在最终 contract cleanup 移除。
- [ ] Skill 中 capability/readiness/eligibility 文案仍需按新架构收口。
- [ ] Active runtime 对旧 `capability.py` 的 import 仍需清零。

## Validation

本次不默认运行全仓历史测试；旧 capability-authority 专项测试验证的是本次已废弃实现，不能成为要求恢复旧链的门禁。

已执行一次隔离 GitHub Actions 定向验证：

| Validation | Result | Proves | Does not prove |
| --- | --- | --- | --- |
| Python 3.12 package install | pass | 当前包依赖可安装 | 真实平台可用 |
| `compileall` active package | pass | 当前 Python 源码可编译 | 业务全链路正确 |
| parse all contract JSON | pass | 当前 JSON 语法完整 | 所有 Schema 语义均被实例覆盖 |
| `test_acquisition_simplification_0037.py` | pass | simplified Request、primary webpage route、migration 8、新表无 authority digest、Start 无 authority_digest、主要下载 Schema 已简化 | 真实 OpenClaw / 真实网络 / Archive 全闭环 |

临时验证 workflow 已删除，避免后续每次小 push 自动重复跑测试。

## Remaining validation

1. 新库 migration 0 → 8 的更完整 CRUD；
2. v7 → 8 带真实旧数据升级；
3. Prepare/Start 的 stale Resolution、selection drift、provider missing；
4. Job succeeded/partial/failed/cancelled；
5. Archive succeeded Job ready Asset；
6. 真实 OpenClaw generic article primary webpage 闭环；
7. 再根据改动范围决定是否跑更大 regression。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: targeted validation only; real Agent pending
New abstraction introduced?: one small ProviderSpec/Planner, replacing several state entities
New source of truth introduced?: no; migration 8 simplifies acquisition persistence
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: docs/contracts only for alignment
Actual user flow affected?: yes, acquisition model and article webpage semantics
Actual user flow validated?: not yet in real OpenClaw
Scope drift detected?: old authority cleanup remains staged, explicitly tracked
```

## Completion record

```text
[x] Active path cutover
[x] persistence migration 8 active tables
[x] public download schema cleanup (except flow_status optional legacy field)
[x] targeted tests
[ ] acquisition integration tests
[x] main docs aligned
[ ] Skill aligned
[ ] obsolete capability authority code removed from Active imports
[ ] old authority tables physically cleaned up
[ ] real Agent/user-flow revalidated
```

## Completion condition

本计划只有在以下都满足后才可改为 `completed`：

- Active runtime 不再依赖旧 CapabilityCoordinator；
- 公共 current Schema 不再暴露 authority/readiness/eligibility digest；
- 兼容期旧表有明确 cleanup 处置；
- 关键 acquisition integration 测试通过；
- 至少一个真实 generic 用户回合完成 Search → Inspect → Select → Confirm → Acquire → Archive → Recover。
