# 自适应检索循环

## 目的与统一语言

一次检索只回答“这条搜索路线返回了什么”，不能保证已经覆盖用户要解决的学习问题。
本参考把当前任务组织为一个有界循环：

```text
Plan -> Search -> Evaluate -> Inspect? -> Gap -> Replan / Present / Clarify / StopWithGap
```

术语严格采用仓库统一语言：

| 术语 | 在循环中的含义 | 不要混同为 |
|---|---|---|
| `SearchDirection` | 为覆盖一个明确的学习目标、使用结果或决策缺口而选择的探索路线 | query、platform 或 resource type |
| `SearchRound` | 在一次当前决策下，针对一个或多个 `SearchDirection` 完成并统一评估的一组有界检索 | 分页或单条 query |
| `Coverage` | 当前候选与核验证据对任务必要维度的满足程度 | 结果数量、召回率或相关性分数 |
| `Gap` | 尚未满足或尚未验证，且可能改变后续搜索、推荐或获取决策的必要条件 | 任意未知、任意失败或低分 |
| `InformationGain` | 一轮实际新增的决策价值：关闭关键缺口、新增可展示候选或新增互补来源 | 新鲜度、关键词命中或去重数量本身 |
| `StopDecision` | 评估后决定继续重规划、向用户澄清、进入展示或带缺口停止的结论 | “搜够了”或“没有更多结果” |
| `Replan` | 根据 `Coverage`、`Gap` 和 `InformationGain` 调整后续方向或来源路线，同时保留原目标和显式约束 | 翻页、换近义词或重新理解用户 |

`SearchDirection` 要说明“本轮要获得的学习价值或证据，以及它要关闭的缺口”。例如：
“获得一份能让孩子观察并记录现象的可跟做活动，弥补只有原理讲解的缺口”是方向；
“Bilibili 视频”“实验 query”或“video 类型”都不是方向。查询、平台和资源类型只是该方向
的执行参数或结果形态。

## Plan：先确定决策，不先拼平台

规划只使用独立的 `goal`、`resource_target` 和用户明示的 `constraints`：

- `goal` 决定希望用户最终理解、观察、实践、巩固、表达或完成什么结果。
- `resource_target` 决定资源给孩子使用、给家长参考，或保持未知；它不能由
  `user_role` 推导。
- `constraints` 保存明确的 must、prefer、exclude、来源、语言、格式、时间和使用条件。
- `user_role` 只改变交互方式，例如称呼、解释深度、是否提示成人监督和确认语气；它不推导
  学科、内容方向、平台或资源类型。

年龄和年级未知时不默认追问，也不把未知本身写成 `Gap`。只有教材同步、册次匹配或其他
明确必须定位学段的硬范围缺失时，才提出一个最小澄清问题；详见
[`intent-and-clarification.md`](intent-and-clarification.md)。

### 方向与首轮预算

首轮先建立 1–2 个 `SearchDirection`。用户已明确单一形态或路线时可以只有一个；
不要为了形式多样增加无关方向。每个方向的默认检索预算是：

- 选择 2–3 个与该方向直接相关的平台路线；用户指定平台或安全/权威来源约束可使数量更少。
- 每个平台准备 1–2 条 query；query 必须包含核心主题、要获得的学习结果和确实能改善召回的
  显式约束，不把“优质、权威、适合孩子、高赞”等评价词当作证据。
- 每条 query 的目标召回预算为 5–10 条。预算只是计划上限，不是实际候选数；实际计数必须
  以 MCP 返回的 provenance 为准。
- 首轮跨方向的 `new_unique` 不超过 30。若候选预算会超过该上限，减少路线或把互补方向
  延后到下一轮；不把结果列表长度当作 `new_unique`。

方向表至少在内部保存以下信息，不把它伪装成 MCP 权威状态：

| 字段 | 内容 |
|---|---|
| 方向说明 | 要获得的学习价值或证据 |
| 服务目标 | 对应的 `goal`、`resource_target` 或显式 constraint |
| 要关闭的 Gap | 已知且可能改变决策的缺口；首轮可以是待验证的决策假设 |
| 路线预算 | 2–3 个平台、每平台 1–2 个 query、每 query 5–10 |
| 成功信号 | 何种候选、表示或证据足以改变 Coverage/StopDecision |

方向名称可以是模型内部的短标签，但不是 `flow_id`、`search_run_id`、`result_set_id` 或
`resource_id`。若服务端返回 `direction_id`，只使用返回值；若当前契约没有该字段，不得
自行补造 per-direction provenance。

## Search：一轮只产生一个不可变 ResultSet

1. 首次任务先调用 `resource_flow_start`；已有 Flow、上下文压缩或工具响应丢失时先读
   `resource_flow_status`。只使用 MCP 返回的 `flow_id`、`task_version` 和当前 ResultSet。
