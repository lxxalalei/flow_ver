# Inspection Guidance

Inspect 的目标是确认“这个候选到底是什么、关键事实是什么、有哪些 Representation、当前可用性如何”，不是为了给所有搜索结果做全文抓取。

## 什么时候 Inspect

只检查会改变决策的少量高潜候选，典型情况：

- 搜索摘要不足以判断相关性、内容深度或版本；
- 用户有必须验证的硬约束；
- 同名/多版本资源需要确认 identity；
- 用户准备选择/获取，但 primary representation、格式、时长、版本、章节等关键事实不确定；
- Generic search 只给到 landing page，需要确认页面实际承载什么；
- 某候选是否可合法获取会直接影响推荐。

以下情况通常不需要 Inspect：

- 用户只做轻量探索，搜索摘要已经足以比较；
- 平台 Adapter 已返回足够可信且完整的事实；
- 该候选低潜，即使核验也不会进入展示/选择；
- Inspect 不能关闭任何当前 Gap。

## 权威边界

`resource_inspect` 只接受当前 Flow 已存在的 `resource_id`，不接受模型提供的任意 URL、Cookie、Token 或本地路径。

Inspection 产生或刷新独立的 Resolution/Representation 事实，不改写旧 ResultSet，也不自动把候选升级为“推荐”“可下载”或“primary available”。

## Inspection 后必须重审

Inspect 完成后重新读取当前事实，并重新做 SemanticReview / Gap 判断。不能沿用 Inspect 前的乐观结论。

可能的结果包括：

- 内容与目标匹配，可以进入 Presentation；
- 只确认到 metadata / landing page，不能承诺资源本体；
- 存在 concrete representation，可进入后续 Eligibility / Prepare；
- AUTH_REQUIRED / unsupported / policy blocked；
- identity/版本仍然模糊，需要 Clarify 或 StopWithGap；
- 内容不相关，淘汰候选。

## Inspect 预算

优先 Inspect Top-K 高潜候选，不全量检查。若连续检查无法关闭关键 Gap，应停止扩大 Inspect，改为 Replan、Clarify 或 StopWithGap。

## 安全

Inspection 不绕过登录、验证码、付费墙、DRM 或访问控制，不通过浏览器/CDP、Generic Web 或其他 Provider 偷偷替代被阻断的平台能力。
