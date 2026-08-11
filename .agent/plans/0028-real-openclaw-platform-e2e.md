# 0028 Real OpenClaw and Real Platform E2E

- 状态：in_progress
- 创建日期：2026-08-08
- 完成日期：未完成
- 范围：真实 OpenClaw 默认 Agent、唯一入口 Skill、当前 13 个 MCP Tool、真实 stdio MCP、平台 readiness、合法会话、Search → Inspect → Present → Select → Confirm → Acquire → Archive → Recover 全链路
- 前置条件：[`0025 Platform Capability Contract Alignment`](archive/0025-platform-capability-contract-alignment.md) 与 [`0027 Platform Acquisition Enablement`](archive/0027-platform-acquisition-enablement.md) 已完成；只有 0027 证明为 executable 的 route 才进入成功路径，结构化阻断项只验证真实 blocked 事实
- 关联计划：[`0023 Retrieval E2E Hardening`](0023-retrieval-e2e-hardening.md)；本计划通过前，0023 的真实 Agent/平台阻塞项不得关闭

## 目标

证明真实 OpenClaw 默认 Agent 能从自然语言出发，使用当前工作区唯一入口 Skill 和同一套
13 个 `resource_*` Tool 完成可信教育资源闭环，并逐平台记录真实部署、网络、认证、检查、
获取和策略事实。固定 fixture、直接调用 Service、MCP probe 或 Adapter 已注册都不能替代
真实 Agent 回合，也不能被解释为平台 production-ready。

## 硬边界

- 0027 已完成；当前成功路径只允许使用机器 catalog 和默认 ResourceService 中正式接入的 exact route。
  Bilibili、Douyin、Ximalaya、Anna/Libgen 与 `web_capture` 保持 0027 冻结的结构化阻断，除非先通过
  独立实现计划解除前置条件，不得在 0028 临时接入或用 generic/capture 替代。
- 不新增第 14 个 MCP Tool，不恢复 legacy Skill，不让 Agent 拼接 shell、脚本、二进制或路径。
- 所有副作用继续执行 `prepare -> 用户明确确认 -> start`；不得自动确认或重放网络副作用。
- 认证只使用用户/平台合法授权的 session-manager/SecretRef。默认通过受控浏览器捕获；用户明确指定
  平台、用途并授权保存时，也可把其合法获得的 canonical Cookie/Token 一次性直送
  `resource_session_save.session_data`。凭据不得进入其他 Tool、日志、计划、仓库或证据正文。
- 不绕过验证码、登录、付费墙、DRM、robots/访问控制或版权/策略边界。
- 不以增加超时、盲目重试、降低 SSRF/重定向/大小/MIME/magic 校验或静默 generic fallback
  换取“通过”。失败必须保持真实结构化状态。
- OpenClaw 命令串行执行；先区分环境锁、进程、网络、认证、策略与产品功能失败，再决定动作。

## 2026-08-11 Step E Direct Import Task Spec

### Goal

用户明确指定支持的平台、认证用途并授权保存其合法获得的 Cookie/Token 时，Agent 能通过现有
`resource_session_save` canonical 输入完成一次最小化本地保存，并只返回非敏感状态。

### Non-goals

- 不接收或代填账号、密码、验证码、扫码内容、短信码或 MFA；不绕过登录、付费、DRM 或访问控制。
- 不新增 Tool、Schema、状态源、任意 Header/文件导入或兼容层，不改变平台 policy 和 exact Provider。
- 不把 `stored/no_probe`、合成测试或本地落盘解释为远端认证有效或 production-ready。

### User / Business Behavior

```text
Given: 用户明确指定受支持平台和用途，并主动提供合法 Cookie/Token 且授权保存
When: Agent 执行 direct import
Then: 原值只作为一次 resource_session_save.session_data 输入，响应只含状态/计数/revision
```

### Business Invariants

- 默认仍为官方页面自行登录和 Browser capture；direct import 不能与同一次 browser capture 混用。
- Agent 不索取账号/密码/验证码/MFA，不复述、展示、截图、写临时文件或把凭据交给其他 Tool。
- save 失败、响应不确定或验证失败时不得自动重放或要求重发；先读权威 status 后停止并重新取得授权。
- 保存后仍须 fresh Search/Inspect、Resolution/Eligibility、新 Plan 和独立用户确认，才能 Start。

### Current System Understanding

- `resource_session_save` Schema 已接受平台 canonical `cookies`/`tokens`，SessionStore 负责最小化、权限、
  幂等和不回显；无需新增机器接口。
- session-manager 是唯一可写凭据权威源；education-resources 只读共享 store，其他 Tool 不接收凭据。

### Expected Change Surface

- 修改 active session-manager README/server instructions/login guide、唯一入口 Skill、当前架构/计划文档。
- 补充 canonical SmartEdu direct-token 的 contract/stdio 行为测试；不修改契约版本与错误码。
- 不修改 `AGENTS.md`、archive、legacy、平台 policy、Acquisition/Archive 门禁。

### Acceptance Criteria

```text
AC-01: 明确授权的 canonical SmartEdu token 可保存为 stored，响应、status 与错误不含原值。
AC-02: 账号/密码/验证码、未知字段、任意 Header/文件仍被拒绝，失败不引入自动重放语义。
AC-03: direct import 后仍执行 session/readiness 与 fresh Resolution/Eligibility 门禁。
```

### Validation Plan

- Session-manager contract、store、stdio 定向测试和 Python compileall。
- Education-resources standalone bridge/SmartEdu Adapter 定向测试。
- Markdown 本地链接、敏感值扫描、`git diff --check` 和 live MCP Tool/状态只读复核。

### Complexity Exception

No。复用现有 canonical save 输入与唯一 SessionStore 权威源。

### Dependency Research

No。没有新增或升级第三方依赖；继续使用已注册的 `openclaw-session-manager==0.4.0` 与现有 MCP 契约。

### Completion Record

```text
[x] implemented
[x] statically checked
[x] targeted unit tested
[x] subsystem/integration tested
[x] backend E2E tested
[x] real Agent/user-flow tested
[ ] visual behavior inspected (not applicable)
[ ] full repository regression tested

Not validated: 有效 SmartEdu 会话下的 Search/Inspect/Resolution/Eligibility 与后续 Plan/Job 成功路径。
Known remaining risks: 当前保存值被真实平台以认证 HTTP 403 拒绝；POSIX store 依赖 0700/0600 权限而非 Windows DPAPI。
```

## 权威证据模型

每次真实验收记录至少包含：

- 日期、OS/WSL、OpenClaw/Node/Python/包版本及 Agent 模型标识；
- 当前 Git branch/commit/dirty 摘要和 Skill/MCP 实际加载路径；
- MCP config/status/doctor/probe 输出摘要、13 Tool 名称与 schema/catalog digest；
- 对话原始自然语言、Agent 工具调用序列、服务端稳定 ID/状态、人工确认点；
- descriptor/readiness/resolution/eligibility/plan/execution/outcome/asset/archive 追踪摘要；
- 平台网络、认证、Inspect、Acquisition、Policy 结果及结构化失败码；
- 是否产生资产、资产角色/格式/哈希、是否归档、重启后恢复结果；
- 所有敏感值在写入证据前完成脱敏，仓库中只保留机器可比较的非敏感摘要。

## 步骤

- [x] completed：A. 复核 0025/0027 completion evidence，冻结本次 OpenClaw、MCP、Skill、catalog、capability registry 与数据库 migration 基线
- [x] completed：B. 串行执行 OpenClaw 环境预检，证明当前工作区、唯一 Skill、13 Tool、schema/catalog、仓库外运行目录与凭据边界正确
- [x] completed：C. 建立不含生产凭据的真实 Agent 证据采集模板和逐平台 readiness 记录，先执行无需认证平台
- [ ] in_progress：D. 执行文章、网页物化、视频、音频、图书/版本、课程/Bundle、混合检索、恢复八类自然语言 Agent 回合
- [ ] blocked：E. 在合法会话可用的平台验证 AUTH_REQUIRED → session ready → 新 Plan/Job 恢复；SmartEdu canonical direct import 已保存为 `stored/no_probe`，但 fresh 真实 Search 返回认证 HTTP 403，等待新的合法有效会话
- [x] completed：F. 验证中断、重启、幂等、Selection/Plan 失效、取消、partial、无 primary、策略拒绝与归档限制
- [x] completed：G. 逐平台完成 readiness 分级与用户文案审计；只有完整证据通过的平台才可标 `production_ready`
- [ ] pending：H. 运行离线 stdio/全量回归，更新 0023、CURRENT_ARCHITECTURE、DEVELOPMENT_PLAN 和运维证据，由根 Agent 完成逐项验收

## 环境预检

按顺序执行并保存脱敏摘要：

```bash
openclaw --version
openclaw config validate --json
openclaw mcp status --verbose
openclaw mcp doctor education-resources --probe
openclaw mcp probe education-resources --json
```

必须额外核实：

1. OpenClaw 实际加载当前仓库 `skills/learning-resource-flow/` 和
   `mcp/education-resources/`，不是旧同步目录。
2. Agent allowlist 只发现唯一 active Skill；`legacy/skill-pipeline-v1/` 不参与正常运行。
3. probe 精确返回当前 catalog 的 13 个 Tool，输入 schema、必填字段和 catalog digest 一致。
4. SQLite、jobs/download/library、session/browser profile、SecretRef 均位于仓库外受控目录。
5. 测试配置与生产配置分离，环境变量和日志不泄漏凭据或任意本地路径。

## 2026-08-11 环境基线与预检证据

- Git：branch `codex/growth-resource-taxonomy-rework`，HEAD
  `0dc163adbab8cc5eb3f8700c118179614af14d9b`；工作树已有用户修改，预检未覆盖、回滚或清理这些改动。
- 运行环境：macOS 26.5.2 arm64、OpenClaw `2026.7.1-2 (0790d9f)`、Node `v24.19.0`、
  Python `3.14.5`；默认 Agent 为 `main`，模型标识为 `deepseek/deepseek-v4-flash`。
- Skill：仓库顶层 `skills/` 只含 `learning-resource-flow`。该 Skill 已复制到
  `/Users/arale/.openclaw/workspace/skills/learning-resource-flow`；`skills check` 将其列为 eligible、
  model-visible 和 command-visible。排除 OpenClaw 自身 `.openclaw/source-origin.json` 后，源与安装副本
  8 个文件的当前内容摘要均为 `e4798e89bd8a24029454279614acba733d712e4ef89bfacf46fac66a844062a1`。
  该摘要包含真实回合后新增的 MCP 封闭工具面、版本、extend 总容量、候选可访问性、停止预算、
  重复读取保护、native platform 封闭命名空间、AUTH_REQUIRED 证据边界，以及 extend 后必须使用当前
  public resource ID 重新 Inspect 的约束、本体 unknown 不得触发登录建议，以及完整用户可见列表必须
  先于 PresentationSave、受限/重复项不得默认进入 Presentation，以及 idempotency key 只能使用合规
  ASCII 字符且不能复制脱敏缩写，以及低相关结果不能在无 Tool 证据时归因为 query 被拆分/改写的边界；
  当前摘要还包含明确授权 canonical direct import 只能进入一次 `resource_session_save`、不得回显/转发/
  自动重放的边界；各证据记录继续保留其回合实际加载的旧摘要。
