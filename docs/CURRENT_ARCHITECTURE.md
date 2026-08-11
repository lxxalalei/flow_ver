# 当前架构事实

> 快照日期：2026-08-11
>
> 本文记录当前工作树的人类可读事实。机器事实仍以公共契约和实际运行时代码为准。

## 事实优先级

发生冲突时按以下顺序确认：

1. `mcp/education-resources/contracts/` 中当前 Tool catalog、Schema、错误码、平台与分类契约；
2. `mcp/education-resources/src/education_resource_mcp/` 中当前运行时入口、服务、存储、Provider 和 Adapter；
3. 本文与其他 current 文档；
4. `.agent/plans/` 当前执行计划；
5. `docs/archive/`、`.agent/plans/archive/` 和 `legacy/` 历史材料。

Registry、Adapter、ProviderSpec 或历史实现存在，都不能单独证明某个平台当前可用、某个候选存在具体 Representation，或一次获取已经成功。

## 1. Active 边界与机器版本

| 项目 | 当前事实 |
| --- | --- |
| 唯一用户入口 | `skills/learning-resource-flow/` |
| MCP 服务 | `mcp/education-resources/`，Python stdio MCP |
| MCP server | `education-resources`；实现 metadata `0.2.0` |
| 公共契约 | `contract_version=1.0.0` |
| 公共工具目录 | `catalog_version=1.6.0`，仍为 13 个领域级 Tool |
| 平台 Registry | 固定平台身份与检索声明；不作为获取成功证明 |
| 分类体系 | `contracts/taxonomy/learning-v1.json` |
| SQLite | 最新 active migration `8` |
| Active 获取服务 | `simple_service.py` |
| Active 获取状态 | `simple_storage.py` 中 `acquisition_plan_items` / `job_items` / `execution_outcomes` |
| 获取规划 | `acquisition/planner.py` 中轻量 `ProviderSpec` + `AcquisitionPlanner` |
| Provider 路由 | exact `(provider_id, provider_version)`；失败不静默换 Provider |
| Legacy | `legacy/skill-pipeline-v1/` 只读；0037 前的 capability authority 代码仍暂留源码作迁移兼容，不再是新写入真值 |

### Active 主链

```text
用户自然语言
  -> learning-resource-flow Skill
  -> education-resources stdio MCP
  -> Search / Inspect
  -> Resolution / Representation
  -> Prepare Plan
  -> 用户明确确认
  -> Start Job
  -> exact Provider
  -> Outcome + Asset/Bundle
  -> Archive
```

### 当前业务状态链

```text
FlowTask
  -> ResultSet
  -> Presentation
  -> Selection
  -> Resolution / Representation
  -> AcquisitionPlan / PlanItem
  -> Job / JobItem
  -> Outcome
  -> AssetBundle / Asset
  -> Archive
```

其中：

- `Resolution / Representation` 回答“候选真正有哪些可获取表示”；
- `PlanItem` 只保存本次确认所需的 `resource / representation / scope / strategy / exact Provider`；
- `JobItem` 是 Start 重验证后对 PlanItem 的服务端执行快照；
- `Outcome` 只记录实际执行结果，不再承担状态防伪职责。

## 2. 0037 获取模型简化

### 已从 Active 持久链移除

以下对象不再作为新业务状态写入：

- Capability Descriptor binding；
- Deployment Readiness Snapshot；
- Eligibility Decision；
- `authority_digest`；
- `plan_binding_digest` / `binding_digest`；
- `execution_binding_digest`；
- `outcome_digest`。

Capability 不再是一条需要逐层证明的状态链。它被降级成 Provider 路由配置：当前 Representation 能否由某个 Provider 以某种 Strategy 执行。

### ProviderSpec

当前获取规划核心是轻量 `ProviderSpec`：

```text
platform
+ resource / representation shape
+ scope
+ strategy
+ provider_id / provider_version
```

Prepare 根据 fresh Representation 选择一条明确路线；Start 再读取当前 Resolution，确认 Representation 仍存在且核心字段未漂移，并确认 exact Provider 当前仍注册且支持该 scope/strategy。

这两个时点的检查是业务校验，不生成 Readiness ID、Eligibility ID 或 digest。

