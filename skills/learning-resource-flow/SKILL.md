---
name: learning-resource-flow
description: 面向孩子和家长的教育资源唯一对话入口。用户想寻找、推荐、比较、筛选、下载、收藏或再次查找课程、视频、图书、文章、练习、活动方案等资源时使用；也用于从模糊的学习或成长问题出发澄清目标、规划有界的自适应检索、审查搜索候选、提交实际展示集、保存用户选择，以及恢复、确认、取消或查询资源任务。通过 education-resources MCP 控制 Flow、ResultSet、Presentation、Selection、Plan、Job、Asset 及其 AssetBundle 关系；平台登录交给独立 session-manager。
---

# Learning Resource Flow

## 结果

帮助用户获得真正符合当前目标和明确约束的教育资源，并在明确选择和确认后安全下载或归档。让用户始终用自然语言交流，不要求用户理解 Skill、MCP、平台参数或业务 ID。

不要把搜索召回、完成工具调用、返回很多链接或模型自己记住状态当成成功。

## 分工

由本 Skill 负责：

- 理解需求，区分用户事实、可靠推断和低风险默认。
- 判断是否需要澄清，设计 `SearchDirection`，并驱动 Plan -> Search -> Evaluate -> Inspect? -> 私有 Gap/StopDecision -> Replan/Present 的有界循环。
- 审查 ResultSet 候选的相关性、内容门槛、儿童安全、证据、可用性和组合价值。
- 在候选展示前克制地决定哪些高潜候选需要 `resource_inspect`，并解释真实核验结果。
- 实际向用户展示经过审查的有序子集，并把完全相同的顺序提交为 Presentation。
- 解释选择、计划、风险、进度、失败和下一步。

由 `education-resources` MCP 负责：

- Flow、ResultSet、Presentation、Selection、Plan、Job、Asset 以及 AssetBundle/BundleItem 关系的权威状态。
- SearchRound、搜索运行 provenance、跨轮去重、服务端观察到的 factual `coverage` 和恢复状态的权威事实（契约提供时）。`coverage` 只说明服务端看到了什么；其中的 `gaps` 是 factual gaps，不是本 Skill 的语义 `Gap`。
- 单个资源的 Resolution、Inspection、Representation、可用性、失败和恢复状态。
- 结果集和展示集成员校验、位置映射、版本、幂等、恢复、下载、取消和归档。

搜索结果不是已展示结果。模型不得把 ResultSet 自动称为 Presentation，也不得让用户选择未进入当前 Presentation 的隐藏候选。

平台登录不属于本 Skill 或 `education-resources` 控制面。需要认证时暂停当前流程，交给独立 `session-manager` 和 `session-login-flow` 完成合法登录与会话保存；登录成功后调用 `resource_flow_status` 恢复，不在本 Skill 中复制 Cookie 捕获逻辑。

## 生产判定边界

生产链只有一组服务端权威事实来源和一个停止决策执行者：

```text
MCP Search -> immutable ResultSet + factual `coverage`
MCP Inspect / Resolution / Capability / Job / Outcome / Asset -> 各自独立的权威事实
  -> Skill 统一读取上述事实
  -> Skill 私有 `SemanticReview`
  -> Skill 私有 `Gap`
  -> Skill 唯一 `StopDecision`
  -> Present | Replan | Clarify | StopWithGap
```

Inspect、Resolution、Capability、Job、Outcome、Asset 或 Archive 的变化不反写旧 ResultSet 的
`coverage`；恢复时分别读取它们的当前服务端状态，再重新计算私有语义判断。

获取执行必须沿一条服务端权威链前进：Capability Descriptor -> Runtime Readiness -> persisted
Resolution/Representation -> Eligibility -> Plan capability binding + `authority_digest` -> fresh
Execution binding -> exact Provider -> persisted Acquisition Outcome -> Asset/AssetBundle -> sanitized
Job status projection。平台 Registry、静态 descriptor、文件扩展名或旧 options 都不能单独决定
Provider、strategy 或 scope，也不存在隐式 generic Provider fallback。

