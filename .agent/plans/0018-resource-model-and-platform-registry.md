# Resource Model 与 Platform Registry

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-08
- 范围：education-resources 内部 Retrieval 模型、Resource Identity、Candidate 去重、平台能力 Registry、Adapter descriptor、搜索兼容接入、Skill 参考和测试

## 目标与边界

本阶段建立 `Resource != URL != Asset` 的内部语义模型，并把平台能力从 Prompt 常识升级为
机器可校验的 Registry。保持公共契约 `1.0.0`、现有 12 个工具、SQLite Schema、随机
`resource_id`、搜索输出和下载/归档语义不变；不实现 `resource_inspect`，不新增数据库迁移。

根智能体负责身份规则、兼容边界、跨工作包整合和最终验收；子智能体统一使用
`gpt-5.6-luna`、`reasoning_effort=max`，并按互不重叠的文件范围并行交付。

## 架构决策

- 内部新增 `retrieval/`，不把 Retrieval 内部模型继续塞入 MCP 输入模型 `models.py`。
- Identity 优先级：平台 native identity -> ISBN -> DOI -> 平台感知 canonical URL ->
  标题/作者/版本弱指纹；强身份冲突不得自动合并。
- URL 全局只安全移除 fragment；query 参数只能按平台 identity profile 决定是否清理。
- 同一候选重复时保持首次顺序，后续候选只补充缺失事实，不覆盖强身份或已有权威值。
- `resource_id` 继续由服务端生成；内部 Identity 不作为模型可提交或可伪造的业务 ID。
- 能力 Registry 与 `sessions.py` 的登录态 registry 分离；0018 中所有 `inspect` 能力保持 false。

## 步骤

- [x] completed：完成 0018 只读架构预研、现状审计、文件边界和测试矩阵
- [x] completed：建立身份与去重 Golden Cases；DOI URL 与 ISBN-10/13 等价性已修正并验收
- [x] completed：完成 Retrieval 内部模型、Identity Resolver 与稳定 Candidate Dedup；补齐跨平台 ISBN + native ID Golden Case，根复跑 23 项测试通过
- [x] completed：完成 Platform Registry Schema、16 平台数据和严格加载器；URL identity profile 与内置 fallback 已锁定一致
- [x] completed：为 generic 与全部 active Adapter 增加不可变 descriptor，并校验 Registry 一致性；legacy stub 保持兼容
- [x] completed：统一 normalizer/dedup 已接入 `resource_search` 与 `resource_browse_creator`；相关隔离环境验收通过
- [x] completed：生成 Skill 平台能力参考，更新契约/架构文档和总体规划进度
- [x] completed：根智能体审查整合，运行相关测试、Schema、链接、编译和差异检查
- [x] completed：完成 0018，创建并启动 `0019-inspection-layer.md`

## 验证

- Identity：BV、aweme、知乎对象、喜马拉雅 album、Anna MD5、ISBN、DOI、fragment、
  SmartEdu query、跨平台同值和强身份冲突
- Dedup：首次顺序、缺失字段补充、版本差异、limit、跨 query/platform 行为和幂等重放
- Registry：JSON Schema、16 平台唯一性、合法 resource types、无凭据/路径、Adapter descriptor 一致
- 兼容：现有 `resource_search`、`resource_browse_creator`、1.0.0 契约和相关服务测试
- Python 编译、修改 Markdown 链接、`git diff --check`、`git status --short --branch`

## 结果

- 已交付 private Retrieval 模型、平台感知 Identity Resolver、稳定 Candidate Dedup、16 平台
  Registry/Schema/严格 loader、generic 与 15 个内置 Adapter descriptor，以及 Search/Browse
  共用的服务端候选归一化路径。
- 根智能体在隔离 Python 环境运行 0018 相关 Identity、Dedup、Registry、Adapter、Search、
  Browse、Service、Contract 和 Control Plane 104 项测试，全部通过；Registry JSON Schema、
  `compileall`、16 项 Skill 平台表一致性、22 条本地 Markdown 链接和 `git diff --check` 通过。
- 未运行全量测试、真实平台网络测试或 OpenClaw doctor/probe；当前机器未发现 OpenClaw。
  这些不阻止 0018 内部架构完成，但平台生产可用性仍需逐平台合法授权与真实环境验收。
- 未提交、未推送、未创建分支；下一阶段已在 `.agent/plans/0019-inspection-layer.md` 启动。
