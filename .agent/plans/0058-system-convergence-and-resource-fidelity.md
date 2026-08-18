# 0058 — 系统收敛、能力接通与资源保真

- 状态：pending
- 创建日期：2026-08-18
- 完成日期：未完成
- 范围：`mcp/education-resources/`、`mcp/session-manager/`、Host Web URL Import、Generic Web 资源保存、active 文档/计划、真实 OpenClaw 验收

## Objective

在不恢复旧 Flow / ResultSet / Selection / Plan / Asset / authority / digest 架构的前提下，把当前已经正确的 **Agent / Skill 语义层 + MCP 能力层** 真正接通并收敛成一个可稳定运行的系统：

1. Session 继续保持独立代码职责，但不再为了当前单一消费者维持独立 MCP 进程；
2. Host Web Search 找到已接入平台 URL 后，能回到对应平台的 Inspector / Downloader，而不是一律退化为 Generic Web；
3. 网页“完整保存”和“给模型阅读的正文抽取”分离，避免把模型上下文限制变成资源数据截断；
4. active 文档和计划只描述当前真实架构，不再把旧 Flow / Plan / Asset 规则带回实现；
5. 通过真实 OpenClaw 用户链路证明上述改动解决的是产品问题，而不是只让后端测试通过。

最终目标不是继续扩展平台数量，而是把现有 Search / Import / Inspect / Download / Batch / Archive 跑通、跑稳、提质。

## Non-goals

- 不重写 `learning-resource-flow` 主体；当前 Skill 先冻结，除非真实 OpenClaw 多个 case 重复出现同一种语义退化。
- 不新增 Session Service、Auth Gateway、Credential Authority、Login Transaction、Workflow Engine 或其他认证平台抽象。
- 不新增 URL Resolver Framework、Provider Discovery Framework、Capability Registry 第二真实来源；URL 平台识别保持薄且明确。
- 不恢复 `prepare -> confirm -> start`、confirmation token、Asset/AssetBundle、eligibility、authority/binding/digest 链。
- 不为了迁移建立长期 compatibility layer；旧独立 session-manager 在迁移完成后删除，而不是双轨长期维护。
- 不把 Web Resource 改造成浏览器克隆器；目标是保存有价值的源内容与可读表示，不追求离线复刻任意动态应用。
- 不在本计划中新增无真实需求的平台 Adapter。
- 不用全量测试替代针对改动风险的最小充分验证。

## Business invariants

1. Agent / Skill 继续负责需求理解、搜索任务设计、来源职责、候选判断、Gap、停止、用户选择和归档分类。
2. MCP 只负责真实平台能力、IO、副作用和真实长任务所需的 Job 状态。
3. `resource_id` 继续是进程内临时句柄；稳定资源身份仍是 URL / 平台原生稳定 ID。
4. `job_id` 只用于真实下载/Batch 长任务，不升级成用户研究流程状态。
5. 用户已经明确选中对象并要求下载时直接执行，不制造形式化二次确认。
6. Session Tool 不是 Search / Download 的固定前置步骤；只有真实 `AUTH_REQUIRED` 或用户主动管理登录态时才进入 Session 能力。
7. SmartEdu 公共 Search / Catalog 继续匿名；公共访问失败不得自动通过重放 token 解决。
8. `annas-archive` 当前继续表示 Libgen 镜像支持的匿名图书发现/获取能力，不引入 Anna 会员登录链。
9. exact Provider 失败后返回真实失败，不静默切换不等价 Provider。
10. 完整 Batch 默认枚举到来源真实结束；分页只控制 Tool Result，不截断磁盘结果。
11. 网页用于模型判断的抽取可以有显式阅读预算；用户资源本体不得因为模型上下文预算被静默裁掉。
12. 任何必须存在的容量/协议限制都应有真实技术理由，并以显式失败或显式 `truncated` 事实暴露；不增加隐藏数据丢弃。

## Current architecture

当前事实仍以 `docs/CURRENT_ARCHITECTURE.md` 为准：

```text
Main Agent / learning-resource-flow
        │
        ├── Host Web Search
        │
        ├── education-resources MCP
        │      Search / Import URL / Inspect / Download / Batch / Archive
        │
        └── session-manager MCP
               Session save / status / login guide / delete
```

