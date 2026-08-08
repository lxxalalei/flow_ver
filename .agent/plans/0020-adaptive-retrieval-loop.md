# Adaptive Retrieval Loop

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：SearchRun provenance、immutable ResultSet extend、Coverage/Gap/Stop、Skill SearchDirection 与 golden retrieval benchmark

## 目标与边界

把一次性搜索升级为可解释的 `Plan -> Search -> Evaluate -> Inspect -> Gap -> Replan` 循环，
同时保持 ResultSet 不可变、现有下载/选择绑定不被绕过。0019 Inspection 作为证据增强入口，
0020 不扩张为下载、网页物化或浏览器快照。

公共兼容方案须先通过审计再冻结。优先评估在 `resource_search` 上增加可选 extend 输入和
有界 provenance/coverage 输出，保持既有调用仍可工作；不预设 contract major 版本，
也不为未来字段先伪造运行时状态。

## 初步架构问题

- `mode=replace|extend` 与 `base_result_set_id` 的条件约束及旧调用默认值。
- 新 ResultSet 是否复制并重新分配 opaque `resource_id`，以及 Presentation/Selection 如何失效。
- `round`、`direction_id`、platform/query、candidate/failure/new_unique/duplicate 的权威来源。
- provenance 使用现有持久化 JSON 快照还是需要前向 migration；不得仅为形式新增表。
- Coverage/Gap 如何从目标、显式 constraints、ResourceType、平台与 Inspection 事实计算，避免模型伪造。
- 信息增益低、硬约束已覆盖、重复率高、来源失败时的停止或重规划条件。

## 步骤

- [x] completed：并行审计当前 Search/ResultSet/Schema/Skill 与总体规划，冻结兼容边界
- [x] completed：实现 SearchDirection、Coverage、Gap、Stop 的内部有界模型与 golden cases
- [x] completed：实现 immutable ResultSet extend、跨轮 Identity/Dedup 与 provenance 持久化
- [x] completed：更新 `resource_search` 契约、server/service/storage 与恢复输出
- [x] completed：更新 Skill discovery/inspection/retrieval loop 策略与用户解释
- [x] completed：更新架构、契约、总体规划和 0021 启动条件
- [x] completed：根智能体运行相关契约、快照、语义 golden、回归、编译、链接和差异验收
- [x] completed：完成 0020，规划并启动 0021 Acquisition Core + Web Materializer

## 验证矩阵

- Compatibility：旧 `resource_search` 调用与既有 13 tools 保持可用；新增字段严格有界。
- Immutability：extend 创建新 ResultSet；base ResultSet、Presentation、Selection 不被改写。
- Provenance：每轮/方向/平台/查询的计数可恢复，不由模型手写权威状态。
- Dedup：base 与新增候选跨轮去重，new_unique/duplicate 可复算。
- Semantics：Coverage/Gap/Stop golden cases 覆盖探索、教材同步、家长参考、多形态资源和失败来源。
- Recovery：`resource_flow_status` 能恢复当前 ResultSet 及检索循环状态。
- Regression：Inspection、Search、Browse、Presentation、Selection、Download、Archive、Library 不回归。

## 结果

- 兼容边界已冻结：复用 `resource_search`；省略 `mode` 等价于 `replace`，`extend`
  必须绑定当前 Flow 的 `base_result_set_id`；`limit` 表示新快照总容量；Provider 接口不变。
- 版本边界已冻结：`contract_version` 保持 `1.0.0`，兼容扩展将
  `catalog_version` 提升到 `1.2.0`，不增加公共工具或动作名。
- ResultSet 继续不可变；extend 复制 base 候选、跨轮去重并为新快照分配新的 opaque
  `resource_id`。Storage 在最终事务内复核 task version 与 current ResultSet，防止陈旧 base
  或并发 extend 覆盖。
- Migration 4 只持久化可恢复、可复算的 SearchRun/ResultSet 事实：mode、base、round、
  task version、provider query runs、identity evidence、provenance 与事实 coverage；不提前引入
  `resource_discovery_state_save`。
- 内部 adaptive evaluator 固定 7 个 Coverage 维度、3 档 Gap severity、4 种 StopDecision、
  常规 3 轮/综合 4 轮预算和连续两轮无信息增益停止；18 个 golden cases 覆盖澄清、补搜、
  展示、认证、策略、unsupported、重复和多形态。
- 根验收运行 education-resources 本地 MCP 回归 279/279 通过；新增 adaptive contract 6/6、
  golden 4/4、extend storage 4/4、migration 5/5、retrieval service 5/5 均包含在内。
  `compileall`、33 条本地 Markdown 链接和 `git diff --check` 通过。
- 未执行真实平台网络或 OpenClaw doctor/probe；这些属于 0023 E2E 环境验收。未提交、未推送。
