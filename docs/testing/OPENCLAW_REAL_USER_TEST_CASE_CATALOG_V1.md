# OpenClaw 真实用户测试用例库 v1（审核稿）

- 状态：draft / 待人工审核
- 目标：维护一套可持续迭代的真实用户行为用例库；先审核，再执行，再依据真实失败决定修改方向。
- 执行原则：只有 `review_status=approved` 的用例才允许进入 OpenClaw Runner。
- 当前版本：只定义用例，不修改 `real-user-journeys.json`，不触发任何测试。

## 1. 测试流程

```text
设计/补充用例
↓
人工审核（draft → approved / rejected）
↓
选择一个批次执行
↓
OpenClaw 真实多轮会话
↓
保存 request / stdout / stderr / tool calls / job / timing
↓
人工看结果，不由 runner 自动裁判产品语义
↓
归因：SEMANTIC / MCP_CAPABILITY / ADAPTER / PLATFORM_EXTERNAL /
      HARNESS / FIXTURE / PERFORMANCE / PRODUCT_RULE
↓
决定修改方向
↓
先重跑失败项，再跑关键回归
```

## 2. 用例字段

每条用例维护：

- `priority`：P0 / P1 / P2
- `review_status`：draft / approved / rejected
- `run_status`：never_run / passed / failed / needs_review
- `purpose`：为什么测
- `turns`：用户真实连续说什么
- `acceptance`：必须出现的行为
- `forbidden`：不能出现的行为
- `fixtures`：只有确实需要固定外部对象时才配置
- `coverage`：覆盖的能力/语义边界

## 3. 执行等级

- **P0 核心 Journey**：约 15 条。重要语义/MCP/路由改动后优先跑。
- **P1 完整回归**：约 15 条。阶段性版本、较大修改后跑。
- **P2 专项/异常**：约 5 条。相关 Adapter、Session、风险控制等变化时跑。

---

# P0 — 核心真实用户 Journey

## P0-01 三年级数学视频：从自然语言自己找资源

- review_status: draft
- run_status: never_run
- purpose: 验证用户不提供 URL 时，Agent 能自己选择来源、搜索并给出真实视频候选。
- turns:
  1. `帮我找一些适合三年级学生看的数学视频，先给我推荐，不要下载。`
  2. `更偏课堂同步一点，最好是一套连续课程。`
- acceptance:
  - 首轮把任务视为 Locate/Browse，而不是直接下载。
  - 根据“三年级、数学、视频”选择合理来源，不机械全平台扫描。
  - 第二轮根据“课堂同步、连续课程”调整搜索/候选组织。
  - 如果搜索到课程容器，应识别其 container 价值并在需要时 Expand。
- forbidden:
  - 要求用户先提供课程 URL。
  - 未授权下载。
  - 为了平台多样性加入明显不相关来源。
- fixtures: 无。
- coverage: Goal / Source routing / Search / Container discovery / Stop。

## P0-02 模糊的一年级数学资料：只问一个关键问题

- review_status: draft
- run_status: never_run
- purpose: 验证真正存在路线分叉时才澄清，并且只问最高信息增益问题。
- turns:
  1. `帮我找一年级数学资料。`
  2. `主要想做基础练习巩固，最好能直接打印，不要视频。`
  3. `给我最适合的几个就行，先别下载。`
- acceptance:
  - 首轮只问一个能显著影响路线的问题。
  - 第二轮保留“一年级数学”，加入“练习/可打印/不要视频”。
  - 搜索方向转为 worksheet/练习/文档类来源。
  - 第三轮基于已有证据筛选，不重新从头理解任务。
- forbidden:
  - 一次询问平台、格式、数量、版本等字段清单。
  - 第二轮再次问年级或是否需要视频。
- fixtures: 无。
- coverage: Clarify / Goal update / Search / Precision / Stop。

## P0-03 精确版本：《呐喊》1923 新潮社初版扫描

- review_status: draft
- run_status: never_run
- purpose: 验证精确版本定位，不拿普通电子书冒充指定版本。
- turns:
  1. `帮我找1923年新潮社初版《呐喊》的扫描版，要能验证确实是初版。`
  2. `先给我证据和链接，不下载。`
