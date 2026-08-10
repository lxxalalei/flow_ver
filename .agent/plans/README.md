# 计划管理规范

影响多个文件、包含多个阶段或可能跨会话的任务，应在本目录创建一个计划文件。
范围局部但非平凡的任务优先使用 [`../TASK_TEMPLATE.md`](../TASK_TEMPLATE.md)；不要为了形式给每个小改动都新建长期计划。

## 顶层计划与归档

- 顶层 `.agent/plans/` **只放当前仍需跟踪的计划**：`in_progress`、`blocked` 或 `pending`。
  `completed` 或已经被替代的计划应移入 [`archive/README.md`](archive/README.md) 所管理的归档目录。
- `archive/` **不是默认必读目录**。正常接手任务时先读取顶层当前计划；只有需要追溯历史
  决策、验证证据、迁移边界、接替关系或回滚信息时，才读取归档索引和相关历史文件。
- 每份计划的唯一标识是**完整文件名**（包括数字前缀和主题 slug），不能只使用数字前缀。
  数字前缀可以表达顺序，但重复前缀的不同主题仍是不同计划；引用时应使用完整文件名或
  明确的完整计划标题。
- 计划移动或重命名后，必须同步正文中的计划引用和 `.agent/plans/` 内的 Markdown 链接。
  不得留下指向旧文件名的链接，也不得用短数字引用掩盖重复编号。

建议命名：

```text
NNNN-short-topic.md
```

## 计划必须先冻结什么

长任务不是 todo 列表。开始实现前至少明确：

1. **Objective**：一个最终用户/业务结果，不能写“完成这个项目”之类不可验收目标。
2. **Non-goals**：相邻但明确不做的事项。
3. **Business invariants**：实施过程中不得被破坏的事实。
4. **Current architecture**：相关组件、source of truth、上游、下游和主要约束。
5. **Expected change surface**：预计会改与明确不应改的模块。
6. **Acceptance criteria**：可观察、可验证的完成条件。
7. **Validation scope**：先定义最小充分验证；全量回归默认不是小阶段的验收方式。
8. **Complexity exceptions**：若要新增 abstraction/source of truth/fallback/compatibility/generalized framework，先完成复杂度举证。

不得在实现过程中静默改写 Objective、Non-goals 或 Acceptance Criteria 来匹配已经写出的代码。
如果上游产品目标确实发生变化，先更新对应产品/路线依据，再修改当前计划。

## 推荐模板

````markdown
# 计划标题

- 状态：in_progress
- 创建日期：YYYY-MM-DD
- 完成日期：未完成
- 范围：涉及的目录或能力

## Objective

- 一个可验证的最终用户/业务结果。

## Non-goals

- 明确不做的相邻工作。

## Business invariants

- 本任务完成后仍必须成立的事实。

## Current architecture

- Relevant components:
- Sources of truth:
- Upstream / downstream:
- Known constraints / unknowns:

## Expected change surface

- Likely to change:
- Should not change:

## Acceptance criteria

- AC-01:
- AC-02:

## Complexity exceptions

默认：无。

如确实新增复杂度，先填写：

```text
Problem:
Why current structure cannot solve it:
Simplest alternative considered:
Why that alternative is insufficient:
New source of truth introduced:
New invariant introduced:
Failure modes introduced:
```

## 步骤

- [x] completed：已经完成的步骤
- [ ] in_progress：当前唯一正在执行的步骤
- [ ] pending：尚未开始的步骤
- [ ] blocked：无法继续，后面写明原因和所需条件

## Milestone checkpoint

每个 milestone 完成后核对：

```text
Original goal still unchanged?:
Non-goals still respected?:
Business invariants still true?:
New abstraction introduced?:
New source of truth introduced?:
Fallback added?:
Data truncation added?:
Unrelated files changed?:
Actual user flow affected?:
Actual user flow validated?:
Scope drift detected?:
```

发现 drift 时先纠正，再进入下一 milestone。

## Decision log

只记录会改变架构、业务不变量、source of truth、公共契约或后续实施路径的决定；不要把普通实现细节写成 ADR。

### Decision 001

- Context:
- Options considered:
- Chosen option:
- Why:
- Complexity introduced:

## 验证

记录实际计划执行的验证，以及它能证明和不能证明什么。

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted unit | | | |
| integration | | | |
| backend E2E | | | real Agent/user flow |
| real Agent/user flow | | | |
| full regression | | | |

## 结果

- 完成后填写改动摘要、验证结果、未验证项和剩余风险。
````

## 状态要求

- 文件顶部状态使用 `pending`、`in_progress`、`completed` 或 `blocked`。
- 同一计划最多一个步骤为 `in_progress`。
- 每完成一个 milestone 就执行一次 checkpoint；不要只在最终总结时检查 scope drift。
- 任务结束时，本次已经实施的步骤不得仍标为 `pending` 或 `in_progress`。
- 全部承诺完成后，将顶部状态改为 `completed` 并填写完成日期。
- 因外部条件无法完成时，顶部状态改为 `blocked`，记录连续失败证据和恢复条件。
- 被替代的计划可以保留合法的原始状态，并在正文增加明确的 `处置：superseded` 和接替说明；
  这不等于把它标记为 `completed`。
- 产品开发路线图不等于当前执行计划；未来路线保持“未开始”是正常状态。

## 验证预算

计划中的测试范围按 `AGENTS.md` 的四级验证执行：Small Edit → Subsystem → Milestone → Release/Cross-cutting。
昂贵测试必须能够回答“这个 diff 的什么现实回归风险只能或最适合由它发现”；否则优先 narrower targeted validation。
