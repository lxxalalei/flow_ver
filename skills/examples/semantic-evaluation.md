# Semantic Evaluation Guide v7

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
- Web Search 候选不需要先拥有 MCP `resource_id` 才能被推荐或被用户选择；
- 用户只是要推荐 Web 资料时，不应把全部 Web 命中机械 `resource_import_url`；
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
5. **Dispatch quality**：是否根据 Direct Value Match 选择 OpenClaw `web_search`、MCP `resource_search` 或二者共同召回，而不是按平台列表发 query；
6. **Query quality**：query 是否像人在对应来源里真实搜索；
7. **Evidence judgment**：是否识别关键词命中但实际没用、空壳、landing page、尺度不适配，以及 Web snippet 与页面本体事实的边界；
8. **Uncertainty handling**：是否知道哪些事实未知且会改变决策；
9. **Gap quality**：Gap 是否具体，并能推出一条实质不同的下一步；
10. **Stop judgment**：主要目标覆盖后，是否能判断下一轮还有没有明确高信息增益。

Judgment benchmark 不应该预先规定：

- 必须用 Bilibili / SmartEdu / OpenClaw `web_search`；
- 必须搜固定轮数；
- 必须返回固定候选数量；
- 必须凑齐视频 + 图文 + PDF + 音频；
- 必须使用某个内部思考术语。

如果模型用不同来源达成同样甚至更好的目标覆盖，应判为合理。

### Layer C — Real retrieval

这层必须在真实 OpenClaw + 真实 MCP/Host Web 环境中执行，评价用户实际得到的结果。

关注：

- 第一轮是否召回真正有用的候选；
- `web_search` 与 `resource_search` 是否按任务价值合理分工或共同召回；
- Web 与专门平台命中同一实际资源时是否避免重复推荐；
- 是否为了“流程完整”批量 Import Web 搜索结果；
- 最终候选是否覆盖主要目标，而不是只有关键词相关；
- 是否存在明显同质化结果和未处理的主要 Coverage Gap；
- 是否为了“保险”反复搜相同空间；
- 补搜是否真的增加新的有用证据；
- 是否过早停止或明显晚停；
- 用户最终看到的候选是否差异清楚、可选择；
- 涉及获取时，Web URL → `resource_import_url` → Download 的对象是否稳定；
- Tool 调用次数、无效搜索次数和耗时只作为成本指标，不直接代表质量。

## 2. Immutable old baseline

0074 的旧对照组固定为：

```text
commit: 3a20c1e14358631201e99fb54e007ccfcf118d94
Skill: skills/SKILL.md @ 3a20c1e
```

active Skill 已按用户要求继续修改，因此不再要求“修改 active Skill 前先跑 baseline”。公平性由 immutable old commit + 独立 worktree 保证：后续仍需用同模型、同 MCP、同输入分别运行 old/new。

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
same OpenClaw web_search environment
same session availability where practical
Old Skill vs New Skill
```

若平台实时数据变化明显，应记录环境差异，不把来源变化误判为 Prompt 收益。

A/B 重点比较：

- 需求是否理解得更准；
- 是否更少出现“直接挑最顺手平台”的行为；
- 是否能正确把开放 Web 与专门资源平台作为并列召回来源；
- 是否减少近义 query 和无价值平台扩散；
- 是否避免把所有 Web 命中机械 Import；
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
还能换个 web_search 关键词
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
- Hold 只在未知事实确实重要时进一步读取页面本体或 Inspect；
- Recommendable 应能说明它具体覆盖用户目标的哪部分。

对于 Web Search 候选，snippet 足够支持推荐时可以直接 Recommendable；snippet 不足以确认关键事实时才 Hold。不能把“尚未 Import”本身当成 Hold 理由。

## 7. 重点失败模式

### Task 层

- 用户已经给 URL 还重新做主题搜索；
- 用户只想浏览几个代表作品却自动全量 Expand；
- 用户明确要求全部却只返回推荐列表；
- 用户已经选中资源并要求下载，却再次进入候选研究。

### Retrieval 层

- 用户原话直接变 query；
- 需求开放就直接挑最熟平台，没有价值分解；
- 把 `web_search` 当成所有专门平台失败后的 fallback；
- 为平台覆盖率搜索所有来源；
- 为形式多样强行凑视频/图文/音频/PDF；
- 多条 query 只是近义改写；
- Web Search 每个命中都自动 Import；
- Web 与平台搜索命中同一资源却重复推荐；
- 候选数量多就判断“够了”；
- 有明显目标缺口却因为已有几个结果过早停止；
- 没有具体 Gap 仍继续搜索。

### Evidence 层

- 只看标题、平台名、播放量；
- 把 Web snippet 当成全文事实；
- 把目录/聚合页当成资源本体；
- 把平台技术失败翻译成内容不存在；
- 没有证据却补齐年龄适配、版权、公开性或文件格式。

### Action 层

- 隐藏候选编号被解释成用户选择；
- Web 候选没有 `resource_id` 就拒绝用户选择；
- 用户选中一个 Web URL 后却批量 Import 同页其他候选；
- “先别下载”仍下载；
- 明确下载仍要求形式确认；
- 完整枚举被页面大小截断；
- 临时句柄丢失后重跑整套研究导致对象漂移。

## 8. 关于 OpenClaw `web_search` 与来源派发

OpenClaw `web_search` 是重要的跨生态发现能力，但它不是评测里固定的流程门槛。

如果开放式任务缺少专业/官方/图文/长尾发现，而 `web_search` 明显能补上，跳过它可能说明 Coverage 判断有问题；但如果用户明确限定平台/媒介，或窄任务已经被专门生态高质量覆盖，不应因为没调用 `web_search` 就自动扣分。

同理，任何专门平台只要对当前 Coverage 有**直接、具体的价值匹配**就可以参与，不要求它拥有其他来源完全没有的“独占价值”。评测应惩罚的是无理由 fan-out，而不是多个合理来源竞争同一价值。

Web Search 命中也不是 MCP Resource。只有用户选择、关键页面事实检查或获取/转换等需要 MCP 能力时，具体 URL 才进入 `resource_import_url`。

## 9. Web Search integration cases

`web-search-integration-cases.json` 专门覆盖：

- 开放式任务中 `web_search` 与 `resource_search` 共同召回；
- 纯开放网页发现不强行调用专门平台；
- Web 候选无需先 Import 即可推荐；
- 用户选中 Web 候选后 URL → `resource_import_url` → Download / Archive；
- Web 与平台搜索命中同一资源时语义去重；
- 已知 URL 获取任务跳过 Web Search；
- snippet 不足时只检查高潜候选。

这些 case 主要验证边界和 judgment，不规定固定候选数量或固定调用次数。

## 10. 静态 case 与真实 OpenClaw 的关系

静态 case 只能验证规则边界和 evaluator 设计，不能证明真实对话质量。

0074 的关键里程碑必须使用真实 OpenClaw 执行旧版与新版 A/B。后端 pytest、MCP stdio probe、schema 检查都只能证明数据面或工具面，不能替代语义验收。

最终要回答的不是：

> 新版是不是更会遵守我们写的规则？

而是：

> 在相同工具能力下，新版是否更稳定地找到真正适合用户的资源，并在该停的时候停？