# Retrieval Guidance

本文件负责自适应检索、候选语义审查、Gap 与 StopDecision。生产权威边界以 [`docs/RETRIEVAL_AUTHORITY.md`](../../../docs/RETRIEVAL_AUTHORITY.md) 为准。

## 权威边界

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> Resolution / Representation facts
MCP Plan / Job / Outcome / Asset -> acquisition facts
Skill reads facts + task context -> private SemanticReview
Skill -> private Gap -> one StopDecision
```

MCP factual `coverage` 只说明服务端实际观察到的候选、来源、去重、失败等事实，不表示任务已经语义满足。Skill 的 `SemanticReview`、`Gap`、`StopDecision` 不写入公共 MCP 状态。

## 搜索前语义检查

开始首轮 Search 前，不生成新的 Intent Schema，也不要求填满字段；只在模型私有推理中按需确认以下问题：

1. 用户真正想解决的核心问题/主题是什么？
2. 期望结果是什么：理解、练习、观察、实践、比较、表达、找版本、找可获取文件，还是其他？
3. 资源实际给谁使用？OpenClaw 当前会话或上层用户记忆/上下文是否已经提供与该对象明确对应、且真的会影响检索的背景？
4. 有哪些显式 must / prefer / exclude？
5. 用户是否明确指定资源载体、内容形态、文件格式、版本、语言或来源？
6. 这是普通推荐还是明确要求全面比较？

这些只是搜索规划检查项，不是必填槽位。未知信息如果不会改变当前路线，直接省略。

资源 Skill 只消费当前可见的可靠用户背景，不拥有这些背景的长期存储。不得为了检索新增年龄/年级/Profile 等 MCP 状态，不从搜索结果反向构建用户画像，也不把本轮模型推断写回 OpenClaw 长期记忆。

模型为了提高召回而提出的资源形态、内容切面、学习方式或来源属于**召回假设**，可以进入 SearchDirection/query，但不能被当成用户事实或约束。

如果当前问题存在几条实质不同的用户目标路线，而且 1–2 个首轮 SearchDirection 无法低成本覆盖，先按 `conversation.md` 澄清一个最关键分叉；如果只是主题较宽但可以有界探索，直接搜索。

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

首轮通常规划 1–2 个方向。没有指定资源形态时，优先选择能够产生不同实际价值的互补方向，而不是近义 query。例如“火山科普”可首轮覆盖“原理理解 + 过程观察”；但若用户已经明确“只要可打印练习”，就收敛到一个方向。

每个方向如何分配主力/补充来源、如何生成平台化 query，见 `source-routing.md`。

建议预算：

- 每方向通常 1 个主力来源，必要时加 1–2 个真正互补来源；
- 每个平台每轮通常 1 个聚焦 query；只有两个检索范围确实不重叠且总容量留有空间时最多 2 个，更高优先级 query 放前；
- 常规窄主题或比较任务首轮 `replace` 显式设置 `resource_search limit=8`；
- `limit` 是新 ResultSet 的总容量，不是本轮新增配额；`extend` 通常按 `next_limit=min(20, base_count+8)` 增长，常见序列为 `8 -> 16 -> 20`；
- 常规任务最多 3 轮，明确要求全面横向比较时最多 4 轮。

这些是规划预算，不是需要模型伪造的实际计数。

## Query 规划边界

首轮 query 应服务于 SearchDirection 和来源职责，不追求“提前把所有可能性都搜完”。

高质量 query 的差异应来自真实搜索目标，例如：

- 原理解释 vs 过程演示；
- 同步讲解 vs 基础练习；
- 官方原始材料 vs 经验比较；
- 单篇朗读 vs 连续专辑；
- 普通网页理解材料 vs 可打印文件。

只替换同义词、追加“优质/精品/高赞”等词不能算新的方向。年龄、年级、教材版本、文件格式等只有用户明确要求，或 OpenClaw 当前上下文已提供且确实改善当前召回时才进入 query；背景不需要机械复制到每条 query。

Legacy 中“一个平台一开始生成多条 query”的做法不恢复。当前策略是：首轮少量高价值 query → 看真实 ResultSet → 从 Gap 决定下一条 query。这样搜索计划会随结果变化，而不是在搜索前一次性膨胀。

## Search / Extend

首轮使用 `resource_search mode=replace`。只有明确 Replan 且有当前 `base_result_set_id` 时才使用 `mode=extend`。

ResultSet 始终不可变；跨轮复制、去重和新快照由 MCP 完成，Skill 不手工合并候选。

`extend` 前从当前 Tool 结果或 `resource_flow_status.current_result_set.candidates` 取得 `base_count`。下一次 `limit` 必须大于 `base_count`，否则 base-first 总容量会占满新快照，本轮即使实际搜到新候选也不会进入 candidates。常规总容量上限为 20；已经达到 20 时停止 extend，并根据现有事实 Present、Clarify 或 StopWithGap。不得把 `platform_runs` 的 candidate count 当成候选已进入 ResultSet；只有新快照 `candidates` 中实际存在的项才能审查、Inspect 或展示。

`has_more=true` 只说明服务端还有未返回候选，不表示当前任务存在语义 Gap，也不构成自动翻页/继续搜索的理由。只有当前私有 Gap 仍存在，并且继续同一路线确实可能关闭它时，才继续取更多结果或 Replan。

每次 Replan 必须能回答两个问题：

1. 当前具体缺什么？
2. 下一条 SearchDirection / 来源 / query 为什么有现实机会关闭这个 Gap？

例如：

- 已有大量视频讲解，但缺用户要求的可打印练习 → 搜练习/文档方向，不继续扩 B 站近义词；
- 内容相关但来源可信度不足 → 补官方/专业机构或定向 `site:`；
- 理论资料够了但没有过程演示 → 补视觉演示来源；
- 用户要公开可读，但高潜项尚未核验 → 优先 Inspect，不因为“还可以搜”就继续 Search。

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

### 适用性与背景事实

`target_fit` 可以使用 OpenClaw 当前上下文已经提供、并与当前 resource target 明确对应的可靠背景，但这些背景不是资源系统自己的状态。年龄/年级确实会影响理解门槛、内容尺度或教材范围时可以参与判断；未知时不要自动判 fail，也不要因为缺年龄元数据删除所有候选。

如果候选覆盖不同年龄/阶段但都可能有价值，可以在展示时说明差异，让用户选择；只有年龄/阶段差异会使当前候选明显不可安全/有效使用且无法通过现有证据判断时，才形成 Clarify Gap。

多资源对象时只使用当前对象已经可见的背景，不跨对象迁移年龄、年级、偏好或使用场景；也不在本 Skill 内创建对象画像或 Profile ID 来解决这个问题。

### 候选比较边界

除上述私有审查维度外，在 `reasons` 和最终排序中还要比较两类会直接影响用户决策的因素，但不要因此建立新的公共字段或固定加权评分：

- **可信度**：作者/机构、原始来源和关键声明是否有可核验依据；官方或知名平台只能提高证据先验，不能自动证明相关、完整、适合当前用途或可获取。
- **互补性**：候选之间是否提供不同且有价值的内容/学习体验；不要让镜像、同系列或高度重复内容因为数量多而占满展示。

播放量、收藏量、平台热度只能作为辅助信号，不替代当前任务证据。证据不足但可能有独特价值的候选可以作为明确标注“信息不足/未核验”的备选，不靠猜测抬高，也不因元数据缺失机械删除所有长尾资源。

低相关结果不证明 query 被分词、截断或改写。只有 Search Tool 明确给出相应事实时才能这样解释；若请求 query 与 `platform_runs.query_runs.query` 一致，只能记录为当前召回/搜索质量 Gap，不能猜测 Adapter 内部原因。

以下候选通常不进入 Presentation：明显偏题、违反 must/exclude、空页/纯广告/明显失效且没有实际资源价值，或标题与摘要都不能提供基本相关证据且没有可行的进一步核验路线。

“公开”“无需登录”“可直接阅读”是用户明示时的 must constraint，不是来源名称或搜索命中即可证明的标签。计入用户要求的来源数量前必须 Inspect，并以当前 Resolution 的 availability 为准；`AUTH_REQUIRED`、paywall、blocked、unresolved 都不能计作公开可访问候选。它们可以在候选列表之外作为 Gap/受限备选解释，但不得为了凑 N 项进入该组 Presentation。仍有检索预算时围绕这个 Gap Replan；预算到顶时只展示真实满足的较少项并 StopWithGap。

## Gap

Gap 只表示“尚未满足/验证，并且会改变下一步搜索、推荐或获取决策”的必要条件。

有效 Gap 示例：

- 用户真正想走哪条学习路线仍不明确，而且不同路线会得到完全不同候选；
- 目标资源版本仍不确定且会影响选择；
- 当前候选都只有 landing page，但用户明确要求资源本体；
- 横向比较任务只覆盖一个来源族；
- 高潜候选是否包含所需内容仍无法判断；
- OpenClaw 当前上下文已知有多个资源对象，当前对象不明确且背景差异会明显改变内容适配。

无效 Gap 示例：

- 任意未知字段；
- 仅仅不知道年龄/年级；
- 任意低分；
- 还没搜过的所有平台；
- 与当前决策无关的元数据缺失；
- `has_more=true`；
- “可能还能找到更好的”但说不出具体缺口。

## StopDecision

每轮只作出一个：

- `Present`：当前事实和语义审查已经足以支持展示；
- `Replan`：存在可行动 Gap，且有明确下一条路线可能关闭它；
- `Clarify`：只有用户提供的最小必要事实才能继续；
- `StopWithGap`：仍有重要 Gap，但继续搜索没有安全/高价值路线，或预算已到上限。

不得仅因为“结果够多”或 `coverage.status` 看起来良好就 Present。

也不得因为“某个语义字段未知”就 Clarify。Clarify 必须对应一个真实决策分叉，并说明该事实会如何改变下一步。

连续两轮 `new_unique=0` 且没有关闭任何私有 Gap 时停止继续搜索；若事实和语义足够则 Present，否则 StopWithGap/Clarify。

## 展示边界

ResultSet 不是 Presentation。只有 Skill 实际向用户展示的有序子集，才能以完全相同顺序提交 `resource_presentation_save`。完整用户可见列表必须先于 Tool call 出现在消息中；内部计划、“接下来展示”或准备在 Tool 返回后输出都不算展示。若保存后在实际列表输出前超时，恢复时必须把该 Presentation 纠正为空或重新展示后保存。用户只能从当前 Presentation 选择。

不要默认展示或保存整个 ResultSet。违反 must/exclude 的项放在编号候选列表之外解释 Gap；高度重复、没有额外决策价值的同类页面只保留代表性子集。

展示项优先让用户看到真正影响选择的信息：标题、资源类型/来源、为什么匹配当前目标、重要限制或不确定性；需要用户自行打开原始公开页面时，可以使用 Candidate/Resolution 中实际返回的 canonical public URL，不从标题或平台名拼 URL。

如果适用阶段存在差异且确实影响选择，可以自然说明“更偏低龄入门 / 更适合已有基础 / 对应某年级同步”，但没有证据时不要伪造精确年龄标签。

`resource_presentation_save` 失败时，刚才的文本列表不能被当成可选择的权威 Presentation；先恢复服务端状态，必要时重新展示并保存，再邀请用户按编号选择。

只有 Presentation 保存成功后才邀请用户按编号选择。“全部”只表示当前 Presentation 中实际可见的全部位置，不包括隐藏 ResultSet 候选、旧 Presentation 或其他轮次结果。
