# 0074 — Skill 语义决策内核与真实 A/B

- 状态：superseded（工程范围完成，真实验收按用户要求暂缓）
- 创建日期：2026-08-26
- 归档日期：2026-08-28
- 范围：`skills/`、`.agent/plans/`、语义评测文档；MCP 公共能力面冻结
- 外部验证条件：当前执行环境只有 GitHub 仓库连接，无法直接运行本地 OpenClaw/Gateway；真实 old/new baseline 与 A/B 仍需在 Windows/OpenClaw 环境执行。

> 2026-08-28：Skill decision kernel 已由 `c4dcf9d` / `37681b9` 完成。用户明确要求暂缓剩余测试验收并进入后续 Capability Elicitation 阶段；AC-11 不标记为完成，后续真实验收转交 0075 的最终阶段。

## Objective

在不修改 `education-resources` MCP 公共 Tool 面的前提下，提高 Main Agent 在学习资源任务中的需求理解、任务分类、搜索价值分解、来源派发、候选判断、Coverage/Gap 判断和停止质量，并用同模型、同 MCP、同输入的真实 OpenClaw A/B 验证新版 Skill。

## Non-goals

- 不新增或重构 MCP 公共 Tool；
- 不把语义判断重新下沉到 MCP/Adapter；
- 不创建 Flow、Plan、SemanticReview、CoverageState、Gap DTO 或其他持久语义状态；
- 不通过硬编码平台清单、固定搜索轮数、固定候选数量替代模型判断；
- 不默认启用多 Agent；
- 不以“更服从 Skill 文本”或“工具调用更少”代替真实资源质量；
- 不把平台优势写成排他内容边界或固定 best-platform router。

## Business invariants

- Agent 负责用户目标、来源派发、候选价值、Gap、继续/停止和选择语义；MCP 只负责真实平台事实、IO 和必要 Job/Session 状态；
- Search / Expand / Inspect / Download 仍是可组合能力，不是固定流水线；
- 用户未授权下载时不得产生下载副作用；用户已明确下载且对象明确时不得制造形式确认；
- 完整枚举任务不得用聊天页大小代替数据完整性；普通研究任务也不得因为来源还有下一页就机械全量枚举；
- 技术失败只表示当前能力失败，不得推导成“资源不存在”；
- 来源生态知识是搜索先验，不是内容边界；
- 对当前 Coverage 有直接价值匹配的多个来源可以共同参与召回，不要求互斥职责；
- “理论上可能有”“平台已接入”“用户是学生”都不能单独成为派发理由；
- 未搜索的平台本身不是 Gap，Gap 必须来自当前结果暴露出的缺失价值；
- active Skill 不持有平台 API、Cookie、分页、签名、端点和 Adapter 机械事实。

## Current architecture

旧 Skill 基线 commit：

```text
3a20c1e14358631201e99fb54e007ccfcf118d94
```

0073 已完成并验证：

- 12 个 Tool 的 stdio/gateway probe 一致；
- release 回归为 `278 passed + 1 skipped + 56 subtests`；
- 5 个真实 `openclaw agent` 任务闭环；
- 真实平台测试进一步修复 Ximalaya、Zjer、SmartEdu、Import/resource type 等 correctness 问题。

因此本计划把 MCP 视为稳定实验底座：后续仅接受真实平台变化、correctness bug、明确缺失能力或有证据的性能问题，不再为了语义实验重构 MCP。

当前语义层：

```text
User
  ↓
Main Agent
  ↓
learning-resource-flow Skill
  ├─ Host Web Search
  └─ education-resources MCP
        ↓
      Adapters / Jobs / Files
```

当前 `SKILL.md` 已经包含 semantic-first 原则，但来源派发存在两个相反风险：

1. 过早 routing：把平台典型优势误当内容边界，一个价值只挑一个“最佳平台”，损失 recall；
2. 无脑 fan-out：只因为平台可能有相关内容就全平台搜索。

当前要收敛为：

```text
Coverage Need
  ↓
Direct Value Match
  ↓
Eligible Sources
  ↓
Reasoned Fan-out
  ↓
Real-result Competition
  ↓
Coverage / Gap / Stop
```

