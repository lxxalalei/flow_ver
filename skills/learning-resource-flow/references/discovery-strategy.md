# 教育资源发现策略

## 从学习结果反推搜索

先判断 `resource_target`、`goal` 和显式 `constraints`：资源给谁用，以及用户希望使用后发生什么。
再决定搜索方向和查询。不要逐字段拼接关键词，也不要从旧平台清单反推需求。

`SearchDirection` 是为覆盖一个明确的学习目标、使用结果或决策缺口而选择的探索路线，
不是 query、platform 或 resource type。query 是执行文本，platform 是来源路线，resource
type 是结果形态；三者都不能代替方向。`user_role` 只影响交互方式，不推导内容方向；
方向由 `resource_target`、`goal` 和 `constraints` 决定。统一的多轮循环、轮次上限、Coverage、
Gap 和 StopDecision 见 [`adaptive-retrieval.md`](adaptive-retrieval.md)。

常见学习体验包括：

- 理解：讲解、图解、课程、文章、图书。
- 沉浸：故事、纪录片、音频、绘本、人物叙事。
- 观察：实验现象、过程记录、地图、图鉴、案例。
- 实践：实验、手工、项目、活动方案、生活任务。
- 巩固：练习、题卡、问答、互动工具。
- 表达：讲述、写作、绘画、模型、展示任务。

这些是探索方向，不是固定分类，也不是用户事实。

## 选择本轮方向

- 用户明确限定形态或具体使用条件时遵循它；任务很窄且单一形态足以完成时，只搜一个方向。
- 首轮默认规划 1–2 个 `SearchDirection`。每个方向选择 2–3 个直接相关的平台路线，
  每个平台 1–2 条 query；用户指定来源、硬约束或安全边界可以使数量更少。
- 每条 query 的目标召回预算为 5–10 条；首轮所有方向的 `new_unique` 不超过 30。预算是
  规划边界，不是实际计数；不得用 query 数量、候选数组长度或模型估算替代服务端 provenance。
- 用户未限定形态时，优先选择能产生不同学习价值的方向；不为了形式多样加入无关的课程、
  练习或文件。宽泛探索也受常规最多 3 轮、综合最多 4 轮限制。
- `resource_search` 每次只产生一个待审查的不可变 ResultSet，不产生展示集合。首轮使用
  `mode=replace`（省略即为 replace）；后续确需补齐 Gap 时使用 `mode=extend`，并传当前
  ResultSet 的 `base_result_set_id`。extend 由 MCP 复制 base、跨轮去重并返回新的 ResultSet，
  不得由模型手工拼接候选或混用旧 Presentation。
- 当前用户身份只影响交互方式。搜索方向始终由 `resource_target`、`goal` 和 `constraints`
  决定。

## 构造查询

一个有效查询通常包含：

1. 不可丢失的核心主题。
2. 本轮希望得到的内容或学习行为。
3. 用户已经提供、且确实改善召回的学习背景、具体使用条件、语言、来源或格式限定。

示例：

- `太阳系 小学生 图解 科普`
- `鸟类观察 儿童 记录卡 活动`
- `一年级 20以内加减法 基础练习 可打印`
- `儿童 防溺水 官方 安全教育`

不要加入"优质、权威、高赞、精品、必看、儿童友好、适合孩子"等无法由搜索词保证的评价词。`儿童`、`小学生` 等资源对象或用户已给出的学段词可以使用；质量、内容门槛和可信度留给候选审查。

同一目标需要换方向时，改变搜索任务本身，例如从“获得原理图解”改为“获得可跟做实验以
关闭实践缺口”，不要只替换近义词。新方向必须说明它要关闭的 Gap。

只在缺失的硬条件会实质改变资源范围时澄清，例如教材同步或册次匹配任务缺少必要范围。

### 可信站点定向搜索

当需求明确指向某类权威来源（教材配套、官方科普、安全教育、古诗文等），且宽泛搜索结果质量不足时，在查询末尾追加 `site:域名` 限定搜索范围。站点列表见 `site-whitelist.md`。

规则：

