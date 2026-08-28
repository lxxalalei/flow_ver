# 0075 — MCP 能力激发与 Tool 契约收敛

> 处置：2026-08-28 工程范围完成并归档；AC-07 真实 OpenClaw User Journey 继续保持 deferred，不作为后续 CCTV 依赖减重的并行 active 路线。

- 状态：in_progress
- 创建日期：2026-08-28
- 完成日期：未完成
- 范围：MCP Tool description/input schema、能力审计文档、Skill 语义用例；MCP 业务行为冻结

## Objective

在不新增 Tool、不修改平台行为和持久状态的前提下，让模型能够从自然语言稳定识别并正确组合 education-resources MCP 已有 12 个 Tool；先证明现有能力是否可被正确激发，再决定是否存在真实能力缺口。

## Non-goals

- 不新增或删除 MCP Tool，不改变 Tool 参数结构；
- 不修改 Adapter、Downloader、Job、SessionStore 或 Archive 行为；
- 不扩平台，不启用默认 Multi-agent，不重写 CCTV WASM；
- 不为 education-resources 单独建设 Windows 卸载脚本、卸载说明或卸载 CI；产品最终随定制 OpenClaw 交付，安装、升级、卸载生命周期由总安装包统一负责；
- 不新增 capability registry、canonical/projection、状态机、fallback 或重复 source of truth；
- 按用户要求，本阶段先不执行真实 OpenClaw、A/B 或完整测试验收。

## Business invariants

- Skill/Main Agent 继续负责意图、路线、候选、Gap、停止和用户选择；
- MCP 只表达并执行真实能力，不把语义流程下沉成固定 Tool 流水线；
- Search/Expand 不产生下载授权；Download/HTML Design/Archive/Session Manage 只在对应意图成立时触发；
- Open Web 发现默认使用宿主 Web Search，MCP Search 负责明确选择的专门平台；
- Tool description 是运行时能力入口，Inventory 只是审计证据，不成为第二份运行时契约。

## Current architecture

- MCP 通过 stdio 暴露 12 个 Tool；实际 `tools/list` 顶层 description 当前全部为空；
- 参数字段已有局部说明，但模型缺少每个 Tool 的总体用途、触发条件和关键非触发条件；
- `TOOLS.md`、MCP README 与 Skill 已描述能力边界，但运行时 Tool 契约没有完整承载这些最小语义；
- 现有 `run_semantic_baseline.py` 可以直接承载新的自然语言 judgment suite，不需要新测试框架。

## Expected change surface

- `mcp/education-resources/src/education_resource_mcp/server.py`：只补 Tool docstring 和必要字段说明；
- `docs/MCP_CAPABILITY_INVENTORY.md`：记录审计结论与代码证据；
- `skills/examples/mcp-capability-elicitation-cases.json`：自然语言 Tool 选择用例；
- 相关契约测试只补断言，不执行完整验收。

## Acceptance criteria

- [x] AC-01：12 个 Tool 的运行时 description 均非空，并说明用途、触发条件和关键边界；
- [x] AC-02：Tool 数量、名称和参数结构不变；
- [x] AC-03：Capability Inventory 覆盖 12 Tool 的用户意图、输入来源、输出/Job、认证、副作用和失败边界；
- [x] AC-04：自然语言 Elicitation suite 覆盖 12 Tool、组合调用、非触发和副作用授权；
- [x] AC-05：没有新增 runtime registry、状态模型或平台实现规则；
- [x] AC-06：静态/schema 检查通过；真实 OpenClaw 与语义 A/B 按用户要求暂缓，未执行时明确记录；
- [ ] AC-07：最终真实多轮 OpenClaw User Journey 通过，并补做 0074 AC-11（deferred）。

## Complexity exceptions

无。Tool docstring 是现有 MCP runtime contract 的缺失部分；Inventory 和 JSON suite 是审计/测试证据，不参与运行时决策。

## Steps

- [x] completed：核对 live HEAD、12 Tool、Skill 路由和现有评测结构。
- [x] completed：建立 Capability Inventory 并审查 Tool description/schema。
- [x] completed：最小修正 12 Tool runtime description，不改变参数和业务行为。
- [x] completed：增加自然语言 Capability Elicitation suite 和契约断言。
- [x] completed：更新文档与计划，执行静态检查；真实验收保持 deferred。

## Current checkpoint

```text
Engineering scope complete?: yes
Tool count/name/input fields changed?: no
Runtime registry/state model introduced?: no
Adapter/Downloader/Job/Session behavior changed?: no
Static contract/JSON/diff checks run?: yes
Focused stdio schema probe run?: yes
OpenClaw Elicitation/User Journey run?: deferred by user
Remaining active acceptance?: AC-07 only
```

## Product packaging decision

2026-08-28 用户确认：education-resources 后续随定制 OpenClaw 一体交付。当前独立 `install.cmd/install.ps1` 只保留为开发、调试和恢复入口；不继续扩展独立卸载链。正式产品只要求总安装包预装并注册 MCP/Skill、依赖体检通过、升级保留用户数据；卸载与数据保留策略由定制 OpenClaw 统一处理。
