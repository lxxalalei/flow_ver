# 0027 Existing Platform Acquisition Enablement

- 状态：completed
- 创建日期：2026-08-10
- 完成日期：2026-08-11
- 范围：`mcp/education-resources` 中现有 Bilibili、Douyin、Ximalaya、Anna's Archive 下载实现与通用浏览器捕获机制的正式能力接入
- 前置计划：[`0025 Platform Capability Contract Alignment`](0025-platform-capability-contract-alignment.md)（completed）
- 后续验收：[`0028 Real OpenClaw and Real Platform E2E`](../0028-real-openclaw-platform-e2e.md)
- 实现基线：`4c7bdb9`（已推送至 `origin/codex/growth-resource-taxonomy-rework`）

## 目标

让源码中已经存在的平台获取实现进入 0025 冻结的单一权威链：静态 Capability Descriptor、
运行时 Deployment Readiness、Inspection 产生的 Resolution/Representation、Eligibility、不可变
Plan/Execution binding、exact AcquisitionRouter Provider、Outcome/Bundle/Asset/Archive。接入不得依赖
平台名隐式路由、generic fallback、扩大 timeout、跳过认证/权限或把 landing page 冒充 primary。

浏览器渲染/CDP 是通用 `web_capture` 获取机制，不计为独立平台；只有明确 descriptor、依赖和
策略均满足时才可执行。Anna's Archive/Libgen 获取必须经过明确版权/许可策略审查，不能因已有
下载代码就默认放行。

## 本阶段非目标

- 不修改 `skills/learning-resource-flow/` 或其 references；若实现中发现必须改变用户对话语义，
  只记录独立后续任务，不顺手扩大 0027。
- 不新增公共 MCP Tool，不改变 `contract_version=1.0.0`，不建立第二套平台级工具入口。
- 不把 Registry/Adapter/Downloader 已存在写成 `production_ready`，也不使用真实凭据、Cookie、
  Token、下载资产或正式 SQLite 作为离线测试夹具。
- 不通过 generic fallback、平台名猜测、扩大 timeout、跳过认证/权限或落地页冒充 primary 来
  获得表面成功。

## 步骤

- [x] completed：A. 审计现有 Provider、Inspector、搜索候选、依赖、认证、网络与内容校验边界，冻结逐平台接入矩阵。
- [x] completed：B. 复核 Capability Descriptor、runtime readiness inventory、provider registration 与版本兼容策略；修复 `running` Outcome 的公共 Schema 漂移并锁定 generic fail-closed 基线，阻断项不新增空壳 descriptor。
- [x] completed：C. 逐平台审查 Provider 的安全、依赖、认证和结构化错误缺口；没有一条被阻断的 legacy Provider 满足接入条件，因此默认 ResourceService 保持三条已证明 exact route。
- [x] completed：D. 补齐逐平台 capability 不声明、generic cross-route 禁止和 materialize Plan/Execution/Outcome 一致性的契约与生命周期回归。
- [x] completed：E. 运行受影响单测、全量 unittest、契约/Schema、compile、retrieval calibration 和 stdio fixture 覆盖，由根 Agent 审查差异。
- [x] completed：F. 更新架构、MCP 文档和 0028 E2E 边界与交付结果；active Skill 保持不变，真实网络与合法会话验收留给 0028。

## 2026-08-11 步骤 A 根 Agent 冻结结果

- 审计基线：`7a3e263`；工作树已有且继续保留 `AGENTS.md` 与
  `skills/learning-resource-flow/references/conversation.md` 两处外部未提交修改，本计划不触碰。
- 机器事实优先级继续是 contracts → runtime → 当前架构文档 → 执行计划；Platform Registry 中的
  历史 acquisition 声明不等于 1.1 Capability Descriptor、runtime readiness 或 executable Provider。
- 当前 Capability catalog 只有 generic direct、generic webpage materialize 和 SmartEdu direct 三条
  descriptor；默认 `ResourceService` 也只注册对应三个 exact Provider。所审计平台当前不会被
  generic 接管，而是在 descriptor/provider/representation 门槛 fail closed。