- MCP：运行时固定在仓库外
  `/Users/arale/.local/share/quanxiao/education-resource-mcp-runtime/0.2.0-9e17ea8c`，数据与资源库固定在
  `/Users/arale/.local/share/quanxiao/education-resource-mcp-e2e/0028-20260811`。配置只传递上述两个非敏感
  数据目录变量；源码快照、SQLite、jobs、sessions 与 library 均未写入仓库。
- 部署一致性：运行时源码与仓库源码的 66 个 Python 文件内容摘要均为
  `32a8865b46e00d527612b0b60faa1e946f8f39b3071d26518d50e662828a12df`；23 个 Schema JSON 摘要均为
  `954f1ad2a133d5220709c6a5400ae13d0fc7bd27fcedfec627d42c99a076f2ae`；170 个运行时快照文件摘要
  均为 `9e17ea8c0edd83c107b4183fab509c6720abf660915707a9bb63bae741d32729`。运行时依赖校验和直接 stdio
  EOF smoke 均通过；旧 `0.2.0-e09bc434` 运行时未覆盖、未删除，可用于精确回退。
- 契约冻结：tool catalog `1.5.0`，13 个业务 Tool；tool catalog、capability descriptors、platform
  registry、common schema 的 SHA-256 分别为
  `f1afbacb42e587a12320f49e682ca05189e477a5d26d9f1cd18877b1a7dea893`、
  `767ca961970e1696a16f1caa04983d06a620a9505432d4ed8ee289e2f6ada6e6`、
  `a3bbf7a24c396d042c4271a3b99dc36b217d16fd05783923bf21da4f0c16d208`、
  `aab316c69ddc0395c1d0d1bf706b49e6b4b00b9f2d67a8ac13d8d0603f760902`。
- OpenClaw 门禁：`config validate`、`mcp status --verbose`、`mcp doctor --probe`、`mcp probe` 串行通过；
  probe 无 diagnostics。实时 MCP 与当前仓库分别启动后，完整 `list_tools` 结果完全一致，摘要为
  `9565ee6e2862b0ea825a7b536aed39b608aab61582721f0cc6ce336fcf4c4680`；工具名与 catalog 精确一致，
  每个输入 Schema 的 required/properties 与合同一致。
- 部署偏差：非 editable wheel 不包含顶层 `contracts/`，因此不能满足当前源码布局；该失败探测未写入
  OpenClaw 配置。预检改用现行 README 规定的仓库外版本化源码快照加 editable install，成功后已精确删除
  本轮生成的 89 MB 失败 wheel 运行时。这个 packaging 限制不改变 0028 的产品契约，后续应独立处理。

