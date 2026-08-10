# 采集策略与网页物化

> 历史基础：0021–0022；当前执行边界：catalog 1.5.0 Capability Authority
>
> 本文描述 education-resources 内部的获取策略和唯一入口 Skill 的决策边界，不是新的 MCP
> 公共契约，也不是要求模型提交的参数协议。

## 版本与公共边界

当前公开口径固定为：

| 项目 | 口径 |
|---|---|
| `contract_version` | `1.0.0` |
| `catalog_version` | `1.5.0` |
| 公共工具 | 13 个，工具名不增加 |
| 用户控制流 | `resource_download_prepare` -> 用户明确确认 -> `resource_download_start` |
| 归档入口 | 仍只接受服务端产生的 `asset_id`，Bundle 关系由服务端投影 |

Acquisition Router 是 Job 执行路径中的内部组件。0022 的 catalog 1.3.0 增加 AssetBundle
兼容投影，历史 1.4.0 增加 factual `coverage` 元数据，当前 1.5.0 增加 Capability Authority
与 Acquisition Outcome 的兼容投影；均不改变公开工具名、`contract_version=1.0.0`、确认流程、
Job 生命周期或 Archive 输入，也不把内部路由名暴露为新的 MCP 工具。

## Capability Authority 与精确执行路线

服务端权威链固定为：

```text
Capability Descriptor
-> Runtime Readiness
-> persisted Resolution / Representation
-> Eligibility
-> Plan capability binding + authority_digest
-> fresh Execution binding
-> exact Provider
-> persisted Acquisition Outcome
-> Asset / AssetBundle
-> sanitized Job status projection
```

`resource_download_prepare` 只能从已声明的 descriptor、当前 readiness、持久化
Resolution/Representation 和 Eligibility 生成精确的 Provider/strategy/scope Plan binding。
`plan_digest` 已绑定服务端生成的 `authority_digest`；Skill 和模型不能生成或重算任一摘要。

`resource_download_start.authority_digest` 是可选兼容校验输入。省略时服务端从不可变 Plan 读取
真实摘要；提供时必须精确匹配。start 会重新校验 authority facts 并持久化 fresh immutable
Execution binding，Job runner 只能按该绑定调用 exact Provider。省略摘要不是 fallback，也不允许
从平台 Registry、旧 options、扩展名或通用 Provider 推导另一条 strategy/scope 路线。

`allow_safe_fallback` 只保留为兼容字段；只有 Capability Descriptor 与 readiness 明确声明并重新
校验的同 Provider、同 strategy、同 scope 路线才可能成立。当前 descriptor 的 fallback 均未
启用，因此没有隐式或静默 generic Provider takeover。

## Artifact、Asset 与 AssetBundle

获取过程中必须区分临时产物、持久化资产和关系：

- `Artifact` 是一次 Acquisition 尝试产生的临时单项文件描述。它没有公共 `asset_id`，只有
  通过服务端路径、大小、MIME、魔数和摘要校验并提交后，才能成为 `Asset`。
- `Asset` 是服务端确认并持久化的不可变内容表示，使用服务端生成的 `asset_id`。本地路径
  不是业务标识，不能出现在 Skill 输入或用户可提交的 Archive 参数中。
- `AssetBundle` 是一个 Job × Resource 的有序关系，最多一个 Bundle；它不是 ZIP、文件夹或
  物理容器。`BundleItem` 关联成功 Asset，或在失败时保留角色、顺序、item key 和错误事实，
  失败项的 `asset_id` 必须为空，不创建零字节假 Asset。
- 一个可用 Bundle 必须有且只有一个 `primary`。公开角色固定为：
  `primary`、`subtitle`、`cover`、`metadata`、`attachment`、`transcript`、`companion`。
  角色、顺序、`bundle_id` 和 `item_key` 由服务端生成，不能按文件名或扩展名猜测。

Bundle 完整度只有在已有可用 primary 时才可为 `partial`；没有 primary 的结果为 `failed`，
取消结果为 `cancelled` 并 quarantine，不得把两者伪装成 partial。内部 canonical
`ActualOutcome.status="partial"` 是 acquisition outcome 事实，不新增 Job `partial` 状态；
非取消 Job 仍终结为 `succeeded` 或 `failed`，取消仍为 `cancelled`。
`resource_job_status.outcomes` 是持久化 Outcome 的脱敏公共投影，不是客户端可回填的
persistence payload。

## 三种内部策略

