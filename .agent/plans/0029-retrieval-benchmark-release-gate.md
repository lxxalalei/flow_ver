# 0029 — Semantic Retrieval Benchmark 与 Release Gate

- 状态：pending
- 创建日期：2026-08-08
- 更新日期：2026-08-14
- 完成日期：未完成
- 范围：`learning-resource-flow` 的语义决策质量、检索结果质量、必要 Inspect 决策，以及不可破坏的 MCP 业务边界
- 真实 Agent 证据：[`0028 Real OpenClaw and Real Platform E2E`](0028-real-openclaw-platform-e2e.md)

## Objective

建立一套版本化、可重复、能逐 case 审查的资源检索质量评测，使每次 Skill/Search 相关修改都能回答：

- 模型有没有理解用户真正想完成什么；
- 搜索角度是不是少量、互补而不是关键词改写；
- 来源/平台是不是因为内容或证据需求而选择；
- query 是否像该来源里的真实搜索；
- 搜到结果以后能不能识别“关键词命中但实际没用”；
- 是否只在存在明确缺口和更好的下一路线时继续搜索；
- 是否在需要时 Inspect、在不需要时不过度 Inspect；
- 最终推荐是否真正满足用户目标和显式约束。

Benchmark 的主要对象是 **semantic decision quality**，不是让模型复现 MCP 的内部状态机。MCP 的状态、安全和副作用约束作为独立 hard gate 验证。

## Why this plan changed

0029 最初写于 Flow-heavy Skill 阶段，当时把 `SemanticReview / Gap / StopDecision`、旧 Capability Authority、Readiness/Eligibility/digest 链作为大量 benchmark 字段和指标。

0046 已把 active Skill 重构为 semantic-first：模型负责需求理解、搜索角度、来源派发、query、结果判断和自然的补搜/停止判断；MCP 负责 Flow/ResultSet/Presentation/Selection/Resolution/Plan/Job/Asset 等事实和副作用。

因此 0029 不应把已经退出模型主思维的术语重新做成评测目标，否则 benchmark 会反向迫使 Skill 再次变成 Workflow Operator Manual。

## Non-goals

- 不建立第二套生产状态机、Planner、Intent Service 或 SemanticReview 服务。
- 不要求模型输出内部 chain-of-thought、固定 JSON 推理模板或 `Gap/StopDecision` 对象。
- 不用 Tool 调用数量、平台数量、搜索轮数或“成功走完 Flow”代替语义质量。
- 不以固定 120 cases 等数量目标推动低信息密度样本堆积；case 数量由真实覆盖缺口驱动。
- 不通过随机重试、多次取最好结果、放宽 gold 或删除负例提高分数。
- 不为 benchmark 增加 benchmark digest、authority digest 或新的运行时哈希链。
- 不访问真实平台、不执行真实下载、不读取真实凭据；真实网络/OpenClaw 证据继续由 0028 独立记录。
- 不把 benchmark 结果写回生产 SQLite 或 MCP 业务状态。

## Business invariants

1. Skill 负责语义研究与决策；MCP 负责事实、状态和副作用。
2. ResultSet/Resolution/Provider/Asset 等事实只能来自 MCP/fixture，不由 evaluator 或模型补造。
3. `prepare -> 用户明确确认 -> start` 不因 benchmark 被绕过。
4. exact Provider 失败后不切 generic、其他 provider、scope 或 strategy。
5. benchmark 可以测“是否应该 Inspect”，但不能把 Inspect 全量化当高分行为。
6. 真实 OpenClaw 成功率与离线 semantic score 分开报告；两者不能互相替代。
7. Gold 描述可接受的决策边界，不要求所有模型逐字给出同一自然语言答案。

## 评测对象

### 1. Need reconstruction

判断模型是否从用户原话还原实际目标，而不是直接生成关键词。

例：

```text
用户：帮孩子找一些火山科普资料，形式你看着办。

合理：目标是建立火山喷发的原理理解与过程直观认识。
机械：topic=火山；query=儿童优质火山科普资料。
```

### 2. Clarification judgment

只在答案会导致明显不同搜索路线时追问。

重点同时惩罚：

