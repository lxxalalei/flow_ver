# Semantic Evaluation Guide

这份评测用于判断 `learning-resource-flow` 是否真的提升了模型找资源的能力，而不是只判断它有没有按 MCP 工作流走完。

## 评测目标

同一个用户输入、同一个 Main Agent 模型、同一个 `education-resources` MCP 条件下，优先比较六项决策质量：

1. **Need reconstruction**：是否理解用户最终想解决的问题，而不是把原话直接变成关键词；
2. **Clarification judgment**：该问时是否问关键分叉，不该问时是否直接探索；
3. **Search angles**：是否形成少量真正互补的角度，而不是同义 query；
4. **Source routing**：平台/来源是否因为当前内容或证据需求被选择，而不是为了覆盖平台；
5. **Query quality**：query 是否像对应来源里的真实搜索表达；
6. **Result judgment**：是否能发现“关键词命中但实际没用”，并形成更好的下一步。

MCP workflow safety 是 gate，不是主要语义得分：不得伪造业务状态、不得选择未展示候选、不得未经当前计划确认下载、不得绕过 resource MCP 建第二条数据面。通过这些 gate 只能证明没有破坏业务边界，不能证明搜索质量高。

## A/B 方法

建议保留一个旧 Skill Git ref 作为 baseline，与当前分支做同输入 A/B：

```text
A：旧 Flow-heavy Skill
B：semantic-first Skill
```

每个 case 都记录：

- 模型是否追问以及问题是什么；
- 内部/可观察的搜索角度；
- 实际派发的平台与 query；
- 第一轮 ResultSet 中高潜候选质量；
- 是否识别结果方向错误；
- 是否进行了有意义补搜；
- 用户最终看到的候选是否更匹配目标；
- Tool 调用数量和无效搜索次数，仅作为成本指标。

不要用“B 调用更少 Tool”直接判 B 更好，也不要用“完整走完 Flow”判语义通过。

## 建议判定

单 case 优先使用 0/1/2 三档：

- `0`：核心方向错误，或者把工作流合规当成任务完成；
- `1`：基本相关，但需求理解/派发/query/结果判断仍明显机械；
- `2`：目标还原合理，搜索角度与来源有清楚职责，query 自然，并能根据真实结果调整。

六个语义维度分别评分，不汇总成伪精确的加权总分。真正关心的是新版是否在多数真实场景稳定优于旧版，以及是否出现新的系统性退化。

## 失败模式重点观察

- 直接把用户原话复制成 query；
- 为了平台覆盖率搜一圈已注册来源；
- 每个平台生成多条近义 query；
- 结果数量很多就直接 Present；
- 搜索失败就反过来问用户已明确的信息；
- 把模型为召回提出的载体/来源写成用户长期偏好；
- 为普通窄搜索自动启用 sub-agent；
- 把 Search/Inspect/Plan/ResultSet 等内部术语暴露给用户；
- 只看标题或平台名，忽略对象适配、资源本体、公开访问等真实要求。

## 真实 OpenClaw 验证

静态 case 只能证明 Skill 文本覆盖了这些决策边界，不能证明 OpenClaw 实际运行质量。里程碑验收至少应抽取若干 case 在真实 OpenClaw 对话中执行，并保存实际搜索任务、query、结果和用户可见回复进行 A/B。

后端单测、Service 直调或 MCP probe 不能替代这一步。
