# 原生 OpenClaw + 本地 MCP 改造开发计划

## 1. 文档目的

本计划指导现有教育资源 Skill 套件在不依赖远端服务器的条件下，迁移到原生 OpenClaw。首个可运行版本采用本地 Python stdio MCP、SQLite 和隔离测试目录；待教育平台后端具备部署条件后，再迁移到远程 Streamable HTTP MCP，并按需增加薄 Tool Plugin。

本文同时记录未来产品路线和当前开发实现状态。截至 2026-08-08，当前分支的 active
contract 目录为 `mcp/education-resources/contracts/`，公共协议版本为 `1.0.0`、catalog
版本为 `1.3.0`，机器目录与运行时共 13 个工具（包含 `resource_browse_creator` 和
`resource_inspect`）。唯一入口
Skill、Python stdio MCP 和内部状态链已建立；教育资源 v1 契约已从工作区删除，历史迁移
说明只保留为参考。当前分支、HEAD、完整工具表和 Adapter 快照见
[当前架构事实快照](CURRENT_ARCHITECTURE.md)。
0019 Inspection Layer 与 0022 AssetBundle 已完成本地根验收；真实 OpenClaw 完整教育资源业务回合进入 0023。

当前执行队列：

- `0021 Acquisition Core/Web Materializer`：实现与本地根回归已完成；
- `0022 Multimodal AssetBundle`：实现与本地根回归已完成；
- `0023 E2E Hardening`：进程级离线 E2E 与重启恢复已完成；当前 macOS 缺少 `openclaw`，
  真实 doctor/probe 和默认 Agent 完整对话待外部环境就绪。

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
`education-resources`，通过 `resource_*` 过滤严格暴露 13 个领域工具。

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
- active 1.0.0 的资料库检索为了本地审计仍要求有效 `flow_id`；生产版应改为可信身份
  注入的 tenant-scoped 查询，不能让模型提交 `tenant_id` 或 `user_id`。

### 3.6 active 1.0.0 控制面与后续契约能力

`mcp/education-resources/contracts/` 是当前唯一 active contract，公共协议版本为 `1.0.0`、
catalog 版本为 `1.3.0`；历史教育资源 v1 已从工作区清理，迁移差异保留在
`contracts/compatibility.md` 和 Git 历史中。当前 active 1.0.0 已完成以下控制面边界：

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

0019 在不改变公共 `contract_version=1.0.0` 的前提下，以 catalog 兼容加法增加
`resource_inspect`。输入严格为 `contract_version`、`flow_id`、`resource_id`、
`idempotency_key`；服务端从当前 Flow 资源取得来源，不接受 URL、路径、批量 ID、检查深度或
凭据。Candidate、ResolvedResource、Representation、Resolution 分层；SQLite migration 3
独立保存 `resource_resolutions`，ResultSet 保持不可变。成功/partial 按
`resource_id + source_fingerprint + inspect-v1` 缓存，unresolved 仅保留审计并允许新幂等键重试；
`resource_flow_status` 返回 `current_resolutions` 安全摘要。Inspect 不下载、不归档、不返回
locator、文件字节或本地路径。

当前权威状态链严格为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job
         -> AssetBundle(服务端关系) -> Asset -> Archive
