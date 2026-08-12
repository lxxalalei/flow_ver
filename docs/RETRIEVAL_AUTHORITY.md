# Retrieval Authority：事实、语义审查与停止决策

- **状态**：Accepted
- **日期**：2026-08-12

## 权威边界

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> Resolution / Representation facts
MCP Plan / Job / Asset / Archive -> service facts
                               |
                               v
Skill reads MCP facts -> private SemanticReview
                               |
                               v
Skill decides: Present / Replan / Clarify / StopWithGap
```

## 原则

1. **MCP 只保存事实**：ResultSet、Resolution、Selection、Plan、Job、Outcome、Asset。
2. **语义判断在 Skill 私有完成**：SemanticReview、Gap、StopDecision 不持久化、不暴露给 MCP。
3. **候选数量或标题命中不自动触发 Present**：Skill 基于任务目标和证据质量判断。
4. **Selective Inspect**：只对会改变决策的高潜候选做 Inspect。
5. **停止决策不可委托给 MCP**：Skill 拥有 Present / Replan / Clarify / Stop 的最终决策权。
