# Education Resources MCP

`education-resources` 是工作区唯一 active 的教育资源执行服务。它是 Python stdio MCP，负责 ResultSet、Presentation、Selection、Resolution、Plan、Job、Outcome、Asset/AssetBundle 和资料库归档的服务端业务状态；它不是用户入口 Skill，也不是登录凭据管理器。

当前公共接口由机器契约定义：`contract_version=1.0.0`、`catalog_version=1.6.0`，工具集合和每个工具的输入/输出以 [`contracts/tool-catalog.json`](contracts/tool-catalog.json) 与 [`contracts/schemas/`](contracts/schemas/) 为准。Skill 负责需求理解、候选审查、实际展示、用户确认和结果解释；独立 `session-manager` 负责合法登录与会话保存。

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

- Search 和 creator browse 只产生候选 ResultSet；只有 Skill 实际展示后保存的 Presentation 才能被选择。
- `resource_inspect` 产生/刷新 Resolution 与 Representation。显式 evidence 过期时必须重新 Inspect；Prepare/Start 不把旧 evidence 当当前事实。
- `resource_download_prepare` 基于当前 Selection + fresh Representation 选择明确的 `scope / strategy / provider`，只准备计划，不下载。
- 下载必须经过 `prepare -> 用户明确确认 -> start`。Start 再次读取当前 Resolution，确认 Representation 和 exact Provider route 没有漂移，然后创建 Job。
- Router 只执行 Plan 指定的 `(provider_id, provider_version)`，失败不会静默换 generic Provider。
- Job 是异步的；状态、取消、Outcome、Asset 和 Archive 由 MCP 服务端产生，模型不能伪造这些业务 ID 或执行结果。
- `coverage` 与 Resolution 是服务端事实，不能替代 Skill 的 SemanticReview、Gap 或 StopDecision。检索语义边界见 [`docs/RETRIEVAL_AUTHORITY.md`](../../docs/RETRIEVAL_AUTHORITY.md)。

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
  -> simple_service.py
     -> acquisition/planner.py
     -> acquisition/simple.py
     -> simple_storage.py
```

0037 前的旧 authority 代码暂时还在源码中作为迁移兼容基座，后续 cleanup 会物理删除；它们不再是新 acquisition 写入路径。

## 目录

```text
contracts/                  # 当前公共 Tool/Schema/平台/分类契约
src/education_resource_mcp/
├── server.py               # stdio MCP 入口
├── simple_service.py       # 当前 Active 获取服务切换层
├── simple_storage.py       # migration 8 与简化 Plan/JobItem/Outcome
├── service.py              # 0037 前成熟服务基座；待后续兼容清理
├── storage.py              # 0037 前成熟存储基座；待后续兼容清理
├── adapters/               # 平台 Search/Inspect/Provider Adapter
├── retrieval/              # 候选归一化、身份与去重
└── acquisition/
    ├── planner.py          # ProviderSpec / route planning
    ├── simple.py           # 简化 Provider request/router boundary
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

- `EDUCATION_RESOURCE_MCP_DATA_DIR`：`~/.local/share/quanxiao/education-resource-mcp-data`；
- `EDUCATION_RESOURCE_MCP_LIBRARY_DIR`：默认 `$EDUCATION_RESOURCE_MCP_DATA_DIR/学习资料库`；
- `EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR`：独立 session store；
- `EDUCATION_RESOURCE_MCP_SEARXNG_URL`：可选受信任搜索后端。

SQLite、Job 临时目录、归档文件、Cookie/Token 和浏览器档案都不得放入源码目录。

## 安全与数据边界

- 来源只允许经过策略校验的 `http`/`https`；逐跳检查重定向。
- Provider 输出只能进入服务端受控 Job 目录；取消/失败要清理或隔离临时产物。
- 认证由独立 `session-manager` 管理。
- Tool 不接受 shell 命令、脚本、解释器、任意下载 URL 或本地文件路径；Archive 只接受服务端 `asset_id`。
- 文件真实格式、MIME、路径和网络策略检查继续保留。
- 文件 `sha256` / `byte_size` 作为 Asset 元数据与去重信息，不作为“声明值必须一致”的额外下载验收门禁，也不恢复通用下载大小上限。

## 验证

优先跑与改动直接相关的定向测试；不要因为一个小改动默认重复执行整个仓库的耗时测试。

```bash
cd mcp/education-resources
.venv/bin/python -m compileall -q src
.venv/bin/python -m pytest -q tests/test_acquisition_simplification_0037.py
```

需要验证更大范围时再显式运行：

```bash
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh all
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh e2e
```

0037 已在隔离 GitHub Actions 中实际通过：包安装、active package compileall、全部 JSON 契约解析以及 0037 定向测试。旧 capability-authority 专项测试需要按新业务行为重写或移出 Active 测试面，不能用它们强迫实现恢复已废弃状态链。

离线 E2E/单测不能把平台标为 production-ready。真实 Agent、真实网络、合法会话和人工确认验收仍由 [0028 执行计划](../../.agent/plans/0028-real-openclaw-platform-e2e.md) 跟踪。

## 契约与架构导航

- [工作区根 README](../../README.md)
- [当前架构事实](../../docs/CURRENT_ARCHITECTURE.md)
- [开发路线](../../docs/DEVELOPMENT_PLAN.md)
- [检索权威边界](../../docs/RETRIEVAL_AUTHORITY.md)
- [`contracts/` 契约总览](contracts/README.md)
- [0037 获取状态链简化](../../.agent/plans/0037-acquisition-state-simplification.md)