`SemanticReview`、Skill `Gap` 和 `StopDecision` 是对当前任务的私有语义判断，不写入 MCP
Schema、SQLite、Flow/ResultSet 业务状态或任何可提交的业务 ID。MCP 公共
`coverage.gaps` 只记录服务端实际观察到的事实缺口；不能直接当作 Skill `Gap`，也不能把
`coverage.status`、候选数量、标题命中、平台数量或 `SearchDirection` 单独当成相关性、用途、
目标适配、约束满足或可推荐性的证据。`adaptive.py` 只用于离线 oracle/benchmark，不能参与
生产搜索、Inspect、下载、归档或停止决策。

## 当前任务模型

内部维护一个独立三部分任务模型：

- `user_role`：当前对话者是孩子、家长或未知。
- `resource_target`：资源给孩子使用、给家长参考或未知。
- `constraints`：用户明示或有充分证据支持的 must、prefer、exclude 及具体使用条件。

同时保存核心目标 `goal`。`user_role` 与 `resource_target` 相互独立，不能互相推导；未知保持未知。把该模型按 Task Schema 传给 `resource_flow_start`，不得回退为混合的 audience 字段。

`SearchDirection` 不是 query、platform 或 resource type，而是本 Skill 为覆盖明确的学习目标、使用
结果或决策缺口选择的搜索路径。方向由 `resource_target`、`goal` 和显式 `constraints` 决定；
`user_role` 只影响交互方式。方向是 Skill 的搜索路线说明和可选审计 trace，不是事实 ID、
Coverage 维度、语义证据、`Gap` 或 `StopDecision`；改变方向本身不能伪造候选计数、可用性或
coverage 状态。搜索方向、轮次预算、Coverage/Gap 和 StopDecision 的完整规则见
[`references/adaptive-retrieval.md`](references/adaptive-retrieval.md)。

处理模糊请求、冲突、短回答或敏感儿童主题时读取 `references/intent-and-clarification.md`。

## 强制控制流

正常流程严格使用：

```text
resource_flow_start
-> Plan：确定 1–2 个 SearchDirection 和本轮有界路线
-> Search：resource_search / resource_browse_creator  # 首轮 replace
-> Evaluate：读取当前 ResultSet、MCP factual coverage、provenance 和失败事实
-> SemanticReview：Skill 对候选生成私有语义审查（unknown 不等于 pass）
-> Inspect?：对少量会改变决策的候选执行 Inspection Gate，并重新审查
-> Gap/Decision：Skill 生成私有 Gap，并且每轮只选择一个 StopDecision
   （Present / Clarify / StopWithGap / Replan）
   -> Replan：resource_search mode=extend + 当前 base_result_set_id，回到 Search
   -> Present：模型审查并实际向用户展示当前 ResultSet 的有序子集
-> resource_presentation_save         # 提交刚才实际展示的完全相同集合和顺序
-> 等待用户选择
-> resource_selection_save            # 只提交当前 Presentation 的 positions
-> resource_download_prepare
-> 向用户展示计划并等待明确确认
-> resource_download_start
```

之后使用 `resource_job_status`、`resource_job_cancel`、`resource_archive` 和 `resource_library_search`。

不得省略、交换或合并 `Plan -> Search -> Evaluate -> Inspect? -> Gap`，也不得跳过
`实际展示 -> presentation_save -> 用户选择 -> selection_save`。尤其禁止：

- 搜索成功后直接调用 `selection_save`。
- 在实际展示前调用 `presentation_save`。
- 把 ResultSet 全量候选默认记为已展示。
- 把未展示候选、旧 Presentation 项或模型生成的资源放入选择。
- 根据对话文本猜测 position、版本或当前状态。

## 自适应检索循环

检索不是一次查询。按 [`references/adaptive-retrieval.md`](references/adaptive-retrieval.md)
逐轮执行，并在每轮结束时作出一个 `StopDecision`：

1. **Plan**：从 `resource_target`、`goal` 和 `constraints` 规划首轮 1–2 个
   `SearchDirection`。每个方向默认 2–3 个直接相关平台、每个平台 1–2 个 query、每个 query
   5–10 条目标召回；首轮 `new_unique` 不超过 30。预算不是实际结果，不能由模型填写计数。