- 关键分叉存在却直接猜；
- 信息已经足够却为了填字段追问平台、数量、年龄等；
- 搜索结果差就反过来追问用户已经说明的约束。

### 3. Search angle quality

好的搜索角度描述不同的信息/学习价值，例如：

```text
喷发原理理解
喷发过程观察
```

而不是：

```text
火山
火山知识
火山科普
儿童火山科普
```

不要求固定角度数量。窄任务一个角度即可；宽任务只有在确实需要互补价值时才扩展。

### 4. Source routing quality

来源选择必须能回答“为什么这个来源对当前角度有独特价值”。

例如：

- 观察过程 → 视频/公共媒体生态；
- 教材同步 → 结构化教育来源；
- 版本/ISBN/古籍 → 图书目录、公版/古籍来源；
- 朗读/故事 → 音频来源；
- 具体公开文件 → 文档来源或 Generic Web。

不因 Registry 里存在某平台就机械派发，也不以平台覆盖数计分。

### 5. Query quality

Query 应是对应来源中的自然搜索表达：主题 + 当前切面；只有确实影响召回时才加入学段、版本、格式、语言等条件。

需要识别的反模式包括：

- 原句整段复制；
- 机械拼接所有约束；
- `优质 / 精品 / 权威 / 高赞 / 最好` 等评价词替代候选判断；
- 同一来源首轮发多条近义 query；
- 为了表现“规划”制造没有召回差异的 query。

### 6. Result judgment

Search 返回很多结果不等于任务完成。

评测模型是否会检查：

- 与目标的真实相关性；
- 对实际使用者是否合适；
- must / exclude 是否满足；
- 是否有实质内容而不是聚合、广告、空壳详情；
- 当前任务所需可信度是否足够；
- 多个候选是否互补而不是重复。

### 7. Inspect decision

Inspect 是为决策补事实，而不是流程仪式。

好的判断包括：

- 用户要求公开可读/可下载，而 Search 只有线索 → Inspect 高潜候选；
- 需要确认 primary resource vs landing page → Inspect；
- 标题/摘要已经足够做初步推荐、用户也没要求获取 → 不为全部候选 Inspect；
- Prepare 前需要 fresh Representation → 进入获取阶段按 MCP 事实执行。

### 8. Next action quality

搜索后自然选择：

- `clarify`：仍存在会改变路线的关键歧义；
- `search`：能指出一个具体缺失部分，并存在明显不同的下一条搜索路线；
- `inspect`：一个具体事实会改变推荐/获取决策；
- `present`：当前结果已经足够帮助用户选择；
- `stop_with_limit`：无法进一步可靠改善，应明确说明限制。

Evaluator 判断的是**理由是否符合实际任务**，而不是要求模型输出上述标签。

## Case schema

每个 case 保持可人工审查，不要求把模型思考过程结构化落盘。建议字段：

```text
case_id
benchmark_version
task_family
messages / user_utterance
available_user_context              # 仅该 case 明确提供的上下文
explicit_constraints
fixture_search_results              # 可选；确定性搜索事实
fixture_inspection_facts            # 可选；确定性 Inspect 事实

expected_need                       # 目标/使用者/成功标准的关键点
critical_ambiguity                  # null 或真正会分叉的歧义
acceptable_search_angles            # 可接受方向及职责，不要求唯一措辞
source_role_expectations             # 来源需要承担什么角色；仅必要时固定平台
query_expectations                   # 应包含/不应包含的搜索意图特征
recommendable_ids                    # 基于 fixture 确实适合推荐
forbidden_recommendation_ids         # 明确不应展示的候选
facts_requiring_inspect              # 哪些事实不足会改变决策
acceptable_next_actions              # 基于当前事实可接受的下一步
rationale
critical_invariants
```

Gold 不要求模型输出内部 chain-of-thought。可观察输出、Tool arguments、选择的平台/query、实际 Presentation 和下一步行为足以评估。

## Case families

不设为了凑数量的总 case 数门槛。初始集合应优先覆盖高信息密度边界，并在真实失败出现时扩充：

