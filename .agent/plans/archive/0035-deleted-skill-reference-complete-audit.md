# Deleted Skill Reference Complete Audit

- 状态：completed
- 创建日期：2026-08-11
- 完成日期：2026-08-11
- 范围：0031 前 `learning-resource-flow` 的旧 `SKILL.md` 与全部 11 个已删除 reference，对照当前 `SKILL.md + 6 references + machine contracts/runtime`
- 前置：0034 已补回一批确认语义，但后续检查发现其审计范围虽然列出了旧文件，却没有把所有仍有效行为逐项闭环；本计划作为纠偏，不回写历史把 0034 伪装成“当时已经完整”。

## Objective

一次性完成旧 Skill 行为的语义守恒审计，确保不再依赖用户逐条指出遗漏。每一类旧规则落入以下三种之一：

1. `retained`：当前 Skill/reference 已有等价规则；
2. `machine-owned / intentionally removed`：应由 contract/runtime/Registry/session state 等机器事实承担，或已经过时；
3. `semantic loss`：仍影响真实 Agent 行为，但当前没有等价承载，已最小补回。

## Non-goals

- 不恢复 11 个旧 reference 文件。
- 不恢复 Markdown 平台能力快照、登录状态快照、Provider route 快照、taxonomy 常量副本。
- 不新增新的公共 Tool、Schema、MCP 状态或业务 source of truth。
- 不把历史经验默认升级为新的硬业务要求。
- 不修改 0027/0028/0029 路线。

## Business invariants

- Skill 负责语义、对话、来源选择和 StopDecision；MCP/contract/runtime 负责事实与副作用。
- 静态平台身份/认证属性从 Platform Registry 读取；当前会话状态从 session-manager/实际返回读取；当前 acquisition 可执行性走 Descriptor → Readiness → Resolution/Representation → Eligibility → Plan/Execution。
- 可信来源导航是 discovery guidance，不是安全 allowlist、capability allowlist 或内容质量证明。
- 任何恢复项不得建立第二份机器真相。

## Audit corpus

旧基线：`3c90806099dd13191b437c1ffb862f83182af47b`

1. `SKILL.md`
2. `intent-and-clarification.md`
3. `response-guidelines.md`
4. `adaptive-retrieval.md`
5. `candidate-judgment.md`
6. `discovery-strategy.md`
7. `platform-capabilities.md`
8. `site-whitelist.md`
9. `inspection-strategy.md`
10. `acquisition-strategy.md`
11. `mcp-workflow.md`
12. `library-structure.md`

当前承载：`SKILL.md` + `conversation.md` / `retrieval.md` / `source-routing.md` / `inspection.md` / `acquisition.md` / `library.md`，并对照 Platform Registry、Capability Descriptor、taxonomy、Tool Schema、Retrieval Authority ADR 和 archive/runtime。

## 实际修改

- `skills/learning-resource-flow/SKILL.md`
  - 恢复所有带 `idempotency_key` 操作的通用重试规则；
  - 恢复结构化失败/响应不确定时先读权威状态；
  - 恢复核心任务变化时建立新 Flow、同一目标换搜索角度继续当前 Flow；
  - 明确不从聊天文本重建 ID/version/digest/token/provider/path。
- `references/conversation.md`
  - 恢复 Ready 两问判断；
  - 恢复“先承接已知信息、只问一个最小必要问题、必要时给少量自然方向”；
  - 恢复首轮搜索前简短说明路线；
  - 恢复失败时“真实事实 + 一个可执行下一步”。
- `references/retrieval.md`
  - 恢复理解/沉浸/观察/实践/巩固/表达等 SearchDirection 语义模板，但不作为 taxonomy；
  - 恢复 `has_more` 不等于 Gap、不能自动无限翻页；
  - 恢复候选展示的用户决策信息和 canonical public URL 边界；
  - 恢复“全部”只表示当前 Presentation。
- `references/source-routing.md`
  - 恢复 curated preferred source 定向搜索知识；
  - 明确它不是 security/network/capability allowlist；
  - 恢复静态 auth 属性与动态 session state 的区分；
  - 恢复 optional/required auth 对搜索流程的行为边界；
  - 明确 Generic Web discovery 不能冒充 native platform search。
