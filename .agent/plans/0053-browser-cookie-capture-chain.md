# Task Spec 0053：登录捕获改为服务端 CDP 直读（含 httpOnly）

- 状态：in_progress
- 创建日期：2026-08-15
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`
- 来源：0028 用户真实测试反馈（2026-08-15，抖音搜索「停云小阁」登录后持续失败）

## 事故记录（来自 TUI 会话 646dcf76）

```text
Date/time: 2026-08-15 15:00–15:33 (UTC+8)
Platform: douyin
User request: 在抖音上搜索停云小阁这个用户
Reached stage: Search（AUTH_REQUIRED）→ 登录引导 → 用户扫码登录成功 → 保存会话 → 重存反复中断
Observed status or error code:
  1) 首次保存后搜索仍 AUTH_REQUIRED；
  2) 重存阶段每次 output 顶格 4096 tokens，
     terminalError=non_deliverable_terminal_turn（工具调用被 maxTokens 截断）。
Expected behavior: 登录成功且保存后，抖音搜索应正常返回。
Actual behavior:
  捕获走 document.cookie，读不到 httpOnly 的 sessionid/sid_tt/uid_tt 等关键凭证，
  存下的是"半份"会话；agent 自行发现完整 cookie 后，重存需要模型把 ~28KB cookie
  转述进工具调用，超过 maxTokens=4096 被截断，重存永远无法完成。
Sensitive values removed: yes
```

定位（两层）：

1. **捕获通道缺口**：`session-login-flow` 的捕获指引允许 agent 用浏览器上下文
   `document.cookie` 读 Cookie；httpOnly 登录凭证（sessionid 等）对该通道不可见。
2. **模型转述瓶颈**：凭据大负载必须经模型上下文转述，受输出 token 上限与
   凭据泄漏到上下文双重约束。当日已将 openclaw.json 两个模型 maxTokens 4096→8192
   缓解第二层，但正确方向是让凭据不过模型。

当日人工修复（不作为工程完成证据）：经 CDP `Storage.getCookies` 读取完整 54 条
douyin cookie 直接写入 store（过滤 1 条空名 cookie 后），并用生产
`DouyinSearchAdapter` 验证搜索「停云小阁」返回 6 条真实结果。

## Goal（必填）

用户/系统能够：在 OpenClaw 中对 cookie 登录平台完成「打开登录页 → 用户确认已登录」后，
由 session-manager MCP 新工具 `resource_session_capture_browser` 服务端直读受控浏览器
（CDP `Storage.getCookies`，含 httpOnly），按平台提取后落盘；全程凭据字节不经模型
上下文转述。保存后既有 status/probe/search 链路即可使用。

## Non-goals（必填）

- 不改 `resource_session_save` 的宽捕获契约：用户自愿提供的 canonical Cookie/Token
  直存分支保持不变；storage 平台（localStorage）捕获仍走该分支。
- 不实现浏览器启动/关闭：浏览器生命周期仍由 OpenClaw 网关管理；CDP 不可达时返回
  结构化可重试错误，由 agent 先开浏览器再重试。
- 不引入 WebSocket 第三方依赖：CDP 客户端用标准库实现（单命令请求/响应的最小
  RFC6455 子集），依赖面保持 `mcp==2.0.0` 不变。
- 不改 store 的平台提取规则、DPAPI 加密、幂等与文件安全语义。
- 不新增平台、不改 education-resources 侧任何代码。

## Acceptance Criteria（必填）

### AC-01 捕获工具读到 httpOnly 凭证并落盘

```text
Given: 受控浏览器已打开且用户已登录平台（如 douyin），CDP 端点可发现
When: resource_session_capture_browser(platform="douyin")
Then: 返回 ok、stored_credential_count>0、含 httpOnly 关键凭证（按 store 提取规则）；
      响应中不含任何 cookie 值；随后 resource_session_status 该平台为 stored。
```

### AC-02 空名/垃圾 cookie 被丢弃而不是整单拒绝

```text
Given: CDP 返回的 cookies 中存在 name 为空的条目（真实事故样本）
When: resource_session_save(宽捕获) 或 capture_browser
Then: 该条目计入 discarded，其余正常保存；不再 SESSION_PAYLOAD_INVALID 整单失败。
```

### AC-03 CDP 不可达返回结构化可重试错误

```text
Given: 受控浏览器未运行（loopback CDP 端口拒绝连接）
When: resource_session_capture_browser
Then: ok=false，error.code=BROWSER_UNAVAILABLE，retriable=true，
      message 指示先打开浏览器再重试；无凭据泄漏。