- acceptance:
  - 任务识别为 Locate exact edition。
  - 版本证据与资源 URL 分开说明。
  - 没有可靠版本证据时明确不确定，而不是拿同名书替代。
- forbidden:
  - 普通 EPUB/PDF 只因书名相同就声称是 1923 初版。
  - 伪造馆藏、版本或 URL。
- fixtures: 无。
- coverage: Exact edition / Evidence / Web search / Book routing。

## P0-04 平台约束：只在 B 站找牛顿第二定律

- review_status: draft
- run_status: never_run
- purpose: 验证用户明确限定平台后，不擅自扩大来源。
- turns:
  1. `只在B站帮我找几个适合初中生理解牛顿第二定律的视频，先别下载。`
  2. `把第二个和第三个对比一下。`
- acceptance:
  - 使用 Bilibili 搜索能力。
  - 候选有真实可访问链接。
  - 第二轮只对已有候选做比较。
- forbidden:
  - 转去抖音/CCTV/全网补结果。
  - 第二轮重新搜索一批候选再替换编号。
- fixtures: 无。
- coverage: Platform constraint / Search / Selection continuity。

## P0-05 搜索 → 编号选择 → 下载 → 归档

- review_status: draft
- run_status: never_run
- purpose: 覆盖最典型端到端资源获取链。
- turns:
  1. `在B站帮我找3个适合初中生理解火山喷发原理的中文视频，给我真实链接和区别，先不要下载。`
  2. `第二个比较合适，就把第二个按原始格式下载下来。`
  3. `下载完成后把它归档进学习资料库，主题按火山科普整理。`
- acceptance:
  - 首轮只 Search/展示。
  - 第二轮严格映射用户看到的第2个候选。
  - Download 以真实 Job 终态为成功依据。
  - 第三轮只在真实文件产生后 Archive。
- forbidden:
  - 首轮下载。
  - 重新搜索后把新的第2个当用户选择。
  - queued/running 时声称完成。
  - 无文件时归档。
- fixtures: 无。
- coverage: Search / Selection / Download / Job / Archive。

## P0-06 已知网页：保存离线网页，不自动设计

- review_status: draft
- run_status: never_run
- purpose: 验证已知 URL 直接 Import/Download，默认 Reader 与视觉 Design 分离。
- turns:
  1. `把这个网页保存成离线网页，正文不要改：<GENERIC_WEB_URL>`
  2. `先这样，不需要美化。`
- acceptance:
  - URL 已知时跳过主题 Search。
  - 使用 resource_import_url 后按保存意图下载。
  - 默认生成 Generic Web Reader。
  - 保留原始响应与清洗正文。
- forbidden:
  - 重新搜索这个 URL。
  - 自动触发 HTML Design。
  - 改写正文。
- fixtures: GENERIC_WEB_URL（稳定公开文章）。
- coverage: Import / Generic Web / Download / No unnecessary Search。

## P0-07 自然语言发现课程容器并展开

- review_status: draft
- run_status: never_run
- purpose: 验证 Course container 应由系统自己从搜索结果发现，而不是要求用户提供 URL。
- turns:
  1. `帮我找三年级数学上册的系统视频课程。`
  2. `如果有一整套课程，先把里面具体有哪些课时给我看看。`
  3. `给我先看前20个。`
- acceptance:
  - 首轮自己 Search。
  - 发现合适课程/教材容器后，第二轮使用 Expand，而不是继续关键词搜索猜课时。
  - 完整枚举保存在 Expand Job；第三轮只分页读前20个。
- forbidden:
  - 要求用户先提供 COURSE_CONTAINER_URL。
  - 只抓第一页然后声称“全部课时”。
  - 自动下载全部课时。
- fixtures: 无；如果开放搜索长期无法稳定发现，可另增加固定 URL 能力测试，但不能替代本 Journey。
- coverage: Search → Container discovery → Expand → Job read。

## P0-08 B站创作者：Browse → 完整 Enumerate

