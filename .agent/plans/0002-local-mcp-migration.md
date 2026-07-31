# 本地 MCP 首轮改造

> 历史说明：本计划记录首轮实现时的目录。2026-07-30 已由
> `0005-workspace-two-part-cleanup.md` 将 active 服务迁移到
> `mcp/education-resources/`，并把旧 Skill 隔离到 `legacy/skill-pipeline-v1/`。

- 状态：completed
- 创建日期：2026-07-29
- 完成日期：2026-07-29
- 范围：`contracts/`、`services/education-resource-mcp/`、`skills/learning-resource-flow/`、本地 OpenClaw 试验配置与相关文档

## 目标

在不删除旧 Skill、不依赖远端服务器的条件下，建立原生 OpenClaw 可调用的 Python stdio MCP 最小闭环。服务端成为 Flow、Selection、Download Plan、Job 和 Asset 的权威状态，并具备两阶段下载、幂等、取消、受控归档和本地恢复能力。

## 步骤

- [x] completed：固化现有测试与运行环境基线，确认 OpenClaw/MCP 本机能力。
- [x] completed：定义领域契约、错误模型、SQLite 状态机和安全策略。
- [x] completed：实现本地 Python stdio MCP 服务及领域级工具。
- [x] completed：补齐单元、契约、协议与安全测试并修复问题。
- [x] completed：生成 OpenClaw 本地配置并改造唯一入口 Skill 使用 MCP。
- [x] completed：跑通领域与 stdio 协议闭环，更新文档和计划状态。

## 首轮工具范围

- `resource_flow_start`
- `resource_search`
- `resource_selection_save`
- `resource_download_prepare`
- `resource_download_start`
- `resource_job_status`
- `resource_job_cancel`
- `resource_archive`
- `resource_library_search`

## 验证

- 现有离线测试基线。
- 新 MCP 服务的语法、单元、数据库状态机、安全、协议和工具契约测试。
- MCP stdio initialize、tools/list、tools/call smoke test。
- 本机存在 OpenClaw 时执行 `openclaw mcp doctor/probe`；不存在时提供可直接使用的注册配置与替代协议验证。
- 端到端覆盖 Flow、搜索候选、明确选择、prepare、确认、异步 Job、归档和检索。

## 回滚

- 不删除或移动旧 Skill。
- 新代码全部位于独立目录；入口 Skill 的修改保持可审查，旧阶段说明继续保留为兼容参考。
- MCP 失败时只允许回到旧流程或只展示来源，不允许静默执行不受控下载。

## 结果

- 新增 `contracts/v1/`，固化 9 个领域工具、31 个错误码、状态机和输入/输出
  JSON Schema。
- 新增本地 Python stdio MCP，使用 SQLite 持有 Flow、展示集合、Selection、Plan、
  Job、Asset 与归档状态；实现两阶段下载、幂等、取消、重启终结、资产隔离和安全
  网络/路径策略。
- `learning-resource-flow` 已成为专用 OpenClaw Agent 的唯一可发现入口，默认调用
  `education-resources` MCP；旧六阶段流程保留为显式 `legacy` 回滚后端。
- 旧流程 11 个测试文件共 75 项通过；新 MCP 26 项通过；入口 Skill 结构校验通过；
  官方 MCP 客户端完成 `initialize`、9 工具发现、全部输入字段契约核对和实际调用。
- OpenClaw MCP doctor/probe 已验证注册与 9 个工具。跨 Windows/WSL 混用安装曾导致
  CLI 挂起；2026-07-30 改为 WSL 原生 OpenClaw 后，status、doctor 和 probe 全部
  通过。随后已把 `glm-req/glm-5.2` 配置为默认模型，Provider probe 和最小真实
  Agent 回合成功，未使用 fallback；完整资源业务回合仍需在阶段 6 后续任务中验收。
- 生产迁移仍需把进程内 Job 外置为持久 Worker，把模型可见确认令牌升级为平台审批
  记录，并将资料库查询迁移为可信身份下的租户级查询。