2. **Search**：首轮 `resource_search` 使用 `mode=replace`（省略即为 replace）。只有在
   `Replan` 且确有当前 `base_result_set_id` 时使用 `mode=extend`；MCP 负责复制 base、跨轮
   去重并创建新的不可变 ResultSet，模型不手工合并候选。
3. **Evaluate**：读取 MCP 返回的 ResultSet、platform/query runs、provenance、factual
   `coverage`、failures 和 Inspection 事实；`coverage` 及其 `gaps` 只表示服务端观察到的
   事实完整度，不是任务语义结论。候选数量、相关性分数、平台数量、`coverage.status` 或
   `SearchDirection` 都不能单独触发 `Present`。
4. **SemanticReview**：Skill 对准备比较或展示的候选生成私有审查，至少记录
   `relevance`、`usefulness`、`target_fit`、`constraint_fit`、`substantive`、
   `evidence_level` 和 `reasons`。每个维度都允许 `unknown`；`unknown` 不是 `pass`，
   证据不足时必须保留未知并进入 Inspect、Clarify、Replan 或 `StopWithGap`。
5. **Inspect?**：只检查高潜、差异关键、可用性不确定或下载前需要 Representation 的少量
   候选。检查结果回来后重新读取 factual facts 并重算私有 `SemanticReview`；未检查或检查
   失败的 Candidate 仍然未核验。
6. **Gap/StopDecision**：Skill 根据目标、显式约束、MCP factual facts 和私有
   `SemanticReview` 生成私有 `Gap`，每轮只产生一个 `StopDecision`。缺口必须是会改变后续
   搜索、推荐或获取决策的必要条件，不是任意未知。语义判断足以支持当前目标且有足够事实
   与审查通过的候选时才可 `Present`；缺少会改变方向的用户事实/硬范围时 `Clarify`；仍有
   必要缺口且没有有价值的下一步时 `StopWithGap`；有新方向可关闭缺口时 `Replan`。

常规任务最多 3 轮，用户明确要求全面探索/横向比较的综合任务最多 4 轮。连续 2 轮
`new_unique=0` 且 Skill 没有基于 MCP facts 关闭任何私有 `Gap` 时必须停止继续搜索；事实
足够且候选通过必要的私有审查才可 `Present`，否则选择 `StopWithGap`/`Clarify`。`new_unique`、
duplicate 和 factual coverage 只能使用服务端事实；`Gap closure`、语义通过与
`StopDecision` 只能由 Skill 判断。缺少返回值时说明“无法确认”，不能补造。

## 对话决策循环

### 1. 理解并判断是否澄清

理解核心目标、`user_role`、`resource_target` 和显式 `constraints`。只有核心主题、搜索路线、硬约束或资源对象歧义会实质改变结果时才澄清；一次只问一个容易回答的问题。

不要为了补齐不影响当前结果的字段而追问。需求足够时直接搜索；搜索本身不需要确认。

### 2. 设计搜索方向

需要规划或比较平台路线时，按需读取 references/platform-capabilities.md，以其中引用的
platform-registry.json 作为当前能力和认证信息的机器权威。该参考只帮助判断可用路线；
仍须由目标、resource_target 和显式 constraints 决定平台选择，不因注册表列出平台而
无差别搜索全部平台，也不把平台能力当作内容质量证据。

搜索前读取 `references/discovery-strategy.md` 和 `references/adaptive-retrieval.md`。查询只由
`goal`、`resource_target` 和显式 `constraints` 驱动；`user_role` 只影响交互方式。不要用
“优质、权威、适合孩子、高赞”等评价词替代后续审查。

### 3. 建立或恢复 Flow

首次任务调用 `education-resources__resource_flow_start`。如果已有 `flow_id` 但状态不确定、上下文被压缩、工具响应丢失、OpenClaw 或 MCP 重启，先调用 `education-resources__resource_flow_status`，不要重新创建 Flow 或从聊天记录猜测状态。

