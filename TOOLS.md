# TOOLS.md

唯一业务执行后端是 `education-resources` MCP。OpenClaw 中工具名通常带服务器前缀，例如 `education-resources__resource_search`。

工具名称、版本、输入输出和副作用只以以下机器事实为准：

- [`mcp/education-resources/contracts/tool-catalog.json`](mcp/education-resources/contracts/tool-catalog.json)
- [`mcp/education-resources/contracts/schemas/`](mcp/education-resources/contracts/schemas/)
- [`mcp/education-resources/contracts/error-codes.json`](mcp/education-resources/contracts/error-codes.json)

服务安装、启动和验证见 [`mcp/education-resources/README.md`](mcp/education-resources/README.md)；文档导航见 [`docs/README.md`](docs/README.md)。

运行时不得让模型拼接 shell、Python、Node、脚本路径、本地下载路径、任意下载 URL 或伪造业务 ID/状态。有副作用的获取继续遵循 `prepare -> 用户明确确认 -> start`；归档只接受服务端返回并校验过的 `asset_id`。

## OpenClaw 搜索 sub-agent

`learning-resource-flow` 可以在复杂检索中使用 OpenClaw 原生 `sessions_spawn` / `sessions_yield` / `subagents` 做**语义搜索规划**。这不增加第二个资源后端。

Main Agent 需要的运行时工具：

- `sessions_spawn`：启动 leaf search-planning child；
- `sessions_yield`：本轮已 spawn 所需 child 后，让完成事件自然回到 requester；
- `subagents`：只用于按需查看/取消，不用于轮询等待。

从实际 Main Agent 会话执行 `/tools` 确认这些工具没有被 profile、agent、provider、channel/sender 或 sandbox policy 移除。若当前 profile 已包含这些工具，无需修改配置；若使用显式 `tools.allow`，把需要的工具加入现有 allow，不要在同一 scope 同时配置 `tools.allow` 与 `tools.alsoAllow`。

第一版保持 `maxSpawnDepth=1`，每次复杂搜索最多 2 个 leaf child。是否把 `maxChildrenPerAgent` 在 live OpenClaw config 收窄到 2，由部署配置决定；Skill 本身已经限制搜索规划并发预算。

### leaf child 的工具边界

在 `learning-resource-flow` 为搜索规划启动的 leaf child：

- 只分析 SearchDirection、来源职责、query 和不确定性；
- 不调用 `education-resources__resource_*`；
- 不调用 session-manager；
- 不用 web/browser/exec/curl 等建立另一条候选发现路径；
- 不生成或猜测 Flow、ResultSet、resource_id、Resolution、availability、Provider、Asset 等业务事实；
- 不执行下载、归档或其他副作用。

部署层若需要硬限制，可以在 OpenClaw 的 `tools.subagents.tools` policy 中进一步 deny 上述工具；具体字段以当前 live `openclaw config schema` / `config.schema.lookup` 为准，不在仓库里覆盖用户机器的 `~/.openclaw/openclaw.json`。

完整行为规则见 [`skills/learning-resource-flow/references/multi-agent.md`](skills/learning-resource-flow/references/multi-agent.md)。