### 当前已声明的简化路线

当前 0037 planner 至少包含：

1. generic document primary → `direct_file` → `generic-direct@1.0.0`；
2. generic webpage primary → `web_materialize` → `generic-web-materializer@1.0.0`；
3. generic webpage landing → `web_materialize` → `generic-web-materializer@1.0.0`；
4. SmartEdu document primary → `direct_file` → `smartedu-resource@1.0.0`，前提是该 Provider 在当前部署实际注册。

“配置里存在”不等于平台生产可用；真实网络、认证、策略和内容获取仍由 0028 验收。

## 3. 正文网页与 landing page

0037 修正了此前真实 E2E 暴露出的语义问题：

- 如果网页本身就是用户选择的文章/正文资源，它可以是：

```text
kind=webpage
role=primary
scope=primary_resource
strategy=web_materialize
```

- 如果网页只是导航、详情、预览或跳转入口，则仍然是：

```text
role=landing
scope=landing_page
```

`web_materialize` 是“如何保存网页”的执行机制，不决定这个网页在业务上是 primary 还是 landing。

## 4. `source_fingerprint` 与文件元数据

`source_fingerprint` 继续保留，但只承担资源身份与 Resolution cache 关联作用。它不是 Plan、Job 或 Outcome 的权威凭证。

文件 `sha256` 和 `byte_size` 继续作为 Asset 元数据、索引和现有去重信息保存，但按照 0030 的既定决定：

- 不因为 Provider 声明大小与实际大小不一致拒绝已经生成的文件；
- 不因为声明 SHA-256 与实际文件不一致拒绝文件；
- 不恢复每资源/Bundle 下载字节上限作为通用获取门禁。

网页解析自己的内存/DOM/图片数量等资源保护边界属于具体处理器实现，不等同于通用文件下载大小门禁。

## 5. 公共 MCP 工具

公共 Tool 数量不变，仍为 13 个：

| 工具 | 作用 |
| --- | --- |
| `resource_flow_start` | 创建 FlowTask |
| `resource_flow_status` | 恢复当前 Flow 快照 |
| `resource_search` | 搜索并保存不可变 ResultSet |
| `resource_presentation_save` | 固化实际展示集合和顺序 |
| `resource_selection_save` | 保存用户选择 |
| `resource_download_prepare` | 基于 Selection + fresh Representation 生成 Plan |
| `resource_download_start` | 用户确认后重验证并创建 Job |
| `resource_job_status` | 查询 Job、Outcome、Asset/Bundle |
| `resource_job_cancel` | 请求取消 Job |
| `resource_archive` | 归档 ready Asset |
| `resource_library_search` | 查询资料库 |
| `resource_browse_creator` | 浏览创作者内容并形成 ResultSet |
| `resource_inspect` | 核验候选并产生/刷新 Resolution |

`resource_download_start` 不再接受 `authority_digest`。Prepare 的 PlanItem 和 JobStatus 的 Outcome 也不再暴露 capability/readiness/eligibility 或多层 binding digest。

## 6. 仍然保留的业务与安全不变量

简化获取链不等于取消必要边界。以下规则继续保留：

- 下载严格执行 `prepare -> 用户明确确认 -> start`；
- Agent 不能提交任意本地路径、脚本、解释器或 Provider 来替代服务端 Plan；
- Selection / Presentation / Plan 版本与幂等关系仍由服务端校验；
- 有显式 Representation evidence 时，Prepare 和 Start 都要求 evidence 当前有效；
- Start 必须再次读取 Resolution，确认 representation 仍存在且关键语义没有漂移；
- Router 只执行 Plan 中的 exact Provider，不因失败静默切换 generic Provider；
- Job 支持 queued/running/cancelling/succeeded/failed/cancelled；
- Asset 必须由服务端任务目录生成，归档只接受 `asset_id`；
- SSRF、逐跳重定向、受控输出目录、取消、超时、内容类型与真实格式检查继续保留；
- 不绕过登录、验证码、付费墙、DRM 或明确访问控制。

## 7. SQLite migration 8

migration 8 新增三张 Active 获取表：

```text
acquisition_plan_items
job_items
execution_outcomes
```

