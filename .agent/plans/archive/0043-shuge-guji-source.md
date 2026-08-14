# Task Spec 0043：新增书格（shuge）古籍书源

## Goal（必填）

用户/系统能够：通过 `education-resources` MCP 搜索书格公开存储（shuge.hanjihebi.com，OpenList）中的公版古籍，并对其 PDF 文件完成搜索 → Inspect → 确认 → 直链下载（`/d/` 端点，支持 Range）的完整闭环，无需登录、无需网盘。

## Non-goals（必填）

- 不接入书格 WordPress 站内搜索与短链（s.shuge.org → f.shuge.org/dl）链路；不解析网盘分享链接（百度/阿里/豆包）。
- 不做网盘直链解析器（蓝奏云/天翼云等）；本期只覆盖书格公开存储。
- 不改动 annas-archive/libgen 现有行为。
- 不新增抽象层、事件总线或新框架；沿用现有 adapter / inspector / ProviderRegistration 模式。
- 不处理需要登录的 OpenList 分享（`@s/` share API 403）。

## Acceptance Criteria（必填）

### AC-01 搜索

Given: Flow 已建立，用户搜索古籍（如“宋词三百首”）且 search_tasks 含 platform=shuge
When: resource_search 执行
Then: 返回候选含书名（含书名+版本信息）、文件大小、直链来源信息；失败时返回结构化 PARTIAL_FAILURE 而非异常。

### AC-02 Inspect

Given: 候选来自 shuge 搜索且携带存储路径
When: resource_inspect 执行
Then: 返回 fresh Resolution/Representation：技术可用性、文件大小、直接下载 URL（/d/ 路径），且 Inspect 再次调用 OpenList API 核验存在性。

### AC-03 下载

Given: Plan 确认后 resource_download_start
When: 执行下载
Then: 文件以流式写入 jobs 目录，最终产物 sha256/byte_size 与下载内容一致；失败返回可重试的结构化错误。

### AC-04 注册一致性

Given: 代码加载
When: 启动/测试
Then: platform-registry.json、retrieval/registry.py EXPECTED_PLATFORM_IDS/INSPECTION_PLATFORM_IDS、search/inspection/下载注册、test_adapter_registry_consistency.py、SKILL.md 命名空间全部包含 shuge，且一致性测试通过。

## Business Invariants

- 模型不得伪造业务状态、下载结果、路径或哈希。
- 有副作用下载仍走 prepare → 确认 → start 两阶段。
- 下载只经服务端 /d/ 直链与受控 jobs 目录；不经模型拼接命令。
- 不静默 fallback：OpenList API 失败返回结构化错误，不切换其他 Provider。

## 验证等级

- Level 1：新增/受影响单元测试（mock 网络）、语法检查、一致性测试。
- Level 2：真实网络 smoke（搜索“宋词三百首”→ inspect → 下载前 512KB 验证 206 与 content-type）。