| 平台/机制 | Search / Inspect | 当前权威链事实 | 依赖 / 认证 / 策略 | 冻结状态 | 本阶段处置 |
| --- | --- | --- | --- | --- | --- |
| generic direct | Generic Search + `GenericWebInspector` | 已有 concrete primary document descriptor 与 `generic-direct@1.0.0` | public HTTP；无认证；禁止 fallback | `ready`（仅代码接入事实） | 锁定为 exact-route 与 no-fallback 回归基线；不以此证明真实网络 ready |
| generic webpage materialize | Generic Search + `GenericWebInspector` | 已有 landing-page descriptor 与 `generic-web-materializer@1.0.0` | public HTTP；无认证；landing 不升格 primary | `ready`（仅代码接入事实） | 锁定 landing/primary 边界与无隐式 capture 回归 |
| Bilibili | Search 与平台 Inspector 已存在；Inspector 当前只产生 unknown companion video | 无 1.1 descriptor；`BilibiliDownloader` 未注册；没有 concrete primary video binding | 官方开放平台未声明任意视频播放/下载 API；用户协议限制未经书面许可的自动获取；`ffmpeg` 必需且当前机器缺失 | `policy_blocked` + `dependency_missing` | 本阶段保持 fail closed：不登记 executable descriptor/provider；只有取得书面授权/官方 API 范围并补齐依赖与安全 transport 后才可重新开启 |
| Douyin | Search/creator browse 存在；Registry `inspect=false` | 无 Inspector、descriptor、readiness 或 exact Provider | 官方 Open API 只在应用权限与用户授权范围内开放特定视频/数据能力；现有源码使用网页 Cookie、硬编码设备参数和 `a_bogus` signer | `policy_blocked` + `auth_required` | 本阶段保持 fail closed：不补基于网页内部接口的 Inspector/Provider；未来仅对官方授权且明确允许获取的 Representation 重开 |
| Ximalaya | Search 与 Inspector 已存在；Inspector 只产生 unknown companion audio | 无 descriptor/readiness/exact Provider；album 自动取首曲会造成 representation 漂移 | 官方 Open API/SDK 需要开发者入驻、应用授权和内容合作范围；现有源码使用非官方网页签名/硬编码设备材料；当前 Python 还缺 `Crypto` | `policy_blocked` + `auth_required` + `dependency_missing` | 本阶段保持 fail closed：不登记现有 Downloader；未来只允许官方 Open API/SDK 授权的单 track 或显式 Bundle 语义，禁止 album → 隐式首曲 |
| Anna / Libgen | Search 与 Inspector 已存在；Inspector 默认只给 metadata/landing | 无 descriptor/readiness/exact Provider；没有 concrete primary 或可审计许可事实 | 匿名镜像；版权、许可、镜像 allowlist 与 redirect policy 未决 | `policy_blocked` | 本阶段保持结构化阻断；未有书面政策前不注册默认成功 Provider |
| `web_capture` | 通用 rendering 实现存在，但不是独立平台 | Router 支持策略类型；catalog、readiness、default Provider 均未接入；旧 seam 被 Service 显式拒绝 | live Chrome 存在但默认 binary 路径不匹配，Python 缺 `websocket-client`；只验证入口 URL，未逐请求拦截 redirect/subresource | `unsupported` | 本阶段保持 fail closed：不登记 descriptor/provider；只有逐请求网络策略、显式依赖和输出校验完备后才重开，且永不作为静态/认证失败的 fallback |

### 根 Agent 冻结的实施顺序

1. 先修复 runtime `Acquisition Outcome.status="running"` 与公共 `outcome_status` Schema 的 P0 漂移，
   补 job-status contract round-trip；不改变 `contract_version=1.0.0`，不新增状态权威。
2. 固化 generic direct/materialize 的 no-fallback 与 landing/primary 负面基线。
3. 复用现有 policy/fetch/validation 原语补齐平台 Provider 的 URL、逐跳 redirect、host/address、大小、
   临时文件清理、MIME/magic 和取消边界；若现有结构不能承载复用，再先完成 `AGENTS.md` 的复杂度举证，
   不预先创建新的 generalized transport framework。