- 一次查询最多加一个 `site:`。
- 不确定该用哪个站点时不加，先做宽泛搜索。
- 用户指定来源时优先使用用户提供的站点。
- 安全、健康、心理主题优先加对应官方机构站点。

示例：

- `太阳系 科普 site:cdstm.cn` — 定向搜中国数字科技馆
- `春晓 赏析 site:gushiwen.cn` — 定向搜古诗文网
- `消防 安全 教育 site:119.gov.cn` — 定向搜国家消防救援局

## 领域策略

| 领域 | 高价值搜索方向 |
|---|---|
| 学科与知识 | 学段或知识点讲解、同步材料、练习；只有同步学习需要时加入教材版本。 |
| 自然与科学 | 原理解释、图解、观察、实验、博物馆或科普机构资源。 |
| 阅读与语言 | 绘本、分级阅读、朗读、故事和表达任务。 |
| 艺术与创造 | 操作演示、作品观察、活动步骤和可完成的创作任务。 |
| 情绪与心理 | 儿童友好故事、情绪识别、可实践方法和专业儿童发展科普。 |
| 生活习惯 | 清单、日常实践和儿童可用工具，避免只搜抽象说教。 |
| 安全教育 | 官方指南、演练、活动手册和可执行清单，关注儿童安全与模仿风险。 |
| 运动与健康 | 专业机构科普、规范动作和安全注意事项。 |

## 来源策略

- 涉及健康、安全、心理、灾害、人体或公共规则时，优先官方、专业机构和可核验原始来源。
- 学科同步优先公共教育平台、出版社和明确教材配套来源。
- 科学、人文、艺术探索优先博物馆、科技馆、图书馆、公共文化和专业科普来源。
- 实践经验和操作方法可以使用可靠教育者或机构内容，但要与事实性来源区分。
- 聚合页、转载和平台热度只能作为发现线索，不自动证明内容质量。
- 用户指定来源是约束；当前 MCP 未接入时如实降级到公开网页，不伪造平台搜索。

### 候选后的选择性核验

搜索只产生 Candidate。候选展示前读取 `inspection-strategy.md`，只将高潜、差异关键、
可用性不确定或下载前需要判断表示形态的少量候选送入 Inspection Gate；不要默认全量
调用检查，也不要因 ResultSet 有 URL 就把 URL 传给 Skill 或工具。

`resource_inspect` 只接受 `contract_version`、`flow_id`、`resource_id` 和
`idempotency_key`。服务端从当前 Flow 解析来源并执行安全边界；Skill 不传 URL、路径、
检查深度、批量 ID 或凭据，也不自行拼接 `resolution_status`、`availability` 或
`representations`。检查失败、未支持或未执行时，继续按未核验 Candidate 审查，不把它写成
已确认可用资源。

如果用户只是探索“有哪些”，优先保留搜索广度；如果用户要推荐或准备下载，再把会改变
选择的候选送入 Gate。完整决策表、失败恢复和用户用语见
[`inspection-strategy.md`](inspection-strategy.md)。

### 平台路线按需选择

规划或比较具体平台时，读取 [`platform-capabilities.md`](platform-capabilities.md)。其中引用的
[`platform-registry.json`](../../../mcp/education-resources/contracts/platforms/platform-registry.json)
`1.0.0` 只作为平台身份、检索、会话路由和历史 inspect/acquire 声明的机器 Registry，不是
当前 Tool catalog 1.5 的 acquisition 执行权威。静态执行声明来自独立的
[`capability-descriptors.json`](../../../mcp/education-resources/contracts/capabilities/capability-descriptors.json)，
其 `catalog_version`、`registry_version` 均为 `1.1.0`；实际执行仍必须同时满足当前 readiness、
持久化 Resolution/Representation、Eligibility 和不可变 Plan/Execution binding。

当前只有 `generic-direct`、`generic-web-materializer`、`smartedu-resource` 三条 exact route，
且所有 fallback 都关闭。0021/0022 的 Bilibili、Ximalaya、Douyin、Anna Downloader 只属于
历史实现与 Bundle 兼容事实；缺少 exact route 或任一运行时权威事实时必须保留结构化缺口，
不得让 generic Provider 接管。

