# Task Spec

用于非平凡但范围局部的任务。目的不是增加流程，而是在改代码前冻结目标、边界和验证范围。
跨会话、跨模块或多 milestone 任务仍使用 `.agent/plans/`。

**必填 3 段：Goal、Non-goals、Acceptance Criteria。其余段落按需保留，不需要的整段删除。**

## Goal（必填）

只写一个可验证结果。

```text
用户/系统能够：
```

## Non-goals（必填）

明确列出相邻但本任务不处理的事项。

- 
- 

## Acceptance Criteria（必填）

### AC-01

```text
Given:
When:
Then:
```

### AC-02

```text
Given:
When:
Then:
```

## 可选段落（按需）

以下段落按需保留；不需要时整段删除。

### User / Business Behavior

```text
Given:
When:
Then:
```

任务不直接改变用户行为时，写清楚它保护的业务/架构结果。

### Business Invariants

本次修改后必须继续成立：

- 

### Current System Understanding

Relevant components / sources of truth / upstream / downstream：

- 

Major unknowns to investigate before implementation:

- 

### Expected Change Surface

Likely to change:

- 

Should not change:

- 

### Validation Plan

Smallest useful validation:

- 

Full regression required?

- No by default.
- If yes,具体风险依据：

## Complexity Exception

仅当确认需要新增 abstraction、writable state、source of truth、fallback、compatibility layer 或 generalized framework 时填写；默认不填。

```text
Problem:
Why current structure cannot solve it:
Simplest alternative considered:
Why that alternative is insufficient:
New source of truth introduced:
New invariant introduced:
Failure modes introduced:
```

## Dependency Research

仅当新增或实质修改第三方集成时填写。

```text
Dependency + exact version:
Required capability:
Official API / types inspected:
What the dependency already solves:
What must still be implemented locally:
Known limitations / migration constraints:
Current project integration points:
Why this approach is preferred:
```

不要凭记忆发明 API，不重复实现依赖已有能力，不为尚不存在的第二个用例提前泛化。

## Completion Record

只勾选实际执行的验证等级（语义见 `AGENTS.md`「验证要求」）：

```text
[ ] Level 1 — 小改动：直接受影响单元测试、语法/静态检查
[ ] Level 2 — 子系统改动：受影响模块测试和直接相关 integration
[ ] Level 3 — milestone/用户链路改动：受影响回归、相关 E2E、适用时真实流程
[ ] Level 4 — release/跨切面改动：有具体风险依据时运行全量回归
[ ] 未执行真实 Agent/用户流程验证（未执行时勾选）

Not validated:

Known remaining risks:
```