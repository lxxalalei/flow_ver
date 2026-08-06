# 原生 OpenClaw + 本地 MCP 改造开发计划

## 1. 文档目的

本计划指导现有教育资源 Skill 套件在不依赖远端服务器的条件下，迁移到原生 OpenClaw。首个可运行版本采用本地 Python stdio MCP、SQLite 和隔离测试目录；待教育平台后端具备部署条件后，再迁移到远程 Streamable HTTP MCP，并按需增加薄 Tool Plugin。

本文同时记录未来产品路线和当前开发实现状态。截至 2026-08-03，本地 Python
stdio MCP、active contract `mcp/education-resources/contracts/v2/`（`2.0.0`）、
唯一入口 Skill、OpenClaw 专用 Agent/MCP 注册和 MCP doctor/probe 已完成；v1 已冻结，
仅保留为迁移参考。2026-08-06 已删除工作区中的教育资源 v1 契约，当前仅保留 v2。
`glm-req/glm-5.2` Provider probe 和最小真实 Agent 回合也已通过。
完整教育资源业务回合仍未完成验收。

当前 macOS 检查环境尚未安装 `openclaw`，且项目 Python 依赖未安装；历史 WSL
OpenClaw doctor/probe 结果仍保留在本文件，不能当作本机当前环境的实时验证。

当前实现是本地开发 MVP，不代表高风险平台、多租户安全隔离或教育平台生产部署
已经完成。

本项目采用目标优先而不是旧实现优先的改造方式。旧七个 Skill 和六阶段流水线只用于
提取经过实践形成的教育语义规则、案例与回归基线，不构成兼容承诺。active Skill、MCP
契约和内部状态模型可以为了最终自然语言体验、安全边界和可维护性被重构或重新设计。

任务模型由三个独立部分组成：当前对话者 `user_role`、资源服务对象
`resource_target`，以及用户明确提出的 `constraints`。前两项的取值都是孩子或家长，
可以暂时未知且不能相互推导。其余会影响结果的用户明示条件进入普通约束。年龄和年级
仅作为用户主动提供的可选搜索条件，不得成为
默认澄清项。教材同步任务缺少年级或册次时，可以澄清资源范围。

## 2. 当前基线

当前已经形成 active 与 legacy 两个边界：

- 新路径：`learning-resource-flow -> education-resources MCP -> SQLite/受控文件`。
- Legacy 快照：原有 7 个 Skill 和阶段脚本完整保存在
  `legacy/skill-pipeline-v1/skills/`，只用于审计、显式回滚和迁移参考，不参与正常运行。

OpenClaw 默认 Agent `main`（名称 `education-resources`）绑定本工作区，Skill
allowlist 只包含 `learning-resource-flow`，因此只有一个用户入口。MCP 注册名为
`education-resources`，通过 `resource_*` 过滤严格暴露 11 个领域工具。

Legacy 中的 7 个 Skill 组成六阶段业务流程：

```text
Intent -> Search Plan -> Platforms -> Selector -> Downloader -> Library Manager
```

当前优势：

- 已有较完整的阶段拆分、Schema、验证器和多个平台适配器。
- 搜索、下载和归档已有 Python 实现，可作为 MCP 服务内部实现的迁移来源。
- 下载层已经包含部分文件格式、网络访问和降级校验。

迁移前必须解决或以测试锁定的风险：

- 取消选择后仍可能形成下载产物。
- 下载执行参数需要在服务端再次校验，不能信任模型生成的计划。
- 任意二进制、脚本路径或本地绝对路径不能成为 Tool 参数。
- 所有下载路径都必须真正执行 `max_bytes`、SSRF、重定向和格式约束。
- 长下载需要异步任务、幂等、取消和恢复。
- Selector 展示集合、用户选择和恢复状态需要服务端持久化。
- 资料库索引、去重、事务和维护能力需要和文档保持一致。

## 3. 技术决策

