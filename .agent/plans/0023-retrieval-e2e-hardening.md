# Retrieval E2E Hardening

- 状态：blocked
- 创建日期：2026-08-08
- 完成日期：未完成
- 范围：真实 stdio MCP 回合、跨进程恢复、部分失败、认证恢复、多资源 Acquisition、Archive/Library 与 OpenClaw 环境验收

## 目标与边界

在不访问真实平台、不写入凭据的前提下，先用固定夹具跑通真实 MCP stdio 子进程和 SQLite
跨进程状态链，再执行可用环境中的 OpenClaw doctor/probe 与完整对话。离线 harness 必须调用
公开 13 个工具而不是直接调用 Service；真实 OpenClaw 不可用时明确保留环境门槛，不能用
Python unit test 冒充。

## 步骤

- [x] completed：审计 stdio 客户端、测试夹具、重启/认证/多资源边界和 OpenClaw 环境，冻结最小 E2E 矩阵
- [x] completed：实现可重复的真实 stdio MCP E2E harness，覆盖搜索到归档再检索的完整控制面
- [x] completed：覆盖单视频、混合资源、网页物化、书籍版本、部分失败与多资产 Bundle 场景
- [x] completed：实现真实子进程终止/重启和同 SQLite 恢复，验证无网络副作用自动重放
- [x] completed：实现 AUTH_REQUIRED 后合法会话恢复并由新 Plan/Job 继续，不泄漏凭据
- [x] completed：执行 MCP stdio probe、13 工具/Schema/绑定/幂等/安全断言和完整本地回归
- [x] completed：2026-08-08 当前环境串行执行 OpenClaw config/status/doctor/probe；配置有效、MCP doctor 为 ok、probe 精确发现 13 个 `resource_*` Tool 且无 diagnostics
- [x] completed：更新 Skill、MCP、架构、开发计划和总体规划的 E2E 证据与剩余风险
- [ ] blocked：默认 Agent 的真实 Select → Confirm → Acquire → Archive 闭环与合法平台认证恢复尚未验收；
  真实只读/失败回合和 16 平台 readiness 分级已由 0028 记录，但 0023 不把它们或 stdio fixture
  冒充完整用户闭环

## E2E 矩阵

1. 单视频：Intent -> Search -> Inspect -> Presentation -> Selection -> Confirm -> Download -> Archive。
2. 混合资源：video/article/book 多方向 ResultSet -> 多 Provider -> 多 Bundle -> Archive/Library。
3. 网页：静态 Web Materializer -> singleton ZIP primary -> Archive。
4. 书籍版本：Inspect 后明确 edition，再选择 PDF/EPUB，不按标题猜版本。
5. 重启：中断进程 -> 新 MCP 子进程 -> flow_status/job_status，状态一致且不自动重放网络。
6. 部分失败：一个失败、一个成功；Job lifecycle 与 completion 分离，无假 Asset。
7. 认证恢复：AUTH_REQUIRED 终止当前 Job；合法会话就绪后创建新 Plan/Job 继续。

## 验收条件

- harness 通过 JSON-RPC stdio 调用公开工具，工具集与 catalog 精确为 13，不能直接调用 Service 伪装 E2E。
- 同一数据库跨至少两个 MCP 子进程恢复 Flow/ResultSet/Presentation/Selection/Job/Bundle/Archive。
- 绑定字段、确认令牌、幂等冲突、取消、partial、无 primary、归档和 Library 关系均有失败或成功断言。
- 测试数据只在临时目录；不产生凭据、Cookie、Token、仓库 SQLite、下载产物或网络调用。
- OpenClaw CLI 与 MCP 发现层已通过；只有默认 Agent 完整对话和真实平台边界实际验收后，0023 才能标记完成。

## 2026-08-08 当前环境复验

- `openclaw --version`：`OpenClaw 2026.7.1-2 (0790d9f)`。
- `openclaw config validate --json`：`valid=true`，无 warning。
- `openclaw mcp status --verbose`：`education-resources` 指向当前仓库、持久 venv 和 `resource_*` filter。
- `openclaw mcp doctor education-resources --probe`：`ok`。
- `openclaw mcp probe education-resources --json`：13 个 Tool，`diagnostics=[]`。
- 上述命令必须串行执行；并行执行曾出现 CLI 锁竞争式长时间无输出，不能据此误判 MCP 不可用。

## 2026-08-11 与 0028 的当前衔接

- 0028 已在真实默认 Agent/平台边界完成文章只读路径，以及视频、音频、图书/版本、课程/Bundle、
  混合检索和中断恢复的诚实失败/恢复证据；16 个平台均完成本环境分级和用户文案审计，当前
  `production_ready=fail` 为 `16/16`。
- 公开 stdio 子进程 E2E 为 `8/8`：六条业务/控制面场景加两条重启/认证恢复场景；Selection/Plan
  失效、取消、partial、无 primary、策略拒绝、跨 Flow 归档限制和无副作用重放均已有进程级证据。
- 前一检查点全量 unittest 为 `493/493`；本次 direct-import 变更另有 session-manager `67` 项
  `OK (skipped=5)`、受影响 education bridge/SmartEdu `32/32`、隔离 `compileall`、Skill/Markdown 与
  `git diff --check` 验证。新增测试后的 education 全量回归尚未重跑；上述结果仍不等于真实平台
  Acquisition 成功。
- 当前 OpenClaw 已注册 `session-manager`，education-resources 已配置 standalone store bridge，部署
  runtime 可导入 0.4.0 包，且两个 MCP 的共享 store 配置一致；4 个 session Tool 与原 13 个教育业务 Tool
  均完成 live probe。用户明确授权的 SmartEdu canonical direct import 已保存为 `stored/no_probe`，但 fresh
  真实 Agent Search 返回认证 HTTP 403、0 候选且未到达 Inspect，因此 0028 Step E 继续 blocked；不得
  自动重放当前值，也不得把安装、保存、probe 或离线 AUTH fixture 当成真实会话恢复。
- 0023 继续保持 `blocked`：当前真实文章 Presentation 有两个公开候选，必须先由用户明确选择；
  Prepare 后还要展示 Plan 并获得一次独立确认，才可 Start。用户选择与确认之前不得为了验收制造
  Selection、Plan、Job、Asset 或 Archive。
