# 0025 Platform Capability Contract Alignment

- 状态：completed
- 创建日期：2026-08-08
- 完成日期：2026-08-10
- 范围：`mcp/education-resources` 的平台 Registry、Adapter/Inspector/Provider loader、Resolution/Representation、Policy、Acquisition、Plan/Job/Asset 与契约 Schema；`skills/learning-resource-flow` 只同步能力语义和用户可见解释
- 前置审计：[`0025 Capability Truth Audit`](0025-capability-truth-audit.md)
- 相关权威边界：[`Retrieval Authority`](../../../docs/RETRIEVAL_AUTHORITY.md)
- 性质：已完成的实施计划；A→H 已按依赖顺序收口，并保留全量、E2E、静态契约与 OpenClaw 机器证据
- 完成快照与下一阶段交接：[`0025 Completion Snapshot and 0028 Handoff`](0025-platform-capability-contract-alignment-handoff.md)

## 目标

把平台“是否支持获取”从静态布尔声明、运行时偶然导入和通用 Provider fallback 中收敛为一条
可追溯、可重新校验的服务端能力链：

```text
Static Capability Descriptor
  -> Deployment Readiness Snapshot
  -> Candidate Resolution / Inspection
  -> Representation + Resolved Capability
  -> Policy / Rights Eligibility
  -> per-resource download_prepare
  -> bound Plan + digest
  -> download_start revalidation
  -> declared Provider / Acquisition Router
  -> Actual Outcome + Asset / Bundle
  -> Skill explanation and archive
```

每一层都由 MCP/服务端生成稳定 ID、版本、摘要或状态，并保存上游引用；模型只能对相关性、
用途、目标适配和用户解释作语义判断，不能创建能力事实、Provider、Representation、权限、
计划绑定、Asset 或下载成功结论。

## 非目标与硬禁止

- 不以增加超时、吞掉异常、伪造 readiness 或继续保留隐式 fallback 作为兼容方案。
- 不把 Registry 的 `acquire=true`、平台 strategy、搜索结果数量或标题命中解释为候选存在
  可下载的 `primary` 文件。
- 不允许 generic Provider 静默接管：未声明、未加载、未通过 readiness、scope 不匹配或
  专用 Provider 已失败时，不能自动换成 generic direct Provider。若未来确实要使用 generic
  Provider，必须把它作为显式、带 scope 的 Provider descriptor，经过同样 readiness、policy
  和 revalidation；否则返回结构化 capability/provider 缺口。
- 不把 landing page、登录页、详情页、metadata 或镜像入口冒充 `primary`；只有服务端真实
  验证的 concrete representation 才能成为可获取 primary。landing-only 候选可保留为事实，
  但不能进入 primary 下载计划或被解释为“可下载”。
- 不绕过登录、验证码、付费墙、DRM、版权、URL/私网/重定向安全策略或平台访问控制。
- 不在 Skill、Registry 配置、测试夹具或仓库中写入平台凭据、Cookie、Token 或浏览器档案。
- 不新增第 14 个 MCP Tool；不改变 ResultSet 不可变、Presentation/Selection 绑定以及
  `prepare -> 用户确认 -> start` 两阶段边界。

## 单一能力权威与数据契约

### 1. Static Capability Descriptor

由 Registry loader 读取并校验的 descriptor 是平台/路线声明的唯一静态入口。每个 descriptor
至少需要服务端生成或校验：

- `descriptor_id`、`descriptor_version`、`descriptor_digest`、`registry_version`；
- 平台、资源对象和 capability scope（search、browse、inspect、resolve、acquire、
  `primary`/landing/metadata 等表示范围）；
- `provider_id`、`provider_version`、`inspector_id`/version、支持的 container/MIME/representation；
- 运行时 readiness 所需的前置条件、auth/policy 依赖、网络/大小/重试限制和显式 fallback
  规则；
- descriptor 的来源、发布时间和兼容策略。

