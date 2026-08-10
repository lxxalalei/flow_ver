# 教育资源 OpenClaw 工作区

这是一个专用 OpenClaw 工作区：用户用自然语言查找、比较、获取并归档教育资源。
当前 active 产品只有两个部分：唯一用户入口 Skill，以及拥有业务状态和安全边界的本地
Python stdio MCP。

```text
用户自然语言
  -> skills/learning-resource-flow/
  -> mcp/education-resources/
  -> 搜索 / 核验 / 选择 / prepare-confirm-start 获取 / 归档
```

## 默认阅读顺序

1. **执行约束**：[AGENTS.md](AGENTS.md)。先确认工作树保护、产品边界、计划和验证要求。
2. **当前事实**：[CURRENT_ARCHITECTURE.md](docs/CURRENT_ARCHITECTURE.md)。机器契约、Schema、
   运行时代码和当前工作树优先于任何说明文档或历史计划。
3. **唯一长期路线**：[DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)。它只保留 evergreen
   路线和完成门槛，不替代执行计划。
4. **当前执行**：[0027 平台获取能力接入](.agent/plans/0027-platform-acquisition-enablement.md)。
5. **后续顺序**：[0028 真实 OpenClaw/平台 E2E](.agent/plans/0028-real-openclaw-platform-e2e.md)
   → [0029 检索 benchmark 与发布门禁](.agent/plans/0029-retrieval-benchmark-release-gate.md)。

`docs/archive/` 和 `.agent/plans/archive/` 只用于历史背景、审计和回滚证据；已完成计划也
不是默认必读内容。需要了解归档文档时，从 [归档索引](docs/archive/README.md) 进入。
本轮文档治理记录在 [0030 文档权威收敛计划](.agent/plans/archive/0030-document-authority-consolidation.md)。

## Active 结构

```text
skills/learning-resource-flow/       # 唯一用户入口和对话编排
mcp/education-resources/              # stdio MCP、契约、搜索、获取、任务与归档
mcp/education-resources/contracts/   # 机器权威 catalog、Schema 和 capability 声明
legacy/skill-pipeline-v1/             # 只读历史快照，不参与 active runtime
.openclaw-test/                       # 临时隔离测试数据，不是正式资源库
```

Skill 负责理解 `user_role`、`resource_target`、目标和显式约束，决定澄清、搜索、核验、展示
和恢复；MCP 负责服务端生成的业务 ID、权威状态、网络/下载安全、异步 Job 以及归档。
用户不需要知道工具名、`flow_id`、`job_id`、确认令牌或本地路径。

## 开始对话

在工作区根目录运行：

```bash
openclaw chat --local
```

例如：

```text
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

## 入口与边界

- [工具跳转页](TOOLS.md)
- [MCP 服务说明](mcp/education-resources/README.md)
- [MCP 领域契约](mcp/education-resources/contracts/README.md)
- [Retrieval Authority ADR](docs/RETRIEVAL_AUTHORITY.md)
- [Legacy 说明](legacy/README.md)
- [Agent 执行约束](AGENTS.md)

凭据、Cookie、浏览器档案、SQLite 数据和下载资产必须位于源码工作区之外；stdio MCP
是进程边界而不是安全沙箱。不绕过登录、验证码、付费墙、DRM 或明确的访问控制，也不把
模型提供的任意 URL、路径、业务 ID 或伪造状态当作权威输入。
