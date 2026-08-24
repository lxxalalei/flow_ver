# 已退役：Retrieval Authority

本文件不再承载 active 架构或执行路线。

当前唯一架构入口是 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)：

- Agent / Skill 负责需求理解、搜索设计、候选判断、Gap、停止、用户选择与归档分类；
- `education-resources` MCP 负责 Search / Expand / Inspect / Download、Job、Archive 与辅助 Session 能力；
- MCP 不保存 Flow、ResultSet、Presentation、Selection、Plan、Eligibility、Authority、Asset 或 digest 状态链。

需要修改语义决策时读取 [`skills/SKILL.md`](../skills/SKILL.md)；需要修改公共 Tool 时读取 [`TOOLS.md`](../TOOLS.md) 和运行时 `server.py`。历史 Retrieval Authority 设计仅保留在 Git 历史与归档材料中。