### 3.1 首版使用 stdio MCP

stdio MCP 不要求远端服务器。OpenClaw 启动本地 Python 子进程，通过 stdin/stdout 交换 MCP 消息：

```text
OpenClaw Gateway
  -> local stdio
education-resource-mcp Python process
  -> SQLite + isolated files + existing adapters
```

它提供清晰的进程与协议边界，但不是安全沙箱：MCP 子进程仍使用当前操作系统用户权限。因此必须限制工作目录、环境变量、网络出口和可写目录。

### 3.2 首版不开发 Tool Plugin

原生 Plugin 与 OpenClaw Gateway 同进程，适合审批、Hook、平台身份和 UI 集成，不适合运行爬虫、视频下载、转码或长任务。首轮试验优先验证 MCP 业务闭环；需要深度平台集成时再增加薄 Plugin。

### 3.3 Skill 与服务分工

| 层 | 负责 | 不负责 |
|---|---|---|
| Skill | 教育需求理解、澄清判断、资源形态与搜索策略、候选审查、交互、调用工具、解释结果、恢复引导 | 下载执行、数据库事务、路径拼接、伪造状态 |
| MCP | Flow 状态、搜索、选择、下载任务、归档、错误码 | 自由对话和面向用户的解释 |
| Adapter | 具体来源访问与归一化 | 暴露任意脚本入口或决定用户权限 |
| OpenClaw Plugin（未来） | 审批、Hook、平台身份、展示 | 真实搜索下载和重任务 |

### 3.4 OpenClaw 本地运行版本

本机 `/usr/bin/node` 为 `22.22.1`，不满足当前 OpenClaw 的最低要求 `22.22.3`。
2026-07-30 已从 Node.js 官方发行包安装最新兼容 LTS `24.18.1` 到用户级目录，并由
`/home/admin_quanxiao/.local/bin/node` 作为默认命令。Node 26 不在当前 OpenClaw
`2026.7.1-2` 的兼容范围内。

同日已通过 npm 官方注册表在 WSL 独立安装 OpenClaw `2026.7.1-2`，默认命令为
`/home/admin_quanxiao/.local/bin/openclaw`。Windows 的 OpenClaw 安装继续保留，
但本工作区不再从 WSL 跨环境调用 Windows npm 目录中的包。

```bash
node --version
openclaw --version
```

该用户级安装不携带或记录 Gateway token、provider key 或任何其他凭据。

本地默认模型使用 Claude Code 当前使用的 `glm-req/glm-5.2`：OpenClaw Provider
采用 `anthropic-messages` 协议，Provider 内模型 ID 为 `glm-5.2`，专用 Agent 的
完整模型引用为 `glm-req/glm-5.2`。凭据不复制进仓库或 `openclaw.json`，而是通过
File SecretRef 从 `~/.claude/settings.json` 的 `/env/ANTHROPIC_AUTH_TOKEN` 读取。
当前模型元数据采用保守值：`contextWindow=200000`、`contextTokens=180000`、
`maxTokens=32768`，后续应以服务端正式能力声明为准。

### 3.5 本地 MVP 与生产边界

- 当前 stdio MCP 的 Job runner 使用进程内线程池。服务重启会把未完成任务明确
  终结并隔离资产，但不会跨进程继续执行；生产版必须迁移到常驻 MCP 服务和持久
  Worker/队列。
- 当前确认令牌用于约束 `prepare -> start` 顺序，但令牌会经过模型上下文，不能单独
  证明真实用户审批。生产版应由平台 approval record 或薄 Plugin 的工具调用审批
  注入不可伪造的授权结论。
- active v2 的资料库检索为了本地审计仍要求有效 `flow_id`；生产版应改为可信身份
  注入的 tenant-scoped 查询，不能让模型提交 `tenant_id` 或 `user_id`。

### 3.6 active v2 控制面与后续契约能力

