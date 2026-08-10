# Task Spec

用于非平凡但范围局部的任务。目的不是增加流程，而是在改代码前冻结目标、边界和验证范围。
跨会话、跨模块或多 milestone 任务仍使用 `.agent/plans/`。

## Goal

只写一个可验证结果。

```text
用户/系统能够：
```

## Non-goals

明确列出相邻但本任务不处理的事项。

- 
- 

## User / Business Behavior

```text
Given:
When:
Then:
```

如果任务不直接改变用户行为，写清楚它保护的业务/架构结果。

## Business Invariants

本次修改后必须继续成立：

- 
- 

## Current System Understanding

Relevant components:

- 

Authoritative source(s) of truth:

- 

Upstream:

- 

Downstream:

- 

Major unknowns to investigate before implementation:

- 

## Expected Change Surface

Likely to change:

- 

Should not change:

- 

## Acceptance Criteria

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

## Validation Plan

Smallest useful validation:

- 

Relevant integration / user-flow validation:

- 

Full regression required?

- No by default.
- If yes,具体风险依据：

## Complexity Exception

Does this task require a new abstraction, writable state, source of truth, fallback, compatibility layer or generalized framework?

- No by default.

If yes, complete before implementation:

```text
Problem:
Why current structure cannot solve it:
Simplest alternative considered:
Why that alternative is insufficient:
New source of truth introduced:
New invariant introduced:
Failure modes introduced:
```

举证不足时，不增加复杂度。

## Dependency Research

是否新增或实质修改第三方集成？

- No by default.

If yes,先记录：

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

```text
[ ] implemented
[ ] statically checked
[ ] targeted unit tested
[ ] subsystem/integration tested
[ ] backend E2E tested
[ ] real Agent/user-flow tested
[ ] visual behavior inspected
[ ] full regression tested

Not validated:

Known remaining risks:
```
