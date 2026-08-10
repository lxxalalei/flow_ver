# Retrieval Authority and Quality Calibration

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：测试环境与机器事实、Retrieval 权威边界、FactualCoverage、SemanticReview、StopDecision、最小校准集、Skill/MCP 运行时集成与回归

## 目标

以真实用户链路为唯一验收对象，消除公共 factual coverage、内部 adaptive evaluator 与
Skill 语义判断之间的双重/多重权威。服务端只声明可验证事实，模型只负责需要语义理解的
审查，最终停止决策具有唯一且可解释的执行位置。任何缺少相关性、目标适配或必要可用性
证据的候选，不得仅因标题、数量或搜索方向存在而触发 `Present`。

## 明确非目标

- 不新增第 14 个 MCP Tool，不新增平台。
- 不以增加超时、吞掉失败或保留双轨逻辑作为测试稳定化方案。
- 不把 LLM 语义判断伪装为服务端事实，也不让模型伪造 provenance、availability 或获取结果。
- 不破坏 ResultSet 不可变、Presentation/Selection 绑定及 `prepare -> confirm -> start` 安全边界。
- 本计划不承担完整真实平台 readiness；该部分进入后续 0026。

## 架构原则

- `FactualCoverageSummary`：当前 public `coverage` 仅由服务端基于 Search ResultSet 事实产生；Inspect/Resolution/Registry/Job/Asset/Archive 保持各自独立权威，不反写旧 coverage。
- `SemanticReview`：由 Skill/LLM 对 relevance、usefulness、target fit、substantive 等语义维度产生，不成为公共 MCP 权威事实。
- `StopDecision`：由唯一入口 Skill 执行；MCP 不持久化 Skill 语义结论，offline oracle 只用于校准。
- `retrieval/adaptive.py`：固定为离线 oracle/benchmark evaluator，不搜索、不 Inspect、不下载、不归档、不写公共状态。
- 校准先有基线再改实现；0024 固化可重复 benchmark 与 Skill 权威边界，真实平台/Agent 质量门禁转交后续计划。

## 步骤

- [x] completed：冻结当前机器事实、修正 OpenClaw/测试环境漂移，建立使用 Linux 本地临时目录和串行 OpenClaw 命令的可重复 baseline 与失败分类
- [x] completed：完成 Retrieval Authority ADR，确定 public Search factual coverage、Skill SemanticReview/Gap/StopDecision 与 offline oracle 的唯一权威边界
- [x] completed：建立 39 个 decision-focused 最小校准集、gold 期望和机器可比较 runner
- [x] completed：收紧 factual evidence 聚合与命名，明确 immutable Search coverage 与 Inspect/Resolution/Registry/Job/Asset/Archive 独立事实的语义边界
- [x] completed：校准 displayable、target/constraint/availability/selection evidence 与 Gap/StopDecision 规则，并验证未知不能升级为 Present
- [x] completed：在唯一入口 Skill 文档中固化语义审查和停止决策边界，收敛 adaptive 双轨逻辑为 offline oracle；真实平台 readiness 与 Agent 全链路不纳入本计划
- [x] completed：在 E2E 子进程显式环境隔离修复后，重新完成定向、契约、全量、stdio、OpenClaw preflight 和 benchmark 根回归
- [x] completed：同步 Skill references、CURRENT_ARCHITECTURE、DEVELOPMENT_PLAN、README 和下一阶段规划的当前 factual coverage 语义与版本证据
- [x] completed：根智能体完成跨层代码审查、差异审查和最终验收；剩余平台/质量门禁风险转交 0025/0026/0027

## 测试环境验收

- 项目 venv 必须由当前 `pyproject.toml` 可重复构建，包版本与依赖一致；真实需要的延迟导入依赖必须可导入。
- 测试临时目录必须位于 Linux 本地文件系统的受控临时目录，不依赖 `/mnt/c` 9p。
- 不允许多个全量测试套件共享同一临时状态或因 OpenClaw CLI 锁竞争并行执行。
- Job/stdio 测试使用显式 readiness/事件条件和诊断信息，不以盲目延长固定 sleep 掩盖问题。
- functional failure、environment failure、timeout/flaky 必须在测试输出和验收记录中分开。