4. 按 Bilibili → Ximalaya → Douyin 串行迁移平台纵切；每条先有可审计 Representation，再登记
   descriptor/readiness/exact Provider，前一条通过定向生命周期测试后才迁移下一条。
5. Anna/Libgen 先完成明确 policy disposition；没有合法允许范围时，以可测试的 `policy_blocked`
   完成本阶段处置，不以匿名镜像可访问性替代授权。
6. 最后接 `web_capture`，仅允许显式 descriptor/strategy，增加 Chrome/CDP dependency readiness 和
   “任何 Provider 失败都不会转入 capture”的负面测试。

### 2026-08-11 Bilibili 第三方依赖研究与处置

本次研究只使用 Bilibili 官方一手材料和 live 本机依赖事实；没有调用真实平台 API、没有使用会话或
下载内容。

```text
Dependency + exact version:
- ffmpeg: 外部可执行依赖，仓库未固定版本；live PATH 中不存在，无法给出已安装版本
- WBI nav/view/playurl: 现有源码使用的未版本化网页内部接口，不属于已找到的官方 Open API 契约
Required capability:
- 对已检查的公开 BVID/CID 取得可验证的 primary video representation，并在用户确认后安全获取
Official API / types inspected:
- https://openhome.bilibili.com/doc
- https://openhome.bilibili.com/agreement/developer-service
- https://www.bilibili.com/blackboard/user-rule-linux.html
What the dependency already solves:
- 官方开放平台公开列出账号授权、稿件发布/删除/查询和授权数据能力；未列出任意公开视频播放地址或下载能力
What must still be implemented locally:
- 只有未来取得匹配本产品的官方书面授权/API 后，才讨论 exact Inspector/Provider、逐跳网络策略、
  max_bytes、MP4 magic、ffmpeg 取消/清理和离线生命周期测试
Known limitations / migration constraints:
- 官方用户协议第 4.2.11 条限制未经事先明确书面许可使用自动程序获取平台服务、内容或数据；现有
  WBI/playurl 实现不能被当成官方支持或稳定兼容面
- 视频内容还需要逐项权利依据；用户拥有 Bilibili 会话不等于拥有下载、归档或再次分发授权
Current project integration points:
- adapters/bilibili.py、adapters/inspect_bilibili.py、adapters/bilibili_download.py、
  inspection_registry.py；Downloader 当前未注册到默认 ResourceService
Why this approach is preferred:
- 保留 Search/landing Inspection，但不新增 descriptor/provider，使现有权威链继续结构化 fail closed；
  不以内部网页接口、cookie 或缺失 ffmpeg 构造表面成功
```

根 Agent 基于上述一手材料作出的保守推断是：Bilibili acquisition 当前属于 `policy_blocked`，同时
live 部署还存在 `ffmpeg` dependency missing；后者解决也不会自动解除前者。该新证据把 Bilibili
纵切的本阶段完成条件从“接成 executable”收敛为“明确不注册且有回归证据”，不改变 0027 总目标或
generic/exact-provider 业务不变量。

### 2026-08-11 Ximalaya 第三方依赖研究与处置

```text
Dependency + exact version:
- pycryptodome>=3.20（pyproject 已声明）；live Python 3.14.5 当前找不到 Crypto 模块
- 喜马拉雅 Open API/SDK：官方页面未给出一个可由本仓库匿名使用的固定 API 版本；需要开发者入驻、
  应用和相应内容/调用权限
Required capability:
- 对用户明确选择的单个 track 取得可验证 audio representation；不得把 album 静默改写成首曲
Official API / types inspected:
- https://open.ximalaya.com/
- https://open.ximalaya.com/docNoHelp/detailApi?articleId=6&categoryId=1
- https://open.ximalaya.com/doc/detailDev?articleId=21&categoryId=4
- https://www.ximalaya.com/gatekeeper/member-agreement-html/ts-1626084264680
What the dependency already solves:
- 官方合作面可提供免费内容或授权内容的声音模型、播放能力和受限播放地址；不同接入形态要求 API
  调用权限或官方客户端 SDK
What must still be implemented locally:
- 若未来获得官方合作授权，需要新增受控的 Open API client、应用级凭据管理、单 track identity、
  短期 locator 重取、内容类型/magic、大小、取消和归档权利校验
Known limitations / migration constraints:
- 官方文档同时存在旧的免费播放地址接口说明和“服务端 API 不再直接返回播放地址、需 SDK”的接入
  说明；不能凭旧页面假定当前匿名能力
- 最新会员协议把自动脚本下载/传播与平台分离排除在合法会员服务之外；普通 Cookie/VIP 不等于开发者
  API、离线归档或再次分发授权
- 现有 ximalaya_download.py 使用网页 baseInfo、硬编码 AES/device 材料和第三方签名上报，并会把
  album 隐式变成第一首；这些都不能成为当前 exact Provider 的基础
Current project integration points:
- adapters/ximalaya.py、adapters/inspect_ximalaya.py、adapters/ximalaya_download.py、
  inspection_registry.py；Downloader 当前未注册到默认 ResourceService
Why this approach is preferred:
- 维持 Search/landing Inspection 与结构化阻断，避免把普通会话、逆向网页协议或第一首曲目替代成
  用户确认的 primary resource
```

