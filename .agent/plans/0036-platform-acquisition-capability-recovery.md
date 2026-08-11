# 平台获取能力恢复与架构止损计划

- 状态：pending
- 创建日期：2026-08-11
- 完成日期：未完成
- 范围：`legacy/skill-pipeline-v1/` 历史平台下载能力审计、`mcp/education-resources/` Active Provider 恢复、真实 OpenClaw 获取/归档/恢复验收，以及后续架构减法
- 前置事实：[`0027 Existing Platform Acquisition Enablement`](archive/0027-platform-acquisition-enablement.md) 已完成结构化阻断；[`0028 Real OpenClaw and Real Platform E2E`](0028-real-openclaw-platform-e2e.md) 尚未形成 Job、Asset 或 Archive
- 后续关系：本计划的真实平台纵切优先于 [`0029 Retrieval Benchmark and Release Gate`](0029-retrieval-benchmark-release-gate.md)

## Objective

恢复至少一条无需登录、来源和使用边界清晰的真实平台获取纵切，使用户能够通过自然语言完成：

```text
Search -> Inspect -> Present -> Select -> Prepare -> Confirm -> Start
       -> Job succeeded -> original Asset -> Archive -> Recover -> Open
```

第一条纵切必须产生可验证、可重新打开的原始 PDF、EPUB、MP4、音频或其他真实主资源，不能用
HTML 页面、landing page、metadata、错误页或网页 ZIP 替代。第一条通过后，继续恢复到至少三条
真实平台获取路线，再进入平台扩展、benchmark 或更大范围架构演进。

## Why this plan exists

当前项目保留 16 个平台的 Search 历史声明和 Adapter，但默认 acquisition 执行面只剩三条 exact route：

1. `generic-direct@1.0.0 / direct_file / primary_resource`
2. `generic-web-materializer@1.0.0 / web_materialize / landing_page`
3. `smartedu-resource@1.0.0 / direct_file / primary_resource`

Legacy 统一执行器曾明确路由 Bilibili、CCTV、Douyin、SmartEdu、Zhihu、NLC、Open163、Yixi 八个平台
下载入口；Active MCP 迁移没有完整保留这些入口，Bilibili、Douyin、Ximalaya、Anna/Libgen 等现有
Provider 随后又被移出默认执行面。0027 把“明确结构化阻断”作为阶段完成结果，保证了失败真实性，
但没有恢复真实产品能力。

0028 在 SmartEdu 真实 Search 返回认证 HTTP 403 后，把第一条无需认证路径固定为 generic 公共图文
文章。该候选只形成 `landing_page + web_materialize` Plan，随后 Plan 过期且未 Start；没有 Job、Asset、
Archive 或 Recover。继续围绕 HTML scope 修补不能回答用户是否真正获得教育资源。

相关事实来源：

- [Legacy 下载方法与八个平台入口](../../legacy/skill-pipeline-v1/skills/resource-downloader/references/download-methods.md)
- [当前 16 平台声明与三条 exact acquisition route](../../mcp/education-resources/contracts/platforms/README.md)
- [当前架构和未验收边界](../../docs/CURRENT_ARCHITECTURE.md)
- [当前开发路线](../../docs/DEVELOPMENT_PLAN.md)

## Non-goals

- 不把保存 HTML、sanitized HTML、Markdown、MHTML、截图或网页 ZIP 当作平台主资源获取成功。
- 不在本计划第一条纵切中新增平台、公共 MCP Tool、第二套下载控制面或新的 source of truth。
- 不绕过登录、验证码、付费墙、DRM、地区限制、平台访问控制或明确的版权/许可边界。
- 不因为代码存在就重新开启 Bilibili、Douyin、Ximalaya、Anna/Libgen 等已记录策略缺口的路线。
- 不立即删除 Descriptor、Readiness、Resolution、Eligibility、Plan、Job 或 Asset；先用真实纵切证明
  哪些结构有价值，再做减法。
- 不启动 0029 benchmark、远程 MCP、多租户部署、Viewer 大改或新的平台扩展计划。
- 不修改或继续开发 `legacy/skill-pipeline-v1/`；Legacy 只作为只读迁移依据和回归证据。
- 不读取、打印、提交或自动重放现有 Token、Cookie、浏览器档案或其他凭据。

## Business invariants

- 下载网络继续只允许 `http`/`https`，执行 SSRF、DNS/IP、逐跳重定向、域名、超时和取消检查。
- 每个响应和最终 Bundle 都有真实来源的大小上限；声明大小和实际流式读取量都必须校验。
- `Content-Type`、魔数、容器、扩展名和实际文件必须一致；登录页、错误 HTML、空文件和损坏文件
  不得成为 Asset。