`mcp/education-resources/contracts/v2/` 是当前唯一 active contract，版本为 `2.0.0`；
历史 v1 已从工作区清理，迁移差异保留在 `contracts/v2/compatibility.md` 和 Git 历史中。
v2 已完成以下控制面边界：

- `FlowTask` 使用目标导向结构：必填 `goal.topic`，可选 `goal.outcome`；`user_role` 与
  `resource_target` 独立且均可未知；其他用户明示条件进入 `constraints` 数组。
- `resource_search` 返回并持久化不可变 `ResultSet`；搜索结果不再直接等同于模型已向
  用户展示的候选。
- `resource_presentation_save` 以 `result_set_id + displayed_resource_ids` 保存实际
  `Presentation`；`resource_selection_save` 以
  `presentation_id + presented_version + selected_positions` 保存 `Selection`，确保用户
  只能按真实展示顺序选择候选。
- 下载准备、启动和状态恢复绑定 `presentation_id + presented_version` 与
  `selection_version + selection_digest`，避免展示或选择变化后复用旧计划。
- `resource_flow_status` 提供可恢复的权威状态快照，但不返回确认令牌等敏感能力。

当前权威状态链严格为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive
```

以下内容尚未进入 active v2，仍属于后续能力，文档、Skill 和运行时不得把它们描述成
已经由服务端保证：

- `direction_runs` 及多方向搜索的执行记录、聚合和确定性去重。
- `filter_execution` 及每项硬过滤的完整执行状态、失败原因和保证级别。
- 候选证据模型，包括来源可追溯证据、内容定位、使用门槛、安全提示和重要未知。

这些能力应在运行时需求、迁移和测试方案明确后，通过后续显式契约版本引入，不回填或
重新引入旧 v1 语义，也不能破坏 v2 已建立的展示、选择与下载绑定边界。

## 4. 目标目录

```text
mcp/
└── education-resources/
    ├── README.md
    ├── pyproject.toml
    ├── contracts/v2/                  # active 2.0.0 契约
    ├── src/education_resource_mcp/
    │   ├── adapters/
    │   ├── config.py
    │   ├── downloader.py
    │   ├── errors.py
    │   ├── server.py
    │   ├── service.py
    │   ├── jobs.py
    │   ├── policy.py
    │   ├── search.py
    │   ├── storage.py
    └── tests/
skills/
└── learning-resource-flow/
    ├── SKILL.md
    ├── references/
    └── examples/
legacy/
└── skill-pipeline-v1/skills/       # 旧六阶段快照，不参与正常运行
.openclaw-test/                     # 隔离测试数据，不是持久注册数据
```

顶层 `skills/` 只保留唯一入口。旧 Skill 已移到 legacy，但在完成对等验收和回滚演练前
不删除其代码与测试。

## 5. 领域工具契约

active contract 为 `mcp/education-resources/contracts/v2/`，契约版本 `2.0.0`。对
OpenClaw 公开的领域工具严格为以下 11 个，不为各平台 Adapter 额外暴露工具：

| 工具 | 副作用 | 主要返回 |
|---|---:|---|
| `resource_flow_start` | 写状态 | `FlowTask`、`flow_id`、当前阶段 |
| `resource_flow_status` | 无或更新时间戳 | 可恢复状态快照，不含确认令牌 |
| `resource_search` | 写结果集 | 不可变 `ResultSet`、候选、游标、错误摘要 |
| `resource_presentation_save` | 写展示状态 | `Presentation`、展示版本和展示资源顺序 |
| `resource_selection_save` | 写选择状态 | `Selection`、选择版本和选择摘要 |
| `resource_download_prepare` | 写下载计划，不下载 | `DownloadPlan`、大小/格式/风险摘要、确认要求 |
| `resource_download_start` | 启动任务 | `Job`、`job_id`、任务状态 |
| `resource_job_status` | 无或更新时间戳 | 进度、`Asset`、结构化错误 |
| `resource_job_cancel` | 请求取消 | 最终或过渡任务状态 |
| `resource_archive` | 写资料库 | `Archive`、`asset_id`、归档元数据 |
| `resource_library_search` | 无 | 已归档资产列表 |

权威状态链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive
```

