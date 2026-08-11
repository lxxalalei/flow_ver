# 教育资源 OpenClaw evergreen 开发路线

## 文档定位

这是项目唯一长期技术路线。它只记录产品目标、阶段顺序和完成门槛；当前机器事实见 [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)，具体执行记录见 `.agent/plans/`。

当前 active 产品只有：

- `skills/learning-resource-flow/`：唯一用户入口与对话/语义编排；
- `mcp/education-resources/`：Python stdio MCP，负责搜索事实、Resolution、Plan、Job、Asset 与 Archive。

## 当前路线

2026-08-11 经过真实 E2E 和架构复核后，项目顺序调整为：

```text
0037 获取状态链简化
  -> 0028 真实 OpenClaw / 真实平台 E2E（基于简化模型重验）
  -> 0029 检索 benchmark 与 release gate
  -> 主体架构阶段完成
  -> 平台扩展 / Library & Viewer / 质量优化
  -> 平台化部署
```

0025/0027 的历史工作仍保留为迁移证据，但其中 Descriptor → Readiness → Eligibility → binding digest 的运行时权威链已被 0037 明确废弃。保留的是它们验证出来的业务原则：Representation 要真实、Provider 要明确、失败不能静默换路、认证与策略边界要显式。

## 产品目标

用户应能通过自然语言完成完整教育资源闭环：

```text
表达需求
  -> 必要澄清
  -> 多轮但有上限的搜索
  -> 候选语义审查
  -> 必要 Inspect
  -> 展示差异
  -> 用户选择
  -> 获取计划
  -> 用户确认
  -> 获取与进度
  -> Asset / Bundle
  -> 归档与再次查找
```

成功不等于“Tool 调用成功”或“搜到很多链接”。成功意味着：结果符合目标、关键事实可解释、用户明确控制副作用、实际资源能正确获取并恢复。

## 不可变架构约束

### 1. 语义判断与事实状态分开

MCP 保存事实：ResultSet、Resolution、Selection、Plan、Job、Asset 等。

Skill 私有完成：

- SemanticReview；
- Gap；
- StopDecision；
- 是否继续搜索；
- 是否需要 Selective Inspect；
- 如何解释候选差异。

不把“候选数量”“标题命中”或固定评分器当作自动 Present 条件。

### 2. 获取链保持业务化

获取只保留：

```text
Resolution / Representation
  -> AcquisitionPlan
  -> 用户确认
  -> Job / JobItem
  -> exact Provider
  -> Outcome
  -> Asset / Bundle
  -> Archive
```

不重新引入：

- Capability Descriptor 持久 binding；
- Readiness Snapshot 持久状态；
- Eligibility Decision 持久状态；
- `authority_digest`；
- `plan_binding_digest`；
- `execution_binding_digest`；
- `outcome_digest`。

Provider 能力用轻量配置和运行时检查表达。需要防止串错时优先使用 server-owned ID、数据库关系、状态机、事务和显式版本，不用 SHA-256 给服务端自己的状态做多层“防伪”。

### 3. 精确 Provider，但不做静默 fallback

Plan 选择哪个 Provider，Start 就执行哪个 Provider。失败后：

- 返回真实失败；
- 需要改变路线时重新 Inspect / Prepare；
- 不在 Router 内按平台名、资源类型或错误码偷偷切 generic Provider。

`web_materialize` / `web_capture` 是执行机制，不是“失败后的万能兜底”。

### 4. Representation 是核心业务事实

系统必须区分：

- `primary_resource`；
- `representation`；
- `landing_page`；
- `metadata`。

特别是网页：文章正文网页可以是 `primary_resource + web_materialize`；导航/预览页才是 landing page。

### 5. 保留真正必要的安全边界

简化不能删除：

- `prepare -> 用户明确确认 -> start`；
- Selection / Plan 版本与幂等；
- Start 前重新检查当前 Representation；
- SSRF 与逐跳重定向；
- 受控任务目录；
- 取消、超时和失败恢复；
- 内容类型与真实格式检查；
- 登录、验证码、付费墙、DRM 和访问控制边界；
- Archive 只接受服务端 `asset_id`。

文件 `sha256` / `byte_size` 只作元数据与去重信息，不恢复为通用下载验收门禁。

## 当前阶段：0037 Acquisition State Simplification

### 目标

把 0025/0027 形成的“能力权威证明系统”降级为简单获取业务模型，同时不破坏搜索、Inspect、Provider、Asset 与 Archive 的成熟实现。

### 已完成

- 新增轻量 `AcquisitionPlanner` / `ProviderSpec`；
- generic document、generic primary webpage、generic landing webpage、SmartEdu document 的简化 Provider route；
- MCP runtime 切到 `simple_service.ResourceService`；
- migration 8 新增 `acquisition_plan_items`、`job_items`、`execution_outcomes`；
- 新写入不再产生 Readiness/Eligibility/binding/outcome digest；
- `resource_download_start` 删除 `authority_digest`；
- PlanItem / JobStatus / Outcome 公共 Schema 删除 capability/readiness/eligibility digest 组；
- tool catalog 升至 `1.6.0`；
- 文章正文网页允许作为 primary resource 物化；
- 完成一次 GitHub Actions 定向验证：包安装、compileall、JSON 契约解析和 0037 定向测试均通过。

### 仍需完成

1. 清理旧 authority 专项测试；
2. 将 0037 前的 `capability.py`、旧 acquisition authority 代码从兼容基座中彻底移除；
3. 增加 cleanup migration，在兼容期结束后删除 v6/v7 旧 authority 表；
4. 同步 Skill 中仍残留的 capability/readiness/eligibility 文案；
5. 用真实 OpenClaw 部署简化后的 MCP 后重新跑完整业务回合；
6. 0037 完成后归档计划并恢复 0028 主线。