- Provider 只能写入服务端创建的受控 Job 目录；路径逃逸、符号链接和外部文件引用必须拒绝。
- 有副作用的真实 Start 继续使用 `prepare -> 用户独立确认 -> start`。代码恢复、只读网络探测和
  Prepare 不代替 Start 确认。
- Flow、Selection、Plan、Job、Asset、Archive 和幂等状态继续由 MCP 服务端生成和持久化。
- “结构化 blocked”只表示路线未恢复，不得再作为平台获取能力完成或 production-ready 的证明。
- HTML 物化只在用户明确要保存文章/网页时执行；当目标是 PDF、EPUB、视频或音频时不能作为
  silent fallback。
- 凭据、运行 SQLite、下载产物和正式资源库继续与源码仓库分离。
- 现有用户未提交改动必须保留，不进入本计划提交范围。

## Security gates and their intended role

安全门禁是所有 Provider 共用的底层获取约束，不是独立产品阶段，也不应扩大成用户可见流程：

| Gate | Prevents | Required behavior |
| --- | --- | --- |
| SSRF / redirect policy | 访问 localhost、私网、链路本地、云元数据、DNS rebinding 或公开地址到私网的重定向 | 初始 URL、每一跳 redirect、最终 URL 和解析地址全部校验 |
| Size limits | 无限响应、磁盘/内存耗尽、超大附件、Bundle 失控 | 同时检查 `Content-Length` 和实际流式字节；按 HTML、文档、媒体分别配置 |
| MIME / magic validation | 把登录页、403 HTML、伪装文件、错误扩展名或损坏容器当作成功 | 声明类型、文件签名、容器和扩展名一致后才晋升 Asset |
| Path / atomic commit | Provider 覆盖外部文件、引用符号链接或留下半成品 | 只写受控临时目录；验证通过后原子提交 |
| Confirmation / idempotency | Agent 未经同意产生副作用或重放下载 | Start 前独立确认；相同幂等键只产生一个权威结果 |

这些约束应优先复用现有 `policy.py`、`downloader.py`、`acquisition/web_fetch.py`、
`acquisition/router.py` 和 Archive 校验，不为单个平台重复建立 generalized transport framework。

## Current architecture

### Relevant components

- `skills/learning-resource-flow/`：用户意图、候选判断、最小澄清和确认编排。
- `mcp/education-resources/src/education_resource_mcp/search.py`：generic 与多平台 Search 路由。
- `mcp/education-resources/src/education_resource_mcp/adapters/`：Active Search、Inspect 和部分 Downloader。
- `mcp/education-resources/src/education_resource_mcp/capability.py`：Descriptor、Readiness、Representation、
  Eligibility 和 Plan/Execution binding。
- `mcp/education-resources/src/education_resource_mcp/acquisition/`：Provider Router、Artifact/Bundle 和 Web Materializer。
- `mcp/education-resources/src/education_resource_mcp/service.py`：默认 Provider 注册、Job、Asset 和 Archive 控制面。
- `legacy/skill-pipeline-v1/skills/resource-downloader/`：八个平台下载器和统一执行器的只读历史证据。

### Sources of truth

- 平台 Search/Inspect 历史声明：`contracts/platforms/platform-registry.json`。
- 当前 acquisition 设计面：`contracts/capabilities/capability-descriptors.json`。
- 当前 Provider 运行面：`ResourceService` 构建的 `AcquisitionRouter.provider_registry`。
- 候选可获取事实：持久化 Resolution/Representation、Readiness 和 Eligibility。
- 实际结果：持久化 Job、Outcome、Asset/Bundle 和 Archive。

### Known constraints

- SmartEdu 当前保存会话在真实 Search 中得到认证 HTTP 403；不得自动重放。
- Bilibili、Douyin、Ximalaya、Anna/Libgen 当前有明确策略、授权、依赖或 representation 缺口。
- Legacy 中 CCTV、NLC、Open163、Yixi、Zhihu 下载入口没有完整迁入当前 exact Provider catalog。
- Legacy 文档和 fixture 不能证明今天的真实 endpoint、依赖、许可或内容仍可用。
- 第一次真实 Start 必须在新的 Plan 下重新取得用户确认。

### Unknowns to resolve before implementation

- CCTV、NLC、Open163、Yixi 的当前公开 endpoint 是否仍可用，是否返回原始文件或未加密点播资源。
- 哪一条路线无需登录、无需 ffmpeg 或其他大型依赖即可形成最小真实纵切。
- Legacy Provider 能否直接复用当前安全 HTTP 原语，还是只抽取解析逻辑更安全。
- 对应平台当前公开条款、API/页面契约和内容许可边界是否允许本项目的获取与个人归档用途。
- 现有 Inspector 是否能产生 exact primary Representation；若不能，最小需要增加哪些平台事实。

