# Education Resources MCP

`education-resources` 是工作区唯一 active 的教育资源执行服务。它是 Python stdio MCP，负责 ResultSet、Presentation、Selection、Resolution、Plan、Job、Outcome、Asset/AssetBundle 和资料库归档的服务端业务状态；它不是用户入口 Skill，也不是登录凭据管理器。

当前公共接口由机器契约定义：`contract_version=1.0.0`、`catalog_version=1.7.0`，工具集合和每个工具的输入/输出以 [`contracts/tool-catalog.json`](contracts/tool-catalog.json) 与 [`contracts/schemas/`](contracts/schemas/) 为准。Skill 负责需求理解、候选审查、实际展示、用户确认和结果解释；独立 `session-manager` 负责合法登录与会话保存。

## 当前服务边界

业务主链：

```text
FlowTask
  -> ResultSet
  -> Presentation
  -> Selection
  -> Resolution / Representation
  -> AcquisitionPlan
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> AssetBundle / Asset
  -> Archive
```

这些对象是**服务端业务事实**，不是要求 Agent 逐层搬运的公共协议对象。

- Search 和 creator browse 产生候选 ResultSet；只有 Skill 实际展示后保存的 Presentation 才能被选择。
- `resource_inspect` 产生/刷新完整 Resolution 与 Representation；Public Tool 只暴露会改变用户/Agent 决策的 availability、Representation 与失败事实。
- `resource_download_prepare` 基于当前 Selection + fresh Representation 选择明确的 `scope / strategy / provider`，只准备计划，不下载。
- 下载必须经过 `prepare -> 用户明确确认 -> start`。Start 再次读取当前 Resolution，确认 Representation 和 exact Provider route 没有漂移，然后创建 Job。
- Router 只执行 Plan 指定的 `(provider_id, provider_version)`，失败不会静默换 generic Provider。
- Job 是异步的；状态、取消、Outcome、Asset 和 Archive 由 MCP 服务端产生，模型不能伪造这些业务 ID 或执行结果。
- 检索结果是否“够好”、还缺什么、要不要继续搜，由 Skill/Main Agent 根据用户目标判断，不由 ResultSet 状态机替代。

## 0055 Public MCP Surface Simplification

OpenClaw 不再需要在相邻 Tool 调用之间搬运大批内部版本和摘要字段。完整状态仍由 Service/Store 保存并校验，Public MCP 只暴露下一步所需事实。

当前主要调用形态：

```text
resource_search(flow_id, search_tasks, mode?, filters?, limit?)
  -> compact candidates + failures

resource_presentation_save(flow_id, displayed_resource_ids)
  -> server binds current ResultSet

resource_selection_save(flow_id, selected_positions)
  -> server binds current Presentation/version

resource_inspect(flow_id, resource_id)
  -> compact availability + representations + failures

resource_download_prepare(flow_id, options?)
  -> server binds current Selection/Presentation/digest

resource_download_start(flow_id, plan_id, confirmation_token)
  -> Job

resource_job_status(flow_id, job_id)
  -> compact progress + ready assets + failures
```

`resource_flow_status` 现在是**紧凑恢复摘要**，不是全量状态转储。它不会重新发送完整 ResultSet、Resolution evidence、selection/plan digest 或 execution route；只有在上下文丢失、flow 状态不确定时才需要调用。

普通 Search 默认 `limit=8`，候选摘要最多公开 600 字并用 `summary_complete` 标明是否完整；Creator Browse 保留请求范围内候选清单，但不回灌逐条长摘要。被移出 Agent-facing 输入/输出的内部字段并没有从数据库或一致性校验中删除。详细兼容边界见 [`contracts/compatibility.md`](contracts/compatibility.md)。

## 0037 获取简化

当前 Active 获取路径已不再把以下对象作为持久业务状态：

- Capability Descriptor binding；
- Deployment Readiness Snapshot；
- Eligibility Decision；
- `authority_digest`；
- `plan_binding_digest` / `execution_binding_digest`；
- `outcome_digest`。

Provider 能力改为轻量 `ProviderSpec` + Start 前运行时检查。`source_fingerprint` 只用于资源身份与 Resolution cache 关联，不是执行凭证。

当前实现入口：

```text
server.py
  -> service.py (ResourceService)
     -> acquisition/planner.py   # ProviderSpec / route planning
     -> acquisition/simple.py    # AcquisitionRequest / AcquisitionRouter
     -> storage.py (Store)
```