## Milestone checkpoint（A/B）

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no
Actual user flow affected?: deployment only; no Agent turn or acquisition started
Actual user flow validated?: no; this is the gate for Step C/D
Scope drift detected?: no
```

## 真实 Agent 对话矩阵

### 脱敏证据记录模板

每次真实回合使用 `EV-0028-YYYYMMDD-NN`，只在本计划保存以下非敏感摘要；原始 CLI/Agent 输出、
SQLite、session、confirmation token、资源 URL 和下载文件不进入仓库：

```text
evidence_id:
evidence_level: offline_fixture | stdio_process | real_openclaw | real_platform
observed_at_utc:
environment_fingerprint:
natural_language_goal:
loaded_skill_and_mcp_digest:
tool_sequence:                   # 只留 Tool 名、顺序、稳定 ID 类型和结构化状态
platform_observations:
human_confirmation: not_reached | requested | explicitly_confirmed | declined
side_effects: none | state_only | network_acquisition | archive
asset_archive_summary:
reason_codes:
redactions_applied:
proves:
does_not_prove:
```

readiness 字段只允许 `pass`、`fail`、`blocked`、`not_applicable`、`not_observed`；不得把
`code_present`、fixture、静态 Registry 或单次 probe 自动换算为 `production_ready=pass`。

### 当前逐平台 readiness（真实 Agent、平台与环境证据）

- `observed_at`：`2026-08-11T04:19:12Z`
- `environment_fingerprint`：`981bf39dad6388e36529cff8c18e5db832787fe377ffe32dc073ac37be729fbe`
- `evidence_ids`：`EV-0028-BASELINE-01`、`EV-0028-0027-DISPOSITION-01`、
  `EV-0028-20260811-01`、`EV-0028-20260811-02`、`EV-0028-20260811-03`
  、`EV-0028-20260811-04`、`EV-0028-20260811-05`、`EV-0028-20260811-06`、
  `EV-0028-20260811-07`、`EV-0028-20260811-08`、`EV-0028-20260811-09`、
  `EV-0028-20260811-10`、`EV-0028-20260811-11`、`EV-0028-20260811-12`、
  `EV-0028-20260811-13`、`EV-0028-20260811-14`、`EV-0028-20260811-15`、
  `EV-0028-20260811-16`
- EV-15 只刷新安装、MCP 配置和认证状态事实；平台网络、Search、Inspect、Acquisition 与 Policy
  字段沿用此前同一源码/运行时证据，本轮没有重新访问真实平台。
- EV-16 新增一次明确授权的 SmartEdu canonical direct import 和 fresh 真实 Agent Search；本地保存成功，
  但平台返回认证 HTTP 403、0 候选，未执行 Inspect，auth recovery 因此为 fail 而非 pass。
- `runtime_component_loaded` 记为 `S/I/A`，分别代表 Search、Inspect、Acquisition；`A` 只写 exact
  Provider，不把 generic 路由或历史 downloader 源码算作平台 Provider。

| platform | code_present | fixture_passed | runtime_component_loaded (S/I/A) | network_smoke_passed | auth_flow_passed | search_passed | inspect_passed | acquisition_passed | policy_reviewed | production_ready | reason_codes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| generic | pass | not_observed | pass/pass/`generic-direct`,`generic-web-materializer` | pass | not_applicable | pass | pass | not_observed | pass | fail | `REAL_AGENT_BEHAVIOR_GATE_PASS`,`PUBLIC_READ_ONLY_PATH_PASS`,`HONEST_STOP_WITH_GAP_PASS`,`PRESENTATION_RECOVERY_PASS`,`QUERY_PRESERVATION_PASS`,`MIXED_RECALL_FAILED`,`BOOK_METADATA_ONLY`,`PRIMARY_DOCUMENT_NOT_PROVEN`,`ACQUISITION_NOT_RUN` |
| bilibili | pass | not_observed | pass/pass/blocked | pass | not_applicable | pass | pass | blocked | blocked | fail | `SEARCH_PASS`,`INSPECT_PASS`,`LANDING_AVAILABLE`,`VIDEO_REPRESENTATION_UNKNOWN`,`NO_PRIMARY_VIDEO`,`COURSE_BUNDLE_NOT_PROVEN`,`POLICY_BLOCKED`,`DEPENDENCY_MISSING` |
| douyin | pass | not_observed | pass/blocked/blocked | not_observed | blocked | not_observed | not_applicable | blocked | blocked | fail | `POLICY_BLOCKED`,`AUTH_REQUIRED`,`SESSION_MANAGER_REGISTERED`,`SESSION_STATUS_NOT_OBSERVED`,`AUTH_RECOVERY_NOT_RUN` |
| zhihu | pass | not_observed | pass/pass/blocked | pass | blocked | blocked | not_observed | blocked | not_observed | fail | `AUTH_REQUIRED`,`CAPABILITY_NOT_DECLARED`,`SESSION_MANAGER_REGISTERED`,`SESSION_STATUS_NOT_OBSERVED`,`AUTH_RECOVERY_NOT_RUN` |
| smartedu | pass | not_observed | pass/pass/`smartedu-resource` | pass | fail | pass | pass | not_observed | pass | fail | `SEARCH_PASS`,`INSPECT_PARTIAL`,`LANDING_AVAILABLE`,`AUTH_REQUIRED_CANDIDATE`,`SESSION_MANAGER_REGISTERED`,`SESSION_STATUS_STORED_NO_PROBE`,`DIRECT_IMPORT_AUTHORIZED`,`AUTH_SEARCH_HTTP_403`,`AUTH_RECOVERY_FAILED`,`VIDEO_DOCUMENT_REPRESENTATIONS_UNPROVEN`,`COURSE_BUNDLE_NOT_PROVEN`,`ACQUISITION_NOT_RUN` |
| ximalaya | pass | not_observed | pass/pass/blocked | pass | not_observed | pass | pass | blocked | blocked | fail | `SEARCH_PASS`,`INSPECT_PASS`,`LANDING_AVAILABLE`,`AUDIO_REPRESENTATION_UNKNOWN`,`NO_PRIMARY_AUDIO`,`ACQUISITION_POLICY_BLOCKED`,`AUTH_FLOW_NOT_RUN`,`DEPENDENCY_MISSING` |
| cctv | pass | not_observed | pass/blocked/blocked | not_observed | not_observed | not_observed | not_applicable | blocked | not_observed | fail | `CAPABILITY_NOT_DECLARED` |
| yixi | pass | not_observed | pass/blocked/blocked | not_observed | not_observed | not_observed | not_applicable | blocked | not_observed | fail | `CAPABILITY_NOT_DECLARED` |
| kepu | pass | not_observed | pass/blocked/blocked | pass | not_observed | pass | not_applicable | blocked | not_observed | fail | `SEARCH_PASS`,`NO_RETAINED_CANDIDATE`,`CAPABILITY_NOT_DECLARED` |
| baiduwenku | pass | not_observed | pass/blocked/blocked | fail | not_observed | fail | not_applicable | blocked | not_observed | fail | `SEARCH_HTTP_403`,`CAPABILITY_NOT_DECLARED` |
| runoob | pass | not_observed | pass/blocked/blocked | not_observed | not_observed | not_observed | not_applicable | blocked | not_observed | fail | `CAPABILITY_NOT_DECLARED` |
| nlc | pass | not_observed | pass/pass/blocked | pass | not_observed | pass | fail | blocked | not_observed | fail | `SEARCH_PASS`,`INSPECT_PLATFORM_UNAVAILABLE`,`ACQUISITION_NOT_RUN`,`CAPABILITY_NOT_DECLARED` |
| open163 | pass | not_observed | pass/blocked/blocked | not_observed | not_observed | not_observed | not_applicable | blocked | not_observed | fail | `CAPABILITY_NOT_DECLARED` |
| annas-archive | pass | not_observed | pass/pass/blocked | pass | not_observed | pass | not_observed | blocked | blocked | fail | `SEARCH_PASS`,`NO_RETAINED_CANDIDATE`,`POLICY_BLOCKED` |
| weibo | pass | not_observed | pass/blocked/blocked | not_observed | not_observed | not_observed | not_applicable | blocked | not_observed | fail | `CAPABILITY_NOT_DECLARED` |
| wechat | pass | not_observed | pass/blocked/blocked | pass | not_observed | pass | not_applicable | blocked | not_observed | fail | `SEARCH_PASS`,`INSPECT_FEATURE_NOT_SUPPORTED`,`CAPABILITY_NOT_DECLARED` |

### 2026-08-11 Step G readiness 与用户文案验收

根 Agent 在子 Agent 只读审计后独立解析 Registry 与本表：两者顺序一致且均为 16 个唯一 platform ID，
无缺失、无额外项、标量字段均只使用允许枚举，`production_ready=fail` 为 `16/16`。本轮没有新增平台
调用，也没有把 code、fixture、Registry、Descriptor、probe 或 Step F 的 stdio 证据提升为真实平台成功。

| platform | 当前允许的最强用户文案 |
| --- | --- |
| generic | 已找到并核验公开文章候选，可比较；网页物化、正文下载与归档尚未验证。 |
| bilibili | 已搜索并检查到落地页；视频本体尚未证实，当前获取受策略与依赖阻断。 |
| douyin | 当前观测到合法认证要求，获取仍受策略阻断；未证明可检查或获取本体。 |
| zhihu | 当前真实路径需要合法认证；网络可达不代表已经可搜索、检查或获取。 |
| smartedu | 历史回合可搜索并部分检查候选；本次直导会话后的 fresh 搜索收到认证 HTTP 403，当前不能称已登录或可获取，视频/文档本体和课程 Bundle 均未证实。 |
| ximalaya | 可搜索并检查到落地页；音频本体尚未证实，获取受策略/依赖阻断，认证流程未运行。 |
| cctv | 当前未观察到原生搜索、检查或获取成功路径。 |
| yixi | 当前未观察到原生搜索、检查或获取成功路径。 |
| kepu | 本次可检索但未保留相关候选；本体未核验，当前无可获取路径。 |
| baiduwenku | 本次搜索收到 HTTP 403；未确认可用资源，不能推断平台永久故障或资源不存在。 |
| runoob | 当前未观察到原生搜索、检查或获取成功路径。 |
| nlc | 可检索候选；本次检查时平台不可用，尚未证实可获取本体。 |
| open163 | 当前未观察到原生搜索、检查或获取成功路径。 |
| annas-archive | 本次未形成可用候选，获取受策略阻断；metadata/landing 不代表书籍正文可得。 |
| weibo | 当前未观察到原生搜索、检查或获取成功路径；静态认证字段不代表本次已观察登录墙。 |
| wechat | 可搜索；当前 Inspect 功能不支持，本体尚未核验，不能解释为资源不存在。 |

Step G 因此标为 `completed`，只表示分级和文案边界已经逐平台验收；所有平台仍非 production-ready，
且该结论不解除 Step D 的用户选择/独立确认门禁，也不代表 0028 整体完成。

### EV-0028-20260811-14 — Step E 合法会话恢复前置条件精确阻断

```text
evidence_id: EV-0028-20260811-14
evidence_level: real_openclaw configuration + local runtime environment; no real_platform request
observed_at_utc: 2026-08-11T01:44:01Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 核对 AUTH_REQUIRED → 合法 session ready → 新 Plan/Job 的当前可执行前置条件；禁止登录、凭据读取、平台探测和业务副作用
loaded_skill_and_mcp_digest: education-resources runtime 0.2.0-9e17ea8c；OpenClaw 配置 valid；未加载 session-manager
tool_sequence: OpenClaw MCP status -> session-manager probe(not configured) -> config validate -> safe env-key audit -> package metadata audit -> empty session-directory count
platform_observations: OpenClaw 只注册 education-resources；没有 4 个 resource_session_* Tool；education-resources 未配置 standalone store bridge；runtime 未安装 openclaw-session-manager；当前受控 legacy sessions 目录文件数为 0
human_confirmation: not_reached
side_effects: none
asset_archive_summary: no session save/delete, Flow, Selection, Plan, Job, Asset or Archive
reason_codes: SESSION_MANAGER_NOT_CONFIGURED, SESSION_BRIDGE_NOT_CONFIGURED, SESSION_MANAGER_PACKAGE_MISSING, LEGAL_SESSION_NOT_AVAILABLE, NO_CREDENTIAL_CONTENT_READ
redactions_applied: 配置只记录安全键名/布尔事实；不记录 store 路径、Cookie、Token、session 原文或业务 ID
proves: 当前环境不能合法执行 Step E；缺失条件会硬阻断而不是静默 fallback 或假装 session ready
does_not_prove: 任一平台当前 session 状态、远端登录有效性、AUTH_REQUIRED 恢复、fresh Resolution/Eligibility、Plan/Job 或 Provider 成功
```

EV-14 当时将 Step E 标为 `blocked`，恢复条件包括安装/注册独立 session-manager、让两个 MCP 指向
同一受控 store 并验证包可导入；这些环境前置条件已由 EV-15 解除。合法登录、fresh Resolution、
新 Plan/Job 与 exact Provider 的要求没有改变。

### EV-0028-20260811-15 — session-manager 安装/注册通过，会话仍缺失

```text
evidence_id: EV-0028-20260811-15
evidence_level: real_openclaw configuration + stdio_process + embedded default Agent fallback; no authenticated real_platform request
observed_at_utc: 2026-08-11T03:18:52Z
environment_fingerprint: c761d49d231a074844cdfce163c05d4e7b504de2729cc50ecae89e148b1ec61c
natural_language_goal: 安装并注册独立 session-manager，配置 education-resources 只读共享同一受控 store，并只读核对 SmartEdu 当前会话状态；禁止接收聊天 Cookie、登录、远端探活和业务副作用
loaded_skill_and_mcp_digest: learning-resource-flow 源与安装副本 8 文件一致，当前清单摘要 488f5efc19f247724b81fc5ac5a40e068481da58db06f71d4ae799107f8995f7；education-resources runtime 0.2.0-9e17ea8c；openclaw-session-manager 0.4.0，源码摘要 0af0af196363c510b41cfdf7279f1068c1a67774746a89d70eeeb5baa70ebe12
tool_sequence: targeted unit/bridge tests -> package install -> OpenClaw MCP add/set/reload -> config validate -> MCP status/doctor/probe -> synthetic standalone bridge Adapter smoke -> stdio status/login-guide metadata -> default Agent status
platform_observations: 两个 MCP configured/enabled/ok；共享 store=true、owner-only mode=0700、credential file count=0；session-manager 精确发现 4 Tool 且无 diagnostics；education-resources 13 个业务 Tool 与 catalog 精确一致且无 diagnostics；合成 SmartEdu token 与 Zhihu Cookie 的跨包读取 smoke 通过；SmartEdu 真实本地 status=missing、probe_supported=false，省略的 probe_status 按契约解释为 no_probe
human_confirmation: 安装/注册已获用户明确授权；平台登录确认 not_reached
side_effects: state_only
asset_archive_summary: 仅修改仓库外 Python runtime、OpenClaw MCP 配置、空私有 store 目录和独立 Agent session；没有 session save/delete、Flow、Selection、Plan、Job、Asset 或 Archive
reason_codes: SESSION_MANAGER_INSTALLED, SESSION_MANAGER_REGISTERED, SESSION_BRIDGE_CONFIGURED, SESSION_STORE_EMPTY, SESSION_STATUS_MISSING, LEGAL_SESSION_NOT_AVAILABLE, CHAT_COOKIE_INPUT_FORBIDDEN, GATEWAY_1006_EMBEDDED_FALLBACK
redactions_applied: 只记录版本、摘要、计数、布尔值和状态枚举；不记录 store 路径、登录 URL、Cookie、Token、session 原文、配置值或业务 ID
proves: 安装、注册、共享 store、包可导入和 Tool 发现前置条件已经满足；无会话时保持 missing，不回退 legacy store，也不伪造 session ready
does_not_prove: 合成 bridge smoke 不证明真实凭据；本证据也不证明 Gateway 正常回合、用户已登录、远端平台接受会话、AUTH_REQUIRED 恢复、fresh Resolution/Eligibility、Plan/Job、Provider、Asset、Archive 或 production readiness
```

### D-0028-20260811-01 — 明确授权的 canonical direct import

EV-15 记录的是当时生效的“聊天凭据禁用”规则，保持原文作为历史证据。自本决策起，默认仍使用受控
浏览器捕获；用户主动提供其合法获得的 Cookie/Token，并明确指定受支持平台、认证用途和保存授权时，
Agent 可将 canonical 值一次性直送独立 `resource_session_save.session_data`。不得索取或代填账号、密码、
验证码、短信码或 MFA；不得复述、展示、截图、写日志/计划/仓库、转发给其他 Tool、混入 browser
capture，或在 save 失败/响应不确定后自动重放。此决策不改变 session/readiness、平台 policy、exact
Provider、fresh Resolution/Eligibility、Plan 和独立确认门禁。

### EV-0028-20260811-16 — direct import 已落盘，真实 SmartEdu 仍返回认证 403

```text
evidence_id: EV-0028-20260811-16
evidence_level: local stdio credential write + real_openclaw embedded fallback + real_platform SmartEdu Search
observed_at_utc: 2026-08-11T04:17:42Z..2026-08-11T04:19:12Z
environment_fingerprint: 981bf39dad6388e36529cff8c18e5db832787fe377ffe32dc073ac37be729fbe
natural_language_goal: 用户明确授权把其合法 SmartEdu canonical token 保存到既有受控 store，并只读验证是否解除 AUTH_REQUIRED；禁止选择、Presentation、Prepare、Start、下载和归档
loaded_skill_and_mcp_digest: learning-resource-flow 源与安装副本 8 文件一致，摘要 e4798e89bd8a24029454279614acba733d712e4ef89bfacf46fac66a844062a1；education-resources runtime 0.2.0-9e17ea8c；openclaw-session-manager 0.4.0，当前 22 个 tracked source 文件摘要 6cb57d04514d611c5655685fe1a88b8e40c77fb23c3b7e886ff050b708428935
tool_sequence: constraint/task-spec update -> session-manager 66-test suite + education bridge/SmartEdu 31 tests -> package/Skill deploy -> config/probe -> pre-save status(missing) -> exactly one resource_session_save -> status(stored/no_probe) -> real Agent session status -> new FlowStart -> SmartEdu Search -> FlowStatus; no candidate so Inspect not called
platform_observations: direct save ok、stored_credential_count=1、discarded=0、idempotent_replay=false、response contains no credential；owner-only store/file mode=0700/0600；fresh SmartEdu Search status=failed、PARTIAL_FAILURE、authentication HTTP 403、retryable=true、candidate_count=0、coverage=empty；flow hash=752a111b1806；Gateway 1006 后 embedded DeepSeek 回合成功结束
human_confirmation: 用户已明确指定 SmartEdu、测试用途并授权本地保存；没有下载选择或确认
side_effects: one authorized credential_state_write + one state-only Flow; no Selection, Presentation, Plan, Job, Asset or Archive
asset_archive_summary: no resource candidate, Resolution, Eligibility, Plan, Job, Asset or Archive；Inspect 因无 resource_id 未执行
reason_codes: DIRECT_IMPORT_AUTHORIZED, SESSION_STORED_NO_PROBE, REAL_PLATFORM_AUTH_HTTP_403, AUTH_REQUIRED_NOT_RESOLVED, ZERO_CANDIDATES, INSPECT_NOT_RUN, NO_CREDENTIAL_REPLAY, GATEWAY_1006_EMBEDDED_FALLBACK
redactions_applied: 不记录或回显 Token、session_data、session revision、凭据文件名、完整 Flow/ResultSet/Resource ID；只保留计数、模式、状态、HTTP 类别和 Flow hash
proves: 明确授权 direct import 能通过唯一 save 通道最小落盘且不回显；education-resources fresh SmartEdu 路径实际发出认证请求并诚实保留 HTTP 403/零候选
does_not_prove: stored/no_probe 不证明远端接受；本次未证明有效登录、Inspect、fresh Resolution/Eligibility、Plan/Job、Provider 成功、Asset、Archive 或 production readiness
```

Step E 继续标为 `blocked`：本地凭据已形成，但 fresh 真实 Search 的认证 HTTP 403 证明远端未接受当前
会话。不得自动重放、变换或要求用户重发该值；恢复条件是受控浏览器形成新的合法会话，或用户对新的
canonical 值再次给出平台/用途/保存授权。新会话仍须重新 Search/Inspect，以新的 concrete primary、
Resolution 和 Eligibility 证明实际生效，再重新 Prepare、展示新 Plan 并取得独立确认，才允许 Start。
Douyin 的 exact acquisition 仍 policy blocked，不得作为替代，也不得切换 generic 或 `web_capture`。
离线 AUTH fixture 不能证明真实会话或平台接受。

第一条合法无认证成功候选路径固定为：`generic` 公共图文文章的 Search → optional Inspect → Present；
该只读路径已由 EV-0028-20260811-06 通过，且没有选择、prepare、下载或归档。下一步必须先由用户从
当前 Presentation 的 2 个公开候选中明确选择；Selection/Prepare 只生成权威计划，展示该计划后仍需一次
独立的明确确认，才允许 Start 网络副作用。

### EV-0028-20260811-01 — generic 文章探索失败基线

```text
evidence_id: EV-0028-20260811-01
evidence_level: real_openclaw (embedded fallback) + real_platform (generic Search/Inspect)
observed_at_utc: 2026-08-10T19:29:30Z..2026-08-10T19:32:30Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 家长为孩子找“为什么会有四季”的中文图文科普，比较 3 个公开来源；明确禁止下载、保存本地、归档和代选
loaded_skill_and_mcp_digest: Skill eb4016b...798a; live list_tools 9565ee6e...4680
tool_sequence: read Skill/reference x3 -> FlowStart x1 -> Search x7 -> FlowStatus x1 -> Inspect x1 -> built-in web_search x1 -> built-in web_fetch x17
platform_observations: generic Search 真实成功；当前 ResultSet 20 candidates、coverage=partial/inspection；一次 generic Inspect resolved/available/landing_page
human_confirmation: not_reached
side_effects: state_only; no acquisition or archive
asset_archive_summary: no Presentation, Selection, Plan, Job, Asset or Archive
reason_codes: GATEWAY_UNAVAILABLE_EMBEDDED_FALLBACK, TASK_VERSION_CONFLICT, MCP_TOOL_SURFACE_BYPASS, AGENT_TURN_TIMEOUT, PRESENTATION_NOT_SAVED
redactions_applied: session/run/Flow/ResultSet/Resource/Resolution IDs 只保留 hash；URL、标题、Tool 原文和模型思考未入库
proves: OpenClaw embedded Agent 实际加载 Skill 和 MCP；generic 真实 Search 与单项 Inspect 可到达；副作用门禁未被越过
does_not_prove: Gateway 路径、候选正确展示、Presentation、用户选择、获取、归档、恢复或 production readiness
```

持久状态复核：Flow hash `da04a433645f` 保持 `stage=reviewing`、`task_version=1`；当前 ResultSet hash
`0ef656fc90d3`、`result_version=6`、20 个 generic candidates，且 Presentation/Selection/Plan/Job 均为空。
该回合失败不是超时参数不足：Agent 在 180 秒内重复 `replace` 搜索并离开 MCP 封闭工具面；不得通过增加
timeout 掩盖。下一次真实回合前先收紧 Skill 的工具面、task version、replace/extend 和停止预算。

### EV-0028-20260811-02 — Gateway 文章探索 partial

```text
evidence_id: EV-0028-20260811-02
evidence_level: real_openclaw (Gateway) + real_platform (multi-platform Search)
observed_at_utc: 2026-08-10T19:41:51Z..2026-08-10T19:44:36Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 与 EV-0028-20260811-01 完全相同
loaded_skill_and_mcp_digest: Skill 1885b389...5916; live list_tools 9565ee6e...4680
tool_sequence: read x6 -> FlowStart x1 -> Search x1 -> resources_list x1 -> prompts_list x1 -> exec x10 -> Search x5 -> PresentationSave x1
platform_observations: Gateway RPC 实际通过；generic/kepu 等真实 Search；最终只形成一个来源族的 4 个 search-only 候选并向用户准确说明跨来源 Gap
human_confirmation: not_reached
side_effects: state_only; Presentation 4 items; no acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: BROKEN_LAUNCHAGENT_PATH, FOREGROUND_GATEWAY_USED, MCP_PROTOCOL_PSEUDO_TOOL_BYPASS, EXEC_TOOL_BYPASS, SECOND_REPLACE, SEARCH_ROUND_BUDGET_EXCEEDED
redactions_applied: session/run/Flow/ResultSet/Presentation IDs 只保留 hash；URL、标题、Tool 原文、exec 命令和模型思考未入库
proves: 当前 Gateway 二进制可运行；默认 Agent 可完成 Flow -> Search -> Present 并保存与用户列表一致的 4 项 Presentation；失败与认证限制能诚实解释；副作用门禁未越过
does_not_prove: Skill 封闭工具面和三轮预算、LaunchAgent 服务、Inspect、用户选择、获取、归档、恢复或 production readiness
```

持久状态复核：Flow hash `0c3fba4a4e5f` 为 `stage=presented`、`task_version=1`；当前 ResultSet hash
`90b54214a382`、`result_version=5`、`mode=extend`、`round=4`、20 candidates；Presentation hash
`30b8f6c62e7e` 含 4 项，Selection/Plan/Job 均为空。用户可见结果按 search-only 证据解释，未虚构 Inspect。

本轮不能判通过：`web_search/web_fetch` 已降为零，但 Agent 为寻找 Registry/结果旁路调用了 `exec` 和 MCP
protocol resources/prompts；根因是 `source-routing.md` 仍要求运行时读取机器 Registry/Descriptor，且默认
20 个候选使 Tool 结果发生截断。下一轮前移除这项冲突，明确禁止 protocol pseudo-tools，并把常规比较
Search `limit` 收紧到 8；不修改全局或 `main` tool policy。

### EV-0028-20260811-03 — Gateway 行为门禁通过、候选语义失败

```text
evidence_id: EV-0028-20260811-03
evidence_level: real_openclaw (Gateway) + real_platform (generic/zhihu/bilibili Search)
observed_at_utc: 2026-08-10T19:48:22Z..2026-08-10T19:49:35Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 与 EV-0028-20260811-01 完全相同
loaded_skill_and_mcp_digest: Skill 58d30880...f02d; live list_tools 9565ee6e...4680
tool_sequence: read x3 -> FlowStart x1 -> Search x3 -> StopWithGap
platform_observations: 第 1/2 轮 generic 各提交 4 条完整多字中文 query；第 3 轮 zhihu 2 条均 AUTH_REQUIRED，bilibili 1 条原生 Search succeeded；三轮均 limit=8
human_confirmation: not_reached
side_effects: state_only; no Presentation, acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: CLOSED_TOOL_SURFACE_PASS, SEARCH_ROUND_BUDGET_PASS, STOP_WITH_GAP_PASS, SEMANTIC_RELEVANCE_FAILED, BING_CJK_RECALL_FAILED, EXTEND_CAPACITY_EXHAUSTED, AUTH_REQUIRED
redactions_applied: session/run/Flow/ResultSet IDs 只保留 hash；query 只记录数量与完整多字事实；URL、标题、Tool 原文和模型思考未入库
proves: 默认 Agent 在真实 Gateway 中遵守专用工具面、task_version、一次 replace + 两次 extend、三轮硬预算和无候选时 StopWithGap；未越过副作用门禁
does_not_prove: 相关候选、Inspect、Presentation、用户选择、获取、归档、恢复或任一平台 production readiness
```

持久状态复核：Flow hash `1faa51b84fae` 为 `stage=reviewing`、`task_version=1`；当前 ResultSet hash
`580ec1841e06`、`result_version=3`、`mode=extend`、`round=3`、8 个 generic candidates；
Presentation/Selection/Plan/Job 均为空，允许的下一步仍只有只读 Search/Inspect/Presentation/Library
类动作。Agent 最终如实说明没有 3 个可比较来源，未拿无关结果凑数，也未替用户选择。

根 Agent 对 session payload 与公开搜索响应做了脱敏诊断：三轮 `search_tasks` 与服务端
`platform_runs.query_runs.query` 都保留完整多字中文，Bing HTML 也回显完整 query，因此“拆成单字”
只是 Agent 对低相关结果的错误归因，不是 MCP 字符切分。当前默认 Bing 对该组中文 query 返回 8 个
零主题命中的结果；同一现有 Adapter 的 DuckDuckGo/Baidu 只读诊断能返回主题相关候选，但直接
Adapter 诊断不计作真实 Agent 成功证据。

另一个已证实问题是 `limit` 的冻结语义为新 ResultSet **总容量**：首轮已经有 8 项后，后续
`extend limit=8` 以 base-first 合并会把全部 incoming generic/Bilibili 候选截掉。因此 Bilibili 原生
Search 虽成功，当前 ResultSet 仍只含首轮 generic 候选；这不是 Bilibili → generic fallback。

本证据把 Agent 行为门禁判为通过，但 Step C 仍为 `in_progress`：尚未得到可语义展示的合法无认证
成功路径。下一轮只能在既有 exact route 内修正 CJK 搜索引擎选择与 extend 总容量用法，补充定向
回归、重新部署并生成新 digest 后，再重跑同一自然语言回合；不得把直接 Adapter 诊断改写为通过。

### EV-0028-20260811-04 — 相关性与状态恢复通过、公开来源数量 partial

```text
evidence_id: EV-0028-20260811-04
evidence_level: real_openclaw (Gateway) + real_platform (generic Search/Inspect/Present)
observed_at_utc: 2026-08-10T20:08:25Z..2026-08-10T20:10:18Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 与 EV-0028-20260811-01 完全相同
loaded_skill_and_mcp_digest: Skill 3aa0e594...3b1d; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read x3 -> FlowStart -> Search replace(8) -> Search extend(16) -> Inspect x3 -> PresentationSave failed(stale IDs) -> FlowStatus -> Inspect x2 -> PresentationSave success
platform_observations: CJK generic exact route 返回相关候选；当前 ResultSet 16 项、round=2、new_unique=8、new_displayable=8；2 个已展示来源 Inspect=resolved/available，1 个 Inspect=unresolved/AUTH_REQUIRED
human_confirmation: not_reached
side_effects: state_only; final Presentation 3 items; no acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: CLOSED_TOOL_SURFACE_PASS, EXTEND_TOTAL_CAPACITY_PASS, SEMANTIC_RELEVANCE_PASS, STALE_RESULTSET_IDS_RECOVERED, PRESENTATION_SAVE_PASS, PUBLIC_SOURCE_COUNT_FAILED, AUTH_REQUIRED
redactions_applied: session/run/Flow/ResultSet/Resource/Resolution/Presentation IDs 只保留 hash；URL、标题、Tool 原文和模型思考未入库
proves: 默认 Agent 可在真实 Gateway 中用相关 CJK 候选完成两轮有界 Search、串行 Inspect、结构化失败恢复和最终 Presentation 绑定；副作用门禁未越过
does_not_prove: 3 个当前无需登录且可直接阅读的公开来源、用户选择、获取、归档、恢复或 production readiness
```

持久状态复核：Flow hash `a9ffc99c21e9` 为 `stage=presented`、`task_version=1`；当前 ResultSet hash
`a43b0dacf031`、`result_version=2`、`mode=extend`、`round=2`、16 candidates；当前 Presentation hash
`dd2c38378dcc` 精确含最终展示的 3 项，Selection/Plan/Job 均为空。首次 PresentationSave 使用旧 ResultSet
资源 ID，服务端以 `RESOURCE_NOT_FOUND` 拒绝；Agent 随后读取 FlowStatus、使用当前 ID 重新 Inspect 并成功
保存最终列表，证明了只读控制面恢复，而不是绕过绑定。

本回合仍不能关闭 Step C：最终第三项的 Resolution 明确为 `AUTH_REQUIRED`，因此不满足用户“公开来源”
这一显式 must constraint，不能作为第三个无需认证成功候选。已把该边界收紧到当前 Skill：计入用户要求的
N 个公开来源前必须 Inspect 且 availability=available；受限候选只作 Gap 说明。第五轮应在剩余第 3 轮和
总容量 20 内继续找第三个公开可访问来源，或准确以 2 项 + StopWithGap 结束。

### EV-0028-20260811-05 — 重复读取循环，由根 Agent 有界中止

```text
evidence_id: EV-0028-20260811-05
evidence_level: real_openclaw (Gateway); no real_platform business call reached
observed_at_utc: 2026-08-10T20:13:35Z..2026-08-10T20:15:20Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 与 EV-0028-20260811-01 完全相同
loaded_skill_and_mcp_digest: loaded SKILL.md 5dc72f8c...9aa0; live list_tools unchanged
tool_sequence: read same SKILL.md path without offset x40 -> root bounded abort
platform_observations: FlowStart 与全部 13 个业务 Tool 均未到达；没有创建 Flow 或接触平台网络
human_confirmation: not_reached
side_effects: none
asset_archive_summary: no Flow, ResultSet, Presentation, Selection, Plan, Job, Asset or Archive
reason_codes: REPEATED_READ_LOOP, NO_FLOW_CREATED, ROOT_ABORTED_BOUNDED_RUN, NO_SIDE_EFFECTS
redactions_applied: session/run IDs、Tool 原文和模型思考未入库；只保留重复路径类型和次数
proves: 根 Agent 的有界监控能识别并中止无进展 Agent 循环，且循环没有越过业务或副作用边界
does_not_prove: Search、Inspect、Present、平台可用性、获取、归档、恢复或 production readiness
```

该回合不是平台或 MCP 失败。根 Agent 只在唯一 Skill 增加“同一文件、同一路径和 offset 的成功读取不得
重复”约束，没有放宽全局工具策略、增加 timeout 或自动重试。随后重新同步 Skill 并重跑相同自然语言目标。

### EV-0028-20260811-06 — 合法无认证只读路径通过，2 项 + 诚实 Gap

```text
evidence_id: EV-0028-20260811-06
evidence_level: real_openclaw (Gateway) + real_platform (generic Search/Inspect/Present)
observed_at_utc: 2026-08-10T20:15:50Z..2026-08-10T20:17:43Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 与 EV-0028-20260811-01 完全相同
loaded_skill_and_mcp_digest: loaded SKILL.md 62841311...7c11; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read Skill/reference x2 -> FlowStart -> Search replace(8) -> Search extend(16) -> Search extend(20) -> Inspect x3 -> PresentationSave x1 -> StopWithGap
platform_observations: 三轮 generic Search 均成功并各使用一条完整 query；最终 ResultSet 20 项、round=3、new_unique=9、duplicate=8、new_displayable=4；2 项 Inspect=resolved/available，1 项 Inspect=unresolved/AUTH_REQUIRED；最终 Presentation 只含 2 个公开项
human_confirmation: not_reached
side_effects: state_only; no selection, acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: REPEATED_READ_GUARD_PASS, CLOSED_TOOL_SURFACE_PASS, SEARCH_ROUND_BUDGET_PASS, PUBLIC_READ_ONLY_PATH_PASS, HONEST_STOP_WITH_GAP_PASS, AUTH_REQUIRED
redactions_applied: session/run/Flow/ResultSet/Resource/Resolution/Presentation IDs 只保留 hash；URL、标题、query、Tool 原文和模型思考未入库
proves: 默认 Agent 可在真实 Gateway 中用合法公开来源完成有界 Search、可访问性 Inspect、2 项 Presentation 与真实 Gap 说明；没有拿登录受限项凑数或越过副作用门禁
does_not_prove: 用户选择、Prepare/Confirm/Start、资产获取、归档、恢复或任一平台 production readiness
```

持久状态复核：Flow hash `2c36902119cd` 为 `stage=presented`、`task_version=1`；当前 ResultSet hash
`18ba84247b7a`、`result_version=3`、`mode=extend`、`round=3`、20 candidates，最终 provenance 为
`new_unique=9`、`duplicate=8`、`new_displayable=4`；当前 Presentation hash `14b49b711ee9` 精确含 2 项，
3 个 Resolution 中 2 个 available、1 个 AUTH_REQUIRED，Selection/Plan/Job 均为空。服务端仍只允许只读动作
和 `resource_selection_save`，因此当前没有隐式下载或可重放副作用。

Step C 现标 `completed`：它要求的是第一条合法无认证只读路径，不要求用受限来源伪造用户要求的数量。
EV-0028-20260811-06 已按前一证据预设的“第三轮继续补，若仍不足则 2 项 + StopWithGap”完成；用户原始
“3 个公开来源”目标仍准确记录为 partial。Step D 转为 `in_progress`，并停在必须由用户明确选择资源的闸门。

## Milestone checkpoint（C）

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no; total-capacity semantics and retained counts are explicit
Unrelated files changed?: no
Actual user flow affected?: read-only Search -> Inspect -> Present only
Actual user flow validated?: yes; legal unauthenticated generic path, with honest partial gap
Scope drift detected?: no
```