## Platform recovery groups

### Group A — first recovery candidates

优先只读审计以下 Legacy 公开资源入口：

| Platform | Historical output | First questions |
| --- | --- | --- |
| CCTV | 官方公开视频 API、未加密点播 HLS | 当前 API/页面是否仍给出可验证媒体；是否必须 ffmpeg |
| Open163 | 公开课 MP4，必要时未加密 HLS | 是否仍有直链 MP4；课程/单视频身份是否稳定 |
| Yixi | 公开 MP4、未加密 HLS或完整文稿 | 是否能稳定解析单视频 primary；没有视频时不得用文稿冒充视频 |
| NLC | 公开阅文 EPUB | 是否仍能取得公开 EPUB；版本、访问控制和文件签名是否清晰 |

第一条路线不按平台名气排序，以“无需登录、原始文件明确、依赖最少、合法边界清晰、Legacy 可复用”
为选择标准。

### Group B — authorized or article-specific recovery

- SmartEdu：第一条公开纵切通过后再处理合法会话恢复；403 未解除前保持 blocked。
- Zhihu：只在用户目标就是公开文章正文时作为网页主资源处理，不作为任意附件/媒体下载能力。

### Group C — remain blocked until conditions change

- Bilibili：官方授权/API 范围、内容权利和媒体依赖未满足前不注册默认 Provider。
- Douyin：不得把 Cookie、设备参数和内部 signer 视为官方可执行契约。
- Ximalaya：官方合作/API、单 track representation 和依赖未满足前不恢复。
- Anna/Libgen：没有逐作品许可、镜像和 redirect/network policy 时保持 blocked。

## Expected change surface

### Likely to change after a route is selected

- 一个明确平台的 Active Downloader Adapter；优先移植解析逻辑并复用现有安全传输。
- 对应 Inspector/Resolution 的最小 primary Representation 事实。
- `capability-descriptors.json` 中该平台唯一 exact route。
- `ResourceService` / `AcquisitionRouter` 中该 Provider 的显式注册和 readiness inventory。
- 对应定向 Provider、Capability、Service、Job/Asset/Archive 和恢复测试。
- `skills/learning-resource-flow/references/` 中仅与该真实能力直接相关的平台解释。
- 0028、CURRENT_ARCHITECTURE、DEVELOPMENT_PLAN 和本计划的实际证据。

### Should not change in the first route

- 公共 MCP Tool 数量和 `contract_version`。
- Flow/Selection/Plan/Job/Asset/Archive 的服务端 ownership。
- 通用 HTML Materializer 的实现；它不是本阶段成功路径。
- 其他平台 Adapter、Descriptor 或策略状态。
- `legacy/skill-pipeline-v1/` 内容。
- session-manager 凭据格式或 direct-import 通道。
- Viewer、远程 MCP、多租户和 benchmark 架构。

## Agent orchestration

根 Agent 保留平台选择、架构决策、写入整合、真实 Start 请求和最终验收权。

### Read-only audit phase

- 子 Agent A：审计 CCTV、Open163、Yixi、NLC 的 Legacy 下载入口、公开 endpoint、依赖、输出格式、
  访问控制和最小 live read-only probe；禁止修改文件和下载完整资产。
- 子 Agent B：审计 Active MCP 的 Adapter/Inspector/Descriptor/Provider/Outcome 接入断点，输出每个平台
  的最小变更面和复用测试；禁止修改文件。
- 根 Agent：对照 live 代码、当前契约和真实网络证据解决冲突，选择唯一第一条路线。

### Write phase

- 只把一个平台纵切交给一个隔离 worktree 中的 worker；明确文件所有权和验收命令。
- 共享的 capability catalog、service registration、计划和总文档由根 Agent 串行整合。
- worker 不得顺手恢复第二个平台、增加公共 Tool、引入 fallback 或修改其他平台策略。
- 根 Agent 必须独立复核 diff、定向测试、运行时注册和真实用户链，不能以 worker 完成声明代替验收。

## Acceptance criteria

### AC-01 — truthful recovery inventory

```text
Given: Legacy 八个平台入口和当前 Active 三条 exact route
When: 完成 Group A/B/C 的代码、依赖、访问控制和 live read-only 审计
Then: 每个平台都有“可恢复 / 需授权 / 策略阻断 / endpoint 失效”的唯一结论、证据和下一条件
And: blocked 不计入 restored 或 completed 数量
```

