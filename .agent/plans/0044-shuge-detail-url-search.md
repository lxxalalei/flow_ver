# Task Spec 0044：书格详情页/短链链接直转公开存储直链

## Goal（必填）

用户或模型把书格详情页链接（`www.shuge.org/view/<slug>/`）或书格短链
（`s.shuge.org/<code>`）作为 `resource_search` 的 query 传给 `shuge` 平台时，
`ShugeSearchAdapter` 自动完成：抓取详情页 → 提取书名 → 在公开存储
（shuge.hanjihebi.com OpenList `/书格网站资源`）按书名搜索 → 返回 `/d/`
直链候选（含 `file_path`、`detail_url` 信号），复用既有 inspect/下载链路。

## Non-goals（必填）

- 不解析网站自身的网盘分发通道（百度/阿里/蓝奏等分享链接）。
- 不实现短链 302 后的登录态分享页下载（f.shuge.org/dl 当前 525，恢复后也只提取书名）。
- 不改下载/归档链路、不动 Registry 声明、不新增抽象层或新工具。
- 不把详情页链接抓取扩展到 shuge.org 之外的域（防 SSRF）。

## Acceptance Criteria（必填）

### AC-01 链接识别
Given: query 为 `shuge.org/view/...`、`www.shuge.org/view/...`（带/不带协议、带/不带尾斜杠）或 `s.shuge.org/...`
When: `ShugeSearchAdapter.search(query, limit)`
Then: 走详情页抓取路径；普通关键词仍走原存储搜索路径，行为不变。

### AC-02 书名提取与二次搜索
Given: 详情页 HTML 含 `<title>五经类语 – 书格</title>`（含 HTML 实体、各种分隔符）
When: 提取书名并调 OpenList `/api/fs/search`
Then: payload `keywords` 为提取后的书名（去尾部"书格"），返回候选含 `/d/` source_url、`file_path` 与 `detail_url` 信号。

### AC-03 结构化失败
Given: 详情页网络错误 / HTTP 错误 / 无法提取书名（无 title 或 title 仅剩"书格"）
When: 执行
Then: 返回 `PARTIAL_FAILURE`；网络类 retryable=True，HTTP 4xx/5xx 与解析失败 retryable=False；不抛异常、不静默按 URL 字符串当关键词搜。

### AC-04 测试与文档
Given: 改动完成
When: 运行受影响测试与 smoke
Then: `test_shuge.py` 新增用例全过（mock 网络，断言两次请求的 URL/payload）；`test_adapter_registry_consistency.py`、`test_platform_registry.py` 不回归；真实网络 smoke（真实详情页 URL）提取书名并命中存储；`source-routing.md` 补 `shuge` 生态条目并把 `shuge` 加入命名空间列表（修复 0043 同步缺口）。

## Business Invariants

- 不伪造业务状态、路径或直链；`file_path` 必须来自服务端 OpenList 响应。
- 只允许抓取 `*.shuge.org` 域页面，绝不把用户提供的 URL 作为任意 SSRF 目标。
- 失败全部结构化返回，不 silent fallback 到其他平台。
- 下载仍只走服务端 `/d/` 直链 + 受控 jobs 目录。

## 验证等级

- Level 1：`tests/test_shuge.py`（新增 + 既有）、`test_adapter_registry_consistency.py`、`test_platform_registry.py`、`git diff --check`。
- Level 2：真实网络 smoke：`search("https://www.shuge.org/view/wu_jing_lei_yu/", 10)` → 提取"五经类语"→ 命中 696MB PDF 直链；`/d/` Range 探测 206。
- 不运行全量回归（diff 只影响 shuge adapter 及其直接测试与文档）。
