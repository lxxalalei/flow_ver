# Acquisition Guidance

本文件负责用户选择后的获取流程、Representation/Plan/Provider 边界、确认和结果解释。

## 前置条件

只有当前 Presentation 中用户明确选择的资源，才能进入 `resource_selection_save` 和后续获取准备。ResultSet 中未展示的候选不能直接获取。

获取依赖当前 Inspect 产生的 `Resolution / Representation`。搜索结果、平台名、标题、扩展名或模型常识不能替代当前 Representation 事实。

## 强制流程

```text
Presentation
  -> user selects
  -> resource_selection_save(selected_positions)
  -> fresh Resolution / Representation
  -> resource_download_prepare(options?)
  -> 向用户展示实际 Plan 和限制
  -> 用户明确确认
  -> resource_download_start(plan_id, confirmation_token)
  -> Job
  -> exact Provider
  -> Outcome
  -> Asset / AssetBundle
  -> optional Archive
```

不得跳过用户确认，也不得把“用户之前说想要这个资源”自动解释为对当前 Plan 的确认。

## Public MCP 与内部绑定

Public MCP 不再要求 Agent 搬运：

- `result_set_id`；
- `presentation_id` / `presented_version`；
- `selection_version` / `selection_digest`；
- `plan_digest`；
- Inspect 的 `resolution_id` / source fingerprint / inspector version；
- Job 的 execution route / Outcome 细节。

这些事实仍保存在服务端，并继续参与原有一致性校验。删除的是 **Agent-facing 参数与结果噪音**，不是服务端校验。

因此不要从旧聊天文本、FlowStatus 或 Plan 输出中提取这些字段再传回 MCP。Presentation、Selection、Prepare 都使用当前 Flow 中的服务端权威状态。

## Prepare 做什么

`resource_download_prepare` 根据当前 Selection 和 fresh Representation 生成服务端 Plan。Agent 的公共调用只需要：

```text
flow_id + idempotency_key + optional options
```

服务端仍会读取当前 Selection / Presentation 绑定并执行版本、digest、Representation freshness 和 Provider route 校验。

PlanItem 内部仍要明确：获取哪个资源和 Representation、scope、strategy、exact Provider、container 以及风险。Prepare 不下载，不生成 Capability/Readiness/Eligibility 实体，也不生成新的多层 authority 状态链。

## 向用户解释当前 Plan

Prepare 成功后，只解释会影响用户决定的事实，例如：

- 这次准备获取哪些已选资源；
- 获取的是资源本体、另一种 representation、landing page 还是 metadata；
- 预期保存形式；
- 是否有认证、策略或可用性限制；
- Plan 有效期和明显风险。

用户不需要看到 selection/plan digest、内部版本、Provider version 等实现字段。`plan_id` 和 confirmation token 只用于后续 Tool 调用，不作为用户要理解的内容。

## Acquisition Scope

必须区分：

- `primary_resource`：用户真正要的主要资源本体；
- `representation`：同一逻辑资源的另一种可获取表示；
- `landing_page`：承载、介绍、导航或预览页面；
- `metadata`：目录、版本、描述等元数据。

不能把 landing page / metadata 冒充 primary resource。

网页不天然等于 landing page。如果网页本身就是用户选择的文章、教程、图文正文，它可以是 primary resource；只有导航、详情、预览、跳转入口才是 landing page。`web_materialize` 描述怎么保存，不决定业务角色。

## Provider 与运行时检查

Provider 能力由服务端轻量 ProviderSpec 和当前部署注册决定，不维护 Descriptor → Readiness → Eligibility 的持久状态链。

Prepare/Start 仍在服务端检查：

1. 当前 Selection / Plan 未变化；
2. Plan 未过期且确认令牌有效；
3. 当前 Resolution 仍属于同一资源；
4. `representation_id` 仍存在且关键语义未漂移；
5. Representation evidence 仍有效；
6. exact Provider 当前仍注册并支持该 scope / strategy。

失败应结构化返回并按需要重新 Inspect / Prepare，而不是 silent fallback 或补造 authority 字段。

## exact Provider 与 fallback

Plan 绑定哪个 Provider，Start 就执行哪个 Provider。Provider 失败时保留真实失败。禁止在 Router 内根据平台名、资源类型、错误码或“看起来能用”静默切换到 Generic、其他平台、scope 或 strategy。

需要改变路线时：

```text
失败 / 事实变化
  -> 必要时重新 Inspect
  -> 重新 Prepare
  -> 向用户展示新 Plan
  -> 用户重新确认
```

## 幂等、变更与重新确认

- 同一逻辑请求因超时/响应丢失而重试时复用原 idempotency key；请求语义变化时使用新 key。
- Tool 返回失败或结果不确定时，不假定状态已经成功转换；读取紧凑 Flow/Job 状态。
- 用户修改 Selection、建立新 Presentation、Plan 过期、Representation 漂移或 route 变化时，不沿用旧确认。
- 重新 Prepare 后必须展示新计划并重新确认。

## Job 与结果

Job 状态：`queued / running / cancelling / succeeded / failed / cancelled`。

`resource_job_status` 面向 Agent 只暴露：

- Job 状态；
- progress；
- ready Asset handles 与必要媒体元数据；
- 失败摘要；
- bundle completion（存在时）。

Provider route、Outcome execution projection、sha256 等内部/归档事实不再为了状态查询反复进入 Agent 上下文。完整事实仍由 Service/Store 保存。

只有服务端返回的 ready Asset / AssetBundle 才能视为获取产物。模型不得伪造 Outcome、Asset、路径、大小或哈希。

## 恢复

重启、超时或对话中断后：

- 用 `resource_flow_status` 恢复当前阶段和下一步句柄；
- 已有 `job_id` 时直接用 `resource_job_status`；
- 不要求 FlowStatus 重放整个 ResultSet/Resolution/Outcome；
- 不读取源码来恢复业务状态；
- 不自动重放已经确认的网络副作用。

若旧 Plan 无法按当前 Representation/Provider route 重验证，重新 Prepare/Confirm。

## 认证

登录不属于本 Skill 或 `education-resources` 的公共获取控制面。遇到当前 Tool 明确返回 `AUTH_REQUIRED` 时，暂停当前路径并交给独立 session-manager。

默认使用受控浏览器。只有用户主动提供合法 Cookie/Token、明确指定平台与用途并授权保存时，session-manager 才可执行一次 canonical direct import。不要索取或代填账号、密码、验证码、短信码或 MFA。Cookie/Token 原值不得进入 `education-resources` Tool、日志、计划或仓库。
