# Inspection Layer

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：`resource_inspect` 公共工具、Resolution 持久化、通用与首批平台 Inspector、恢复、Skill、契约和安全测试

## 目标与边界

本阶段让 Skill 能在展示候选前按服务端 `resource_id` 核验高潜资源，补充可比较的详情、
可用性和 Representation。工具不接受 URL、路径、Cookie、Token、批量 ID 或模型选择的
检查深度；服务端从当前 Flow 的候选中重新取得来源并执行网络策略。

保持既有 12 个工具输入输出和 `contract_version=1.0.0` 兼容；新增第 13 个工具属于 catalog
加法更新，`catalog_version` 升为 `1.1.0`，不创建 contract 2.0。SQLite 使用前向 migration 3，
ResultSet 快照不被 Inspect 改写。

根智能体负责公共形状、状态/缓存语义、安全边界、跨层整合和最终验收；子智能体统一使用
`gpt-5.6-luna`、`reasoning_effort=max`，写入范围互斥。

## 架构决策

- 首版 `resource_inspect` 一次只接受一个 `resource_id`，固定服务端 profile `inspect-v1`。
- 工具采用严格有界同步检查：单资源、有限请求、总超时和最大读取字节；不把网页深抓或浏览器
  快照塞入本阶段。超过边界的未来任务再设计异步 inspection job，不复用下载 `jobs` 表。
- 输入仅含 `contract_version`、`flow_id`、`resource_id`、`idempotency_key`，禁止 URL、
  `result_set_id`、批量、depth、凭据和路径。
- `resource_resolutions` 与 `resources/search_result_sets` 分表；Inspect 不修改不可变 ResultSet
  candidate 或 Presentation/Selection 绑定。
- 请求幂等范围为 `resource_inspect:{flow_id}`；同键同请求精确重放，不同资源冲突。
- 成功/partial Resolution 按 `resource_id + source_fingerprint + inspector_version` 缓存；
  重试性 unresolved 只由同一幂等键重放，新键允许重新检查。
- `resource_flow_status` 增加当前 ResultSet 的安全 Resolution 摘要，支持上下文压缩和 MCP 重启后恢复。
- Availability 仅使用 `available`、`auth_required`、`unavailable`、`unknown`、
  `policy_blocked`；HEAD 只是提示，格式声明需要受限 GET、Content-Type 与内容特征交叉核对。
- Inspector 不返回 locator URL、文件字节、本地路径或凭据；Representation 只返回受控元数据。
- 初始平台感知 Inspector：generic、bilibili、nlc、annas-archive、ximalaya、zhihu、smartedu。
  Registry 只为实际实现的平台开启 inspect；其他平台返回结构化 `FEATURE_NOT_SUPPORTED`，不
  静默伪装为已核验。

## 步骤

- [x] completed：完成契约、Adapter、安全与持久化三路只读预研，冻结首版边界
- [x] completed：新增第 13 个工具的 Schema/catalog/model/error 兼容测试
- [x] completed：新增 SQLite migration 3、Resolution/幂等缓存原子读写与恢复查询
- [x] completed：实现有界 Inspection Core、Generic Web Inspector 与安全测试
- [x] completed：并行实现 Bilibili/NLC/Anna/Ximalaya/Zhihu/SmartEdu Inspector 与固定夹具
- [x] completed：接入 ResourceService、server 和 flow_status 恢复输出
- [x] completed：更新 Platform Registry inspect 能力与 descriptor 一致性
- [x] completed：更新 Skill inspection gate、MCP/契约/架构文档和总体规划进度
- [x] completed：根智能体运行相关契约、迁移、安全、服务、stdio、编译、链接和差异验收
- [x] completed：完成 0019，规划并启动 0020 Adaptive Retrieval Loop

## 验证矩阵

- Contract：13 工具精确一致；旧 12 工具输出不变；URL、批量、depth 和额外字段被拒绝。
- Ownership：只能 Inspect 当前 Flow 的 `resource_id`；跨 Flow/不存在 ID 不泄露事实。
- Persistence：migration 2 -> 3、幂等 replay/conflict、缓存命中、重试性失败、新旧数据库恢复。
- Network：SSRF、DNS 私网、重定向、认证、404/410、429/5xx、超时、HEAD fallback、
  Content-Length/流式上限、MIME/内容不一致。
- Platform：七类固定夹具；Anna/Libgen 来源差异、SmartEdu identity query、Zhihu/Bilibili 合法会话边界。
- Recovery：flow_status 返回安全 Resolution 摘要，不返回来源 URL、凭据、文件路径或正文大对象。
- Compatibility：Search、Browse、Presentation、Selection、Download、Archive 和 Library 相关测试。

## 结果

- 公共契约工作包已交付并通过根验收：catalog 为 `1.1.0`、精确 13 tools，
  `resource_inspect` 输入仅接受冻结的四个字段；Inspect Schema 定向测试 4/4 通过。
- 第一轮持久化执行者只落地 migration 3 与存储实现，Inspection Core 执行者未形成文件；
  两个未完成实例已终止，保留可见改动并拆为更窄的 Luna Max 补测/核心任务重新派发。
- Resolution 存储补测已由第二轮 Luna Max 子任务交付并通过根验收：迁移、事务、幂等、
  cache、跨 Flow、当前 ResultSet 恢复、快照不变、并发与递归敏感字段剥离合计 11/11 通过。
- Inspection Core 已由第二轮 Luna Max 子任务交付并通过根验收：冻结结果、严格有界 JSON、
  稳定 source fingerprint、精确平台 Router、无 generic fallback 与敏感信息阻断合计 7/7 通过；
  本步骤余项为 Generic Web Inspector。
- Platform Registry 已精确启用 generic、Bilibili、NLC、Anna/Libgen、Ximalaya、Zhihu、
  SmartEdu 七个平台 inspect，其他九个平台保持关闭；Schema/loader/descriptor 相关 23/23 通过。
- Generic Web Inspector 已交付并通过根验收：注入式 resolver/transport、严格有界 GET、
  逐跳 SSRF/redirect 校验、1 MiB 声明与流式上限、HTML metadata、MIME/魔数冲突与稳定
  错误映射合计 18/18 通过；未访问真实网络。
- 六个平台 Inspector 已按两组交付并通过根验收：Bilibili/Zhihu/SmartEdu 相关 26/26，
  NLC/Anna-Libgen/Ximalaya 相关 26/26；均使用固定夹具、保留 availability/failure 状态，
  不读取登录凭据或返回 locator。
- Service/server 接入已交付并通过根验收：默认 Router 精确七平台，Flow ownership、同键 replay/
  conflict、resolved/partial cache、unresolved retry、并发单检查、快照不变、flow_status 恢复与
  第 13 个 MCP tool 相关 30/30 通过。
- Skill、根/MCP/契约文档已对齐；新增选择性 Inspection Gate、失败恢复、缓存与上下文恢复规则。
- 最终根验收：0019 合并相关 109/109 通过；`compileall` 通过；23 条本地 Markdown 链接通过；
  Registry/Skill 表为 16 平台、inspect 7 开 9 关；catalog/runtime 为 13 tools；
  `git diff --check` 通过。
- 未运行全量测试、真实平台网络或 OpenClaw doctor/probe；未提交、未推送。0020 已创建并启动。
- 当前静态 server/catalog 工具数不一致是集成前暂态，必须在本计划服务接入步骤消除后才能验收。