### AC-02 — first real original Asset

```text
Given: 一个无需登录且已证明存在 primary Representation 的 Group A 候选
When: 用户明确选择、看到新 Plan 并独立确认 Start
Then: exact Provider 从真实网络取得非零原始文件
And: MIME、魔数、容器、扩展名、大小和 SHA-256 全部通过
And: 结果不是 HTML、登录页、metadata、landing page 或网页 ZIP
```

### AC-03 — Archive, restart, Recover, Open

```text
Given: AC-02 产生的 ready Asset
When: 以 asset_id 归档、重启 MCP、执行 Library Search/Recover 并打开资源
Then: 归档关系、文件摘要、Representation 和可打开内容保持一致
And: 不依赖模型记住本地路径或重新请求远端
```

### AC-04 — failures remain honest

```text
Given: endpoint 失效、认证缺失、大小超限、MIME/magic 冲突、取消或策略拒绝
When: 执行对应 Prepare/Start/Provider 路径
Then: 返回稳定结构化失败且不创建假 Asset
And: 不切换到 HTML、generic direct、web capture 或其他平台作为 silent fallback
```

### AC-05 — three-route recovery gate

```text
Given: 第一条真实纵切已通过 AC-02/03
When: 按相同标准继续恢复平台能力
Then: 至少三条独立真实平台路线完成 Acquire -> Archive -> Recover -> Open
Before: 启动 0029 benchmark、平台扩展或宣称主体获取能力成熟
```

### AC-06 — user-visible simplicity

```text
Given: 内部仍可能保留 Descriptor/Readiness/Resolution/Eligibility/Plan/Job
When: 用户完成一次资源任务
Then: 用户只需理解搜索、比较、选择、确认、获取和资料库结果
And: 内部 TTL、digest、provider binding 和 evidence 不作为额外产品步骤暴露
```

## Validation scope

### Read-only selection gate

- 逐平台代码/依赖/endpoint 证据和小响应 HEAD/metadata probe；不得在选择路线前下载完整资源。
- 当前环境依赖版本和 Provider import/readiness 探测。
- Legacy 夹具与 Active contract 差距清单。

### First-route implementation gate

- Provider URL/redirect/SSRF、超时、取消、声明/实际大小、临时文件清理、路径和符号链接测试。
- 目标格式 MIME/magic/container、登录页/错误 HTML、零字节和损坏文件测试。
- Descriptor -> Readiness -> Representation -> Eligibility -> Plan/Execution -> exact Provider -> Outcome 测试。
- Job/Asset/Archive/Recover 的定向 service 与 stdio E2E。
- `compileall`、受影响 JSON/Schema、Markdown links 和 `git diff --check`。
- 全量 education-resources 回归只在第一条纵切跨越共享 capability/service/storage 边界时运行，并明确
  它不能代替真实平台用户验收。

### Real user-flow gate

- 使用当期真实网络和新幂等键；不复用旧 Plan、旧 confirmation token 或历史 Outcome。
- Start 前展示资源标题、平台、Representation、预计大小/上限、Provider 和实际风险，单独取得确认。
- Job 成功后核对真实文件，再 Archive、重启、Recover、Open。
- 记录真实成功和失败；不得把 read-only probe、fixture、unit test 或 OpenClaw doctor 当作该门槛通过。

## Complexity exceptions

默认：无。

第一条纵切必须复用现有网络、Provider、Capability、Job、Asset 和 Archive 原语。若实现方认为需要新增
abstraction、source of truth、fallback、兼容层或 generalized transport framework，先在本计划增加完整
复杂度举证；举证不足则不增加。

允许的最小复杂度方向只有：把已经在多个真实 Provider 中重复且行为不一致的安全传输/文件校验收口
到现有模块。不得为了尚未选择的第二个平台预先泛化。

## Milestones and steps

- [x] completed：A. 冻结当前能力退化事实、止损原则、平台分组和真实 Asset 验收标准；只创建本计划，不启动实现。
- [ ] pending：B. 暂停把 0028 HTML/landing-page 路径作为主验收，保持 0029 未启动，并同步计划接替关系。
- [ ] pending：C. 根 Agent 调度两个只读子 Agent，完成 Group A Legacy/live 能力与 Active 接入断点审计。
- [ ] pending：D. 根 Agent 选择唯一第一条公开平台路线，冻结平台级 Task Spec、依赖研究、文件所有权和最小验证。
- [ ] pending：E. 在隔离 worktree 中恢复该平台 Downloader/Inspector/Descriptor/Provider 纵切，由根 Agent 串行整合共享文件。
- [ ] pending：F. 完成离线定向/集成验证和 runtime 注册复核；没有可确认的 exact Plan 时不得进入真实 Start。
- [ ] pending：G. 展示新 Plan 并取得用户独立确认后，完成真实 Acquire -> Asset -> Archive -> restart -> Recover -> Open。
- [ ] pending：H. 按同一标准恢复到至少三条真实平台路线；SmartEdu 仅在新的合法会话被平台接受后进入。
- [ ] pending：I. 基于真实纵切使用证据做架构减法，简化用户可见流程，并决定 0029 是否仍有必要及其范围。