核心约束：

- 除 `resource_flow_start` 外，每次调用携带有效 `flow_id`；结果集、展示、选择、资源、
  计划、任务、资产和归档使用服务端生成的稳定 ID。
- `resource_search` 产生不可变 `ResultSet`；`resource_presentation_save` 只接受
  `result_set_id + displayed_resource_ids`，并保存实际展示顺序。
- `resource_selection_save` 只接受
  `presentation_id + presented_version + selected_positions`，不得直接提交任意资源 ID
  绕过展示边界。
- `resource_download_prepare`、`resource_download_start` 和任务状态恢复共同绑定
  `presentation_id + presented_version + selection_version + selection_digest`；任何展示或
  选择变化都使旧绑定失效。
- `resource_download_start` 只接受未过期的 `plan_id`、确认令牌和幂等键；确认令牌不得由
  `resource_flow_status` 返回。
- Job 状态机至少包含 `queued`、`running`、`cancelling`、`succeeded`、`failed`、`cancelled`。
- `cancelled` 不得被计为成功；临时文件必须清理或明确隔离为不可归档状态。
- `resource_archive` 只接受已完成 Job 产生的 `asset_id`，不接受本地路径。
- `direction_runs`、多方向聚合、`filter_execution`、完整硬过滤执行报告和候选证据模型
  不属于当前 11 个工具的 v2 保证，留待后续显式契约版本。

## 6. 数据与状态

### 6.1 SQLite 作为权威状态

建议首版至少建立：

- `flow_tasks`
- `resources`
- `result_sets`
- `presentations`
- `selections`
- `download_plans`
- `jobs`
- `assets`
- `schema_migrations`
- `archive_contents`
- `archive_entries`
- `archive_secondary_domains`
- `archive_topics`
- `archive_purposes`
- `archive_grade_levels`
- `archive_curriculum_versions`
- `archive_tags`
- `idempotency_keys`
- `audit_events`

`archive_contents` 表示按 SHA-256 和文件大小去重的物理内容；`archive_entries` 表示 Asset
到归档内容的可追溯关系。分类标量保存在 Archive 主记录，多值分类进入关联表，不能依赖
`metadata_json LIKE` 完成结构化过滤。SQLite 迁移只做幂等前向升级，不移动或批量重命名
用户已有资料文件。

旧 Stage 1–6 JSON 在兼容期可以作为导入导出格式，但不能继续承担安全边界。模型不得直接写数据库或权威 JSON。

### 6.2 文件边界

- 临时下载写入单个 Job 专属目录。
- 校验通过后原子移动到受控资产区。
- 失败和取消任务不得留下可被归档的最终资产记录。
- 所有路径由服务端从 ID 解析；客户端不得提交绝对路径或 `..`。

### 6.3 当前持久开发路径

OpenClaw 注册使用用户级持久 venv 和数据目录，避免 `/tmp` 生命周期和仓库运行产物
污染：

```text
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv/
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-data/
└── database.sqlite
```

MCP 进程配置为：

```text
command: /home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv/bin/python
args:    -m education_resource_mcp.server
cwd:     /home/admin_quanxiao/projects/quanxiao/collector_flow_ver/mcp/education-resources
data:    /home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-data
```

仓库内 `.openclaw-test/` 只保留给隔离测试；生产环境必须另行配置受控存储和数据库。

## 7. 安全与策略

### 7.1 网络

- 仅允许 `http` 和 `https`。
- DNS 解析前后都检查目标地址，阻断 loopback、私网、链路本地、保留地址和云元数据。
- 每次重定向重新验证协议、主机和 IP。
- 平台 Adapter 使用显式域名策略；通用网页保存采用更严格的 SSRF 规则。

