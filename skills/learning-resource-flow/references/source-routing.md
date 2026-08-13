# Source Routing Guidance

本文件负责“这一轮要解决什么、去哪里搜、为什么由这些来源负责、query 如何体现分工”，不负责候选语义评分，也不证明平台当前可获取资源本体。

## 基本原则

来源选择由 `goal + resource_target + explicit constraints + 当前 Gap` 驱动，而不是由用户身份、平台热度或 Registry 列表驱动。

先决定 **SearchDirection 要解决什么问题**，再判断需要什么内容形态/证据，最后选择能提供独特贡献的来源。不同来源应有互补价值，不为了“平台数量”机械扩散。

平台规划是召回策略，不是用户事实。模型可以判断“这个方向适合视频演示”“需要官方材料”“应该补一个图书目录来源”，但不能把这些探索判断反写成用户偏好或约束。

## 从需求到搜索任务

每个 SearchDirection 建议按以下顺序推理：

1. **目标**：这个方向要帮助用户理解、练习、观察、实践、比较、表达，还是关闭某个已有 Gap？
2. **内容/证据**：完成这个目标需要画面演示、声音输入、结构化课程、长文、可打印材料、原始官方信息、图书版本线索还是实践案例？
3. **主力来源**：哪个来源最直接承担这个方向的核心召回？
4. **补充来源**：哪个来源能提供主力来源缺少的媒介、证据或内容切面？
5. **去重职责**：如果两个平台大概率只会召回高度同质内容，不因为它们都“相关”就同时搜索。

同一个 SearchDirection 通常选择 1 个主力来源，必要时再加 1–2 个有明确互补价值的来源。没有独特贡献的平台不加入。

不要把“资源类型”直接当路由器。例如需要理解火山原理，可能由专业科普网页承担可信解释、视频平台承担喷发过程演示；不是因为 `resource_type=video` 就自动选择某个平台。

## 用户事实与召回假设

生成搜索任务时明确区分：

- **用户事实**：用户在当前任务中明确表达/确认的信息，以及 OpenClaw 当前上下文已经提供、与当前 resource target 明确对应且来源可靠的背景；
- **召回假设**：模型为了提高发现质量提出的内容切面、资源形态、学习方式或来源类型，只用于探索。

例如用户只说“想了解火山”，模型可以首轮规划“原理理解 + 过程观察”两个方向；这不表示用户已经明确偏好文章或纪录片。

年龄、年级等背景只有在 OpenClaw 当前上下文已经提供且确实能提高当前 query 定位时才使用，不统一追加到所有搜索词；未知时也不为了生成平台任务而追问。路由层只消费背景，不负责保存、更新或写回长期用户记忆，也不能把模型为本轮搜索做出的推断沉淀成用户画像。

## 查询生成方法

query 应先体现“这个平台在当前方向里要找什么”，再写成该来源自然使用的表达。不要逐字段机械拼接，也不要用“优质、权威、高赞、精品、适合孩子”等评价词替代后续审查。

同一轮多 query 必须扩大真正的检索空间，而不是只替换近义词。可通过以下差异形成互补：

- 总览 vs 关键子问题；
- 原理解释 vs 过程演示；
- 理解 vs 练习/实践；
- 直接学习材料 vs 使用方法；
- 官方原始来源 vs 社区经验；
- 文章/课程线索 vs 可打印文件；
- 单篇内容 vs 连续专辑/系列内容。

每个平台每轮通常只发 1 条最有价值的聚焦 query；只有两个检索范围确实不重叠且容量有余时最多 2 条。不要恢复 legacy 中“一开始每个平台生成 2–4 条 query”的前置扩散。更多角度应由真实结果产生的 Gap 驱动下一轮 Replan。

### 平台语言

同一目标应根据平台生态调整表达，而不是统一追加后缀：

- 视频来源：突出要“看懂/看到”的对象，如动画解释、过程演示、纪录片、操作步骤；
- 音频来源：突出朗读、故事、听书、跟读、连续专辑等听觉内容；
- 结构化教育来源：使用学段/年级/学科/知识点、课文名、单元主题等真正有助于站内召回的信息；
- 方法与社区来源：使用真实问题、经验、比较、做法等表达；
- 图书/目录来源：使用书名、主题、作者、版本、ISBN 等书目线索；
- Generic Web：使用主题 + 内容切面/用途，并在确有价值时用 `site:` 或 `filetype:` 缩小发现空间。

只在用户明确要求或 OpenClaw 当前上下文已有事实表明相关时加入年龄、年级、教材版本、文件格式等限定；不要虚构版本，也不要把背景重复堆进每条 query。

## 平台生态速查

以下内容是 discovery 语义知识，不是当前可执行能力表，也不证明 acquisition 可用。实际是否能 Search/Inspect/Acquire 仍以业务 Tool 返回和当前 Registry/Provider runtime 为准。