```

以下内容尚未进入 active 1.0.0，仍属于后续能力，文档、Skill 和运行时不得把它们描述成
已经由服务端保证：

- `direction_runs` 及多方向搜索的执行记录、聚合和确定性去重。
- `filter_execution` 及每项硬过滤的完整执行状态、失败原因和保证级别。
- 候选证据模型，包括来源可追溯证据、内容定位、使用门槛、安全提示和重要未知。

这些能力应在运行时需求、迁移和测试方案明确后，通过后续显式契约版本引入，不回填或
重新引入旧 v1 语义，也不能破坏当前已建立的展示、选择与下载绑定边界。

### 3.7 0018：内部 Resource Model 与 Platform Registry 当前实现

0018 在 MCP 内部新增 private Retrieval 层，不改变公共输入/输出模型。当前实现包括：

- `CandidateResourceInternal`、`ResourceIdentity`、`Representation` 等内部模型，以及按
  平台 native identity、ISBN、DOI、平台感知 canonical URL、弱指纹排序的 Identity Resolver。
- 保守 Candidate Dedup：保持首次顺序，后续重复候选只补充缺失事实；强身份冲突不自动合并，
  `limit` 在去重后应用。
- `mcp/education-resources/contracts/platforms/platform-registry.json` 的 16 平台 Registry：
  `generic` 加 15 个内置平台；generic 搜索后端和 15 个内置 Adapter 均挂载不可变、与 Registry
  一致的 `AdapterDescriptor`。
- `resource_search` 与 `resource_browse_creator` 共用服务端安全规范化、Identity/Dedup 和
  公共候选生成路径；逻辑资源先去重，最终公共 `resource_id` 仍由服务端随机生成。

0018 的兼容与验收边界固定如下：

- 公共 `contract_version=1.0.0`、当时 `catalog_version=1.2.0`、13 个 MCP Tool、现有公共资源
  输出和下载/归档语义保持不变；`resource_inspect` 是 0019 的兼容新增工具。
- SQLite 仍是 Flow、ResultSet、Presentation、Selection、Plan、Job、Asset、Archive 和
  Resolution 的权威状态；0018 不新增迁移，0019 使用 migration 3 独立保存 Resolution；
  内部 Identity 不是可提交的业务 ID。
- Registry 与 Adapter descriptor 只属于服务内部事实和一致性校验，登录态继续由独立的
  session registry 管理；历史/外部仅有 `platform_id` 的 stub 保持兼容。
- 0018 阶段的 inspect 能力关闭事实已由 0019 更新：当前 Registry 精确启用 generic、Bilibili、
  NLC、Anna/Libgen、Ximalaya、Zhihu、SmartEdu 七个平台；其余平台返回
  `FEATURE_NOT_SUPPORTED`。Adaptive Retrieval Loop 已在 0020 通过兼容字段、migration 4、
  immutable extend、SearchRun provenance、事实 coverage 与 Skill evaluator 实现。

### 3.8 0022：AssetBundle 多资产关系与部分结果

0022 保持公共 `contract_version=1.0.0`、13 个工具和既有 Job 生命周期状态；catalog 兼容加法
升至 `1.3.0`，不新增 Bundle Tool，也不增加 `partial` Job 状态。当前冻结的领域边界为：

- `Artifact` 是 Acquisition 的临时文件描述；`Asset` 是通过服务端校验后持久化的不可变内容；
  `AssetBundle` 是一个 Job × Resource 的有序关系，不等于 ZIP 或本地目录。
- 一个可用 Bundle 必须有且只有一个 `primary`；正式角色固定为 `primary`、`subtitle`、`cover`、
  `metadata`、`attachment`、`transcript`、`companion`。失败 BundleItem 的 `asset_id` 为空，
  不创建零字节假 Asset。
- `completion=complete|partial` 只表达结果完整度。已有 primary 且存在失败项才是 partial；
  没有 primary 为 failed；取消为 cancelled 并 quarantine，不自动重放网络副作用。
- 旧单文件 Provider 映射 primary，旧有序列表首项映射 primary、其余 attachment；SmartEdu
  保留视频/PDF/MP3/显式封面的来源关系和逐项失败，认证、策略阻断或取消终止整项获取。
- Archive 仍按 `asset_id` 逐 Asset 归档，Library 仍按 Asset 返回并恢复 Bundle 关系；模型不能
  提交或伪造 bundle_id、role、order、item_key。

数据层使用 migration 5 的 `asset_bundles`、`asset_bundle_items`、`asset_bundle_failures`，
历史 Asset 按 `jobs.asset_ids_json` 顺序回填 singleton Bundle，首项为 primary、其余为
attachment，不按文件名猜测。该迁移和 0022 跨层本地根验收均已完成。

## 4. 目标目录

```text
mcp/
└── education-resources/
    ├── README.md
    ├── pyproject.toml
    ├── contracts/                    # active 1.0.0 契约与 catalog
    │   └── platforms/                # 16 平台 Registry（机器事实）
    ├── src/education_resource_mcp/
    │   ├── adapters/
    │   ├── retrieval/                 # private resource model / identity / dedup
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

