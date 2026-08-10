# Retrieval Guidance

本文件负责自适应检索、候选语义审查、Gap 与 StopDecision。生产权威边界以 [`docs/RETRIEVAL_AUTHORITY.md`](../../../docs/RETRIEVAL_AUTHORITY.md) 为准。

## 权威边界

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect / Resolution / Readiness / Eligibility -> 独立事实
Skill reads facts + task context -> private SemanticReview
Skill -> private Gap -> one StopDecision
```

MCP factual `coverage` 只说明服务端实际观察到的候选、来源、去重、失败等事实，不表示任务已经语义满足。Skill 的 `SemanticReview`、`Gap`、`StopDecision` 不写入公共 MCP 状态。

## SearchDirection

`SearchDirection` 是为了覆盖一个明确目标或关闭一个关键 Gap 的搜索路线，不是 query、platform、resource type 或评分标签。

首轮通常规划 1–2 个方向。每个方向选择少量直接相关平台和查询，不无差别搜索全部平台。

建议预算：

- 每方向 2–3 个直接相关来源/平台；
- 每个平台 1–2 个 query；
- 每个 query 5–10 条目标召回；
- 首轮唯一候选通常不超过 30；
- 常规任务最多 3 轮，明确要求全面横向比较时最多 4 轮。

这些是规划预算，不是需要模型伪造的实际计数。

## Search / Extend

首轮使用 `resource_search mode=replace`。只有明确 Replan 且有当前 `base_result_set_id` 时才使用 `mode=extend`。

ResultSet 始终不可变；跨轮复制、去重和新快照由 MCP 完成，Skill 不手工合并候选。

## SemanticReview

只对准备比较、展示或需要进一步 Inspect 的高潜候选做语义审查。至少判断：

- relevance：是否真的围绕当前主题/目标；
- usefulness：是否能帮助用户完成任务；
- target_fit：是否适合实际资源对象/用途；
- constraint_fit：是否满足显式 must/exclude；
- substantive：是否有真实内容而非空壳、聚合、广告或标题党；
- evidence_level：`search_only` 或 `inspected`；
- reasons：简短说明证据和不确定性。

允许 `unknown`；unknown 不等于 pass。没有证据不能靠候选数量、平台名、标题命中或模型乐观推断升级为通过。

## Gap

Gap 只表示“尚未满足/验证，并且会改变下一步搜索、推荐或获取决策”的必要条件。

有效 Gap 示例：

- 目标资源版本仍不确定且会影响选择；
- 当前候选都只有 landing page，但用户明确要求资源本体；
- 横向比较任务只覆盖一个来源族；
- 高潜候选是否包含所需内容仍无法判断。

无效 Gap 示例：任意未知、任意低分、还没搜过的所有平台、与当前决策无关的元数据缺失。

## StopDecision

每轮只作出一个：

- `Present`：当前事实和语义审查已经足以支持展示；
- `Replan`：存在可行动 Gap，且有明确下一条路线可能关闭它；
- `Clarify`：只有用户提供的最小必要事实才能继续；
- `StopWithGap`：仍有重要 Gap，但继续搜索没有安全/高价值路线，或预算已到上限。

不得仅因为“结果够多”或 `coverage.status` 看起来良好就 Present。

连续两轮 `new_unique=0` 且没有关闭任何私有 Gap 时停止继续搜索；若事实和语义足够则 Present，否则 StopWithGap/Clarify。

## 展示边界

ResultSet 不是 Presentation。只有 Skill 实际向用户展示的有序子集，才能以完全相同顺序提交 `resource_presentation_save`。用户只能从当前 Presentation 选择。
