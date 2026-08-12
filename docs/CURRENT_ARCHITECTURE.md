# 当前架构

> 快照日期：2026-08-12

## Active 边界

| 项目 | 事实 |
| --- | --- |
| 用户入口 | `skills/learning-resource-flow/` |
| MCP | `mcp/education-resources/`（Python stdio） |
| MCP metadata | `0.2.0` |
| 公共契约 | `contract_version=1.0.0` |
| Tool catalog | `catalog_version=1.6.0`，13 个领域 Tool |
| 分类 | `contracts/taxonomy/learning-v1.json` |
| SQLite | migration 9 |
| 获取服务 | `service.py` → `ResourceService` |
| 获取存储 | `storage.py` → `Store` |
| 获取规划 | `acquisition/planner.py` |
| 获取请求 | `acquisition/simple.py` → `AcquisitionRequest` |
| Provider 路由 | exact `(provider_id, provider_version)` |

## 主链

```text
用户自然语言
  -> learning-resource-flow Skill
  -> education-resources MCP
  -> Search / Inspect
  -> Resolution / Representation
  -> AcquisitionPlan
  -> 用户确认
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / Bundle
  -> Archive
```

## 业务状态

```text
FlowTask
  -> ResultSet -> Presentation -> Selection
  -> Resolution / Representation
  -> Plan / PlanItem
  -> Job / JobItem
  -> Outcome
  -> AssetBundle / Asset
  -> Archive
```

## 数据库

migration 1-7 保留旧表定义以支持旧库升级。migration 8 新增三张 acquisition 表：

- `acquisition_plan_items`
- `job_items`
- `execution_outcomes`

migration 9 物理删除旧 authority 表（`capability_readiness_snapshots`、`eligibility_decisions`、`download_plan_items`、`job_execution_items`、`acquisition_outcomes`）。

## ProviderSpec

Planner 内置以下 route（`DEFAULT_PROVIDER_SPECS`）：

1. SmartEdu document/video/audio → `direct_file` → `smartedu-resource@1.0.0`
2. Generic document → `direct_file` → `generic-direct@1.0.0`
3. Generic video → `direct_file` → `generic-direct@1.0.0`
4. Generic webpage (primary) → `web_materialize` → `generic-web-materializer@1.0.0`
5. Generic webpage (landing) → `web_materialize` → `generic-web-materializer@1.0.0`

ProviderSpec 存在不等于平台 production-ready。真实网络、认证、许可仍需 E2E 验证。

## 网页角色

正文网页（文章、教程、图文）：`kind=webpage, role=primary, scope=primary_resource, strategy=web_materialize`。

导航/预览页：`role=landing, scope=landing_page`。

`web_materialize` 只描述"如何保存网页"，不能把正文降级成 landing 或把 landing 冒充正文。

## 安全边界

- `prepare -> 用户确认 -> start`
- Agent 不能提交任意路径、脚本或 Provider 替代服务端 Plan
- Selection / Plan 版本与幂等关系由服务端校验
- Start 重新核验当前 Resolution / Representation
- Router 只执行 Plan 的 exact Provider；失败不 silent fallback
- SSRF、逐跳重定向、路径逃逸、取消、超时、MIME 检查保留
- 不绕过登录、验证码、付费墙、DRM 或访问控制
- Archive 只接受服务端 ready `asset_id`

## 搜索分权

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> Resolution / Representation facts
Skill -> private SemanticReview -> Gap -> StopDecision
```

## 公共 Tool

`resource_flow_start`、`resource_flow_status`、`resource_search`、`resource_presentation_save`、`resource_selection_save`、`resource_download_prepare`、`resource_download_start`、`resource_job_status`、`resource_job_cancel`、`resource_archive`、`resource_library_search`、`resource_browse_creator`、`resource_inspect`。

## 当前执行顺序

1. **0028** 真实 OpenClaw / 真实平台 E2E
2. **0029** 检索 benchmark 与 release gate
3. Platform Expansion / Library & Viewer / 部署
