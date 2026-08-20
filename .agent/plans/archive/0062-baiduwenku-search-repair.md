# Task Spec 0062：修复百度文库实时搜索

- 状态：completed
- 创建日期：2026-08-20
- 完成日期：2026-08-20
- 范围：百度文库搜索适配器、共用 HTTP fallback 的必要平台兼容、定向测试

## Goal（必填）

用户/系统能够：通过 `resource_search(platform=baiduwenku)` 获得百度文库当前公开搜索结果，或在上游拒绝访问时得到显式结构化失败，而不是因过期页面结构稳定返回空列表。

## Non-goals（必填）

- 不新增百度文库下载、Inspect、登录或 Cookie 捕获能力。
- 不建立新的平台 Registry、通用浏览器自动化层或持久状态。
- 不修改其他平台搜索语义，也不处理先前未提交的能力说明改动。

## Acceptance Criteria（必填）

### AC-01

```text
Given: 百度文库当前公开搜索响应
When: 适配器搜索教育资源关键词
Then: 返回带标题、稳定详情 URL 和文档类型的候选，且遵守 limit
```

### AC-02

```text
Given: urllib 被 403 拒绝但本机可用 curl 能访问同一公开 URL
When: 百度文库适配器执行搜索
Then: 现有 HTTP fallback 能在当前操作系统完成请求；若 fallback 也失败则返回显式 PARTIAL_FAILURE
```

### AC-03

```text
Given: 固定的当前响应夹具与失败响应
When: 运行百度文库定向测试和搜索子系统测试
Then: 新旧解析边界、limit、错误语义以及不影响其他适配器的行为均有证据覆盖
```

## Business Invariants

- 搜索只返回公开候选，不把可发现误报为可下载。
- 不静默吞掉上游拒绝、响应协议变化或解析异常。
- `resource_id` 仍由 ResourceService 生成，适配器不引入新权威状态。

## Current System Understanding

- `adapters/baiduwenku.py` 直接读取搜索 HTML 中旧版 `window.pageData` 路径。
- 当前 urllib 请求收到 403；同机 curl 得到 200。
- 当前 200 页面不再包含旧版 `docList`，需要确认实际公开搜索数据来源后再实现。

## Expected Change Surface

- Likely to change: `adapters/baiduwenku.py`、`adapters/http_client.py`、直接相关测试。
- Should not change: MCP 公共 Tool Schema、下载/检查路由、其他平台能力、先前未提交的三个文件。

## Validation Plan

- 百度文库解析与错误处理单元测试。
- HTTP fallback 定向测试。
- 搜索契约/适配器相关测试。
- 一次真实联网 `ResourceService.search`。
- 不默认运行全量回归；只有共用 HTTP helper 的定向回归无法覆盖风险时再扩大。

## Complexity Exception

```text
Problem: 现有 HTTP helper 的 curl fallback 被硬编码为 Windows-only，当前 macOS urllib 被 403 拒绝。
Why current structure cannot solve it: 适配器已使用该 helper，但无法请求一次可用的系统 curl。
Simplest alternative considered: 仅增加请求头。
Why that alternative is insufficient: 相同请求头下 urllib 仍为 403，而 curl 为 200，证据指向客户端指纹差异。
New source of truth introduced: 无。
New invariant introduced: 只有调用方明确声明可对特定 HTTP 状态 fallback 时才使用 curl。
Failure modes introduced: 系统未安装 curl 或 curl 请求失败；继续沿用现有显式异常语义。
```

## 步骤

- [x] completed：确认百度文库当前公开搜索数据来源和最小请求方式。
- [x] completed：实现跨平台显式 curl fallback 与新版结果解析。
- [x] completed：补充定向测试并执行真实联网验证。
- [x] completed：完成边界复核、记录结果并归档计划。

## Milestone checkpoint

```text
Original goal still unchanged?: 是
Non-goals still respected?: 是；未增加下载、Inspect、登录或 Registry
Business invariants still true?: 是
New abstraction introduced?: 否
New source of truth introduced?: 否
Fallback added?: 是；仅调用方显式声明 403 时跨平台调用现有 curl fallback
Data truncation added?: 否；既有 limit 语义保持不变
Unrelated files changed?: 否；先前未提交的能力说明文件未被本任务改写
Actual user flow affected?: 百度文库 resource_search 恢复
Actual user flow validated?: 后端真实联网 ResourceService 已验证；未执行真实 OpenClaw Agent
Scope drift detected?: 否
```

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted unit | 26 tests passed | 新移动页解析、limit、显式解析失败、HTTP fallback 契约 | 上游长期稳定性 |
| integration | MCP package 全量 pytest 通过 | 当前 MCP 搜索、HTTP helper 与其他子系统回归 | 真实 OpenClaw Agent 行为 |
| real network search | 2 queries、10 candidates、0 failures | 当前网络下真实 ResourceService 可搜索两类教育关键词 | 百度未来页面稳定性、Windows 真实运行 |
| real Agent/user flow | 未执行 | — | OpenClaw 的工具选择与结果呈现 |

## 结果

- 百度文库搜索改用仍包含服务端结果的移动端公开页面；桌面 AI 空壳不再作为结果数据源。
- 当前 `initData.docList[].docInfo` 已映射为稳定标题、摘要、详情 URL 和平台信号。
- urllib 收到明确 403 时使用现有 curl fallback；系统 curl 检测支持 Windows/macOS/Linux，原自动证书 workaround 仍保持 Windows-only。
- Level 2 验证完成；未执行真实 OpenClaw Agent、Windows 实机或下载流程。
