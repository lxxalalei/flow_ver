---
name: learning-resource-flow
description: 学习资源（图书、课程、视频、文章、教材、音频、练习等）的搜索、比较、获取与归档入口。先理解用户真正要解决的问题，再由模型决定搜索方向、来源和 query；education-resources MCP 负责资源事实、选择、下载和归档状态。
---

# Learning Resource Research

你的首要职责不是“走完 Flow”，而是**找到真正能帮助用户完成目标的学习资源**。

`education-resources` MCP 是资源后端；你是研究和决策者。不要从 Tool、平台清单或状态字段开始思考。先理解用户为什么找这些资源、什么结果才有用，再决定去哪里搜、搜什么、如何判断结果。

## 1. 分工

Main Agent 负责：需求理解、必要澄清、搜索角度、来源选择、query、候选判断、补搜决策和用户解释。

MCP 负责：Flow、ResultSet、Presentation、Selection、Resolution/Representation、Plan、Job、Asset、Archive 以及所有服务端状态校验和副作用。

只使用 MCP 实际返回的资源/Plan/Job/Asset 句柄和业务事实；不要猜测或补造。**不要把 MCP 的内部状态模型变成自己的思考模型，也不要充当数据库事务协调器。**

## 2. 搜索前先理解真正需求

不要把用户原话直接翻译成关键词。先在内部回答：

1. 用户最终想完成什么：理解、观察、练习、实践、比较、备课、找版本、找具体文件，还是别的？
2. 资源实际给谁用？当前上下文是否已有会明显改变内容尺度的可靠背景？
3. 什么样的结果才真正有用？
4. 哪些 must / prefer / exclude 会改变候选范围？
5. 是否存在一个关键歧义，使不同答案会导向完全不同的搜索？

未知信息如果不影响路线，不问。不要为了填满 `goal`、`user_role`、`resource_target`、`constraints` 追问。

只有不同回答会显著改变搜索方向、内容尺度、教材版本或筛选标准时才澄清。例如“物理启蒙”但学段未知值得问；“小学三年级太阳系资料”已经足够直接搜索；用户说“形式你看着办”“先看看”时不要把决定权退回去。

用户回答后重新理解整个目标，而不是只记录一个字段。

## 3. 从目标形成互补搜索角度

先想用户需要获得什么价值，再想平台。

常见角度包括：

- 理解：概念解释、图解、系统讲解；
- 观察：真实过程、动画、纪录片、实验现象；
- 练习：题卡、习题、可打印任务；
- 实践：实验、手工、项目、活动方案；
- 沉浸：故事、朗读、人物叙事；
- 比较/判断：方法、版本差异、经验、原始证据；
- 获取具体资源：书名、版本、ISBN、文件或详情页线索。

这些不是固定 taxonomy，也不需要凑齐。窄任务一个角度即可；较宽任务通常 1–3 个真正互补的角度。

`火山 / 火山知识 / 火山科普 / 儿童火山科普` 不是四个方向；“喷发原理理解”和“喷发过程观察”才是不同方向。

## 4. 来源派发由内容/证据需求驱动

不要为了平台覆盖率机械扩散。

- 视觉讲解、动画、实验、真实过程、纪录片 → 视频/公共媒体生态；
- 系统课程、同步知识点、教材体系 → 结构化教育生态；
- 故事、朗读、听书、连续音频 → 音频生态；
- 方法、经验、比较、概念辨析 → 问答/社区/专业网页；
- 专业科普、原始说明、官方材料 → 科普机构、官方/专业 Web；
- 图书、版本、作者、ISBN、古籍 → 图书目录、古籍/公版来源；
- PDF、讲义、课件、练习、具体文件 → 文档来源、Generic Web；
- 长尾站点或未单独接入站点 → Generic Web。

具体平台生态见 [`references/source-routing.md`](references/source-routing.md)。实际平台 ID、登录状态、Inspect/Acquire 能力以 MCP schema 和返回事实为准；Skill 不维护第二份机器 Registry，也不猜未注册 ID。

一个角度通常一个主力来源；只有另一个来源能提供明显不同价值时才补充。

## 5. Query 要像这个来源里的真实搜索

Query 应体现“主题 + 当前要解决的切面”，只在确实影响召回时加入年级、版本、格式、语言等条件。

不要靠“优质、精品、高赞、权威、适合孩子”等评价词替代后续判断。

- 视频：突出过程、动画、实验、纪录片、操作；
- 音频：朗读、故事、跟读、听书、专辑；
- 教育平台：学段、学科、知识点、单元、教材版本；
- 图书来源：书名、主题、作者、版本、ISBN；
- Generic Web：主题 + 用途/内容切面，必要时 `site:` / `filetype:`。

同一来源首轮通常只发最有价值的一条 query。先看真实结果，再决定是否补搜。

## 6. 搜完判断“有用”，不是判断“有结果”

候选多不代表任务完成。对准备推荐的候选重点判断：

- 是否真正相关；
- 是否能帮助用户完成目标；
- 是否适合实际使用者；
- 是否满足 must / exclude；
- 是否有实质内容而非聚合、广告、空壳详情；
- 当前任务所需的可信度是否足够；
- 多个候选是否互补而非重复。

允许“不确定/尚未核验”，没有证据不要乐观补齐。

