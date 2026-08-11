# 当前架构事实

> 快照日期：2026-08-12
>
> 本文记录当前工作树的人类可读事实。机器事实仍以公共契约和实际运行代码为准。

## 事实优先级

发生冲突时按以下顺序确认：

1. `mcp/education-resources/contracts/` 中当前 Tool catalog、Schema、错误码、平台与分类契约；
2. `mcp/education-resources/src/education_resource_mcp/` 中当前运行时入口、服务、存储、Provider 和 Adapter；
3. 本文与其他 current 文档；
4. `.agent/plans/` 当前执行计划；
5. `docs/archive/`、`.agent/plans/archive/` 和 `legacy/` 历史材料。

Registry、Adapter、ProviderSpec 或历史代码存在，都不能单独证明某个平台当前可用、某个候选存在具体 Representation，或一次获取已经成功。

## 1. Active 边界

| 项目 | 当前事实 |
| --- | --- |
| 唯一用户入口 | `skills/learning-resource-flow/` |
| MCP | `mcp/education-resources/`，Python stdio MCP |
| MCP server | `education-resources`；metadata `0.2.0` |
| 公共契约 | `contract_version=1.0.0` |
| Tool catalog | `catalog_version=1.6.0`，13 个领域级 Tool |
| 分类 | `contracts/taxonomy/learning-v1.json` |
| SQLite | active migration `9` |
| Active 获取服务 | `simple_service.py` |
| Active 获取存储 | `simple_storage.py` |
| 获取规划 | `acquisition/planner.py` 的 `ProviderSpec` / `AcquisitionPlanner` |
| 获取请求 | `acquisition/simple.py` 的轻量 `AcquisitionRequest` |
| Provider 路由 | exact `(provider_id, provider_version)`；失败不 silent fallback |

Active 主链：

```text
用户自然语言
  -> learning-resource-flow Skill
  -> education-resources MCP
  -> Search / Inspect
  -> Resolution / Representation
  -> AcquisitionPlan
  -> 用户明确确认
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / Bundle
  -> Archive
```

业务状态只保留：

```text
FlowTask
  -> ResultSet
  -> Presentation
  -> Selection
  -> Resolution / Representation
  -> Plan / PlanItem
  -> Job / JobItem
  -> Outcome
  -> AssetBundle / Asset
  -> Archive
```

## 2. 已删除的获取权威链

以下对象已经退出 Active acquisition 状态和 current 公共契约：

- Capability Descriptor binding；
- Deployment Readiness Snapshot；
- Eligibility Decision；
- `authority_digest`；
- `plan_binding_digest` / `binding_digest`；
- `execution_binding_digest`；
- `outcome_digest`。

Capability 现在只回答一个运行时问题：当前 Representation 能否由某个明确 Provider 以某个 Strategy 执行。

Prepare 根据 fresh Representation 生成 Plan；Start 再读取当前 Resolution，确认：

- Selection / Plan 仍有效；
- `representation_id` 仍存在且核心语义未漂移；
- evidence 当前有效；
- Plan 指定的 exact Provider 当前仍注册并支持该 scope/strategy。

这些是业务校验，不生成 Readiness ID、Eligibility ID 或 digest。

旧 `capability.py` 的大型 authority 实现已经删除，仅保留 fail-fast shim 防止旧获取入口被误用。Active `simple_service` 不创建或调用 `CapabilityCoordinator`。

## 3. 当前 ProviderSpec 路线

当前简化 Planner 至少声明：

1. generic document primary → `direct_file` → `generic-direct@1.0.0`；
2. generic webpage primary → `web_materialize` → `generic-web-materializer@1.0.0`；
3. generic webpage landing → `web_materialize` → `generic-web-materializer@1.0.0`；
4. SmartEdu document primary → `direct_file` → `smartedu-resource@1.0.0`，仅当前部署实际注册时可用。

ProviderSpec 存在不等于平台 production-ready。真实网络、认证、策略、许可和内容输出仍由 0028 验收。

## 4. 正文网页与 landing page

网页的业务角色和获取机制分开判断。

如果网页本身就是用户选择的文章、教程或图文正文：