```

### AC-04 直存分支与既有行为不回退

```text
When: 运行 session-manager 全量测试（store/contracts/stdio）
Then: 既有用例不因本次改动失败；canonical 直存、storage 平台宽捕获语义不变。
```

### AC-05 Skill 指引更新且不再依赖 document.cookie

```text
Given: session-login-flow SKILL.md / login-workflow.md / server instructions
Then: cookie 平台捕获步骤指向 resource_session_capture_browser；
      明确禁止用 document.cookie 等读不到 httpOnly 的通道充当完整捕获；
      保留 canonical 直存分支原文语义。
```

### AC-06 真实 OpenClaw 复测（归档前置）

```text
Given: OpenClaw 部署含本修复
When: 用户对任一 cookie 登录平台走完整登录-捕获-搜索链路
Then: 不出现"登录后仍 AUTH_REQUIRED"与"重存中断"；结果记回 0028。
```

## 设计要点

1. 新模块 `src/session_manager/browser_capture.py`：
   - CDP 发现：`GET http://127.0.0.1:<port>/json/version`（端口取
     `SESSION_MANAGER_BROWSER_CDP_PORT`，默认 18800，仅 loopback）；
   - 最小 stdlib WS 客户端（握手 + 单条 masked text frame + 响应重组 + close），
     只发 `Storage.getCookies` 一个命令；
   - CDP cookie → store schema 归一化（sameSite 映射、expires 数值化），
     过滤空名条目；
   - 传输层可注入，供测试 stub。
2. `store.py` `_sanitize_cookie_payload`：空/非法 name 从"整单拒绝"改为"丢弃计数"
   （与 out-of-domain 同类）；数量/长度上限语义不变。
3. `server.py` 新增 `resource_session_capture_browser(contract_version, platform)`：
   捕获 → `store.save(platform, {"cookies": ...})` → 返回 store 结果 + counts；
   更新 server instructions 的推荐链路。
4. Skill 文件（`distribution/skills/session-login-flow/`）同步改写捕获段；
   版本 0.4.0 → 0.4.1。
5. 测试：`tests/test_browser_capture.py`（stub 传输：归一化、空名过滤、
   CDP 不可达、凭据不出现在响应）；`tests/test_store.py` 补 AC-02 用例。

## Validation checkpoint

已完成（2026-08-15，Windows 本机）：

- `tests/test_browser_capture.py` 10 个用例通过：归一化（空名丢弃、sameSite 映射、
  session/非法 expires 省略）、真实 loopback socket 假 CDP 端点的 WS 往返
  （握手/掩码/Storage.getCookies）、端口 env 覆盖、非 loopback 调试 URL 拒绝、
  工具端到端（stored/discarded/captured 计数、响应不含 cookie 值）、
  CDP 不可达 → BROWSER_UNAVAILABLE retriable。
- `test_contracts.py` / `test_mcp_stdio.py` 通过（catalog 1.2.0、五工具、错误码枚举
  补 BROWSER_UNAVAILABLE / BROWSER_CDP_ERROR、服务版本 0.4.1）。
- `test_store.py` 新增空名丢弃两条用例通过。
- 全量：70 passed / 5 failed / 4 skipped。5 个失败为基线固有（写入明文记录的用例在
  原生 Windows DPAPI fail-closed 语义下必败，与本次改动无关，stash 基线复现相同失败集）。

待完成：

- ~~同步部署到 Windows OpenClaw，`openclaw mcp doctor session-manager --probe` ok~~
  已完成（2026-08-15）：sync 脚本同步、gateway 重启、两个 MCP doctor --probe 均 ok。
- ~~对真实浏览器实测 `resource_session_capture_browser` 一次完整捕获-保存-搜索链~~
  已完成（2026-08-15）：真实受控浏览器上调用工具一次成功——ok / stored /
  stored_credential_count=54（含 httpOnly 凭证）/ discarded_credential_count=32
  （他域）/ 响应无任何凭据值；随后生产 `DouyinSearchAdapter` 真实搜索「停云小阁」
  返回 6 条结果。
- AC-06 用户复测后归档。

## Completion criteria

- AC-01~AC-05 全部有实现与测试证据；
- 已同步部署到 Windows OpenClaw 且 `openclaw mcp doctor session-manager --probe` ok；
- AC-06 用户真实复测通过并记录回 0028 后，本计划方可归档。
