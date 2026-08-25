# AGENTS.md

本文件约束在本仓库工作的所有 Agent。除非更深目录存在更具体的 `AGENTS.md`，否则本文件对整个仓库生效。

本仓库同时是专用 OpenClaw Agent 的源码工作区和本地开发工作区，不是生产多租户平台。正式凭据、下载资产、平台会话和用户运行数据必须与源码分离；`.openclaw-test/` 仅用于临时隔离测试。

## 项目目标

最终产品目标是让用户直接通过自然语言完成可信的教育/学习资源闭环：表达需求、必要且克制的澄清、探索合适来源、判断候选、明确选择、获取真实资源，并在需要时归档。

当前架构以 `docs/CURRENT_ARCHITECTURE.md` 为准。旧 Flow / ResultSet / Presentation / Selection / Plan / Asset / authority / digest 等设计只保留在 Git 历史或 legacy 中，不是 active 兼容目标。

当前 active 产品部分只有：

- `skills/`（SKILL.md + references + examples）：唯一用户入口和语义决策层；
- `mcp/education-resources/`：唯一 MCP，提供资源能力和辅助 Session Tool。

`legacy/skill-pipeline-v1/` 只用于审计、参考和显式回滚，不参与正常运行。

## 工程硬规则

以下规则优先约束实现方式；新增复杂度的一方承担举证责任。

1. 优先选择能够正确解决问题的最小修改。
2. 不自行发明需求；已有产品、安全、权限和访问控制要求继续有效，但不得在任务之外扩展新的安全、反滥用、防篡改、遥测、重试、兼容或 fallback 体系。
3. 没有具体理由，不新增抽象层。
4. 没有明确架构需要，不新增另一个数据真实来源。
5. 不静默截断或丢弃业务数据；容量限制必须有真实来源，并显式暴露分页、截断或失败语义。
6. 不使用兜底逻辑掩盖业务不变量被破坏的问题；fallback 只有在降级行为本身是明确产品需求时才允许。
7. 不为了让测试通过而修改正确的生产行为；测试与业务冲突时先判断哪一方错误。
8. 不使用后端测试、fixture、Service 直调或 MCP probe 冒充真实 Agent / 用户链路验证。
9. 小改动之后不默认运行全部测试；验证范围必须与 diff 和真实回归风险成比例。
10. 不重构无关代码；发现无关问题先记录，除非它阻塞当前验收标准。
11. 没有实际执行过的验证，不得声称已经完成。
12. 存在不确定性时，先调查，再增加代码。

默认优化顺序：正确业务行为 → 最小必要复杂度 → 可维护性 → 显式失败 → 成本与风险相称的验证。

### 复杂度举证

以下改动默认不允许直接引入：新的 canonical model、projection、duplicated state、同步层、对简单 API 的额外 wrapper、trivial persistence 的 repository 抽象、event bus、CQRS、自定义工作流状态机、compatibility layer、generalized framework、speculative extension point。

确实需要时先说明：

```text
Problem:
Why current structure cannot solve it:
Simplest alternative considered:
Why that alternative is insufficient:
New source of truth introduced:
New invariant introduced:
Failure modes introduced:
```

举证不足时，不增加该抽象。

## 修改边界

- 顶层 `skills/` 直接放置 active Skill（SKILL.md、references、examples），不再有二级 Skill 目录；不要把 legacy Skill 复制回来。
- 未经明确授权，不删除 `legacy/`。
- 不提交凭据、Cookie、Token、浏览器档案、下载产物、SQLite 运行库或测试会话数据。
- 测试运行数据只写入 `.openclaw-test/` 或测试临时目录；正式运行数据使用用户级受控目录。
- 不根据历史交接猜测当前工作区状态；修改前以 live 仓库事实为准。

## 计划管理

- 非平凡局部任务先冻结 Goal、Non-goals、Acceptance Criteria；多步骤任务建立简短计划。
- 计划步骤只使用 `pending`、`in_progress`、`completed`、`blocked`；同一时间最多一个 `in_progress`。
- 每完成一个阶段重新核对目标、范围、是否引入新抽象/source of truth/fallback/截断以及是否发生 scope drift。
- 不得静默重写目标或验收标准来迁就已经写出的代码。

## Skill 层

Skill 是教育资源任务的语义决策层，不是 MCP 说明书，也不是固定工具流水线。

Skill / Main Agent 负责：

- 理解用户目标、资源实际使用者和显式约束；
- 判断哪些问题值得澄清；
- 设计互补的搜索任务和来源职责；
- 判断候选是否有用、是否存在内容 Gap 或 Coverage Gap；
- 决定继续搜索、停止、Inspect 或让用户选择；
- 理解用户实际选中了哪个资源；
- 判断是否存在明确下载意图；
- 决定归档的语义分类。

Skill 不负责复制 MCP 参数表、返回字段、Provider 内部实现、Job 文件结构或平台 Registry。运行时 Tool schema 和真实返回是能力契约的事实来源。

不得把正常用户行为重新建模成 Flow、Presentation、Selection、Plan、eligibility、authority、binding、digest 等持久状态。

当前 Skill 先保持稳定；单个平台失败、登录问题、URL 路由或网页保存质量应优先修 MCP，不向 Skill 继续堆平台实现规则。

## education-resources MCP

`education-resources` 是能力和 IO 数据面，不是资源工作流后端。

当前 12 个 Tool 分为两组：

资源能力：Search、Expand、Import URL、Inspect、Download、Job Status/Cancel/Read、HTML Design、Archive。