### 7.2 下载

- 响应头和实际流式字节都执行 `max_bytes`。
- 设置连接、读取、单次任务和整体超时。
- 使用临时文件，完成格式与内容校验后再提交。
- 不绕过验证码、付费墙、DRM、登录限制或站点明确禁止的访问控制。
- 第一批只接入公开、低风险、已具备测试的来源。

### 7.3 审批与审计

- `prepare` 返回来源、预计大小、格式、降级级别和风险。
- OpenClaw 在调用 `start` 前取得用户明确确认。
- 所有副作用工具记录用户/会话标识、参数摘要、幂等键、结果和错误码；日志不得包含凭据。

## 8. 分阶段开发路线

### 阶段 0：工作区初始化 — 已完成

交付物：

- 根级 `AGENTS.md`
- `README.md`
- `.agent/` 计划与汇报规范
- 本开发计划

验收：工作区约束可发现，初始化计划标记为 `completed`，新增文档链接有效，未改写现有 Skill。

### 阶段 1：基线固化 — 部分完成

工作：

- 保存完整 `git status` 与既有修改范围，确认 `.gitignore` 删除意图。
- 统一可重复的测试入口，记录 Python 和外部依赖。
- 为已知高风险行为补回归测试：取消后下载、参数二次校验、`max_bytes`、SSRF、重定向、选择恢复和归档事务。
- 明确首版允许的平台和必须暂缓的平台。

当前结果：新 MCP 服务和入口 Skill 已建立可重复单元/协议测试，取消后下载、
幂等、展示集合、路径逃逸、SSRF、重定向和归档状态已有保护用例。原有全部 Skill
与平台 Adapter 的统一基线、`.gitignore` 删除意图和完整工作树恢复方案仍需收尾。

验收：离线测试可一条命令运行；关键风险均有失败用例或已通过的保护用例；工作树基线可恢复。

### 阶段 2：MCP 骨架与契约 — 已完成（本地 MVP）

工作：

- 建立 Python 包、stdio MCP server、配置加载和结构化日志。
- 定义工具 Schema、错误模型、ID 规则和协议版本。
- 建立 SQLite migration、repository 层和测试夹具。
- 实现 `resource_flow_start`、健康检查和只读状态查询。

当前结果：

- active `mcp/education-resources/contracts/v2/` 已提供领域不变量、41 个稳定错误码、
  严格 11 个工具目录和 Draft 2020-12 输入/输出 Schema；契约版本为 `2.0.0`。
  v2 延续历史 v1 中仍有效的错误语义，并追加控制面与任务终态错误码；旧 v1 文件不再
  作为工作区契约分发。
- Python stdio MCP、SQLite repository、配置、结构化业务错误和协议 smoke test
  已实现。
- MCP initialize、tools/list 和 tools/call 测试通过；运行数据写入独立 data 目录，
  未把凭据写入仓库。

验收：本地进程可启动；工具列表和 Schema 稳定；并发启动不会破坏 SQLite；无凭据写入仓库。

### 阶段 3：搜索与选择闭环 — 已完成（首批 MVP）

工作：

- 包装现有搜索规划与低风险 Adapter。
- 归一化候选并持久化不可变 `ResultSet`。
- 实现 `resource_search`、`resource_presentation_save` 与 `resource_selection_save`。
- 支持分页、部分失败、重试上限和 Flow 恢复。

当前结果：已包装 Generic 搜索兼容层，并接入 Bilibili、知乎、SmartEdu、CCTV、NLC、
喜马拉雅、网易公开课、微信、微博等平台 Adapter；以
`resource_search -> ResultSet -> resource_presentation_save -> Presentation -> resource_selection_save -> Selection`
建立搜索、实际展示和位置选择的权威边界；同时保留分页、部分失败结构和重启后 SQLite
恢复。平台是否可用仍取决于真实来源、授权状态和逐平台验收，不能把 Adapter 已接入
描述成所有平台的生产可用保证。

