# Acquisition Guidance

本文件负责用户选择后的获取流程、Representation/Plan/Provider 边界、确认和结果解释。

## 前置条件

只有当前 Presentation 中用户明确选择的资源，才能进入 `resource_selection_save` 和后续获取准备。ResultSet 中未展示的候选不能直接获取。

获取依赖当前 Inspect 产生的 `Resolution / Representation`。搜索结果、平台名、标题、扩展名或模型常识不能替代当前 Representation 事实。

## 强制流程

```text
Presentation
  -> user selects
  -> resource_selection_save
  -> fresh Resolution / Representation
  -> resource_download_prepare
  -> 向用户展示实际 Plan 和限制
  -> 用户明确确认
  -> resource_download_start
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / AssetBundle
  -> optional Archive
```

不得跳过用户确认，也不得把“用户之前说想要这个资源”自动解释为对当前 Plan 的确认。

## Prepare 做什么

`resource_download_prepare` 只根据当前 Selection 和 fresh Representation 生成服务端 Plan。每个 PlanItem 只需要回答：

- 获取哪个 `resource_id`；
- 使用哪个 `representation_id`；
- scope 是 `primary_resource` / `representation` / `landing_page` / `metadata` 中哪一种；
- 使用哪个 strategy；
- 使用哪个 exact Provider；
- 预期 container / format；
- 当前已知风险或限制。

Prepare 不下载，不生成 Capability/Readiness/Eligibility 实体，也不生成多层 authority/binding digest。

## 向用户解释当前 Plan

Prepare 成功后，只解释 MCP 实际返回、且会影响用户决定的事实，例如：

- 这次准备获取哪些已选资源；
- 获取的是资源本体、另一种 representation、landing page 还是 metadata；
- 预期保存形式；
- 是否有认证、策略或 Provider 可用性限制；
- Plan 有效期和明显风险。

某字段没有返回就保持未知，不用平台常识补齐。

用户不需要看到 `plan_id`、`selection_digest`、`plan_digest`、confirmation token 或 Provider 内部名；这些只用于服务端状态与工具调用。确认问题应针对用户刚看过的实际计划。

## Acquisition Scope

必须区分：

- `primary_resource`：用户真正要的主要资源本体；
- `representation`：同一逻辑资源的另一种可获取表示；
- `landing_page`：承载、介绍、导航或预览页面；
- `metadata`：目录、版本、描述等元数据。

不能把 landing page / metadata 冒充 primary resource。

### 正文网页

网页不天然等于 landing page。如果网页本身就是用户选择的文章、教程、图文正文，它可以是：

```text
kind=webpage
role=primary
scope=primary_resource
strategy=web_materialize
```

只有导航、详情、预览、跳转入口才应作为 landing page。

`web_materialize` / `web_capture` 描述“怎么获取网页”，不决定网页在业务上是什么角色。

## Provider 与运行时检查

Provider 能力由服务端轻量 ProviderSpec 和当前部署注册决定，不维护 Descriptor → Readiness → Eligibility 的持久状态链。

Prepare 选择一条明确 route；Start 前服务端再次确认：

1. Selection / Plan 仍是当前版本；
2. Plan 未过期且确认令牌有效；
3. 当前 Resolution 仍属于同一资源；
4. `representation_id` 仍存在且关键语义未漂移；
5. Representation evidence 仍有效；
6. Plan 指定的 exact Provider 当前仍注册，并支持该 scope / strategy。

任一条件失败，应返回结构化失败并要求重新 Inspect / Prepare，而不是生成新的 Readiness/Eligibility ID 来维持旧计划。

## exact Provider 与 fallback

Plan 绑定哪个 Provider，Start 就执行哪个 Provider。Provider 失败时保留真实失败。

禁止在 Router 内根据平台名、资源类型、错误码或“看起来能用”静默切换到 Generic、其他平台、其他 scope 或其他 strategy。

如果确实需要改变获取路线：

```text
失败 / 事实变化
  -> 必要时重新 Inspect
  -> 重新 Prepare
  -> 向用户展示新 Plan
  -> 用户重新确认
```

`web_materialize` / `web_capture` 不是失败后的万能 fallback。

## `source_fingerprint`

`source_fingerprint` 只用于资源身份和 Resolution cache 关联。它可以帮助判断当前 Resolution 是否仍属于同一来源，但不是 Plan/Job/Outcome 的防伪凭证。

不要向用户展示它，也不要把它当作“远端内容可信”的证明。

## 幂等、变更与重新确认

- 同一个逻辑请求因超时/响应丢失而重试时复用原 idempotency key；请求语义变化时使用新 key。
- Tool 返回结构化失败或结果不确定时，不假定状态已经成功转换；先读取 Flow/Job 当前事实。
- 用户修改 Selection、建立新 Presentation、Plan 过期、Representation 漂移或 Provider route 变化时，不沿用旧确认。
- 重新 Prepare 后必须展示新的实际计划并再次获得明确确认。

## Job 与结果

Job 是异步状态：`queued / running / cancelling / succeeded / failed / cancelled`。

Bundle 的 `completion=partial` 表示同一资源的资产不完整，不创造新的 Job `partial` 状态。

面向用户必须区分：

- 仍在执行；
- primary 成功但 companion 部分失败；
- primary 失败；
- AUTH_REQUIRED；
- Provider/dependency unavailable；
- policy/permission blocked；
- unsupported。

Outcome 只记录实际执行结果，不是证明链。只有服务端返回的 ready Asset / AssetBundle 才能视为获取产物。模型不得伪造 Outcome、Asset、路径、大小或哈希。

## 文件元数据

文件 `sha256` / `byte_size` 可以作为 Asset 元数据、索引和去重信息，但不作为“声明值必须和实际值一致”的额外成功门禁，也不恢复通用下载体积上限。

仍然保留真正必要的文件/网络边界：受控输出目录、非空文件、真实格式/MIME、逐跳重定向、取消和超时。

## 恢复

重启、超时或对话中断后先读取 `resource_flow_status` / `resource_job_status`。不要从聊天文本猜 Plan/Job 状态，也不要自动重放已经确认的网络副作用。

若旧 Plan 无法按当前 Representation/Provider route 重验证，重新 Prepare/Confirm，而不是补造旧 capability authority 字段。

## 认证

登录不属于本 Skill 或 `education-resources` 的公共获取控制面。遇到当前 Tool 明确返回 `AUTH_REQUIRED` 时，暂停当前路径并交给独立 session-manager。

默认使用受控浏览器。只有用户主动提供合法 Cookie/Token、明确指定平台与用途并授权保存时，session-manager 才可执行一次 canonical direct import。

不要索取或代填账号、密码、验证码、短信码或 MFA。Cookie/Token 原值不得进入 `education-resources` Tool、日志、计划或仓库；不得回显、失败后自动重放或与同一次 browser capture 混用。
