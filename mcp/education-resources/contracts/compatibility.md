# 当前兼容与重置政策

## 产品承诺

产品只承诺当前公共控制面：`contract_version=1.0.0`、`catalog_version=1.6.0`。机器事实以 [`tool-catalog.json`](tool-catalog.json) 和相关 Schema 为准。

项目不承诺任意历史客户端、缓存的旧 Tool Schema、旧 Plan 确认材料或旧内部 authority 对象仍可继续执行。兼容的首要目标是“不误执行旧状态”，不是“让所有旧字段继续存在”。

## 0037 获取模型切换

当前新写获取链为：

```text
Selection
  -> Resolution / Representation
  -> Plan / PlanItem
  -> 用户确认
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / Bundle
  -> Archive
```

以下 0037 前字段/实体不再属于新公共获取控制面：

- Capability Descriptor binding；
- Readiness Snapshot；
- Eligibility Decision；
- `authority_digest`；
- Plan/Execution binding digest；
- `outcome_digest`。

服务端不会为了“兼容旧字段”在新 Plan/Job 中重新生成上述状态。

## 旧 v7 数据

migration 8 允许从旧 `download_plan_items`、`job_execution_items`、`acquisition_outcomes` 降维 backfill 到：

- `acquisition_plan_items`；
- `job_items`；
- `execution_outcomes`。

迁移只保留业务执行仍需要的事实：resource、resolution、representation、scope、strategy、Provider、Outcome 与 Asset/Bundle 关系。旧 digest 不作为迁移后执行凭证。

已经消费、过期、缺少 Resolution/Representation 或无法重建明确 Provider route 的旧 Plan 不应被强行恢复为可执行状态；正确恢复方式是重新 Inspect / Selection / Prepare / Confirm。

## 客户端兼容

`resource_download_start` 已不再接受 `authority_digest`。缓存旧 `1.5` Schema 的客户端必须在 `initialize` / `tools/list` 后刷新当前目录，否则可能因为多传已删除字段而被严格 Schema 拒绝。

这是显式契约升级，不提供“多传旧字段也悄悄忽略”的公共 Tool 兼容层。内部 Python Provider seam 为了 staged cutover 暂时接受并丢弃旧 authority 参数，但该行为不是公共协议，不得被客户端依赖。

## Plan / Selection 摘要

`selection_digest` 与 `plan_digest` 继续保留，因为它们是当前用户选择和确认计划的服务端版本/内容标识，用于幂等与防止确认错计划。

它们与已删除的 capability/readiness/eligibility authority digest 不同：

- 不构成多层状态证明链；
- 不传给 Provider；
- 不生成新的 Readiness/Eligibility 实体；
- 不用于证明远端内容“可信”。

## `source_fingerprint`

`source_fingerprint` 继续作为资源身份与 Resolution cache key。它可参与“当前 Resolution 是否仍属于同一资源”的比较，但不作为 Plan/Job/Outcome 防伪签名。

## 运行中 Outcome

公共 `outcome_status` 继续允许 `running`。Outcome 终态可为 succeeded / partial / failed / cancelled；Job 生命周期仍独立使用 queued / running / cancelling / succeeded / failed / cancelled。

Outcome 公共投影只描述 planned / execution / actual route 与 Asset/Bundle/failure，不再包含 digest credential。

## ResultSet extend

`resource_search.limit` 仍表示新不可变 ResultSet 的总容量。`mode=extend` 时 base 候选占用容量；例如已有 8 个候选，若希望最多再容纳 8 个，应请求 `limit=16`，并继续受服务端总上限约束。

检索语义与 0037 获取简化相互独立；不得因为获取层删减状态而降低 SemanticReview、Gap、StopDecision 或 Selective Inspect 的要求。

## 后续 cleanup

兼容期结束后需要独立 cleanup：

1. 旧 authority 专项测试移出 Active 门禁；
2. Active runtime 不再 import 旧 `capability.py`；
3. cleanup migration 删除 v6/v7 已无读取者的 authority 表；
4. 删除不再被任何公共或迁移路径引用的 capability/readiness/eligibility Schema 与 catalog 文件。

相关文档：

- [当前架构](../../../docs/CURRENT_ARCHITECTURE.md)
- [开发路线](../../../docs/DEVELOPMENT_PLAN.md)
- [0037 获取状态链简化](../../../.agent/plans/0037-acquisition-state-simplification.md)
- [检索权威边界](../../../docs/RETRIEVAL_AUTHORITY.md)