## 最小校准集验收

至少覆盖：

- 仅标题相关、无语义证据；
- 标题相关但 Inspection 证明正文不相关；
- 高质量 search-only 探索任务；
- 错误 `resource_target`；
- 硬约束未知、冲突或不满足；
- 单一来源族与横向比较任务；
- landing-page-only 与资源本体获取要求；
- 教材同步的最小澄清边界；
- 连续零增益；
- AUTH_REQUIRED、POLICY、FEATURE_NOT_SUPPORTED；
- 同名版本/representation 不确定；
- 候选数量足够但没有必要证据。

每个 case 至少标注：期望展示/拒绝候选、关键 Gap、是否 Inspect、是否 Clarify、期望
StopDecision、期望 acquisition scope。改动前后输出机器可比较结果。

## 验证

计划执行期间使用以下命令（OpenClaw 命令串行执行；Python 测试和 compileall 使用
`TMPDIR=/tmp`，避免 `/mnt/c` 9p 临时目录）：

```bash
cd mcp/education-resources
TMPDIR=/tmp TEMP=/tmp python -m unittest discover -s tests -q
TMPDIR=/tmp TEMP=/tmp python scripts/run_retrieval_calibration.py
TMPDIR=/tmp TEMP=/tmp python -m unittest discover -s tests -p test_inspection_core.py -q
TMPDIR=/tmp TEMP=/tmp python -m compileall -q src tests scripts

openclaw config validate --json
openclaw mcp status --verbose
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

## 结果

### 根验收完成证据（2026-08-08）

- 标准隔离入口进程级 stdio E2E：**8 tests，OK**；全量 education-resources unittest：**374 tests，OK**。
- Retrieval calibration：**39 cases，passed=39，failed=0**。
- Inspection Core 定向回归：**7 tests，OK**。
- `compileall -q src tests scripts`：**exit 0**。
- OpenClaw `config validate`：`valid=true`、`warnings=[]`；MCP status 指向当前仓库和持久
  venv，并保留 `resource_*` filter；MCP doctor：`ok`；MCP probe：**13 tools**、
  `diagnostics=[]`。
- 0024 关联的 contract/schema、service/integration、import-boundary、runtime-dependency
  与 stdio cleanup 已包含在上述全量 unittest；契约/coverage 定向回归 **25 tests，OK**；
  本轮相关 Markdown 相对链接检查为 `checked_relative_links=56`、`missing=0`，JSON 解析、
  `git diff --check` 与未跟踪文件尾随空白检查均通过。
  未执行真实平台网络或 Agent 对话，不将其写成通过。

### 根验收结论

- P1 测试隔离问题已修复：裸 `RawMcpClient` 使用显式白名单环境，MCP data/library、HOME/XDG、临时目录和 Python cache 均位于每个 E2E 的受控目录；父进程的 session-manager、搜索后端、凭据、Cookie、Python import 配置和其他 MCP override 不会进入 fixture 子进程。
- 根智能体在最终实现稳定后重新串行完成 8/8 E2E、374/374 全量回归、39/39 calibration、25 项契约/coverage 定向回归、compileall 和 OpenClaw config/status/doctor/probe；独立只读审查未发现生产 authority、import boundary 或安全边界阻塞。
- 0024 范围已完成；默认 Agent 完整回合、真实平台 readiness 和持续 benchmark release gate 分别进入 0026、0026 和 0027，不以 fixture/doctor/probe 冒充。

### 交接风险（不阻塞 0024 完成）

- **0025**：平台能力真值审计和契约对齐——Registry/runtime readiness、Resolution/
  Representation、Policy eligibility、Provider routing、权限/版权资格及跨层 revalidation。
- **0026**：真实 OpenClaw Agent 与真实平台 E2E——Search → Inspect → Present → Select →
  Confirm → Acquire → Archive → Recover，以及真实网络/授权边界；当前 preflight/probe 通过
  不等于完整 Agent/平台链路已验收。
- **0027**：持续质量与可观测性发布门禁——premature Present、Gap precision/recall、Inspect
  efficiency、acquisition truthfulness 和长期 calibration telemetry。具体后续计划文件按阶段
  另行建立。
