# Inspection Guidance

Inspect 的目标是确认“这个候选到底是什么、关键事实是什么、有哪些 Representation、当前可用性如何”，不是为了给所有搜索结果做全文抓取或完成固定流程。

## 什么时候 Inspect

只检查会改变当前推荐、选择或获取决策的少量高潜候选。典型情况：

- 搜索摘要不足以判断相关性、内容深度或版本；
- 用户有必须验证的硬约束；
- 同名/多版本资源需要确认 identity；
- 用户准备选择/获取，但 primary representation、格式、时长、版本、章节等关键事实不确定；
- Generic search 只给到 landing page，需要确认页面实际承载什么；
- 某候选是否可合法获取会直接影响推荐；
- 用户明确要求公开、无需登录、可直接阅读或下载，需要实际 availability 事实。

通常不需要 Inspect：

- 用户只做轻量探索，搜索摘要已经足以比较；
- Adapter 已返回足够事实；
- 候选本身低潜，即使核验也不会展示；
- 你说不出 Inspect 哪个事实会改变下一步。

## 权威边界

`resource_inspect` 只接受当前 Flow 已存在的 `resource_id`，不接受模型提供的任意 URL、Cookie、Token 或本地路径。

Inspection 产生或刷新 Resolution/Representation 事实；它不会自动把候选升级为“推荐”“可下载”或“primary available”。推荐仍然由 Main Agent 根据用户目标判断；真正能否按某条 route 获取则在 Prepare/Start 阶段由服务端继续确认。

## ResultSet 更新后的 Inspection

成功补搜后会产生新的 immutable ResultSet。旧 ResultSet 上的 Resolution 不应被模型当作新快照的当前事实。

因此：

- 优先在搜索基本收敛后，对准备展示/获取的高潜项做最终 Inspect；
- 如果补搜后需要继续依赖某个候选的 Inspect 事实，从当前 Search 响应或 `resource_flow_status` 取得当前 `resource_id`，再按当前快照核验；
- 不从旧聊天文本或标题猜当前 ID，也不假定旧 Resolution 自动迁移。

这只是保持服务端事实对应当前 ResultSet，不需要把 Inspection 变成额外状态机。

## Inspect 后重新判断候选

拿到新事实以后重新问：

- 这个候选是否仍然真的帮助用户完成目标？
- 原来不确定的关键事实有没有被确认？
- 它是资源本体、representation、landing page 还是 metadata？
- 当前 availability/认证/策略限制是什么？
- 现在是否足以展示、选择或进入 Prepare？

常见结果：

- 内容匹配且关键事实足够，可以进入 Presentation；
- 只确认到 metadata / landing page，不能承诺资源本体；
- 存在 concrete representation，可在用户选择后进入 Prepare；
- `AUTH_REQUIRED` / unsupported / policy blocked；
- identity/版本仍然模糊，需要用户确认关键分叉，或如实说明当前无法确认；
- 内容实际不相关，淘汰候选。

不要沿用 Inspect 前的乐观结论。

## 结果语义边界

- `FEATURE_NOT_SUPPORTED` / unsupported：当前没有可用 Inspector 路线，不等于资源不存在、无价值或一定不可用；只能说当前未核验。
- Inspection 只确认到部分事实：明确哪些仍 unknown，降低承诺强度，不用标题、平台名或模型推断补齐。
- 没有形成足够 Resolution：保持“暂未核验”，不能改写成“应该可用”或“已经失效”。
- `AUTH_REQUIRED`：需要合法会话后再确认；不改走 Generic/browser 路线绕过。
- policy blocked：保留真实策略阻断。
- 缓存/历史 Resolution：只按服务端返回的记录时间和实际字段使用，不能说成“刚刚重新检查”。

## 公开/无需登录

如果用户把“公开”“无需登录”“可直接阅读/下载”作为 must，搜索命中不够。

准备把候选计入满足条件的推荐时，应以当前 Inspect/Resolution 的 availability 为准。`AUTH_REQUIRED`、paywall、blocked、unresolved 均不能作为满足该 must 的候选。

这些受限结果仍可在编号候选之外解释为“相关但当前不满足访问条件”，不要为了凑数量弱化用户条件。

## Inspect 数量

先检查最可能影响决策的高潜项，不设固定 Top-K 数字作为形式要求。

如果连续 Inspection 没有让你更接近用户目标，先检查是不是搜索方向本身错了、需要换来源/补搜，或用户有一个真正需要澄清的关键分叉；不要继续扩大 Inspect 只是为了覆盖更多候选。

## 与下载的边界

Inspection 确认“现在看到的资源/表示事实”。它不是下载授权，也不替代 `resource_download_prepare`。

用户选择之后，Prepare 根据当前 Selection、fresh Representation 和 exact Provider runtime 生成实际获取计划；只有用户确认当前 Plan 后才 Start。

## 数据面边界

Inspection 不通过浏览器/CDP、Generic Web、curl、exec 或其他 Provider 偷偷替代被阻断的平台能力。资源核验事实仍只来自 `education-resources` 当前业务 Tool。
