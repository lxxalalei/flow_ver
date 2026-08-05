# Education Resources MCP

本目录是教育资源工作区唯一的执行与权威状态服务。当前 Python stdio MCP 已运行
`contracts/v2/` 的 `2.0.0` 控制面，并且公共 catalog **仅暴露 11 个工具**。

`contracts/v1/` 冻结在 `1.0.0`，只保留作历史兼容、审计和显式回滚依据；不再向 v1 增加字段、工具或运行语义。

v2 权威状态链为：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive
```

搜索结果与模型实际展示集合严格分离。Skill 负责语义判断、候选审查和实际展示；MCP 负责所有权威状态、副作用、
幂等和安全校验。

平台登录、Cookie、Token、浏览器会话捕获与本地会话保存由独立 `session-manager` 负责，不属于
education-resources 的 11 工具 catalog。education-resources 不向模型暴露登录秘密。

## 目录

```text
contracts/v1/                  # 冻结的 1.0.0 历史契约
contracts/v2/                  # 当前运行的 2.0.0 控制面契约
src/education_resource_mcp/
├── adapters/                  # MCP 内部平台 Adapter
├── server.py                  # stdio MCP 入口
├── service.py                 # 领域服务
├── storage.py                 # SQLite 权威状态
├── jobs.py                    # 异步任务
├── downloader.py              # 受控 HTTP(S) 下载
└── policy.py                  # 网络与路径安全
tests/                         # 单元、契约、安全和 stdio 测试
```

## 本地安装

使用独立虚拟环境，不要安装到系统 Python：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

当前 WSL 开发环境使用：

```text
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv
```

## 启动

```bash
EDUCATION_RESOURCE_MCP_DATA_DIR=/absolute/path/to/data \
EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR=/absolute/path/to/session-manager-data \
EDUCATION_RESOURCE_MCP_SEARXNG_URL=http://127.0.0.1:8888 \
  .venv/bin/education-resource-mcp
```

stdio 的 stdout 只用于 MCP 协议。诊断日志应写入 stderr，业务文件只写入配置的数据目录。

`EDUCATION_RESOURCE_MCP_SESSION_MANAGER_DATA_DIR` 指向独立 `session-manager` 的数据目录。设置后，
education-resources 会通过 `openclaw-session-manager` 包只读消费同一份安全凭据（Windows 下包括当前用户 DPAPI），
不会维护第二份 Cookie/Token。显式设置该目录但运行环境未安装 `openclaw-session-manager` 时，MCP 会启动失败而不是静默读取空的旧存储。

未设置 `EDUCATION_RESOURCE_MCP_DATA_DIR` 时，默认使用：

```text
~/.local/share/quanxiao/education-resource-mcp-data
```

## 公共工具

v2 只暴露以下 11 个工具：

1. `resource_flow_start`
2. `resource_flow_status`
3. `resource_search`
4. `resource_presentation_save`
5. `resource_selection_save`
6. `resource_download_prepare`
7. `resource_download_start`
8. `resource_job_status`
9. `resource_job_cancel`
10. `resource_archive`
11. `resource_library_search`

主流程为：

```text
resource_flow_start
-> resource_search（提交 task_version，filters 使用 SearchFilters 对象）
-> 模型实际展示审查后的 ResultSet 子集
-> resource_presentation_save（允许保存空 Presentation）
-> 用户选择
-> resource_selection_save（只提交当前 Presentation positions）
-> resource_download_prepare（完整绑定 Presentation/Selection，返回 plan_digest）
-> 用户明确确认
-> resource_download_start（提交完整绑定和 plan_digest）
-> resource_job_status / resource_job_cancel
-> resource_archive
-> resource_library_search
```

`resource_flow_status` 可在任意恢复点调用，返回：

```text
current_result_set
current_presentation
current_selection
current_plan
current_job
```

它不会返回 confirmation token/hash、Cookie、Token、数据库路径、临时目录、下载路径或归档本地路径。

完整不变量见 `contracts/v2/domain-contract.md`；v1/v2 破坏性差异和冻结策略见
`contracts/v2/compatibility.md`；精确工具集合见 `contracts/v2/tool-catalog.json`。

## 搜索、下载和登录边界

当前 Generic 搜索 Adapter 已内聚到 MCP 包，不依赖 `legacy/`。下载只允许通过服务端策略校验的 HTTP(S) 来源，
并强制执行网络边界、重定向、大小、内容类型和真实格式校验。

需要认证的平台返回 `AUTH_REQUIRED` 后，应暂停资源状态转换，调用独立 `session-manager` 完成合法登录与会话保存，
再通过 `resource_flow_status` 恢复当前 Flow。不得把 Cookie 或 Token 作为 education-resources 工具参数传递。

## 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

通过 OpenClaw 验证：

```bash
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

成功条件是 doctor 报告 `ok`，probe 精确发现 11 个工具且 `diagnostics=[]`。