平台选择仍由目标、resource_target 和显式 constraints 决定：先选与本轮学习结果直接相关的
少量检索路线，只有确有互补价值时才增加平台；不要因为 Registry 列出 16 个平台就无差别
全搜。平台声明和平台名称不构成相关性、可信度、儿童适用性、内容质量或可执行下载证据。

## 平台登录与搜索质量

MCP 搜索执行层会自动从 SessionStore 读取已保存的平台登录态。大部分平台无需登录即可搜索；
少数平台有登录态时结果更全面。搜索前不需要逐个检查登录状态，但在以下时机提醒用户：

### 平台登录分级

| registry auth mode / kind | 平台 | 处理方式 |
|---|---|---|---|
| none / none | generic, cctv, yixi, kepu, baiduwenku, runoob, nlc, open163, annas-archive | 注册表不要求会话 |
| optional / cookie | bilibili, zhihu, ximalaya, wechat | 先按公开路线搜索；是否需要登录以实际返回状态为准 |
| optional / token | smartedu | 先按公开路线搜索；需要令牌时按结构化状态处理 |
| required / cookie | douyin, weibo | 缺少合法会话时可能返回 AUTH_REQUIRED，按登录流程处理 |

该分级只描述会话与检索路由，不描述结果质量。平台的 resource types、creator browse、
Inspection 和历史 acquisition 声明按需查阅 platform-capabilities.md；当前 acquisition route
仍以 capability catalog + 运行时 authority chain 为准，不要在本节维护第二份平台能力清单。

### 何时提醒

1. **不阻塞首次搜索**：即使用户未登录任何平台，也先执行搜索，给出已有结果。
2. **结果不足时建议**：如果搜索结果明显偏少（如某平台返回 0-2 条），且注册表显示该平台
   需要或可选合法会话，提示“登录 XX 平台可能获得更多结果，是否现在登录？”
3. **用户主动指定平台时**：如果用户明确要求搜某个平台（如“去微博搜”）但实际返回
   AUTH_REQUIRED 或同类状态，直接提醒需要合法登录。
4. **不重复提醒**：同一会话中对同一平台只提醒一次；用户选择跳过后不再追问。

### 提醒方式

提醒不是搜索的前置条件，而是搜索质量的增强建议：

- 简短说明："zhihu 当前未登录，登录后可能获得更多结果。"
- 给出选择："可以先看现有结果，也可以先登录再搜。要登录吗？"
- 用户选择登录时，引导通过 session-manager 完成登录，然后重新搜索。
- 用户选择跳过时，直接使用现有结果继续。

## 搜索后的判断

每个 `SearchRound` 都要统一评估当前 ResultSet：

- 保留核心主题，没有被宽泛词带偏；候选能支持当前 `goal` 的学习结果。
- 没有被同一来源、相同内容或广告页占满；`new_unique` 和 duplicate 只看 MCP provenance。
- 对高风险主题包含可信来源线索；关键表示或可用性未知时识别为可能的 Gap，而不是猜测补齐。
- 读取服务端 `Coverage`、`Gap`、失败和信息增益事实（若该版本契约返回）；模型不能自行
  伪造 Coverage、provenance、候选计数或关闭 Gap 的记录。

如果存在可由新学习价值路线关闭的 Gap，按 [`adaptive-retrieval.md`](adaptive-retrieval.md)
选择 `Replan` 并用 extend；如果 Coverage 足够则选择 `Present`，先按
[`inspection-strategy.md`](inspection-strategy.md) 做选择性 Inspection，再展示并保存当前
ResultSet 的 Presentation。仍有必要 Gap 且没有有价值的下一步时选择 `StopWithGap`；只有
用户事实或硬范围缺失会实质改变方向时选择 `Clarify`。

连续 2 轮 `new_unique=0` 且没有 Gap closure 时停止继续搜索；常规任务最多 3 轮，综合探索
最多 4 轮。达到上限或继续搜索不会改变决策时也停止，不为了数量或让所有候选都有 Resolution
而继续召回/检查。新的 ResultSet 必须独立审查；实际展示并成功提交新 Presentation 后，旧
展示编号才不得继续使用。