- `bilibili`：适合视觉讲解、动画、实验/操作过程、纪录片、系列课程等需要画面理解的方向。
- `ximalaya`：适合朗读、故事、听书、跟读、音频课和连续专辑等听觉输入。
- `smartedu`：适合结构化课程、同步学习、知识点讲解和公共教育资源；只有结构化教学对当前目标有独特价值时才作为主力。
- `zhihu`：适合方法解释、经验比较、概念辨析和资源线索，尤其是供家长/规划者理解的问题；不自动等同于孩子直接使用的学习材料。
- `kepu`：适合科学、自然、健康安全等公共科普图文/视频线索，可作为专业科普来源之一。
- `nlc`：适合图书选题、版本、作者、ISBN、馆藏等书目发现；目录命中不等于可直接阅读或下载。
- `baiduwenku`：适合发现课件、讲义、练习、文档和可打印材料候选；搜索命中不证明免费、完整或可获取。
- `douyin`：适合短时间演示单个动作、步骤、技巧或趣味切面，不承担完整知识体系的默认主力职责。
- `cctv` / `open163` / `yixi`：适合公共媒体、纪录片、公开课、演讲等较完整的视频内容切面；是否适龄和是否匹配仍由候选审查决定。
- `runoob`：只在编程/计算机技术主题下提供结构化中文教程和实例价值。
- `weibo` / `wechat`：适合机构发布、专题文章、活动/资料线索等生态内容，通常是发现补充，不替代原始权威来源。
- `annas-archive`：只在图书/电子书/长文发现确有价值时考虑；必须继续遵守版权、访问与实际 acquisition 边界。
- `shuge`：适合古籍、公版影印本的直链发现。搜索支持直接传入书格详情页链接（`shuge.org/view/<slug>`）或短链（`s.shuge.org/<code>`），适配器会提取书名并在公开存储（shuge.hanjihebi.com）定位 `/d/` 直链；书格网站自身的网盘分发通道不在本适配器范围。
- `generic`：跨站发现官方机构、专业网页、长尾文章、具体文件、活动方案和未接入站点内容，是专门 Adapter 的补充路线，不是 acquisition fallback。

平台画像只帮助回答“为什么值得搜这里”。不要从画像直接推导当前登录状态、可下载性、资源本体存在或 Provider 可用。

## 三类事实不要混淆

1. **Platform Registry**：平台身份、resource types、search / creator browse / Inspect 等静态声明，以及 `auth_mode` / `auth_kind` 等认证属性；
2. **Session State**：当前用户是否具有合法、有效的平台会话；
3. **Resolution / Representation + Provider runtime**：当前候选实际是什么、有哪些表示、当前是否可用，以及服务端能否用已注册的 exact Provider 执行当前 route。

Registry 存在不能单独证明“现在能下载这个资源”。当前是否登录由 session-manager / 实际服务状态判断；当前是否可获取必须先形成 fresh `Resolution / Representation`，再由 `resource_download_prepare` 基于服务端 `ProviderSpec` 选择 exact route，并在 Start 前重新核验 Representation 与 Provider 当前注册状态。平台机器事实的开发/运维入口见 [`mcp/education-resources/contracts/`](../../../mcp/education-resources/contracts/README.md)。

不要在本文件维护完整平台能力表、固定登录状态表或 acquisition route 快照。真实用户 Flow 中也不得通过 `read` / `exec` / MCP protocol resources 去打开仓库或运行时 Registry / ProviderSpec；候选和当前状态只看 13 个业务 `resource_*` Tool 的返回。若对 native platform ID 没有明确依据，不猜测、不扫描本地文件，改用当前目标本来就允许的 `generic` discovery route，或 StopWithGap。

当前 0028 runtime 冻结的 native platform ID 命名空间是：`generic`、`bilibili`、`douyin`、`zhihu`、`smartedu`、`ximalaya`、`cctv`、`yixi`、`kepu`、`baiduwenku`、`runoob`、`nlc`、`open163`、`annas-archive`、`weibo`、`wechat`、`shuge`。这只是封闭 ID 集，不是当前可获取能力表；未列出的站点只能作为 `generic` query 中的来源线索，不能临时发明 native platform ID。

## Search 与 Creator Browse

用户是在“按主题找内容”时使用普通 `resource_search`。只有用户的目标明确是浏览某个创作者/账号已有内容，且当前平台 Registry/Tool 能力实际支持 creator browse 时，才使用 `resource_browse_creator`。

典型 creator browse 意图包括：用户提供创作者主页/账号并询问“这个人发了什么”“把这个作者的相关内容找出来”等。普通内容链接、单条资源 URL 或仅仅提到创作者名字，都不能自动转换成 creator browse 身份。

`resource_browse_creator` 返回的仍然是 ResultSet，后续必须经过相同的 Evaluate → Presentation → Selection 流程；它不是批量下载入口。平台不支持、需要认证或返回其他结构化失败时保留真实状态，不偷偷改成另一种浏览/下载路线。

## 可信来源定向搜索

有些来源知识属于 Skill 的 discovery guidance，而不是平台获取能力声明。它们用于在“明确需要高可信来源且宽泛搜索质量不足”时缩小搜索空间。

