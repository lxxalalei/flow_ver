# 0041 — 网页内容抽取与 Web-to-Markdown 方案评估

- 状态：pending
- 创建日期：2026-08-13
- 完成日期：未完成
- 范围：网页正文抽取、结构保留、Web-to-Markdown、后续与 `education-resources` 的融合方案

## Objective

在不修改当前资源 Flow、MCP 状态模型和获取链的前提下，先独立评估成熟开源方案对真实学习资源网页的正文抽取、结构保留与 Markdown 输出质量，形成可复现的 benchmark 和明确技术决策，再决定后续采用哪一个主实现以及如何最小化接回现有 `GenericWebInspector` / `web_materializer`。

本计划的最终产物不是“接入某个库”，而是：

1. 一组能代表真实学习资源网页的 benchmark 样本与人工期望；
2. 对候选开源项目和当前自研实现的同页对比结果；
3. 一个主方案选择结论；
4. 一个最小融合设计，明确哪些现有代码保留、替换或删除；
5. 在结论出来前，不改变线上/当前 OpenClaw 资源流程。

## Why now

当前网页链路已经具备：

```text
Search -> Generic URL candidate -> Inspect -> Plan -> Web Materializer -> Archive
```

但当前能力仍有两个明显缺口：

- Generic Search 首轮主要依赖标题、URL、搜索摘要，尚不能稳定利用正文内容判断候选质量；
- `acquisition/web_blocks.py` 已经实现 HTML -> Block IR，但正文范围选择较粗，且与 Acquisition 耦合；当前 Generic Inspector 对 HTML 页面也缺少可靠的“正文网页 vs landing/navigation”区分。

因此先把“网页内容到底如何抽取并保存”为独立问题验证，比直接继续扩展现有启发式代码更合适。

## Non-goals

本计划处于 pending 阶段，后续开始执行时也先坚持以下边界：

- 不立即接入任何候选库。
- 不修改 `education-resources` 公共 Tool、Schema、Flow、ResultSet、Presentation、Selection、Plan、Job、Asset、Archive 状态模型。
- 不把新的 extractor 做成独立 MCP、微服务、Agent 或第二套资源数据面。
- 不在 benchmark 前建立 ExtractorFactory、BackendRegistry、StrategyChain、fallback chain 等泛化框架。
- 不让多个 extractor 长期并存为生产 runtime fallback；benchmark 可以并行比较，生产期原则上选择一个主实现。
- 不让正文抽取器负责用户语义相关性、资源推荐、`primary_resource` 业务判断或下载决策。
- 不在本阶段改搜索引擎、平台 Adapter、下载 Provider 或归档目录。
- 不因为模型上下文有限而截断原始网页资源；“完整保存”和“给模型阅读多少”分开处理。

## Business invariants

后续无论选择哪种方案，都必须保持：

1. `education-resources` MCP 继续拥有资源业务状态与副作用。
2. 网络抓取、URL/redirect/DNS/timeout 等现有网络边界仍由项目现有受控 fetch 层负责；第三方 extractor 默认只消费已经取得的 HTML/DOM。
3. Extractor 输出是网页内容事实，不是用户偏好、SemanticReview、Resolution 或 acquisition 结果。
4. 用户相关性继续由 Skill/Main Agent 结合任务上下文判断，不把复杂语义判断重新塞回启发式代码。
5. 网页正文资源和 landing/navigation 页最终可以被区分，但该映射发生在 Inspector/业务层，不直接把第三方库自己的分类当业务真相。
6. 网页被归档时应尽量保留完整有价值内容；正常正文不能因模型上下文预算被静默裁掉。
7. 当前 `web_blocks.py` 在技术决策完成前保留为 baseline，不提前删除。

## Current architecture

相关现状：

```text
Generic Search
  -> title / source_url / snippet / small metadata
  -> immutable ResultSet

Selective Inspect
  -> GenericWebInspector
  -> HTTP/MIME/redirect/metadata/Representation facts

Acquisition
  -> generic-web-materializer
  -> web_fetch.py
  -> web_blocks.py
  -> BlockIR
  -> static HTML / Markdown / assets
```

当前 `web_blocks.py` 已支持的 Block 概念包括：

