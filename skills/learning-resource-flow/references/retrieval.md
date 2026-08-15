# Retrieval Guidance

本文件补充主 Skill 中多轮检索、候选审查、Inspect 与 ResultSet/Presentation 的必要细节。需求理解、来源选择和 query 设计仍以 `SKILL.md` 为主；这里不再要求模型维护 `SemanticReview / Gap / StopDecision` 形式状态机。

## 1. 多轮检索应围绕用户目标自然推进

每一轮只需要回答四件事：

```text
当前用户真正需要什么
  -> 这一轮最值得搜什么
  -> 真实结果是否有用
  -> 还缺什么，下一轮是否有明显不同的路线能补上
```

继续搜索前必须能具体回答：

1. 当前还缺什么？
2. 下一条 SearchDirection / 来源 / query 为什么比刚才更有机会补上？

如果只能说“可能还有更好的”“还有平台没搜”，就没有足够理由继续。普通任务通常 1–3 轮有意义搜索已经足够；用户明确要求全面横向比较时可以更广，但每一轮仍必须扩大真实检索空间或补充新的证据，不做近义词循环。

## 2. SearchDirection 是思考角度，不是新的状态模型

SearchDirection 只表达一个真实学习/资源价值，例如：理解形成原理、观察真实过程、找可打印练习本体、确认某个教材/图书版本、补充可信原始来源、找一个具体文件或资源表示。

它不是 query、platform、resource type，也不需要为了形式完整而固定生成几个。任务很窄时一个方向足够；宽一些时优先 1–3 个彼此互补方向。不要恢复 legacy 中“每个平台先生成多条 query”的前置扩散。

## 3. 首轮 Search 与后续补搜

当前 Public MCP 已把 ResultSet lineage 收回服务端：

- 新 Flow 首轮 `resource_search` 使用默认 `mode=replace`；
- 同一目标后续有明确缺口时使用 `mode=extend`；
- `extend` 自动绑定当前服务端 ResultSet，**不要提交或缓存 `base_result_set_id` / `task_version`**；
- ResultSet 仍是服务端不可变快照，跨轮复制、合并和去重由 MCP 完成；
- Flow 不确定时先用 `resource_flow_list` / `resource_flow_status` 恢复，不从聊天文本猜内部版本或 lineage ID。

这些只是 Tool choreography。不要围绕 replace/extend 设计语义，也不要向用户解释内部 ResultSet 版本。

## 4. `limit`、摘要与候选可达性

`resource_search.limit` 控制每个平台 Adapter 的返回预算，默认值为 `8`。普通研究型搜索优先使用这个小预算；只有用户明确要求更广枚举、结果数量本身就是任务目标，或当前缺口确实需要扩大召回时才提高。不要机械把 `limit` 拉到最大。

Public Search 会返回本轮实际产生的全部候选，但不再附带 ResultSet lineage、platform runs、provenance/coverage 等内部状态。候选摘要最多暴露 600 字，并用 `summary_complete` 明确区分完整摘要与 excerpt；当 excerpt 不足以改变判断时再 Inspect 高潜项，而不是为了拿全文去读取源码或内部 Store。

`resource_browse_creator` 属于枚举型任务：用户要求创作者清单时，列表中的候选仍保持可达，不为了省上下文隐藏后半段结果；但逐条长摘要不回灌上下文，必要时再 Inspect 某个具体条目。

不要：

- 因为前一个平台先返回很多结果，就认为后面的平台应该被全局截断；
- 为了“控制上下文”在 Skill 中另建一份隐藏 ResultSet 或手工复制全部候选；
- 因候选很多自动继续搜索；
- 为了恢复状态调用 `resource_flow_status` 后再期待它重放完整 Search 结果。

Presentation 可以只展示少量高价值候选；这是展示精选，不是删除服务端 ResultSet 数据。

## 5. 结果匹配：标题命中不等于满足需求

搜索之后首先问：**这些结果真的帮助用户完成目标吗？**

典型不匹配：用户要低龄启蒙却全是高年级课程；要可打印练习却全是视频；要特定版本却是其他版本；要孩子直接使用的材料却全是家长方法讨论；要实质内容却是聚合/广告/预览；要具体文件却只有介绍页。

需求已经清楚时，优先修正搜索角度、来源或 query；不要因为结果差就重新询问已经明确的信息。只有搜索结果暴露出真正未确认的用户分叉，而且不同答案会改变下一步时，才回到澄清。

## 6. 候选审查重点

只对准备比较、展示或可能 Inspect 的高潜候选做深入判断。至少考虑：

- relevance：是否真正围绕当前主题和目标；
- usefulness：拿到它以后能否完成当前任务；
- target fit：深度、语言、媒介和使用方式是否适合实际资源对象；
- constraint fit：是否满足 must / exclude；
- substantive：是否有真实内容，而非空页、聚合、广告、标题党；
- credibility：当前任务所需的作者/机构/原始来源证据是否足够；
- complementarity：与其他候选相比是否提供不同而有价值的内容；
- evidence level：当前只是 search metadata，还是已经通过 Inspect 得到更强事实。