当前主要断点：

### A. Session 拆成了独立 MCP，但目前只有一个实际消费者

`session-manager` 主要承担浏览器已有登录态的筛选、保存、查询和删除；`education-resources` 并不是通过 MCP 调用它，而是通过 `session_bridge.py` 读取同一 SessionStore。

因此当前独立进程额外产生：

- 两个 Python package / stdio MCP；
- 两份部署配置；
- shared data dir 一致性要求；
- `session_bridge.py`；
- standalone store 与 local fallback 的歧义；
- “session-manager 写 A，education-resources 读 B”的配置失败面。

代码职责仍应独立，但当前没有足够证据证明需要独立 MCP 进程边界。

### B. Host Web Search → `resource_import_url` 会丢失平台身份

当前 `resource_import_url()` 对任意 URL 都建立 `platform="generic"`。

因此 Host Web Search 即使找到 Bilibili / SmartEdu / Zhihu 等已接入平台的具体 URL，也可能进入 Generic Inspector / Web Materializer，而不是对应平台 Inspector / Downloader。

### C. Generic Web 当前更像“受限正文清洗器”，不是资源保真保存

当前 `web_blocks.py` / `web_materializer.py` 会：

- 丢失或弱化链接语义；
- 删除视频、音频、iframe、SVG、canvas 等节点；
- 只允许同源图片，现实 CDN 图片容易丢失；
- 对 HTML、DOM、正文字符、block、表格、列表、代码、图片数量/总大小使用固定上限；
- 超过部分预算时直接裁剪正文、列表或表格。

其中“给模型阅读多少”和“归档资源保存多少”目前没有真正分开。

### D. active 文档/计划存在架构漂移

`0029-retrieval-benchmark-release-gate.md`、`0041-web-content-extraction-benchmark.md` 等仍包含旧 ResultSet / Plan / Asset / prepare-confirm-start 等历史描述；`README.md`、`DEVELOPMENT_PLAN.md` 也与当前两个 MCP、10 个资源 Tool、现有 Archive 能力存在不同程度滞后。

这些文件会被后续 Coding Agent 读取，可能反向把已删除设计带回实现。

## Expected change surface

### Likely to change

```text
mcp/education-resources/
  src/education_resource_mcp/server.py
  src/education_resource_mcp/service.py
  src/education_resource_mcp/session*/
  src/education_resource_mcp/search.py / URL platform identification helper
  src/education_resource_mcp/inspection_registry.py
  src/education_resource_mcp/acquisition/web_*.py
  tests/

mcp/session-manager/                  # 迁移完成后删除

README.md
TOOLS.md
AGENTS.md                         # 仅当当前事实变化需要同步
CONTEXT.md / SOUL.md / USER.md    # 仅同步事实，不扩写流程
docs/CURRENT_ARCHITECTURE.md
docs/DEVELOPMENT_PLAN.md
.agent/plans/
```

### Should not change without a concrete failure

```text
skills/learning-resource-flow/SKILL.md
skills/learning-resource-flow/references/*
library taxonomy
Batch 完整枚举语义
Job 文件状态模型
现有平台 Search query 语义
```

## Acceptance criteria

### AC-01 — Session 部署边界收敛

- OpenClaw 只需配置一个 `education-resources` MCP 即可完成资源能力和 Session 管理。
- Session Tool 仍然是独立职责的一组 Tool，但由同一个 MCP server 暴露。
- SessionStore 只有一份真实存储路径，不再存在 standalone/local 双路径和 `session_bridge.py`。
- 删除独立 `mcp/session-manager/` 后，没有第二套 SessionStore 实现残留。
- SmartEdu / Bilibili / Douyin 等现有 Session 行为不因合并而改变业务语义。

### AC-02 — SessionStore 简化且不预先丢浏览器数据