- heading
- paragraph
- list
- quote
- code
- table
- image
- linebreak

现有主内容选择大体是优先 `<article>` / `<main>`，否则退到 `<body>`；因此它很适合作为 benchmark baseline，但不默认继续承担最终正文识别算法。

## Candidate landscape

候选不混成一类，分两条 Track 比较。

### Track A — HTML 正文抽取 / Clean Content

目标：回答“网页里哪些内容是真正文，并保留哪些结构/metadata”。

第一梯队：

1. **Trafilatura**
   - Python；
   - 通用正文抽取；
   - metadata、标题层级、列表、链接、图片、表格等；
   - 与当前 Python/lxml 技术栈接入成本低。

2. **Mozilla Readability**
   - JavaScript；
   - Reader View 路线的成熟文章正文基准；
   - 重点作为质量 benchmark，不预设直接成为 Python MCP 生产依赖。

3. **Defuddle**
   - TypeScript/JavaScript；
   - 偏现代网页清洗与结构化输出；
   - 重点观察代码、数学、脚注、复杂页面和 Markdown 质量。

4. **当前 `web_blocks.py`**
   - 作为项目 baseline；
   - 用于判断成熟项目相较当前实现到底提升了什么。

按需补充，不进入首轮全量：

- Goose3 / Newspaper4k：当文章/新闻类样本出现明显差距时再加入；
- jusText：作为纯正文/boilerplate removal 对照；
- Fundus：仅新闻专项；
- Inscriptis：用于观察 layout/text/table 结构损失，不作为主正文识别器。

### Track B — URL/HTML -> Clean Markdown

目标：回答“如果最终产品要把网页保存成清晰、完整、可供用户和 Agent 阅读的 Markdown，哪条端到端路线最好”。

首轮候选：

1. **Crawl4AI**
   - 重点观察动态网页、结构清理、Markdown 完整性；
   - 不预设采用它的 Search/Crawl/Job 架构，只比较 Web -> Markdown 能力。

2. **Jina Reader**
   - 作为 URL -> LLM-friendly Markdown 的强基准；
   - 首轮重点用于结果质量对照。

3. **Defuddle**
   - 同时参与 Track A/B，观察 Clean HTML 与 Markdown 两种输出。

4. **Trafilatura + 薄 Markdown 转换**
   - 观察“正文抽取库 + 项目自己的统一表示”是否已经足够。

5. **当前 `web_blocks.py` + `web_materializer`**
   - 作为当前端到端 baseline。

架构参考但首轮不作为主集成候选：

- Firecrawl：其 Search/Crawl/Scrape/Job 能力与当前系统重叠较多，主要研究 Web pipeline 设计和结果质量；
- Turndown：只是 Clean HTML -> Markdown 的转换层，不参与“正文识别”主排名；
- MarkItDown：更适合未来 PDF/Office/EPUB 等多资源统一 Markdown 表示，不作为当前网页正文识别主方案。

> 开始执行本计划时，应重新核对各候选当时的版本、许可证、维护状态和部署约束；本计划不冻结 2026-08-13 之外的未来版本事实。

## Benchmark dataset

### 规模

首轮建议 24–30 个真实页面，数量不求大，要求类型覆盖和人工判断可靠。

### 页面类型

至少覆盖：

1. 普通长文章；
2. 新闻/媒体文章；
3. 知乎/问答式页面；
4. 古诗文/传统文化页面；
5. 技术教程；
6. 图文科普；
7. 带复杂表格的页面；
8. 带代码块的页面；
9. 图片较多且图片位置重要的页面；
10. 长页面/多章节教程；
11. 课程/资源详情页；
12. 搜索结果/目录/导航页；
13. 推荐卡片和评论较重的页面；
14. 静态 HTML 几乎无正文、需要 JS 渲染的页面。

### 样本保存原则

为了避免 benchmark 被某个当前 live 页面随时变化影响，执行时优先形成可复现输入：

- 保存 URL manifest、页面类型和人工期望；
- 对允许保存的页面，可保留测试用 HTML snapshot；
- 对版权/许可不适合直接提交完整 HTML 的第三方页面，只在本地 benchmark 数据目录保存或记录 URL + 人工期望，不把第三方完整正文提交仓库；
- 真实网页结果和人工期望分开，不能根据某个 extractor 的输出来反写“标准答案”。

