# Education 资源主链 v1 清理与文档对齐

- 状态：completed
- 创建日期：2026-08-06
- 范围：删除 `mcp/education-resources/contracts/v1/`，同步当前 v2 文档

## 边界

- 删除教育资源主链的冻结 v1 契约。
- 保留 `mcp/session-manager/contracts/v1/`，它仍是独立服务的 active 契约。
- 保留 `legacy/skill-pipeline-v1/`，它仍作为历史审计和回滚证据。
- 不修改历史计划中对迁移过程的事实记录。

## 步骤

- [x] completed：删除教育资源主链 contracts/v1。
- [x] completed：同步根 README、TOOLS、MCP 契约说明、开发路线和 Agent 约束。
- [x] completed：检查残留引用、契约目录、编译和工作树状态。

## 验证

- education-resources v1 目录已不存在；session-manager v1 和 legacy 快照仍保留。
- v2 JSON 15 个文件可解析，11 个工具目录和 178 个外部引用检查通过。
- education-resources 源码和测试语法编译通过。
- 修改文档的本地链接检查通过，`git diff --check` 通过。