静态 descriptor 只表达“设计上声明支持什么”，不表达当前进程是否已经加载、凭据是否有效、
来源是否可达或某个候选是否有 concrete file。

### 2. Deployment Readiness Snapshot

服务端在启动、配置变更和能力使用前生成 readiness snapshot，至少记录：

- descriptor 引用及 digest、实际加载的 adapter/inspector/provider ID 与版本；
- load/import 结果、健康检查、依赖和 session/auth 状态、policy profile、scope；
- readiness 状态（例如 `ready`、`degraded`、`unavailable`、`auth_required`、
  `policy_blocked`、`feature_not_supported`）及检查时间、原因和有效期；
- 不可用时的显式允许替代路线；没有声明的替代路线必须保持不可用，不得隐式升级 generic。

readiness 是部署/运行事实，不等于候选 Resolution，也不等于用户拥有下载权利。

### 3. Candidate Resolution / Representation

`resource_inspect` 或受支持的 Resolution 路径必须引用 descriptor/readiness，并为每个候选
保留服务端 `resolution_id`、来源指纹、检查器版本、`resolution_status`、`availability`、
`representations`、`capability_ref` 和 failures。Representation 至少区分：

- concrete primary file/media 与 landing/metadata/detail page；
- MIME、大小、格式、来源 URL/域名策略、获取范围和是否可物化；
- 版本、语言、章节/附件关系和必要的 `rights_hint`/未确认状态。

没有 concrete primary representation 时，Resolution 可以是 `landing_only`、`metadata_only`
或 `unresolved`，但不能被 Plan 选择为 primary。

### 4. Policy / Rights Eligibility

Policy 层按当前用户、Flow、来源、representation、平台授权和组织策略重新计算
`eligibility_id`/版本/摘要。`eligible` 只表示当前策略允许尝试，不保证网络成功或版权事实；
`unknown`、`auth_required`、`policy_blocked`、`unsupported` 和来源失效必须保持结构化状态，
不能由模型或 Provider 改写为成功。

### 5. Prepare/Start binding and revalidation

`download_prepare` 必须按资源逐项读取 fresh Resolution/Representation/Eligibility，并把
以下内容绑定到 Plan digest：descriptor/readiness/resolution/capability/eligibility 引用、
selected representation、provider scope、container、policy profile、来源版本和过期时间。

`download_start` 在消费确认令牌之前重新校验同一绑定元组、有效期、Flow ownership、
Presentation/Selection digest、readiness、eligibility、来源和 representation。任一事实过期、
scope 不一致、Provider 变更或策略阻断都必须拒绝/结构化失败并要求重新 prepare；不能依赖
prepare 时的缓存结论。

### 6. Provider / Actual Outcome

Router 只能选择 Plan 已声明且 readiness 仍为可用、scope 匹配的 Provider。Provider 返回的
实际 outcome 必须记录 provider ID/version、request/attempt 摘要、representation、HTTP/策略
结果、校验后的 MIME/魔数/大小/摘要、取消/失败原因和 Asset/Bundle 关系。实际 outcome 与
Plan 不一致时不能伪装成成功；没有可用 primary 的 Job 为 `failed`，已有 primary 但预期项
失败才按现有 Bundle completion 语义记录 `partial`。

## Breaking boundary、迁移与版本策略

### 公共版本策略

- 继续保持 `contract_version=1.0.0`、13 个 MCP 工具和现有 `prepare -> confirm -> start`
  控制流；新增 capability/readiness/resolution/eligibility 引用必须是可选、可忽略且只追加
  字段，不重解释旧字段。
- 当前 Public Tool `catalog_version=1.5.0`，继续保持 `contract_version=1.0.0` 与 13 个
  Public Tools。`catalog_version=1.4.0` 仅是 0024 基线和历史读兼容版本；1.5.0 以可选、
  可忽略的加法字段接入 capability authority，不新增第二个 coverage 权威字段。
