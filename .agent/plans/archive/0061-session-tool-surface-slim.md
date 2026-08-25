# 0061 — Session Tool 公共契约瘦身

> 处置：superseded by [0067-resource-capability-surface-unification.md](0067-resource-capability-surface-unification.md)。Session 结论已进入当前架构，剩余 AUTH_REQUIRED 真实验收已并入 [0028-real-openclaw-platform-e2e.md](0028-real-openclaw-platform-e2e.md)。

- 状态：in_progress
- 创建日期：2026-08-20
- 完成日期：未完成
- 范围：`mcp/education-resources` Session Tool schema、SessionStore 公共 metadata、相关文档与聚焦测试

## Objective

把平台认证细节从主模型的 Tool schema 中移回 MCP 内部：模型只判断何时需要登录，并把浏览器捕获结果作为 opaque capture 交给 MCP；平台代码负责识别和保存实际需要的 Cookie / Token / storage 字段。

## Non-goals

- 不改变资源 Search / Inspect / Download / Batch / Archive 主流程。
- 不新增 Session 工作流状态机或独立 session-manager。
- 不凭经验新增未经真实验证的 Cookie 名白名单。
- 不删除现有 broad browser capture 的兼容能力；只收窄公共 schema。
- 不改变 Windows DPAPI、原子写入、过期判断、probe 等存储行为。

## Business invariants

1. Session 仍只在真实资源能力返回 `AUTH_REQUIRED`，或用户主动管理登录态时使用。
2. Agent 不负责判断某个平台需要哪些 Cookie / Token，也不手工拼 canonical credential。
3. 浏览器捕获可以较宽；MCP 按平台内部规则筛选后只持久化 canonical subset。
4. 已确认的平台认证要求继续由 `PlatformConfig` / SessionStore 内部实现掌握；未确认到具体 Cookie 名的平台不凭猜测收窄。
5. 公共 Session Tool 不返回凭据原文。
6. Tool 总数本轮不作为目标；优先减少 schema 复杂度而不是为了数字强行合并 Tool。

## Current architecture

旧公共契约的 `resource_session_save` 直接展开 `SessionCapture`：cookies、storage_origin、local_storage、session_storage、tokens 等嵌套字段。实际上 SessionStore 已经按 platform 做域名/字段提取，例如 SmartEdu 明确要求 `accessToken`，因此这些细节不需要长期存在于主模型的 Tool schema。

当前实现已改为：

```text
resource_session_save(
  platform,
  capture,      # opaque object
  expires_at?
)
```

`capture` 原样交给既有 SessionStore 过滤逻辑；内部 platform auth rules 没有迁到 Agent。

## Expected change surface

已改：

- `mcp/education-resources/src/education_resource_mcp/server.py`
- `mcp/education-resources/src/education_resource_mcp/sessions.py`
- `mcp/education-resources/tests/test_session_public_contract.py`
- `TOOLS.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `mcp/education-resources/README.md`

未改：

- 各资源 Adapter 的 Search / Inspect / Download 逻辑
- Job / Batch / Archive
- SessionStore canonical extraction 主逻辑

## Acceptance criteria

- AC-01：`resource_session_save` 的公开 input schema 只把浏览器捕获暴露为一个 opaque object，不再展开 cookies/localStorage/sessionStorage/tokens 的嵌套字段定义。
- AC-02：Tool 调用后仍把 opaque capture 原样交给现有 SessionStore 过滤逻辑，现有 SmartEdu / Cookie 平台保存行为不变。
- AC-03：`resource_session_status` / `resource_session_login_guide` 的公开 metadata 不再暴露内部 `cookie_domains` / `storage_keys`。
- AC-04：SmartEdu `required_storage_keys=("accessToken",)` 等内部认证事实保留。
- AC-05：现有 14 个 Tool 名称保持不变，避免为了瘦 schema 制造无关兼容破坏。
- AC-06：聚焦测试验证 public schema 不再包含 `cookies` / `local_storage` / `session_storage` / `tokens` 字段定义。

## Complexity exceptions

默认：无。没有新增 source of truth，只把既有内部/外部边界调正。

## 步骤

- [x] completed：确认平台认证事实已经由 SessionStore / PlatformConfig 部分固化
- [x] completed：瘦身 Session Tool public schema 与 public metadata
- [x] completed：补聚焦测试与文档
- [ ] in_progress：在可运行仓库环境执行聚焦测试并做真实 OpenClaw AUTH_REQUIRED 登录链路复测

## 验证

静态回读已确认：

- `resource_session_save` 公共参数为 `platform + capture + expires_at`；
- `capture` 类型为 `dict[str, Any]`，server 不再定义 SessionCapture 的 cookies/storage/tokens 嵌套 schema；
- `PlatformConfig.public_metadata()` 不再返回 `cookie_domains` / `storage_keys`；
- SmartEdu 内部仍保留 `required_storage_keys=("accessToken",)`。

新增聚焦测试：

```text
pytest tests/test_sessions.py tests/test_session_public_contract.py tests/test_mcp_stdio.py
```

本轮尝试从 ChatGPT 容器访问仓库时，`git ls-remote https://github.com/lxxalalei/flow_ver.git HEAD` 仍失败：`Could not resolve host: github.com`。因此上述 pytest **尚未实际执行**，不能写成已通过。

真实链路仍待验证：

```text
资源能力 -> AUTH_REQUIRED
-> resource_session_login_guide
-> 浏览器 capture
-> resource_session_save(platform, capture)
-> 重试原资源能力
```

## 结果

代码和公共契约收敛已完成；计划保持 `in_progress`，直到聚焦测试和至少一次真实 OpenClaw 登录闭环有实际证据。
