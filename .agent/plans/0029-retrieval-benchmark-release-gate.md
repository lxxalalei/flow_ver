# 0029 Retrieval Benchmark and Release Gate

- 状态：pending
- 创建日期：2026-08-08
- 完成日期：未完成
- 范围：固定 gold 任务集、离线 benchmark runner、Retrieval/SemanticReview/StopDecision/Capability truth 指标、基线与差异报告、本地与 CI 发布门禁
- 前置条件：[`0025 Platform Capability Contract Alignment`](archive/0025-platform-capability-contract-alignment.md) 完成；真实 Agent 指标需 [`0028 Real OpenClaw and Real Platform E2E`](0028-real-openclaw-platform-e2e.md) 证据
- 权威边界：[`Retrieval Authority`](../../docs/RETRIEVAL_AUTHORITY.md)

## 目标

建立版本化、可重复、机器可比较且不访问真实凭据的检索质量门禁，使每次修改都能回答：
候选相关性是否改善、是否过早 Present、Gap 是否准确、Inspect 是否有效、能力是否被误承诺、
真实 Agent 是否能完成闭环。Benchmark 不是第二套生产状态机，不写 MCP 公共事实，也不以一个
综合总分掩盖 P0 安全或真实性失败。

## 硬边界

- production factual coverage 仍由 MCP Search ResultSet 事实产生；SemanticReview/Gap/StopDecision
  仍由唯一入口 Skill 执行；offline oracle 只用于 gold 比较和回归。
- Benchmark runner 不搜索真实平台、不下载、不归档、不持久化到生产 SQLite，不读取真实凭据。
- 真实网络 smoke 和 OpenClaw 对话指标使用 0028 的独立、脱敏证据；不得混入确定性离线分数。
- 不以增加样本宽松度、删负例、随机重试、多次取最好结果或静默 fallback 提高分数。
- Critical invariant 任一失败都直接阻断发布，不能被平均分抵消。
- Gold 变更必须可审查、版本化并说明为何用户期望发生变化；不能只为让当前实现通过而改 gold。

## Benchmark 领域模型

每个 case 至少包含：

```text
case_id
benchmark_version
task_family
user_utterance
user_role
resource_target
explicit_constraints
fixture/search/inspection facts
expected_displayable_ids
forbidden_display_ids
expected_key_gaps
expected_clarify
expected_inspect_ids / inspect_budget
expected_stop_decision
expected_acquisition_scope
expected_capability_status / reason_codes
critical_invariants
gold_rationale
```

Runner 输出每 case 的原始事实摘要、预测/期望差异、指标贡献和稳定失败码，同时生成 JSON 和
人可读 Markdown 报告。所有排序指标必须明确 N、去重规则、无候选分母与 unknown 处理方式。

## 步骤

- [ ] pending：A. 冻结 benchmark schema、gold 评审规则、指标数学定义、随机性/重复运行策略和 critical invariant 列表
- [ ] pending：B. 从 0024 calibration、0025 capability truth、0028 Agent evidence 和历史 regression 提炼版本化任务集，建立独立 train-free gold
- [ ] pending：C. 实现确定性离线 runner、case-level JSON、聚合 Markdown、baseline snapshot 和版本/digest 校验
- [ ] pending：D. 实现 Retrieval relevance、Present/Replan、Gap、Clarify、Inspect efficiency、dedup/source diversity 指标
- [ ] pending：E. 实现 acquisition truthfulness、scope/provider/readiness/policy、no-fallback、Plan/Outcome consistency 指标与 P0 门禁
- [ ] pending：F. 将 0028 脱敏 OpenClaw 证据接入独立 E2E completion/readiness 报告，不污染离线确定性指标
- [ ] pending：G. 建立本地单命令和 CI/release gate，支持与批准 baseline 比较、失败阈值、报告归档和可审查 baseline 更新
- [ ] pending：H. 执行全量 benchmark、单元/契约/全量/stdio 回归，更新 DEVELOPMENT_PLAN/CURRENT_ARCHITECTURE/README，由根 Agent 完成逐指标审计