2. 首轮调用 `resource_search` 时使用 `mode=replace`；省略 `mode` 的旧调用也等价于
   `replace`。它创建只包含本次检索结果的新 ResultSet。
3. Replan 后追加新路线时使用 `mode=extend`，并且必须传服务端返回的当前
   `base_result_set_id`。`base_result_set_id` 是当前 Flow 的 ResultSet 不可变快照 ID，
   不是 query、平台 ID、资源 ID 或模型生成的字符串。
4. `extend` 的语义是服务端复制 base 快照、执行新搜索、按服务端身份规则跨轮去重，生成一份
   新的不可变 ResultSet；它不修改 base，不由模型手工拼接候选。服务端返回新的
   `result_set_id`、版本和（如契约定义）新快照中的 opaque `resource_id`，只能使用这些返回值。
5. `extend` 的 `limit` 表示新快照的总容量，不是模型可以声称的每个平台或每条 query 的实际
   返回数。达到容量不等于 Coverage 已满足；查询和平台的真实计数以服务端 provenance 为准。
6. 每次新的搜索动作使用新的幂等键；同一个幂等键只接受服务端原响应 replay，不生成新的
   ID、候选、Coverage 或 provenance。旧 base、旧 Presentation 和旧 Selection 不得与新快照
   混合使用；要展示时只从当前 ResultSet 建立新的 Presentation。

`resource_search` 的输入只能使用当前契约允许的字段，例如 `search_tasks` 中真实的
`platform` 与 query、受支持的 filters、当前 `flow_id`/`task_version` 和服务端幂等键。
不能把方向说明、Coverage、Gap、候选计数、URL、路径、Cookie、Token 或自造 ID 塞进工具
请求。若服务端拒绝 `mode` 或 `base_result_set_id`，先按结构化错误恢复，不改用手工合并。

## Evaluate：先读事实，再判断缺口

搜索返回的是当前 ResultSet 的 Candidate。每轮统一评估：

1. 用 [`candidate-judgment.md`](candidate-judgment.md) 过滤明显偏题、不安全、违反硬约束和
   无实际价值的候选；不要把过滤数量写成 Coverage。
2. 读取 MCP 返回的 `search_run_id`、ResultSet 版本、platform/query runs、候选数、失败数、
   去重/身份事实和（契约提供时）`provenance`、`coverage`、`information_gain`。这些是审计
   事实，不由模型重算后写回工具或用户可见的权威 JSON。
3. Coverage 至少从任务必要维度判断：目标结果是否有候选支撑、显式 must 是否满足、
   `resource_target` 是否被正确覆盖、是否有足够可信的来源线索、候选是否互补，以及可用
   表示/获取是否会阻止下一步。不能用候选数量或相关性分数代替 Coverage。
4. 只把可能改变排序、推荐、可用性或下载计划的少量候选送入
   [`inspection-strategy.md`](inspection-strategy.md) 定义的 Inspection Gate；检查结果回来后
   再评估 Coverage/Gap。Inspection 是证据增强，不是把候选或 ResultSet 改写成已核验。

### Gap 判定

把“未知”升级为 `Gap` 需要同时满足：它是当前任务的必要条件、目前没有足够证据满足或
验证、并且补齐它可能改变下一次搜索、推荐或获取决策。典型 Gap 包括：

- 只有讲解材料，目标还需要能实际操作或练习的资源形态。
- 用户明确要求教材同步，但版本/册次/学段尚未定位。
- 候选看似相关，但关键的公开可用性、Representation 或合法获取条件会改变选择。
- 只有单一来源或高度重复候选，无法完成用户要求的比较或互补组合。
- 关键来源路线失败，且该路线是当前目标的必要证据来源。

下列情况单独不构成 Gap：年龄/年级未知但用户没有教材同步硬要求、单纯没有更多相似
标题、重复候选、与当前决策无关的元数据缺失，或一次可重试的网络失败。失败只有在影响
必要覆盖时才进入 Gap，并需在说明中保留失败原因。

## Gap 后的 StopDecision

每个 `SearchRound` 结束时只选择一个下一步：

| `StopDecision` | 适用条件 | 下一步 |
|---|---|---|
| `Present` | Coverage 足以支持当前目标，关键 Gap 已关闭或不影响选择，且已有可解释候选 | 选择性 Inspection（如需要）后实际展示当前 ResultSet，立即保存同一快照的 Presentation |
| `Clarify` | 缺少会实质改变方向的用户事实、资源对象或硬约束；搜索无法安全替用户决定 | 只问一个最小问题；教材同步等硬范围才问年级/册次，不为画像补问年龄 |
| `StopWithGap` | 仍有 Gap，但在当前来源、轮次或安全边界内没有足够有价值的下一步 | 说明已覆盖内容、未闭合 Gap、真实失败/限制及其影响；安全地展示可用候选或明确没有可推荐项 |
| `Replan` | Gap 很可能通过新的学习价值路线、互补来源或不同资源形态关闭，且仍未达到轮次上限 | 保留原 goal/resource_target/constraints，改变 SearchDirection 或来源路线，用 `extend` 继续 |