- 删除只为独立 MCP 重放写入而存在、且没有真实用户需求的 operation ledger / fingerprint / revision/idempotency 复杂度。
- 保留真正必要的原子写入、最小凭据筛选和本机凭据保护。
- 浏览器宽捕获先按平台规则筛选，再对真正准备持久化的 canonical session 做容量/格式校验；不因为整个 localStorage/cookie snapshot 较大而在筛选前失败。
- 不静默截断 Cookie/Token；不合法或不可保存时返回明确错误。

### AC-03 — Host Web URL 能进入专门平台能力

- `resource_import_url()` 对明确可识别的已接入平台 URL 保留/恢复对应 `platform_id`。
- 至少验证 Bilibili、Zhihu、SmartEdu 这类代表性 URL 能走对应 Inspector；未知普通网页仍走 `generic`。
- 平台识别只基于明确 hostname / URL pattern；不能确定时不猜。
- 不建立新的 Registry/Resolver framework，仅使用一层可读的薄识别逻辑。

### AC-04 — Web Resource 保存与模型抽取分离

对普通静态/服务端渲染学习网页：

- 下载 Job 保存原始源响应或等价可追溯 source snapshot，不把 Block IR 当唯一资源本体。
- `index.html` / `content.md` 等可读表示来自抽取结果，但其阅读预算不影响 source snapshot 的完整性。
- 抽取器显式记录是否截断；任何模型阅读截断不能被描述成“完整网页已保存”。
- 保留正文中的重要链接语义。
- 对常见公共 CDN 图片允许在现有 URL/DNS 网络边界下抓取，不再机械要求 same-origin；失败图片保留原引用/明确缺失事实，不伪造成功。
- 对视频/音频/iframe/SVG 等复杂内容至少保留有价值的引用或占位元数据，而不是无痕删除。
- 大型页面如果因真实下载/磁盘/协议约束无法完整保存，应显式失败或报告不完整，不静默裁成一个看似完整的资源。

### AC-05 — active 文档不再反向污染实现

- `CURRENT_ARCHITECTURE.md`、`README.md`、`TOOLS.md`、`DEVELOPMENT_PLAN.md` 与最终实际部署边界一致。
- active plans 不再把 Flow / ResultSet / Selection / Plan / Asset / prepare-confirm-start 当现行架构。
- `0029` 与 `0041` 的仍有效目标由本计划吸收；旧版本移入 archive 或明确 superseded，不再作为默认实施依据。

### AC-06 — 真实 OpenClaw 闭环

至少记录并完成：

1. 一个 Host Web Search 找到已接入平台 URL → Import → 专门 Inspector/Downloader → 实际文件的链路；
2. SmartEdu 保存过 session 的环境下仍能匿名公共 Search；
3. Anna/Libgen 图书链不触发登录；
4. 一个需要真实登录态的平台在合并 Session Tool 后能完成“AUTH_REQUIRED → 用户登录/捕获 → 保存 → 重试资源能力”；
5. 一个 Generic Web 学习网页能保存 source snapshot + 可读表示，并人工检查主要正文/图片/链接保真度；
6. 一个此前易 compaction 的较长任务仍由 0028 记录是否完整完成。

后端 E2E 不能替代这些验收。

## Complexity exceptions

默认：无新的体系级抽象。

允许保留/新增的最小结构只有：

### 1. `session/` 内部模块目录

Problem: Session 代码需要与资源 Adapter 分离职责，但不值得独立 MCP 进程。

Simplest solution: 把现有 Store/平台规则/本机保护迁入 `education_resource_mcp/session/`，由同一 server 暴露 Session Tool。

New source of truth: 无；SessionStore 反而从两套部署路径收敛为一份。

### 2. 薄 URL → platform 识别函数

Problem: Host Web URL import 丢失已知平台身份。

Simplest solution: 明确 host/path pattern 映射；未知返回 `generic`。

New source of truth: 不建立独立 Registry；优先复用现有 platform id，映射仅负责 URL 识别。

### 3. Web source snapshot

Problem: 当前抽取预算会改变资源本体。

Simplest solution: 下载层先保存源响应，再基于该响应生成模型/用户可读衍生表示。

New source of truth: 源响应文件是下载 Job 的一个真实 artifact，不建立 Resource database 或 Asset 状态机。

## Milestones

### M0 — 文档与计划先收敛