## 最低任务集

| 任务族 | 最低数量 | 必须覆盖 |
| --- | ---: | --- |
| 窄目标查找 | 12 | 指定主题、格式、来源、语言，precision 与硬约束 |
| 宽泛探索 | 12 | 多方向探索、search-only 可展示边界、停止成本 |
| 混合资源 | 12 | article/video/document/book/course 组合与来源多样性 |
| 教材同步 | 10 | 必须澄清与不应询问年级/年龄的边界 |
| 版本与表示 | 10 | 版本、册次、PDF/EPUB、primary/representation/landing/metadata |
| 来源可信度 | 10 | 官方、专业、社区、聚合/镜像来源差异 |
| 认证与策略 | 10 | AUTH_REQUIRED、policy block、unsupported、readiness expiry |
| 低质量负例 | 14 | 标题党、重复、无正文、错误 target、候选数量伪充分 |
| 网页物化 | 10 | 文本、图文、长文、代码、表格、复杂页面与资源边界 |
| 恢复与状态 | 8 | 重启、幂等、Selection/Plan 失效、取消、partial |
| Capability truth | 12 | search-only、landing-only、concrete primary、provider drift/no fallback |

最低总量为 120 cases；每个任务族至少包含正例、负例、unknown/insufficient 例和一个会改变
StopDecision 或 acquisition scope 的边界例。新增 case 不得复制同一事实仅改标题凑数。

## 指标定义

### Retrieval / Conversation

- **Top-N Relevance Precision**：实际展示 Top-N 中 gold relevant 的比例；N 和空集合行为固定。
- **Forbidden Display Rate**：被 gold 明确禁止展示的候选进入 Presentation 的比例。
- **Premature Present Rate**：仍有 gold critical Gap 或必要证据缺失却选择 Present 的 case 比例。
- **Unnecessary Replan Rate**：gold 已满足目标且无 critical Gap 却继续搜索/Inspect 的比例。
- **Gap Precision / Recall / F1**：按规范化 Gap 类型与绑定对象比较，不用自由文本相似度冒充。
- **Clarification Precision / Recall**：只对会改变资源范围/选择的必要澄清计分；年龄/年级误问单列。
- **Inspect Precision**：Inspect 的候选中 gold 认为需要 Inspect 的比例。
- **Inspect Recall**：gold 必须 Inspect 的候选被检查比例。
- **Inspect Efficiency**：完成目标所需 Inspect 次数与 gold 最小预算的差异，安全必要检查不作为浪费。
- **Source Diversity / Dedup Accuracy**：来源族覆盖与逻辑重复识别准确性，不能用数量替代质量。

### Capability / Acquisition

- **Acquisition Truthfulness**：scope、strategy、provider、representation、eligibility 和 outcome 与 gold/事实一致比例。
- **Primary False-Promise Rate**：landing/metadata/unknown 被承诺为 primary 的比例。
- **Implicit Fallback Rate**：Provider/strategy/scope 在 prepare/start/outcome 间未经声明改变的比例。
- **Revalidation Escape Rate**：descriptor/readiness/source/policy 漂移却成功 start 的比例。
- **Asset Truth Rate**：成功结论具有真实、校验过且与 outcome/Bundle 绑定的 Asset 比例。
- **E2E Completion**：来自 0028 真实 Agent 证据的任务完成比例；与离线质量分开报告。

## Critical Invariants（零容忍）

以下任一 case 失败即 release gate 失败，不允许综合分抵消：

