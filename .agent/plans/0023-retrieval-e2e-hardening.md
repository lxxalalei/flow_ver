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
- [ ] blocked：本机未发现 `openclaw`；无法执行 doctor/probe 和默认 Agent 完整对话，继续条件为提供已安装并配置的 OpenClaw 环境
- [x] completed：更新 Skill、MCP、架构、开发计划和总体规划的 E2E 证据与剩余风险
- [ ] blocked：根智能体完成本地跨层验收；0023 因真实 OpenClaw 门槛保持 blocked，不把 stdio 固定夹具冒充完整 OpenClaw 验收

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
- 真实 OpenClaw 验收只有在 doctor/probe 和完整对话实际运行后才能标记通过。