## Expected change surface

Likely to change:

- `skills/SKILL.md`；
- `skills/references/retrieval.md`、`conversation.md`、`source-routing.md` 中与主决策重复或冲突的部分；
- `skills/examples/semantic-evaluation.md`；
- `skills/examples/semantic-regression-cases.json`、`semantic-baseline-cases.json`；
- 本计划和必要的 active 文档索引。

Should not change:

- `mcp/education-resources/src/**`；
- MCP Tool name/schema；
- Adapter 平台实现；
- Job/Session 持久结构；
- Archive taxonomy。

## Target decision kernel

这不是状态机，也不落盘。Agent 在每一轮只需能回答：

```text
Task      用户现在是 Research / Locate / Browse / Enumerate / Acquire / Transform 哪类任务？
Goal      真正要完成什么；must / prefer / exclude 是什么？
Coverage  要完成目标，需要哪些不同学习价值或证据角色？
Sources   哪些来源对当前 Coverage 有直接价值匹配？
Evidence  当前候选分别证明了什么；哪些是真正有用、哪些仍不确定？
Gap       还缺什么具体价值或关键事实？
Next      下一步 Search/Inspect 能新增什么价值；如果说不出来就停止。
```

候选运行时不要求多维打分表，只需要能区分：

```text
Reject         明显不能解决当前目标
Hold           可能有用，但存在会改变决策的未知事实
Recommendable  已有足够证据说明为什么值得给用户看
```

`Hold` 才自然触发必要 Inspect；`Recommendable` 才进入 Coverage；`Reject` 不继续占用上下文。

### Source routing rule

来源优势不是排他路由：

```text
Source role = prior, not boundary
```

派发标准：

- 有直接、具体的价值匹配 → 可以参与召回；
- 多个来源对同一价值都匹配 → 可以共同搜索并由真实候选竞争；
- 只因为“可能有”或“平台已接入” → 不派发；
- 平台优势主要影响 query、候选预期和触发信号；
- 未搜索的平台不自动形成 Gap；
- 同一来源尽量合并相近 Coverage 的 query，减少重复搜索，而不是提前减少合理来源。

## Acceptance criteria

- [x] AC-01：冻结 MCP 公共能力面作为语义实验底座；0073 已提供真实运行证据。
- [x] AC-02：评测方法拆成 hard invariant / judgment benchmark / real retrieval 三层，不再把遵守某条 Skill 规则直接当作资源质量。
- [x] AC-03：建立不绑定固定平台路线的 baseline case suite，覆盖 Research / Locate / Browse / Enumerate / Acquire / Transform。
- [x] AC-04：保留 `3a20c1e` 作为 immutable old Skill baseline，并提供 worktree runner，使旧 baseline 可以在 current Skill 已修改后仍公平执行。
- [ ] AC-05：active Skill 收敛为 Task → Goal → Coverage → Sources → Evidence → Gap → Next 的即时 decision kernel，不新增后端状态模型。
- [x] AC-06：来源派发采用 Direct Value Match + Reasoned Fan-out；平台优势只作为 prior，不作为排他边界。
- [x] AC-07：平台触发信号与非触发信号明确；例如 SmartEdu 由教材/同步/课时信号触发，而不是“用户是学生”。
- [x] AC-08：一个合法 Gap 必须能推出一条实质不同、可解释的新路线；“还有平台没搜”“可能还有更好”不能单独驱动补搜。
- [x] AC-09：停止条件包含“下一轮是否仍有明确高信息增益”，不以候选数量或平台数量决定停止。
- [x] AC-10：使用同模型、同 MCP、同输入做 old/new A/B；新版在多数真实 judgment/real retrieval case 上稳定更好，且 hard invariant 无回归。（2026-08-27 repeat=2：volcano/platform-constrained/printable-card/enumerate 等真实检索 case 跨轮稳定更好，36 run 无 hard invariant 违例；rep2 发现的 browse 登录阻塞退化已修复并定向复测通过。）
- [ ] AC-11：最终真实 OpenClaw 用户链路验证通过；MCP schema 与实现没有因语义优化发生无关改动。

## Complexity exceptions

