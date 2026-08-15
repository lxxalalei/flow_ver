# 0055 — Public MCP Surface Simplification

- 状态：completed
- 创建日期：2026-08-16
- 完成日期：2026-08-16
- 范围：`mcp/education-resources` 公共 Tool 输入/输出、对应契约与 Skill 文档

## Objective

降低 OpenClaw 执行资源任务时的上下文压力和事务状态搬运，使 Agent 只接收完成下一步决策所需的紧凑业务事实，并由服务端继续持有完整 Flow / ResultSet / Resolution / Plan / Job 状态。

## Non-goals

- 不重写数据库结构或 Store。
- 不改 Provider、Downloader、Search/Inspect 平台 Adapter。
- 不解决本轮之外的 Job durable execution 问题。
- 不新增通用 projection/canonical/readiness/authority 框架。

## Business invariants

- 完整搜索、Inspect、Plan、Job、Asset 事实仍由服务端持久化。
- `prepare -> 用户明确确认 -> start` 不变。
- 用户序号选择仍绑定实际 Presentation。
- exact Provider 路由、认证失败和真实失败不得被隐藏或 fallback。
- 公共表面省略内部字段不等于删除服务端事实；不得静默改变用户选择或资源身份。

## Current architecture

- Public tools 注册：`src/education_resource_mcp/server.py`。
- Domain state / validation：`service.py` + `storage.py`。
- 公共 JSON Schema：`contracts/schemas/tools/`。
- Skill orchestration：`skills/learning-resource-flow/`。
- 完整 ResultSet / Presentation / Selection / Resolution / Plan / Job 继续由服务端持有；Public MCP 只投影下一步需要的事实。

## Expected change surface

- 已改：`server.py`、相关 Tool schemas、tool catalog 描述、Skill references、MCP/架构文档、定向静态 contract guard。
- 未改：DB migration、Store schema、Provider/Downloader/Adapter、平台 Registry 的能力事实。

## Acceptance criteria

- AC-01：`resource_search` 不再向 Agent 返回完整内部 ResultSet/平台运行细节，只返回候选决策所需的紧凑结果和必要失败摘要。**完成。**
- AC-02：`resource_flow_status` 用于恢复时不再重新灌入完整 candidates/resolutions/内部 digest 链，只返回当前阶段和下一步所需句柄/摘要。**完成。**
- AC-03：`resource_inspect` 不暴露 inspector version/fingerprint 等内部证据细节，只保留可访问性、表示形式和失败事实。**完成。**
- AC-04：`resource_job_status` 不要求 Agent 理解 presentation/selection/plan digest/provider execution 等内部绑定，只返回状态、进度、ready assets 与失败摘要。**完成。**
- AC-05：`resource_download_prepare` 的公共输入不再要求 Agent 提交 presentation/version/selection_digest；服务端从当前 Flow 状态读取并继续执行原有校验。**完成。**
- AC-06：契约、Skill 指引和定向测试与新公共表面一致。**完成。**

## Complexity exceptions

无。复用现有 Service/Store 状态和 `server.py` 边界 helper；没有新增通用 projection 框架或第二份状态权威。

## 实施结果

### 1. Agent 不再搬运内部事务绑定

已从 Public Tool 输入中删除：

- Search：`task_version`、`base_result_set_id`；
- Presentation：`result_set_id`；
- Selection：`presentation_id`、`presented_version`；
- Prepare：`presentation_id`、`presented_version`、`selection_version`、`selection_digest`。

这些值仍由服务端当前 Flow 状态解析，并继续进入原有一致性校验。

### 2. Public output 收紧

- Search / Browse Creator：去掉 ResultSet lineage、platform runs、provenance/coverage 等内部状态。
- Inspect：去掉 inspector/version/method、source fingerprint、evidence payload、resolution digest 等内部证据机器字段。
- Presentation / Selection：不再把内部 ID/version/digest 回传给 Agent。
- Prepare：只返回用户确认所需的 Plan handle、有效期、确认 token、资源/格式/风险摘要；不公开 Representation/Provider route 绑定。
- Start：只返回 `job_id/status/queued_at`。
- FlowStatus：改成 compact recovery summary。
- JobStatus：只返回状态、progress、ready Asset handle 与失败摘要。

### 3. Search 上下文预算

- 普通 `resource_search` 默认 `limit` 从 20 收紧到 8；需要广泛枚举时仍可显式提高。
- Candidate summary Public excerpt 上限 600 字，并用 `summary_complete` 明确是否完整。
- 没有用隐藏“前 20 个候选”的方式节省上下文；Search 本轮返回的候选仍全部可达。
- Creator Browse 保留请求范围内的完整候选清单（当前 limit 最大 200），但不回灌逐条长摘要；需要内容细节时再 Inspect 单项。
- FlowStatus 作为恢复工具只返回最多 20 条 candidate refs，并用 `candidate_refs_complete` 明确是否完整。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: only explicit public summary excerpts / recovery refs; completeness is surfaced; Search/Browse candidates are not silently hidden
Unrelated files changed?: no
Actual user flow affected?: public Agent choreography only
Actual user flow validated?: pending under 0028 real OpenClaw E2E
Scope drift detected?: no
```

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| 0055 stdlib static guard | passed via GitHub Actions run `31899769782` | Public server 参数与 Schema 输入一致；删除字段未回流；compact output 不公开目标内部字段；修改 Schema 的本地 `$ref` 可解析；search/creator/flow-status 预算规则受测试保护 | MCP runtime dependency integration、真实网络平台行为 |
| Existing contract shape compatibility | preserved by retaining internal `$defs/success` and stable `contract_version=1.0.0` / `catalog_version=1.7.0` / 14 tools | Direct Service fixture contract 与 Public MCP output 可以分层存在 | 完整历史测试套件全部通过 |
| targeted stdio/control-plane | not run in this execution environment | — | MCPServer `tools/list/call_tool` runtime behavior |
| real OpenClaw user flow | pending under `0028-real-openclaw-platform-e2e.md` | — | 实际 compaction/中断改善程度 |

没有执行全量回归：本次 diff 没有改数据库、Provider、Downloader 或平台 Adapter；按仓库验证预算只执行与 Public Surface 直接相关的静态门禁。真实 OpenClaw 验收继续由 0028 负责，不以静态测试冒充真实用户闭环。

## 结果

0055 实现完成。Public MCP 已从“暴露内部业务状态树/让 Agent 搬事务句柄”收敛为 thin Agent-facing surface；完整状态与校验仍在 Service/Store。下一步不是继续扩架构，而是在 0028 中复测此前容易 compaction/中断的真实 OpenClaw 任务，观察上下文压力是否实质下降。