用户改变核心目标、资源对象或硬约束时建立新 Flow。同一目标下换搜索角度时可继续当前 Flow。

### 4. 执行搜索轮次并只获得 ResultSet

调用 `education-resources__resource_search`，保存 MCP 返回的 `search_run_id`、`result_set_id`、
结果版本、候选 `resource_id`、platform/query runs、失败和（契约提供时）provenance、factual
`coverage`。`coverage.gaps` 只作为服务端事实输入，不能直接写成 Skill `Gap`。
把返回项称为“搜索候选”或“待审查候选”，不能称为“已展示候选”。

- 首轮或新任务用 `mode=replace`；`mode` 省略时按 replace 处理。
- `Replan` 只用 `mode=extend`，且 `base_result_set_id` 必须是当前 Flow 状态或上一轮 MCP
  返回的当前 ResultSet ID。extend 产生新的不可变 ResultSet；base 不变，不能由模型把两份
  候选数组手工合并，也不能混用旧 Presentation/Selection。
- `extend` 返回的新 `result_set_id`、版本和 opaque `resource_id` 才能继续使用；不猜测、
  改写或复用未被新响应确认的 ID。每次新动作使用新幂等键，同键只接受服务端原响应。
- `limit` 若存在，表示新 ResultSet 的总容量，不是模型可声称的每 query 实际召回数。

需要认证的平台返回 `AUTH_REQUIRED` 或同类登录状态时，按 `references/mcp-workflow.md` 委托独立 session-manager；登录成功后先 `resource_flow_status` 再继续。

### 5. 选择性核验、审查、实际展示并提交 Presentation

读取 `references/inspection-strategy.md`、`references/candidate-judgment.md` 和
`references/response-guidelines.md`：

1. 先从当前一个 ResultSet 中排除偏题、不安全、违反硬约束、不可定位或无实际价值的项；
   ResultSet 中的条目仍然只是 Candidate，不是已核验资源。
2. 只把以下候选送入 Inspection Gate：高潜且可能推荐的候选、需要核验关键差异的候选、
   可用性不确定的候选，或下载前必须判断 Representation 的候选。不要因为候选多就默认
   全量检查，也不要为了补齐字段检查低潜或已经有充分证据的候选。
3. 调用 `education-resources__resource_inspect` 时，请求对象只能包含下面四个字段；
   `resource_id` 必须来自当前 Flow 的当前 ResultSet。不得传 URL、路径、depth、batch、
   Cookie、Token、其他凭据或自造的状态字段，也不要让模型从对话拼接服务端状态：

   ```json
   {
     "contract_version": "1.0.0",
     "flow_id": "<当前 Flow 的 flow_id>",
     "resource_id": "<当前 ResultSet 中候选的 resource_id>",
     "idempotency_key": "<本次检查请求的幂等键>"
   }
   ```

4. 把 MCP 返回的 Candidate 与 `resolved_resource` 严格分开。只有服务端真实返回的
   `resolution_status`、`availability`、`representations`、`inspection` 和 `failures`
   才能用于说明核验结果；不把标题、搜索摘要、平台名或模型常识升级为
   ResolvedResource，也不把检查失败伪装成“已核验”。
5. 按 `references/candidate-judgment.md` 比较 Candidate 与 Resolution，形成少量、有序、
   可解释的展示子集。`resolved` 只表示本次检查形成了足够完整的服务端解析，仍要单独
   说明 `availability` 和权利/适用性未知；`partial` 必须标出缺口；`unresolved` 只能
   作为未核验或暂不可确认的候选处理。
6. `FEATURE_NOT_SUPPORTED` 表示当前平台没有接入该检查路线，不是资源不存在；
   `auth_required` 交给独立 session-manager 合法登录，登录成功后先
   `resource_flow_status`，再用新的幂等键重试；`policy_blocked` 不得绕过安全策略；
   `unavailable` 降低或撤下该候选；可重试的 unresolved 用新的幂等键重试，同一幂等键只
   重放原结果。任何一种失败都不能改写成可用或已核验。
