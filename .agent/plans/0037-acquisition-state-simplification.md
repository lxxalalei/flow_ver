# 0037 — 获取状态链简化

- 状态：in_progress
- 创建日期：2026-08-11
- 分支：`codex/growth-resource-taxonomy-rework`
- 优先级：高于 0036 中“恢复平台后再决定是否减法”的顺序；0036 的平台恢复目标保留，但不得继续扩展 Capability Authority 链

## Goal

把当前获取链从“权威证明系统”收敛为资源获取业务系统，同时保留真正影响业务正确性的边界：

```text
Selection
  -> Resolution / Representation
  -> AcquisitionPlan
  -> 用户确认
  -> Job + JobItem snapshot
  -> exact Provider
  -> Outcome
  -> Asset / Bundle
  -> Archive
```

Capability Descriptor、Readiness Snapshot、Eligibility Decision 不再作为运行时持久状态；Plan/Execution/Outcome 不再依赖多层 SHA-256 binding digest。

## Product decisions

### 保留

- `Resolution / Representation`：它回答“候选真正有哪些可获取表示”。
- `AcquisitionPlan`：它回答“用户确认后准备获取什么、用什么策略和 Provider”。
- `Job` 与按资源的 `JobItem` 快照：异步任务和多资源执行需要持久化成员关系。
- `Outcome`：记录实际成功、失败、partial、Provider 与 Asset/Bundle 关系。
- `source_fingerprint`：只作为资源身份和 Resolution cache key，不作为权威证明。
- exact Provider routing：Plan 绑定的 Provider 失败后不静默切换第二个 Provider。
- Selection/Plan 版本、用户确认、幂等、取消、SSRF、重定向、受控目录、真实格式校验。

### 删除

- 持久化 Capability Descriptor binding。
- `Deployment Readiness Snapshot` 持久状态和 TTL 链。
- `Eligibility Decision` 持久状态和 TTL 链。
- `authority_digest`。
- `plan_binding_digest` / `binding_digest`。
- `execution_binding_digest`。
- `outcome_digest`。
- Provider 请求中仅用于证明上述链条的 descriptor/readiness/eligibility 字段。

### 降级为运行时逻辑

- Capability：变成小型 `ProviderSpec` 配置，描述 platform / representation / scope / strategy / provider。
- Readiness：Start 前检查 exact Provider 是否已注册且支持计划的 strategy/scope；不写数据库。
- Eligibility：Prepare/Start 时根据 Representation 当前事实直接返回允许/阻断；不生成实体 ID。

## Business invariants

1. Agent 仍不能提交任意本地路径、下载 URL 或 Provider 来替代服务端计划。
2. Prepare 只能基于当前 Selection 和已 Inspect 的 Resolution。
3. 显式 Representation evidence 存在时，Prepare 与 Start 均要求 `observed_at <= now < expires_at`。
4. Start 必须重新读取当前 Resolution，并确认计划中的 representation 仍存在、核心字段未漂移。
5. Start 只执行 Plan 中保存的 `provider_id + provider_version + strategy + scope`；Router 不做 silent fallback。
6. JobItem 是 PlanItem 在 Start 成功校验后的服务端快照，不额外生成“执行权威凭证”。
7. Outcome 只描述实际执行事实；归档根据 `Job succeeded + Asset ready + Bundle/Outcome/JobItem 关系` 判断，不比较摘要链。
8. 网页本身就是文章正文时允许 `webpage + primary + primary_resource -> web_materialize`；landing page 仍保持 landing scope，二者不再混为一谈。
9. 文件 SHA-256/byte_size 可作为 Asset 元数据和去重信息，但不得重新成为下载验收门禁；0030 的决定继续有效。

## Implementation

### Phase A — Active path cutover

- 将当前 `service.py` / `storage.py` / acquisition models/router 保留为迁移参考文件，Active 文件改为薄层实现。
- 新增 `AcquisitionPlanner`，只维护少量 ProviderSpec 并从当前 Representation 解析执行路线。
- `ResourceService.__init__` 不再创建 `CapabilityCoordinator`。
- `download_prepare` 生成简单 PlanItem。
- `download_start` 不接收 `authority_digest`，只校验 Selection/Plan、fresh Resolution、Representation 与 Provider registration。
- Router 继续 exact routing，但结果不附加 binding/source authority 字段。

### Phase B — Persistence simplification

数据库 migration 8：

- `download_plan_items` 只保留 `resource/resolution/representation/scope/strategy/provider/source_fingerprint/representation_json`。
- 用 `job_items` 代替 `job_execution_items`，只保存 PlanItem 的执行快照与 `revalidated_at`。
- `acquisition_outcomes` 删除 plan/execution/outcome digest 字段。
- 删除 `capability_readiness_snapshots` 与 `eligibility_decisions` 表。
- 既有 v7 行迁移到简化表，不能凭空补造新的 authority evidence。

### Phase C — Contract / docs cleanup

- `resource_download_start` 删除 `authority_digest`。
- PlanItem schema 删除 capability / eligibility / binding digest 组。
- Outcome schema 删除 `outcome_digest` 与 execution binding 结构。
- CURRENT_ARCHITECTURE / DEVELOPMENT_PLAN / Skill 说明改为简单获取链。
- `capability.py` 与 capability descriptor schemas 在所有 Active import 清零后移入历史或删除；不得留下第二套运行真值。

## Validation

定向验证优先，不因本次改造默认跑耗时全仓回归：

1. 新数据库从 migration 0 -> 8，旧 v7 数据 -> 8。
2. Prepare：generic document primary、generic webpage primary、generic landing page、SmartEdu document 路由正确。
3. Prepare：无 Resolution、stale evidence、无匹配 Provider 明确失败。
4. Start：Selection 改变、Plan 过期、Representation 消失/漂移、Provider 未注册均不创建 Job。
5. Start：成功时只创建一个 Job，并把 PlanItem 复制为 JobItem。
6. Router：exact Provider；失败不切 generic fallback。
7. Outcome：成功/失败/partial/取消无需任何 digest 即可恢复。
8. Archive：只接受 succeeded Job 的 ready Asset，且 Asset 必须属于对应 JobItem/Outcome/Bundle。
9. 文章正文网页能以 `primary_resource + web_materialize` 获取，不再被强制降为 landing page。
10. `git diff --check`、Python compile、相关 acquisition/service/storage/contract tests。

## Completion record

```text
[ ] Active path cutover
[ ] persistence migration 8
[ ] public schema cleanup
[ ] targeted tests
[ ] integration tests
[ ] docs aligned
[ ] obsolete capability authority code removed from Active imports
[ ] real Agent/user-flow revalidated
```