`Replan` 不是把同一 query 换几个近义词，也不是翻页。新方向必须明确它要关闭的 Gap；
若只是 provider 暂时失败，可以在同一方向选择有决策价值的受支持替代路线，但必须在
provenance/失败说明中区分重试和新方向。

## 轮次与停止上限

- 常规任务最多 3 个 `SearchRound`；用户明确要求全面探索、横向比较或多种互补形态时，
  综合任务最多 4 个。上限是整个当前决策的上限，不是每个平台各自的上限。
- 如果连续 2 轮 `new_unique=0` 且没有关闭任何 `Gap`，必须停止继续搜索。Coverage 足够时
  选择 `Present`，仍有必要 Gap 时选择 `StopWithGap`；不得为了数量再发起一轮。
- `new_unique`、duplicate、Gap closure 和失败计数必须来自 MCP 返回的 provenance/coverage
  事实。没有这些字段时只能说“无法确认新增量/闭合量”，不能伪造满足停止条件。
- 达到轮次上限时同样停止；Coverage 足够则 `Present`，否则 `StopWithGap` 或因必要事实
  缺失而 `Clarify`。硬安全边界、policy block 或无法合法获取时可提前 `StopWithGap`。
- provider 返回 0 条但自身失败或需要认证时，不把“0”解释成“没有资源”；先解释失败，
  再决定 `Replan`、合法登录后重试或 `StopWithGap`。

## 失败解释与恢复

| 事实 | 对用户的解释 | 循环动作 |
|---|---|---|
| `AUTH_REQUIRED` / `auth_required` | 该路线需要合法登录，不能据此断言资源不存在 | 交给独立 `session-manager`；成功后先读 Flow 状态，再用新的幂等键重试 |
| `FEATURE_NOT_SUPPORTED` | 当前平台或检查路线未接入，不等于资源不存在 | 保留未核验/不完整状态，换有决策价值的受支持路线或 `StopWithGap` |
| `policy_blocked` | 当前安全策略不允许继续核验或获取 | 不绕过策略、重定向或访问控制；寻找公开替代或 `StopWithGap` |
| `unavailable` | 当前检查显示入口/表示不可用 | 降低或撤下该候选，必要时用新方向寻找替代 |
| timeout、transport 或 provider `failed` | 本轮来源失败，Coverage 只到失败前的事实 | 只在能关闭 Gap 且仍在上限内时换路线/重试；不要把失败写成零召回 |
| `duplicate` | 结果与 base 或本轮已有候选相同，没有新增独立价值 | 不报为新候选；以服务端 `new_unique`/duplicate 事实评估信息增益 |
| stale/invalid `base_result_set_id` 或 mode | 当前快照已变更或请求不符合契约 | 读 `resource_flow_status`，取得新的当前 ResultSet；不得猜 ID 或手工合并 |

失败说明必须保留来源、状态和对 Coverage/Gap 的影响；不要用平台名、标题或模型常识
覆盖失败。结构化错误没有返回可支持的事实时，使用“本轮未能确认”，而不是“应该可用”。

## 权威状态与恢复

以下值只能来自 MCP 或 `resource_flow_status`：`flow_id`、`task_version`、`search_run_id`、
`result_set_id`、`result_version`、`resource_id`、`resolution_id`、`presentation_id`、实际
候选计数、duplicate/new_unique、服务端返回的 Coverage、provenance 和 failures。`Gap` 和
`StopDecision` 是当前循环基于 `goal`、`resource_target`、`constraints` 及上述事实作出的
语义判断；若服务端返回规范化值则以它为准，否则不得把模型判断伪装成 MCP 字段。模型可以
提出内部的方向假设和下一步判断，但不能创造这些 ID、计数或权威字段。

上下文压缩、工具响应丢失或 MCP 重启后：

1. 先调用 `resource_flow_status`，以当前 ResultSet、当前搜索运行摘要和当前 Resolution 为准。
2. 若找不到当前 base 或 provenance，就不要重建 extend、Coverage 或 new_unique；回到
   “未确认”状态并根据返回事实重新 Plan。
3. 若已有 Presentation/Selection，不能为了继续检索把它与新 ResultSet 混用；新快照必须
   重新审查、实际展示并保存新的 Presentation。

最终展示和选择的绑定规则仍见 [`mcp-workflow.md`](mcp-workflow.md)：只有当前 ResultSet 的
实际展示可以保存为 Presentation，只有当前 Presentation 的 positions 可以进入 Selection。