### 2026-08-11 当前回归快照

- 仓库外 `0.2.0-9e17ea8c` runtime verifier 的既有结果保持通过；在该 runtime 的 `venv/bin/python`
  上重跑全量 unittest，新增四条公共 stdio 门禁后由 `489/489` 增至 `493/493`，全部通过。Step F
  定向组合为 `83/83`，新增 `test_e2e_stdio_scenarios` 模块为 `6/6`。
- 独立 stdio E2E、隔离 pycache 的 `compileall`、28 个 contracts JSON 解析、76 个非隐藏 Markdown
  文件的 129 个本地链接（含隐藏计划共 118 个文件、186 个链接）和仓库根 `git diff --check` 全部通过。
  全量测试仍有一个既有测试路径触发
  未关闭 SQLite 的 `ResourceWarning`，没有测试失败；该 warning 只记录为后续清理项，不改写通过结果。
- 本轮验收用前台 Gateway 已收到 SIGINT 并干净退出，`127.0.0.1:18789` 无监听。LaunchAgent 仍处于
  “loaded but stopped”，其命令指向缺失的旧 npm-global 安装且 PATH 非标准；本计划没有安装、repair 或
  覆盖用户级服务配置。
- 以上是 Step C/D 交界处的中间回归，不替代所有真实副作用、恢复场景完成后的 Step H 最终回归。