## Human reference / expected facts

每个样本不做伪精确分数，人工先记录最关键事实：

```text
页面类型：article / tutorial / landing / listing / other（仅 benchmark 标注）
正文起点：
正文终点：
必须保留：
- 标题层级
- 关键段落
- 图片/图注
- 表格
- 代码块
- 列表/引用

必须排除：
- 导航
- 登录/注册框
- 广告
- 推荐阅读
- 评论
- 分享按钮
- 页脚

metadata：
- title
- author（若页面明确）
- published_at（若页面明确）
- language
```

人工 reference 只记录页面中确实存在且对用户阅读有意义的事实，不要求为每个 DOM 节点制作 gold label。

## Evaluation dimensions

不采用“ExtractionScore 0.873”一类不可解释总分作为唯一裁判。按可观察业务结果对比。

### A. 正文质量

- 正文是否完整；
- 是否错误删掉关键段落；
- 是否混入导航、广告、推荐、评论；
- 长文章是否完整保留；
- 是否把 landing/listing 错当正文文章。

### B. 结构保留

- H1–H6/章节层级；
- 段落；
- 列表；
- 引用；
- 代码块及语言信息；
- 表格；
- 链接；
- 图片、alt、caption、正文中的相对位置；
- 数学/脚注等特殊结构（样本存在时）。

### C. Metadata

- title；
- author；
- published time；
- language；
- site name / description（如果可靠）。

### D. Markdown 最终可用性

- 用户直接阅读是否自然；
- Agent/LLM 阅读是否结构清楚；
- 是否存在大量无意义链接/按钮文本；
- 图片引用是否可追踪；
- 代码/表格是否被破坏；
- 是否产生大量重复正文。

### E. 工程代价

- Python 原生还是需要 Node/浏览器；
- 是否要求 Playwright/Chromium；
- 安装和 Windows/OpenClaw 部署复杂度；
- 单页处理耗时和资源开销；
- 许可证是否适合项目；
- 是否需要维护大量站点规则；
- 是否会与现有 Search/Job/Fetch 形成重复架构。

## Benchmark protocol

同一页面必须尽量使用同一份输入比较，避免把“抓取差异”误算成“正文算法差异”。

### Protocol A — Static HTML extractor

```text
同一份 raw HTML snapshot
  -> current web_blocks
  -> Trafilatura
  -> Readability
  -> Defuddle
  -> normalized comparison output
```

用于比较正文识别本身。

### Protocol B — Web-to-Markdown

```text
同一 URL
  -> current project path
  -> Crawl4AI
  -> Jina Reader
  -> Defuddle
  -> Trafilatura-based prototype
  -> final Markdown comparison
```

用于比较产品最终效果。

如果某项目必须自己负责浏览器渲染，则在报告中明确标记“包含 rendering advantage”，不要和纯静态 HTML extractor 混为一个排名。

## Decision rules

Benchmark 结束后只选一个默认主路线，除非真实结果证明单一路线无法覆盖项目主要页面类型。

### 首选倾向

优先选择：

1. 在学习资源主要页面类型上正文完整性稳定；
2. 能保留结构而不是只给纯文本；
3. Python/现有依赖下接入简单；
4. 不要求我们复制它自己的 Search/Job/Crawl 状态系统；
5. 通过薄 adapter 就能转成项目统一表示；
6. 对失败页面能够明确返回“提取不足”，而不是静默伪造完整正文。

### 不因为单点优势引入双 runtime

例如 Readability 在新闻类略优，但 Trafilatura 在绝大多数学习资源类型表现已经足够，则不因此长期维护 Python + Node 两套主 extractor。

### 只有明显分层优势才考虑第二实现

只有当 benchmark 明确显示：

```text
方案 A 在某类占比高的重要页面上稳定失败
且
方案 B 在该类页面上稳定成功
且
无法通过简单输入/转换方式补齐
```

才重新讨论是否需要第二实现。讨论前必须重新做复杂度举证。

## Proposed target architecture after decision

如果最终采用成熟开源 extractor，建议目标形态保持简单：

