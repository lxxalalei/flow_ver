# 当前架构事实

> 快照日期：2026-08-11
>
> 本文是当前工作树的人类可读事实快照，不是第二套运行时契约。

## 事实优先级

发生冲突时，按以下顺序确认事实：

1. `mcp/education-resources/contracts/` 中的机器 catalog、Schema、错误码和 capability 声明；
2. `mcp/education-resources/src/education_resource_mcp/` 中的运行时注册、服务、存储、策略和 Adapter；
3. 本文和其他说明文档；
4. `legacy/`、`docs/archive/` 和已完成计划中的历史描述。

历史文档不能覆盖当前机器事实；代码中已注册或 Registry 中已声明，也不能单独证明某个平台
当前可用、某个候选存在具体资源表示，或一次获取已经成功。

## 1. Active 边界与机器版本

| 项目 | 当前事实 |
| --- | --- |
| 唯一用户入口 | `skills/learning-resource-flow/` |
| MCP 服务 | `mcp/education-resources/`，Python stdio MCP |
| MCP server | `education-resources`；实现 metadata `0.2.0` |
| 公共契约 | `contract_version=1.0.0` |
| 公共工具目录 | `catalog_version=1.5.0`，机器目录和运行时均为 13 个工具 |
| 平台 Registry | `registry_version=1.0.0`，固定 16 个平台身份/检索/历史声明 |
| Capability Descriptor catalog | `catalog_version=1.1.0`、`registry_version=1.1.0` |
| SQLite | 最新 migration `7`；包含 capability authority 和 fresh Job execution binding |
| Legacy | `legacy/skill-pipeline-v1/`，只读迁移、审计和显式回滚证据，不参与 active runtime |
| 运行数据 | SQLite、凭据、Cookie、浏览器档案和下载资产位于源码工作区之外；测试数据使用 `.openclaw-test/` 或临时目录 |

### Active 主链

```text
用户自然语言
  -> learning-resource-flow Skill
  -> education-resources stdio MCP
  -> ResourceService
  -> Search / Inspect / Capability coordination
  -> exact Acquisition Provider
  -> SQLite 权威状态 + 受控 Asset
```

### 业务状态链

```text
FlowTask -> ResultSet -> Presentation -> Selection
         -> DownloadPlan / PlanItem
         -> immutable Job ExecutionItem -> Acquisition Outcome
         -> AssetBundle / BundleItem -> Asset -> Archive
```

能力真值链独立于搜索命中：

```text
Static Capability Descriptor
  -> Deployment Readiness
  -> candidate Resolution / Representation
  -> Eligibility
  -> PlanItem + authority_digest
  -> fresh ExecutionItem
  -> exact Provider
  -> persisted Actual Outcome
```

`resource_inspect` 只新增或刷新候选的 Resolution/Representation，不改写不可变 ResultSet。显式
representation evidence 使用半开有效区间 `observed_at <= now < expires_at`：过期 cache 走真实
Inspector 并返回 `cache_status=refresh`；Prepare 和 Start 都拒绝过期或未来时间的 evidence。
`session-manager` 是独立的会话/授权 MCP，不属于本服务的公共 catalog。

## 2. 公共 MCP 工具

工具名称和 Schema 以 `contracts/tool-catalog.json` 及 `server.py` 为准。当前工具按领域职责分为：

| 工具 | 作用 | 副作用 |
| --- | --- | --- |
| `resource_flow_start` | 创建 FlowTask | 写状态 |
| `resource_flow_status` | 返回可恢复 Flow 快照 | 读状态/更新时间戳 |
| `resource_search` | 搜索并保存不可变 ResultSet | 写结果集 |
| `resource_presentation_save` | 固化实际展示集合和顺序 | 写展示 |
| `resource_selection_save` | 保存用户从展示集合中选择的资源 | 写选择 |
| `resource_download_prepare` | 生成下载计划和确认摘要，不下载 | 写计划 |
| `resource_download_start` | 在确认和重新校验后启动 Job | 启动异步任务 |
| `resource_job_status` | 查询 Job、Outcome、Asset/Bundle 摘要 | 读状态 |
| `resource_job_cancel` | 请求并持久化取消 | 控制 Job |
| `resource_archive` | 将服务端 Asset 归档 | 写资料库 |
| `resource_library_search` | 查找已归档 Asset/Bundle | 读资料库 |
| `resource_browse_creator` | 浏览创作者内容并保存结果集 | 写结果集 |
| `resource_inspect` | 对当前 Flow 中单个候选做有界核验 | 写 Resolution |

工具不会把平台 Adapter 暴露成一组额外的 MCP Tool。模型只能使用服务端生成并重新校验的
`flow_id`、`resource_id`、`plan_id`、`job_id`、`asset_id` 等稳定 ID；不得提交任意路径、脚本、
解释器、下载 URL 或确认令牌来替代这些业务事实。

## 3. 检索、能力和获取边界

- `resource_search.coverage` 是 MCP 根据 ResultSet 实际观察到的候选、来源、去重和失败事实生成的
  factual 摘要；它不表示语义充分性、推荐、Skill 的 `Gap` 或 `StopDecision`。
- `retrieval/` 的 resource model、identity resolver 和保守 dedup 是 MCP 内部实现；内部 identity
  不等于公共 `resource_id`。普通搜索与创作者浏览共用规范化和去重边界。
- `retrieval/adaptive.py` 只作为离线 oracle/calibration helper，不搜索、Inspect、下载、归档、
  写入公共状态，也不是 `ResourceService` 的生产 factual-state 依赖。语义审查、Gap 和停止决策
  由唯一入口 Skill 私有完成，边界见 [Retrieval Authority ADR](RETRIEVAL_AUTHORITY.md)。