- [ ] in_progress：创建本计划，冻结上述 Objective / Non-goals / AC。
- [ ] pending：更新 `docs/DEVELOPMENT_PLAN.md`，把当前路线调整为“边界收敛 → 接通 → Web 保真 → 真实验收”。
- [ ] pending：将旧 `0029` / `0041` 有效目标吸收到本计划，旧文件移入 archive 或明确 superseded。
- [ ] pending：检查 README / TOOLS / CONTEXT / AGENTS 是否仍有与当前事实冲突的文字；只修事实，不提前写未来实现为已完成。

Validation: Markdown link / active-plan consistency；不运行 Python 测试。

### M1 — 把 Session 合回 education-resources MCP

- [ ] pending：把 `session-manager/src/session_manager/` 中仍需要的 Store、平台配置、本机保护迁入 `education_resource_mcp/session/`。
- [ ] pending：把四个 Session Tool 合并到 `education-resources` server，保持 Tool 语义清楚，避免成为 Search 前置流程。
- [ ] pending：让资源 Adapter 直接读取同一 SessionStore；删除 `session_bridge.py` 和 standalone/local 双 store 路径。
- [ ] pending：删除独立 `mcp/session-manager/` package、安装说明和环境变量。
- [ ] pending：同步 Tool schema 和 README。

Validation:

- Session save/status/delete/login-guide targeted tests；
- SmartEdu/Bilibili/Douyin 直接读取同一 Store 的 integration；
- MCP stdio tool-list / schema probe；
- 不跑全仓。

Milestone checkpoint: 如果为了合并出现 compatibility proxy、双写 Store、跨 MCP RPC，判定 scope drift，回退到更简单方案。

### M2 — SessionStore 去掉没有兑现价值的复杂度

- [ ] pending：删除公共 `idempotency_key` 与 operation ledger / fingerprint / revision replay 逻辑，除非真实 OpenClaw 写入语义证明它仍有必要。
- [ ] pending：保留原子文件写入、必要文件权限、Windows DPAPI 和平台字段筛选。
- [ ] pending：调整浏览器 capture 处理顺序为“识别/筛选需要字段 → 校验 canonical session → 保存”。
- [ ] pending：逐项审计 `MAX_*`；只有平台/协议/存储真实边界保留，且不得静默截断。

Validation:

- 大 localStorage + 少量有效 token 的 SmartEdu capture；
- 大量无关 Cookie + 少量有效 Cookie 的平台 capture；
- malformed / expired / wrong-domain 负例；
- Windows DPAPI 路径用现有 targeted test，不新增通用安全框架。

### M3 — 接通 Host Web Search → 专门平台 Import

- [ ] pending：实现薄 URL platform recognition。
- [ ] pending：`resource_import_url()` 使用识别结果构造资源，而不是无条件 `generic`。
- [ ] pending：验证已知平台 URL 的 Inspector/Downloader route；未知 URL 保持 Generic。
- [ ] pending：如果某平台 URL 还需要最小稳定 ID，从 URL 本身提取；不重新主题搜索。

Validation:

- Bilibili URL → bilibili inspector；
- Zhihu URL → zhihu inspector；
- SmartEdu URL → smartedu inspector；
- 普通机构网页 → generic inspector；
- known platform download 路由至少做一个 integration。

### M4 — Web Resource benchmark 与 source/extraction 分层

- [ ] pending：先使用真实学习网页样本建立小型 benchmark，不先引入新 extractor 框架。
- [ ] pending：样本至少覆盖：长文本、图文/CDN 图片、表格/列表、代码、PDF 链接、嵌入视频/iframe、复杂导航页。
- [ ] pending：对当前 `web_blocks.py` 记录正文召回、结构、链接、图片、复杂嵌入和截断问题。
- [ ] pending：比较成熟 extractor 或浏览器已有能力；生产最终只选一个主抽取路径，不做长期多 extractor fallback chain。

Validation: 人工 gold + 同页对比；不以“解析不报错”作为质量结论。

### M5 — Web Resource 保真实现

