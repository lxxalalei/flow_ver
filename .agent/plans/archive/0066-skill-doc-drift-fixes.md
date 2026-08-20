# Task Spec 0066：修正 Skill 文档漂移与 Tool 列表脚本

- 状态：completed
- 创建日期：2026-08-20
- 完成日期：2026-08-20
- 范围：`learning-resource-flow` 获取/检查说明与 `list_tools.py`

## Goal（必填）

用户/系统能够：依据 active Skill 正确处理异步 Job、`AUTH_REQUIRED`、仅发现候选和 Generic Web Reader v2，并能用现有辅助脚本列出当前 Tool。

## Non-goals（必填）

- 不新增平台 Registry、工作流状态、持久对象、fallback 或抽象层。
- 不修改 MCP Tool 契约、运行时行为、平台适配器或其他 Skill reference。
- 不扩展本次审查意见之外的语义规则或回归案例。

## Acceptance Criteria（必填）

### AC-01

```text
Given: Download 或 Batch 返回异步 job_id
When: Agent 依据获取说明继续任务
Then: 在 Job 到达终态前不宣称完成、归档或把 Batch 当成完整结果
```

### AC-02

```text
Given: 真实资源操作返回 AUTH_REQUIRED
When: Agent 依据获取说明恢复
Then: 只在该错误后进入 Session 流程，由用户登录，opaque capture 保存后重试原操作
```

### AC-03

```text
Given: 候选来自仅发现平台或 Generic Web Reader v2
When: Agent 依据检查/获取说明行动
Then: Inspect 受运行时能力约束，且 index.html、webbundle.zip 和 partial 图片语义被准确说明
```

### AC-04

```text
Given: 当前 server.py 只暴露 create_server()
When: 运行 list_tools.py
Then: 脚本成功列出当前注册的 14 个 Tool
```

## Expected Change Surface

- Likely to change: `references/acquisition.md`、`references/inspection.md`、`list_tools.py`。
- Should not change: MCP 生产代码、Tool schema、其他平台与 Skill 语义。

## Validation Plan

- 直接运行 `list_tools.py` 并做 Python 语法检查。
- 运行 Tool 注册、能力层级、Session、Job 与 Reader 相关定向测试。
- 检查 Markdown 引用文件、`git diff --check` 和最终 diff 范围。
- 不运行全量回归；生产代码和公共契约未修改。

## 步骤

- [x] completed：冻结 Goal、Non-goals、Acceptance Criteria 和最小修改面。
- [x] completed：落实五条审查意见。
- [x] completed：运行定向验证并复核 diff。

## Milestone checkpoint

```text
Original goal still unchanged?: 是
Non-goals still respected?: 是
Business invariants still true?: 是
New abstraction introduced?: 否
New source of truth introduced?: 否
Fallback added?: 否
Data truncation added?: 否
Unrelated files changed?: 否
Actual user flow affected?: Skill 对异步任务、认证、Inspect 与网页交付的判断
Actual user flow validated?: 未执行真实 OpenClaw Agent
Scope drift detected?: 否
```

## Completion Record

```text
[x] Level 1 — 小改动：直接受影响单元测试、语法/静态检查
[ ] Level 2 — 子系统改动：受影响模块测试和直接相关 integration
[ ] Level 3 — milestone/用户链路改动：受影响回归、相关 E2E、适用时真实流程
[ ] Level 4 — release/跨切面改动：有具体风险依据时运行全量回归
[x] 未执行真实 Agent/用户流程验证（未执行时勾选）

Not validated: 真实 OpenClaw Agent/用户流程；全量回归。

Known remaining risks: 文本能否稳定改变模型行为仍需真实 Agent 场景验证。
```

## 验证结果

- `list_tools.py` 在项目配置的源码运行环境中成功列出 14 个 Tool。
- `py_compile` 通过。
- Tool 注册、能力层级、Session、Job、Batch 与 Reader 相关 32 项定向测试通过。
- Markdown 引用文件检查、`git diff --check` 与修改范围检查通过。

## 结果

- 只修改两份现有 Skill reference 和失效的 Tool 列表辅助脚本。
- 没有修改 MCP 生产代码、Tool schema、平台适配器或其他 Skill 语义。
- 没有新增 Registry、状态机、fallback、依赖或抽象层。