0037 前的旧 authority 残留（migration 1-7 旧表定义、旧数据读兼容路径）仅为旧库升级和已存储数据可读保留，不再是新 acquisition 写入路径。

## 目录

```text
contracts/                  # 当前公共 Tool/Schema/平台/分类契约
src/education_resource_mcp/
├── server.py               # stdio MCP 入口 + thin public projection/binding
├── service.py              # 领域服务（完整业务事实、校验、Job/Asset 收口）
├── storage.py              # SQLite 状态权威（Flow/Plan/Job/Asset/Library）
├── adapters/               # 平台 Search/Inspect/Provider Adapter
├── retrieval/              # 候选归一化、身份与去重
└── acquisition/
    ├── planner.py          # ProviderSpec / route planning
    ├── simple.py           # AcquisitionRequest / AcquisitionRouter
    └── ...                 # Provider 与网页物化实现
scripts/                    # 隔离测试与运行环境校验脚本
tests/                      # 单元、契约、安全与 stdio 测试
```

## 安装

```bash
cd mcp/education-resources
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

## 启动

stdio 的 stdout 只用于 MCP 协议；诊断日志写入 stderr，业务数据只写入受控数据目录。

```bash
EDUCATION_RESOURCE_MCP_DATA_DIR=/absolute/path/to/data \
EDUCATION_RESOURCE_MCP_LIBRARY_DIR=/absolute/path/to/library \
EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR=/absolute/path/to/session-manager-data \
EDUCATION_RESOURCE_MCP_SEARXNG_URL=http://127.0.0.1:8888 \
  .venv/bin/education-resource-mcp
```

默认/关键目录：

- `EDUCATION_RESOURCE_MCP_DATA_DIR`：`~/.local/share/quanxiao/education-resource-mcp-data`，用于 SQLite、Job 工作区等内部数据；
- `EDUCATION_RESOURCE_MCP_LIBRARY_DIR`：默认 `~/Documents/学习资料库`。Windows 原生环境通常对应 `%USERPROFILE%\Documents\学习资料库`；显式配置该环境变量时使用用户指定目录；
- `EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR`：独立 session store；
- `EDUCATION_RESOURCE_MCP_SEARXNG_URL`：可选受信任搜索后端。

归档资料库与内部工作区有意分离：下载中的文件先进入 `$EDUCATION_RESOURCE_MCP_DATA_DIR/jobs/`，成功 Asset 经 `resource_archive` 后发布到用户可直接找到的 `Documents/学习资料库`。

SQLite、Job 临时目录、Cookie/Token 和浏览器档案不得放入源码目录；正式归档资料可以位于用户 Documents 或显式配置的独立资料盘。

## 安全与数据边界

- 来源只允许经过策略校验的 `http`/`https`；逐跳检查重定向。
- Provider 输出只能进入服务端受控 Job 目录；取消/失败要清理或隔离临时产物。
- 认证由独立 `session-manager` 管理。
- Tool 不接受 shell 命令、脚本、解释器、任意下载 URL 或本地文件路径；Archive 只接受服务端 `asset_id`。
- 文件真实格式、MIME、路径和网络策略检查继续保留。
- 文件 `sha256` / `byte_size` 作为 Asset 元数据与去重信息，不作为“声明值必须一致”的额外下载验收门禁，也不恢复通用下载大小上限。

## 验证

优先跑与改动直接相关的定向测试；不要因为一个小改动默认重复执行整个仓库的耗时测试。

0055 的无运行时依赖静态门禁：

```bash
cd mcp/education-resources
python -m unittest tests.test_public_surface_simplification_0055
```

安装 MCP 运行依赖后，再按需运行 contract/stdio 定向测试。需要验证更大范围时才显式运行：

```bash
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh all
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh e2e
```

离线 E2E/单测不能把平台标为 production-ready。真实 Agent、真实网络、合法会话和人工确认验收仍由 [0028 执行计划](../../.agent/plans/0028-real-openclaw-platform-e2e.md) 跟踪。

## 契约与架构导航

- [工作区根 README](../../README.md)
- [当前架构事实](../../docs/CURRENT_ARCHITECTURE.md)
- [开发路线](../../docs/DEVELOPMENT_PLAN.md)
- [检索权威边界](../../docs/RETRIEVAL_AUTHORITY.md)
- [`contracts/` 契约总览](contracts/README.md)
- [0055 Public MCP Surface Simplification](../../.agent/plans/archive/0055-public-mcp-surface-simplification.md)
