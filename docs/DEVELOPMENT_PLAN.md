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
  -> 主体架构阶段完成
  -> 产品能力成熟：扩平台 / Library & Viewer / 持续质量优化 / readiness 扩展
  -> 平台化部署
```

0025 Platform Capability Contract Alignment 已于 2026-08-10 完成，是上述顺序的前置基础。
0027 不是新增产品方向，而是 2026-08-08 归档路线中原 0025 的“逐平台实际能力接入”执行面拆分；
该阶段已于 2026-08-11 完成：
0025 已完成 Descriptor、Readiness、Resolution/Representation、Eligibility、Plan/Execution、exact Provider、
Outcome 等能力权威骨架；0027 将可证明路线保持在该权威链，并对其余现有实现完成结构化阻断。因此，归档路线中的
原 0026 Real OpenClaw & Platform E2E 对应当前 0028，原 0027 Retrieval Benchmark & Release Gate
对应当前 0029。该拆分改变计划编号与颗粒度，不改变原路线的产品目标和先后依赖。

文档治理由 [0030 计划](../.agent/plans/archive/0030-document-authority-consolidation.md) 单独跟踪，
不改变产品路线。2026-08-08 的阶段规划保留在 archive 中作为历史决策依据；若本文与历史路线出现
实质产品目标差异，必须显式记录差异原因，不能因文档精简而静默丢失既定目标。

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

### 0027：Platform Acquisition Enablement（completed 2026-08-11）

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

完成计划：[0027-platform-acquisition-enablement.md](../.agent/plans/archive/0027-platform-acquisition-enablement.md)。

### 0028：Real OpenClaw and Real Platform E2E（当前）

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

**2026-08-11 当前检查点**：环境/工具基线、合法 generic 只读路径、进程级副作用门禁和 16 平台
readiness/用户文案审计已完成；所有平台仍为非 production-ready。文章已有两个公开候选等待用户明确
选择，Prepare 后仍须独立确认才允许 Start。当前环境没有注册/桥接/安装独立 session-manager，Step E
按精确恢复条件 blocked；真实网页物化/归档、合法平台认证恢复和最终文档验收仍未完成，不能由
`493/493` 全量 unittest 或 `8/8` stdio 子进程 E2E 替代。

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

### 主体架构阶段完成边界

0027–0029 全部通过后，主体架构阶段才结束。此时至少应满足：

- 0023 的真实 OpenClaw 阻塞项已经由 0028 的真实证据关闭；
- 检索不会因候选数量或标题表面相关而过早 Present，SemanticReview、Gap、StopDecision 的权威位置稳定；
- Planner/Skill 能准确区分 primary resource、representation、landing page 和 metadata；
- 真实 OpenClaw 能完成 Search → Inspect → Present → Select → Confirm → Acquire → Archive → Recover；
- benchmark 与 critical invariants 已成为后续修改的稳定 release gate；
- 公共 Tool 继续保持领域级入口，不因扩平台重新退化为脚本型 Tool 集合；
- Registry、Capability、runtime、Skill、Schema、测试和文档之间没有已知语义漂移。

达到该边界只表示“核心骨架可以稳定演进”，不表示产品能力、资料库体验或平台覆盖已经完成。

### 后续阶段一：产品能力成熟

0029 之后优先进入产品能力成熟阶段，而不是直接把主要精力切到远程化或多租户部署。
这一阶段延续 2026-08-08 归档路线中“稳定扩平台与持续质量优化”的原始目标，并补回用户侧
Library/Viewer 闭环。

#### 1. Platform Expansion

在不改变核心 Tool/authority 架构的前提下，逐步新增或强化：

- Platform Adapter：提高发现覆盖、来源质量和平台特征表达；
- Inspector：补强版本、Representation、availability、auth/policy 和可比较证据；
- Acquisition Provider：只为通过 capability/readiness/policy 门槛的平台增加真实获取能力；
- 平台能力必须继续走 Descriptor → Readiness → Resolution/Representation → Eligibility →
  Plan/Execution → exact Provider → Outcome，不为“多支持一个平台”建立旁路。

扩平台的完成标准不是代码存在，而是相应 benchmark、真实 E2E、readiness 与失败边界均可审计。

#### 2. Library / Viewer

Archive 成功不等于用户闭环完成。资料库必须从“存储资产”进一步演进为“按 Representation 正确打开和使用资源”。

优先目标包括：

- Representation-aware opening：Library 根据资源/Asset/Bundle 的真实表示选择正确打开方式；
- WebBundle：底层可继续保存 ZIP/Bundle，但用户默认打开 `index.html` 或受控 primary representation，
  不把 ZIP 文件本身当作最终阅读体验；
- PDF / EPUB / video / audio：按真实 MIME、role、container 和平台策略提供相应查看/播放/打开入口；
- Bundle / companion UX：主资源、字幕、封面、转写、附件等关系在资料库中可理解、可访问；
- Library Search 返回的关系和展示信息应服务用户选择与再次使用，而不是泄露底层路径或存储细节。

Viewer 是产品表现层，不得为了方便打开资源而绕过 Asset、Bundle、Archive、权限或路径安全边界。

#### 3. Retrieval Quality Iteration

0029 建立 benchmark 后，后续检索改进以 benchmark 为主回归入口：

- 提升 Top-N relevance、Gap/Clarify 准确率、Inspect efficiency 和来源多样性；
- 降低 Premature Present、Unnecessary Replan、Forbidden Display 和错误 capability promise；
- 新增平台、Adapter、Inspector、Provider 或 Skill 规则时同步增加相应 gold/negative cases；
- 不通过放宽 gold、增加随机重试、扩大 timeout 或静默 fallback 换取指标改善。

#### 4. Capability Readiness Expansion

随着真实平台验证积累，把平台从 `code_present` / experimental / auth_required 等中间状态逐步推进到
可审计的 `production_ready`。状态提升必须来自当期环境的真实证据，而不是 Registry 布尔值、fixture
通过或历史成功记录。

产品能力成熟阶段不预先绑定单一计划编号。进入某个明确工作包时，再从 evergreen 路线创建新的
`.agent/plans/<next-id>-*.md`，避免为了路线图先制造一批长期 pending 计划。

### 后续阶段二：平台化部署

只有在核心架构稳定、产品能力成熟路径明确后，才把主要开发重心转向教育平台的远程化和生产部署：

- 远程 Streamable HTTP MCP；
- 独立 session / credential service；
- remote storage 与运行目录治理；
- 网络隔离与受控出网；
- multi-tenant authentication / authorization；
- audit、quota、rate limit 与运维可观测性。

远程化不是当前本地 MVP 的默认前置，也不能通过扩大本地 Tool catalog 替代真实平台化设计。
平台化工作可以提前做必要预研，但不得以部署基础设施取代 Platform Expansion、Library/Viewer、
Retrieval Quality Iteration 或 Capability Readiness Expansion 的产品成熟工作。

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