## Milestone checkpoints

每完成 C、G、H、I 后执行：

```text
Original goal still unchanged?:
Non-goals still respected?:
Business invariants still true?:
New abstraction introduced?:
New source of truth introduced?:
Fallback added?:
Data truncation added?:
Unrelated files changed?:
Actual original Asset produced?:
Archive -> Recover -> Open validated?:
Blocked route incorrectly counted as completed?:
Actual user flow affected?:
Actual user flow validated?:
Scope drift detected?:
```

任一 checkpoint 没有真实 original Asset 时，不得把 G/H 标为 completed。发现 scope drift 时先纠正，
不得通过降低资源类型、改写成 HTML 或放宽成功定义推进状态。

## Decision log

### Decision 001 — retain essential safety gates

- Context: SSRF、大小、MIME/magic、路径和确认门禁保护本机、资料库和结果真实性。
- Options considered: 删除门禁换取快速成功；继续为每个平台重复实现；复用现有安全层。
- Chosen option: 保留并复用现有安全原语，按资源类型配置真实上限。
- Why: 门禁不是能力退化根因，删除会制造假 Asset 和本机网络/文件风险。
- Complexity introduced: 无新抽象；只有真实重复行为出现时才允许最小收口。

### Decision 002 — blocked is not enabled

- Context: 0027 以所有不合格 Provider 被结构化阻断完成了阶段，但没有增加真实可执行平台路线。
- Options considered: 继续沿用“接入或阻断均完成”；只把真实 Asset 闭环计为恢复。
- Chosen option: `blocked` 只记录事实，不计入 restored、ready 或平台完成数量。
- Why: 产品结果是用户拿到并重新使用资源，而不是系统解释为什么拿不到。
- Complexity introduced: 无；只是收紧完成定义。

### Decision 003 — HTML is explicit, not a substitute

- Context: 当前第一条 generic 文章路径被分类为 landing-page materialization，但用户目标不是验证网页保存插件。
- Options considered: 继续以 HTML 物化作为首个闭环；删除 Web Materializer；保留为显式文章能力。
- Chosen option: 保留 Web Materializer，只在用户明确要保存网页/文章时使用；不替代文件或媒体 primary。
- Why: 网页文章可以是合法主资源，但不能证明平台 PDF、EPUB、视频或音频获取能力。
- Complexity introduced: 无新 fallback；需要后续明确网页正文与 landing page 的分类规则，但不阻塞第一条平台原始资产纵切。

### Decision 004 — recover capability before benchmark

- Context: 当前大量离线回归通过，但真实 Asset 数量仍为零。
- Options considered: 先执行 0029；先恢复一条或三条真实路线；重写全部架构。
- Chosen option: 第一条真实路线优先，三条路线达到 gate 后再重新评估 0029。
- Why: benchmark 只能校准已有行为，不能替代不存在的产品能力。
- Complexity introduced: 不新增架构；调整执行优先级。

## Verification record

本计划创建时只完成了只读事实审计和文档冻结，没有执行实现或真实平台请求。

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| current worktree/status review | passed | 新计划不会覆盖当前两处用户未提交改动 | 平台能力可用 |
| Legacy/Active code and plan audit | passed | 历史八个平台入口、Active 三条 route 和 0027/0028 状态可追溯 | endpoint 今天仍可用 |
| targeted unit | not run | 本次仅新增计划文档 | 任何实现正确 |
| integration/backend E2E | not run | 本次未实现代码 | 真实获取闭环 |
| real Agent/user flow | not run | 没有越过确认边界 | Job、Asset、Archive 或 Recover |
| full regression | not run | 新增计划不需要全量 Python 回归 | runtime 无回归 |

## Result

- 当前仅完成计划冻结；恢复实施尚未开始。
- 第一项后续工作是两个只读审计，而不是修改 HTML scope 或启动 0029。
- 第一次真实 Start 仍需要用户对当期新 Plan 的单独明确确认。
- 项目后续核心指标改为：真实可打开的 original Asset 数量，以及 Archive -> Recover -> Open 成功路线数。