验收：搜索结果可重放；用户只能选择本轮展示集合；重启 MCP 后选择状态不丢失；单个平台失败不破坏整个 Flow。

### 阶段 4：下载准备、异步任务与取消 — 已完成（首批 MVP）

工作：

- 实现 `resource_download_prepare`、`resource_download_start`、状态和取消工具。
- 服务端重新执行来源、Selection、策略、大小和路径验证。
- 建立 Job worker、幂等和临时文件提交协议。
- 首批支持公开网页正文、公开文件直链，以及已接入的 Bilibili、SmartEdu、喜马拉雅下载器；
  平台下载仍需合法会话和逐平台真实验收。

当前结果：已实现 prepare/confirmation/start 两阶段、幂等 Job、状态查询、取消、
受控临时目录、公开 HTTP(S) 下载和资产提交；网络与路径策略测试覆盖私网/保留地址、
混合 DNS、重定向、协议、凭据 URL、路径穿越和符号链接逃逸。完整进程中断恢复与
更多真实来源仍需进一步验收。

验收：未确认不能下载；重复 start 不产生重复任务；取消后没有可归档资产；进程重启后可恢复或明确终结任务；所有网络安全测试通过。

### 阶段 5：学习资料库归档 — 已完成（0016 foundation）

工作：

- 建立唯一 `learning-v1` 分类注册表、十个稳定机器领域 ID 和固定中文目录映射。
- 用版本化嵌套分类统一 Skill、JSON Schema、Python 模型、SQLite 索引和工具文档；兼容读取
  旧平铺字段与旧中文领域，无法可靠映射时进入 `needs_review` 并保留原始元数据。
- 建立 schema version 2 的幂等前向迁移、内容实体、归档状态和多值关联索引。
- 实现 Asset 校验、权威命名、路径与符号链接安全、跨 Asset 内容去重、
  `pending -> ready` 文件提交和内部对账恢复。
- 实现 `resource_archive` 与 `resource_library_search`；结构化字段精确过滤，关键词受控模糊
  查询，并使用稳定 keyset 排序和签名不透明 cursor 分页。

此前本地 MVP 已做到只接受 `job_id` 和 `asset_id`、同 Asset 幂等归档及
cancelled/failed Asset 不可归档，但审计发现它仍使用旧成长领域、按 Asset 而非内容去重、
先落正式文件后写索引、用 `metadata_json LIKE` 过滤、拒绝已声明 cursor，并会返回绝对路径。
计划 `0016-learning-resource-archive-foundation.md` 已替换这些行为，并完成迁移、故障注入、
精确检索、分页、路径安全、Schema 一致性和完整 MCP 回归。本次 macOS 环境没有
`openclaw` 命令，阶段 6 的进程级复验仍按其独立边界处理，不影响本阶段本地 foundation
完成状态。

验收：十个领域及中文目录跨层一致；新旧数据库均可幂等打开；不同 Asset 的相同内容不重复
复制；索引和文件提交可对账恢复；结构化过滤没有子串误匹配；分页无重复或遗漏；只返回
ready 且文件存在的记录和安全相对路径；任意路径输入被拒绝；完整教育资源 MCP 测试无回归。

### 阶段 6：OpenClaw 原生联调 — 部分完成

工作：

- 在本机注册 stdio MCP。
- 通过 MCP doctor/probe 验证工具发现和调用。
- 改造 `learning-resource-flow`，只调用 MCP 工具。
- 把 Intent、Search、Selector 规则逐步收敛到入口 Skill 的 references。
- 跑通“澄清 -> 搜索 -> 展示 -> 选择 -> 确认 -> 下载 -> 归档”。

当前结果：

