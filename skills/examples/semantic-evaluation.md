# Semantic Evaluation Guide v6

这份评测用于判断 `learning-resource-flow` 是否真的提升了模型找资源的语义能力，而不是判断模型有没有复述 Skill 规则、走完整工具流程或调用更多平台。

核心原则：

> **评测用户目标是否被更好完成，不评测 Agent 是否更像 Skill 文本本身。**

同一个用户输入可能存在多条合理搜索路线。除非用户明确限定平台、媒介或资源形态，评测不得把“必须搜某个平台”“首轮必须调用某个 Tool”写成唯一正确答案。

## 1. 三层评测

### Layer A — Hard invariant

这层只验证有明确对错的行为边界，不评价资源质量高低。

典型 invariant：

- 用户说“先不要下载”时不执行下载；
- 用户已经明确要求下载且对象清楚时，不制造形式化二次确认；
- 用户说“第 2 个”只能映射到实际展示且能合理指代的第 2 个；
- 完整枚举不能因为聊天只展示 20/50 条就截断底层数据；
- 普通浏览不能自动升级为“全部采集”；
- 技术失败不等于资源不存在；
- 已知 URL / 已选资源不应无理由重启整套研究；
- 没有真实文件时不能宣称下载成功；
- 临时 `resource_id` 失效时优先重定位同一资源，而不是让对象漂移。

Hard invariant 任一严重回归都可以直接否决新版，不需要用其他语义得分抵消。

### Layer B — Judgment benchmark

这层评价模型的语义判断质量，但允许多种合理路线。

重点看：

1. **Task recognition**：是否分清 Research / Locate / Browse / Enumerate / Acquire / Transform；
2. **Need reconstruction**：是否还原最终任务，而不是直接把原话变成 query；
3. **Clarification judgment**：只有不同答案会显著改变路线时才问；
4. **Coverage design**：是否识别完成目标需要的不同学习价值/证据角色；
5. **Dispatch quality**：每条搜索路线是否有清楚职责，而不是按平台列表发 query；
6. **Query quality**：query 是否像人在对应来源里真实搜索；
7. **Evidence judgment**：是否识别关键词命中但实际没用、空壳、landing page、尺度不适配等问题；
8. **Uncertainty handling**：是否知道哪些事实未知且会改变决策；
9. **Gap quality**：Gap 是否具体，并能推出一条实质不同的下一步；
10. **Stop judgment**：主要目标覆盖后，是否能判断下一轮还有没有明确高信息增益。

Judgment benchmark 不应该预先规定：

- 必须用 Bilibili / SmartEdu / Host Web Search；
- 必须搜固定轮数；
- 必须返回固定候选数量；
- 必须凑齐视频 + 图文 + PDF + 音频；
- 必须使用某个内部思考术语。

如果模型用不同来源达成同样甚至更好的目标覆盖，应判为合理。

### Layer C — Real retrieval

这层必须在真实 OpenClaw + 真实 MCP/Host Web 环境中执行，评价用户实际得到的结果。

关注：

- 第一轮是否召回真正有用的候选；
- 最终候选是否覆盖主要目标，而不是只有关键词相关；
- 是否存在明显同质化结果和未处理的主要 Coverage Gap；
- 是否为了“保险”反复搜相同空间；
- 补搜是否真的增加新的有用证据；
- 是否过早停止或明显晚停；
- 用户最终看到的候选是否差异清楚、可选择；
- 涉及获取时，实际资源对象是否稳定、真实文件是否正确；
- Tool 调用次数、无效搜索次数和耗时只作为成本指标，不直接代表质量。

## 2. Baseline first

0074 的当前基线固定为：

```text
commit: 3a20c1e14358631201e99fb54e007ccfcf118d94
Skill: skills/SKILL.md @ 3a20c1e
MCP: education-resources @ 同一 commit
```

在改写 active `SKILL.md` 前，先真实执行 `semantic-baseline-cases.json`。

每个 case 至少保存：

```text
case id
user messages
model / OpenClaw config
Skill commit
MCP commit
clarification asked?
interpreted task / goal
actual search dispatch + queries
actual Tool trace
high-potential candidates
rejected/uncertain candidates（只记录关键原因）
coverage reached
gap before each extra search
stop reason
user-visible final answer
hard invariant result
judgment notes
real retrieval notes
```

不要求把 Agent 私有思考落成结构化运行时对象；这些字段只是离线实验记录。

## 3. Old / New A/B

新版 Skill 的验收必须满足：

```text
same user input
same Main Agent model/config
same MCP version
same Host Web environment
same session availability where practical
Old Skill vs New Skill
```