Session 辅助能力：Session Status、Session Manage（save/delete）。

状态边界：

- `resource_id` 是当前 MCP 进程内的临时操作句柄，不持久化；
- 真正稳定的资源身份是 URL、平台原生稳定 ID 等；
- `job_id` 只为真实 Download/Expand 长任务提供持久运行身份；
- SessionStore 只持久化平台真正需要的登录态；
- 不持久化 Flow、Selection、Plan、Asset、Outcome 或证明链。

用户已经明确选择资源并要求下载时，可直接调用下载能力，不增加 `prepare -> confirm -> start` 形式化二次确认。成功与否只依据真实 Job/文件结果。

HTML Design 只在用户明确要求视觉优化时使用。Agent 依据有界设计上下文产生 DesignSpec；MCP 必须原样保留完整清洗正文并同步真实文件记录，不允许模型正文替代 `content.md`。

Expand 的读取分页只控制单次 Tool Result，不得变成完整枚举的数据上限。平台枚举必须依据真实终止信号，不得偷偷增加条目或分片上限。

归档由 Agent 决定分类，MCP 只移动下载 Job 已产生的真实文件；不要恢复 ArchiveRecord、AssetBundle 或 archive digest/version 状态链。

## Session 边界

Session 是 `education-resources` 内部的辅助能力，不再使用独立 `session-manager` MCP、`session_bridge.py` 或第二份 Store。

- 用户自己完成登录；Agent 不索取或代填密码、验证码、短信码或 MFA。
- 浏览器捕获结果直接交给 `resource_session_manage(action=save)`，由 MCP 按平台域名/字段规则先筛选，再只保存 canonical Cookie/Token/storage key。
- Agent 不手工拼 Cookie Header 或 canonical Token。
- 只有用户明确授权并主动提供合法取得的 canonical Cookie/Token 时，才可直接导入。
- Session Tool 不是 Search / Download 前置步骤；只有真实 `AUTH_REQUIRED` 或用户主动管理会话时才使用。
- Windows 本机凭据保护、原子写入和必要 probe 可以保留；不要重新加入 operation ledger、idempotency fingerprint/revision 或认证工作流状态机。

SmartEdu 公共 Search / Catalog 必须保持匿名；公共网络拒绝不得通过重放 token 自动处理。LibGen 不进入 Session 管理。

## Host Web Import

普通 Web 发现由宿主 Web Search 完成。具体 URL 进入 `resource_import_url` 后，只对明确的已知 URL 形态恢复专门平台身份；未知或模糊 URL 保持 `generic`。

不要把这个桥接扩展成第二套 Capability Registry / Resolver Framework。新增 URL pattern 必须对应一个真实已接入 Inspector/Downloader 和实际用户需求。

## Generic Web Resource

网络获取继续由现有 `BoundedWebFetcher` 负责。Web Materializer 的职责是：

```text
fetch 成功的 HTML -> source.html
source.html -> Trafilatura -> index.html / content.md / metadata.json
```

原则：

- 原始 source snapshot 与正文抽取分离；
- 抽取失败不得删除已成功取得的 source；
- 不继续扩展自研 Block IR；
- 当前不引入 Monolith / SingleFile / ArchiveBox 或多 extractor fallback；
- 如果真实需求以后要求自包含离线还原，再单独评估，不提前搭框架；
- 真实 HTTP 响应大小上限可以显式失败，但不能静默裁成“完整资源”。

## 搜索、下载与归档边界

保留直接保护真实能力正确性的必要检查：

- URL/本地路径合法性；
- 平台实际登录态；
- Provider 必须产生真实文件；
- exact Provider 路由；
- 下载和 Batch 取消；
- 下载器实际需要的格式/MIME 校验；
- 平台明确存在的身份格式要求。

不新增与真实业务无关的证明链、哈希绑定、任意业务数据截断或“安全起见”的数据丢弃。大结果使用 Job/文件/分页承载，不把完整大数据塞进模型上下文。

## Tool 与契约要求

- Tool 名称、description 和 input schema 应足以让模型理解能力、使用时机和参数。
- 不要求每个业务对象都有永久稳定 ID；只有真实需要跨进程/跨任务定位的对象才使用稳定身份。
- 业务失败应保留真实错误码和可重试事实；不要把 Adapter 业务错误伪装成 crash，也不要隐藏真实失败做成功 fallback。
- 修改第三方平台集成前，先确认实际接口、当前实现和真实返回，不凭记忆发明 API。
- 适配器属于服务内部实现，不因为新增平台就机械增加平台级 MCP Tool。

## 验证要求

验证是证据，不是产品规格。每次按实际改动和回归风险选择最小充分验证：

- 小改动：直接受影响的单元测试、语法/静态检查；
- 子系统改动：受影响 package/module 测试和直接相关 integration；
- Tool schema 变化：MCP stdio/tool probe；
- 用户链路改动：相关 E2E，并在适用时做真实 OpenClaw Agent/用户流程；
- 只有 release、跨切面高风险改动或明确要求时才考虑全量回归。

运行昂贵测试前先回答：这个 diff 现实中可能造成什么回归，是否有更窄测试覆盖同一风险。

后端 E2E 不能证明真实 OpenClaw Agent/用户流程；真实链路未执行时必须明确说明。

## 完成与汇报

每次任务完成后明确说明：

1. 做了什么、哪些关键文件变化；
2. 实际运行了哪些验证、分别证明什么；
3. 哪些更高等级验证没有运行；
4. 已知风险、阻塞项和下一步。
