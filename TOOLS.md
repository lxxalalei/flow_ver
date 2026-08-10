# TOOLS.md

唯一业务执行后端是 `education-resources` MCP；OpenClaw 中的工具名通常带服务器前缀，
例如 `education-resources__resource_search`。

- [当前架构事实与完整工具表](docs/CURRENT_ARCHITECTURE.md)
- [机器权威 catalog、Schema 与平台声明](mcp/education-resources/contracts/README.md)
- [唯一 evergreen 开发路线](docs/DEVELOPMENT_PLAN.md)
- [Retrieval Authority ADR](docs/RETRIEVAL_AUTHORITY.md)
- [当前执行：0027 平台获取能力接入](.agent/plans/0027-platform-acquisition-enablement.md)
- [后续：0028 真实 OpenClaw/平台 E2E](.agent/plans/0028-real-openclaw-platform-e2e.md)
- [后续：0029 检索 benchmark 与发布门禁](.agent/plans/0029-retrieval-benchmark-release-gate.md)
- [历史文档归档](docs/archive/README.md)

工具名、输入输出和版本只以 `mcp/education-resources/contracts/`、Schema 与运行时注册为准；
不要让模型拼接 shell、Python、Node、脚本路径、本地下载路径或伪造 MCP 状态。
副作用继续遵循 `prepare -> 用户明确确认 -> start`；归档只接受服务端返回的 `asset_id`。