```text
kind=webpage
role=primary
scope=primary_resource
strategy=web_materialize
```

如果只是导航、详情、预览或跳转入口：

```text
role=landing
scope=landing_page
```

`web_materialize` 只描述“如何保存网页”，不能自动把正文降级成 landing page，也不能把 landing page 冒充正文资源。

## 5. `source_fingerprint` 与文件元数据

`source_fingerprint` 只承担资源身份与 Resolution cache 关联作用，不是 Plan/Job/Outcome 的防伪凭证。

文件 `sha256` / `byte_size` 继续作为 Asset 元数据、索引和去重信息，但 0030 的决定继续有效：

- 不因为 Provider 声明大小与实际大小不一致拒绝已经生成的文件；
- 不因为声明 SHA-256 与实际文件不一致拒绝文件；
- 不恢复每资源/Bundle 通用下载字节上限作为成功门禁。

网页解析器自身的内存、DOM、图片数量等保护边界属于具体处理器资源保护，不等于通用文件大小验收门禁。

## 6. 公共 MCP 工具

公共 Tool 数量仍为 13：

`resource_flow_start`、`resource_flow_status`、`resource_search`、`resource_presentation_save`、`resource_selection_save`、`resource_download_prepare`、`resource_download_start`、`resource_job_status`、`resource_job_cancel`、`resource_archive`、`resource_library_search`、`resource_browse_creator`、`resource_inspect`。

当前公共契约中：

- `resource_download_start` 不接受 `authority_digest`；
- Prepare PlanItem 不暴露 capability/readiness/eligibility/binding digest；
- FlowStatus current Plan/Job 不暴露 `authority_digest`；
- JobStatus Outcome 不暴露 plan/execution/outcome digest；
- 独立 Capability Descriptor、Deployment Readiness、Eligibility Decision current schema/catalog 已物理删除。

`selection_digest` / `plan_digest` 继续存在，只用于当前选择与确认计划的内容标识和幂等关系，不构成多层 capability authority chain，也不传给 Provider。

## 7. AcquisitionRequest 与 Provider 边界

当前 `AcquisitionRequest` 是独立轻量 DTO，只包含执行实际需要的事实：

```text
job_id
resource
strategy
provider_id / provider_version
planned_scope
representation_id
preferred_container
cancel_event
jobs_root
```

它不继承旧 Request，也没有 capability、descriptor、readiness、eligibility、binding digest 等空 slot。

Router 负责确认请求类型和 exact Provider；Provider 负责执行，不再重复要求某个历史 Request concrete class。`WebMaterializer` 已移除此前的旧 `isinstance(AcquisitionRequest)` 兼容检查。

## 8. SQLite migration 8 / 9

migration 8 建立当前三张 acquisition 业务表并先从 v7 降维 backfill：

```text
acquisition_plan_items
job_items
execution_outcomes
```

这些表只保存业务执行需要的字段，不包含 Descriptor/Readiness/Eligibility/digest 列。

migration 9 在 backfill 完成后物理删除旧 acquisition authority 表：

```text
job_execution_items
acquisition_outcomes
download_plan_items
eligibility_decisions
capability_readiness_snapshots
```

`storage.py` 中仍保留历史 migration 定义，目的是让旧数据库能够升级；migration 9 后 Active acquisition 不读取或写入这些旧表。

## 9. Active runner 与 Job 状态

`simple_service.ResourceService` 已直接实现 acquisition runner：

```text
Job
  -> get_job_items()
  -> AcquisitionRequest
  -> exact Provider
  -> execution_outcomes
  -> AssetBundle / Asset
  -> finalize Job
```

Runner 不再调用 `get_job_execution_items()`，也不再人工补 `capability_scope`、`readiness_snapshot_id`、`eligibility_id` 等空兼容字段。

`resource_job_status` 同样从 `job_items` 与 `execution_outcomes` 恢复实际执行事实。

`simple_storage` 的 success / failure / cancellation 收口使用当前 Outcome 表；Asset/Bundle/Archive graph 仍作为资源产物一致性的业务事实。

## 10. 仍保留的业务与安全不变量