- review_status: draft
- run_status: never_run
- purpose: 复测历史真实超时问题，并验证 Browse 与 Enumerate 边界。
- turns:
  1. `看看这个UP主最近主要讲什么，挑几个有代表性的公开视频给我，不用全部列出来：<BILIBILI_CREATOR_URL>`
  2. `我看过了，现在把这个UP主所有公开视频完整列出来，一个都不要漏，先别下载。`
  3. `先给我看完整列表里的第21到40个。`
- acceptance:
  - 第一轮仅 Preview。
  - 第二轮任务升级为完整 Enumerate，Expand 到来源真实结束。
  - 第三轮从同一 Expand Job 读取 offset=20 limit=20。
  - 风控/重试期间不能把部分结果说成全部。
- forbidden:
  - 第一轮自动全枚举。
  - 第二轮反复 web_search 猜列表。
  - 前20/前50声称为全部。
- fixtures: BILIBILI_CREATOR_URL。
- coverage: Browse / Enumerate / Expand / Performance / Risk backoff / Pagination。

## P0-09 喜马拉雅：专辑 → Track → 下载

- review_status: draft
- run_status: never_run
- purpose: 覆盖音频类容器资源。
- turns:
  1. `帮我找适合小学生听的《西游记》儿童版音频，先给我几个选择。`
  2. `这个专辑不错，看看里面都有哪些集。`
  3. `下载第5集，保持原始音频格式。`
- acceptance:
  - 搜索偏向音频来源。
  - 专辑识别为 container 并 Expand tracks。
  - 只下载用户看到并选择的第5集。
- forbidden:
  - 把专辑当单文件直接下载。
  - 未经用户选择批量下载全部音频。
- fixtures: 无。
- coverage: Search / Ximalaya / Album expand / Track download。

## P0-10 CCTV：系列 → 单集 → 最高画质

- review_status: draft
- run_status: never_run
- purpose: 验证系列容器与最高画质下载规则组合。
- turns:
  1. `帮我找一个央视公开的历史纪录片系列，先给我看看有哪些集。`
  2. `下载第1集，要当前实际能拿到的最高画质。`
- acceptance:
  - 系列/栏目先 Expand 为单集。
  - 第二轮只下载第1集。
  - clear/H5E 统一按真实画质排序；解密方式不参与优先级。
  - 最高画质失败时明确失败，不静默降质。
- forbidden:
  - 把整个系列当单个视频下载。
  - 因 H5E/clear 类型改变画质优先级。
- fixtures: 无；必要时使用稳定公开系列作为回归 fixture。
- coverage: CCTV Search / Series Expand / Selection / Highest quality Download。

## P0-11 Job 状态：running 不能说完成

- review_status: draft
- run_status: never_run
- purpose: 验证长任务的终态语义。
- turns:
  1. `下载这个视频：<LONG_PUBLIC_VIDEO_URL>`
  2. `下载好了吗？`
  3. `现在呢？`
- acceptance:
  - 首轮启动 Download Job。
  - 后续根据真实 job status 回答。
  - 只有 success/terminal 且文件存在时说完成。
- forbidden:
  - queued/running 时声称“已下载完成”。
  - 为了回答进度重新发起下载。
- fixtures: LONG_PUBLIC_VIDEO_URL。
- coverage: Download Job / Status / Multi-turn continuity。

## P0-12 临时 resource_id 失效后恢复

- review_status: draft
- run_status: never_run
- purpose: 验证临时 handle 不是资源永久身份。
- turns:
  1. `帮我找几个关于光合作用的学习视频，先别下载。`
  2. `第二个就行，下载它。`
- acceptance:
  - 如果先前 resource_id 已失效但真实 URL/资源身份仍可重定位，应恢复后继续原选择。
  - 不因 handle 失效而重新主题搜索替换候选。
- forbidden:
  - 把 resource_id 当永久 URL。
  - 选择漂移到另一条内容。
- fixtures: 可通过测试环境制造 handle 失效。
- coverage: Handle invalidation / Resource identity / Selection continuity。

## P0-13 Coverage 已满足后停止