- Capability catalog / registry 均为 `1.1.0`；Platform Registry 继续为 `1.0.0`。
- `platform-registry.schema.json` 的静态 descriptor 扩展先使用向后兼容的可选字段和新的
  `registry_version` minor 版本（例如 `1.1.0`）。删除字段、改变旧 enum 含义、把可选字段
  改必填、或要求调用方理解新的必需绑定时，必须切换到 `registry_version=2.0.0`，提供迁移
  工具和明确拒绝旧 descriptor 的错误码。
- 若公共 Tool 输入/输出必须出现新的 required 字段、旧状态语义改变或旧客户端无法安全
  忽略，则把 `contract_version` 提升为 `2.0.0`，并保留旧读路径直到迁移完成；不能在
  `1.0.0` 中偷偷改变语义。

### 数据/运行时迁移

1. 增加 descriptor/readiness/resolution/eligibility/provider outcome 的可选持久化字段或
   受控 JSON snapshot，保留旧 Registry、旧 `coverage_json`、ResultSet/Selection/Job/Asset
   记录可读。
2. 旧 Registry entry 读取为 `legacy_descriptor`，只可用于 search/已有事实读取；没有显式
   provider、scope、readiness 和 concrete representation 时，下载不得自动沿用旧 generic
   路径，必须返回 capability/provider 缺口或要求重新 inspect。
3. 对已存在 Resolution/Plan/Job 逐步回填上游 capability 引用；无法安全回填的记录标为
   unknown/legacy，并在 prepare/start 时要求重新 Resolution/prepare，不猜测历史 provider
   或 rights eligibility。
4. 迁移期间同时支持旧读、新写和幂等 replay；每次新写保存 descriptor/readiness/resolution/
   eligibility/provider 的版本与 digest。完成后删除仅为兼容而存在的隐式 generic fallback，
   并保留一条有观测的拒绝路径。
5. SQLite migration 必须可重复执行、可回滚读取（不要求回滚新事实），运行数据继续写入
   受控用户目录或 `.openclaw-test/`，不把测试数据库、下载资产或凭据提交到仓库。

## 步骤

- [x] completed：A. 冻结 capability descriptor、readiness、Resolution/Representation、eligibility、Plan/provider outcome 契约与 breaking boundary。
- [x] completed：B. 实现 Registry descriptor 校验、版本/digest/scope 和显式 Provider/Inspector 声明，保留旧读路径。
- [x] completed：C. 统一运行时 Adapter/Inspector/Provider loader，生成 readiness snapshot、依赖和结构化不可用状态。
- [x] completed：D. 将 Resolution/Representation 绑定 descriptor/readiness，区分 concrete primary、landing、metadata、物化和版本/权限线索。
- [x] completed：E. 生成 Policy/Rights eligibility，并让 `download_prepare` 逐资源绑定 fresh capability facts、representation 和 plan digest。
- [x] completed：F. 让 `download_start` 重新校验绑定、readiness、eligibility、来源和 Provider scope；删除静默 generic 接管路径。
- [x] completed：G. 持久化实际 Provider outcome、Asset/Bundle 关系和失败/取消事实，同步 Skill 解释与恢复语义。
- [x] completed：H. 完成 0025 范围内的兼容迁移、旧数据恢复、契约/定向/全量/E2E/calibration 验收并切换 active 默认链；真实平台矩阵与 release gate 分别留给 0028/0029。

## 分阶段实施与 Ownership

