# 0077 — 真实多轮 User Journey 与 Agent Release Gate

- 状态：in_progress
- 创建日期：2026-08-29
- 完成日期：未完成
- 范围：`skills/examples/`、真实 OpenClaw/MCP 验收证据、必要的最小 Skill/Tool contract 修正；MCP 业务能力面默认冻结

## Objective

在配置完成的真实 OpenClaw 环境中，用连续多轮自然语言任务验证 Main Agent 是否能稳定激发现有 MCP 能力、保持用户选择/URL/Job 语义并完成真实资源闭环；只有真实 Journey 暴露退化时才做最小修正。

## Non-goals

- 不新增平台或第 13 个 MCP Tool；
- 不引入 Multi-agent；
- 不继续重构 CCTV runtime、WASM 或安装体系；
- 不新增 Flow / Plan / Selection / CoverageState / capability registry / digest / canonical/projection；
- 不把 synthetic assistant context 或单轮 judgment case 伪装成真实多轮验收；
- 不为了让测试通过而加入静默 fallback、固定平台路由、固定搜索轮数或任意截断。

## Business invariants

- Main Agent / Skill 继续拥有 Goal、Coverage、Sources、Evidence、Gap、Next/Stop 和用户选择语义；
- MCP 只表达并执行真实 Search / Expand / Import / Inspect / Download / Job / HTML Design / Archive / Session 能力；
- 用户可见候选有真实可访问 URL 时必须展示真实 URL；
- Search/Expand 不授权 Download；Session 不是 preflight；
- `resource_id` 是进程内句柄，稳定资源身份仍是 URL / 平台稳定 ID；
- Browse 与 Enumerate 保持不同完整性语义；
- 平台技术失败不自动等于资源不存在。

## Current architecture

已完成：

- 0074：Skill decision kernel 工程收敛；
- 0075：12 Tool runtime description、Capability Inventory、单轮 capability elicitation cases；
- 0076：CCTV static compatibility runtime 与 clean Windows packaged install release gate；
- `skills/examples/run_semantic_baseline.py`：单轮/synthetic-context 语义回归；
- `skills/examples/run_real_user_journeys.py`：真实同 session 多轮原始证据 runner；
- `skills/examples/real-user-journeys.json`：6 条真实 User Journey；
- `docs/REAL_PLATFORM_SMOKE_MATRIX.md`：6 条 Tier 1 真实平台 release smoke。

当前缺口：

> 工程能力已经存在，但尚缺配置完成的真实 OpenClaw model/provider 环境来执行最终多轮 Journey，并据实际 tool calls / URLs / Jobs / files 判断是否存在 Agent orchestration 退化。

## Expected change surface

允许：

- `skills/examples/run_real_user_journeys.py`：只修真实 harness 缺陷；
- `skills/examples/real-user-journeys.json`：只修真实 Journey 表达/fixture 缺陷；
- `skills/SKILL.md` 或 `server.py` Tool description：仅当真实失败证据明确指向语义/affordance 问题时最小修改；
- 本计划与语义评测记录。

默认不改：

- Adapter / Downloader / Job / SessionStore 业务实现；
- Tool 数量/名称/参数结构；
- 平台范围；
- Release 架构。

## Acceptance criteria

- [x] AC-01：存在真正复用同一 OpenClaw `session-id` 的多轮 runner，不再用 synthetic assistant 前情代替真实会话；
- [x] AC-02：每次 harness invocation 使用唯一 session identity，重复执行不会污染上下文；
- [x] AC-03：Journey suite 覆盖搜索→选择→下载→归档、Browse→Enumerate、已知网页→保存→HTML Design、容器 Expand→子项选择、AUTH_REQUIRED→Session→恢复、路线分叉澄清；
- [x] AC-04：真实平台 smoke matrix 已定义，小规模 Tier 1 不随平台数量机械膨胀；
- [ ] AC-05：在配置完成的真实 OpenClaw 环境运行核心无 fixture Journey，保存原始逐轮证据；
- [ ] AC-06：提供真实 fixture 后运行 creator/course/generic-web/auth Journey，保存逐轮证据；
- [ ] AC-07：逐 Journey 人工核对实际 tool calls、真实 URL、selection、Job 终态和副作用，不使用 runner 自动裁判；
- [ ] AC-08：若发现退化，只按真实证据做最小 Skill/Tool contract 修正，并重跑对应 Journey；
- [ ] AC-09：最终至少一条完整真实链达到 Search/发现 → 用户选择 → Download → Job 终态 → Archive，且没有 unsupported claim 或未授权副作用；
- [ ] AC-10：0074 AC-11 / 0075 AC-07 的 deferred 真实 User Journey 验收由本计划明确收口。

## Complexity exceptions

无。当前 runner 和 suite 只是测试证据采集，不参与 runtime 决策，也不引入新的 source of truth。

## Steps

- [x] completed：修复 Windows packaged install 非致命 Gateway restart 退出码并完成 0076 release gate；
- [x] completed：新增真实多轮 Journey runner、6 条 Journey 和真实平台 smoke matrix；
- [ ] in_progress：准备真实 fixture / 配置完成的 OpenClaw 环境并执行第一批 Journey；
- [ ] pending：根据真实失败证据决定是否需要最小 Skill/Tool contract 修正；
- [ ] pending：完成全部关键 Journey 复测并收口 0074/0075 deferred acceptance。

## Validation scope

### Harness validation

- Python syntax / JSON parse；
- dry-run fixture substitution；
- 同一次 Journey 内 session id 必须一致；
- 不同 harness invocation session id 必须不同；
- 一个 turn native failure 后停止该 Journey，不伪造后续结果。

### Real Agent validation

- 使用真实 OpenClaw model/provider；
- 使用真实 installed Skill 与 `education-resources` MCP；
- 用户只说自然语言，不在 prompt 里提示 Tool 名；
- 保存原始 `--json` 输出、tool summary、stderr、turn/session metadata；
- 人工按 Journey acceptance/forbidden 逐项判定。

### Platform validation

按 `docs/REAL_PLATFORM_SMOKE_MATRIX.md`，只对本次改动相关路径和 Tier 1 核心能力做真实 smoke，不默认全平台跑满。

## Current checkpoint

```text
Original goal still unchanged?: yes
Non-goals respected?: yes
Runtime capability surface changed?: no
New runtime state/source of truth?: no
Real multi-turn harness exists?: yes
Real OpenClaw journey executed?: not yet
Current blocker?: needs configured real OpenClaw model/provider + live fixtures for fixture-required journeys
```

## Result

进行中。当前工程侧已经把真实多轮验收所需 harness、Journey 与平台 smoke 边界准备好；下一步不再继续写新能力，而是执行真实 Agent/user flow，并让实际失败决定是否还有必要修改 Skill 或 MCP contract。