### EV-0028-20260811-07 — 混合检索未进入业务 Tool，Gateway 模型调用与 CLI fallback 双重失控

```text
evidence_id: EV-0028-20260811-07
evidence_level: real_openclaw (Gateway failure + automatic embedded fallback); no real_platform call reached
observed_at_utc: attempt A 2026-08-10T20:31:33Z..20:45:28Z; attempt B 2026-08-10T23:48:05Z..23:59:23Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 同主题比较一篇公开图文科普、一段公开视频和一份可打印练习/PDF；只读，不选择、不获取、不归档
loaded_skill_and_mcp_digest: loaded SKILL.md 62841311...7c11; live list_tools unchanged
tool_sequence: attempt A Gateway first model call stalled 789s with no Tool -> CLI auto embedded fallback -> same SKILL.md read x16 -> root abort; provider smoke returned OK in 2.2s; attempt B Gateway read Skill/reference x5 distinct -> next model call stalled 646s -> CLI auto embedded fallback -> same SKILL.md read x10 -> root abort
platform_observations: no FlowStart or business Tool; no platform request and no persisted product state
human_confirmation: not_reached
side_effects: none
asset_archive_summary: no Flow, ResultSet, Resolution, Presentation, Selection, Plan, Job, Asset or Archive
reason_codes: MODEL_STREAM_STALL, TIMEOUT_NOT_ENFORCED_ON_TIME, UNCONDITIONAL_EMBEDDED_FALLBACK, FALLBACK_REPEATED_READ_LOOP, NO_BUSINESS_TOOL, ROOT_ABORTED_BOUNDED_RUN, NO_SIDE_EFFECTS
redactions_applied: run/session IDs、系统 prompt、Tool 原文和模型思考未入库；只保留时长、Tool 类型与次数
proves: 当前 OpenClaw CLI 的 Gateway timeout 会无条件转 embedded，且 provider stream stall 会使声明的 180/240 秒 server timeout 分别延迟到约 646/789 秒；根 Agent 中止后没有副作用
does_not_prove: 混合检索、任何平台 Search/Inspect、Presentation、获取、归档、恢复或 production readiness
```

根 Agent 检查了当前安装的 OpenClaw `2026.7.1-2` 运行代码：`openclaw agent` 对任何
`GatewayTransportError`/Gateway timeout 都直接执行 embedded fallback，没有 CLI 或配置禁用开关。本计划未修改
OpenClaw 安装、全局 tool policy、模型或 timeout。后续真实回合改用同一 Gateway 的底层 `agent` +
`agent.wait` + `chat.abort` RPC，由根 Agent 控制等待与中止；这不改变默认 Agent 或业务 Tool，只消除 CLI
自动 fallback 对证据级别的污染。混合检索场景仍未通过，后续需在受控 RPC 下重跑。

### EV-0028-20260811-08 — Bilibili 视频 Search partial，中断后同 Session 恢复并 StopWithGap