可以在 Generic Web 查询中使用 `site:域名` 做定向发现，但遵守：

- `search_tasks[].platform` 固定写 `generic`，域名只放在 query 的 `site:` 中；不得把 `generic_web`、域名、站点简称或来源族名称当作 platform ID；
- 不是每轮搜索都加 `site:`；先由目标、显式来源要求或当前 Gap 判断是否需要；
- 一条 query 最多绑定一个站点，避免把搜索范围收得不可解释；
- 用户明确指定来源时优先尊重用户来源；
- 站点只表示“优先发现来源”，不证明内容正确、适合当前用途、当前可访问或可获取；
- 某站点搜索失败只表示这条 discovery route 没拿到结果，不等于资源不存在，也不能触发 acquisition fallback。

当前保留的 curated preferred source 线索：

| 场景 | 来源线索 |
| --- | --- |
| 公共教育/教材 | `eduyun.cn`、`pep.com.cn` |
| 汉字/古诗文 | `zdic.net`、`gushiwen.cn`、`edu.cnr.cn` |
| 教案/练习/编程学习 | `21cnjy.com`、`runoob.com` |
| 科学与自然 | `cdstm.cn`、`school.kepu.net.cn`、`xiaoxiaotong.org`、`ppbc.iplant.cn` |
| 艺术 | `namoc.cn` |
| 消防/防灾/健康 | `119.gov.cn`、`data.earthquake.cn`、`chinacdc.cn` |

这些域名是“curated preferred discovery sources”，不是 security allowlist、network allowlist、ProviderSpec 或内容审批清单。实际搜索与页面可用性仍以当前工具结果为准。

## 资源类型不是平台路由器

`video`、`book`、`document`、`course` 等只是资源语义类型，不能据此直接决定 Provider 或 Acquisition strategy。

例如：

- book 搜索命中图书馆目录，可能只有 metadata/landing page；
- video 平台可能当前只有搜索/Inspect，没有 primary acquisition；
- 普通网页可能通过 web materialization 得到可离线阅读的 representation。

是否能获取必须先 Inspect 得到当前 `Resolution / Representation`，再由 Prepare 选择服务端 exact route，并在 Start 时重新核验；不能从资源类型或平台名直接推导。

## Gap 驱动的来源扩展

首轮不要试图一次覆盖所有平台。看到真实 ResultSet 后，根据当前 Gap 决定扩展什么：

- 缺可信原始来源 → 增加官方/专业机构或定向 `site:`；
- 视频很多但缺结构化材料 → 补文档/课程/专业网页来源；
- 理论解释足够但缺过程演示 → 补视觉平台；
- 只有单篇内容但用户要连续听 → 补音频专辑来源；
- 候选高度同质 → 换内容切面/来源族，而不是继续堆同义 query。

如果没有明确 Gap，不因为某个平台还没搜过就增加任务。

## 登录与搜索质量

认证属性和当前登录状态分开处理：

- Registry 的 `auth_mode` / `auth_kind` 只说明平台静态认证要求；
- 当前用户是否已有有效会话只看 session-manager 或真实工具返回，不能靠 Markdown 表或聊天记忆；
- `auth_mode=optional`、平台常识、landing available 或 representation unknown 都不能被改写成“当前需要登录”；只有当前 Search/Inspect/session Tool 明确返回 `AUTH_REQUIRED` 或等价状态才能这样断言；
- 不默认在首次搜索前逐个平台做登录检查，避免把认证变成无必要的前置阻塞；
- 如果 Registry 明确要求认证且用户当前任务就指定该平台，或真实搜索/Inspect 返回 AUTH_REQUIRED，再进入 session-manager 流程；
- 对 optional auth，当前公开结果已经足够完成任务时不主动打断用户登录；只有结果明显不足、且合法登录很可能改变当前 Gap 时，才把登录作为一个可选下一步；
- `representation=unknown`、只有 landing available 或没有 current Resolution 都不能单独证明登录会改变 Gap，因此不能据此建议 session-manager；用户明确要求“无需登录”时，除非用户主动放宽该约束，否则登录不是当前任务的合法继续路径；
- 用户明确要求公开、无需登录或可直接阅读时，`AUTH_REQUIRED` 候选不满足该条件，不能计入要求的来源数量；只能作为受限备选或 Gap 解释，不以“平台公开可搜索”替代正文当前可访问；
- 登录完成后重新读取 Flow/当前服务状态，不把“已登录”直接推导成搜索、Inspect 或获取成功。

## 认证与策略

需要登录、版权/许可判断或平台策略限制时，不通过其他 Provider 静默绕过。把结构化限制保留给后续 Inspect/Acquisition 和用户解释。

如果某个平台当前没有 native search/browse 能力，不把 Generic Web 结果伪装成该平台原生搜索。只有用户目标允许“查找该平台公开网页”这一不同 discovery route 时，才可明确标注为 Generic Web 发现；它仍不改变后续 `Inspect -> Resolution / Representation -> Prepare -> Confirm -> Start -> exact Provider` 的获取边界。