- `references/acquisition.md`
  - 恢复 prepare 后向用户解释 selection、scope、representation/container、size/expiry、auth/policy/warning 等实际 Plan 事实；
  - 不暴露 token/digest/内部 Provider/原始 Plan JSON。

`library.md` 在本计划前一提交已经恢复本地资料库目录视图，本轮回读后无需再次修改。`inspection.md` 在 0034 已补回 unsupported/partial/cache 等状态语义，本轮无需再次修改。

## 逐文件闭环

### 1. 旧 `SKILL.md`

- `retained`：唯一入口、ResultSet/Presentation/Selection、SemanticReview/Gap/StopDecision、Inspect、Capability Authority、确认后 start、Archive/Asset 边界。
- `semantic loss -> fixed`：通用 Tool 幂等/恢复、Flow 生命周期。
- `intentionally not restored`：旧“孩子和家长”作为全产品默认范围；当前产品已收敛为一般教育/学习资源，`user_role/resource_target` 仍可表达 child/parent，但不默认补画像。

### 2. `intent-and-clarification.md`

- `semantic loss -> fixed`：explicit/inferred/defaulted、must/prefer/exclude、载体/内容形态/文件格式、Ready 判断、澄清问法。
- `not restored as global default`：旧儿童成长扩展性护栏；只在真实 resource_target/主题需要时由 target_fit 和高风险来源策略处理，不建立默认儿童画像。

### 3. `response-guidelines.md`

- `semantic loss -> fixed`：搜索前简短说明、候选决策信息、Presentation 成功后才邀请选择、“全部”当前 Presentation、Plan 用户解释、失败给可执行下一步、Archive 相对位置/分类语义（后者已在 `library.md`）。
- `intentionally removed as hard template`：固定推荐 3–5 个、固定响应模板；这些是表现层经验，不升级为业务不变量。

### 4. `adaptive-retrieval.md`

- `retained`：SearchDirection/ResultSet/coverage/SemanticReview/Gap/StopDecision authority、预算、replace/extend、连续无增量停止、offline adaptive oracle 边界；oracle 边界由 `docs/RETRIEVAL_AUTHORITY.md` 明确承担。
- `semantic loss -> fixed`：`has_more` 不自动驱动继续搜索、通用 idempotency/recovery、Flow 生命周期。

### 5. `candidate-judgment.md`

- `semantic loss -> fixed by 0034`：可信度、互补性、未核验证据强度、Presentation save 失败。
- `retained`：relevance/usefulness/target_fit/constraint_fit/substantive/evidence_level、unknown 不等于 pass、隐藏候选不可选。
- `not restored as fixed behavior`：固定 3–5 推荐数量和旧儿童内容扩展规则。

### 6. `discovery-strategy.md`

- `semantic loss -> fixed`：学习结果方向模板、领域来源选择、site 定向搜索、登录对搜索质量的行为策略。
- `retained`：查询由 goal/resource_target/explicit constraints 驱动，resource type 不是 platform/provider 路由器。
- `corrected`：不再写固定平台 auth 表；改为按 Registry 静态属性 + session-manager/实际返回动态事实执行。

### 7. `platform-capabilities.md`

- `machine-owned`：平台 resource types、search/browse/inspect 声明、auth_mode/auth_kind -> Platform Registry；acquisition route -> Capability Descriptor + runtime authority chain。
- `intentionally removed`：Markdown 完整平台能力矩阵、catalog/version/exact route 快照。
- `residual architecture gap`：旧文件还记录过 adapter backend provenance，例如 Anna's Archive search 为 Libgen-backed、Wechat search 为 Sogou Weixin-backed。当前 runtime 代码仍有这些事实，但公共 Candidate/Registry 没有通用 backend provenance 字段。此次不把它们复制回 Skill；若产品需要向用户稳定披露“搜索实际由哪个 backend 提供”，应由后续机器契约/Registry 增加 provenance，而不是再建 Markdown 真相表。

### 8. `site-whitelist.md`