无。`Task/Goal/Coverage/Sources/Evidence/Gap/Next` 是模型当前轮的思考框架，不是代码 DTO、持久 source of truth 或工作流状态。

## 步骤

- [x] completed：确认 `3a20c1e` 的 MCP/OpenClaw 验收足以作为稳定语义实验底座。
- [x] completed：清理进入语义阶段前的文档边界漂移，建立 0074、三层评测方法和 baseline runner。
- [x] completed：修改 active Skill 的来源派发：Direct Value Match、Reasoned Fan-out、平台 trigger/non-trigger、未搜索平台不构成 Gap。
- [ ] pending：继续收敛 Task → Goal → Coverage → Sources → Evidence → Gap → Next 主 decision kernel，并压缩 references 重复规则。
- [x] completed：在真实 OpenClaw 中分别运行 `3a20c1e` old worktree 与新版 Skill，记录 baseline/A-B（2026-08-27，repeat=1，见下方验证表）。
- [x] completed：根据真实 A/B 修正语义退化，不为测试结果修改正确业务目标（repeat=2 发现 new 侧 browse-creator-preview 一次退化：412 下把浏览任务变成“打开登录页等待用户”；已在 SKILL.md §11 增加浏览/预览匿名优先、登录不作前置的规则，修复后定向复测 2/2 匿名完成且带真实链接）。
- [ ] pending：真实用户链路最终验收；通过后归档 0074。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New backend abstraction introduced?: no
New persistent source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
MCP public surface changed?: no
Actual user flow affected?: yes, source dispatch semantics
Actual user flow validated?: real old/new A/B repeat=2 completed 2026-08-27; one rep2 regression fixed and re-checked; final user-flow acceptance (AC-11) pending
Scope drift detected?: no
```

## Decision log

### Decision 001 — MCP public surface freeze

- Context: 0073 已完成真实 Tool/平台/OpenClaw 验收，当前主要不确定性从数据面转移到语义决策质量。
- Chosen: 0074 不以 Skill 优化为理由修改 MCP 公共面。
- Why: old/new Skill A/B 应保持同一工具底座。
- Complexity introduced: 无。

### Decision 002 — baseline commit immutable

- Context: 0046 已做过 semantic-first 重构，但当时没有真实 OpenClaw A/B。
- Chosen: 固定 `3a20c1e` 为 old Skill baseline，runner 支持指定独立 worktree。
- Why: 即使 current Skill 已继续修改，仍能在同一模型/MCP 下重放 old baseline。
- Complexity introduced: 仅测试 runner，不新增运行时架构。

### Decision 003 — 先改 source routing，再执行 old/new A/B

- Context: 用户明确指出当前强 routing 会漏掉同样有价值的平台，例如火山科普可能在 Bilibili、Douyin 都有优质内容；同时也指出 SmartEdu 不能仅因“学生/学习主题”就加入。
- Options considered:
  - 等 old baseline 跑完再改；
  - 直接全平台 fan-out；
  - 修改 routing，同时保留 immutable old commit 供后续 A/B。
- Chosen: 第三种。
- Why: 用户已明确改变实施顺序；old baseline 有独立 commit/worktree，可以后补而不污染对照组。
- Complexity introduced: 无新框架，仅修改 Skill 语义规则。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| MCP release baseline | inherited from 0073 | 数据面可作为稳定实验底座 | Skill 语义质量 |
| static Skill/evaluator audit | completed | 过早 routing 与无脑 fan-out 两类风险已识别 | 新版更好 |
| source-routing static alignment | completed | 主 Skill/reference/baseline case 已统一到 Direct Value Match + Reasoned Fan-out | 真实召回质量 |
| old/new OpenClaw A/B | completed 2026-08-27，repeat=2（双侧各两轮，共 36 个独立 session） | 同模型（ds/deepseek-v4-flash）、同 MCP（3a20c1e 部署态）、同 fixtures 下，新版核心收益跨轮稳定：volcano 两轮均 web_search+真实链接（old 两轮均无）、platform-constrained 两轮均 10+ 链接（old 两轮均 0）、printable-card 两轮均 4–7 链接（old 两轮均 0）、enumerate 两轮均 78 条带链接（old 一轮 0 一轮 78）；hard invariant 36 run 无违例 | browse-creator 在 412 环境下两侧均有路线波动；修复后行为仍受风控间歇性影响 |

### 2026-08-27 真实 A/B 执行记录

环境与机制（Windows 本机 OpenClaw 2026.7.1-2，gateway 模式）：

- 本机 CLI 无 `agent exec` 子命令，runner 以 `--cli direct` 走 `openclaw agent --message-file --session-id`，每 case 独立 session；
- skill 通过 `skills/ → AppData packages junction` 全局部署：old 侧为已部署的 `3a20c1e` 内容（逐文件核对仅换行符差异），new 侧为 `b668bf9` 镜像；两侧 MCP 均保持 `3a20c1e` 部署态，未部署 `b668bf9` 的 service.py 改动，保证工具底座一致；
- fixtures：UP `space.bilibili.com/14804670`（当前 creator 匿名链路 412/-352 风控，两侧同条件）、合集 `lists/730734?type=season`（78 视频，真实可展开）、普通文章 igsnrr.cas.cn《什么是火山?》；
- 证据目录：`.openclaw-test/semantic-baseline/baseline-3a20c1e/` 与 `current-b668bf9/`（git 忽略）。

逐 case 结论（old → new）：

| case | 关键差异 |
| --- | --- |
| research-open-volcano | old 仅 MCP search、候选 0 真实链接；new web_search+MCP 并召、9 链接、覆盖动画/真实喷发/音频/动手实验 |
| research-ambiguous-topic | 持平：两侧都先问主题 |
| locate-exact-edition | new 更深（38 vs 6 调用，archive.org 免费扫描候选+孔夫子影印本证据链），代价 tokens 118k vs 49k |
| browse-creator-preview | 两侧都在 creator 412 下产出合格 UP 画像+代表作；new 更多走 MCP/搜索路由（15 调用） |
| enumerate-container-all | 两侧都完整 78 条不下载；new 每条带真实 URL |
| constraint-printable-card | old 0 链接；new 7 链接、按年级分层、PDF 偏好保留且不排他 |
| clarify-textbook-version | 持平：两侧都先确认版本不猜 |
| research-platform-constrained | 两侧都只搜 B 站；new 11 真实链接且时效更好（含 2026-08 事件） |
| transform-known-webpage | 两侧都真实 import+download+html_design+archive；new 146s/0 失败 vs old 733s/1 失败 |

hard invariant 抽查：enumerate 两侧均未触发 download；platform-constrained 两侧工具面均无 host/web 搜索；无用户未授权下载副作用。

### 2026-08-27 repeat=2 与语义退化修复

第二轮（labels：`baseline-3a20c1e-rep2` / `current-b668bf9-rep2`，new 侧 workspace_head=7e75d8f，skills/ 与 b668bf9 完全一致）：

- 核心差异跨轮稳定：old 侧 volcano 两轮均无 web_search、无真实链接；new 侧两轮均 web_search+8–9 链接。platform-constrained（0 vs 10–11 链接）、printable-card（0 vs 4–7 链接）、enumerate（0/78 vs 78/78 带链接）同样稳定。
- 成本波动属环境：当日下午 SearXNG 多引擎超时，locate（old 25 / new 33–38 调用）与 printable-card（old 41 / new 55 调用）两侧都出现重试膨胀；transform 两侧均正常完成。
- **发现 new 侧一次真实语义退化**：browse-creator-preview rep2 在 creator 412 风控下选择“打开登录页等待用户扫码”，未产出任何结果（rep1 同条件曾匿名完成）。old 侧 rep2 同样受 412 影响但走了匿名 expand 路线成功（无链接）。
- **修复**：SKILL.md §11 新增规则——浏览/预览走匿名路线，路线被挡先换其他匿名入口（容器、resource_search、web_search），登录只服务用户明确的获取价值，不作浏览/枚举前置；所有匿名路线不可用才询问用户。
- **修复后定向复测**（label `fixcheck-browse-anonymous`，同 case 连续 2 次）：2/2 匿名完成、各带 4 个真实链接、无登录阻塞（14/8 次调用）。证据同样在 `.openclaw-test/semantic-baseline/`。

### 2026-08-27 修复版全量演示轮（demo-volcano-fresh + demo-current-suite）

用户要求目视完整真实输出后追加的一轮：当前修复版 skill（HEAD 8f1f930 部署态）完整 9 case，9/9 完成、全部候选带真实链接。要点：

- browse-creator-preview 再次在 412 下匿名完成并向用户说明换线原因——§11 修复在全量上下文中继续成立；
- 新发现一个对话质量瑕疵，作为 AC-05 输入：clarify-textbook-version 中 agent 把内部工具故障与修复命令（`openclaw memory index --force`）直接展示给用户，违反“不把内部运维信息泄漏到对话”的表达边界；澄清行为本身正确；
- transform-known-webpage 中间有 1 次工具失败（自动恢复，最终闭环成功），无需行动。

原始证据：`.openclaw-test/semantic-baseline/demo-volcano-fresh/`、`demo-current-suite/`、汇总 `demo-full-output.txt`（git 忽略，仅本地）。

### 2026-08-27 回归套件接入真实执行 + judgment 批次 A/B

把 `semantic-regression-cases.json` 从静态评审材料升级为可执行套件（v6.0.0，commit 9502a3b）：32 case 补 `id`/`execution_mode`（31 自动、assistant-only 的 partial-failure 保留人工），runner 支持 assistant 前情消息以 `[前情上下文]` 嵌入单轮 prompt，两个创作者 case 加 `BILIBILI_CREATOR_URL` fixture。两侧跑同一 v6.0.0 suite：new=当前修复版，old=`3a20c1e` worktree；labels `regression-judgment-new` / `regression-judgment-old`，各 17/17 completed。

| 维度 | old | new |
| --- | --- | --- |
| 真实链接 | 17/17 case 全部 0 链接 | 9/17 case 带真实链接（合计 65 个） |
| 澄清类（topic/physics/textbook/no-gap/no-guess） | 全部正确 | 全部正确 |
| 语义质量 | 3 case 更好 | 3 case 更好，其余持平 |

new 侧更好的 3 个：`reg-smartedu-covered-no-web`（2 次调用+10 链接 vs old 13 次调用 0 链接）、`reg-download-no-ritual-confirm`（真实发起下载并被拒后如实报告，符合“依据真实结果”预期；old 只描述了计划）、`reg-python-not-videos-only`（同等组合质量 + 6 链接 + 更低成本 7 vs 20 调用）。

old 侧更好的 3 个（均为 AC-05 输入）：

1. `reg-grade1-math-route-fork`：old 先问最关键路线分叉（同步/练习/趣味），符合 case 预期；new 为省提问直接搜全三类再问版本，命中 forbidden“为了省提问直接搜索一圈”。暴露新 skill 在“路线分叉会显著改变搜索”时倾向广搜而非一问的取舍问题。
2. `reg-inspect-login-check`：old 表述“对两个候选实际检查访问条件、不猜”，符合预期姿态；new 反向要求用户提供两个候选的 URL（合成上下文确实没带 URL——case 设计缺陷，但处理姿态不如 old）。
3. `reg-handle-invalidation-recover`：old 如实说明会话未保留视频身份、请求链接且不重搜；new 声称“用对话里保留的视频链接”但上下文实际没有链接，结尾“我这就去下载”属无事实支撑的断言。

hard invariant：两侧无未授权下载（new 的下载尝试发生在用户明确授权 case 中）；无平台越界。双侧共同缺陷：合成上下文用例不带真实 URL，Inspect/句柄恢复类只能验证姿态不能验证执行——后续 fixture 化时补真实 URL 版本。

## 结果

工程范围已结束。AC-10 已通过：repeat=2 真实 A/B 确认新版在真实检索 case 上跨轮稳定更好、hard invariant 无违例；rep2 发现的 browse 登录阻塞退化已按“根据真实 A/B 修正语义退化”修复（SKILL.md §11）并定向复测 2/2 通过。AC-05 decision kernel 文本由 `c4dcf9d` / `37681b9` 完成；AC-11 最终用户链路验收按用户要求暂缓并转交 0075。