active contract 为 `mcp/education-resources/contracts/`，公共协议版本为 `1.0.0`、catalog
版本为 `1.3.0`。对 OpenClaw 公开的领域工具严格为以下 13 个，不为各平台 Adapter 额外暴露工具：

| 工具 | 副作用 | 主要返回 |
|---|---:|---|
| `resource_flow_start` | 写状态 | `FlowTask`、`flow_id`、当前阶段 |
| `resource_flow_status` | 无或更新时间戳 | 可恢复状态快照，不含确认令牌 |
| `resource_search` | 写结果集 | 不可变 `ResultSet`、候选、游标、错误摘要 |
| `resource_presentation_save` | 写展示状态 | `Presentation`、展示版本和展示资源顺序 |
| `resource_selection_save` | 写选择状态 | `Selection`、选择版本和选择摘要 |
| `resource_download_prepare` | 写下载计划，不下载 | `DownloadPlan`、大小/格式/风险摘要、确认要求 |
| `resource_download_start` | 启动任务 | `Job`、`job_id`、任务状态 |
| `resource_job_status` | 无或更新时间戳 | 进度、`Asset`/Bundle、结构化错误 |
| `resource_job_cancel` | 请求取消 | 最终或过渡任务状态 |
| `resource_archive` | 写资料库 | `Archive`、`asset_id`、归档元数据和可选 Bundle 投影 |
| `resource_library_search` | 无 | 已归档 Asset 列表和可选 Bundle 投影 |
| `resource_browse_creator` | 写结果集 | 创作者内容列表与部分失败摘要 |
| `resource_inspect` | 写 Resolution | 当前 Flow 单个资源的有界核验、可用性、Representation 与失败摘要 |

权威状态链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job
         -> AssetBundle(服务端关系) -> Asset -> Archive

CandidateResource -> ResolvedResource -> Representation -> Resolution
                                      ^
                                      resource_inspect
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
- Job `status` 不含 `partial`；`completion=complete|partial` 只表达已有 primary 时的 Bundle
  完整度。公共角色固定为 `primary`、`subtitle`、`cover`、`metadata`、`attachment`、
  `transcript`、`companion`。
- `cancelled` 不得被计为成功；临时文件必须清理或明确隔离为不可归档状态。
- `resource_archive` 仍只接受已完成 Job 产生的服务端 `asset_id`，不接受本地路径或 Bundle
  关系；Archive 以 Asset 为粒度，Library 通过 BundleItem 恢复关系。
- `resource_inspect` 只接受当前 Flow 的 `resource_id`，不下载、不归档，且不返回 locator、文件字节或本地路径。
- `direction_runs`、多方向聚合、`filter_execution`、完整硬过滤执行报告和候选证据模型
  不属于当前 13 个工具的 active 1.0.0 保证，留待后续显式契约版本。

## 6. 数据与状态

### 6.1 SQLite 作为权威状态

0019 通过 migration 3 新增 `resource_resolutions`；0020 的 migration 4 同时保存可恢复的
检索轮次、provenance、coverage 与私有 identity；0022 在当前工作树增加 migration 5，
建立 `asset_bundles`、`asset_bundle_items`、`asset_bundle_failures`。`resource_resolutions`
与 `resources/search_result_sets` 分表，保存 `resolution_id`、Flow/resource ownership、
profile、source fingerprint、状态、受控解析/检查/失败 JSON 和时间戳，并以
资源/profile/fingerprint 唯一约束实现 Resolution 缓存。ResultSet 快照不可被 Inspect 改写。