| 任务族 | 重点覆盖 |
| --- | --- |
| 已充分指定的窄任务 | 不该追问；直接形成高质量 query |
| 真正存在路线分叉的模糊任务 | 关键澄清而非字段收集 |
| 多形态学习任务 | 是否形成真正互补角度 |
| 可打印/具体文件任务 | 内容形态 vs 文件格式；不误派视频 |
| 教材/课程同步 | 学段、版本真的影响路线时才追问 |
| 图书/版本/古籍 | 书名、作者、版本、ISBN、Shuge/NLC 等来源职责 |
| 音视频过程观察 | 视频/音频生态的正确职责 |
| 结果数量多但方向错 | 不因数量充足而过早推荐 |
| Search 摘要不足 | 有选择地 Inspect 高潜候选 |
| 公开访问/无需登录 | availability/auth 事实必须被核验 |
| 网页 primary vs landing | 不把导航页当资源本体 |
| 部分失败/来源不可用 | 不掩盖失败、不无意义扩散平台 |
| 用户只想搜索不下载 | 不越权进入 Prepare/Start |
| 用户明确选择并下载 | Presentation/Selection/确认安全 gate |
| 上下文中已有可靠信息 | 不重复追问，也不扩展成长期偏好 |

每个任务族至少要有能够区分“看起来合理”和“真正决策正确”的正例、负例或边界例；发现新系统性失败时增加能复现该失败的 case，而不是机械扩充数量。

## 评分方式

### 语义维度

沿用 `skills/learning-resource-flow/examples/semantic-evaluation.md` 的 0/1/2 三档思想，不做伪精确加权总分：

- `0`：核心判断错误，或工作流合规但实际资源决策明显失败；
- `1`：基本相关，但仍有机械派发、机械 query、无效澄清或结果判断不足；
- `2`：目标还原、搜索角度、来源职责、query 和基于结果的调整都合理。

分别记录：

1. Need reconstruction
2. Clarification judgment
3. Search angle quality
4. Source routing quality
5. Query quality
6. Result judgment
7. Inspect decision
8. Next action quality

不要用单一综合分掩盖某个维度的系统性退化。

### 候选结果指标

有确定性 fixture 时可以计算：

- **Recommendation Precision**：实际 Presentation 中适合推荐的比例；
- **Forbidden Recommendation Rate**：明确不应推荐的候选进入 Presentation 的比例；
- **Constraint Satisfaction**：must/exclude 是否被真实满足；
- **Inspect Precision**：被 Inspect 的候选中确实需要补事实的比例；
- **Inspect Recall**：gold 明确必须核验的关键事实是否被核验；
- **Redundant Search Rate**：没有新信息价值的近义搜索比例。

这些指标只解释可观察行为，不尝试量化模型隐藏思考过程。

## Hard gates

以下不是语义加分项，而是零容忍业务边界：

1. 模型不得伪造 `flow_id`、ResultSet、Resolution、Provider、Plan、Job、Asset、Archive 或本地路径。
2. 用户序号选择必须绑定实际 Presentation；不能选择没有展示的候选。
3. 未经当前 Plan 的用户明确确认不得 `resource_download_start`。
4. Start/Job 只执行 Plan 的 exact Provider；失败后不得 silent fallback 到 generic、其他 provider、scope 或 strategy。
5. AUTH_REQUIRED、unavailable、policy block 等事实不得被隐藏或乐观改写。
6. 未产生真实 ready Asset 不得报告下载成功或可归档。
7. Skill 资源任务不得绕开 `education-resources`，使用 browser/web/curl/其他 MCP 建第二条候选发现或获取数据面。
8. MCP 当前公共 Tool 数为 14；benchmark 不要求新增工具来满足评测。

状态版本、幂等、Representation freshness 等后端机械约束继续由 MCP 单元/集成/E2E 测试负责；它们不需要被重新包装成模型的语义 benchmark 状态机。

## A/B 方法

至少保留一个 Flow-heavy Skill 的 Git ref 作为历史 baseline，与 semantic-first Skill 使用：

```text
同一 Main Agent 模型
同一用户输入
同一 fixture / MCP 事实
同一运行参数
唯一主要变量：Skill 版本
```

逐 case 保存：