- 平台 Registry 只是平台身份、检索和历史能力声明；静态 Capability Descriptor 只是设计上支持的
  platform/resource/scope/strategy/Provider/Inspector 声明。两者都不证明 deployment readiness、
  candidate Representation、当前 Eligibility 或 Provider 成功。
- 当前源码包含多平台 Search/Inspect/Acquisition Adapter；其中 Registry/Adapter 已注册不等于
  平台已通过真实网络、合法会话、版权/策略和用户闭环验收。0027 已完成逐项正式接入或结构化阻断；
  真实环境与用户闭环证据由当前 0028 验收。
- 获取路线必须保持同一条 descriptor → readiness → resolution → eligibility → plan → execution →
  exact provider → outcome 链；禁止按平台名、资源类型或失败结果隐式切换 generic Provider，
  `web_capture` 也不是静态失败或认证失败的自动 fallback。
- 当前机器 catalog 的可执行设计面仍只有 generic direct、generic landing materialize 和 SmartEdu
  direct。Bilibili、Douyin、Ximalaya、Anna/Libgen 与 `web_capture` 经 0027 审计后分别保持
  policy/auth/dependency/unsupported 阻断；没有 descriptor 和 exact Provider 时以
  `CAPABILITY_NOT_DECLARED` fail closed，不能被 Platform Registry 的历史 `acquire=true` 覆盖。

## 4. 安全和持久化不变量

- 有副作用的下载严格采用 `prepare -> 用户明确确认 -> start`，每次调用重新校验 Flow ownership、
  来源、选择、计划、权限、状态、幂等键和 authority digest。
- Job 是异步资源；状态至少区分 `queued`、`running`、`cancelling`、`succeeded`、`failed`、
  `cancelled`。Bundle 的 `completion=partial` 表示成员不完整，不新增 Job `partial` 状态。
- Acquisition Outcome 在单项执行中可为 `running`；公共 `outcome_status` Schema 已接受该既有
  runtime 状态，但它不替代 Job 生命周期，也不赋予客户端创建或改写 Outcome 的权限。
- `resource_archive` 只接受服务端返回的 `asset_id`，不接受模型提供的文件路径；二进制和大文件
  不进入模型上下文或 Tool JSON。
- 网络只允许 `http`/`https`，必须执行 SSRF、逐跳重定向、域名/策略、超时、重试、并发、大小、
  内容类型和真实文件格式校验；不绕过登录、验证码、付费墙、DRM 或明确访问控制。
- stdio MCP 是进程边界，不是沙箱；本地进程权限、工作目录、网络出口和环境变量仍需最小化。

## 5. 当前执行顺序

0025 Platform Capability Contract Alignment 已于 **2026-08-10** 完成，0027 Platform Acquisition
Enablement 已于 **2026-08-11** 完成。当前唯一技术顺序为：

1. **0028 Real OpenClaw and Real Platform E2E**（当前执行）：在合法会话和真实网络边界内，验证默认 Agent
   从自然语言完成 Search → Inspect → Present → Select → Confirm → Acquire → Archive → Recover。
2. **0029 Retrieval Benchmark and Release Gate**（后续）：建立版本化离线 benchmark、质量/真实性指标、
   critical invariant 和可审查发布门禁；真实 Agent 证据与离线分数分层报告。

## 6. 已知未验收边界

以下事项当前不能声称完成：

- 默认 OpenClaw Agent 的完整自然语言教育资源业务回合尚未完成。0028 已验证合法 generic 文章
  Search → Inspect → Present、多个真实平台失败/恢复路径和状态恢复；用户已明确选择第 1 个文章候选，
  过期 Resolution cache 的 P0 门禁缺口已修复并真实刷新。随后生成的 landing-page Plan 已过期且未
  Start；用户已质疑文章正文网页是否应按 landing page 获取，下一步先审计该产品/契约语义。尚无
  Job、Asset 或 Archive；doctor/probe 不等于该闭环。
- 16 平台本环境 readiness 与用户文案边界已经逐项审计，当前 `production_ready=fail` 为 `16/16`。
  这表示分级完成，不表示所有网络、合法会话、版权/策略或获取路径均已成功；Adapter、Descriptor、
  fixture 和单次 probe 仍不能升级平台状态。
- 当前 0028 OpenClaw 已注册独立 `session-manager`，education-resources 已配置同一受控 store bridge，
  其 runtime 可导入 0.4.0 包；4 个 session Tool 与原 13 个教育业务 Tool 的 live probe 均通过。
  用户明确授权的 SmartEdu canonical direct import 已最小保存为 `stored/no_probe`，但 fresh 真实 Agent
  Search 返回认证 HTTP 403、0 候选，未到达 Inspect，因此真实 AUTH_REQUIRED 恢复仍 blocked。不得退回
  legacy store、自动重放/变换当前值，或把安装、保存、probe、离线 marker 当作合法远端 session；新的
  direct import 仍须用户明确指定平台、用途并再次授权，且不得索取密码/验证码、转发、回显或写入仓库。
- 中断/重启、幂等、Selection/Plan 失效、取消、partial、无 primary、策略拒绝和归档限制已有真实或
  stdio 进程级证据，但真实平台 Acquisition → Asset/Bundle → Archive → Recover 尚未形成成功闭环。
- 0028、0029 的最终 release gate，以及远程 Streamable HTTP、多租户生产隔离和正式平台部署。

## 相关入口

- [工作区入口](../README.md)
- [工具跳转页](../TOOLS.md)
- [唯一 evergreen 开发路线](DEVELOPMENT_PLAN.md)
- [Retrieval Authority ADR](RETRIEVAL_AUTHORITY.md)
- [机器契约目录](../mcp/education-resources/contracts/README.md)
- [历史归档索引](archive/README.md)
