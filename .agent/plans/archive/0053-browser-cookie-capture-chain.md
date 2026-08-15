# Task Spec 0053：登录捕获改为服务端 CDP 直读（含 httpOnly）

- 状态：superseded
- 创建日期：2026-08-15
- 替代日期：2026-08-16
- 分支：`codex/growth-resource-taxonomy-rework`
- 来源：0028 用户真实测试反馈（2026-08-15，抖音搜索「停云小阁」登录后持续失败）

## 原事故

2026-08-15 的真实 OpenClaw 会话中，抖音登录后搜索仍然 `AUTH_REQUIRED`。当时 Agent 实际选择了 page-context `document.cookie` 捕获，因此拿不到 httpOnly 登录 Cookie；随后又尝试把完整 Cookie 大对象经模型转述给 `resource_session_save`，遇到输出截断，保存无法完成。

这个事故是真实的，但后续把它解释成“OpenClaw 浏览器本身无法完整读取 httpOnly Cookie”是错误的。

## 原方案

0053 曾增加：

- `resource_session_capture_browser` MCP 工具；
- `browser_capture.py`，自行实现 CDP `/json/version`、WebSocket、`Storage.getCookies`；
- `BROWSER_UNAVAILABLE / BROWSER_CDP_ERROR`；
- 对应 schema、tool catalog、Skill 指引和测试；
- session-manager 版本 `0.4.0 -> 0.4.1`。

目标是让 session-manager 自己连接 OpenClaw-managed browser，并在 MCP 内部完成 Cookie 捕获与保存。

## 2026-08-16 重新核验

重新阅读 OpenClaw 官方源码后确认，OpenClaw 原生浏览器 Cookie 能力已经通过 Playwright 获取浏览器上下文 Cookie：

```ts
const cookies = await page.context().cookies();
```

这不是 `document.cookie`。`BrowserContext.cookies()` 返回浏览器上下文 Cookie，并包含 `httpOnly` 等字段。因此：

- “需要自建 CDP 才能取得 httpOnly Cookie”不成立；
- “OpenClaw 只提供 page-context Cookie”不成立；
- 自建一套 CDP/WebSocket 客户端与 OpenClaw 现有浏览器层职责重复。

0053 唯一额外能力是“Cookie 值不经过 Agent/tool result”，但当前项目没有把这一点定义为必须为之维护独立 CDP transport 的产品硬要求，不能据此支撑数百行底层实现。

## 最终决策

撤销 0053 的自建浏览器捕获通道，恢复原有职责边界：

```text
resource_session_status
→ resource_session_login_guide
→ OpenClaw managed browser 登录
→ OpenClaw 原生 browser cookies（Playwright BrowserContext.cookies）
→ resource_session_save
→ SessionStore 平台提取 / 最小化 / 持久化
→ status / probe
```

session-manager 不再自己管理：

- CDP 端口；
- `/json/version` 发现；
- WebSocket 握手/帧；
- `Storage.getCookies`；
- OpenClaw 浏览器生命周期或连接方式。

这些属于 OpenClaw 浏览器层。

## 保留的独立修复

真实捕获样本暴露了一个与 CDP 架构无关的问题：浏览器 Cookie 列表可能包含空名/非法名垃圾条目。它们不是凭据，不应导致整批 `resource_session_save` 失败。

因此保留 `SessionStore` 的行为：

```text
空名 / 非法名 Cookie
→ discarded +1
→ 继续处理其余 Cookie
```

以及对应的 `test_store.py` 回归用例。

## 对 0028 的修正

0028 保留“登录后搜索失败”和“模型转述大 Cookie 失败”的真实事故记录，但不再把 `document.cookie` 的局限描述为 OpenClaw 原生 browser cookie 能力的局限。当前复测应走 OpenClaw 原生 browser cookies → `resource_session_save`。

## Validation boundary

本次替代只做结构与职责回退：删除自建 CDP 工具/契约/实现/专项测试，恢复 0053 之前的 session-manager server、Skill、catalog 与版本，同时保留空名 Cookie 修复。

真实登录 → 保存 → 搜索仍由 0028 的用户 OpenClaw E2E 验收，不以离线测试冒充真实通过。
