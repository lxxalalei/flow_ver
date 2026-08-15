# Inspection Guidance

Inspect 的目标是确认“这个候选到底是什么、关键事实是什么、有哪些 Representation、当前可用性如何”，不是为了给所有搜索结果做全文抓取或完成固定流程。

## 什么时候 Inspect

只检查会改变当前推荐、选择或获取决策的少量高潜候选。典型情况：搜索摘要不足；用户有必须验证的硬约束；同名/多版本需要确认；primary representation、格式、时长或版本不确定；Generic search 只给 landing page；可访问性会直接影响推荐；用户明确要求公开/无需登录/可直接阅读下载。

通常不需要 Inspect：轻量探索且摘要已经足够；Adapter 已返回足够事实；候选本身低潜；或者说不出哪个新事实会改变下一步。

## 权威边界

`resource_inspect` 只接受当前 Flow 已存在的 `resource_id`，不接受模型提供的任意 URL、Cookie、Token 或本地路径。

Inspection 在服务端产生或刷新完整 Resolution/Representation。Public MCP 只返回决策所需的紧凑事实：

- `resolution_status`；
- 资源标题/类型/摘要/creator/language（存在时）；
- availability；
- Representation 的 ID、scope、kind、container、MIME、role、大小、是否可 materialize/需认证等；
- 平台可用时的 `resource.creator_id`；
- warnings / failures / inspected_at。

Public 结果**不再暴露** inspector id/version/method、source fingerprint、evidence payload、resolution digest、capability_ref 等内部事实。它们仍可在 Service/Store 中参与缓存、重验证和调试，不需要进入 Agent 上下文。

## ResultSet 更新后的 Inspection

补搜后服务端会产生新的 immutable ResultSet。旧快照的资源 ID 不应被模型当成当前事实。

因此优先在搜索基本收敛后，对准备展示/获取的高潜项做最终 Inspect；补搜后继续核验时使用当前 Search 返回的 `resource_id`。`resource_flow_status` 只提供紧凑恢复引用，不保证重放完整旧 ResultSet；不要从旧聊天文本或标题猜 ID。

## Inspect 后重新判断候选

拿到新事实以后重新问：

- 这个候选是否仍然帮助用户完成目标？
- 原来不确定的关键事实是否被确认？
- 它是资源本体、representation、landing page 还是 metadata？
- availability/认证/策略限制是什么？
- 是否足以展示、选择或进入 Prepare？

可能的真实结果包括：内容匹配且事实足够；只确认到 metadata/landing page；存在 concrete representation；`AUTH_REQUIRED` / unsupported / policy blocked；identity 仍模糊；或者内容实际不相关。不要沿用 Inspect 前的乐观结论。

## 结果语义边界

- unsupported：当前没有 Inspector 路线，不等于资源不存在或一定不可用；
- partial/unknown：明确尚未确认的部分，不靠标题或模型常识补齐；
- `AUTH_REQUIRED`：需要合法会话后再确认，不改走 Generic/browser 绕过；
- policy blocked：保留真实阻断；
- 缓存事实：只能按 Tool 返回的实际时间使用，不能说成“刚刚重新检查”。

## 公开/无需登录

如果用户把“公开”“无需登录”“可直接阅读/下载”作为 must，搜索命中不够。准备计入满足条件的推荐时，应以当前 Inspect availability 为准。`AUTH_REQUIRED`、paywall、blocked、unresolved 均不能冒充满足条件。

## Inspect 数量

先检查最可能影响决策的高潜项，不设固定 Top-K。连续 Inspect 没有让结果更接近目标时，应检查搜索方向、来源或真正的用户分叉，而不是为了覆盖率继续扩大检查。

## 与下载的边界

Inspection 确认当前资源/表示事实，不是下载授权，也不替代 `resource_download_prepare`。用户选择后，Prepare 从服务端当前 Selection 和 fresh Representation 生成 Plan；只有用户明确确认该 Plan 后才 Start。

## 数据面边界

Inspection 不通过浏览器/CDP、Generic Web、curl、exec 或其他 Provider 偷偷替代被阻断的平台能力。资源核验事实仍只来自 `education-resources` 当前业务 Tool。