- review_status: draft
- run_status: never_run
- purpose: 验证 Stop，不进行平台清单式搜索。
- turns:
  1. `帮我找3个适合初中生做的简单物理小实验，视频或图文都行。`
  2. `这几个已经够用了。`
- acceptance:
  - 找到足够高质量候选后可停止。
  - 第二轮明确停止，不继续 Search。
- forbidden:
  - 因还有平台没搜过就继续扫 B站/知乎/抖音/CCTV 等。
- fixtures: 无。
- coverage: Coverage / Diminishing gain / Stop。

## P0-14 Tool 一次瞬时失败后恢复

- review_status: draft
- run_status: never_run
- purpose: 验证真实 Tool transient failure 不被错误升级成任务失败。
- turns:
  1. `帮我找适合初二学生看的勾股定理讲解视频，先给我几个。`
- acceptance:
  - 测试注入一次可重试 Tool failure。
  - Agent/MCP 在合理边界内恢复并完成任务。
  - 最终结果来自真实成功调用。
- forbidden:
  - 编造成功结果掩盖 Tool failure。
  - 加无界重试。
- fixtures: harness 注入一次 transient failure。
- coverage: Error recovery / Retry boundary / Evidence integrity。

## P0-15 用户中途改变目标

- review_status: draft
- run_status: never_run
- purpose: 验证 Goal 会根据用户真实新意图更新，而不是死守初始任务。
- turns:
  1. `帮我找一些初中英语听力材料。`
  2. `算了，不要听力了，我更需要能打印的词汇练习。`
  3. `给我适合初二的。`
- acceptance:
  - 第二轮停止继续听力路线。
  - 保留“初中英语”但目标更新为 printable vocabulary practice。
  - 第三轮增加初二约束。
- forbidden:
  - 继续推荐音频。
  - 第二轮重新询问已经明确的学科。
- fixtures: 无。
- coverage: Goal update / Constraint merge / Search reroute。

---

# P1 — 完整回归 Journey

## P1-01 可打印练习：结果质量与格式约束

- review_status: draft
- run_status: never_run
- purpose: 验证“可打印”不是简单关键词，而是实际资源形态约束。
- turns:
  1. `给一年级学生找5份20以内加减法练习，最好打开就能打印。`
  2. `不要在线小游戏，只要纸面练习。`
- acceptance: 候选以 PDF/文档/可打印页面为主，并剔除小游戏类结果。
- forbidden: 把视频、互动游戏作为主要推荐。
- fixtures: 无。
- coverage: Search precision / Format constraint。

## P1-02 Research：比较英语单词学习方法

- review_status: draft
- run_status: never_run
- purpose: 验证 Research 与“找下载资源”不同。
- turns:
  1. `帮我比较几种适合初中生背英语单词的方法，最好有不同来源的依据。`
  2. `最后告诉我哪几种最适合每天20分钟。`
- acceptance: 多来源研究、比较、归纳；不强行进入 Download。
- forbidden: 因系统是资源工具就硬找一个文件下载。
- fixtures: 无。
- coverage: Research / Multi-source evidence / Synthesis。

## P1-03 音频需求：不要被视频结果淹没

- review_status: draft
- run_status: never_run
- purpose: 验证用户明确媒介偏好会影响 Source routing。
- turns:
  1. `我想找睡前能听的儿童科普音频，不要视频。`
- acceptance: 优先音频平台/音频资源。
- forbidden: 用视频推荐填满结果。
- fixtures: 无。
- coverage: Media constraint / Source prior。

## P1-04 教材版本澄清

- review_status: draft
- run_status: never_run
- purpose: 验证版本差异真正影响结果时才澄清。
- turns:
  1. `帮我找三年级数学上册同步课程。`
  2. `<根据 Agent 首轮澄清回答具体教材版本>`
- acceptance: 若平台/教材存在显著版本差异，只问教材版本这一关键问题；回答后直接继续。
- forbidden: 同时追问平台、格式、数量。
- fixtures: 无。
- coverage: Clarification / Textbook version / SmartEdu/Zjer routing。

## P1-05 Zjer 课程发现与具体课时

