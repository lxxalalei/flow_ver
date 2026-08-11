# AGENTS.md

本文件约束在本仓库工作的所有 Agent。除非更深目录存在更具体的 `AGENTS.md`，否则本文件对整个仓库生效。

本仓库同时是专用 OpenClaw Agent 的源码工作区和本地开发工作区，不是教育平台的
生产多租户运行目录。正式凭据、租户状态、下载资产和平台数据必须与源码分离；
`.openclaw-test/` 仅用于临时隔离测试。

## 项目目标

最终产品目标不是复刻旧七个 Skill 或旧六阶段文件流水线，而是让孩子或家长
直接通过自然语言完成一个可信的教育资源闭环：表达模糊需求、获得必要且克制的澄清、
探索合适来源、理解候选差异、明确选择、安全下载并在需要时归档和再次查找。

任务理解使用三个独立部分：`user_role` 表示当前对话者是孩子或家长，
`resource_target` 表示资源给孩子使用或给家长参考，`constraints` 保存其他会影响结果的
用户明示条件。前两项可以未知，且不能相互推导。
设计必须从这个用户结果反推。允许重构、替换或从零重建 active Skill 与 MCP；
`legacy/skill-pipeline-v1/` 只提供领域经验、案例和回归证据，不是接口兼容目标、目录模板
或阶段数量约束。不得为了保留旧实现而牺牲自然对话体验、语义判断质量或服务端安全边界。

工作区只有两个 active 产品部分：

- `skills/learning-resource-flow/`：唯一用户入口和对话编排层。
- `mcp/education-resources/`：Python stdio MCP、领域契约、搜索、下载、任务状态和归档。

其他内容都是工作区控制、文档、测试或历史快照：

- `legacy/skill-pipeline-v1/` 保存迁移前六阶段 Skill 套件，只用于审计、对等测试和显式回滚。
- 未来接入教育平台时，可迁移为远程 Streamable HTTP MCP，并按需增加薄 OpenClaw Plugin。

架构与开发顺序以 `docs/DEVELOPMENT_PLAN.md` 为准。

## 工程硬规则

以下规则优先约束实现方式；新增复杂度的一方承担举证责任。

1. 优先选择能够正确解决问题的最小修改。
2. 不自行发明需求；已有产品、安全、权限和访问控制要求继续有效，但不得在任务之外继续扩展新的安全、反滥用、防篡改、遥测、重试、兼容或 fallback 体系。
3. 没有具体理由，不新增抽象层。
4. 没有明确架构需要，不新增另一个数据真实来源。
5. 不静默截断或丢弃业务数据；容量限制必须有真实来源，并显式暴露截断、分页或失败语义。
6. 不使用兜底逻辑掩盖业务不变量被破坏的问题；fallback 只有在降级行为本身是明确产品需求时才允许。
7. 不为了让测试通过而修改正确的生产行为；测试与业务冲突时先报告冲突并判断哪一方错误。
8. 不使用后端测试、fixture、Service 直调或 MCP probe 作为前端、真实 Agent 或用户流程正确的证明。
9. 小改动之后，不默认运行全部测试；验证范围必须与 diff 和真实回归风险成比例。
10. 实现明确范围内的任务时，不重构无关代码；发现无关问题先记录，除非它阻塞当前验收标准，否则不顺手修。
11. 没有实际执行过的验证，不得声称已经完成；不同验证等级不得相互冒充。
12. 存在不确定性时，先调查，再增加代码。

默认优化顺序：正确业务行为 → 最小必要复杂度 → 可维护性 → 显式失败 → 成本与风险相称的验证。
不要为了架构精巧、理论完整或未来可能扩展而主动增加复杂度。

### 复杂度举证

以下改动默认不允许直接引入：新的 canonical model、projection、duplicated state、同步层、
对简单 API 的额外 adapter/wrapper、trivial persistence 的 repository 抽象、event bus、CQRS、
自定义状态机、compatibility layer、generalized framework、speculative extension point。

确实需要时，必须在任务计划或 Task Spec 中先记录：

```text
Problem:
Why current structure cannot solve it:
Simplest alternative considered:
Why that alternative is insufficient:
New source of truth introduced:
New invariant introduced:
Failure modes introduced:
```

