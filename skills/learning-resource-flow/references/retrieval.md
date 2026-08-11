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

常见方向可以围绕用户希望获得的实际学习结果展开，例如：

- 理解：讲解、图解、课程、文章、图书；
- 沉浸：故事、纪录片、音频、绘本、人物叙事；
- 观察：过程记录、地图、图鉴、实验现象、案例；
- 实践：实验、手工、项目、活动方案、生活任务；
- 巩固：练习、题卡、问答、互动工具；
- 表达：讲述、写作、绘画、模型、展示任务。

这些只是帮助形成 SearchDirection 的语义模板，不是固定 taxonomy、用户事实或必须凑齐的资源类型。任务很窄时一个方向就够；不要为了形式多样而加入无关方向。

首轮通常规划 1–2 个方向。每个方向选择少量直接相关平台和查询，不无差别搜索全部平台。

建议预算：

- 每方向 2–3 个直接相关来源/平台；
- 每个平台每轮通常 1 个聚焦 query；只有两个检索范围确实不重叠且总容量留有空间时最多 2 个，
  更高优先级 query 放前；
- 常规窄主题或比较任务首轮 `replace` 显式设置 `resource_search limit=8`；
- `limit` 是新 ResultSet 的总容量，不是本轮新增配额；`extend` 通常按
  `next_limit=min(20, base_count+8)` 增长，常见序列为 `8 -> 16 -> 20`；
- 常规任务最多 3 轮，明确要求全面横向比较时最多 4 轮。

这些是规划预算，不是需要模型伪造的实际计数。

## Search / Extend

首轮使用 `resource_search mode=replace`。只有明确 Replan 且有当前 `base_result_set_id` 时才使用 `mode=extend`。

ResultSet 始终不可变；跨轮复制、去重和新快照由 MCP 完成，Skill 不手工合并候选。

`extend` 前从当前 Tool 结果或 `resource_flow_status.current_result_set.candidates` 取得 `base_count`。
下一次 `limit` 必须大于 `base_count`，否则 base-first 总容量会占满新快照，本轮即使实际搜到新候选也
不会进入 candidates。常规总容量上限为 20；已经达到 20 时停止 extend，并根据现有事实 Present、
Clarify 或 StopWithGap。不得把 `platform_runs` 的 candidate count 当成候选已进入 ResultSet；只有新快照
`candidates` 中实际存在的项才能审查、Inspect 或展示。

`has_more=true` 只说明服务端还有未返回候选，不表示当前任务存在语义 Gap，也不构成自动翻页/继续搜索的理由。只有当前私有 Gap 仍存在，并且继续同一路线确实可能关闭它时，才继续取更多结果或 Replan。

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

### 候选比较边界

除上述私有审查维度外，在 `reasons` 和最终排序中还要比较两类会直接影响用户决策的因素，但不要因此建立新的公共字段或固定加权评分：

- **可信度**：作者/机构、原始来源和关键声明是否有可核验依据；官方或知名平台只能提高证据先验，不能自动证明相关、完整、适合当前用途或可获取。
- **互补性**：候选之间是否提供不同且有价值的内容/学习体验；不要让镜像、同系列或高度重复内容因为数量多而占满展示。

播放量、收藏量、平台热度只能作为辅助信号，不替代当前任务证据。证据不足但可能有独特价值的候选可以作为明确标注“信息不足/未核验”的备选，不靠猜测抬高，也不因元数据缺失机械删除所有长尾资源。

低相关结果不证明 query 被分词、截断或改写。只有 Search Tool 明确给出相应事实时才能这样解释；
若请求 query 与 `platform_runs.query_runs.query` 一致，只能记录为当前召回/搜索质量 Gap，不能猜测
Adapter 内部原因。

以下候选通常不进入 Presentation：明显偏题、违反 must/exclude、空页/纯广告/明显失效且没有实际资源价值，或标题与摘要都不能提供基本相关证据且没有可行的进一步核验路线。

“公开”“无需登录”“可直接阅读”是用户明示时的 must constraint，不是来源名称或搜索命中即可证明的
标签。计入用户要求的来源数量前必须 Inspect，并以当前 Resolution 的 availability 为准；
`AUTH_REQUIRED`、paywall、blocked、unresolved 都不能计作公开可访问候选。它们可以在候选列表之外
作为 Gap/受限备选解释，但不得为了凑 N 项进入该组 Presentation。仍有检索预算时围绕这个 Gap
Replan；预算到顶时只展示真实满足的较少项并 StopWithGap。

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

ResultSet 不是 Presentation。只有 Skill 实际向用户展示的有序子集，才能以完全相同顺序提交
`resource_presentation_save`。完整用户可见列表必须先于 Tool call 出现在消息中；内部计划、“接下来展示”
或准备在 Tool 返回后输出都不算展示。若保存后在实际列表输出前超时，恢复时必须把该 Presentation
纠正为空或重新展示后保存。用户只能从当前 Presentation 选择。

不要默认展示或保存整个 ResultSet。违反 must/exclude 的项放在编号候选列表之外解释 Gap；高度重复、
没有额外决策价值的同类页面只保留代表性子集。

展示项优先让用户看到真正影响选择的信息：标题、资源类型/来源、为什么匹配当前目标、重要限制或不确定性；需要用户自行打开原始公开页面时，可以使用 Candidate/Resolution 中实际返回的 canonical public URL，不从标题或平台名拼 URL。

`resource_presentation_save` 失败时，刚才的文本列表不能被当成可选择的权威 Presentation；先恢复服务端状态，必要时重新展示并保存，再邀请用户按编号选择。

只有 Presentation 保存成功后才邀请用户按编号选择。“全部”只表示当前 Presentation 中实际可见的全部位置，不包括隐藏 ResultSet 候选、旧 Presentation 或其他轮次结果。