- `semantic loss -> fixed`：原本是搜索质量知识而不是机器能力表，已恢复到 `source-routing.md` 并改称 `curated preferred discovery sources`。
- 明确这些站点不是 security allowlist、network allowlist、Capability 或内容审批。
- 当前站点是否仍可访问以实际搜索结果为准，不把静态线索说成运行时可用性。

### 9. `inspection-strategy.md`

- `retained / fixed by 0034`：Selective Inspection、FEATURE_NOT_SUPPORTED、partial/unresolved、AUTH_REQUIRED/policy blocked、cache/historical Resolution、Inspect 后重做 SemanticReview/Gap。
- `machine-owned`：具体 request schema、Inspector 网络/安全实现细节。

### 10. `acquisition-strategy.md`

- `retained`：Capability Authority、primary/representation/landing/metadata、exact Provider、no silent fallback、Asset/Bundle、Job status。
- `semantic loss -> fixed`：Plan 面向用户的实际解释、retry/re-prepare/re-confirm。
- `machine-owned`：web materializer 文件清单、Provider/Artifact 内部映射、具体大小常量与实现细节。

### 11. `mcp-workflow.md`

- `semantic loss -> fixed`：通用 idempotency、`ok=false`/响应不确定恢复、Flow 生命周期、“全部”只指当前 Presentation。
- `retained`：Presentation/Selection/prepare/start、AUTH_REQUIRED/session-manager、Job/Archive/Library Search 主链。
- `machine-owned`：具体 schema 字段、catalog 版本与内部 ID 形状。

### 12. `library-structure.md`

- `semantic loss -> fixed before this plan`：本地资料库是 Archive 的用户可理解物理视图，目录概念为领域/主题/格式/文件；归档成功后可解释安全相对路径；needs_review/unclassified 不冒充分类完成。
- `machine-owned`：learning-v1 领域 ID、具体目录名、字段上限、命名清洗、去重/发布实现。

## 验证

- 回读旧 12 个输入面，并逐项映射到当前六 references、`SKILL.md`、Retrieval ADR、Platform Registry、Capability Descriptor、taxonomy 与实际 archive/adapter runtime。
- 回读修改后的 `SKILL.md`、`conversation.md`、`retrieval.md`、`source-routing.md`、`acquisition.md`；`inspection.md` 与 `library.md` 无本轮新增改动但纳入闭环检查。
- 以本任务开始前提交 `0ff7ca28922196fa06f4c649cf7533580d9e8ba5` 为基线执行 GitHub compare：实际 Skill 变更只有 `SKILL.md` + 4 个 reference；没有 runtime/contracts/Schema/0027/0028/0029 改动。
- 本轮为 Markdown Skill 语义修复，不运行 MCP 全量测试；没有执行真实 OpenClaw 用户流，也不声称完成该验证。
- 未执行本地 Markdown link checker 或 `git diff --check`；通过逐文件回读和 GitHub compare 作为本轮实际验证。

## Acceptance criteria

- AC-01：12 个旧输入面均有明确闭环结论：pass。
- AC-02：所有确认 `semantic loss` 均有当前承载位置：pass。
- AC-03：Platform Registry / Descriptor / session state / taxonomy 没有在 Skill 中复制完整快照：pass。
- AC-04：可信来源定向搜索恢复为 discovery guidance，并明确不是 security/capability allowlist：pass。
- AC-05：diff 仅涉及 Skill/reference 与本计划；归档时另只更新归档索引：pass。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no, GitHub compare confirmed
Actual user flow affected?: yes, restored previously lost Skill guidance
Actual user flow validated?: no real OpenClaw run in this Markdown audit
Scope drift detected?: no
```

## Steps

- [x] A. 重新读取 12 个旧输入面与当前六-reference/机器权威。
- [x] B. 冻结完整分类表。
- [x] C. 一次性补齐全部剩余 semantic loss。
- [x] D. 回读并做机器事实副本检查。
- [x] E. compare、记录残余风险、归档。

## Result

0031/0032 的问题不是“旧内容都应该恢复”，而是当时没有做规则级语义守恒。0034 修了一部分，但仍遗漏来源路由、登录行为、Ready/响应、通用幂等与 Flow 生命周期等规则。本计划完成后，旧 12 个输入面均已有明确去向；当前继续保持 6-reference 架构，不恢复旧 reference 体系。