举证不足时，不增加该抽象。新增 source of truth 时必须同时说明所有权、写入边界、与现有权威的关系，以及旧权威是否被删除或降级为 derived view。

## 修改边界

- 顶层 `skills/` 只允许存在 `learning-resource-flow`。不要把 `legacy/` 中的旧 Skill
  复制回顶层，也不要在旧 Skill 中继续开发新平台能力。
- 未经明确任务授权，不得删除 `legacy/`；历史快照可能包含未提交修改和回滚证据。
- 不得提交凭据、Cookie、Token、浏览器档案、下载产物、SQLite 运行库或测试会话数据。
- 测试运行数据只能写入仓库内 `.openclaw-test/` 或测试临时目录；持久本地开发数据
  写入用户级受控目录，正式资源库位置必须由配置或服务端策略决定。
- 不得根据历史交接或文档猜测 `.gitignore` 当前状态；需要新增运行文件前先检查 live `git status --short` 和跟踪状态，不擅自恢复、覆盖或扩大忽略范围。

## 目标目录边界

后续改造优先遵循以下结构：

```text
skills/learning-resource-flow/     # 唯一 active Skill
mcp/education-resources/           # stdio MCP、契约、Adapter 和测试
legacy/skill-pipeline-v1/          # 迁移前快照，不参与正常运行
.openclaw-test/                    # 临时隔离测试数据，不进入版本库
.agent/                            # Agent 计划、约束和交付模板
docs/                              # 架构、开发和运维文档
```

新平台 Adapter 必须进入 `mcp/education-resources/src/education_resource_mcp/adapters/`。
可以参考或抽取 legacy 实现，但 active MCP 不得在运行时导入 `legacy/`。

## 计划管理

- 非平凡但局部的任务，先使用 `.agent/TASK_TEMPLATE.md` 冻结 Goal、Non-goals、业务不变量、变更面、验收标准和最小验证。
- 多步骤任务开始前必须建立简短计划；跨会话、影响多个模块或包含多个 milestone 的任务还要在 `.agent/plans/` 新建计划文件。
- 计划步骤只使用 `pending`、`in_progress`、`completed`、`blocked` 四种状态。
- 同一时间最多一个步骤为 `in_progress`。
- 每完成一个阶段就更新计划，并重新核对原目标、Non-goals、业务不变量、是否引入新抽象/source of truth/fallback/截断、是否出现无关改动和 scope drift。
- 不得静默重写 Goal、Non-goals 或验收标准来匹配已经写出的代码；如果产品目标确实变化，先修改上游产品/路线依据，再调整当前计划。
- 任务完成前，所有本次承诺的步骤必须标记为 `completed`；确实无法完成的步骤标记为 `blocked`，并写明证据、影响和继续所需条件。
- 开发路线图中的未来阶段可以保持“未开始”，但必须与当前执行计划分开，不得伪装为本次已完成工作。

计划格式与模板见 `.agent/plans/README.md`。

## 实现约束

### Skill 层

- Skill 是教育资源任务的语义决策与对话层，不是薄工具路由器。它负责需求理解与证据
  强度、澄清必要性、资源形态判断、搜索策略、候选审查、交互、工具选择、结果解释和
  失败恢复。
- Skill 的任务模型只使用 `user_role`、`resource_target`、目标和显式约束。未知字段保持
  未知，不为补齐模型而追问。搜索方向必须由资源对象、目标和显式约束共同决定，不能
  仅从当前对话者身份推出额外内容方向。
- Skill 的语义设计应从真实用户对话和期望结果重新推导；可以吸收 legacy 中验证有效的
  规则，但不得复制旧 Stage 文件协议、脚本调用方式或多 Skill 调度结构。
- 新设计不得要求模型拼接任意 shell 命令、脚本路径、Node/Python 二进制路径或绝对下载路径。
- 模型不得手工伪造 MCP 业务状态、下载结果或归档结果。
- 只保留一个可发现的用户入口 Skill。active Skill 不包含 Python 执行脚本、Stage
  manifest、下载实现或旧六阶段兼容逻辑。

### MCP 服务层

