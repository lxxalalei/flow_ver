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
    ├── contracts/
    │   └── platforms/                 # 平台能力 Registry（机器事实）
    ├── src/education_resource_mcp/
    │   ├── adapters/
    │   ├── retrieval/                  # private resource model / identity / dedup
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

education-resources MCP 当前使用 `contract_version=1.0.0`、`catalog_version=1.3.0`，
对外暴露 13 个领域工具：

```text
resource_flow_start
resource_flow_status
resource_search
resource_presentation_save
resource_selection_save
resource_download_prepare
resource_download_start
resource_job_status
resource_job_cancel
resource_archive
resource_library_search
resource_browse_creator
resource_inspect
```

`resource_browse_creator` 是正式 active 工具，当前对 Douyin、Bilibili、知乎和微博的
创作者内容浏览提供 Adapter 支持。完整工具、副作用、资源类型、Adapter 和边界以
[当前架构事实快照](docs/CURRENT_ARCHITECTURE.md) 为准。

0018 已补齐内部检索层：`retrieval/` 持有 private resource model、identity resolver 和
保守的 candidate dedup；平台能力 Registry 当前有 16 个条目，即 `generic` 加 15 个内置
平台，generic 搜索后端和 15 个内置 Adapter 均使用不可变 `AdapterDescriptor`。普通搜索与
`resource_browse_creator` 共用安全规范化、逻辑资源识别和去重路径，去重后的公共候选才由
服务端生成随机 `resource_id`。这些内部身份和 descriptor 不构成新的 MCP Tool，也不能由
模型提交为权威 ID。

0019 在保持公共 `contract_version=1.0.0` 的前提下，以 catalog 兼容加法新增
`resource_inspect`，当时将 `catalog_version` 提升到 `1.1.0`；0020 的兼容 adaptive search
字段将 catalog 提升到 `1.2.0`；0022 的可选 AssetBundle 输出字段进一步提升到当前
`1.3.0`，机器目录仍精确包含 13 个工具。
Inspect 只接受 `contract_version`、`flow_id`、`resource_id`、`idempotency_key` 四个字段，
服务端从当前 Flow 的资源重新取得来源，不接受 URL、路径、批量 ID、检查深度或凭据。
Candidate、ResolvedResource、Representation 与 Resolution 分层；Resolution 独立保存于
SQLite migration 3 的 `resource_resolutions`，不改写不可变 ResultSet。成功/partial 按
`resource_id + source_fingerprint + inspect-v1` 缓存，unresolved 只保存审计并允许新幂等键重试；
`resource_flow_status` 返回安全的 `current_resolutions` 摘要。

0020 保持同一个 `resource_search`：旧调用默认 `replace`，`extend` 使用当前
`base_result_set_id` 生成新的不可变快照。服务端持久化 round、跨轮去重 provenance、事实
coverage 与私有 identity evidence；Skill 依据 SearchDirection、Gap 和 InformationGain
在常规最多 3 轮、综合最多 4 轮内决定 Present、Clarify、StopWithGap 或 Replan。

当前首批实现了 generic、Bilibili、NLC、Anna/Libgen、Ximalaya、Zhihu、SmartEdu 七类
Inspector；其余 Registry 平台返回结构化 `FEATURE_NOT_SUPPORTED`，不静默回退 generic。
Generic 检查使用有界 GET、逐跳 SSRF 校验、1 MiB 上限和 MIME/魔数交叉验证。Inspect 不下载、
不归档，不返回 locator、文件字节或本地路径。0019 已完成根级实现与回归验收。
平台能力的机器事实见
[`contracts/platforms/platform-registry.json`](mcp/education-resources/contracts/platforms/platform-registry.json)。

0021 在既有 prepare/confirm/start 控制面内部增加 Acquisition Router：文件型资源使用
`direct_file`，普通网页默认使用不执行脚本的 `web_materialize`，从安全 Block IR 重建
Markdown/HTML、受控同源图片和确定性 `webbundle.zip`；`web_capture` 仅供受控内部调用
显式选择，不是静态失败或认证失败的自动 fallback。0022 已在此基础上增加正式
AssetBundle、BundleItem、角色和逐项失败持久化；`webbundle.zip` 继续作为 singleton primary
Asset 保持兼容并保留归档后的相对链接。

约束：

- 当前搜索由 `generic` 公开网页搜索和已接入的平台 Adapter 共同提供；需要登录的平台
  由独立 `session-manager` 管理授权状态，单个平台失败不会伪装成整体成功。
- 当前获取支持公开文件直链、静态网页物化，以及 Bilibili、SmartEdu、喜马拉雅等已接入且
  具备合法授权的平台下载器；未接入、未授权或被策略阻断的平台不会被静默绕过。
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

机器事实基线：catalog、catalog meta-schema 和运行时工具注册均为 13 个工具。0017–0022
实现与本地根验收已完成；0023 的 4/4 原始 JSON-RPC stdio 进程级 E2E、全量本地回归
352/352、`compileall`、Schema、Markdown 链接和差异检查均已通过。当前 macOS 仍未运行
真实平台网络测试或 OpenClaw doctor/probe；历史 WSL 验证早于本次 catalog 更新，不能作为
当前 13 工具的实时 OpenClaw 验收。

## 安全与数据边界

- Token、Cookie、浏览器档案、SQLite、下载产物和正式资源不得提交到仓库。
- 模型凭据由本机 OpenClaw SecretRef 管理，不写入工作区文档或配置示例。
- stdio MCP 是进程边界，不是安全沙箱；本地进程仍使用当前 WSL 用户权限。
- 当前是单机开发实现，不代表教育平台的多租户生产隔离已经完成。

## 文档

- [Agent 执行约束](AGENTS.md)
- [MCP 服务说明](mcp/education-resources/README.md)
- [MCP 领域契约](mcp/education-resources/contracts/README.md)
- [当前架构事实快照](docs/CURRENT_ARCHITECTURE.md)
- [资源检索系统 v2 总体规划与执行进度](docs/flow_ver_资源检索系统_v2_总体规划与执行计划.md)
- [开发路线](docs/DEVELOPMENT_PLAN.md)
- [当前整理计划](.agent/plans/0005-workspace-two-part-cleanup.md)
- [Legacy 说明](legacy/README.md)
