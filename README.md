# 教育资源 OpenClaw 工作区

这是一个专用 OpenClaw 工作区，只服务教育资源的对话式搜索、筛选、下载和归档。
当前 active 代码只有两部分：一个用户入口 Skill 和一个本地 stdio MCP 服务。

```text
用户自然语言
  -> learning-resource-flow Skill
  -> education-resources MCP
       -> 搜索 Adapter
       -> SQLite 权威状态
       -> 异步下载 Job
       -> 受控 Asset 与资料库
```

## Active 结构

```text
skills/
└── learning-resource-flow/
    ├── SKILL.md
    ├── references/
    │   ├── mcp-workflow.md
    │   └── response-guidelines.md
    └── examples/

mcp/
└── education-resources/
    ├── contracts/v1/
    ├── src/education_resource_mcp/
    │   ├── adapters/
    │   ├── server.py
    │   ├── service.py
    │   ├── storage.py
    │   ├── jobs.py
    │   ├── downloader.py
    │   └── policy.py
    └── tests/
```

根目录的 `AGENTS.md`、`SOUL.md`、`TOOLS.md`、`IDENTITY.md`、`USER.md` 和
`HEARTBEAT.md` 是 OpenClaw 工作区控制文件；`docs/` 与 `.agent/` 用于开发管理。

迁移前的七个 Skill 完整保存在 `legacy/skill-pipeline-v1/`，不参与正常运行，也不在
顶层 `skills/` 中被发现。

## 当前能力

MCP 暴露 9 个领域工具：

```text
resource_flow_start
resource_search
resource_selection_save
resource_download_prepare
resource_download_start
resource_job_status
resource_job_cancel
resource_archive
resource_library_search
```

约束：

- 当前搜索只启用 `generic` 公开网页搜索，默认使用 DuckDuckGo 和 Bing。
- 当前下载只支持公开网页和公开文件直链。
- 下载必须经过 `prepare -> 用户明确确认 -> start`。
- Job 异步执行，支持状态查询和取消。
- 归档只接受服务端返回的 `asset_id`，不接受模型提供的文件路径。
- 网络访问执行 SSRF、重定向、大小上限和协议校验。
- 不绕过登录、验证码、付费墙、DRM 或访问控制。

## 本地 OpenClaw

当前 WSL 环境：

```text
Node:      24.18.1
OpenClaw:  2026.7.1-2
Agent:     main（名称 education-resources）
Model:     glm-req/glm-5.2
MCP:       education-resources
```

OpenClaw 命令：

```text
/home/admin_quanxiao/.local/bin/openclaw
```

MCP 虚拟环境与持久数据位于仓库外：

```text
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv/
/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-data/
```

## 启动对话

在工作区根目录执行：

```bash
openclaw chat --local
```

然后直接使用自然语言：

```text
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

用户不需要知道 MCP 工具名、`flow_id`、`job_id` 或确认令牌。

## 验证

检查 OpenClaw 注册：

```bash
openclaw config validate --json
openclaw mcp status --verbose
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

运行 MCP 测试：

```bash
cd mcp/education-resources

/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv/bin/python \
  -m compileall -q src tests

/home/admin_quanxiao/.local/share/quanxiao/education-resource-mcp-venv/bin/python \
  -m unittest discover -s tests -v
```

成功基线：Python 测试全部通过，MCP doctor 为 `ok`，probe 发现 9 个工具且
`diagnostics=[]`。

## 安全与数据边界

- Token、Cookie、浏览器档案、SQLite、下载产物和正式资源不得提交到仓库。
- 模型凭据由本机 OpenClaw SecretRef 管理，不写入工作区文档或配置示例。
- stdio MCP 是进程边界，不是安全沙箱；本地进程仍使用当前 WSL 用户权限。
- 当前是单机开发实现，不代表教育平台的多租户生产隔离已经完成。

## 文档

- [Agent 执行约束](AGENTS.md)
- [MCP 服务说明](mcp/education-resources/README.md)
- [MCP 领域契约](mcp/education-resources/contracts/README.md)
- [开发路线](docs/DEVELOPMENT_PLAN.md)
- [当前整理计划](.agent/plans/0005-workspace-two-part-cleanup.md)
- [Legacy 说明](legacy/README.md)