### 完成门槛

- Active runtime 不再 import 或写入 capability authority 链；
- 公共 Tool/Schema 不再暴露已删除字段；
- migration 8 新库和 v7 升级库都能正确恢复；
- Prepare/Start 能处理 document、primary webpage、landing webpage；
- exact Provider 失败不 silent fallback；
- Job 成功/partial/失败/取消、Asset/Bundle、Archive 关系不依赖 digest；
- 真实 Agent 至少完成一个 generic Search → Inspect → Select → Confirm → Acquire → Archive → Recover 成功闭环。

## 下一阶段：0028 Real OpenClaw and Real Platform E2E

0037 结束后重新执行 0028，但证据模型改为业务事实，而不是证明每一层 digest。

### 要验证的用户闭环

```text
Search
  -> Inspect
  -> Present
  -> Select
  -> Prepare
  -> Confirm
  -> Start
  -> JobStatus
  -> Asset/Bundle
  -> Archive
  -> Restart / Recover
```

### 覆盖类型

- 文章正文网页；
- 普通网页/landing page；
- 文件型文档/图书；
- 视频；
- 音频；
- 课程/Bundle；
- 混合来源；
- AUTH_REQUIRED / policy / dependency / unavailable 等失败恢复。

### 证据要求

逐平台记录：

- Search 是否真实命中；
- Inspect 是否能确认 Representation；
- Provider 是否实际部署；
- session/auth 是否真实可用；
- Plan route；
- Job/Outcome；
- Asset/Bundle；
- Archive；
- 重启后恢复。

不能用 Adapter 已注册、fixture、doctor/probe 或单元测试替代真实用户闭环。

### 平台恢复原则

0036 中对具体平台的恢复工作仍可继续，但按以下方式接入：

```text
Platform Search / Inspect
  -> Representation
  -> 新增/复用 ProviderSpec
  -> exact Provider
```

不为每个平台新增 Descriptor/Readiness/Eligibility 状态实体。

## 0029 Retrieval Benchmark and Release Gate

0037 与 0028 稳定后再做 benchmark，重点度量业务行为：

- relevance；
- 是否过早 Present；
- Gap 是否准确；
- Replan 是否改善结果；
- Clarify 是否必要；
- Inspect 是否有效；
- 来源多样性和去重；
- Provider route 是否真实；
- Plan / Job / Outcome / Asset 是否一致；
- 真实平台失败是否被如实呈现。

benchmark 不应把当前实现细节写成 gold，更不能通过测试强迫代码维持已废弃架构。

P0 门禁应聚焦：

- 用户未确认却产生副作用；
- 错资源/错 Provider 被获取；
- silent fallback；
- 伪造成功；
- 归档非 ready Asset；
- 绕过认证/访问控制；
- 真实结果明显不符合用户目标却被自动 Present。

## 主体架构阶段完成边界

0037、0028、0029 完成后，主体架构才算稳定。至少满足：

- 搜索的 SemanticReview / Gap / StopDecision 权威位置稳定；
- Planner 能准确区分 primary / representation / landing / metadata；
- 获取链没有多层自证状态；
- 真实 Agent 能完成完整资源闭环；
- benchmark 以业务行为而不是当前代码实现为准；
- 扩平台只需要 Search/Inspect/ProviderSpec/Provider，不需要复制控制面；
- Library/Archive 可以稳定消费 Asset/Bundle。

## 产品成熟阶段

### Platform Expansion

按真实用户价值决定优先级，逐步恢复/新增平台：

- 视频：Bilibili、公开课程平台等；
- 音频：Ximalaya 等；
- 图书/文档：合法公开图书馆、教材、文档来源；
- 网页：文章正文、图文页面、复杂网页物化；
- 课程：课程页、视频、讲义和字幕 Bundle。

平台扩展的核心不是“支持平台名”，而是能把 Search 命中解析成真实 Representation 并通过明确 Provider 获得正确资产。

### Library & Viewer

在获取链稳定后完善：

- 资料库浏览；
- 分类/主题筛选；
- 资源预览；
- HTML/Markdown Viewer；
- 图片与附件关联；
- Bundle 展示；
- 去重和版本关系；
- 再搜索/再获取入口。

### 持续质量优化

后续改动优先回答：

1. 用户实际行为是否更好？
2. 是否增加了新的状态实体或重复投影？
3. 新复杂度能否由真实业务失败证明必要？
4. 能否用更简单的数据关系、事务或测试替代？

禁止因为“以后可能需要”提前建立复杂控制面。

## 平台化部署

远程 Streamable HTTP、多租户隔离、正式 Secret 管理、配额与可观测性等属于后续部署阶段。它们不能反向迫使本地单用户产品提前采用分布式系统式的防伪/签名状态链。

## 历史路线说明

0025/0027、0036 等文件保留作为历史决策和问题证据。若其内容与本文冲突：

- 业务事实可继续引用；
- 已被 0037 废弃的 architecture binding 不再恢复；
- 0030 已移除的文件哈希/大小验收门禁不因旧计划描述而恢复。

相关入口：

- [当前架构事实](CURRENT_ARCHITECTURE.md)
- [0037 获取状态链简化](../.agent/plans/0037-acquisition-state-simplification.md)
- [0028 真实 OpenClaw / 平台 E2E](../.agent/plans/0028-real-openclaw-platform-e2e.md)
- [0029 检索 benchmark](../.agent/plans/0029-retrieval-benchmark-release-gate.md)
- [Retrieval Authority ADR](RETRIEVAL_AUTHORITY.md)