- [ ] pending：下载 Job 保存 source snapshot。
- [ ] pending：从 snapshot 生成 sanitized HTML / Markdown / metadata 等衍生表示。
- [ ] pending：链接成为保留语义；公共 CDN 图片在受控网络请求规则下允许抓取。
- [ ] pending：复杂媒体节点保留引用/元数据。
- [ ] pending：模型阅读预算与 source snapshot 完整性彻底分离。
- [ ] pending：对无法完整保存的情况给出显式 incomplete/failure 事实。

Validation:

- 0041 benchmark 样本回归；
- 下载目录人工检查；
- archive 后文件仍可打开并追溯 source URL；
- 不运行与 Web 无关平台全量测试。

### M6 — active 文档最终对齐

- [ ] pending：更新 `CURRENT_ARCHITECTURE.md` 为单 MCP + 内部 Session 模块的真实架构。
- [ ] pending：更新根 README、TOOLS、DEVELOPMENT_PLAN 和相关 OpenClaw 工作区说明。
- [ ] pending：删除不存在的 standalone session-manager 安装/配置路径。
- [ ] pending：归档已被本计划替代的旧计划，更新 archive 索引。

Validation: 链接、目录、Tool 名称、环境变量和实际代码树一致。

### M7 — 真实 OpenClaw 验收

由 `0028-real-openclaw-platform-e2e.md` 记录真实用户证据，本计划不自行用后端 probe 冒充验收。

优先顺序：

1. Host Web → Bilibili 或另一个专门平台 → Download；
2. SmartEdu 公共 Search + 一个真实具体资源；
3. Anna/Libgen 匿名图书；
4. 一个确实需要登录的平台 Session 链；
5. Generic Web source snapshot；
6. Douyin creator 长任务/compaction 回归。

只有这些关键链路稳定后，才恢复平台扩展或继续给 Skill 增加规则。

## Decision log

### Decision 001 — Session 代码独立，但 MCP 进程不独立

- Context：当前 session-manager 主要只是 SessionStore 管理入口，只有 education-resources 一个实际消费者。
- Options considered：继续两个 MCP；合并全部 Session 代码到资源逻辑；合并 MCP 但保留 session 内部模块。
- Chosen option：合并 MCP 进程边界，保留 `session/` 模块职责边界。
- Why：删除 shared-store coordination、第二 package 和第二 stdio server，同时仍避免 Cookie/Token 逻辑污染资源 Adapter。
- Complexity introduced：无新增体系；预计净删除复杂度。

### Decision 002 — Web Import 先恢复平台身份，不引入 Resolver Framework

- Context：Host Web 已成为通用发现层，但 Import 当前无条件 generic。
- Chosen option：最小 hostname/path platform recognition。
- Why：直接修断链；不需要新服务或 Registry。

### Decision 003 — Web 保存和模型抽取是两个不同问题

- Context：当前 Block IR 的阅读/安全预算会裁掉最终资源内容。
- Chosen option：source snapshot 先落 Job artifact，抽取结果作为衍生表示。
- Why：模型上下文可以有限，但用户下载的资源不能因此变成不完整副本。

### Decision 004 — Skill 暂时冻结

- Context：当前主要问题来自能力断链、平台事实和网页保真，不是缺少更多语义规则。
- Chosen option：本计划默认不修改 Skill；只有真实 OpenClaw 多 case 重复出现同一种语义错误才单独变更。
- Why：防止把新的 Search/Coverage 规则再次固化成机械流程。

## Validation matrix

| Validation | Required stage | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted unit | M1-M5 | 直接改动行为 | 真实 Agent 使用正确 |
| subsystem integration | M1-M5 | Store / Import / Inspector / Downloader 接通 | OpenClaw 不会选错工具 |
| MCP stdio schema probe | M1/M6 | Tool 暴露与 schema 正确 | 真实用户闭环 |
| Web benchmark | M4/M5 | 内容保存/抽取质量 | 所有网页都可高保真保存 |
| real OpenClaw user flow | M7 | Agent + MCP + 平台真实闭环 | 全平台全部场景 |
| full regression | release only | 跨切面回归 | 不能替代真实业务验收 |

## 结果

尚未实施。本文件只冻结接下来一轮系统收敛的目标、顺序和边界。