7. `inspection.cache_status=hit` 表示服务端复用了同一资源来源指纹和 Inspector 版本下的
   成功/部分 Resolution；参考 `inspected_at`，不要声称刚刚完成网络检查。同一幂等键的
   replay 必须接受服务端原响应，不生成新 ID、不自行补状态；更换资源或发起新检查时
   使用新的幂等键。
8. 按最终顺序实际向用户展示并编号；记录每个位置对应的 `resource_id`。展示后立即调用
   `education-resources__resource_presentation_save`，提交该 `result_set_id` 和刚才实际
   展示的完整有序 `displayed_resource_ids`。
9. 只有保存成功后，才邀请或接受用户按编号选择。若用户选择的资源尚未核验且下载计划
   需要 Representation，在 `resource_download_prepare` 前补做一次该资源的 Inspection Gate。

若本轮评估后的 `StopDecision` 是 `Replan`，不要进入展示，按当前 `base_result_set_id` 回到
第 4 步；是 `Clarify` 时只问一个会改变方向的最小问题；是 `StopWithGap` 时先向用户说明
已覆盖内容、未闭合 Gap、真实失败和影响，再决定是否展示安全的低置信候选。只有 `Present`
才执行本节的 Presentation 流程。

`presentation_save` 的集合和顺序必须与用户刚看到的列表完全一致。保存失败时，不接受选择；解释列表尚未建立为可选择状态，恢复状态后重新展示并提交。

### 6. 按 positions 保存选择

用户选择后调用 `education-resources__resource_selection_save`：

- 传当前 `presentation_id`、`presented_version` 和用户选择的 `selected_positions`。
- position 必须来自当前 Presentation，不能由模型映射到隐藏资源 ID。
- “这些都要”只表示当前 Presentation 的全部位置。
- 用户修改选择时提交完整的新 positions 集合，不在旧 Selection 上隐式增删。
- 用户取消时提交空 positions；取消后停止下载流程。

### 7. Prepare、确认和 Start

非空 Selection 必须原样携带当前 `presentation_id`、`presented_version`、`selection_version` 和 `selection_digest` 调用 `resource_download_prepare`。向用户展示计划中的资源、格式或容器、大小上限、有效期、风险，以及 Plan 明确声明的 capability fallback（若有），不展示确认令牌或内部 JSON。

只有用户看过当前有效计划并明确确认后，才原样使用 MCP 返回的 `plan_id`、`plan_digest`、完整 Presentation/Selection 绑定元组和 `confirmation_token` 调用 `resource_download_start`。`authority_digest` 是可选兼容校验输入：可以省略并让服务端从不可变 Plan 读取真实摘要；若回显，只能原样使用 prepare 返回值。`plan_digest` 已绑定该摘要，Skill 不生成或重算任一 digest。用户拒绝、修改选择、Presentation 变化或 Plan 过期后必须重新 prepare 和确认。

## 获取策略与网页物化

当前公开控制面保持兼容：`contract_version=1.0.0`、`catalog_version=1.5.0`，仍然只有
13 个 MCP 工具。0022 在 catalog 1.3.0 中增加可选 AssetBundle 投影；历史 1.4.0 增加
factual coverage 可选元数据；当前 1.5.0 增加 Capability Authority 和 Outcome 的兼容投影。
不新增 Bundle 工具、不增加 `partial` Job 状态，也不改变
`prepare -> 用户确认 -> start` 控制流。
获取策略仍是服务端内部的路由语义，不要求模型向工具提交本地路径、下载 URL、浏览器参数、
角色关系或任意策略 JSON。

### Artifact、Asset 与 AssetBundle

获取边界使用以下固定语言：

- `Artifact` 是一次 Acquisition 尝试产生的临时单项文件描述。它还没有公共业务 ID，只有
  经过服务端路径、大小、MIME、魔数和摘要校验并持久化后，才晋升为 `Asset`。
- `Asset` 是服务端确认并持久化的单个不可变内容表示，拥有服务端产生的 `asset_id`。Skill
  不接触其本地路径，也不能自行制造 Asset。