- review_status: draft
- run_status: never_run
- purpose: 覆盖浙江教育资源平台课程形态。
- turns:
  1. `帮我在浙江教育资源里找小学科学有关天气的课程。`
  2. `如果是一套课，展开看看具体课时。`
- acceptance: 使用 Zjer 真实能力；容器则 Expand。
- forbidden: 平台已限定仍转到其他网站替代。
- fixtures: 无。
- coverage: Zjer Search / Expand。

## P1-06 Douyin：搜索、选择、下载公开视频

- review_status: draft
- run_status: never_run
- purpose: 覆盖短视频平台用户路径。
- turns:
  1. `在抖音找几个能直观看懂日食原理的科普短视频。`
  2. `下载第一个。`
- acceptance: 首轮 Search；第二轮下载用户看到的第一项。
- forbidden: 未授权首轮下载；编号漂移。
- fixtures: 无。
- coverage: Douyin Search / Download / Selection。

## P1-07 复杂网页：图片、表格、代码/引用

- review_status: draft
- run_status: never_run
- purpose: 验证 Generic Web 不只适合纯文本页面。
- turns:
  1. `把这个页面完整保存下来，图片和表格尽量保留，正文不要改：<COMPLEX_WEB_URL>`
- acceptance: 原始响应保存；清洗正文完整；可保留的图片/表格进入离线呈现；缺失明确说明。
- forbidden: 因页面复杂就只保存一段摘要。
- fixtures: COMPLEX_WEB_URL。
- coverage: Generic Web / Images / Tables / Completeness。

## P1-08 网页保存后再视觉设计

- review_status: draft
- run_status: never_run
- purpose: 验证 HTML Design 是用户明确要求后的独立步骤。
- turns:
  1. `把这个网页保存成离线网页：<GENERIC_WEB_URL>`
  2. `我看过了，再设计得更精美一点，适合学生阅读，正文不要改。`
  3. `归档最终版本。`
- acceptance: 首轮默认 Reader；第二轮才 context → DesignSpec → render；第三轮 Archive。
- forbidden: 首轮自动 Design；Design 重写正文。
- fixtures: GENERIC_WEB_URL。
- coverage: Import / Download / HTML Design / Archive。

## P1-09 一个 Resource 产生多个 Files 后归档

- review_status: draft
- run_status: never_run
- purpose: 验证 1 Resource → 0..N Files 的归档语义。
- turns:
  1. `保存这个网页：<GENERIC_WEB_URL>`
  2. `把生成的文件都归档到学习资料库。`
- acceptance: 对真实 job files 集合归档，不只拿其中一个文件冒充完整结果。
- forbidden: 把 Resource 和 File 当成同一对象。
- fixtures: GENERIC_WEB_URL。
- coverage: Resource/File boundary / Archive。

## P1-10 未授权不得下载

- review_status: draft
- run_status: never_run
- purpose: 防止 Search/Browse/Inspect 自动升级 Download。
- turns:
  1. `帮我看看有哪些关于植物细胞的视频，先了解一下，不要下载。`
  2. `第三个讲的什么？`
- acceptance: 全程只 Search/Browse/Inspect/比较。
- forbidden: 任何 Download。
- fixtures: 无。
- coverage: Authorization boundary / Search≠Download / Inspect≠Download。

## P1-11 用户直接给文件/资源 URL

- review_status: draft
- run_status: never_run
- purpose: 验证已知资源 URL 不需要 Search 仪式。
- turns:
  1. `这个就是我要的，按原始格式保存：<KNOWN_RESOURCE_URL>`
- acceptance: Import/Inspect（如确有必要）后直接 Download。
- forbidden: 重新主题搜索；多一次“确定下载吗”。
- fixtures: KNOWN_RESOURCE_URL。
- coverage: Known URL / Direct acquisition / No ritual confirmation。

## P1-12 超大 Container：完整枚举与分页展示分离

- review_status: draft
- run_status: never_run
- purpose: 验证完整性和对话窗口分页不是同一个概念。
- turns:
  1. `把这个合集全部内容列出来，一个都不要漏：<LARGE_CONTAINER_URL>`
  2. `先给我看1到20。`
  3. `再看81到100。`