它们只保存业务执行所需字段，不包含 Descriptor/Readiness/Eligibility/digest 列。

为了已有 v7 数据可恢复，migration 8 会从旧 `download_plan_items`、`job_execution_items`、`acquisition_outcomes` 做一次降维 backfill。旧 v6/v7 authority 表目前仍可能存在于升级后的 SQLite 中，但 0037 Active 新路径不再向这些表写入新的 authority 事实。

后续完成兼容期后，应通过独立 cleanup migration 删除不再被读取的旧表，而不是让两套模型长期共存。

## 8. 当前代码过渡边界

0037 当前采用安全切换而不是一次性重写所有成熟逻辑：

- `server.py` 已指向 `simple_service.ResourceService`；
- `simple_service.py` 复用旧 Service 中成熟的搜索、Inspect、任务取消和归档辅助逻辑，但覆盖获取初始化、Prepare、Start 和 Outcome projection；
- `simple_storage.py` 复用旧 Store 的检索、Resolution、Asset/Archive 基础能力，但覆盖获取 Plan/JobItem/Outcome 和归档关系校验；
- `acquisition/simple.py` 保留旧 Provider 的类型兼容，但 Provider-facing 输入已经不再暴露 authority 字段；
- 0037 前的 `capability.py`、旧 acquisition authority 表和部分旧测试仍存在源码中，尚未物理删除。

因此当前正确描述是：**Active 获取状态已经简化，历史实现仍处于待清理兼容期**，不能声称整个仓库已经彻底删除所有旧 authority 代码。

## 9. 检索边界

检索侧保持既定分权：

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> Resolution / Representation facts
Skill -> private SemanticReview -> Gap -> StopDecision
```

候选数量、标题命中、平台数量和 coverage 不能单独触发 Present。常规任务仍由 Skill 在有限轮次内决定 Replan / Clarify / StopWithGap / Present。

`retrieval/adaptive.py` 继续只作为离线 calibration/helper，不成为生产语义裁判。

## 10. 当前执行顺序

当前优先顺序调整为：

1. **0037 Acquisition State Simplification**：完成 Active 获取模型切换、契约同步、兼容清理和定向验证；
2. **0028 Real OpenClaw and Real Platform E2E**：用简化后的模型重新跑 Search → Inspect → Present → Select → Confirm → Acquire → Archive → Recover；
3. **0029 Retrieval Benchmark and Release Gate**：建立检索质量和真实业务行为发布门禁；
4. 平台能力扩展、Library/Viewer 与后续部署。

0036 中“先恢复平台能力再决定是否减法”的顺序已被 0037 的产品决策覆盖；0036 中具体平台恢复目标仍可继续使用，但不能重新扩展旧 capability authority 链，也不能重新引入 0030 已删除的通用文件大小/哈希验收门禁。

## 11. 已完成验证与未验收项

0037 已完成一次隔离 GitHub Actions 定向验证：

- Python 3.12 环境安装当前 MCP 包成功；
- active package `compileall` 成功；
- `contracts/` 下 JSON 全部可解析；
- 0037 定向测试通过，覆盖：简化 Request、正文网页 primary route、migration 8、新表无 authority digest、Start 签名无 `authority_digest`、下载相关公共 Schema 不再暴露旧链。

仍未完成：

- 全仓旧 authority 专项测试的清理/迁移；
- 旧 `capability.py` 与 v6/v7 authority 表的物理删除；
- 真实 OpenClaw 端到端重新部署与用户闭环；
- SmartEdu 有效会话下真实 Search/Inspect/Acquire；
- Bilibili、Douyin、Ximalaya 等平台 Provider 的后续正式接入；
- 0029 benchmark/release gate。

## 相关入口

- [工作区入口](../README.md)
- [文档导航](README.md)
- [唯一 evergreen 开发路线](DEVELOPMENT_PLAN.md)
- [Retrieval Authority ADR](RETRIEVAL_AUTHORITY.md)
- [0037 当前计划](../.agent/plans/0037-acquisition-state-simplification.md)
- [机器契约目录](../mcp/education-resources/contracts/README.md)
- [历史归档索引](archive/README.md)
