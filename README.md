# 教育资源 OpenClaw 工作区

这是一个专用 OpenClaw 工作区：用户用自然语言查找、比较、获取并归档教育与学习资源。
当前 active 产品只有两个部分：唯一用户入口 Skill，以及拥有业务状态和安全边界的本地 Python stdio MCP。

```text
用户自然语言
  -> skills/learning-resource-flow/
  -> mcp/education-resources/
  -> 搜索 / 核验 / 选择 / prepare-confirm-start 获取 / 归档
```

## 默认阅读顺序

第一次进入项目，只按下面顺序阅读：

1. [AGENTS.md](AGENTS.md)：仓库修改、计划和验证约束。
2. [docs/README.md](docs/README.md)：文档导航，告诉你不同问题应该看哪一层。
3. [docs/CURRENT_ARCHITECTURE.md](docs/CURRENT_ARCHITECTURE.md)：当前机器事实和 active 架构。
4. [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)：唯一 evergreen 技术路线。
5. [当前执行计划](.agent/plans/README.md)：只在需要继续开发时进入。

`docs/archive/`、`.agent/plans/archive/` 和 `legacy/` 只用于历史背景、审计、迁移与回滚证据，不是默认必读内容。

## Active 结构

```text
skills/learning-resource-flow/       # 唯一用户入口和对话编排
mcp/education-resources/              # stdio MCP、契约、搜索、获取、任务与归档
mcp/education-resources/contracts/   # 机器权威 catalog、Schema 和 capability 声明
docs/                                # 当前产品/架构文档与导航
.agent/plans/                         # 当前执行计划；completed 进入 archive
legacy/skill-pipeline-v1/             # 只读历史快照，不参与 active runtime
.openclaw-test/                       # 临时隔离测试数据，不是正式资源库
```

Skill 负责需求理解、澄清、搜索方向、候选语义审查、Selective Inspect、展示、选择解释与恢复；MCP 负责服务端业务 ID、权威状态、Capability/Readiness/Eligibility、网络与获取安全、异步 Job、Asset 和归档。用户不需要知道工具名、`flow_id`、`job_id`、确认令牌或本地路径。

## 开始对话

在工作区根目录运行：

```bash
openclaw chat --local
```

例如：

```text
帮我找适合小学三年级学习太阳系的中文图文资源，先搜索，不要下载。
```

## 主要入口

- [文档导航](docs/README.md)
- [MCP 服务说明](mcp/education-resources/README.md)
- [MCP 机器契约](mcp/education-resources/contracts/README.md)
- [Retrieval Authority ADR](docs/RETRIEVAL_AUTHORITY.md)
- [唯一入口 Skill](skills/learning-resource-flow/SKILL.md)
- [Legacy 说明](legacy/README.md)

凭据、Cookie、浏览器档案、SQLite 数据和下载资产必须位于源码工作区之外。stdio MCP 是进程边界而不是安全沙箱；不绕过登录、验证码、付费墙、DRM 或明确访问控制，也不把模型提供的任意 URL、路径、业务 ID 或伪造状态当作权威输入。
