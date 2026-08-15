# 当前兼容与重置政策

## 产品承诺

产品只承诺当前公共控制面：`contract_version=1.0.0`、`catalog_version=1.7.0`。机器事实以 [`tool-catalog.json`](tool-catalog.json) 和相关 Schema 为准。

项目不承诺任意历史客户端、缓存的旧 Tool Schema、旧 Plan 确认材料或旧内部 authority 对象仍可继续执行。兼容的首要目标是“不误执行旧状态”，不是“让所有旧字段继续存在”。客户端每次连接都应以当前 `initialize` / `tools/list` 为准；多传已删除字段会被严格 Schema 拒绝，而不是静默忽略。

## 0055 Public MCP Surface Simplification

0055 不改数据库、Store、Provider、Downloader 或平台 Adapter。完整的 Flow / ResultSet / Presentation / Selection / Resolution / Representation / Plan / Job / Outcome / Asset 事实继续保存在服务端；改变的是 **Agent-facing 输入/输出表面**。

目标是让 Main Agent 负责语义判断，而不是搬运数据库事务状态。当前公共调用收敛为：

```text
resource_search
  input:  flow_id + search_tasks + mode/filters/limit
  output: compact candidates + failure summary

resource_presentation_save
  input:  flow_id + displayed_resource_ids
  server: bind current ResultSet

resource_selection_save
  input:  flow_id + selected_positions
  server: bind current Presentation/version

resource_download_prepare
  input:  flow_id + optional options
  server: bind current Selection/Presentation/digest

resource_download_start
  input:  flow_id + plan_id + confirmation_token
  server: revalidate stored Plan/Selection/Representation/provider route
```

以下字段不再要求 Agent 在相邻 Tool 之间搬运：

- Search 的 `task_version`、`base_result_set_id`；
- Presentation 的 `result_set_id`；
- Selection 的 `presentation_id`、`presented_version`；
- Prepare 的 `presentation_id`、`presented_version`、`selection_version`、`selection_digest`。

服务端内部仍使用这些事实执行现有一致性校验；公共参数删除不等于校验删除。

### Compact outputs

以下 Tool 不再把完整内部状态树送进 Agent 上下文：

- `resource_search` / `resource_browse_creator`：不返回完整 platform runs、ResultSet lineage、provenance/coverage；保留候选、数量和失败摘要。
- `resource_inspect`：保留 availability、Representation、必要 creator handle、warnings/failures；不返回 inspector/version/method、source fingerprint、evidence payload、resolution digest 等内部证据机器字段。
- `resource_flow_status`：只用于恢复当前阶段和下一步所需引用；不重放完整 candidates、Resolution evidence、selection/plan digest 或 execution route。ResultSet recovery refs 明确最多返回 20 条，并用 `candidate_refs_complete` 标明是否完整，不做静默截断。
- `resource_job_status`：保留状态、进度、ready asset handles 和失败摘要；不返回 presentation/selection/plan digest、Outcome execution route 等内部执行投影。

完整事实仍在 Service/Store，供一致性校验、执行和服务端调试使用。

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

服务端不会为了兼容旧字段在新 Plan/Job 中重新生成上述状态。

## 旧数据与旧 Plan

migration 8/9 继续承担旧库升级。迁移只保留业务执行仍需要的 resource、resolution、representation、scope、strategy、Provider、Outcome 与 Asset/Bundle 关系。

已经消费、过期、缺少 Resolution/Representation 或无法重建明确 Provider route 的旧 Plan 不应被强行恢复为可执行状态；正确恢复方式是重新 Inspect / Selection / Prepare / Confirm。

## Plan / Selection 摘要

`selection_digest` 与 `plan_digest` 可以继续作为**服务端内部**的选择/计划版本与内容标识，用于幂等和防止确认错计划。0055 之后 Main Agent 不需要在普通流程或恢复流程中搬运这些值。

它们与已删除的 capability/readiness/eligibility authority digest 不同：不构成多层证明链、不传给 Provider、不生成 Readiness/Eligibility 实体，也不用于证明远端内容可信。

## `source_fingerprint`

`source_fingerprint` 继续作为资源身份与 Resolution cache key，可参与服务端判断当前 Resolution 是否仍属于同一资源；它不是 Plan/Job/Outcome 防伪签名，也不再作为 Public Inspect 结果反复进入 Agent 上下文。

## 运行中 Outcome

Outcome 仍由服务端记录实际执行结果，终态可为 succeeded / partial / failed / cancelled；Job 生命周期使用 queued / running / cancelling / succeeded / failed / cancelled。

0055 后 `resource_job_status` 不再返回完整 Outcome execution projection。删除公共投影不删除服务端 Outcome，也不降低 ready Asset 的成功条件。

## ResultSet extend

Public `resource_search(mode=extend)` 自动绑定当前服务端 ResultSet，客户端不提交 `base_result_set_id`。ResultSet 仍为不可变服务端快照，跨轮合并与去重仍由 MCP 完成。

检索语义仍由 Skill/Main Agent 判断；不得因为公共状态瘦身而降低相关性判断、Gap 判断、Selective Inspect 或停止搜索的要求。

## 必须保持的执行边界

- `prepare -> 用户明确确认 -> start`；
- 用户序号只绑定实际 Presentation；
- Start 重新验证当前 Selection / Representation / exact Provider；
- Provider 失败不 silent fallback；
- AUTH_REQUIRED / policy blocked / unavailable 保持真实暴露；
- 没有 ready Asset 不得报告下载成功；
- Archive 只接受服务端 ready `asset_id`。

相关文档：

- [当前架构](../../../docs/CURRENT_ARCHITECTURE.md)
- [开发路线](../../../docs/DEVELOPMENT_PLAN.md)
- [Learning Resource Skill](../../../skills/learning-resource-flow/SKILL.md)
- [0055 Public MCP Surface Simplification](../../../.agent/plans/archive/0055-public-mcp-surface-simplification.md)