- 已把默认 Agent `main` 配置为 `education-resources`，workspace 指向本仓库，Skill allowlist
  只包含 `learning-resource-flow`。
- 已注册 stdio MCP `education-resources`，使用持久 venv/data 路径和
  `resource_*` 工具过滤。
- 使用 Node 24.18.1 启动 OpenClaw 后，`mcp doctor education-resources --probe`
  与 `mcp probe education-resources --json` 已成功，证明 MCP 进程、工具发现和协议
  调用可用。
- 已配置 `glm-req/glm-5.2` 为默认模型。模型 Provider probe 返回成功，最小
  `openclaw agent --local` 回合能够加载工作区、唯一入口 Skill 和 11 个 MCP 工具，
  由目标模型返回预期最终文本，未使用 fallback。
- 唯一入口 Skill 已从用户结果重新构建需求理解、澄清、发现策略、候选判断和响应
  references；没有恢复旧 Intent/Search/Selector Skill、Stage JSON 或模型评分文件。
- 完整业务回合仍未完成：尚需逐步验证模型实际调用 MCP 完成澄清、搜索、展示、
  选择、确认、下载、归档和检索，因此当前只证明模型与工具上下文可用，不能宣称
  阶段 6 的完整端到端验收通过。

验收：OpenClaw 中完整闭环成功；模型无法传入脚本、二进制或任意路径；会话恢复后 Flow 状态一致；失败可解释并可继续。

### 阶段 7：Legacy 证据收敛与回滚演练 — 部分完成

工作：

- 从旧流程提取仍有价值的语义原则和判别性案例，不追求旧 Stage 契约对等。
- 取消内部 Skill 的用户可发现性，保留只读历史快照和显式回滚证据。
- 编写迁移、回滚和数据导入导出说明。

当前结果：顶层 `skills/` 已物理收敛为唯一入口 `learning-resource-flow`，active Skill
只保留 MCP 对话编排和响应规范；旧七 Skill 完整移动到
`legacy/skill-pipeline-v1/skills/`。Generic 搜索 Adapter 已抽入 MCP 包，active MCP
不再运行时依赖 legacy。需求、搜索和候选语义已按最终用户结果重新提炼进 active Skill；
数据导入导出和实际回滚演练尚未完成。

验收：判别性语义回归通过；回滚可在不丢失 Flow/资产数据的情况下完成；只有一个用户入口 Skill。

### 阶段 8：教育平台化 — 未开始

工作：

- MCP 迁移到 Streamable HTTP 和平台身份认证。
- 搜索、下载、对象存储、配额、审计迁移到平台服务。
- 按需增加薄 Plugin，承担审批、Hook、身份注入和 UI 展示。
- 按不互信用户设计 Gateway 隔离，不能依赖 session/agent 作为租户安全边界。

验收：租户、凭据、存储、网络和审计隔离通过安全评审；学生前端不接触 Gateway operator token；大文件不经过 Agent transcript。

## 9. 测试策略

### 单元测试

- Schema、ID、状态机、幂等和数据库事务。
- URL/IP 校验、重定向、大小限制和内容类型。
- 每个 Adapter 的标准输入输出和错误映射。

### 集成测试

- stdio MCP 启动、工具发现和请求响应。
- SQLite + Job worker + 文件提交。
- 进程中断、恢复、取消和重复请求。

### 端到端测试

- OpenClaw 完整资源流程。
- 用户拒绝下载、修改选择、取消任务和恢复会话。
- 单个平台失败、网络超时、超限文件和无效内容。

真实联网测试必须低频、可控且符合目标站点访问边界；默认测试使用录制响应、Mock 或本地测试服务器。

### 当前 OpenClaw 验证快照

当前默认 Node 已切换为用户级 `24.18.1`，OpenClaw CLI 可以直接运行：

```bash
node --version
openclaw --version
```

已成功完成的验证：