根 Agent 的保守推断是：当前 Ximalaya acquisition 同时受 policy、authorization 和 deployment
dependency 阻断；安装 `pycryptodome` 或提供普通 Cookie 都不足以解除阻断。本阶段不新增其
descriptor/provider，后续只有在官方合作授权与 Representation 语义明确后才重开。

### 2026-08-11 Douyin 第三方依赖研究与处置

```text
Dependency + exact version:
- Node.js v24.19.0（live）；现有 douyin_sign.js 无外部版本契约，用于计算网页内部 a_bogus
- Douyin Open API：按应用 capability/scope、access-token、open_id 和用户授权控制，具体接口独立演进
Required capability:
- 只对用户明确选择且权利允许的单个视频产生 concrete primary representation，并在确认后获取
Official API / types inspected:
- https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/basic-abilities/video-id-convert/user-video-data/video-data
- https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/posting-task/video-basic-info
- https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/operation/data-analysis/video-analysis/video-detail-analysis-data
- https://developer.open-douyin.com/docs/resource/zh-CN/dop/operation-standard/service-protocol/mobile-web-app-protocal
What the dependency already solves:
- 官方 API 可在已申请能力、应用 token 和用户授权下查询该授权用户的特定公开视频或特定业务范围
  数据；部分受限业务返回播放地址，但不是任意公开视频下载接口
What must still be implemented locally:
- 若未来取得匹配业务的官方 capability，需要 Open API OAuth/permission 集成、Inspector、author
  download permission/rights 证据、短期 locator、逐跳策略、MP4 校验和 exact Provider 生命周期
Known limitations / migration constraints:
- 官方接口限制为授权账号/特定业务范围；不能把普通网页 Cookie 或任意 aweme_id 当成 Open API 权限
- 官方移动/网站应用协议禁止未经书面许可通过 crawler/拟人程序等非正常浏览方式读取、复制或转存内容
- 现有 douyin.py/douyin_download.py 使用硬编码浏览器参数、网页 API、Cookie 和 a_bogus，且没有当前
  Inspector；Node 可用不等于 policy 或 acquisition readiness
Current project integration points:
- adapters/douyin.py、adapters/douyin_download.py、adapters/douyin_sign.js、platform registry；默认
  InspectionRouter 与 ResourceService 均没有 Douyin executable route
Why this approach is preferred:
- 保留现有检索的独立风险边界，但不把网页内部接口变成 acquisition 权威；避免 session、平台名或
  URL 触发未授权 exact Provider
```

根 Agent 的保守推断是：当前 Douyin acquisition 为 `policy_blocked` 且 `auth_required`；Node signer
可运行只证明本地依赖，不证明官方接口权限、候选 Representation 或下载/归档权利。本阶段不新增
Inspector、descriptor 或 Provider。

### 2026-08-11 Anna/Libgen policy disposition

本项不尝试对不同法域、具体作品和镜像作抽象法律判断。仓库根约束已经要求 Anna/Libgen 必须先有
明确版权/许可策略，当前候选又没有可审计的逐作品权利事实，因此“不启用”无需以镜像可访问性或下载
成功来补证。