| 阶段 | 主要工作 | 责任边界/交付物 | 依赖与退出条件 |
|---|---|---|---|
| A. Contract freeze | 冻结 descriptor/readiness/resolution/eligibility/provider outcome 字段、状态、错误码、引用和 digest 规则 | Contract/Schema owner：更新 Registry/Tool/错误码 Schema、兼容说明、fixture；根 Agent 做 breaking review | 无字段双义、版本策略通过；Schema negative tests 先可运行 |
| B. Registry + loader | 实现 descriptor 校验、ID/version/digest、scope、显式 provider/inspector/fallback 声明；loader 输出静态 snapshot | Registry/Adapter owner：`registry.py`、`adapters/base.py`、registry fixtures；禁止以 `acquire=true` 推导 readiness | descriptor 缺失/冲突/未知 provider 有结构化拒绝；旧读路径仍可用 |
| C. Runtime readiness | 统一 Adapter/Inspector/Provider registration、import/load 健康检查、session/policy 依赖、readiness snapshot/TTL | Runtime owner：loader、runtime dependency probe、readiness storage/status；不改变 Skill 语义 | 缺 Provider 不再静默 generic；ready/degraded/auth/policy 状态可查询并可审计 |
| D. Resolution + representation | 让 Inspect/Resolution 引用 descriptor/readiness，区分 primary、landing、metadata、物化和版本/权限线索 | Resolution owner：inspection/representation model、resolution persistence、negative cases | landing-only 不可作为 primary；Resolution replay/过期/来源指纹测试通过 |
| E. Policy + plan binding | 生成并持久化 eligibility；prepare 逐资源绑定 fresh capability facts、representation 和 digest | Policy/Acquisition owner：policy engine、download_prepare、Plan schema/migration | 缺证据/过期/未授权全部结构化失败；Plan 不接受模型拼接字段 |
| F. Start revalidation + provider routing | start 重新校验所有绑定；Router 只选择 declared/ready/scope-matched provider；generic 仅显式 descriptor 可用 | Job/Provider owner：download_start、router、provider adapters、outcome persistence | provider 失败不 generic 接管；plan/outcome mismatch 不报成功 |
| G. Asset/Bundle outcome + Skill sync | 记录 actual outcome 与 Asset/Bundle；Skill 仅解释 facts 并区分 landing/primary/失败/归档边界 | Outcome/Skill owner：Job/Asset metadata、Skill references、recovery guidance | Asset 只由服务端产生；用户可理解解释与事实一致 |
| H. Migration + active boundary | 完成 active 新链默认接入、保留旧读、旧数据恢复和回滚读取边界；删除隐式 fallback | Migration/Release owner：migration、compatibility、recovery tests 与 0028/0029 接续说明 | 新旧数据可恢复且无 silent fallback；真实平台 rollout 与 release gate 不越界到 0025 |

同一阶段最多一个 `in_progress` 子步骤；阶段交付必须包含 Schema、文档、测试和迁移说明，
不得先改代码再补契约。跨阶段共享的唯一权威是服务端生成的 descriptor/readiness/resolution/
eligibility/provider outcome 引用，不得由各模块复制第二套状态。

## 测试矩阵与验证命令

### Contract/Schema

- Registry descriptor 缺 ID/version/digest、scope、provider、未知状态、非法 fallback 时拒绝；
  `acquire=true` 但无 primary scope、无 concrete provider 或无 readiness 不能通过“可获取”
  断言。
- 旧 `registry_version`/旧 `contract_version=1.0.0` fixture 仍可读取；新可选字段能 round-trip；
  breaking fixture 在正确的 major 版本下才接受。
- public coverage 仍是 factual；不暴露 SemanticReview、Skill Gap、StopDecision 或
  arbitrary path/URL/provider 选择字段。

### Runtime/Resolution/Policy

- 缺失/导入失败 Provider、Inspector、session 或 policy dependency：readiness 为结构化
  unavailable/auth/policy 状态，绝不静默 generic。
- 专用 Provider 失败、scope mismatch、版本/来源指纹变化、readiness TTL 过期和 policy
  变更：prepare/start 重新校验并拒绝或要求重新 prepare。
- landing-only、metadata-only、详情页、登录页、镜像入口和 search-only 候选不能成为
  `primary`；只有 concrete file/media Representation 可进入 primary plan。