```bash
openclaw mcp doctor education-resources --probe

openclaw mcp probe education-resources --json

openclaw models status --agent main --probe \
  --probe-provider glm-req --probe-timeout 30000 --probe-max-tokens 4 --json

openclaw agent --agent main --local \
  --session-key glm-config-smoke-01 \
  --message "只回复 GLM_OPENCLAW_OK，不调用任何工具。" --timeout 60 --json
```

模型 probe 已返回 `status=ok`；最小 Agent 回合由 `glm-req/glm-5.2` 返回
`GLM_OPENCLAW_OK`，执行成功且未使用 fallback。该回合证明真实模型可加载当前
工作区、入口 Skill 和 MCP 工具 Schema，但不替代完整资源业务流程验收。

`--local` 模式曾提示 Gateway secrets RPC 未配对，随后按设计使用本地 SecretRef
完成调用。若后续改为通过常驻 Gateway 使用，应单独完成 Gateway 客户端认证和设备
配对。排障记录不得包含 token、key、Cookie 或认证数据库内容。

2026-07-29 至 2026-07-30 早期复跑时，WSL 使用 Linux Node 加载 Windows npm
目录中的 OpenClaw，`mcp status/doctor/probe` 曾出现无输出挂起。升级 Node 本身没有
解决问题。改为 WSL 原生安装后，`agents list`、`mcp status --verbose`、
`mcp doctor education-resources --probe` 和 `mcp probe education-resources --json`
均成功；active v2 的工具发现口径已更新为严格 11 个工具，验收要求
`diagnostics=[]`。因此该 MCP CLI 挂起已解决，主要原因是跨 Windows/WSL 混用安装，
而不是 Python stdio MCP 协议回归。

## 10. 回滚策略

- 每一阶段在独立、可审查的变更中完成，不把 Skill 收敛与服务重写混为一次提交。
- Legacy 保留为仓库外备份和只读历史快照；只有真实数据迁移需要时才设计显式导入工具，
  active Runtime 不承担旧 Stage JSON 兼容义务。
- 新入口切换前保留旧 Skill 代码和测试，不直接删除。
- 数据库迁移必须可前向重跑；破坏性 Schema 变更先备份测试数据并提供迁移脚本。
- 新 MCP 调用失败时可以回到只搜索/只展示来源，不得静默回退到不受控脚本下载。

## 11. 暂缓范围

首轮不承诺以下能力：

- 绕过认证、验证码、付费、DRM 或站点访问限制。
- 将 Douyin、Weibo、SmartEdu、百度文库、Anna's Archive 等高风险或授权边界未明确的平台作为首批生产来源。
- 在 Native Plugin 内运行实际下载、解密、转码或长任务。
- 多租户共享一个无隔离的 OpenClaw Gateway。
- 在没有对象存储和平台后端前模拟正式生产资源库。

## 12. 下一项建议任务

优先完成 active v2 控制面的运行时收敛和阶段 6 完整业务回合验收：

1. 让 Python 实现、SQLite 状态、唯一入口 Skill 和契约测试完整采用
   `mcp/education-resources/contracts/v2/`；教育资源 v1 已不再随工作区分发。
2. 通过默认 Agent `main` 跑通
   “澄清 -> 搜索 -> ResultSet -> 实际展示 -> 选择 -> 确认 -> 下载 -> 归档 -> 检索”，
   验证完整状态链
   `FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive`。
3. 增加真实模型 Tool 调用断言、11 个公开工具的发现断言、绑定字段失配测试和会话恢复
   用例，确保失败可解释且不会绕过展示、选择或确认边界。
4. 在后续独立契约设计中再引入 `direction_runs`、多方向搜索聚合、`filter_execution`、
   完整硬过滤执行状态和候选证据模型；这些能力当前不属于 active v2。
5. 如需常驻 Gateway，再在不记录凭据的前提下完成客户端认证和设备配对。
6. 随后完成回滚演练和进程中断恢复，再扩大 Adapter 范围。