- acceptance: Expand 到来源结束；后两轮读取同一 Job 对应区间。
- forbidden: 为了对话分页只采集前100条。
- fixtures: LARGE_CONTAINER_URL。
- coverage: Enumerate completeness / Job read / Pagination。

## P1-13 单个平台失败 ≠ 资源不存在

- review_status: draft
- run_status: never_run
- purpose: 验证平台事实和全局资源存在性分离。
- turns:
  1. `帮我找关于地震波的学习资料。`
- acceptance: 若某平台真实失败，可使用其他合理来源继续；措辞仅说明该平台当前失败。
- forbidden: 一个平台失败后宣称“没有相关资源”。
- fixtures: harness 让一个来源暂时失败。
- coverage: Platform failure / Source diversification / Truthfulness。

## P1-14 用户说“你决定”

- review_status: draft
- run_status: never_run
- purpose: 验证低价值偏好问题不继续甩回用户。
- turns:
  1. `帮我找一些适合初中生看的天文资料。`
  2. `平台和格式都无所谓，你决定就行。`
- acceptance: 第二轮 Agent 自己根据目标选择来源/形态。
- forbidden: 再追问“你更想视频还是文档/哪个平台”。
- fixtures: 无。
- coverage: Agent autonomy / Clarification threshold。

## P1-15 长多轮选择仍保持原对象

- review_status: draft
- run_status: never_run
- purpose: 验证多轮上下文不会让已选资源漂移。
- turns:
  1. `找3个关于中国古代建筑的纪录片。`
  2. `第二个看起来不错，先介绍详细一点。`
  3. `它大概多长？`
  4. `就下载刚才这个。`
- acceptance: 2/3/4 轮始终指向首轮第二项。
- forbidden: 最后一轮重新 Search 后下载新的“第二个”。
- fixtures: 无。
- coverage: Multi-turn context / Inspect / Selection continuity / Download。

---

# P2 — 专项与异常 Journey

## P2-01 真正 AUTH_REQUIRED 后才进入 Session

- review_status: draft
- run_status: never_run
- purpose: 验证 Session 是认证阻塞后的能力，不做统一 preflight。
- turns:
  1. `这个资源就是我要的，按原始格式保存：<AUTH_REQUIRED_RESOURCE_URL>`
  2. `如果确实需要登录，告诉我怎么处理；如果不需要就直接继续。`
  3. `我已经完成登录，捕获对象是：<SESSION_CAPTURE_JSON>，保存登录状态后继续刚才那个资源。`
- acceptance:
  - 第一轮真实返回 AUTH_REQUIRED 后才进入 Session 路径。
  - 登录后恢复原资源，不重新发现。
  - capture 作为 opaque object 处理。
- forbidden:
  - 首轮先查 Session。
  - 没有 AUTH_REQUIRED 也强迫登录。
  - 要求用户手工拼 Cookie Header/密码/MFA。
- fixtures: AUTH_REQUIRED_RESOURCE_URL + SESSION_CAPTURE_JSON。
- coverage: Auth / Session / Resume / Security boundary。

## P2-02 Session 已过期

- review_status: draft
- run_status: never_run
- purpose: 验证过期会话不会被当成有效登录。
- turns:
  1. `继续下载我刚才那个需要登录的资源。`
- acceptance: 若 Session 真实失效，返回明确认证事实并给出恢复入口。
- forbidden: 伪造下载成功；把网络错误误判成登录过期。
- fixtures: 已保存但失效的 session fixture。
- coverage: Session status / Auth failure classification。

## P2-03 Bilibili -352/-412 风控与完整枚举

- review_status: draft
- run_status: never_run
- purpose: 专门复测历史 creator 全量枚举风险控制。
- turns:
  1. `把这个UP主所有公开视频完整列出来：<BILIBILI_CREATOR_URL>`
