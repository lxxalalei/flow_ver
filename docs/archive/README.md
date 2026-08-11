# 历史文档归档

这里保存迁移前的设计蓝图和阶段性规划。它们用于理解背景、审计取舍和查找历史证据，
**不是当前运行时契约，也不是默认阅读入口**。当前事实以机器契约、运行时代码和
[当前架构事实快照](../CURRENT_ARCHITECTURE.md)为准；长期路线以
[开发路线图](../DEVELOPMENT_PLAN.md)为准；执行中的工作以对应的
`.agent/plans/` 计划为准。

## 归档索引

| 文档 | 原路径 | 文档日期 | 历史定位 | 当前替代文档 |
| --- | --- | --- | --- | --- |
| [flow_ver 下一阶段详尽规划与执行计划](flow_ver_下一阶段详尽规划与执行计划_2026-08-08.md) | `docs/flow_ver_下一阶段详尽规划与执行计划_2026-08-08.md` | 2026-08-08 | 针对 0017–0024 的阶段性收口规划、审计记录和后续交接 | [当前架构](../CURRENT_ARCHITECTURE.md)、[开发路线图](../DEVELOPMENT_PLAN.md)、[0027 平台获取能力接入](../../.agent/plans/archive/0027-platform-acquisition-enablement.md) |
| [flow_ver 资源检索系统 v2 总体规划与执行计划](flow_ver_资源检索系统_v2_总体规划与执行计划.md) | `docs/flow_ver_资源检索系统_v2_总体规划与执行计划.md` | 2026-08-07（执行记录始于 2026-08-08） | 早期总体设计、阶段执行日志和迁移背景 | [当前架构](../CURRENT_ARCHITECTURE.md)、[开发路线图](../DEVELOPMENT_PLAN.md) |
| [Resource Retrieval Agent 系统设计与实现方案](Resource_Retrieval_Agent_系统设计与实现方案.md) | `docs/Resource_Retrieval_Agent_系统设计与实现方案.md` | 2026-08-07 | 独立的早期产品/系统设计蓝图，描述 Intent → Plan → Search → Evaluate → Fetch → Archive | [当前架构](../CURRENT_ARCHITECTURE.md)、[开发路线图](../DEVELOPMENT_PLAN.md)、[active Skill](../../skills/learning-resource-flow/SKILL.md) 与 [MCP 契约](../../mcp/education-resources/contracts/README.md) |

## 历史 Skill reference 路径

0031/0032 文档收敛后，active Skill reference 只保留六个主题入口。归档文档中出现的旧文件名保持其历史语义，不表示这些旧路径仍存在。对应关系如下：

| 历史 reference | 现行入口 |
| --- | --- |
| `intent-and-clarification.md`、`response-guidelines.md` | `conversation.md` |
| `adaptive-retrieval.md`、`candidate-judgment.md` | `retrieval.md` |
| `discovery-strategy.md`、`platform-capabilities.md`、`site-whitelist.md` | `source-routing.md` |
| `inspection-strategy.md` | `inspection.md` |
| `acquisition-strategy.md`、`mcp-workflow.md` | `acquisition.md` |
| `library-structure.md` | `library.md` |

现行入口均位于 [`skills/learning-resource-flow/references/`](../../skills/learning-resource-flow/references/)；历史正文不回写为当前设计，以免篡改当时的审计与规划记录。

历史完成计划另见 [计划归档索引](../../.agent/plans/archive/README.md)；已完成计划和本目录都不是默认必读内容。