| 策略 | 可匹配的已核验表示 | 执行前提 | 输出方向 |
|---|---|---|---|
| `direct_file` | 已验证的 PDF、EPUB、视频、音频、图书或其他直接文件 | exact descriptor/readiness/eligibility/Plan binding | 原始文件及服务端 Asset 元数据 |
| `web_materialize` | 普通文章、古诗文页、图文博客、可静态读取的网页 | exact landing-page materialize binding | 安全 HTML、可读 Markdown、元数据、受控同源资产和 ZIP |
| `web_capture` | 必须依赖浏览器执行、且获得显式允许的动态页面快照 | exact declared route；从不自动选择 | 仅在受控 snapshot profile 可用时产生结果 |

Skill 只根据用户目标、资源表示、已核验事实和获取风险形成语义判断，并解释服务端返回
的计划、警告和结果。服务端 Acquisition Router 不能重新“选择”未绑定路线；它只能消费 fresh
Execution binding 中的 exact Provider/strategy/scope，并再次校验大小预算和取消信号。

### 策略选择规则

1. 资源已经被 `resource_inspect` 形成持久化 Resolution/Representation，且服务端 authority
   chain 精确绑定 `direct_file` 时才执行直接文件路线。不能因为文件扩展名或搜索摘要就把未知
   响应当作文件。
2. 普通网页只有在 exact landing-page `web_materialize` 路线已绑定时才执行静态物化。物化过程不执行页面 JavaScript，不把原始页面
   的不可信 DOM 直接作为最终 HTML，而是提取受限 Block IR 后重新生成输出。
3. 只有用户明确要求动态快照，且服务端存在显式允许的受控浏览器配置时，才允许
   `web_capture`。浏览器采集不是 `web_materialize` 的默认 fallback；静态提取失败、页面
   要求认证或遇到策略阻断时，必须返回真实失败/缺口，不得偷偷升级为浏览器绕过。
4. 需要登录、验证码、付费墙、DRM 或其他访问控制的来源，返回认证或策略状态，交给独立
   `session-manager` 或用户合法完成访问。任何策略都不能绕过这些控制。

Skill 不向工具传入内部策略名、URL、路径、命令、浏览器启动参数、Cookie、Token 或本地
文件名。若公开 Plan 只返回容器或风险说明，Skill 只解释这些服务端事实；不能从对话内容
推断一个“已下载”或“可归档”的状态。

## 历史 Provider 兼容与多资产映射

保留旧 `DownloadProvider` 的单文件/列表兼容，不改变调用方的确认流程：

| Provider 返回形状 | 服务端保守映射 |
|---|---|
| 旧单文件 `DownloadResult` | 唯一项为 `primary` |
| 旧有序文件列表 | 首项为 `primary`，其余按来源顺序为 `attachment` |
| 新 enriched batch | 只接受服务端明确给出的角色、顺序、item key 和逐项失败 |

列表映射保持来源顺序，不按文件名推断 subtitle、cover、transcript 或 companion。SmartEdu
课程的来源关系按以下固定规则保留：存在视频时视频为 `primary`，否则取首个明确内容项；
PDF 为 `attachment`，MP3 为 `companion`，只有来源明确标记的封面才为 `cover`。SmartEdu
必须保留逐项失败和原始关系；认证、策略阻断或取消属于整项获取失败，不能生成可用 partial
Bundle。单资源的旧 Provider 仍可生成 singleton primary Bundle。该映射只解释历史 Provider
返回的资产关系，不能选择或替换当前执行的 Provider、strategy、scope、Representation 或
capability route。

## Web Materializer 输出

普通网页的 Job 工作目录使用以下受控布局：

```text
<job-artifact>/
├── index.html
├── content.md
├── metadata.json
├── assets/
│   └── <server-generated-safe-name>.<verified-extension>
└── webbundle.zip
```

`index.html` 是重建后的安全 HTML，`content.md` 是主要可读文本，`metadata.json` 记录服务
端已确认的标题、来源摘要、抓取时间、内容类型、警告和物化状态。`assets/` 只保存经过
策略、MIME 和魔数校验的受控资源；HTML/Markdown 的资源引用必须指向同一 bundle 内的
相对路径，不得保留未经审查的外部脚本、跟踪像素或任意绝对文件路径。

