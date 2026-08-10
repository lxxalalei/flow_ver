# Deleted Skill Reference Complete Audit

- 状态：in_progress
- 创建日期：2026-08-11
- 范围：0031 前 `learning-resource-flow` 的旧 `SKILL.md` 与全部 11 个已删除 reference，对照当前 `SKILL.md + 6 references + machine contracts/runtime`
- 前置：0034 已补回一批确认语义，但后续检查发现其审计范围虽然列出了旧文件，却没有把所有仍有效行为逐项闭环；本计划作为纠偏，不回写历史把 0034 伪装成“当时已经完整”。

## Objective

一次性完成旧 Skill 行为的语义守恒审计，确保不再依赖用户逐条指出遗漏。每一类旧规则必须落入以下三种之一：

1. `retained`：当前 Skill/reference 已有等价规则；
2. `machine-owned / intentionally removed`：应由 contract/runtime/Registry/session state 等机器事实承担，或已经过时；
3. `semantic loss`：仍影响真实 Agent 行为，但当前没有等价承载，必须最小补回。

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

当前承载：`SKILL.md` + `conversation.md` / `retrieval.md` / `source-routing.md` / `inspection.md` / `acquisition.md` / `library.md`，并对照 Platform Registry、Capability Descriptor、taxonomy、Tool Schema 和 archive/runtime。

## Expected change surface

可能修改：

- `skills/learning-resource-flow/SKILL.md`
- `skills/learning-resource-flow/references/conversation.md`
- `skills/learning-resource-flow/references/retrieval.md`
- `skills/learning-resource-flow/references/source-routing.md`
- `skills/learning-resource-flow/references/acquisition.md`
- `skills/learning-resource-flow/references/library.md`（仅若仍有未闭环项）

不应修改：

- `mcp/education-resources/src/**`
- `mcp/education-resources/contracts/**`
- `docs/DEVELOPMENT_PLAN.md`
- 0027 / 0028 / 0029

## Initial complete classification

| 旧规则族 | 当前判断 | 处理 |
| --- | --- | --- |
| explicit / inferred / defaulted | semantic loss，0034 已补 | 保留当前 `conversation.md` |
| must / prefer / exclude 强度 | semantic loss，0034 已补 | 保留当前 `conversation.md` |
| 载体 / 内容形态 / 文件格式 | semantic loss，0034 已补 | 保留当前 `conversation.md` |
| Ready 判断与澄清问法 | semantic loss | 补 `conversation.md`，不恢复固定表单 |
| 搜索前对用户的简短路线说明 | semantic loss | 补用户响应原则，不暴露内部 query/tool trace |
| Candidate 可信度 / 互补性 | semantic loss，0034 已补 | 保留 `retrieval.md` |
| Presentation save 失败不能继续选 | semantic loss，0034 已补 | 保留 `retrieval.md` |
| ResultSet / Presentation / Selection 边界 | retained | 不重复 |
| SearchDirection / Gap / StopDecision authority | retained | 不重复 |
| SearchDirection 学习结果模板 | semantic loss | 补 `retrieval.md` 作为示例，不建新类型 |
| search/inspect 等副作用前后的通用幂等规则 | semantic loss | 在 `SKILL.md` 建一个通用 Tool 调用不变量段，避免每个 reference 重复 |
| 核心 goal/resource_target/硬约束变化时 Flow 生命周期 | semantic loss | 补 `SKILL.md` / `conversation.md` |
| `has_more` / 更多结果不能自动驱动无限搜索 | semantic loss | 补 `retrieval.md` |
| creator browse 路由 | semantic loss，0034 已补 | 保留 `source-routing.md` |
| 可信站点定向搜索与领域来源知识 | semantic loss | 恢复到 `source-routing.md`，改称 preferred/curated discovery sources，不叫安全白名单 |
| 平台静态能力/认证属性 | machine-owned | Platform Registry；Skill 只读，不复制表 |
| 当前 acquisition route | machine-owned | Capability Descriptor + runtime authority chain |
| 当前用户是否已登录 | machine-owned dynamic state | session-manager / 实际 AUTH_REQUIRED 等状态 |
| 登录对搜索质量的行为策略 | semantic loss | 补 `source-routing.md`：不默认逐平台阻塞；真实不足/认证状态再处理 |
| 固定 Markdown 平台能力表 | intentionally removed | 不恢复 |
| 固定 Markdown 平台登录状态表 | intentionally removed | 不恢复 |
| adapter 内部 backend / Provider 实现表 | machine-owned | runtime/provider facts；不复制 |
| Inspection unsupported/partial/cache 语义 | semantic loss，0034 已补 | 保留 `inspection.md` |
| Acquisition idempotency / re-prepare | semantic loss，0034 已补 | 保留 `acquisition.md`，通用规则上移后避免重复扩张 |
| 下载计划对用户应解释的关键事实 | semantic loss | 补 `acquisition.md`：只解释 MCP 实际返回的选择、representation/container、限制/expiry、warning |
| Web materializer 文件清单/Provider artifact 细节 | machine-owned | runtime；不在 Skill 固化副本 |
| Archive 分类/本地目录视图 | semantic loss，0034 后续已补 | 保留当前 `library.md` |
| taxonomy ID / 目录名 / 上限 | machine-owned | `learning-v1.json` / runtime，不复制 |
| “全部”只表示当前 Presentation 全部项 | semantic loss | 补展示/选择规则 |
| 错误响应先说明事实再给可执行下一步 | semantic loss | 补用户响应原则 |
| 固定推荐 3–5 个 | intentionally removed as hard rule | 可按任务给少量高价值候选，不恢复固定数量硬约束 |
| 旧儿童成长扩展性护栏 | scope-changed / partially retained by target_fit | 不整体恢复；只在用户/资源目标实际涉及儿童或高风险主题时使用相应来源与内容适配，不把年龄/学段变成默认画像 |

## Acceptance criteria

- AC-01：12 个旧输入面均有完整分类，不再出现“未审计但默认已迁移”。
- AC-02：所有 `semantic loss` 有当前承载位置或明确说明为何不补。
- AC-03：Platform Registry / Descriptor / session state / taxonomy 不在 Skill 中复制完整快照。
- AC-04：可信来源定向搜索恢复为 discovery guidance，并明确不是 security/capability allowlist。
- AC-05：diff 只涉及 Skill/reference 与本计划/归档索引。

## Validation plan

- 逐文件回读所有修改后的当前 Skill/reference。
- GitHub compare 确认没有 runtime/contracts/产品计划改动。
- Markdown-only 语义修复不默认运行 MCP 全量测试；不声称真实 OpenClaw 用户流已验证。
- 计划完成前做一次反向检查：每个旧 reference 至少有一条明确结论，不能只按“文件已删除”视为完成。

## Steps

- [x] A. 重新读取 12 个旧输入面与当前六-reference/机器权威。
- [x] B. 冻结完整分类表。
- [ ] C. 一次性补齐全部剩余 semantic loss。
- [ ] D. 回读并做机器事实副本检查。
- [ ] E. compare、记录残余风险、归档。