- acceptance: HTTP 412 和 JSON -352/-412 进入 bounded backoff；最终若可恢复则完整结束；不可恢复则明确 NETWORK_BLOCKED。
- forbidden: 无界重试；风控后拿部分列表声称全部。
- fixtures: BILIBILI_CREATOR_URL（优先选择作品数量较多的真实 creator）。
- coverage: Bilibili risk / Pacing / Backoff / Enumerate completeness / Performance。

## P2-04 新的/不支持的 representation

- review_status: draft
- run_status: never_run
- purpose: 验证遇到未知协议时暴露能力边界，不临时制造不等价 fallback。
- turns:
  1. `下载这个公开视频：<UNSUPPORTED_REPRESENTATION_URL>`
- acceptance: 能识别实际不支持的流/表示并明确失败事实。
- forbidden: 偷偷换低质量、不同资源或其他不等价表示并称成功。
- fixtures: UNSUPPORTED_REPRESENTATION_URL（仅当真实存在时启用）。
- coverage: Adapter boundary / Unsupported feature / No silent fallback。

## P2-05 用户取消长任务

- review_status: draft
- run_status: never_run
- purpose: 验证 Job cancel 与后续状态一致。
- turns:
  1. `下载这个比较长的视频：<LONG_PUBLIC_VIDEO_URL>`
  2. `算了，取消下载。`
  3. `现在这个任务是什么状态？`
- acceptance: 第二轮取消真实 Job；第三轮返回 cancelled/terminal 事实；不继续写文件。
- forbidden: 新开另一个下载；取消后仍说任务成功。
- fixtures: LONG_PUBLIC_VIDEO_URL。
- coverage: Job cancel / Status / File integrity。

---

# 4. 覆盖矩阵

| 领域 | 覆盖用例 |
| --- | --- |
| 自然语言 Goal / Search | P0-01, P0-02, P0-03, P0-04, P1-01, P1-02, P1-03 |
| Clarify / 用户补充条件 | P0-02, P1-04, P1-14, P0-15 |
| Source routing | P0-01, P0-03, P0-04, P0-09, P0-10, P1-03, P1-05, P1-06 |
| Container discovery / Expand | P0-07, P0-08, P0-09, P0-10, P1-05, P1-12 |
| Browse vs Enumerate | P0-08, P1-12 |
| Selection continuity | P0-04, P0-05, P0-12, P1-06, P1-15 |
| Download / Job | P0-05, P0-09, P0-10, P0-11, P1-06, P1-11, P2-05 |
| Archive | P0-05, P1-08, P1-09 |
| Generic Web | P0-06, P1-07, P1-08, P1-09 |
| HTML Design | P1-08 |
| Session/Auth | P2-01, P2-02 |
| 平台风险/异常 | P0-14, P1-13, P2-03, P2-04 |
| Stop / 不机械扫平台 | P0-13 |
| Agent 目标更新 | P0-15 |

# 5. 当前平台覆盖

- Bilibili：P0-04 / P0-05 / P0-08 / P2-03
- Douyin：P1-06
- CCTV：P0-10
- SmartEdu：P0-07 / P1-04（允许实际搜索路由到 SmartEdu）
- Zjer：P1-05
- Ximalaya：P0-09 / P1-03
- Generic Web：P0-06 / P1-07 / P1-08 / P1-09
- Zhihu / Baidu Wenku：当前主要通过开放 Search/Research Journey 间接覆盖；若后续改 Adapter，再补对应 P2 专项，不为了平台数量机械造测试。

# 6. 审核建议

请人工重点检查以下问题，而不是先看“用例数量够不够”：

1. 这些用户说法是否像真实用户，而不是为了命中 Tool 人工编出来的命令。
2. 哪些行为是产品必须保证的硬规则，哪些只是当前实现偏好。
3. 哪些用例存在重复，可合并到一条更真实的多轮 Journey。
4. 哪些平台/资源形态是产品实际重要但这里遗漏的。
5. 哪些 fixture 应由测试维护者固定，哪些必须由 Agent 自己从自然语言发现。
6. 哪些 P0 值得每次大改都跑；哪些只需阶段性或专项跑。

审核完成后，再把 `approved` 的用例转换/同步到 Runner JSON。Runner 不应读取本文所有 draft 用例自动执行。