建议首版至少建立：

- `flow_tasks`
- `resources`
- `result_sets`
- `presentations`
- `selections`
- `download_plans`
- `jobs`
- `assets`
- `asset_bundles`
- `asset_bundle_items`
- `asset_bundle_failures`
- `resource_resolutions`
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

- active `mcp/education-resources/contracts/` 已提供领域不变量、41 个稳定错误码、
  `contract_version=1.0.0`、`catalog_version=1.3.0` 和 Draft 2020-12 输入/输出 Schema；
  机器目录、catalog meta-schema 与 Python runtime 当前都是 13 个工具；旧教育资源 v1
  文件不再作为工作区契约分发。
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
- 首批支持公开网页正文、公开文件直链，以及运行时已注册的 Bilibili、SmartEdu、喜马拉雅、
  Douyin、Anna's Archive 下载器；平台下载仍需合法会话、平台条款审查和逐平台真实验收。

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

### 阶段 5.1：资源核验与 Resolution — 实现与根验收完成（0019）

工作：

- 以 catalog 兼容加法新增 `resource_inspect`，保持公共 `contract_version=1.0.0`，
  0019 当时的 `catalog_version=1.1.0`；输入严格为 `contract_version`、`flow_id`、`resource_id`、
  `idempotency_key`，服务端从 Flow 资源取得来源。
- 建立 Candidate、ResolvedResource、Representation、Resolution 分层；SQLite migration 3
  新建 `resource_resolutions`，不改写 immutable ResultSet。
- 实现 `resource_inspect:{flow_id}` 幂等 scope、source fingerprint 缓存、resolved/partial
  跨键缓存、unresolved 新键重试和 `resource_flow_status.current_resolutions` 恢复摘要。
- 实现 generic 有界 GET、逐跳 SSRF/重定向校验、1 MiB 上限、MIME/魔数交叉验证，以及
  Bilibili、NLC、Anna/Libgen、Ximalaya、Zhihu、SmartEdu 六个平台 Inspector；其余平台
  返回 `FEATURE_NOT_SUPPORTED`。
- 保持下载 `prepare -> 用户明确确认 -> start` 两阶段不变；Inspect 不下载、不归档，
  不返回 locator、文件字节或本地路径。

当前实现：上述代码、Schema、Registry、服务注册和恢复输出已由 0019 工作包完成；实现者
报告的定向测试包括契约 4/4、存储 11/11、Inspection Core 7/7、Generic/Core 18/18、
两组平台 Inspector 各 26/26、服务接入 30/30（其中 Inspect Service 9/9）。当前阶段
最终根验收合并复跑 109/109 通过，同时通过源码编译、23 条本地 Markdown 链接、
16 平台中 inspect 7 开 9 关、catalog/runtime 13 tools 与差异检查。这些结果仍不等于
全量测试、真实平台网络或 OpenClaw doctor/probe 验收。

根验收：需运行契约、迁移、SSRF/重定向/大小/MIME、安全、服务、stdio、编译、链接和差异
检查，并确认旧 12 个工具的兼容性。未完成根验收前，不得将 0019 写成生产可用或完整闭环完成。

### 阶段 5.2：多模态 AssetBundle（0022）— 实现与本地根验收完成

工作：

- 将 `Artifact`、`Asset`、`AssetBundle`、`BundleItem` 和 `PartialFailure` 的领域边界固化为
  文档与服务端持久化语言；Bundle 是关系，不是 ZIP。
- 保持公共 `contract_version=1.0.0`、13 个工具和 Job 生命周期状态；catalog 升至 `1.3.0`，
  只追加可选的 `bundle_id`、`role`、`order`、`bundle_completion`、`completion`、`bundle_ids`
  和 `item_key` 输出。