```text
Required capability:
- 只对明确版本、concrete primary document 和可审计使用权利绑定 exact Provider
Current implementation facts:
- Inspector 保守输出 metadata/landing，rights_hint 明确不代表官方 API 或下载授权
- Downloader/LibgenClient 使用匿名镜像 failover；默认镜像和环境变量镜像未进入 capability policy
- urllib 路线没有复用当前逐跳 SSRF/redirect/host policy，输出名与 MIME/magic 也不足以晋升可信 Asset
Machine disposition:
- 不新增 capability descriptor、readiness 或 provider registration
- prepare 只能以 CAPABILITY_NOT_DECLARED / representation gate 等结构化结果 fail closed
Reopen conditions:
- 明确的逐作品/来源许可事实、受控镜像 allowlist、逐跳网络策略、版本/文件身份、MIME/magic、
  临时文件清理、取消与生命周期测试
```

因此 Anna/Libgen acquisition 本阶段以 `policy_blocked` 完成明确处置；现有 Search/Inspect 的 metadata
能力不被删除，也不被提升为 primary acquisition。

### 2026-08-11 `web_capture` 依赖、安全与路由处置

```text
Dependency + exact live fact:
- /Applications/Google Chrome.app/Contents/MacOS/Google Chrome 存在
- EDUCATION_RESOURCE_MCP_CHROME_BIN 未设置时源码默认 /opt/google/chrome/chrome，与当前 Mac 不匹配
- live Python 3.14.5 无 websocket 模块；pyproject.toml 也未声明 websocket-client
Required capability:
- 只对显式选择、显式 descriptor 和 web_capture strategy 的 landing representation 生成受控 MHTML/PDF/PNG
Official API inspected:
- https://chromedevtools.github.io/devtools-protocol/tot/Page/
- https://chromedevtools.github.io/devtools-protocol/tot/Fetch/
What CDP already solves:
- Page.navigate 可发起导航；Page.captureSnapshot/printToPDF/captureScreenshot 可生成渲染产物
What must still be implemented locally:
- 使用 Fetch.enable/requestPaused 对主导航、每次 redirect 和所有 subresource 请求逐项应用 outbound policy
- 显式探测 Chrome binary/version 与 websocket-client，校验最终顶层 URL、产物 magic/MIME 和失败清理
Known limitations:
- 当前 RenderingDownloader 只在调用 CDPRenderer 前验证初始 URL
- CDPRenderer 只启用 Page；即使设置 cookie 也只启用 Network，没有启用 Fetch 或处理 requestPaused
- 官方 Fetch 文档明确 redirect 会形成新的 request，需要对每一跳重新处理；当前实现没有该循环
Routing disposition:
- AcquisitionRouter 只允许 exact (provider_id, version) 且不跨 strategy fallback
- 默认 catalog/ResourceService 不声明或注册 capture，legacy rendering_downloader seam 被显式拒绝
```

所以 live Chrome 的存在不足以使 `web_capture` ready。根 Agent 将其冻结为 `unsupported`，不安装临时
依赖、不新增 descriptor/provider；已有 static materializer 失败、认证失败或普通静态页面都不会转入
浏览器捕获。