允许 unknown。unknown 不等于通过，也不等于失败；没有证据不要靠平台名、播放量、标题命中或模型常识补齐。播放量、收藏量、热度可以作为弱辅助信号，不能替代相关性、适配性和可信度。

## 7. 用户背景只用于当前适配判断

候选适配可以使用 OpenClaw 当前上下文中已经可靠提供、且与当前 resource target 明确对应的年龄、年级、基础水平等背景。

不要因为候选没有年龄 metadata 就机械删除，不把本轮候选特征反向写成长期画像，不在多资源对象之间串用年龄/偏好，也不在资源 MCP 中新增 Profile 来解决对话上下文问题。

## 8. Inspect 只核验会改变决策的事实

Search 是发现；Inspect 是事实核验。只有某个事实会改变推荐、计数、选择或下载决策时才 Inspect 高潜候选，例如公开/无需登录要求、资源本体与 landing page 区分、真实文件格式、标题摘要不足、下载前需要 fresh Representation。

不要为了“流程完整” Inspect 全部候选。

### 公开/无需登录约束

用户明确要求公开、无需登录、可直接阅读或可直接下载时，这是 must constraint。搜索命中、来源名称或 URL 看起来公开都不能单独证明满足条件。只有当前 Inspect 的 availability 事实支持时，才能计入“已满足”的公开可访问候选。

`AUTH_REQUIRED`、paywall、blocked、unresolved 不得冒充公开可用。如果当前主要缺口只是可访问性核验，优先 Inspect 高潜项，而不是继续堆更多同类 Search 结果。

## 9. 下一轮搜索应该关闭具体缺口

好的补搜包括：已有讲解但缺可打印练习就转文档/PDF；已有理论解释但缺真实过程就转视频/实验；内容相关但可信度不足就补官方/专业原始来源；已找到书名但版本不清就转版本线索；只有 landing page 但用户要本体就 Inspect 或做更具体发现。

差的补搜只是近义词循环，例如：

```text
火山科普
火山知识
火山百科
儿童火山知识
```

## 10. 什么时候停止

以下情况通常应停止搜索并进入展示/说明：已有足够高质量且互补的候选；剩余不确定性应通过 Inspect 或用户选择解决；下一轮只能重复同一来源/query 空间；能力限制已明确；用户只是先看看且当前结果足够；连续补搜没有带来新的有用候选。

停止不等于声称“全网没有更好资源”，只表示当前证据足够做下一步，或当前条件下没有明显更好的继续路线。

## 11. 搜索部分失败时保持真实解释

某平台失败、某条 query partial 或当前结果为空时：某来源失败不等于资源不存在；不把搜索失败解释成下载/Provider 失败；不因为失败偷偷换 acquisition route；关键来源/条件无法满足时向用户说明当前限制。

低相关结果也不证明 Adapter 内部进行了错误分词、截断或改写。只有 Tool 明确返回相应事实时才能这样解释。

## 12. ResultSet 与 Presentation 必须区分

ResultSet 仍是服务端搜索快照，Presentation 是用户**实际看到的有序候选子集**。区别仍然重要，但 Agent 不再搬运 ResultSet/Presetation 版本句柄。

流程要求：

1. 完成候选判断；
2. 在回复中真正向用户展示有序列表；
3. 调 `resource_presentation_save(displayed_resource_ids=[...])`，只提交实际展示的资源 ID 和顺序；服务端自动绑定当前 ResultSet；
4. 保存成功后邀请用户按编号选择；
5. 用户选择后调用 `resource_selection_save(selected_positions=[...])`；服务端自动绑定当前 Presentation。

不要默认展示整个 ResultSet。高度重复或没有额外决策价值的内容只保留代表性候选；违反 must/exclude 的项不要为了凑数进入编号列表。

如果 Presentation 保存失败，刚才文本列表不能被当成可选择的服务端权威列表；先恢复当前 Flow，必要时重新展示并保存。

“全部”只表示当前 Presentation 实际可见的全部位置，不包括隐藏 ResultSet 候选、旧 Presentation 或其他轮次结果。

## 13. `resource_flow_status` 是恢复摘要，不是状态转储

FlowStatus 现在只返回当前阶段、任务、紧凑 candidate refs / Presentation、当前选择、Plan/Job 摘要、已 Inspect resource IDs 和 allowed actions。它故意不返回完整 candidates、Resolution evidence、selection/plan digest 或 execution route。

因此：

- 不要为了“拿回所有旧细节”重复调用 FlowStatus；
- 已有当前上下文时不做无意义的恢复调用；
- context compaction 后只恢复下一步真正需要的句柄；
- 如果尚未 Presentation 且紧凑 candidate refs 不足以继续判断，应按目标重新 Search，而不是读取源码或内部 Store。

## 14. 不要把自然判断重新变成状态机

内部当然需要判断现在够不够好、还缺什么、是继续搜、问用户、Inspect 还是展示。但不要再创建新的 `SemanticReview`、`Gap`、`StopDecision` 公共对象、持久状态或固定 JSON。它们只是 Main Agent 的自然推理，不是 MCP 的新事实来源。
