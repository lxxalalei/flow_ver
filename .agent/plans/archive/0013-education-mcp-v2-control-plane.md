# Education Resources MCP v2 控制面

- 状态：completed
- 创建日期：2026-08-03
- 完成日期：2026-08-03
- 范围：`mcp/education-resources/`、`skills/learning-resource-flow/`、相关文档、测试与 Windows OpenClaw 安装

## 目标与范围

冻结 `contracts/v1/`，新增并切换到 `2.0.0` 控制面，建立服务端权威的：

```text
FlowTask -> ResultSet -> Presentation -> Selection -> DownloadPlan -> Job -> Asset -> Archive
```

本轮交付：

- `resource_flow_start` 使用 `goal + user_role + resource_target + constraints` 任务结构。
- `resource_search` 绑定 `task_version` 并产生独立 ResultSet，不把全部搜索结果视为已展示。
- `resource_presentation_save` 持久化实际展示项和顺序，并允许显式空 Presentation。
- `resource_selection_save` 只接受 Presentation 中的 1-based position，并维护独立单调递增的 `selection_version`。
- 下载计划和启动绑定 `presentation_id`、`presented_version`、`selection_version`、`selection_digest` 与 `plan_digest`，旧计划在 A -> B -> A 后仍不可复用。
- `resource_flow_status` 返回五个可恢复快照和 `allowed_next_actions`，不泄露确认秘密、凭据和路径。
- 公共 Catalog 严格为 11 个 v2 工具；Session 工具不再由 education-resources 对外暴露。
- Skill 同步使用 v2 工具顺序，登录委托独立 `session-manager` / `session-login-flow`。
- education-resources 通过显式配置的只读桥接消费 standalone session-manager 安全存储；Windows 下验证了 DPAPI 存储读取。
- 多方向聚合、完整硬过滤执行状态与候选证据模型作为下一批能力，不伪装为本轮已完成。

## 步骤

- [x] completed：检查工作树、路线图、现有契约、实现与测试基线。
- [x] completed：确定 v2 控制面范围和迁移边界，冻结 v1。
- [x] completed：实现 SQLite v2 状态、事务、幂等、绑定失效和 Service 控制面。
- [x] completed：新增 v2 Schema、11 工具目录、错误码和兼容文档。
- [x] completed：同步 MCP Server、唯一 active Skill 和开发路线图。
- [x] completed：补充控制面、重启恢复、幂等、stdio、取消隔离和 session bridge 测试。
- [x] completed：运行全量单元测试、Schema/引用检查、compileall、Markdown 检查和 `git diff --check`。
- [x] completed：安装到 Windows OpenClaw，完成 Junction、doctor、probe、Skill 和 SearXNG smoke 验证。

## 验证

已执行：

```text
cd mcp/education-resources
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python -m compileall -q src tests
cd ../..
git diff --check
```

结果：

- 全量 Python 测试：`Ran 84 tests ... OK`。
- v2 JSON：15 个文件可解析。
- Draft 2020-12 Schema：13 个 Schema 通过元 Schema 检查。
- v2 `$ref`：263 个引用全部可解析。
- stdio `tools/list`：精确 11 个工具；完整 v2 round trip 通过。
- 取消任务后，quarantined Asset 不再从 Job Status 或 Flow Status 暴露。
- standalone session-manager bridge：未配置保持测试兼容；显式配置时必须加载独立包，缺依赖明确失败。
- `compileall`、Markdown 本地链接检查、`git diff --check`：通过。

Windows OpenClaw：

- OpenClaw `2026.7.1-2 (0790d9f)`。
- `education-resources` 安装在版本目录 `0.2.0`，`current` 为 Junction。
- `learning-resource-flow` 安装在版本目录 `0.2.0`，OpenClaw Skill 路径为 Junction。
- `openclaw mcp doctor education-resources --probe`：`ok`。
- `openclaw mcp probe education-resources --json`：`tools=11`，`diagnostics=[]`。
- `learning-resource-flow`：Ready、visible to model、available as command。
- 旧教育流水线的 6 个个人 Skill 已通过 OpenClaw 配置禁用，文件未删除，可逆恢复。
- SearXNG `http://localhost:8888`：HTTP 200。
- Windows runtime smoke：成功加载 `session_manager.store.SessionStore`，Bilibili/SmartEdu 记录可读取，SearX 搜索返回 3 个候选。

## 结果与剩余风险

本计划全部完成，无 blocked 项。

明确留待后续：

- `direction_runs` 真实多方向搜索执行与聚合；
- `filter_execution` 真实硬过滤执行报告；
- 完整候选证据模型和证据强度；
- 可信宿主确认 receipt；
- 生产多租户隔离和远程 Streamable HTTP MCP。

当前 runtime 对 `direction_runs` 和 `filter_execution` 返回空数组，不能宣称上述能力已完成。