```text
evidence_id: EV-0028-20260811-08
evidence_level: real_openclaw (Gateway direct RPC) + real_platform (Bilibili/Douyin Search, Bilibili Inspect)
observed_at_utc: initial 2026-08-11T00:27:17Z..00:33:39Z; recovery 2026-08-11T00:35:11Z..00:36:00Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 为孩子找一个解释四季成因的中文公开视频；必须无需登录且证实为可观看视频本体；只读，不选择、不获取、不归档
loaded_skill_and_mcp_digest: loaded SKILL.md 62841311...7c11; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read Skill -> FlowStart -> Search replace(8; bilibili + douyin) -> model timeout -> same session follow-up -> FlowStatus -> Inspect x2 -> StopWithGap
platform_observations: Bilibili Search succeeded，当前 ResultSet 8 个 video candidates；Douyin Search=AUTH_REQUIRED；两个 Bilibili Inspect 均 resolution=resolved、landing webpage=available/materializable，但 video representation technical_availability=unknown、materializable=false
human_confirmation: not_reached
side_effects: state_only; no presentation, selection, acquisition or archive
asset_archive_summary: no Presentation, Selection, Plan, Job, Asset or Archive
reason_codes: BILIBILI_SEARCH_PASS, DOUYIN_AUTH_REQUIRED, MODEL_CALL_TIMEOUT, FLOW_RECOVERY_PASS, BILIBILI_LANDING_AVAILABLE, VIDEO_REPRESENTATION_UNKNOWN, NO_PRIMARY_VIDEO, STOP_WITH_GAP_PASS, NO_SIDE_EFFECTS
redactions_applied: run/session/Flow/ResultSet/Resource/Resolution IDs 只保留 hash；URL、标题、query、Tool 原文和模型思考未入库
proves: 默认 Agent 可在真实 Gateway 的后续交互中从服务端 Flow/ResultSet 恢复，串行 Inspect 并区分公开 landing 与未证实的视频本体；没有把 landing、截图或登录受限平台伪装成公开视频
does_not_prove: 无需登录的实际视频播放、concrete primary、视频获取/归档、Douyin 合法会话恢复或任一平台 production readiness
```

持久状态复核：Flow hash `951b57b4b125` 保持 `stage=reviewing`、`task_version=1`；ResultSet hash
`fa3b0deaba5a` 为 `result_version=1`、`mode=replace`、`round=1`、8 个 Bilibili video candidates，
provenance 为 `new_unique=8`、`duplicate=0`、`new_displayable=8`；2 个 Resolution 均只证明 landing
available，Presentation/Selection/Plan/Job 均为空。初始 run 的模型 timeout 没有自动重放；同一 session 的
明确后续交互先读 FlowStatus 再 Inspect，证明控制面恢复而非网络副作用重放。

Step D 的视频**失败/恢复路径**现有真实证据，但视频成功路径仍未完成；Bilibili exact acquisition route 继续按
0027 为 policy/dependency blocked，Douyin 继续为 AUTH_REQUIRED，不得用 generic 或 `web_capture` 代替。

### EV-0028-20260811-09 — Ximalaya 音频事实可达，Agent 命名空间、AUTH 文案与快照绑定失败

```text
evidence_id: EV-0028-20260811-09
evidence_level: real_openclaw (Gateway direct RPC) + real_platform (Ximalaya/generic Search and Inspect)
observed_at_utc: 2026-08-11T00:38:36Z..00:40:34Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 为孩子找一段讲清四季成因的中文音频；必须无需登录且证实有可播放音频本体；只读，不选择、不获取、不归档
loaded_skill_and_mcp_digest: pre-fix Skill tree 9496c38a...abdd; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read SKILL.md x2 + source-routing -> FlowStart -> Search replace(8; ximalaya + invented qingting) -> Inspect x4 -> Search extend(16; generic) -> Inspect x2 -> StopWithGap
platform_observations: Ximalaya Search succeeded；未注册 qingting 返回 PLATFORM_UNAVAILABLE；4 个旧 v1 Ximalaya Resolution 仅证明 landing available、audio representation unknown/materializable=false；extend 后当前 v2 只保留 2 个 generic Resolution
human_confirmation: not_reached
side_effects: state_only; no presentation, selection, acquisition or archive
asset_archive_summary: no Presentation, Selection, Plan, Job, Asset or Archive
reason_codes: XIMALAYA_SEARCH_PASS, XIMALAYA_INSPECT_PASS, INVENTED_PLATFORM_ID, DUPLICATE_SKILL_READ, LANDING_AVAILABLE, AUDIO_REPRESENTATION_UNKNOWN, UNSUPPORTED_AUTH_REQUIRED_CLAIM, STALE_RESOLUTION_CITED_AFTER_EXTEND, STOP_WITH_GAP_PARTIAL, NO_SIDE_EFFECTS
redactions_applied: run/session/Flow/ResultSet/Resource/Resolution IDs 只保留 hash；URL、标题、query、Tool 原文和模型思考未入库
proves: Ximalaya real Search/Inspect 可到达，且当前检查器只能证明 landing page，不足以证明音频本体；副作用门禁未越过
does_not_prove: 登录墙、无需登录播放、concrete primary audio、合法音频获取/归档、状态绑定正确或 production readiness
```

持久状态复核：Flow hash `7f1755b0a631` 为 `stage=reviewing`、`task_version=1`；当前 ResultSet hash
`b00f38d727a0` 为 `result_version=2`、`round=2`、16 candidates，平台为 generic + Ximalaya；当前
Resolution 仅 2 个 generic 项，4 个 Ximalaya Resolution 已随 extend 成为历史绑定，Presentation/Selection/
Plan/Job 均为空。Agent 正确识别音频本体 unknown，却无 Tool 证据地断言网页端播放需要登录，并继续引用
旧 ResultSet 的 Resolution；该回合不能判为用户文案或状态绑定通过。

根 Agent 据此收紧 Skill：冻结 16 个 native platform ID，未注册来源只能作为 `generic` query 线索；
`AUTH_REQUIRED` 只能由当前 Tool 事实得出；每次成功 extend 后，旧 Resolution 不再是当前 Presentation/
Selection 的证据，必要候选必须按当前 public resource ID 重新 Inspect。

### EV-0028-20260811-10 — 音频语义错误持久化后，同 Session 从权威状态纠正为空 Presentation

```text
evidence_id: EV-0028-20260811-10
evidence_level: real_openclaw (Gateway direct RPC) + real_platform (Ximalaya/generic Search, Inspect, Flow recovery)
observed_at_utc: initial 2026-08-11T00:46:22Z..00:48:22Z; recovery 2026-08-11T00:49:54Z..00:50:32Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 与 EV-0028-20260811-09 相同；恢复交互限定先读 FlowStatus、不再 Search、最多 Inspect 两个当前 ID，不满足音频本体证据时把 Presentation 置空
loaded_skill_and_mcp_digest: Skill tree 0fc1ef3b...f60; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read Skill/reference x3 distinct -> FlowStart -> Search replace(8; ximalaya + generic) -> Inspect x4(v1) -> Search extend(16) -> Search extend(20) -> PresentationSave 8 items with no current Resolution -> provider timeout -> same session follow-up -> FlowStatus -> Inspect x2(current v3 IDs) -> PresentationSave empty -> StopWithGap
platform_observations: native namespace、8->16->20 budget 与无重复 read 通过；初始 run 仍把 8 个无当前 Resolution 的 Ximalaya 候选保存为语义不合格 Presentation；恢复 run 核验两个当前 ID，均为 landing available + audio unknown/materializable=false，且没有 AUTH_REQUIRED
human_confirmation: not_reached
side_effects: state_only; Presentation corrected from 8 items to empty; no selection, acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: CLOSED_PLATFORM_NAMESPACE_PASS, REPEATED_READ_GUARD_PASS, SEARCH_ROUND_BUDGET_PASS, CURRENT_RESOLUTION_BINDING_FAILED, INVALID_PRESENTATION_SAVED, MODEL_CALL_TIMEOUT, FLOW_RECOVERY_PASS, CURRENT_REINSPECT_PASS, PRESENTATION_CORRECTED_EMPTY, AUDIO_REPRESENTATION_UNKNOWN, AUTH_REQUIRED_NOT_OBSERVED, NO_SIDE_EFFECTS
redactions_applied: run/session/Flow/ResultSet/Resource/Resolution/Presentation IDs 只保留 hash；URL、标题、query、Tool 原文和模型思考未入库
proves: 同一默认 Agent session 可从服务端恢复当前 ResultSet，按当前 ID 重新 Inspect，并用新 Presentation 纠正已持久化的语义错误；未知本体未被保留为可选音频，且没有自动重放 Search 或副作用
does_not_prove: 可播放或无需登录的 audio primary、登录恢复、音频 acquisition/archive、初始回合一次闭合成功或 production readiness
```

根 Agent 通过独立真实 stdio `resource_flow_status` 复核：Flow hash `067b56afc41c` 为
`stage=presented`、`task_version=1`；当前 ResultSet hash `f27c42e4a09c` 为 `result_version=3`、
`round=3`、20 candidates；当前 Resolution 为 2 个；当前 Presentation hash `5151fb72e31d`、
`presented_version=2`、`empty=true`，Selection/Plan/Job 均为空。Gateway `agent.wait` 对恢复 run 返回
`status=ok`、`stopReason=stop`，不是根线程仅凭 session 尾部推断完成。

因此音频**真实失败/状态恢复路径**已有证据，音频成功路径仍未完成。当前 Ximalaya 事实是 Search/Inspect
可达、landing 可访问、audio representation 尚未证实；没有 `AUTH_REQUIRED` 当前观测，不能把登录流程
描述为已证明的恢复条件，Acquisition 仍按 0027 的 exact route policy/dependency 阻断。

### EV-0028-20260811-11 — 图书版本/正文核验失败，未展示 Presentation 由同 Session 清空

```text
evidence_id: EV-0028-20260811-11
evidence_level: real_openclaw (Gateway direct RPC) + real_platform (generic/NLC/Wechat/Anna/BaiduWenku Search and Inspect)
observed_at_utc: initial 2026-08-11T00:58:01Z..01:01:03Z; recovery 2026-08-11T01:01:36Z..01:02:06Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 比较《小王子》中文译本的译者、出版社、出版年份，并核验是否有公开可读正文；只读，不选择、不获取、不归档
loaded_skill_and_mcp_digest: initial Skill tree a6e8886f...3c03; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read Skill/reference x5 distinct -> FlowStart -> Search replace(8) -> Search extend(16) -> Inspect x4 -> Search extend(20) -> Inspect x6(current v3 IDs) -> PresentationSave 20 items before actual display -> provider timeout -> same session recovery -> FlowStatus -> PresentationSave empty failed(INVALID_ARGUMENT key) -> PresentationSave empty success -> StopWithGap
platform_observations: generic book/reading pages和豆瓣详情页可搜索，当前 Inspect 只证明 landing/作者，未提取译者/出版社/年份；NLC Search 有候选但两次 Inspect=PLATFORM_UNAVAILABLE；Wechat Search 有二手译本线索但 Inspect=FEATURE_NOT_SUPPORTED；Anna Search 有原始命中但没有 retained candidate；BaiduWenku Search=HTTP 403；九九藏书候选 Inspect=AUTH_REQUIRED，其余阅读页只证明 landing 或正文 unknown
human_confirmation: not_reached
side_effects: state_only; invalid 20-item Presentation corrected to empty; no selection, acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: SEARCH_ROUND_BUDGET_PASS, CURRENT_REINSPECT_PASS, VERSION_FIELDS_UNVERIFIED, BOOK_METADATA_ONLY, PRIMARY_DOCUMENT_NOT_PROVEN, NLC_PLATFORM_UNAVAILABLE, WECHAT_INSPECT_UNSUPPORTED, BAIDUWENKU_HTTP_403, ANNA_NO_RETAINED_CANDIDATE, AUTH_REQUIRED_CANDIDATE, PRESENTATION_SAVED_BEFORE_ACTUAL_DISPLAY, MUST_CONSTRAINT_ITEMS_INCLUDED, OVERBROAD_RESULTSET_PRESENTATION, MODEL_CALL_TIMEOUT, FLOW_RECOVERY_PASS, PRESENTATION_CORRECTED_EMPTY, NO_SIDE_EFFECTS
redactions_applied: run/session/Flow/ResultSet/Resource/Resolution/Presentation IDs 只保留 hash；URL、标题细节、query、Tool 原文和模型思考未入库
proves: 默认 Agent 能区分 landing/metadata、正文 unknown、AUTH_REQUIRED 与平台核验失败，并在后续交互从权威 Flow 清除未实际展示的 Presentation；副作用门禁未越过
does_not_prove: 译者/出版社/年份的权威版本核验、公开可读正文、图书 acquisition/archive、初始回合一次闭合成功或 production readiness
```

