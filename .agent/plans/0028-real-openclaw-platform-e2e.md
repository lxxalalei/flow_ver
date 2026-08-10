# 0028 Real OpenClaw and Real Platform E2E

- 状态：pending
- 创建日期：2026-08-08
- 完成日期：未完成
- 范围：真实 OpenClaw 默认 Agent、唯一入口 Skill、当前 13 个 MCP Tool、真实 stdio MCP、平台 readiness、合法会话、Search → Inspect → Present → Select → Confirm → Acquire → Archive → Recover 全链路
- 前置条件：[`0025 Platform Capability Contract Alignment`](archive/0025-platform-capability-contract-alignment.md) 已完成；[`0027 Platform Acquisition Enablement`](0027-platform-acquisition-enablement.md) 必须先完成受测平台的正式能力接入
- 关联计划：[`0023 Retrieval E2E Hardening`](0023-retrieval-e2e-hardening.md)；本计划通过前，0023 的真实 Agent/平台阻塞项不得关闭

## 目标

证明真实 OpenClaw 默认 Agent 能从自然语言出发，使用当前工作区唯一入口 Skill 和同一套
13 个 `resource_*` Tool 完成可信教育资源闭环，并逐平台记录真实部署、网络、认证、检查、
获取和策略事实。固定 fixture、直接调用 Service、MCP probe 或 Adapter 已注册都不能替代
真实 Agent 回合，也不能被解释为平台 production-ready。

## 硬边界

- 不在 0027 完成受测平台的正式能力接入前开始对应真实 Agent/平台验收，避免用未接入或不稳定的能力链生成错误证据。
- 不新增第 14 个 MCP Tool，不恢复 legacy Skill，不让 Agent 拼接 shell、脚本、二进制或路径。
- 所有副作用继续执行 `prepare -> 用户明确确认 -> start`；不得自动确认或重放网络副作用。
- 认证只使用用户/平台合法授权的 session-manager/SecretRef；不得把 Cookie、Token、凭据、
  浏览器档案、SQLite、下载资产或真实平台数据写入仓库。
- 不绕过验证码、登录、付费墙、DRM、robots/访问控制或版权/策略边界。
- 不以增加超时、盲目重试、降低 SSRF/重定向/大小/MIME/magic 校验或静默 generic fallback
  换取“通过”。失败必须保持真实结构化状态。
- OpenClaw 命令串行执行；先区分环境锁、进程、网络、认证、策略与产品功能失败，再决定动作。

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

- [ ] pending：A. 复核 0025 completion evidence，冻结本次 OpenClaw、MCP、Skill、catalog、capability registry 与数据库 migration 基线
- [ ] pending：B. 串行执行 OpenClaw 环境预检，证明当前工作区、唯一 Skill、13 Tool、schema/catalog、仓库外运行目录与凭据边界正确
- [ ] pending：C. 建立不含生产凭据的真实 Agent 证据采集模板和逐平台 readiness 记录，先执行无需认证平台
- [ ] pending：D. 执行文章、网页物化、视频、音频、图书/版本、课程/Bundle、混合检索、恢复八类自然语言 Agent 回合
- [ ] pending：E. 在合法会话可用的平台验证 AUTH_REQUIRED → session ready → 新 Plan/Job 恢复；不可用平台保留精确 blocked/unsupported 事实
- [ ] pending：F. 验证中断、重启、幂等、Selection/Plan 失效、取消、partial、无 primary、策略拒绝与归档限制
- [ ] pending：G. 逐平台完成 readiness 分级与用户文案审计；只有完整证据通过的平台才可标 `production_ready`
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

## 真实 Agent 对话矩阵

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

## 结果

- 尚未开始；0025 已完成，当前等待 0027 完成受测平台的正式能力接入。
