# Education Resources MCP

`education-resources` 是工作区唯一 active 的教育资源执行服务。它是 Python stdio MCP，负责
搜索结果、展示与选择绑定、下载计划、异步 Job、获取结果、Asset/AssetBundle 和资料库归档的
服务端权威状态；它不是用户入口 Skill，也不是登录凭据管理器。

当前公共接口由机器契约定义：`contract_version=1.0.0`、`catalog_version=1.5.0`，工具集合和
每个工具的输入/输出以 [`contracts/tool-catalog.json`](contracts/tool-catalog.json) 与
[`contracts/schemas/`](contracts/schemas/) 为准。Skill 负责需求理解、候选审查、实际展示、
用户确认和结果解释；独立的 `session-manager` 负责合法登录与会话保存。

## 当前服务边界

服务端权威链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection
         -> DownloadPlan -> Job -> Acquisition Outcome
         -> AssetBundle / Asset -> Archive

Capability Descriptor -> Deployment Readiness
  -> Resolution / Representation -> Eligibility
  -> capability-aware Plan + authority_digest
  -> immutable Job Execution Binding -> exact Provider
  -> Acquisition Outcome -> Asset / AssetBundle
```

- Search 和 creator browse 只产生服务端候选 ResultSet；只有 Skill 实际展示后保存的
  Presentation 才能被选择。
- `resource_download_prepare` 只准备计划；有副作用的下载必须经过“prepare -> 用户确认 ->
  start”。`resource_download_start` 会重新校验当前绑定并冻结 Job Execution Binding。
- 显式 representation evidence 只在 `observed_at <= now < expires_at` 时有效。过期 cache 必须由
  `resource_inspect` 真实刷新；Prepare 和 Start 都以 `RESOLUTION_STALE` 拒绝过期或未来时间的
  evidence，不创建可确认 Plan 或 Job。
- Job 是异步的；状态、取消、Outcome、Asset 和 Archive 由 MCP 服务端产生，模型不得伪造 ID、
  摘要、状态、Provider、下载结果或归档结果。
- `coverage`、Resolution、Capability、Readiness、Eligibility 和 Outcome 是服务端事实，不能
  代替 Skill 的语义审查、Gap 或停止决策。检索语义边界见
  [`docs/RETRIEVAL_AUTHORITY.md`](../../docs/RETRIEVAL_AUTHORITY.md)。

## 目录

```text
contracts/                  # 当前公共控制面契约
src/education_resource_mcp/
├── server.py               # stdio MCP 入口
├── service.py              # 领域服务与状态转换
├── storage.py              # SQLite 权威状态
├── adapters/               # 平台 Adapter 与受控来源访问
├── retrieval/              # 私有候选归一化、身份解析与去重
└── acquisition/            # 获取策略、路由与网页物化
scripts/                    # 隔离测试与运行环境校验脚本
tests/                      # 单元、契约、安全与 stdio 测试
```

## 安装

在本目录创建独立虚拟环境，不要安装到系统 Python：

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

未设置时的默认路径：

- `EDUCATION_RESOURCE_MCP_DATA_DIR`：
  `~/.local/share/quanxiao/education-resource-mcp-data`。
- `EDUCATION_RESOURCE_MCP_LIBRARY_DIR`：`$EDUCATION_RESOURCE_MCP_DATA_DIR/学习资料库`。
  归档文件、`database.sqlite` 和 Job 临时目录均不得放入源码目录。
- `EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR`：不设置时使用测试/显式本地部署所选的
  session store；设置后必须安装 `openclaw-session-manager`，服务只读消费该独立目录，不复制
  Cookie、Token 或浏览器档案。
- `EDUCATION_RESOURCE_MCP_SEARXNG_URL`：可选的受信任搜索后端地址；未设置时不启用该后端。

常用资源限制可通过 `EDUCATION_RESOURCE_MCP_MAX_BYTES`、
`EDUCATION_RESOURCE_MCP_SEARCH_TIMEOUT`、`EDUCATION_RESOURCE_MCP_DOWNLOAD_TIMEOUT`、
`EDUCATION_RESOURCE_MCP_MAX_RESULTS`、`EDUCATION_RESOURCE_MCP_MAX_WORKERS` 和
`EDUCATION_RESOURCE_MCP_PLAN_TTL` 配置。值必须为正整数；不要用环境变量传入凭据、任意命令或
本地路径给工具输入。

## 安全与数据边界

- 来源只允许经过策略校验的 `http`/`https`；逐跳校验重定向并阻断本机、私网、链路本地和云
  元数据地址。
- 服务端强制执行超时、重试/并发、流式大小、数量、内容类型和真实文件格式校验，并清理取消
  或失败的临时产物。
- 不绕过登录、验证码、付费墙、DRM 或其他访问控制。需要认证时由独立 `session-manager`
  合法完成浏览器捕获；用户明确指定平台、用途并授权时，也可由它接受一次 canonical direct import。
  凭据不进入 `education-resources`、其他 Tool、日志、计划或仓库，也不得回显或失败后自动重放。
- 工具不接受 shell 命令、脚本、解释器、任意下载 URL 或本地文件路径。Archive 只接受服务端
  生成且经过状态与权威校验的 `asset_id`（以及所属 Job 绑定）。大文件和二进制不进入模型上下文。
- 持久开发数据与源码分离；测试脚本将数据、HOME、临时目录和 bytecode 缓存隔离到原生 Linux
  临时目录，不把测试会话或下载产物写入仓库。

## 验证

始终指定本次使用的虚拟环境解释器：

```bash
cd mcp/education-resources
.venv/bin/python -m compileall -q src tests
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh all
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh e2e
```

`e2e` 使用隔离临时目录和离线 fixture，通过真实 MCP stdio 子进程调用当前 13 个公共 Tool；它用于验证
控制面、重启、认证恢复、取消、partial、策略和归档边界，不访问真实平台。即使全量与 E2E 均通过，
也不能据此把某个平台标为 production-ready。真实 Agent、真实网络、合法会话和人工确认验收由
[0028 执行计划](../../.agent/plans/0028-real-openclaw-platform-e2e.md)单独记录。

具备 OpenClaw 环境时，再运行 MCP doctor/probe；应以当前工具目录和诊断结果为准，不以旧日志或
旧测试数字判断当前状态：

```bash
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

## 契约与架构导航

- [工作区根 README](../../README.md)
- [当前架构事实快照](../../docs/CURRENT_ARCHITECTURE.md)
- [开发计划](../../docs/DEVELOPMENT_PLAN.md)
- [检索权威边界](../../docs/RETRIEVAL_AUTHORITY.md)
- [`contracts/` 契约总览](contracts/README.md)
- [领域契约](contracts/domain-contract.md)
- [当前兼容与重置政策](contracts/compatibility.md)
- [工具目录](contracts/tool-catalog.json)
- [错误码目录](contracts/error-codes.json)
