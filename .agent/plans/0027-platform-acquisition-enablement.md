# 0027 Existing Platform Acquisition Enablement

- 状态：in_progress
- 创建日期：2026-08-10
- 完成日期：未完成
- 范围：`mcp/education-resources` 中现有 Bilibili、Douyin、Ximalaya、Anna's Archive 下载实现与通用浏览器捕获机制的正式能力接入
- 前置计划：[`0025 Platform Capability Contract Alignment`](archive/0025-platform-capability-contract-alignment.md)（completed）
- 后续验收：[`0028 Real OpenClaw and Real Platform E2E`](0028-real-openclaw-platform-e2e.md)

## 目标

让源码中已经存在的平台获取实现进入 0025 冻结的单一权威链：静态 Capability Descriptor、
运行时 Deployment Readiness、Inspection 产生的 Resolution/Representation、Eligibility、不可变
Plan/Execution binding、exact AcquisitionRouter Provider、Outcome/Bundle/Asset/Archive。接入不得依赖
平台名隐式路由、generic fallback、扩大 timeout、跳过认证/权限或把 landing page 冒充 primary。

浏览器渲染/CDP 是通用 `web_capture` 获取机制，不计为独立平台；只有明确 descriptor、依赖和
策略均满足时才可执行。Anna's Archive/Libgen 获取必须经过明确版权/许可策略审查，不能因已有
下载代码就默认放行。

## 步骤

- [ ] in_progress：A. 审计现有 Provider、Inspector、搜索候选、依赖、认证、网络与内容校验边界，冻结逐平台接入矩阵。
- [ ] pending：B. 设计并更新 Capability Descriptor、runtime readiness inventory、provider registration 与版本兼容策略。
- [ ] pending：C. 修正 Provider 的安全、依赖、认证和结构化错误缺口，并接入默认 ResourceService。
- [ ] pending：D. 补齐逐平台 Resolution/Representation 到 Plan/Execution exact binding 的契约与生命周期测试。
- [ ] pending：E. 运行受影响单测、契约/Schema、compile、stdio/OpenClaw 可行 smoke，并由根 Agent 审查差异。
- [ ] pending：F. 更新架构/Skill/0028 E2E 边界与交付结果；真实网络或合法会话不足的项记录为后续真实 E2E，而不伪造 production-ready。

## 验证

- 逐平台 Provider 单测：输入绑定、认证、依赖、取消、大小、域名/重定向、MIME/magic、结构化失败。
- Capability/Registry：descriptor digest、版本、readiness、exact provider/scopes、fallback 全关闭。
- Service 生命周期：Search/Inspect/Present/Select/Prepare/Start/Job/Asset，验证不可变 authority binding。
- 受影响 unittest、`compileall`、契约与 Markdown 链接、`git diff --check`。
- 仅在合法、无敏感信息且不会绕过访问控制时执行真实网络/OpenClaw smoke；否则留给 0028 Real E2E。

## 结果

- 实施中。
