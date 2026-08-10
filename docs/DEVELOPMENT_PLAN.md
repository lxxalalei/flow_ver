# 教育资源 OpenClaw evergreen 开发路线

## 文档定位

这是本项目唯一的长期技术路线图。它描述目标、顺序、边界和完成门槛，不记录每轮执行日志、
历史测试数字或已归档设计。当前工作树的机器事实见
[CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)；正在执行的细节见对应的
`.agent/plans/` 文件。

当前 active 产品只有：

- `skills/learning-resource-flow/`：唯一用户入口和对话编排层；
- `mcp/education-resources/`：Python stdio MCP、领域契约、搜索、核验、获取、任务状态和归档。

当前技术顺序固定为：

```text
0027 平台获取能力接入
  -> 0028 真实 OpenClaw / 真实平台 E2E
  -> 0029 检索 benchmark 与 release gate
```

0025 Platform Capability Contract Alignment 已于 2026-08-10 完成，是上述顺序的前置基础。
文档治理由 [0030 计划](../.agent/plans/archive/0030-document-authority-consolidation.md) 单独跟踪，
不改变产品路线。

## 产品目标与任务模型

用户应能通过自然语言完成可信的教育资源闭环：表达模糊需求、获得必要且克制的澄清、探索来源、
理解候选差异、明确选择、安全获取，并在需要时归档和再次查找。

任务模型只由以下独立部分组成：

- `user_role`：当前对话者是孩子或家长，可以未知；
- `resource_target`：资源给孩子使用或给家长参考，可以未知；
- 目标与用户明示的 `constraints`：主题、资源形态、语言、版本、来源、时间、格式等。

`user_role` 和 `resource_target` 不能相互推导；未提供的信息保持 unknown。Skill 不为补齐模型
而追问，也不把年龄、年级或身份暗推成搜索方向。搜索策略必须由资源对象、目标和显式约束共同决定。

## 不可变架构约束

### Active 与历史边界

- 顶层 `skills/` 只保留 `learning-resource-flow`；旧七个 Skill 和阶段脚本只在
  `legacy/skill-pipeline-v1/` 中作为历史快照。
- Skill 不拼接 shell、Python、Node、脚本路径、绝对下载路径或任意业务 ID。
- MCP 是 Flow、ResultSet、Presentation、Selection、Plan、Job、Resolution、Outcome、Asset 和
  Archive 的服务端权威；模型不能手工伪造这些状态。
- 运行数据、凭据和下载资产与源码分离；测试数据只能进入 `.openclaw-test/` 或临时目录。

### 检索与停止决策

- MCP Search 只产生可恢复的 factual coverage；Inspect/Resolution、readiness、eligibility、Job、
  Asset 和 Archive 保持各自独立权威。
- Skill 私有地完成 SemanticReview、Gap 和 StopDecision；`retrieval/adaptive.py` 只能作为离线
  oracle/calibration helper，不得写入生产状态。
- 不因标题、候选数量、搜索方向或“已注册”自动 Present；证据不足时必须 Inspect、澄清、重规划或
  带 Gap 停止。详见 [Retrieval Authority ADR](RETRIEVAL_AUTHORITY.md)。

### 获取与安全

- 下载严格执行 `prepare -> 用户明确确认 -> start`；服务端在副作用调用中重新校验 ownership、
  来源、选择、计划、权限、状态、幂等和 authority binding。
- 能力路线必须保持 Descriptor → Readiness → Resolution/Representation → Eligibility → Plan →
  fresh Execution → exact Provider → Outcome；禁止隐式 generic fallback。
- 只允许 `http`/`https`，执行 SSRF、逐跳重定向、域名策略、超时、重试、并发、大小、MIME 和真实
  文件格式校验；不绕过登录、验证码、付费墙、DRM、版权或访问控制。
- Job 异步化并可查询、取消和恢复；归档只接受服务端 `asset_id`，大文件不进入模型上下文。

## 路线阶段

### 0027：Platform Acquisition Enablement（当前）

**目标**：把源码中已存在的获取能力接入 0025 冻结的单一能力权威链，不以平台名、资源类型或
generic Provider 猜路由，不把 landing page 或 metadata 冒充 primary resource。

**工作内容**：

1. 审计现有 Provider、Inspector、依赖、认证、网络、内容格式和版权/策略边界；
2. 为每条可执行路线固化 Capability Descriptor、运行时 Readiness、候选 Representation、
   Eligibility、Plan/Execution binding、exact Provider 和 Outcome；
3. 完成 Bilibili、Douyin、Ximalaya、Anna/Libgen 及通用 `web_capture` 等现有实现的明确接入或
   结构化阻断；浏览器渲染是获取机制，不是独立平台；