```text
Existing controlled fetch
        ↓
      raw HTML
        ↓
WebContentExtractor
  (one chosen OSS implementation)
        ↓
   ExtractedPage
        ↓
┌───────────────┬────────────────┐
↓               ↓                ↓
Inspector   SemanticReview   Materializer
```

### Minimal project model

原则上只需要一个项目层结果对象，必要时沿用现有 Block 概念：

```text
ExtractedPage
├─ title
├─ author
├─ published_at
├─ language
├─ description
├─ site_name
└─ blocks
   ├─ heading
   ├─ paragraph
   ├─ list
   ├─ quote
   ├─ code
   ├─ table
   └─ image
```

第三方库自己的对象不直接扩散到 Inspector、Materializer 或 Skill。

不预建 extractor registry/factory；第一版可以只是：

```python
extract_page(html, url) -> ExtractedPage
```

## Integration roadmap after benchmark

这部分只是未来路线，不属于当前 pending 计划立即执行内容。

### Phase 1 — 独立 benchmark

- 固定样本集；
- 跑 Track A / Track B；
- 输出人工对比；
- 选择主实现。

### Phase 2 — 独立 WebContentExtractor

- 增加一个薄模块；
- 只负责 HTML -> ExtractedPage；
- 不接 MCP 状态；
- 不改变用户 Flow。

### Phase 3 — Generic Inspector integration

```text
HTML
 -> ExtractedPage facts
 -> Inspector mapping
 -> primary webpage / landing page
```

此阶段解决当前“HTML 基本只能作为 landing”与 Planner 已支持 `primary_resource + webpage` 之间的缺口。

### Phase 4 — Search semantic integration

让 Selective Inspect 后的 SemanticReview 能读取实际正文/结构事实，而不再主要依赖搜索标题和 snippet。

目标变化：

```text
Search discovery
+ body verification
```

而不是把整个网页正文塞进每次 Search 结果。

### Phase 5 — Materializer reuse

让 `web_materializer` 消费统一 `ExtractedPage/Block`，尽量删除重复 DOM/metadata 抽取逻辑。

最终保存可以继续支持统一 HTML，并按产品需要评估 Markdown 是否也成为正式 archive representation。

### Phase 6 — Wider resource unification（可选未来项）

只有网页路线稳定后，再研究 MarkItDown 等方案是否适合 PDF/Word/PPT/EPUB 等资源的统一可读 Markdown 表示；不要在当前网页专项中提前合并。

## Expected change surface when execution starts

可能新增/修改：

```text
.agent/plans/0041-web-content-extraction-benchmark.md
benchmark/web-content/...                  # 具体目录执行时再定
mcp/education-resources/pyproject.toml     # 只有最终选定依赖后才改
mcp/education-resources/src/education_resource_mcp/web_content/...  # Phase 2
mcp/education-resources/src/education_resource_mcp/adapters/inspect_generic.py  # Phase 3
mcp/education-resources/src/education_resource_mcp/acquisition/web_materializer.py  # Phase 5
```

明确暂时不应改：

```text
MCP public contracts
SQLite schema
Flow/ResultSet/Presentation/Selection
Acquisition Plan/Job model
Archive model
Search provider/platform registry
Skill task model
```

## Acceptance criteria

### AC-01 — Benchmark 代表真实使用场景

至少覆盖文章、教程、图文、代码、表格、导航/landing 和 JS-heavy 页面，不只测试几个干净博客。

### AC-02 — 当前实现也参加比较

`web_blocks.py` / 当前 materializer 必须是 baseline，不能只比较第三方项目之间谁更好。

### AC-03 — 同输入比较

正文 extractor 尽可能使用同一 HTML snapshot；端到端 Markdown 对比必须记录是否包含浏览器渲染差异。

### AC-04 — 最终结论可解释

必须能说明：

- 为什么选它；
- 哪些页面类型表现明显更好；
- 它会引入什么部署成本；
- 哪些现有代码可以删除；
- 哪些能力仍需项目自己负责。

### AC-05 — 不以抽象换未来兼容

没有真实双实现需求时，不建立 registry/factory/plugin/fallback chain。

### AC-06 — 不静默丢正常正文

如果实现存在不可避免的安全/解析上限，必须明确 partial/failure 语义；模型上下文限制不得变成资源本体截断规则。