- `AUTH_REQUIRED`、`FEATURE_NOT_SUPPORTED`、`POLICY_BLOCKED`、`unavailable`、timeout、
  redirect/SSRF/size/MIME/magic mismatch、cancel 和 provider failure 都保持真实错误/结果。

### Persistence/Job/Asset

- 重启/replay 后 descriptor/readiness/resolution/eligibility/provider outcome 引用一致；
  旧记录缺失能力事实时按 unknown 处理，不从标题或聊天记忆补造。
- prepare/start 幂等键只 replay 原响应，不生成新 Plan/Job/Asset；实际 outcome 必须和 Plan
  digest、representation、provider scope、Bundle/Asset 元数据一致。
- 无 primary 的 Job 只能 `failed`；有 primary 且部分预期成员失败才使用现有 `partial` completion；
  取消/quarantine 不可归档。

### End-to-end / Operations

- 运行受影响 Python 的 `compileall`、定向 unittest/pytest、全量回归、stdio client、MCP
  probe/doctor（可用时）和 Markdown link/diff 检查；串行执行并区分功能失败、环境失败、
  timeout/flaky。
- 增加 capability truth calibration：至少覆盖 search-only、landing-only、concrete primary、
  missing provider、provider failure、auth/policy block、版本不确定、重定向/格式校验和重启恢复。
- 输出每层 descriptor/readiness/resolution/eligibility/plan/provider/outcome 的可追溯链，
  机器可比较，不把日志中的模型判断当作服务端事实。

## 退出条件（Exit criteria）

在把本计划标记为 completed 前，必须全部满足：

1. Registry、runtime loader、Resolution/Representation、Policy、Plan、Router、Provider、
   Job/Asset/Bundle 只有一条 capability authority 链，跨模块引用可追溯到 descriptor digest。
2. `acquire=true`、strategy、候选数量、标题或 direction 不再单独触发可获取/可推荐；landing-only
   永不成为 primary。
3. generic Provider 没有任何静默接管路径；若保留 generic，它具有显式 descriptor、scope、
   readiness、policy 和 revalidation 证据，并能在审计中区分专用与 generic 路线。
4. prepare 与 start 都重新校验当前 readiness、Resolution/Representation、eligibility、
   provider scope、来源策略和绑定 digest；过期/冲突结果结构化失败并可恢复。
5. 实际 outcome、Asset/Bundle、失败、取消和归档状态均由 MCP 生成并与计划绑定；模型不能提交
   任意 provider、URL、路径、Asset 或成功状态。
6. 当前 `contract_version=1.0.0`、Public Tool catalog `1.5.0`；0024 的 catalog `1.4.0`、
   旧 Registry/SQLite 记录和幂等 replay 可按迁移说明读取，未通过伪造 execution authority
   升级历史记录。
7. Schema、契约、迁移、runtime、Skill references、定向/全量/e2e/calibration 测试和运维
   文档全部同步，`git diff --check`、Markdown 链接检查及可用的 probe/doctor 通过；未能运行的
   外部环境检查已列出证据和剩余风险。

## 验证

### Python、E2E 与运行时隔离

- 在 `mcp/education-resources` 下执行标准全量 runner：`./scripts/run-tests.sh all`，
  `Ran 482 tests in 20.735s`，`OK`。
- 在 `mcp/education-resources` 下执行标准 E2E runner：`./scripts/run-tests.sh e2e`，
  `Ran 9 tests`，`OK`。
- `compileall_status=0`；生成的 183 个 `.pyc` 全部位于 `/tmp` 隔离 cache。
- runner 的真实 TERM smoke：退出码 `143`，测试根在退出后不存在，子进程没有继续运行。
- stdio fixture 使用统一 hermetic 环境，不继承父进程的 session-manager、SearxNG、凭据、
  Cookie、Token、proxy、任意 `PYTHONPATH` 或用户 site 配置；initialize timeout 仍为 5 秒。

### 静态契约与文档门禁