- `AssetBundle` 是一个 Job 针对一个 Resource 产生的有序多资产关系，不是 ZIP、文件夹或
  物理容器。`BundleItem` 保存角色、顺序、成功 Asset 或失败事实；失败项没有 `asset_id`，
  不创建零字节假 Asset。一个可用 Bundle 必须有且只有一个 `primary`。
- 服务端固定的公开角色只有 `primary`、`subtitle`、`cover`、`metadata`、`attachment`、
  `transcript`、`companion` 七种。Skill 不按文件名、扩展名或对话常识猜角色、顺序、
  `bundle_id` 或 `item_key`。

结果完整度与任务生命周期分离：Job `status` 仍只使用 `queued`、`running`、`cancelling`、
`succeeded`、`failed`、`cancelled`；`completion=complete|partial` 只表达已有可用 primary
时 Bundle 是否有预期项失败。没有可用 primary 的结果为 `failed`，不能声明 `partial`；取消
也不能伪装成 `partial`。内部 canonical `ActualOutcome.status="partial"` 只是按资源持久化的
acquisition outcome 事实；`resource_job_status.outcomes` 是它的脱敏公共投影，两者都不能被
Skill 伪造或回填为服务端 persistence payload。

在用户可理解的层面，本 Skill 只判断资源形态、用户期望和风险，并向用户解释 MCP 返回的
计划与结果：

- 已验证为文件、视频、音频、图书或其他直接媒体，且服务端 Plan 已绑定 `direct_file` 精确路线时，
  按计划解释原始文件获取。
- 普通文章、古诗文页、图文博客和可静态读取的网页，且服务端 Plan 已绑定
  `web_materialize` 精确路线时，按计划解释静态物化；
  物化结果同时提供可读 Markdown 和经过重建的安全 HTML。
- 只有用户明确要求动态页面快照，且服务端计划明确允许受控浏览器采集时，才可以按
  `web_capture` 语义获取。浏览器采集不是网页获取的默认方式，也不是静态物化失败后的
  自动 fallback；动态页面无法安全静态物化时，应如实说明缺口或结构化失败。

服务端只能从已声明的 Capability Descriptor、当前 readiness、持久化 Resolution/Representation
和 Eligibility 生成 Plan；start 时再次校验并保存 fresh Execution binding，Acquisition Router
只能按其中的 exact Provider/strategy/scope 执行。Skill 不拼接命令、
脚本、绝对路径或 URL，也不决定落盘目录。网页物化产生的受控 bundle 以
`index.html`、`content.md`、`metadata.json` 和 `assets/` 组成，并生成 `webbundle.zip`；
`webbundle.zip` 作为一个 singleton Bundle 的 `primary` Asset，ZIP 内部文件不拆成公开
BundleItem。其他媒体或课程的伴随文件只有在 MCP 返回对应 Asset/Bundle 事实时才可解释；
归档时只使用 MCP 返回的 `asset_id`，不自行选择 bundle 内文件或伪造 Asset。

静态获取必须遵守逐跳 SSRF/重定向校验、流式大小上限、MIME 与文件魔数交叉校验、可取消
任务和同源/策略资产限制；不执行网页脚本，不绕过登录、验证码、付费墙、DRM 或其他访问
控制。需要认证时交给独立 `session-manager`，不把 Cookie 或 Token 传给本 Skill 或
education-resources 工具。取消后的中间产物由服务端 quarantine，不能解释为 ready Asset。
进程重启时，未完成 Job 终结为 `failed`/`cancelled` 并 quarantine 相关未完成资产；不自动
重放网络副作用。Skill 只解释服务端真实返回的 Asset/Bundle 字段，不补造内部角色或关系。

完整的路由表、bundle 结构、失败解释和安全边界见
[`references/acquisition-strategy.md`](references/acquisition-strategy.md)。

### 历史 Provider 兼容与多资产解释

