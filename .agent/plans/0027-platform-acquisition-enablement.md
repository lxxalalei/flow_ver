# 0027 Existing Platform Acquisition Enablement

- 状态：in_progress
- 创建日期：2026-08-10
- 完成日期：未完成
- 范围：`mcp/education-resources` 中现有 Bilibili、Douyin、Ximalaya、Anna's Archive 下载实现与通用浏览器捕获机制的正式能力接入
- 前置计划：[`0025 Platform Capability Contract Alignment`](archive/0025-platform-capability-contract-alignment.md)（completed）
- 后续验收：[`0028 Real OpenClaw and Real Platform E2E`](0028-real-openclaw-platform-e2e.md)
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

- [ ] in_progress：A. 审计现有 Provider、Inspector、搜索候选、依赖、认证、网络与内容校验边界，冻结逐平台接入矩阵。
- [ ] pending：B. 设计并更新 Capability Descriptor、runtime readiness inventory、provider registration 与版本兼容策略。
- [ ] pending：C. 修正 Provider 的安全、依赖、认证和结构化错误缺口，并接入默认 ResourceService。
- [ ] pending：D. 补齐逐平台 Resolution/Representation 到 Plan/Execution exact binding 的契约与生命周期测试。
- [ ] pending：E. 运行受影响单测、契约/Schema、compile、stdio/OpenClaw 可行 smoke，并由根 Agent 审查差异。
- [ ] pending：F. 更新架构、MCP 文档和 0028 E2E 边界与交付结果；active Skill 本阶段保持不变，真实网络或合法会话不足的项记录为后续真实 E2E，而不伪造 production-ready。

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

- 逐平台 Provider 单测：输入绑定、认证、依赖、取消、大小、域名/重定向、MIME/magic、结构化失败。
- Capability/Registry：descriptor digest、版本、readiness、exact provider/scopes、fallback 全关闭。
- Service 生命周期：Search/Inspect/Present/Select/Prepare/Start/Job/Asset，验证不可变 authority binding。
- 受影响 unittest、`compileall`、契约与 Markdown 链接、`git diff --check`。
- 仅在合法、无敏感信息且不会绕过访问控制时执行真实网络/OpenClaw smoke；否则留给 0028 Real E2E。

## 结果

- 实施中。