- JSON 文档 40 个、JSON Schema 23 个、本地 Schema `$ref` 570 个，全部可解析和解析到本地目标。
- Public Tools 13 个，Tool catalog `1.5.0`，Public contract `1.0.0`。
- 错误码 78 个，metadata 78 个；Platform Registry `1.0.0`，16 个平台。
- Capability routes 3 条，Capability catalog / registry 均为 `1.1.0`；所有 descriptor 的
  fallback 均关闭，`allowed_scopes=[]`、`on_errors=[]`。
- 代码/契约最终门禁时覆盖 30 个 changed Markdown、73 个本地链接；完成快照写入后再次进行
  文档级复验，仍为 30 个 changed Markdown，现有 74 个本地文件链接全部可解析；
  `git diff --check` 与两份未跟踪计划文档的独立 whitespace check 均通过。

### OpenClaw 与默认 Agent

- OpenClaw `2026.7.1-2`、Node `v24.18.1`；Gateway 状态和连接 probe 正常。
- `openclaw config validate`：配置有效。
- `openclaw mcp doctor education-resources --probe --json`：`ok=true`，`issues=[]`。
- `openclaw mcp probe education-resources --json`：13 Tools，`diagnostics=[]`。
- 默认 Agent 自然语言 smoke 成功，调用链仅为 `read -> resource_flow_start -> resource_search
  -> resource_presentation_save`；没有选择、下载或归档调用，也没有工具失败或 fallback。
- `openclaw mcp status` 已输出 `education-resources configured/enabled/ok=true` 的有效 JSON，
  但 CLI 进程未在 60 秒内自行退出，外层守护返回 `124`。由于 `gateway status`、`mcp list/show`、
  doctor/probe 和真实 Agent 回合均正常，此项记录为 OpenClaw CLI 单路径退出异常，不阻塞 0025。

## 结果

- Capability Descriptor -> Readiness -> Resolution/Representation -> Eligibility -> Plan authority
  -> immutable execution binding -> exact Provider -> Outcome -> Bundle/Asset -> Archive 已收敛为
  单一服务端权威链，项目版本统一为 `0.2.0`。
- 当前冻结机器事实：Public contract `1.0.0`、Public Tool catalog `1.5.0`、13 Tools；Capability
  catalog / registry `1.1.0 / 1.1.0`；Platform Registry `1.0.0`、16 platforms。
- 精确三条 acquisition route：`generic-direct@1.0.0 / direct_file / primary_resource`、
  `generic-web-materializer@1.0.0 / web_materialize / landing_page`、
  `smartedu-resource@1.0.0 / direct_file / primary_resource`；没有隐式 fallback。
- `resource_download_start.authority_digest` 是 optional exact-match：省略时服务端读取并重校验
  Plan authority，提供时必须完全一致。SQLite `cancelling` 是唯一持久化取消权威，Provider 返回
  或 Runner event 不能伪造取消。终态 Outcome 只允许完全一致的只读 replay。
- Legacy Job/Outcome/Archive 保持可读；缺少 `job_execution_items` 时不得新建 Bundle、Asset 或
  Archive。Legacy Outcome 缺少合法 execution digest 时，公共 `resource_job_status` 省略
  `execution`，不会输出伪造值或字符串 `"None"`。
- 真实平台合法凭据、认证 readiness、逐平台 Search -> Acquire -> Archive -> Recover 矩阵属于
  [`0028`](0028-real-openclaw-platform-e2e.md)；benchmark 与 release gate 属于
  [`0029`](../0029-retrieval-benchmark-release-gate.md)，未被伪装为 0025 已完成。
- 剩余非阻塞风险：`RawMcpClient` 的 `select.select(TextIOWrapper)` 仍有 POSIX 文本预读和原生
  Windows pipe 兼容风险；runner 信号 smoke 尚未固化为自动测试；OpenClaw `mcp status` 存在
  单路径退出异常。这些不通过临时 timeout、fallback 或补丁路线掩盖。