服务端保留旧 `DownloadProvider` 兼容边界：旧单文件结果按 `primary` 映射，旧有序列表的
首项按 `primary`、其余按保守的 `attachment` 映射；新 enriched batch 结果只有服务端明确
提供的角色、顺序和失败事实才进入 Bundle。SmartEdu 的课程输出按来源事实保留关系：存在视频
时视频为 `primary`，否则取首个明确内容项；PDF 为 `attachment`，MP3 为 `companion`，显式
封面才是 `cover`，不得靠文件名猜测。逐项失败必须保留；认证、策略阻断或取消会终止整个
获取结果，不把失败项或取消包装成成功。该映射只解释历史 Provider 返回的资产关系，不能在
当前 1.5 中选择或替换 Provider、strategy、scope、Representation 或 capability route。

## 归档与资料库检索

调用 `resource_archive` 或解释 `resource_library_search` 结果前，必须读取
`references/library-structure.md`。归档对象是学习资料，不是儿童成长档案。

- 根据资源实际内容、服务端权威元数据和当前学习目标提出分类；只填写有证据支持的学段、难度、教材版本、专题和标签。
- 从注册表选择唯一主领域和零到多个次领域，不创建一级领域，不把亲子、家长辅导、自主学习、教材同步、学段、媒介或资料用途当作一级领域。
- 分类证据不足时提交 `needs_review` 或 `unclassified`，不为补齐内部字段追问用户，也不伪造来源、标题或归档状态。
- 不拼接本地路径，不决定物理格式目录，不直接写 SQLite；文件格式、命名、落盘、去重、事务、恢复和索引由 MCP 负责。
- 用自然中文解释主领域、主题、分类状态、归档或内容去重结果；位置只使用 MCP 返回的资料库内安全相对路径。
- Archive 仍然是 Asset-scoped：任何 ready BundleItem 都可按其服务端 `asset_id` 独立归档；
  如果用户要求完整 Bundle，按 MCP 返回的 ready 成员逐个归档。Library 仍以 Asset 为返回
  粒度，并通过可选的 `bundle_id`、`role`、`order`、`bundle_completion` 恢复 Bundle 关系。

## 恢复规则

`resource_flow_status` 是恢复权威来源：

- `reviewing` 且只有 ResultSet：继续审查；实际展示后再保存 Presentation。
- 存在当前 ResultSet 但上一轮搜索未完成决策：按状态返回的 provenance、factual `coverage`
  和失败恢复当前 SearchRound；不能从聊天记录补造 `new_unique`、Skill `Gap` closure 或
  base ID。
- 存在当前 Presentation、尚无 Selection：只按状态返回的有序 items 恢复编号并等待选择。
- 上下文被压缩、工具响应丢失或服务重启：先读取 `current_resolutions`，按其中的
  `resolution_id`、`resolution_status`、`resolved_resource`、`inspection` 和 `failures`
  恢复已核验摘要；没有摘要时仍把候选当作未核验，不从聊天记忆补造 Resolution。
- 存在 Selection、尚无 Plan：原样携带当前 Presentation/Selection 绑定元组 prepare。
- 存在有效 Plan、尚未确认：重新展示当前计划并等待确认，不能自动 start。
- 存在 Job：按真实状态查询、取消或报告；`queued`、`running`、`cancelling` 都不是成功。
  `completion` 只作为结果完整度读取，不把它当成新的 Job 状态；取消或重启后的 quarantine
  结果不可归档，也不自动重放网络获取。
- Presentation、Selection 或 Plan 已 superseded/expired：不得沿用旧编号、positions、版本或令牌。

如果状态返回的 Presentation 与对话记忆不一致，以 MCP 为准，并向用户简短说明候选列表已更新。
恢复后只重建 MCP facts；`SemanticReview`、Skill `Gap` 和 `StopDecision` 必须由 Skill 基于
最新事实重新计算，缺失审查按 `unknown` 处理，不能把 unknown 当作 pass。

## 强制边界

- 只使用 MCP 返回的 ID、版本、position、Plan、Job 和 Asset，不猜测、不伪造。
- ResultSet 只能用于审查；只有当前 Presentation 可用于用户选择。
- `base_result_set_id` 只能来自当前 Flow 的服务端状态；`mode=extend` 的复制、跨轮去重和
  新 ResultSet 由 MCP 完成，模型不得手工合并。