简化不等于取消必要边界：

- `prepare -> 用户明确确认 -> start`；
- Agent 不能提交任意本地路径、脚本、解释器或 Provider 替代服务端 Plan；
- Selection / Presentation / Plan 版本与幂等关系由服务端校验；
- Start 重新核验当前 Resolution / Representation；
- Router 只执行 Plan 的 exact Provider；
- Job 支持 queued/running/cancelling/succeeded/failed/cancelled；
- Asset 只能来自服务端受控 Job 目录；Archive 只接受 ready `asset_id`；
- SSRF、逐跳重定向、路径逃逸、取消、超时、真实 MIME/格式检查继续保留；
- 不绕过登录、验证码、付费墙、DRM 或明确访问控制。

## 11. Agent / 检索边界

Skill 已同步到新获取模型，但搜索分权保持不变：

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> Resolution / Representation facts
Skill -> private SemanticReview -> Gap -> StopDecision
```

候选数量、标题命中、平台数量和 coverage 不能单独触发 Present。常规任务仍在有限 Search 轮次内由 Skill 决定 Replan / Clarify / StopWithGap / Present，并只对会改变决策的高潜候选做 Selective Inspect。

0037 没有把搜索质量判断搬回 Python 硬编码。

## 12. 测试治理与验证

只验证旧实现实体的 CapabilityAuthority、Readiness Snapshot、Eligibility/digest binding、Job execution authority storage 等测试已移出 Active 测试面。

平台 Search/Inspect Adapter 注册类测试继续保留。`test_mcp_stdio.py` 没有被删除，而是迁移为新契约继续验证完整业务闭环。

0037 已完成三轮关键验证：

1. simplified state 定向验证；
2. run `31514845872`：完整离线 MCP round trip；
3. run `31517757764`：migration 9 / Request / Runner / contract 物理 cleanup 后再次验证。

第三轮实际通过：

- current package install；
- `compileall`；
- current contract JSON 全量解析；
- `test_acquisition_simplification_0037.py` 7/7；
- `test_mcp_stdio.py` 2/2；
- 五个旧 capability/readiness/eligibility current contract artifact 的物理删除检查。

成功 cutover 提交：`ff2a7044fa26a48491e5c3dac9fed5ee7ffd380d`。

这些验证证明当前简化模型在离线 MCP 业务闭环中可执行，但不能证明真实互联网平台、合法会话或默认 OpenClaw Agent 已通过。

## 13. 当前执行顺序

1. **0037 Acquisition State Simplification**：只剩真实 generic Agent 用户闭环验收；
2. **0028 Real OpenClaw and Real Platform E2E**：基于简化模型恢复/验证真实平台；
3. **0029 Retrieval Benchmark and Release Gate**：建立业务行为质量门禁；
4. Platform Expansion / Library & Viewer / 后续部署。

0036 已 superseded 并移入 `.agent/plans/archive/`。其中平台恢复候选仍可作为 0028 输入，但旧 architecture chain 和重新引入通用大小/哈希门禁的部分不再执行。

## 14. 尚未验收

0037 本身只剩：

- 真实 OpenClaw generic article primary webpage 成功完成：
  `Search -> Inspect -> Present -> Select -> Confirm -> Acquire -> Archive -> Recover`；
- 确认正文网页实际为 `primary_resource + web_materialize`；
- 确认真实调用没有暴露仍可触发的旧 authority acquisition 路径。

后续属于 0028 / 0029：

- SmartEdu 有效会话下真实 Search/Inspect/Acquire；
- Bilibili、Douyin、Ximalaya、CCTV、NLC、Open163、Yixi 等真实平台 Provider 恢复；
- retrieval benchmark / release gate。

## 相关入口

- [工作区入口](../README.md)
- [开发路线](DEVELOPMENT_PLAN.md)
- [Retrieval Authority ADR](RETRIEVAL_AUTHORITY.md)
- [0037 当前计划](../.agent/plans/0037-acquisition-state-simplification.md)
- [机器契约目录](../mcp/education-resources/contracts/README.md)
- [历史归档索引](archive/README.md)