### AC-07 — Benchmark 后再决定依赖

计划执行前不向 `pyproject.toml` 加 Trafilatura/Crawl4AI/其他候选依赖。

## Complexity exceptions

当前：无。

Benchmark 本身允许写少量独立 harness/adapters，只用于统一输出和测量，不得演化成生产多后端框架。

如果后续真的考虑双 extractor/fallback，必须先补：

```text
Problem:
Why one chosen implementation cannot solve it:
Evidence from benchmark:
Simplest alternative considered:
Why that alternative is insufficient:
New source of truth introduced:
New invariant introduced:
Failure modes introduced:
Runtime/deployment cost:
```

## Steps

- [ ] pending：执行前重新核对候选项目版本、许可证、维护状态和部署要求。
- [ ] pending：冻结 24–30 个真实网页 benchmark 类型与样本 manifest。
- [ ] pending：为每个样本人工记录正文/结构/噪声/metadata reference。
- [ ] pending：建立最小 benchmark harness，不进入生产 runtime。
- [ ] pending：运行 Track A — current web_blocks / Trafilatura / Readability / Defuddle。
- [ ] pending：运行 Track B — current path / Crawl4AI / Jina Reader / Defuddle / Trafilatura prototype。
- [ ] pending：对正文完整性、噪声、结构、Markdown、工程成本进行人工对比。
- [ ] pending：形成技术决策：主实现、明确不选方案、保留/删除的现有代码。
- [ ] pending：单独起后续实施计划接入 `WebContentExtractor`；本 0041 不直接承担生产融合。

## Validation scope

本计划未来执行阶段优先使用独立 benchmark，不跑整个 MCP 全量测试作为正文质量证明。

| Validation | Purpose | Not proof of |
| --- | --- | --- |
| Real-page benchmark | 比较正文/结构/Markdown 实际质量 | MCP Flow 正确 |
| Static fixture regression | 保证选定 extractor 对已知页面不明显回退 | live 页面永远不变 |
| Targeted unit tests | 验证 adapter/ExtractedPage 转换 | 用户真实搜索体验 |
| Generic Inspector integration test（Phase 3） | 验证 primary/landing 映射 | Search 结果整体质量 |
| Real OpenClaw resource flow（后续） | 验证最终用户链路 | 所有网页类型 |

## Decision log

### Decision 001 — 先 benchmark，不先押注 Trafilatura

- Context：当前已有自研 Block IR，同时存在成熟正文抽取和 Web-to-Markdown 开源项目。
- Options considered：直接接 Trafilatura；继续完善自研；先用统一样本比较成熟项目和当前实现。
- Chosen option：先 benchmark。
- Why：用户最终关心的是网页资源保存和阅读质量，不是实现一个自研 extractor；先比较能避免重复造轮子，也避免根据项目宣传直接选型。
- Complexity introduced：仅一个 pending 计划和未来临时 benchmark harness。

### Decision 002 — Extractor 与 Web-to-Markdown 分两条 Track

- Context：Trafilatura/Readability 主要解决正文识别，而 Crawl4AI/Jina Reader 等更接近最终 URL -> Markdown 产品效果。
- Chosen option：分别比较，最终从产品结果统一决策。
- Why：避免把浏览器渲染、正文识别、Markdown 转换三种能力混成一个不可解释排名。

### Decision 003 — 生产期原则上单主实现

- Context：benchmark 可以比较很多实现，但用户明确希望控制复杂度。
- Chosen option：除非数据证明明显必要，否则最终只保留一个主 extractor/WebContentExtractor 路线。
- Why：避免 fallback chain、双 runtime 和后续维护成本。

## Resume condition

本计划当前只“放着”。后续只有在明确决定继续推进网页资源内容质量时，将状态从 `pending` 改为 `in_progress`，再开始第一个步骤。

恢复时第一件事不是写代码，而是重新核对：

1. 当前网页链是否已经发生变化；
2. 当前 `web_blocks.py` / Generic Inspector / Materializer 是否仍是上述结构；
3. 候选开源项目当时的最新版本、许可证与部署约束；
4. benchmark 样本是否仍代表真实使用场景。

没有完成这些检查前，不直接接入候选库。