1. landing/metadata/search-only 被升级为 primary，或无 concrete primary 仍报告下载成功。
2. 未经 `prepare -> 用户确认 -> start` 发生副作用。
3. descriptor/readiness/resolution/eligibility/authority digest 漂移未阻止 start。
4. exact provider 失败后切换 generic/其他 provider，或 strategy/scope 被静默改变。
5. 私网/本机/metadata endpoint、恶意重定向、超限、MIME/magic 冲突绕过安全校验。
6. 模型/fixture 伪造 Job、Outcome、Asset、Archive、路径或成功状态。
7. 用户未要求教材同步却仅为“适龄”主动追问年龄/年级，或从 user_role 推断 resource_target。
8. legacy Skill/Tool 被默认发现，公共 Tool 数偏离 13，或 active MCP 运行时导入 legacy。
9. 真实凭据、Cookie、Token、浏览器档案、SQLite 或下载产物进入仓库/报告。

## Release Gate

首个批准 baseline 建立后，默认门禁为：

- Critical invariants：**0 failure**。
- Premature Present、Forbidden Display、Primary False-Promise、Implicit Fallback、
  Revalidation Escape：**不得高于批准 baseline，且目标绝对值为 0**。
- Top-N precision、Gap F1、Clarification F1、Inspect precision/recall、Acquisition Truthfulness、
  Asset Truth：**不得低于批准 baseline**；任何下降必须有逐 case 审查和明确用户价值证据，不能自动放行。
- Unnecessary Replan 和 Inspect cost：不得显著恶化；显著性阈值在 Phase A 根据重复运行方差冻结，
  冻结后只能通过版本化决策修改。
- 任务集、schema、gold、runner、baseline 均有版本和 digest；digest 不匹配直接失败。
- 单元/契约/全量/stdio E2E、compileall、Markdown link、`git diff --check` 同时通过。
- 0028 未完成时，E2E Completion 只能显示 `not_verified`，不得用 fixture 分数代替；0029 可先完成
  离线 gate，但主体架构最终 DoD 必须等 0028 真实证据接入。

## 目录与产物建议

```text
mcp/education-resources/benchmarks/
├── schemas/
├── cases/
├── gold/
├── baselines/
└── README.md
mcp/education-resources/scripts/run_retrieval_benchmark.py
mcp/education-resources/tests/test_benchmark_contract.py
mcp/education-resources/tests/test_benchmark_metrics.py
.openclaw-test/benchmark-output/   # 临时运行输出，不进入版本库
```

仓库只保存小型、脱敏、可审查的 fixture/gold/baseline；大型运行日志和真实平台产物不进入仓库。

## 验证入口

最终应提供一个无需网络和凭据的稳定入口，例如：

```bash
cd mcp/education-resources
PYTHONPATH=src TMPDIR=/tmp TEMP=/tmp <venv-python> scripts/run_retrieval_benchmark.py \
  --cases benchmarks/cases \
  --gold benchmarks/gold \
  --baseline benchmarks/baselines/approved.json \
  --output .openclaw-test/benchmark-output
```

以及受影响测试、全量 unittest、stdio E2E、compileall、Markdown links、文件存在性和仓库根
`git diff --check`。Runner 必须以非零退出码报告 schema/digest/critical invariant/threshold 失败。

## 退出条件

1. 120+ 个去重且经审查的 gold cases 覆盖全部任务族与关键边界。
2. Schema、gold、runner、baseline 都有稳定版本/digest，报告可在同一环境重复生成。
3. 所有指标有数学定义、边界行为、单元测试和 case-level 可追溯差异。
4. Critical invariants 零失败，Release Gate 的 baseline/absolute 阈值全部通过。
5. Acquisition truth 覆盖 0025 authority 全链，真实 E2E 指标与 0028 证据分层。
6. 本地单命令和 CI/release 入口可用，失败返回非零且生成可审查报告。
7. 全量 unittest、stdio E2E、compileall、契约/链接/diff 检查通过。
8. DEVELOPMENT_PLAN、CURRENT_ARCHITECTURE、README/运维文档写明门禁、更新流程与剩余风险。
9. 根 Agent 对任务集质量、gold 独立性、指标、baseline、critical invariants 和运行证据逐项审查通过。

## 结果

- 尚未开始；当前仅冻结执行计划。0025 已完成；0028 真实证据未完成前，E2E Completion 必须保持 `not_verified`，不得用 fixture 分数替代。