若平台实时数据变化明显，应记录环境差异，不把来源变化误判为 Prompt 收益。

A/B 重点比较：

- 需求是否理解得更准；
- 是否更少出现“直接挑最顺手平台”的行为；
- 搜索路线是否更互补；
- 是否减少近义 query 和无价值平台扩散；
- 是否更准确识别结果质量和不确定性；
- Gap 是否更具体；
- 停止是否更稳定；
- 最终资源是否更匹配用户实际目标；
- 是否引入新的 hard invariant 回归。

## 4. Judgment 记录方式

不建议把十几个维度加权成一个精确总分。

每个主要 judgment 维度使用 0/1/2 即可：

- `0`：核心方向错误、明显漏主要目标、机械或产生错误行动；
- `1`：基本相关，但路线单薄、判断不稳、Gap/stop 不清楚；
- `2`：目标还原合理，路线职责清楚，能利用真实结果调整，并在目标覆盖充分后停止。

最终更关注：

- 新版是否在多数 case 上稳定改善；
- 是否出现新的系统性失败模式；
- Hard invariant 是否保持全过；
- Real retrieval 的最终结果是否真实更好。

## 5. 合法 Gap 的最低要求

一个 Gap 只有在能回答下面问题时才有意义：

1. 当前具体缺什么价值、证据或关键事实？
2. 为什么这个缺口对用户目标重要？
3. 下一条路线与已经搜索过的空间有什么实质差别？
4. 下一轮如果成功，会改变什么推荐或停止判断？

下面这些不能单独构成 Gap：

```text
可能还有更好的
还有平台没搜
再多找几个保险
现在只有 5 个结果
```

如果说不出下一轮能新增什么，默认应该停止而不是继续扩散。

## 6. Candidate 判断

评测不要求模型输出复杂 rubric 或分数表。

运行行为可以观察为三类：

- `Reject`：明显不解决目标；
- `Hold`：可能有用，但存在会改变决策的未知事实；
- `Recommendable`：已有足够事实说明值得给用户看。

重要的是行为后果：

- Reject 不应持续占据主要候选；
- Hold 只在未知事实确实重要时进一步 Inspect；
- Recommendable 应能说明它具体覆盖用户目标的哪部分。

## 7. 重点失败模式

### Task 层

- 用户已经给 URL 还重新做主题搜索；
- 用户只想浏览几个代表作品却自动全量 Expand；
- 用户明确要求全部却只返回推荐列表；
- 用户已经选中资源并要求下载，却再次进入候选研究。

### Retrieval 层

- 用户原话直接变 query；
- 需求开放就直接挑最熟平台，没有价值分解；
- 为平台覆盖率搜索所有来源；
- 为形式多样强行凑视频/图文/音频/PDF；
- 多条 query 只是近义改写；
- 候选数量多就判断“够了”；
- 有明显目标缺口却因为已有几个结果过早停止；
- 没有具体 Gap 仍继续搜索。

### Evidence 层

- 只看标题、平台名、播放量；
- 把目录/聚合页当成资源本体；
- 把平台技术失败翻译成内容不存在；
- 没有证据却补齐年龄适配、版权、公开性或文件格式。

### Action 层

- 隐藏候选编号被解释成用户选择；
- “先别下载”仍下载；
- 明确下载仍要求形式确认；
- 完整枚举被页面大小截断；
- 临时句柄丢失后重跑整套研究导致对象漂移。

## 8. 关于来源与 Host Web Search

Host Web Search 是重要的跨生态发现能力，但它不是评测里固定的流程门槛。

如果开放式任务只有某一专门生态无法覆盖的重要价值，而 Web Search 明显能补上，跳过它可能说明 Coverage 判断有问题；但如果其他来源已经高质量覆盖目标，或用户明确限定平台/媒介，不应因为没调用 Host Web Search 就自动扣分。

同理，任何专门平台都只能因为它对当前任务有独特价值才进入路线，而不是因为 Skill 文档列出了它。

## 9. 静态 case 与真实 OpenClaw 的关系

静态 case 只能验证规则边界和 evaluator 设计，不能证明真实对话质量。

0074 的关键里程碑必须使用真实 OpenClaw 执行 baseline 和新版 A/B。后端 pytest、MCP stdio probe、schema 检查都只能证明数据面或工具面，不能替代语义验收。

最终要回答的不是：

> 新版是不是更会遵守我们写的规则？

而是：

> 在相同工具能力下，新版是否更稳定地找到真正适合用户的资源，并在该停的时候停？