4. 关闭跨平台、跨 scope、跨 representation 的静默 fallback，并补齐取消、幂等、大小、MIME/magic、
   重定向、认证和失败恢复契约；
5. 只在合法、可审计的依赖和会话条件下声明 ready/eligible/provider success。

**完成门槛**：每个执行项都能从 descriptor 追溯到 fresh execution 和 persisted outcome；无权威
链缺口时只能阻断或要求重新 Inspect/prepare；定向代码、契约、Schema、状态和安全回归通过。

执行计划：[0027-platform-acquisition-enablement.md](../.agent/plans/0027-platform-acquisition-enablement.md)。

### 0028：Real OpenClaw and Real Platform E2E（后续）

**目标**：证明真实 OpenClaw 默认 Agent 能从自然语言使用唯一 Skill 和当前 MCP 完成可信闭环，
而不是用 fixture、直接 Service 调用、MCP probe 或 Adapter 注册冒充用户验收。

**工作内容**：

1. 冻结脱敏的运行环境、Git dirty 摘要、Skill/MCP 加载路径、catalog/Schema digest 和工具发现证据；
2. 串行验证 Search → Inspect → Present → Select → Confirm → Acquire → Archive → Recover；
3. 覆盖文章、网页物化、视频、音频、图书/版本、课程/Bundle、混合检索和失败恢复；
4. 对每个平台分别记录网络、认证、readiness、Representation、Eligibility、Provider、Outcome、
   Asset/Archive 和重启结果；
5. 只使用用户或平台合法授权的 session/SecretRef；不得把凭据、Cookie、浏览器档案、SQLite 或
   下载产物写入仓库；不绕过验证码、付费墙、DRM 或访问控制。

**完成门槛**：真实 Agent 工具调用顺序、人工确认点、服务端稳定 ID、持久化状态和面向用户的失败
解释可追溯；未具备合法会话或真实证据的平台保持明确 blocked/unsupported，不标记为 ready。

执行计划：[0028-real-openclaw-platform-e2e.md](../.agent/plans/0028-real-openclaw-platform-e2e.md)。

### 0029：Retrieval Benchmark and Release Gate（后续）

**目标**：建立版本化、可重复、机器可比较的质量与真实性发布门禁，防止候选相关性、语义停止决策和
获取能力被数量、标题或静默 fallback 掩盖。

**工作内容**：

1. 冻结可审查的 benchmark schema、gold 规则、指标定义、随机性策略和 critical invariants；
2. 从检索、语义审查、能力真值和真实 Agent 证据构建 train-free 任务集；
3. 实现确定性离线 runner、case JSON、聚合报告、baseline/digest 比较和可审查更新流程；
4. 分别度量 relevance、Present/Replan、Gap、Clarify、Inspect efficiency、去重/来源多样性、
   acquisition truthfulness、scope/provider/readiness/policy 和 Plan/Outcome consistency；
5. 将真实 OpenClaw 证据独立报告，不混入离线分数；任一 P0 安全或权威不变量失败即阻断发布。

**完成门槛**：benchmark 不搜索真实平台、不下载、不归档、不写生产 SQLite、不读取真实凭据；gold
变化可审查；报告能区分产品失败、环境失败、网络/认证失败和策略阻断。

执行计划：[0029-retrieval-benchmark-release-gate.md](../.agent/plans/0029-retrieval-benchmark-release-gate.md)。

### 后续：平台化部署

0027–0029 通过后，才讨论教育平台的远程 Streamable HTTP MCP、会话/凭据服务、存储和网络隔离、
多租户授权、审计与配额。远程化不是当前本地 MVP 的默认前置，也不能通过扩大本地 Tool catalog
替代真实平台化设计。

## 发布与变更门槛

一个阶段只有同时满足以下条件才可标记完成：

- **权威唯一**：机器状态只有一个可解释来源；Skill 的语义结论不伪装成 MCP factual facts；
- **安全**：没有模型伪造 ID、路径、URL、可用性、权限、Provider 或获取结果的成功路径；
- **可恢复**：重启、LLM 失败、超时、取消和幂等重放能从 MCP facts 恢复，缺失语义按 unknown 处理；
- **契约一致**：Schema、catalog、runtime、文档和测试同步；当前过渡只读行为按兼容政策解释，但不构成旧数据产品承诺；
- **用户可解释**：Clarify、Present、Replan、StopWithGap、blocked、unsupported、AUTH_REQUIRED
  和 partial 都保留真实原因；
- **证据可审计**：敏感值脱敏，命令和结果可复现，历史基线与当前事实不混写。

任何跨边界字段、工具入口、状态含义、Provider 路由或 StopDecision 位置的改变，必须同步更新
机器契约、持久化迁移、代码、测试和本文，不得只改 Markdown。