- 使用 migration 5 建立 `asset_bundles`、`asset_bundle_items`、`asset_bundle_failures`；
  历史资产按 `jobs.asset_ids_json` 顺序回填 singleton Bundle，首项 primary、其余 attachment。
- 保留旧 DownloadProvider 和 SmartEdu 来源关系；失败项不创建假 Asset，Archive 继续按
  Asset 归档，Library 通过 BundleItem 恢复关系；取消 quarantine，重启不自动重放网络副作用。

当前结果与边界：catalog 1.3.0、migration 5、服务层多资产持久化、SmartEdu/旧 Provider、
Archive/Library 关系、取消 quarantine 与重启终结语义均已落盘。契约 Bundle 检查 3/3、
16 个 JSON Schema 校验和 education-resources 全量本地固定夹具回归 348/348 通过。真实杀
进程、真实平台网络、OpenClaw doctor/probe 和生产多租户隔离仍没有验收结论，转入 0023。

验收：视频、音频、图书、课程固定夹具覆盖 primary/companion 与课程部分失败；验证角色和顺序、
旧 Provider 兼容、幂等冲突、取消 quarantine、进程杀死恢复、Archive/Library 关系、Schema、
编译、链接和完整本地回归；这些本地结果不得写成生产就绪。

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
  `openclaw agent --local` 回合能够加载工作区、唯一入口 Skill 和当时的 11 个 MCP 工具，
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

当前机器已新增 4 个真实 MCP stdio 子进程 E2E：原始 JSON-RPC 调用 13 个公开工具，覆盖
多资源 Inspect/确认/partial Bundle、网页 ZIP、逐 Asset Archive/Library、AUTH_REQUIRED 后
由外部会话就绪并创建新 Job，以及下载中强杀进程后同 SQLite 重启并确认不自动重放。
4/4 E2E 和包含它们的全量本地回归 352/352 通过；测试数据全部位于临时目录且不访问网络。

真实联网测试必须低频、可控且符合目标站点访问边界；默认测试使用录制响应、Mock 或本地测试服务器。

### 历史 OpenClaw 验证快照（不代表当前 macOS）

历史 WSL 环境的默认 Node 曾切换为用户级 `24.18.1`，OpenClaw CLI 可以直接运行：

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
均成功；该历史快照早于 `resource_browse_creator` 接入，不能作为当前 12 工具
catalog 的实时验收，当前重新验证仍要求 `diagnostics=[]`。因此该 MCP CLI 挂起已解决，主要原因是跨 Windows/WSL 混用安装，
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

当前优先执行 `0023 E2E Hardening`。0022 已完成本地根验收，阶段 6 的 OpenClaw 完整业务
回合仍按其独立验收边界推进：

1. 让 Python 实现、SQLite 状态、唯一入口 Skill 和契约测试完整采用
   `mcp/education-resources/contracts/`；教育资源 v1 已不再随工作区分发。
2. 通过默认 Agent `main` 跑通
   “澄清 -> 搜索 -> ResultSet -> 实际展示 -> 选择 -> 确认 -> 下载 -> 归档 -> 检索”，
   验证完整状态链
   `FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> AssetBundle -> Asset -> Archive`。
3. 增加真实模型 Tool 调用断言、13 个公开工具的发现断言、绑定字段失配测试和会话恢复
   用例，确保失败可解释且不会绕过展示、选择或确认边界。
4. 在后续独立契约设计中再引入 `direction_runs`、多方向搜索聚合、`filter_execution`、
   完整硬过滤执行状态和候选证据模型；这些能力当前不属于 active 1.0.0。
5. 如需常驻 Gateway，再在不记录凭据的前提下完成客户端认证和设备配对。
6. 随后完成回滚演练和进程中断恢复，再扩大 Adapter 范围。
