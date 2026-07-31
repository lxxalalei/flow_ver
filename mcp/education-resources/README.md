# Education Resources MCP

本目录是教育资源工作区唯一的执行与权威状态服务。它通过 Python stdio MCP 向
OpenClaw 暴露 9 个领域工具，持有 Flow、候选集合、Selection、Download Plan、
异步 Job、Asset 和归档状态。

Skill 不执行搜索、下载或文件操作；所有副作用和安全校验都在这里完成。

## 目录

```text
contracts/v1/                  # 工具 Schema、错误码和领域契约
src/education_resource_mcp/
├── adapters/                  # MCP 内部平台 Adapter
├── server.py                  # stdio MCP 入口
├── service.py                 # 领域服务
├── storage.py                 # SQLite 权威状态
├── jobs.py                    # 异步任务
├── downloader.py              # 公开 HTTP(S) 下载
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
  .venv/bin/education-resource-mcp
```

stdio 的 stdout 只用于 MCP 协议。诊断日志应写入 stderr，业务文件只写入配置的数据目录。

未设置 `EDUCATION_RESOURCE_MCP_DATA_DIR` 时，默认使用：

```text
~/.local/share/quanxiao/education-resource-mcp-data
```

## 工具顺序

```text
resource_flow_start
-> resource_search
-> resource_selection_save
-> resource_download_prepare
-> 用户明确确认
-> resource_download_start
-> resource_job_status / resource_job_cancel
-> resource_archive
-> resource_library_search
```

当前 Generic 搜索 Adapter 已内聚到 MCP 包，不依赖 `legacy/`。真实下载只支持公开
网页或公开文件直链；其他平台在完成契约、安全测试和真实验收后逐个迁移。

## 测试

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

通过 OpenClaw 验证：

```bash
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

成功条件是 doctor 报告 `ok`，probe 发现 9 个工具且 `diagnostics=[]`。