### Milestone checkpoint A

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes; active Skill, public Tool count and contract_version unchanged
Business invariants still true?: yes; exact Provider and prepare-confirm-start remain authoritative
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no; only this plan is updated by the root Agent
Actual user flow affected?: no; this milestone is read-only audit and plan freeze
Actual user flow validated?: no
Scope drift detected?: no
```

### Milestone checkpoint B

```text
Original goal still unchanged?: yes; every audited acquisition is either exact executable or structurally blocked
Non-goals still respected?: yes; active Skill, public Tool count and contract_version unchanged
Business invariants still true?: yes; exact Provider, no fallback and prepare-confirm-start remain authoritative
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Data truncation added?: no
Unrelated files changed?: no; root preserves pre-existing AGENTS.md and conversation.md edits
Actual user flow affected?: only the public running Outcome schema is aligned with existing runtime output
Actual user flow validated?: offline contract, service and stdio fixture tests only; no real OpenClaw/platform claim
Scope drift detected?: no
```

## 新会话执行交接

### 起手检查

新根 Agent 先完成以下只读动作，不根据历史交接猜测当前状态：

1. 读取根 `AGENTS.md`、`README.md`、`docs/CURRENT_ARCHITECTURE.md`、
   `docs/DEVELOPMENT_PLAN.md` 和本计划。
2. 运行 `git status --short --branch`、`git rev-parse HEAD`、`git log -3 --oneline`，确认工作树和
   分支；不得清理、回滚或覆盖用户的新改动。
3. 检查 capability descriptor、platform Registry、Inspector inventory、AcquisitionRouter、
   ResourceService、storage migration 和现有逐平台测试的 live 状态。
4. 第一轮只形成逐平台接入矩阵和实施顺序；在矩阵经根 Agent 审核前，不执行真实下载或大范围改码。

逐平台矩阵至少包含：平台/机制、Search/Inspect 路线、descriptor ID/version、exact Provider、
支持的 resource type/scope/strategy、Representation 证据、依赖、认证、版权/策略、readiness 状态、
内容校验、取消/幂等、现有测试、缺口和建议处置。状态只使用 `ready`、`auth_required`、
`dependency_missing`、`policy_blocked`、`unsupported` 或明确的开发中状态。

### 推荐的双子 Agent 分工

第一轮调查可以并行且保持只读；向两个 worker 使用精炼、自包含上下文，优先
`fork_turns="none"`：

- **`terra_worker`：跨层能力权威审计**
  - 审查 Bilibili、Douyin、Ximalaya、Anna/Libgen 与 `web_capture` 从 Descriptor → Readiness →
    Resolution/Representation → Eligibility → Plan/Execution → exact Provider → Outcome 的完整链。
  - 找出隐式平台路由、generic takeover、scope/representation 漂移、认证/策略绕过、landing page
    冒充 primary 和无法追溯的 Outcome 风险。
  - 输出逐平台结论、P0/P1 缺口、推荐接入顺序和应新增/修改的测试；第一轮禁止修改文件。

- **`luna_worker`：实现与测试清单审计**
  - 枚举每个平台现有 Downloader/Inspector/Adapter、注册位置、依赖探测、环境变量、错误码、
    内容校验和测试覆盖。
  - 运行或整理低成本定向基线，核对哪些测试已经证明 exact Provider、取消、大小、MIME/magic、
    重定向、认证和结构化失败，哪些仍缺失。
  - 输出文件映射、可复用测试命令和边界清晰的实现任务；第一轮禁止修改文件。

根 Agent 必须对照 live 代码复核两份报告，解决冲突并冻结唯一矩阵。第二轮实现时：

- 高复杂度、跨层且边界明确的单个平台/权威链任务可交给 `terra_worker`；
- 局部 Provider 修复、测试补充、依赖探测或结构化错误等明确任务可交给 `luna_worker`；
- 任何并行写入必须使用独立 worktree/分支并明确文件所有权；共享文件无法隔离时改为串行；
- worker 不能自行增加平台、改变公共 Tool、修改 active Skill 或扩大策略许可；
- 根 Agent 必须逐项检查实际 diff、契约、测试和失败语义，不能只接受 worker 的完成声明。

### 推荐执行顺序

1. 完成步骤 A，冻结逐平台矩阵并更新本计划证据。
2. 根 Agent 选择一个依赖、许可和 Representation 最清晰的平台作为第一条端到端接入，不按平台
   名气排序；Anna/Libgen 未完成政策判断前不得作为默认成功路径。
3. 对该平台串通 descriptor/readiness/inspection/eligibility/plan/execution/provider/outcome，并补齐
   离线契约与生命周期测试；通过后再迁移下一平台。
4. 最后处理 `web_capture` 的显式适用范围，证明它不是其他 Provider 的自动 fallback。
5. 所有离线门槛通过后才进入 0028 的合法真实网络/OpenClaw E2E；环境或凭据不足必须结构化记录，
   不得伪造生产就绪。

### 根 Agent 验收门槛

- 每个平台都有唯一、可追溯的 descriptor/readiness/representation/eligibility/exact provider 链；
- 未就绪、未认证、策略阻断、representation 不匹配和 Provider 缺失均 fail closed；
- 无跨平台、跨 scope、跨 resource type 或跨 strategy 的静默 fallback；
- Provider 输出只能在受控 Job 根目录内，经大小、MIME/magic、摘要和角色校验后晋升为 Asset；
- 取消、幂等、重启恢复和 partial failure 保留真实 Outcome，不产生零字节假 Asset；
- 运行受影响定向测试、全量隔离测试、retrieval calibration、`compileall`、JSON/Schema、Markdown
  链接和 `git diff --check`；真实 OpenClaw 结果与离线结果分层报告；
- 每完成一个阶段立即更新本计划状态，同一时间只保留一个 `in_progress` 步骤。

### 2026-08-10 交接验证与环境提示

- 基线提交前使用一次性 `/tmp` virtualenv 安装当前 package；隔离全量 unittest **482/482 通过**，
  retrieval calibration **39/39 通过**，`compileall`、56 个 JSON 解析、120 个 Markdown、174 个本地
  链接、UTF-8、围栏和 `git diff --check` 均通过。
- `openclaw config validate --json` 输出 `valid=true`、`warnings=[]`，但进程在输出后未自行退出并被
  timeout 终止；`mcp doctor --probe` 与 `mcp probe --json` 本会话 90 秒内无输出并超时。新会话应
  live 重试并区分 CLI/环境挂起与 MCP 功能失败，不沿用“已通过”或“已损坏”的历史结论。
- 本会话尝试启动 `terra_worker` 时收到 `agent thread limit reached`；live config 中
  `luna_worker`/`terra_worker` 定义存在，但未看到 `agents.max_concurrent_threads_per_session`。
  新会话先用轻量只读任务验证两个 worker；若仍失败，检查 Codex effective config/会话并发或重启
  Desktop，不修改产品代码来绕过调度环境问题。即使 worker 不可用，根 Agent 仍可串行推进。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| 受影响 capability/acquisition/platform 子系统 | 97/97 passed | `running` Schema、exact route、no-fallback、blocked catalog 和 materialize Outcome 回归通过 | 真实网络或 Agent 回合 |
| 隔离全量 unittest | 485/485 passed | 当前 Python 包的离线单元、Service、storage、fixture stdio 与安全回归通过 | 真实 OpenClaw 配置、合法平台会话或 production readiness |
| retrieval calibration | 39/39 passed | 既有确定性检索 oracle 未被本阶段改动破坏 | 在线检索质量 |
| runtime dependency verifier | passed in `/tmp` venv | `education-resource-mcp 0.2.0` 与 pyproject 声明依赖一致，Crypto 可用 | 系统 Python 或正式部署依赖 ready |
| compileall | passed，pycache 定向到 `/tmp` | `src` 与 `tests` 可编译 | runtime 行为正确 |
| JSON / Markdown / diff | all JSON parsed；118 Markdown 本地链接与 UTF-8 passed；`git diff --check` passed | 机器文件可解析、文档本地引用存在、差异无 whitespace error | 外部链接持续可用 |
| real OpenClaw / real platform | not run by design | 保持 0027/0028 验收分层 | 不证明任何平台 production-ready |

## 结果

- 0027 已完成。公共 `outcome_status` 与既有 runtime `running` 对齐；generic direct/materialize 的
  exact-route、scope 和 persisted Outcome 基线已加回归。
- 现有 Bilibili、Douyin、Ximalaya、Anna/Libgen 与 `web_capture` 均未满足同时可审计的
  Representation、策略、依赖和安全边界，因此没有新增 descriptor/provider；机器行为保持
  `CAPABILITY_NOT_DECLARED` 与 no-fallback，具体恢复条件已记录。
- 默认机器 catalog 与 ResourceService 仍只有 generic direct、generic landing materialize 和
  SmartEdu direct 三条 exact route；没有新增公共 Tool、抽象、source of truth、fallback 或 active
  Skill 改动。
- 真实 OpenClaw、真实网络、合法会话、逐平台 E2E 和 production readiness 不属于本阶段完成证据，
  按计划转入 0028。
