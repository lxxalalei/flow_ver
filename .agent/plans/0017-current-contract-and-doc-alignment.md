# 当前契约与文档收敛

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：当前架构事实快照、根级文档、education-resources 契约文档、工具目录一致性测试，以及总体规划进度同步

## 目标与边界

本计划只消除当前代码事实和文档事实之间的漂移，不增加业务功能。当前机器事实以
`mcp/education-resources/contracts/tool-catalog.json`、Schema、运行时工具注册和 Adapter
注册代码为准。统一后的公开口径应为 `contracts/`、协议 `1.0.0`、catalog `1.0.0`、
12 个工具，并明确包含 `resource_browse_creator`。

本阶段由根智能体负责范围控制、冲突处理和最终验收；并行子智能体统一使用
`gpt-5.6-luna`、`reasoning_effort=max`，写入范围必须互不重叠。

## 步骤

- [x] completed：读取根 AGENTS、总体规划、计划规范，确认分支与干净工作树
- [x] completed：并行核对根文档、MCP 契约/运行时和测试基线，形成精确修改清单
- [x] completed：生成 `docs/CURRENT_ARCHITECTURE.md` 并统一根 README、TOOLS 和开发路线
- [x] completed：由根智能体修正 AGENTS 中已漂移的 active contract 路径与版本治理口径
- [x] completed：统一 education-resources README、领域契约和兼容说明中的路径、版本与工具清单
- [x] completed：增加机器目录、运行时工具和关键文档的一致性检查
- [x] completed：根智能体审查并整合全部改动，处理跨文件冲突和语义偏差
- [x] completed：执行文档链接、Schema、相关测试、`git diff --check` 与最终工作树核对
- [x] completed：更新总体规划进度与本计划结果，规划并启动 0018

## 验证

- 当前分支、提交、契约版本、catalog 版本、工具数量、工具名称、资源类型和 Adapter 列表快照
- 所有契约 JSON 解析、本地 `$ref` 与 catalog Schema 检查
- 新增的一致性测试与受影响的现有契约测试
- 修改 Markdown 的本地链接和文件存在性检查
- `git diff --check`
- `git status --short --branch`

## 架构决策

- 0017 采用总体规划指定的当前机器事实：active contract 位于
  `mcp/education-resources/contracts/`，协议与 catalog 均为 `1.0.0`，公共工具为 12 个。
- 根 `AGENTS.md` 中的 `contracts/v2/` 约束是迁移后的历史漂移；必须在本阶段由根智能体
  显式修正，避免后续 Agent 按不存在的目录实施。该修正不改变其他安全、计划或验证约束。

## 结果

- 当前事实已统一为 `contracts/`、协议/catalog `1.0.0`、12 个工具；根 AGENTS、README、
  TOOLS、开发路线、MCP README 与领域契约已同步，新增 `docs/CURRENT_ARCHITECTURE.md`。
- `tool-catalog.schema.json` 已从 11 工具修正为 12 工具；`resource_browse_creator` 已补齐
  `search_run_id`、有效 `$ref`、统一平台运行记录和独立幂等范围，并增加一致性与回归测试。
- 隔离 Python 环境运行 29 项相关测试全部通过；`compileall`、15 条本地 Markdown 链接和
  `git diff --check` 通过。未运行全量测试、真实网络 Adapter 测试或 OpenClaw probe；本机
  未发现 `openclaw`。
- 任务生成的 `.DS_Store`、wheel `build/` 和隔离验证环境已分别移动到废纸篓
  `/Users/arale/.Trash/flow2-0017.DS_Store`、`flow2-0017-build`、
  `flow2-0017-verification`，均可恢复；工作区没有保留验证产物。
- 总体规划文档当前位于 `docs/flow_ver_资源检索系统_v2_总体规划与执行计划.md`，0018 已启动。