`webbundle.zip` 仍是网页物化的 singleton primary Asset；ZIP 内的 `index.html`、Markdown、
metadata 和内部图片不拆成公开 BundleItem。它作为物理容器存在，但不改变“Bundle 是关系、
不是 ZIP”的领域定义。用户归档时只选择或确认 MCP 返回的 Asset，调用 `resource_archive`
时传递服务端返回的 `asset_id`；Skill 不展开目录、不改名、不移动文件，也不提交本地路径。

其他媒体的伴随 Asset 只有在服务端返回明确的 Bundle 关系和角色时才可解释。归档仍是
Asset-scoped：任何 ready 成员都可以独立归档；用户要求完整 Bundle 时，由 Skill 按服务端
返回的 ready 成员依次归档，不能虚构新的 Bundle 级原子操作。

## 安全与资源预算

所有三种策略都受服务端安全边界约束：

- 网络来源只允许 `http`/`https`。初始 URL、每个重定向目标和最终 URL 都必须逐跳执行
  SSRF 检查，阻断 localhost、私网、链路本地、云元数据和其他策略禁止的地址。
- 响应以流式方式读取，执行单响应、单资产、DOM/文本、资产数量和 bundle 总量上限；超过
  上限时停止并返回结构化失败，不能把大文件放进 Tool JSON 或模型上下文。
- `Content-Type` 只是提示，最终 artifact 还必须通过真实内容魔数/格式校验。MIME、扩展名
  和魔数冲突时拒绝或标记不可用；不把 SVG、脚本或不明主动内容当成普通图片资产。
- 网络调用、解析、资产下载和压缩都响应 Job cancellation；取消后不把不完整文件登记为
  ready Asset，也不能继续生成可归档的假成功结果。服务端同时将未完成 Bundle/Item quarantine。
- 不发送或捕获来源 Cookie、Token、浏览器档案或模型提供的凭据。需要认证时保持
  `AUTH_REQUIRED`/等价结构化状态，并交给独立 session-manager。
- 物化 HTML 通过服务端生成，脚本、事件处理器、危险 URL scheme、外部不受控资源引用和
  不安全的 HTML 结构都不进入最终 bundle。

这些校验发生在 MCP/Job 服务端，Skill 的安全检查只能用于解释和编排，不能替代服务端
重新验证。

## 失败与用户解释

Skill 根据 MCP 的真实状态解释失败，不自行补造降级结果：

- `direct_file` 成功：说明文件类型、大小、校验状态和可用的 Asset；若存在 Bundle，额外
  说明服务端返回的 role/order/completion；不声称已经归档，除非 `resource_archive` 返回成功。
- `web_materialize` 成功：说明已生成 Markdown、HTML 和 ZIP 物理容器，并提示内容可能因
  静态提取、图片策略或页面缺失而不完整；ZIP 作为 singleton primary，不把内部文件说成
  独立 Asset。
- 静态页面是动态空壳、需要认证或被安全策略阻断：说明原因和影响；只有用户显式要求并且
  服务端允许的 `web_capture` 才能作为下一步，不自动启动浏览器。
- 取消、超时、大小超限、MIME/魔数不符或重定向被阻断：保留服务端 Job/Asset/Bundle 事实，
  quarantine 未完成产物；不能把 partial 文件说成 ready，也不能要求用户提供本地路径来绕过
  控制面。进程重启不会自动重放网络副作用，未完成 Job 由服务端终结为 failed/cancelled。

恢复时以 `resource_flow_status`、`resource_job_status` 和 `resource_archive` 的服务端结果
为准。对话记忆、页面标题或模型常识不能替代 Job、Asset、Archive 的权威状态。

## 当前阶段与验收边界

0022 的 348/348 是 AssetBundle 阶段的历史固定夹具快照；0023 随后以 4/4 stdio 和
352/352 全量回归验证跨进程恢复。2026-08-08 的 0024 历史基线进一步通过 8/8 进程级
stdio E2E、374/374 全量回归、39/39 retrieval calibration 和 `compileall`；OpenClaw
`2026.7.1-2` 的 config/status/doctor/probe 也串行通过，精确发现 13 个 Tool，
`diagnostics=[]`。

这些历史证据证明当时本地 Acquisition/AssetBundle、MCP 进程、协议和工具发现链可重复，但仍不等于
默认 Agent 完整自然语言业务回合、真实平台网络、合法生产会话、逐平台 readiness 或多租户
生产隔离已经验收。Skill 只能依据 MCP 返回的权威状态恢复和解释结果，不得把设计规则、
offline fixture 或 doctor/probe 当作真实获取成功。