- 是否澄清以及问了什么；
- 实际平台/来源与 query；
- Search/Inspect 的可观察调用；
- 实际展示候选；
- 是否识别错误方向并调整；
- 下一步行为；
- 用户可见解释；
- Tool 调用数和无效搜索数，仅作为成本参考。

A/B 目标不是证明新版“Tool 更少”，而是确认新版在多数代表性任务中稳定做出更好的资源研究决策，并且没有新的系统性失败。

## Offline runner

开始实施时，runner 应尽量简单：

```text
benchmarks/
├── cases/
├── fixtures/
├── baselines/
└── README.md
scripts/run_semantic_benchmark.py
```

输出：

- case-level JSON：输入、可观察决策、各维度评分/断言结果、hard gate；
- Markdown 报告：按失败模式分组，展示 baseline vs candidate 差异；
- 失败返回非零退出码。

不为 runner 新建服务、数据库或 Runtime Registry。baseline 用普通版本化 JSON 保存即可，不增加 digest 权威链。

## 与现有语义回归的关系

`skills/learning-resource-flow/examples/semantic-regression-cases.json` 与 `semantic-evaluation.md` 是当前 seed，而不是需要推翻重写的第二套系统。

0029 实施时应：

1. 先复用其中高质量 case；
2. 加入 0028 的真实 OpenClaw 失败/成功场景；
3. 加入会区分旧 Flow-heavy 与 semantic-first 行为的边界 case；
4. 只有出现新覆盖缺口时再增加 case。

避免复制同一语义只改标题、平台名或主题来凑数量。

## 真实 OpenClaw 验证

Offline benchmark 不能证明真实 Agent 运行质量。

0028 独立记录真实：

```text
用户自然语言
→ Skill 实际分析
→ Search/Inspect
→ 实际候选
→ 选择/确认
→ 下载/Asset（如任务需要）
```

对 Skill 语义改动，应从 0029 代表 case 中抽取若干场景在真实 OpenClaw 上执行 A/B。真实成功率、真实失败阶段和用户可见结果单独报告，不能被离线分数覆盖。

## Release gate

首个可信 baseline 建立后：

- Hard gates：0 failure。
- Forbidden Recommendation Rate：不得恶化；目标为 0。
- Need/Clarification/Angles/Source/Query/Result/Inspect/Next-action 八个维度不得出现新的系统性退化。
- 关键真实场景若 candidate 明显劣于 baseline，应阻断相关 Skill/Search 修改，直到逐 case 解释并修复。
- Tool 成本可作为辅助比较，但不能通过少搜、少 Inspect 换取低质量结果。
- 真实 OpenClaw 尚未验证的版本必须标记 `real_e2e=not_verified`，不能由 fixture/单测代替。

发布判断以“是否产生可解释的用户价值退化”为核心，而不是一个加权总分阈值。

## Steps

- [ ] pending：A. 从现有 semantic regression + 0028 真实反馈整理第一版高信息密度 case 集，并冻结可观察字段与评分说明。
- [ ] pending：B. 实现最小 offline runner 与 baseline/candidate 对比报告，不引入生产状态或 digest 链。
- [ ] pending：C. 为八个语义维度、候选结果指标和 hard gates 添加直接测试。
- [ ] pending：D. 运行历史 Flow-heavy Skill vs semantic-first Skill A/B，逐 case 审查系统性差异。
- [ ] pending：E. 抽取代表 case 在真实 OpenClaw 中执行并把结果关联到 0028。
- [ ] pending：F. 建立本地/release 入口；只有达到 hard gates 与无系统性语义退化后才批准 baseline。

## Completion criteria

1. case 集覆盖当前主要资源决策边界，并能复现至少一批历史真实失败/退化模式；不以总 case 数作为完成标准。
2. 每个语义维度和 hard gate 都有可观察、可复核的判定方法。
3. Offline runner 能稳定比较 baseline/candidate 并生成逐 case 差异，不依赖网络或真实凭据。
4. Flow-heavy vs semantic-first A/B 已形成可审查结论，而不是只比较 Tool 调用是否成功。
5. 真实 OpenClaw 代表场景已由 0028 记录；未验证项明确标记。
6. Benchmark 没有反向把 Skill 重新塑造成 MCP Workflow Operator，也没有引入第二套业务状态权威。
