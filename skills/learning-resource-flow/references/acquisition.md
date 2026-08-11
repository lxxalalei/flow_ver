# Acquisition Guidance

本文件负责用户选择后的获取流程、Capability 权威链、确认边界和结果解释。

## 前置条件

只有当前 Presentation 中用户明确选择的资源，才能进入 `resource_selection_save` 和后续获取准备。ResultSet 中未展示的候选不能直接下载。

## 强制流程

```text
Presentation
  -> user selects
  -> resource_selection_save
  -> resource_download_prepare
  -> 向用户展示计划、范围和已知限制
  -> 用户明确确认
  -> resource_download_start
  -> resource_job_status / cancel
  -> validated Asset / AssetBundle
  -> optional Archive
```

不得跳过用户确认，也不得把“用户之前说想要这个资源”自动解释为对当前 Plan 的确认。

## 向用户解释当前 Plan

`resource_download_prepare` 成功后，只解释 MCP 当前实际返回并会影响用户决定的事实，例如：

- 这次准备获取的是哪些已选资源；
- scope 是 `primary_resource`、representation、landing page 还是 metadata；
- 已确认的 representation / container / format；
- 服务端返回的大小预算、有效期/expiry、认证或策略限制；
- warning、风险或明确声明的能力缺口。

某字段没有返回就保持未知，不用平台常识或旧能力表补齐。Plan 只承诺它实际绑定的 scope；landing page 计划不能说成资源本体下载。

用户不需要看到 `plan_id`、digest、confirmation token、Provider 内部名或原始 Plan JSON。确认问题应针对用户刚看过的实际计划，而不是一个抽象的“是否继续”。

## Capability Authority

获取执行必须沿同一条可追溯链：

```text
Capability Descriptor
  -> Deployment Readiness
  -> persisted Resolution / Representation
  -> Eligibility
  -> PlanItem + authority_digest
  -> fresh ExecutionItem
  -> exact Provider
  -> persisted Actual Outcome
  -> Asset / AssetBundle
```

Platform Registry、平台名、资源类型、文件扩展名、旧 options 或搜索结果都不能单独决定 Provider、strategy 或 scope。

## Acquisition Scope

解释能力时区分：

- `primary_resource`：真正的主要资源本体；
- `representation`：同一逻辑资源的另一种可用表示；
- `landing_page`：资源承载/介绍页面；
- `metadata`：描述、版本、目录等元数据。

绝不能把 landing page / metadata 冒充 primary resource。

## Provider 与 fallback

Plan/Execution 绑定 exact Provider。Provider 失败时保留真实失败，不允许未经声明切换 Generic、其他平台、其他 scope 或其他 strategy 来制造表面成功。

`web_capture` / web materialization 是明确的获取机制，只在当前 descriptor、readiness、representation 和 policy 允许时执行，不是所有平台失败后的兜底。

## 幂等、变更与重新确认

- 同一个逻辑请求因超时/响应丢失而重试时，复用该请求原有的 idempotency key；请求参数、选择或操作目标发生变化时使用新 key。
- Tool 返回结构化失败时，不假定对应状态转换已经成功。响应不确定时先查询 Flow/Job 等服务端事实，再决定是否重试。
- 用户修改 Selection、建立新的 Presentation、Plan 过期/失效或服务端重新校验发现冲突时，不沿用旧 Plan/确认；重新 `resource_download_prepare`，向用户展示新的实际计划并再次获得明确确认。

## Job 与结果

Job 是异步状态，可能 queued/running/cancelling/succeeded/failed/cancelled；Bundle 可以 partial，但 partial 不等于 Job 新状态。

面向用户必须区分：

- 任务仍在执行；
- primary 成功、companion 部分失败；
- primary 失败；
- AUTH_REQUIRED；
- dependency/provider unavailable；
- policy/permission blocked；
- unsupported。

只有服务端生成并验证的 Asset 才能视为获取产物。模型不得伪造 Outcome、Asset、路径或哈希。

## 恢复

重启、超时或对话中断后先查询 Flow/Job 当前事实。不要自动重放已经确认的网络副作用；需要重新执行时遵循服务端幂等和 Plan 有效性要求。

## 安全

不绕过登录、验证码、付费墙、DRM、版权或访问控制；不把 Cookie/Token/Secret 写入本 Skill、`education-resources` 或其他工具参数、日志、计划或仓库。唯一例外是用户明确指定平台、用途并授权后，由独立 session-manager 接受一次 canonical `resource_session_save` 输入；不得回显、混用 browser capture 或失败后自动重放。网络、重定向、大小、MIME/magic 和路径边界由 MCP 服务端强制执行。
