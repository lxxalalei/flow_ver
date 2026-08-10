# Retrieval Authority ADR：事实、语义审查与停止决策

- **状态**：Accepted
- **决策日期**：2026-08-08
- **适用范围**：`skills/learning-resource-flow/` 与 `mcp/education-resources/`

本 ADR 固定检索闭环中的权威边界。它不是运行时契约；若要改变公共字段语义、权威归属或
停止决策执行位置，必须同步更新机器 Schema、持久化、代码、测试和文档，并留下新的决策记录。

## 决策

```text
MCP Search -> immutable ResultSet + factual coverage
MCP Inspect -> independent Resolution / Representation facts
MCP readiness / eligibility / Job / Asset / Archive -> their own service facts
                               |
                               v
Skill reads MCP facts + task context -> private SemanticReview
                               |
                               v
Skill-private Gap + StopDecision
                               |
                 Present | Replan | Clarify | StopWithGap
```

### 1. MCP 是服务端事实的唯一权威

MCP/SQLite 负责创建、校验、持久化和恢复 Flow、ResultSet、Presentation、Selection、Plan、Job、
Resolution、Readiness、Eligibility、Outcome、Asset、Bundle 和 Archive，以及来源、provenance、
去重、失败和可观察到的获取状态摘要。

`resource_search.coverage` 只表示 Search ResultSet 中由服务端观察到的 factual summary。它可以
包含候选、来源、去重、失败和其他可恢复事实，但不表示：

- 用户任务已经被语义满足；
- 候选值得推荐或可以直接展示；
- `Gap`、`StopDecision`、目标适配或用途适配已经成立；
- 某个候选一定存在可获取的 primary Representation；
- Job、Asset、Archive 或 Provider 已经成功。

Inspect/Resolution、Capability Descriptor、Deployment Readiness、Eligibility、Job、Outcome、
Asset 和 Archive 是独立事实，不回写旧 ResultSet 的 factual coverage，也不互相隐式推导。

### 2. Skill 是语义判断的唯一生产执行位置

唯一入口 Skill 根据用户任务和 MCP facts 私有地产生 `SemanticReview`，判断候选的：

- 与用户主题和资源目标的相关性；
- 资源形态、用途、目标对象和显式约束的适配度；
- 内容本体、版本、来源可信度和必要可用性证据；
- 仍需 Inspect、澄清、换词、换来源或停止的关键 Gap。

`user_role`、`resource_target`、目标和 `constraints` 是独立输入；未知保持 unknown，不能由身份、
标题、数量、搜索方向、平台名或“已注册”状态补齐。

只有 Skill 可以在生产对话中执行 `Present`、`Replan`、`Clarify` 或 `StopWithGap`。MCP 不根据
候选数量、标题命中或 coverage 自动升级为 `Present`，也不把 Skill 的语义结论写入公共状态。

### 3. Adaptive evaluator 只用于离线校准

`mcp/education-resources/src/education_resource_mcp/retrieval/adaptive.py` 是离线 oracle /
calibration helper。它可以消费显式 fixture 和私有审查，比较 gold 期望与预测结果，但不得：

- 搜索、Inspect、下载、归档或调用真实 Provider；
- 依赖 `ResourceService` 的生产 factual-state；
- 写入 MCP 公共状态、ResultSet、Flow、Job 或 Asset；
- 成为第二套 coverage、Gap 或 StopDecision 生产权威；
- 被暴露为新的 MCP Tool。

## 恢复、失败与副作用

- 恢复时优先重新读取 MCP facts；缺少 Skill 语义审查按 unknown 处理，不从聊天记忆或旧模型结论
  自动恢复为 Present。
- factual facts 缺失、过期或互相冲突时，保持结构化 unknown/error，触发 Inspect、重算、澄清、
  重规划或带 Gap 停止；不得用默认 available、候选数量或 generic fallback 掩盖证据不足。
- 搜索失败、AUTH_REQUIRED、POLICY、FEATURE_NOT_SUPPORTED、超时、取消和内容校验失败必须保留
  真实结构化原因，不能被语义判断改写成成功。
- 下载、归档等副作用仍由 MCP 强制执行 ownership、来源、状态、权限和幂等校验。下载使用
  `prepare -> 用户明确确认 -> start`；归档只接受服务端 `asset_id`；模型不得提交本地路径、任意
  URL、Provider、计划摘要或伪造业务 ID。

## 变更控制

以下实现锚点用于审计，不改变本 ADR 的定义：

- [当前架构事实](CURRENT_ARCHITECTURE.md)
- [唯一用户入口 Skill](../skills/learning-resource-flow/SKILL.md)
- [MCP ResourceService](../mcp/education-resources/src/education_resource_mcp/service.py)
- [离线 adaptive evaluator](../mcp/education-resources/src/education_resource_mcp/retrieval/adaptive.py)
- [resource_search coverage Schema](../mcp/education-resources/contracts/schemas/tools/resource_search.schema.json)
- [resource_flow_status Schema](../mcp/education-resources/contracts/schemas/tools/resource_flow_status.schema.json)

不得并行保留两套生产 Coverage 语义，不得把 `SemanticReview`、`Gap` 或 `StopDecision` 新增为
公共 MCP Tool/可提交字段。任何跨边界改动都必须同步契约、Schema、迁移、运行时代码和回归证据；
仅修改说明文档不能改变权威事实。