- MCP 返回的 factual `coverage`、new_unique、duplicate、provenance 和失败事实只能来自服务端；
  `InformationGain` 若由服务端提供也只能作为事实摘要读取。Skill `Gap`/`StopDecision` 必须是
  基于这些事实、私有 `SemanticReview` 及当前 goal/resource_target/constraints 的明确语义判断，
  不能把模型判断伪装成 MCP 字段，也不得把计划预算、候选数组长度、平台数量或方向 trace 写成
  这些事实。
- Candidate 不是 ResolvedResource；`resolution_status`、`availability`、Representation 和
  `failures` 只能来自 `resource_inspect` 或 `resource_flow_status.current_resolutions`。
- Capability Descriptor、Runtime Readiness、Eligibility、Plan/Execution binding、Provider 和
  Acquisition Outcome 都是服务端事实。Skill 不从平台 Registry、旧 options 或资源标题推导执行路线，
  不创建/重算 `authority_digest` 或 `plan_digest`，也不把 public `outcomes` 当作可写状态。
- Artifact 只是服务端 Acquisition 的临时描述；只有 MCP 返回的 `asset_id` 才是可归档 Asset。
  Bundle 角色、顺序、`bundle_id`、`item_key` 和 `completion` 都是服务端只读事实，不能由模型提交或伪造。
- 不向工具传本地路径、脚本、二进制、shell 命令、任意 URL、Cookie 或 Token。
- `resource_inspect` 只能传 `contract_version`、`flow_id`、`resource_id`、`idempotency_key`；
  不传批量 ID、检查深度、凭据或模型生成的工具状态。
- 不绕过登录、验证码、付费墙、DRM、版权或访问控制。
- 不把标题宣传、平台热度、平台名气或模型常识写成已核验事实。
- MCP 返回 `ok=false` 时停止当前状态转换，按结构化错误恢复。
- 大文件和二进制不进入对话上下文，只展示 Asset 元数据或受控访问结果。

## 按需资料

- `references/platform-capabilities.md`：平台能力、资源形态、认证方式、创作者浏览和受控获取路线；规划平台选择时按需读取。

- `references/intent-and-clarification.md`：独立的 user_role、resource_target、constraints 模型和澄清。
- `references/discovery-strategy.md`：搜索方向、查询设计、来源策略和停止条件。
- `references/adaptive-retrieval.md`：Plan/Search/Evaluate/Inspect?/Gap 循环、extend、Coverage、失败解释和停止决策。
- `references/acquisition-strategy.md`：Capability Authority、Artifact/Asset/Bundle、ActualOutcome、七种角色、历史 Provider/SmartEdu 映射、网页物化、Browser capture 条件和获取安全边界。
- `references/site-whitelist.md`：可信站点定向搜索参考。
- `references/candidate-judgment.md`：ResultSet 审查、展示子集和证据护栏。
- `references/inspection-strategy.md`：Inspection Gate 决策、结果解释、比较与停止条件。
- `references/mcp-workflow.md`：工具顺序、幂等、Presentation、恢复、独立登录和错误处理。
- `references/library-structure.md`：归档前必读；学习领域、分类元数据、物理目录和资料库检索规则。
- `references/response-guidelines.md`：实际展示、选择、确认、进度和失败表达。
- `examples/semantic-regression-cases.json`：修改 Skill 或执行回归时读取，不作为正常对话输入。

## 当前验收边界

本 Skill 文档已按当前 catalog 1.5.0、Capability Authority、schema version 7、AssetBundle 与
Outcome 投影语义对齐。2026-08-08 的 0024 历史基线在原生 Linux 临时目录中通过全量 374/374、stdio
E2E 8/8、retrieval calibration 39/39、`compileall`，并串行通过 OpenClaw
config/status/doctor/probe（精确发现 13 个 Tool，`diagnostics=[]`）。默认 Agent 的完整自然
语言资源业务回合、真实平台 readiness 和生产多租户隔离仍未完成；对话只能依据 MCP 当前
返回的权威状态，不得把本文件的设计说明或离线 fixture 当作运行时成功事实。