- MCP 服务端拥有 Flow、Selection、Plan、Job 和 Asset 的权威状态。
- 对外使用不可伪造的 `flow_id`、`resource_id`、`plan_id`、`job_id`、`asset_id`，不得以任意本地路径作为业务标识。
- 有副作用的下载必须采用 `prepare -> 用户确认 -> start` 两阶段流程。
- 长任务必须异步化并返回 `job_id`；同时提供状态查询和取消工具。
- 每个有副作用的调用必须支持幂等键，并在服务端重新校验权限、来源、选择状态和资源状态。
- stdio MCP 是进程边界而不是安全沙箱；进程权限、工作目录、网络出口和环境变量仍需最小化。

### 搜索、下载与归档安全

- 只允许 `http`/`https`，阻断本机、私网、链路本地、云元数据和非预期重定向目标。
- 服务端强制执行域名策略、超时、重试上限、并发限制、内容类型和真实文件格式校验；文件下载以固定数据块流式写入，不设置每资源字节上限。
- 需要认证时必须使用用户或平台合法授权的凭据。
- 归档只接受 `asset_id`，不得接受模型提供的任意文件路径。
- 大文件不得写入模型上下文或 Tool JSON；返回资产 ID、元数据或受控访问地址。

以上是本项目已有明确架构/访问控制要求，不构成 Agent 继续自行增加新安全框架的授权。

## 代码与契约要求

- Python 优先使用标准库和已有依赖；新增依赖前说明必要性并固定兼容范围。
- 修改或新增重要第三方集成前，先确认实际依赖版本、官方 API、已有能力、关键类型/限制、迁移约束和本项目接入点；不要凭记忆发明 API，不为尚不存在的第二个用例提前泛化 wrapper。
- 工具输入输出必须有显式 Schema、版本号、错误码和稳定 ID。
- 业务错误作为结构化结果返回；协议错误和不可恢复错误才抛出异常。
- 修改契约时同步更新文档、Schema、兼容说明和测试。
- 适配器属于服务内部实现，不直接暴露为大量平台级 MCP 工具。
- 领域契约位于 `mcp/education-resources/contracts/`，修改工具时同步更新 Schema、
  错误码、文档和契约测试。
- 不把平台凭据写入 Skill、仓库配置或测试夹具。

## 验证要求

验证是证据，不是产品规格。每次按实际改动和回归风险选择最小充分验证，并在完成报告中区分等级。

- **Level 1 — 小改动**：直接受影响的单元测试、必要的语法/静态检查；默认不跑全量回归。
- **Level 2 — 子系统改动**：受影响 package/module 测试和直接相关 integration。
- **Level 3 — milestone/用户链路改动**：受影响回归、相关 E2E，以及适用时的真实 Agent/用户流程。
- **Level 4 — release/跨切面改动/明确要求**：有具体风险依据时运行全量回归。

运行昂贵测试前先回答：这个 diff 现实中可能造成什么回归；是否有更窄测试能覆盖同一风险；相关代码自该昂贵测试最近一次通过后是否又发生变化。没有充分理由，不运行昂贵套件。

具体要求：

- 文档修改至少检查 Markdown 链接、文件存在性和 `git diff --check`。
- Python 修改至少运行受影响目录的 `unittest`/`pytest`、语法检查和相关 smoke test。
- MCP 工具修改需补充契约测试；具备 OpenClaw 环境后还要按实际风险运行 MCP probe/doctor。
- 下载安全逻辑修改必须覆盖与 diff 直接相关的 SSRF、重定向、流式写入、取消、幂等或非法状态转换测试；不因其中某一项存在就自动要求全仓测试。
- 后端 E2E 不能证明真实 OpenClaw Agent/用户流程；真实链路未执行时必须明确写“未执行真实 Agent/用户流程验证”。
- 如果完整测试因环境、网络或凭据无法运行，执行可行的替代检查并列出剩余风险；不得把替代检查描述成更高等级验证。

## 完成与汇报

每次执行完任务，Agent 的最终回复必须明确说明：

1. 做了什么，哪些关键文件发生了变化。
2. 实际运行了哪些验证，各自证明什么；哪些更高等级验证没有运行。
3. 本次计划是否全部完成；如未完成，逐项说明阻塞。
4. 已知风险、没有执行的动作以及建议的下一步。

使用 `.agent/REPORT_TEMPLATE.md` 的验证等级语义，不得只回复“完成”或省略验证结果。
如果本轮没有修改文件，也必须明确写明“本轮只读，未修改工作区”。