初始 run 的三个 Search 正确执行 `replace(8) -> extend(16) -> extend(20)`，最终 Inspect 使用当前 v3
public IDs；但 Agent 把全部 20 项 ResultSet（含 `AUTH_REQUIRED`、正文 unknown、高度重复和版本核心字段未
核验项）在**实际用户可见列表输出前**保存为 Presentation，随后 provider timeout。该列表既未实际展示，
也不满足用户 must constraint，不能因为服务端接受绑定就算产品语义通过。

同一 session 的明确恢复交互先读 FlowStatus，再把 Presentation 纠正为空并 StopWithGap；首个空保存因
`idempotency_key` 不合规被服务端以 `INVALID_ARGUMENT` 拒绝，Agent 使用新合规 key 后成功。根 Agent
通过独立真实 stdio `resource_flow_status` 复核：Flow hash `0fcbda487455`、当前 ResultSet hash
`1e30df005c9a`、`result_version=3`、`round=3`、20 candidates、6 个当前 Resolution；Presentation hash
`5852f4890268`、`presented_version=2`、`empty=true`，Selection/Plan/Job 均为空。

图书/版本**真实失败/恢复路径**现有证据，但成功比较路径仍未完成。当前事实不足以给出一个已核验
译者/出版社/年份且有公开正文的版本；Anna acquisition 继续 policy blocked，NLC/Wechat/BaiduWenku
失败不转 generic 或其他 Provider。根 Agent 已把“完整用户列表必须先于 PresentationSave”与“受限、
未满足 must、高度重复项不得默认保存整个 ResultSet”加入当前 Skill，需由后续真实回合重新验收。

### EV-0028-20260811-12 — 课程组合缺口诚实停止，编号 Gap 与 Presentation 状态由同 Session 对齐

```text
evidence_id: EV-0028-20260811-12
evidence_level: real_openclaw (Gateway direct RPC) + real_platform (SmartEdu/Bilibili/generic Search and Inspect)
observed_at_utc: initial 2026-08-11T01:05:20Z..01:07:57Z; recovery 2026-08-11T01:08:34Z..01:08:51Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 为小学高年级找基础电路中文公开课程；同一课程必须核验视频讲解与可打印 PDF/讲义；只读且禁止跨资源拼装
loaded_skill_and_mcp_digest: initial Skill tree 4e3f2c63...65fb; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read Skill/reference x4 distinct -> FlowStart -> Search replace(8) -> Search extend(16) -> Search extend(20) -> Inspect x4(current v3 IDs) -> StopWithGap with five numbered restricted facts but no PresentationSave -> same session recovery -> FlowStatus -> PresentationSave empty failed(INVALID_ARGUMENT key) -> PresentationSave empty success -> corrected StopWithGap
platform_observations: SmartEdu Search retained 8 relevant course pages；两个 Inspect 仅证明 landing available、视频/PDF本体未证实，一个精品课 Inspect=AUTH_REQUIRED；Bilibili Search retained 8 videos but大多偏题，最高潜候选 Inspect 仅证明 landing available、video representation unknown、无 PDF 线索；generic 最终 4 项均偏题；没有同一 resource 的 video + document relationship
human_confirmation: not_reached
side_effects: state_only; empty Presentation; no selection, acquisition or archive
asset_archive_summary: no Selection, Plan, Job, Asset or Archive
reason_codes: SEARCH_ROUND_BUDGET_PASS, SEMANTIC_RELEVANCE_FILTER_PASS, CURRENT_REINSPECT_PASS, SMARTEDU_SEARCH_PASS, BILIBILI_SEARCH_PASS, LANDING_AVAILABLE, AUTH_REQUIRED_CANDIDATE, VIDEO_REPRESENTATION_UNKNOWN, DOCUMENT_REPRESENTATION_UNPROVEN, CROSS_RESOURCE_BUNDLE_NOT_FABRICATED, COURSE_BUNDLE_GAP, NUMBERED_GAP_WITHOUT_PRESENTATION, FLOW_RECOVERY_PASS, PRESENTATION_CORRECTED_EMPTY, INVALID_IDEMPOTENCY_KEY_RECOVERED, NO_SIDE_EFFECTS
redactions_applied: run/session/Flow/ResultSet/Resource/Resolution/Presentation IDs 只保留 hash；URL、标题细节、query、Tool 原文和模型思考未入库
proves: 默认 Agent 能在真实平台事实下拒绝把不同资源拼成课程 Bundle，并诚实区分课程 landing、视频本体 unknown、PDF 缺失和 AUTH_REQUIRED；后续交互可将不可选 Gap 与空 Presentation 对齐
does_not_prove: 同一课程的 video+PDF representations、真实 AssetBundle、SmartEdu/Bilibili acquisition/archive、初始回合 Presentation 一次一致或 production readiness
```

初始 run 在 3 轮 Search 与 4 次当前 ID Inspect 后正确作出 StopWithGap，没有调用 Selection/Prepare/
Start；但用户可见回复把 5 组受限事实写成编号候选且没有保存 Presentation，违反当前“受限 Gap 在
编号可选列表之外”的展示边界。恢复 run 先读 FlowStatus，确认 `current_presentation=null`，随后保存空
Presentation；首个 key 含不可接受的截断/非 ASCII 字符，被服务端 `INVALID_ARGUMENT` 拒绝，使用新的
ASCII key 后成功。

根 Agent 通过独立真实 stdio `resource_flow_status` 复核：Flow hash `404356b4e2de`、当前 ResultSet hash
`40f7b3fc6a96`、`result_version=3`、`round=3`、20 candidates、4 个当前 Resolution；Presentation hash
`e591df3059af`、`presented_version=1`、`empty=true`，Selection/Plan/Job 均为空。根 Agent 已把 key 的
16–128 位 ASCII 字符规则和“脱敏缩写不可复制回 Tool 参数”写入当前 Skill，需后续真实调用重新验收。

课程/Bundle**真实失败/恢复路径**现有证据，但成功路径仍未完成。当前只证明 SmartEdu/Bilibili 的
Search/Inspect 可到达及组合缺口，不能把静态 `smartedu-resource` descriptor、课程页或单条视频解释成
本次可执行的多资产 Bundle。

### EV-0028-20260811-13 — 受控 Gateway 混合检索完成真实 Gap 闭合，但错误归因低相关召回

```text
evidence_id: EV-0028-20260811-13
evidence_level: real_openclaw (Gateway direct RPC) + real_platform (Bilibili/generic/BaiduWenku/Wechat/Zhihu/SmartEdu/Kepu Search and Bilibili Inspect)
observed_at_utc: 2026-08-11T01:11:13Z..01:13:21Z
environment_fingerprint: 503b48b6a95ff812e1ac875a663009964e741e9b2d7861f267a20ef705aa2065
natural_language_goal: 同一四季主题各找一篇公开图文文章、一段无需登录且证实本体的视频、一份证实 PDF 本体的可打印练习；只读，不选择、不获取、不归档
loaded_skill_and_mcp_digest: Skill tree 0f2b1624...fd20; runtime snapshot 9e17ea8c...2729; live list_tools unchanged
tool_sequence: read Skill -> FlowStart -> Search replace(8) -> Search extend(16) -> FlowStatus -> Search extend(20) -> Inspect x3(current Bilibili IDs) -> StopWithGap
platform_observations: Bilibili Search succeeded and retained 8 relevant videos；3 个 Inspect 均只证明 landing available、video representation unknown/materializable=false；generic 三轮真实 query 保持完整但结果低相关；BaiduWenku 三轮均 PARTIAL_FAILURE/retriable，实际 HTTP 403；Zhihu=AUTH_REQUIRED/non-retriable；Wechat/Kepu/SmartEdu Search succeeded but retained 项为空或偏题；没有相关公开 article 或 PDF candidate
human_confirmation: not_reached
side_effects: state_only; no presentation, selection, acquisition or archive
asset_archive_summary: no Presentation, Selection, Plan, Job, Asset or Archive
reason_codes: DIRECT_GATEWAY_RPC_PASS, SEARCH_ROUND_BUDGET_PASS, EXTEND_TOTAL_CAPACITY_PASS, FLOW_STATUS_RECOVERY_PASS, QUERY_PRESERVATION_PASS, MIXED_RECALL_FAILED, BILIBILI_SEARCH_PASS, BILIBILI_LANDING_AVAILABLE, VIDEO_REPRESENTATION_UNKNOWN, BAIDUWENKU_PARTIAL_FAILURE_3X, ZHIHU_AUTH_REQUIRED, NO_ARTICLE_BODY, NO_PDF_BODY, STOP_WITH_GAP_PASS, FALSE_QUERY_SPLIT_CAUSAL_CLAIM, NO_SIDE_EFFECTS
redactions_applied: run/session/Flow/ResultSet/Resource/Resolution IDs 与 query 只保留 hash/长度；URL、标题细节、Tool 原文和模型思考未入库
proves: 此前 EV-07 的混合场景可在受控 Gateway RPC 下进入完整业务 Tool 链，并在三种本体均未满足时按预算 StopWithGap；没有用 landing、偏题文章或其他类型凑数，也没有越过副作用门禁
does_not_prove: 文章/视频/PDF 三类成功组合、任何 acquisition/archive、BaiduWenku/Zhihu 恢复或 production readiness
```

根 Agent 对三轮 12 条请求 query 与 Search `platform_runs.query_runs.query` 做脱敏比对：每一条的平台、
长度与 SHA-256 前缀完全一致，且全部是 2–13 字的多字 query；因此 Agent 两次“被拆词”的解释没有
Tool 证据，真实事实只是当前 generic 召回低相关。当前 Skill 已收紧为：请求与平台回显一致时只能记为
搜索质量/召回 Gap，不得猜测 Adapter 内部行为。

根 Agent 通过独立真实 stdio `resource_flow_status` 复核：Flow hash `b2abc5fd7975`、`stage=reviewing`、
当前 ResultSet hash `e6822c8c952b`、`result_version=3`、`round=3`、20 candidates、3 个当前
Resolution；Presentation/Selection/Plan/Job 均为空。该状态与明确 StopWithGap 一致，不需要用空
Presentation 伪装成有可选候选。

混合检索**真实失败路径**现有证据，并已消除 CLI 自动 fallback 的证据污染；成功三类型路径仍未完成。
当前能够准确证明的是 Bilibili landing 与视频本体 unknown、BaiduWenku 连续可重试失败、Zhihu
AUTH_REQUIRED，以及 article/PDF 召回缺口，不能把这些改写成任一类型成功。

### 2026-08-11 Step D 只读矩阵检查点