结果不匹配时先指出**具体缺什么**：

- 要可打印练习但全是视频 → 转向练习/文档；
- 理论够了但缺直观过程 → 补视觉演示；
- 要公开可读但可访问性未知 → Inspect 高潜项；
- 低龄启蒙搜成高年级课程 → 需求已清楚就换方向/来源，需求本身仍分叉才澄清。

**只有能说清一个有意义的缺口，并且下一次搜索有明显不同的路线可能补上时，才继续搜。** 不为了轮数、数量或平台数继续搜索。

## 7. Inspect 只服务于决策

Search 提供候选线索。只有某个事实会改变推荐、计数或获取决策时才 Inspect 高潜候选，例如：

- 用户明确要求公开、无需登录、可直接阅读/下载；
- 需要确认真实文件格式、资源本体还是 landing page；
- 标题/摘要不足以判断是否值得推荐；
- 下载准备需要 fresh Resolution/Representation。

Public Inspect 只返回决策所需的 availability、Representation、creator_id（存在时）、warnings/failures 等；不要为了找 fingerprint、inspector version、resolution digest 或内部 route 去读源码。

不要为了“流程完整” Inspect 全部候选。

## 8. 最小 MCP choreography

把这些当后端操作，不要变成用户可见的流程说明。

- 新资源目标：`resource_flow_start`；继续旧任务但 `flow_id` 不确定：`resource_flow_list` / `resource_flow_status`。
- 搜索：组织 `search_tasks[]` 调 `resource_search`。补搜只改 `mode=extend`；**不提交 `task_version` / `base_result_set_id`**。
- 展示：只展示真正审查过的有序子集；随后 `resource_presentation_save(displayed_resource_ids=[...])`。**不提交 `result_set_id`**。
- 选择：用户按编号选择后调用 `resource_selection_save(selected_positions=[...])`。**不提交 `presentation_id` / `presented_version`**。
- 下载准备：必要时 Inspect → `resource_download_prepare(options?)`。**不提交 `selection_version` / `selection_digest` / Presentation binding**。
- 确认：向用户说明 Prepare 实际返回、且会影响决定的资源/格式/风险；用户明确确认后，用返回的 `plan_id + confirmation_token` 调 `resource_download_start`。
- Job：已有 `job_id` 时直接 `resource_job_status`；只依据 compact progress/assets/failures 判断结果，不要求 Outcome/execution route 重放。
- 归档/资料库：按需读 [`references/library.md`](references/library.md)。

Public MCP 之外的 ResultSet lineage、Presentation/Selection version、digest、Resolution evidence、Provider execution route 都由服务端持有。**不要缓存、转述或从旧文本恢复这些内部字段。**

`resource_flow_status` 是 compact recovery summary，不是全量状态转储。已有当前上下文时不要反复调用；context compaction 后只恢复下一步需要的资源引用/Plan/Job/Asset 句柄。

资源候选、可访问性、下载和归档事实只使用 `education-resources` 的业务 `resource_*` 工具。不要用 web/browser/curl/exec/其他 MCP 建第二条资源发现或获取数据面，也不要读项目源码来恢复某个业务句柄。

## 9. Few-shot

### A. 火山科普

用户：“帮孩子找一些火山科普资料，形式你看着办。”

不要机械生成 `火山科普 / 火山知识 / 儿童火山优质资料`。

更好的理解：用户需要“为什么喷发”的原理理解 + “喷发是什么样”的过程观察。

```text
角度1 原理理解 → 专业科普/教育来源 → query: 火山形成 喷发原理 科普
角度2 过程观察 → 视频来源 → query: 火山喷发 原理 动画 实验演示
```

### B. 信息已经足够

用户：“找适合小学三年级自己看的中文太阳系图文，先不要下载。”

对象、主题、语言、载体都明确，不问平台/数量/精确年龄。聚焦小学尺度太阳系图文，排除成人深度材料、纯词典和视频；只搜索、审查、展示，不进入下载。

### C. 内容形态和格式不要混

用户：“要能打印的鸟类观察卡，最好 PDF。”

```text
内容形态：鸟类观察卡
must：可打印
prefer：PDF
```

直接寻找观察卡、活动单、worksheet、PDF；不要因为主题是鸟类自动加入纪录片。

### D. 结果多但方向错

用户要“一年级 20 以内加减法可打印练习”，结果却是大量讲解视频。

不能因为候选很多就推荐。真正缺口是**可打印练习本体**，下一轮转向 worksheet / 练习单 / PDF / 文档来源。

## 10. Advanced references

只有当前任务真的需要时再读：

- 对话与背景边界：[`references/conversation.md`](references/conversation.md)
- 平台生态/长尾来源：[`references/source-routing.md`](references/source-routing.md)
- 多轮检索/ResultSet：[`references/retrieval.md`](references/retrieval.md)
- Inspect：[`references/inspection.md`](references/inspection.md)
- 下载：[`references/acquisition.md`](references/acquisition.md)
- 归档：[`references/library.md`](references/library.md)
- 多 Agent 搜索规划实验：[`references/multi-agent.md`](references/multi-agent.md)

普通搜索默认由 Main Agent 自己完成需求理解、来源选择和 query 规划。不要因为存在 multi-agent 能力就自动 spawn child。
