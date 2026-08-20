# Documentation

`docs/` 只保存当前仍应被人类直接阅读的产品与架构文档。机器契约、Agent 运行指引、执行计划和历史设计分别放在各自目录，不在这里复制正文。

## 我应该看哪一份？

| 你想知道 | 阅读入口 |
| --- | --- |
| 当前系统现在是什么、哪些能力已经落地 | [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md) |
| 项目接下来按什么顺序发展、阶段完成门槛是什么 | [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) |
| 检索事实、语义审查、Gap 与 StopDecision 为什么这样分权 | [RETRIEVAL_AUTHORITY.md](RETRIEVAL_AUTHORITY.md) |
| 当前正在执行什么任务 | [`.agent/plans/`](../.agent/plans/README.md) |
| MCP 当前公共工具与运行参数 | [TOOLS.md](../TOOLS.md) |
| MCP 服务如何安装、启动和验证 | [`mcp/education-resources/README.md`](../mcp/education-resources/README.md) |
| Agent 运行时如何理解、检索、核验和获取资源 | [`skills/`](../skills/SKILL.md) |
| 历史方案与阶段性规划 | [`archive/`](archive/README.md) |

## 文档权威边界

发生冲突时按以下顺序判断：

1. `server.py` 生成的 Tool schema 与实际 MCP 返回；
2. `mcp/education-resources/src/education_resource_mcp/` 中的实际运行时代码和状态转换；
3. `CURRENT_ARCHITECTURE.md` 等当前说明文档；
4. `.agent/plans/` 当前执行计划；
5. `docs/archive/`、`.agent/plans/archive/` 和 `legacy/` 中的历史材料。

文档不能通过描述覆盖机器事实；Registry、Adapter、ProviderSpec 或历史计划存在也不能单独证明某个平台当前可用或某次获取已经成功。

当前 MCP 只保存进程内短期资源句柄、文件型 Job 状态与本地 Session；Agent 不应伪造这些状态，也不应把它们解释为持久用户流程。

## 默认阅读顺序

第一次进入项目时只需要：

```text
README.md
  -> docs/README.md
     -> CURRENT_ARCHITECTURE.md
     -> DEVELOPMENT_PLAN.md
```

只有在需要修改检索语义时再阅读 `RETRIEVAL_AUTHORITY.md`；需要修改公共接口时先读 `TOOLS.md` 与 `server.py`；需要执行当前开发任务时进入 `.agent/plans/`。

默认不要通读 `archive/` 和 `legacy/`。