- 当前源 Skill 与 OpenClaw 安装副本排除 `.openclaw/source-origin.json` 后均为 8 个文件，内容摘要同为
  `be82f5f57ea256c96c8442faa90b98edceb6053d55ae280f6ae8017081681cd1`，`diff -qr` 无差异；
  `openclaw skills check --json` 继续把 `learning-resource-flow` 列为 eligible、model-visible、
  command-visible，未因本轮行为约束修改失去可发现性。
- 根 Agent 已对音频、图书/版本、课程/Bundle、混合四个最新 Flow 分别通过独立真实 stdio
  `resource_flow_status` 复核；所有 Selection/Plan/Job 均为空，两个需要纠正的 Flow 使用空
  Presentation，混合 StopWithGap Flow 保持无 Presentation，没有隐式可选项或副作用。
- 当前追加修改仅涉及 Skill/reference 与 0028 Markdown；Step C/D 交界检查点的 runtime verifier、
  `489/489` unittest、stdio E2E、`compileall` 与 Schema JSON 结果仍适用于未再变化的 Python/runtime。
  本检查点重新执行 76 个 Markdown 文件的 128 个本地目标检查与仓库根 `git diff --check`，均通过。
- 前台 Gateway 已收到 SIGINT 并在 196 ms 内完成 clean shutdown；`127.0.0.1:18789` 与 `[::1]:18789`
  均无监听。LaunchAgent 的旧安装路径问题仍未 repair；未安装依赖、未修改全局 tool policy、模型、
  timeout、代理或用户级服务配置。
- Step D 仍为 `in_progress`：已完成七类只读/失败恢复事实，网页物化及任何真实获取仍停在用户明确
  选择闸门；没有选择与随后独立确认时，不进入 Selection/Prepare/Start/Job/Archive。

### 2026-08-11 Step F 进程级控制面与副作用门禁证据

- 隔离 fixture MCP 通过真实 stdio 子进程只暴露当前 13 个公共 Tool；`test_e2e_stdio_scenarios`
  现为 `6/6`：既有完整/partial Bundle 与网页物化归档路径继续通过，并新增
  `Presentation` 更新使旧 Selection/Plan 失效、运行中 Job 取消且无可归档 Asset、Inspect 明确
  `policy_blocked` 后 Prepare 以 `ELIGIBILITY_REQUIRED` 拒绝且不生成 Plan/Job、跨 Flow 使用有效
  Job/Asset 归档以 `ASSET_NOT_FOUND` 拒绝而原 Flow 仍可正常归档四条公共工具证据。
- `test_e2e_process_recovery` 的 `2/2` 继续证明进程被强制终止后持久状态恢复且不重放网络副作用，
  以及 `AUTH_REQUIRED` 后外部会话就绪必须创建新 Job；与上述 6 条合计 `8/8` 进程级 E2E。
- Step F 定向组合回归共 `83/83` 通过，覆盖 capability truth negative、execution authority、归档
  fail-closed、幂等重放、Selection 单调版本、取消竞态、partial/no-primary、Bundle/outcome 生命周期和
  全部公共 stdio 场景。测试只写临时隔离目录；没有读取或修改真实 0028 Flow、Plan、Job、Asset、
  平台会话或资源库。
- 本节证据级别是 `stdio_process`/`offline_fixture`，只满足退出条件 7 的“真实或进程级证据”；它不证明
  任一真实平台 acquisition 或 production readiness，也不解除 Step D 的用户明确选择和独立确认闸门。

| 场景 | 自然语言结果目标 | 必须观察的链路 | 通过标准 |
| --- | --- | --- | --- |
| 文章探索 | 找一篇中文图文科普文章，先比较再决定是否保存 | Flow → Search/Extend → optional Inspect → Present | 不提前下载；相关性和来源差异可解释；状态可恢复 |
| 网页物化 | 保存公开图文网页供离线阅读 | Select → Prepare → Confirm → Start → Job → Archive | landing scope 保持 landing；实际物化产物/Bundle 关系真实 |
| 视频 | 找并保存一个公开可获取视频 | Search → Inspect → capability chain → Acquisition | 只有 concrete primary 才承诺视频本体；landing-only 明确解释 |
| 音频 | 找一条可合法离线收听的音频 | Search → Inspect → capability chain → Acquisition | 媒体类型、container、role 与真实资产一致，无假 primary |
| 图书/版本 | 找指定版本图书，正文可得才下载 | Search → Inspect edition/representation → Select | 书目/索引只能是 metadata/landing；版本不确定时先澄清或 Inspect |
| 课程/Bundle | 找包含视频和 PDF 的课程 | 多表示 Inspect → Plan → multi-asset outcome | Bundle roles、required/optional、partial 和 Archive 关系一致 |
| 混合检索 | 同主题给文章、视频、可打印材料 | 多方向 Search/Extend → selective Inspect | Gap 驱动扩展，不无差别全平台搜索，不用数量冒充 coverage |
| 恢复 | 中断后继续刚才任务 | Flow/Job status → new interaction | 不丢选择与权威链；不自动重放已确认或网络副作用 |

每类至少包含一个成功路径和一个结构化失败/恢复路径；若真实世界没有合法成功条件，必须保留
`AUTH_REQUIRED`、`FEATURE_NOT_SUPPORTED`、`POLICY_BLOCKED`、`PROVIDER_UNAVAILABLE` 等真实结果，
不能把缺失成功样本改写成 fixture 成功。

## 逐平台 Readiness Matrix

对以下 16 个平台分别记录，不从 Registry 静态声明推断运行结果：

`generic`、`bilibili`、`douyin`、`zhihu`、`smartedu`、`ximalaya`、`cctv`、`yixi`、
`kepu`、`baiduwenku`、`runoob`、`nlc`、`open163`、`annas-archive`、`weibo`、`wechat`。

每个平台字段固定为：

```text
code_present
fixture_passed
runtime_component_loaded
network_smoke_passed
auth_flow_passed
search_passed
inspect_passed
acquisition_passed
policy_reviewed
production_ready
observed_at
environment_fingerprint
evidence_ids
reason_codes
```

`production_ready=true` 必须由本次环境中完整证据计算，不能人工从其他布尔值猜测；未通过时
用户文案只能描述为已接入、可搜索、实验性、需认证、策略阻断或不支持中的精确状态。

## 验证命令与门禁

除真实回合外，至少执行：

```bash
cd mcp/education-resources
PYTHONPATH=src TMPDIR=/tmp TEMP=/tmp <venv-python> -m compileall -q src tests
PYTHONPATH=src TMPDIR=/tmp TEMP=/tmp <venv-python> -m unittest discover -s tests -v
PYTHONPATH=src TMPDIR=/tmp TEMP=/tmp <venv-python> tests/e2e_stdio_client.py
```

并执行 catalog/schema/tool-count、Markdown links、文件存在性与仓库根 `git diff --check`。
如果真实网络或合法会话缺失，只能把对应步骤和平台标记为 `blocked`，列出已连续观测的证据、
影响与恢复条件；不得用离线 fixture 把本计划整体标记完成。

## 退出条件

1. 0025 已 completed 且根验收证据仍有效。
2. OpenClaw config/status/doctor/probe 串行通过，当前工作区唯一 Skill 与精确 13 Tool 可见。
3. 至少文章、网页物化、媒体、图书/版本、混合检索、恢复六大类真实 Agent 回合通过；
   课程/Bundle 和音频若无合法真实来源，必须有精确 blocked 证据而非伪造成功。
4. 每个副作用都可证明经过 prepare、人工确认、start，且 start 使用 0025 权威 digest/revalidation。
5. 真实失败保持结构化、可解释、可恢复，无静默 provider/strategy/scope 替换。
6. 16 平台均有本次环境 readiness 记录；只有证据完备者标 production-ready。
7. 中断/重启/幂等/取消/partial/无 primary/归档边界已通过真实或进程级证据。
8. 0023、CURRENT_ARCHITECTURE、DEVELOPMENT_PLAN、Skill/MCP 运维文档与实际证据同步。
9. 全量 unittest、stdio E2E、compileall、契约/链接/diff 检查通过，未运行项明确记录风险。
10. 根 Agent 对每个退出条件逐项审查通过后，本计划和 0023 才可标 completed。

### 2026-08-11 根 Agent 逐项完成审计

| 退出条件 | 当前判定 | 权威证据/缺口 |
| --- | --- | --- |
| 1. 0025 完成 | pass | 0025/0027 归档 completion evidence 与本轮基线复核一致。 |
| 2. OpenClaw/Skill/13 Tool | pass | config/status/doctor/probe 基线通过；当前配置再次 validate，唯一 active Skill 与 13 Tool digest 未漂移。 |
| 3. 六大类真实 Agent 回合 | incomplete | 文章只读和多类失败/恢复已有证据；网页物化成功、真实媒体/正文成功链仍未完成。 |
| 4. 副作用确认链 | not_reached | 用户尚未选择当前文章；没有真实 Prepare/Confirm/Start/Job/Archive。 |
| 5. 真实失败结构化 | pass | AUTH_REQUIRED、POLICY_BLOCKED、FEATURE_NOT_SUPPORTED、unknown/landing 与 StopWithGap 均未被 fallback 改写。 |
| 6. 16 平台 readiness | pass | 16 行与 Registry 精确一致，用户文案逐项审计，`production_ready=fail` 为 16/16。 |
| 7. 恢复/幂等/取消等边界 | pass | Step F 的真实或进程级 E2E 与 `83/83` 定向回归通过。 |
| 8. 文档同步 | partial | 0023、CURRENT_ARCHITECTURE、DEVELOPMENT_PLAN 和 MCP 运维说明已同步当前检查点；真实闭环后仍需最终结论更新。 |
| 9. 最终验证 | partial | 本次 direct-import 范围 session-manager 运行 67 项并 `OK (skipped=5)`，受影响 education bridge/SmartEdu `32/32`，两侧 compileall、Skill 校验、Markdown links 与 diff check 通过；新增测试后的 education 全量回归和完整 stdio E2E 尚未重跑。 |
| 10. 根验收完成 | fail | 条件 3、4、8 尚未通过；0028 与 0023 不能标 completed。 |

## 结果

- 0025、0027 与本计划 A/B/C 已完成；Step D 仍为 `in_progress`。文章已形成 2 项公开可读的真实
  Presentation；视频、音频、图书/版本、课程/Bundle、混合检索与中断恢复均已有真实失败/恢复证据，
  但不能把 landing、unknown representation、metadata、AUTH_REQUIRED 或静态 descriptor 改写为本体成功。
- 下一条成功路径是由用户从当前文章 Presentation 明确选择后验证网页物化：Selection 与 Prepare
  只生成权威计划；根 Agent 展示计划并再次获得独立明确确认后，才允许 Start/Job/Archive。用户尚未
  选择前，本计划不会擅自越过该闸门。
- 0027 的离线通过、generic 只读成功和各平台失败路径都不代表真实获取、真实归档、其他平台或
  production readiness 已通过；Step F 的进程级恢复与边界验证、Step G 的逐平台分级与文案审计已完成，
  Step E 的安装/注册/共享 store 与 direct-import 通道已通过，但当前 SmartEdu 会话被真实平台以认证
  HTTP 403 拒绝，因此继续精确标为 `blocked`；Step H 仍未完成。
