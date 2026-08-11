# Education Resource Domain Contract

协议版本：`1.0.0`。本文件说明当前领域不变量；工具的完整字段、枚举和 `additionalProperties`
规则只以 [`tool-catalog.json`](tool-catalog.json) 与 [`schemas/`](schemas/) 为准。

## 核心模型

- **FlowTask**：一次资源任务。它保存目标和有证据的显式约束；`user_role` 与
  `resource_target` 独立，可未知，不能互相推导或凭空补齐年龄、年级、教材版本、平台和格式。
- **ResultSet / Candidate**：一次服务端搜索或 creator browse 的不可变候选快照。候选不是已展示、
  已选择或已授权的资源。
- **Presentation**：Skill 实际展示给用户的有序候选集合。Selection 只能引用当前 Presentation，
  不能选择隐藏候选或凭空提交资源 ID。
- **Selection / DownloadPlan**：用户选择的服务端快照，以及由服务端根据当前展示、选择、解析结果、
  能力权威和策略生成的有期限计划。摘要和绑定由服务端计算。
- **Resolution / Representation**：对候选来源和可受控表示的一次服务端核验结果。它不等于相关性、
  教育质量、适龄性或再分发权证明。
- **Capability / Readiness / Eligibility**：静态能力声明、当前部署就绪快照和本次 Flow/资源/动作的
  权利与策略判断。静态 Registry 或 Descriptor 单独不能证明可执行。
- **Job / Execution / Outcome**：异步下载 Job；start 时服务端重新校验并冻结不可变执行绑定，再由
  exact Provider 产生每项 Acquisition Outcome。公共 Job 状态是脱敏、无 locator 的只读投影。
- **Asset / AssetBundle / Archive**：服务端校验后的不可变内容、一个 Job × Resource 的有序关系，以及
  资料库中的归档记录。Bundle 不是 ZIP、目录或模型可提交的路径。

## 权威状态链

```text
FlowTask -> ResultSet -> Presentation -> Selection
         -> DownloadPlan -> immutable Job Execution
         -> Acquisition Outcome -> AssetBundle / Asset -> Archive

Capability Descriptor -> Deployment Readiness
  -> Resolution / Representation -> Eligibility
  -> Plan item + authority_digest -> fresh Execution Binding
  -> exact Provider -> Outcome
```

MCP 服务端拥有上述状态、稳定 ID、版本、摘要、失败事实和副作用结果的权威。SQLite 是本地运行时
持久化状态；Skill 只负责语义决策和用户交互，不能伪造或覆盖服务端事实。`coverage` 是服务端事实
摘要，不代替 Skill 的 `SemanticReview`、Gap 或 StopDecision；边界见
[`RETRIEVAL_AUTHORITY.md`](../../../docs/RETRIEVAL_AUTHORITY.md)。

## 工具不变量

1. 客户端只提交服务端生成的 opaque `flow_id`、`resource_id`、`plan_id`、`job_id`、`asset_id`
   等 ID，以及契约允许的用户输入；不提交路径、脚本、命令、内部存储键或服务端摘要。
2. Search/browse 创建 ResultSet；`resource_search.limit` 表示新不可变 ResultSet 的**总容量**，
   `extend` 时该容量包含从当前 base 复制的候选，不是本轮新增配额。`new_displayable_count` 只统计
   应用该总容量后仍实际保留在新 ResultSet 中的本轮新候选。实际展示后必须保存 Presentation；
   Selection 只接受当前 Presentation 的位置和绑定。
3. `resource_inspect` 只核验当前 Flow 中的单个 `resource_id`，来源由服务端取得；它不接受任意
   URL、路径或凭据，不下载、不归档，也不改变不可变 ResultSet。
4. `resource_download_prepare` 绑定当前 Presentation/Selection、Resolution/Representation、
   Capability/Readiness/Eligibility、exact Provider/strategy/scope 和服务端摘要；随后必须等待用户
   明确确认。
5. `resource_download_start` 必须重新校验 Plan、确认材料、来源指纹和 authority chain，并持久化
   fresh immutable Job Execution Binding。省略可选的 `authority_digest` 不降低校验，也不允许隐式
   fallback 或 Provider takeover。
6. Job 必须异步执行并支持状态查询与取消。Job 生命周期使用 `queued`、`running`、`cancelling`、
   `succeeded`、`failed`、`cancelled`；Bundle 的 `complete|partial` 是结果完整度，不是新的 Job 状态。
7. 所有有副作用的调用使用幂等键；相同规范请求可重放，不同请求复用同一键必须返回结构化冲突。
   业务错误返回稳定错误码，内部异常不得直接成为公共兼容面。
8. `resource_flow_status` 只返回恢复所需的安全投影，不返回确认秘密、凭据、数据库/临时/下载/归档
   本地路径、请求 URL 或大对象。

### Acquisition Outcome 状态

Acquisition Outcome 在执行中使用 `status="running"`；公共
`schemas/common.schema.json` 的 `outcome_status` 已与该 runtime 状态对齐。该值只表示已启动但尚未
终结的单项执行，不替代 Job 状态，也不允许缺少权威绑定的客户端伪造执行中 Outcome。

## 安全边界

- 只允许策略控制的 `http`/`https` 来源；逐跳校验并阻断本机、私网、链路本地、云元数据和非预期
  重定向目标。
- 服务端强制执行超时、重试、并发、流式写入、内容类型、魔数/真实格式和取消清理；不执行不受控
  网页脚本。
- 不绕过登录、验证码、付费墙、DRM 或明确访问控制。合法会话由独立 `session-manager` 管理，
  Cookie、Token 和浏览器档案不进入 MCP 工具输入或结果。
- 大文件、文件字节、任意 URL、shell 命令和本地路径不进入 Tool JSON 或模型上下文。

## 归档语义

归档只接受服务端生成的 `asset_id` 及其所属 Job 绑定。Asset 必须来自已校验的获取结果，并且仍有
可验证的执行 authority；缺失 authority 的 legacy 结果只读，不能 start 或归档。

归档采用受控的 `pending -> ready` 提交流程：服务端在临时位置写入内容，复核大小、SHA-256、媒体类型
和安全相对路径后原子提交索引；失败或取消不得产生可检索的 ready 记录。相同内容按 SHA-256/大小去重，
但保留 Asset 到 Archive 的可追溯关系，不覆盖既有文件。

`AssetBundle` 由服务端生成有序 BundleItem。可用 Bundle 必须有且只有一个 `primary`；其余角色和失败
项由来源事实决定，不能依据文件名或模型输入推断。已有可用 primary、但一个或多个预期项失败时，
Outcome/Bundle 可表达 `partial`；这不改变 Job 生命周期，也不创建零字节假 Asset。资料库分类使用
[`taxonomy/learning-v1.json`](taxonomy/learning-v1.json) 的机器注册表，不能由客户端创建新的一级领域。

## 相关权威文档

- [Contracts 总览](README.md)
- [当前兼容与重置政策](compatibility.md)
- [当前架构事实快照](../../../docs/CURRENT_ARCHITECTURE.md)
- [开发计划](../../../docs/DEVELOPMENT_PLAN.md)
- [工作区根 README](../../../README.md)
