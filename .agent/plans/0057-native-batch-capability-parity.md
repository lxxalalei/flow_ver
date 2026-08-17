# 0057 — Native Batch Capability Parity（四平台批量能力原生化）

- 状态：in_progress
- 创建日期：2026-08-16
- 范围：`mcp/education-resources` 的 douyin / bilibili / zhihu / smartedu 适配器与公共工具

## Objective

把 `mediacrawler-platforms` skill（fork 版 MediaCrawler）中四平台的批量采集与元数据能力，**以原生实现的方式**并入 education-resources MCP：skill 仅作为参考实现样本，完成后与 MCP 无任何运行时关联（不调用、不打包、不依赖），skill 本身退役。

## 参考实现（只读样本，非依赖）

```text
C:\Users\admin\.claude\skills\mediacrawler-platforms\MediaCrawler\media_platform\
  douyin\client.py    # publish_time 过滤、图集、创作者资料
  bilibili\client.py  # pubtime_begin/end 时间范围搜索、UP 资料（wbi）
  zhihu\client.py     # 回答/文章详情、时间/类型/排序过滤
  smartedu\client.py  # 26 分类 tabs、同步课堂目录展开（fork 扩展）
```

## Motivation

- 现状能力差（相对 skill）：bili 无时间范围全量搜索/UP 资料/画质选择；douyin 无发布时间过滤/图集下载/创作者资料；zhihu 无详情富化与过滤参数；smartedu 无分类 tabs/目录展开。
- MCP 的 adapters 本就自带签名与登录链（douyin_sign.js、wbi、session-manager cookie），血缘同源，原生扩展是自然延续。
- 原生实现顺带消灭"两套登录态"：批量能力直接读 session-manager 共享库，不再需要 skill 的 Playwright browser_data。
- 代价（自觉接受）：反爬对抗的维护完全落在本仓库；参考 fork 只用于移植时对照，之后不再跟进。

## Non-goals

- 不引入 MediaCrawler 运行时依赖（不 import、不 subprocess 调用、不打包其代码）。
- 不移植 IP 代理池。
- 不移植 7 种存储格式；批量结果只用本仓库文件布局（jsonl）。
- 不移植 Playwright 扫码登录；登录继续走 session-manager + OpenClaw 原生浏览器（AUTH_REQUIRED 链路）。
- 不把批量结果转成 `resource_id` 句柄；两个数据模型不硬焊。

## Business invariants

- 对话式精选（resource_search limit≤20、候选进对话）与批量采集（结果落盘、O(1) 摘要返回）是两种显式模式，不混用。
- 批量任务必须：上下文只回路径+条数+头部样本；全量数据在文件里，可分页读取。
- exact Provider 路由、真实 AUTH_REQUIRED、真实失败不隐藏、不静默换源，全部不变。
- 平台内串行防限流的口径不变；批量枚举默认并发 1。
- 批量任务复用 0056 的 detached job 语义：跨 MCP/网关重启存活、崩溃如实 interrupted。

## Expected change surface

- 新增公共工具（2 个）：
  - `resource_batch_collect`：platform + mode（`time_range_search` / `creator_full` / `catalog_expand`）+ 模式参数；作为 detached job 执行；返回 `batch_id` + 状态。
  - `resource_batch_read`：batch_id + offset/limit 分页读结果文件；仍不把全量灌进对话。
- 新增 batch worker（复用 jobs/ 目录布局、job.json 状态、JobSpawner、cancel.flag）。
- adapters 增强（按 2026-08-16 范围收口）：
  - **zhihu：planner spec 允许 zhihu 文章/回答路由到 generic-web-materializer（网页物化即正文下载，快赢）**；
  - smartedu：分类 tabs 搜索参数、同步课堂目录展开（fork smartedu client 参考移植）、token 获取与现有 sessions 对齐；
  - douyin：图集下载（DouyinDownloader 扩展 images 类型）、创作者资料并入 browse_creator 返回；
  - douyin/bilibili 的 search_creator 分页循环接入 cancel_event（批量取消检查点）。
- 明确不做（用户决策 2026-08-16）：bili/dy 搜索排序与发布时间过滤（爬虫向，本 MCP 目标是资料收集）；bili 画质维持现状（已请求 DASH 最高含 4K、取最高带宽流，登录态下即 1080P+）。
- 失败分类自诊断（横切）：错误码区分 RISK_CONTROL / AUTH_REQUIRED / PARAM_INVALID / PLATFORM_CHANGED，消息自带下一步建议。
- 文档：README 工具清单、SKILL.md 增补批量模式使用边界。

## 上下文预算硬上限（invariants，构造保证）

- `resource_batch_collect` 返回体 ≤ 2KB（路径/条数/头部样本）。
- `resource_batch_read` 单次默认 ≤ 20 条、上限 50 条。
- 错误消息 ≤ 500 字符，超出的诊断信息落 worker.log / 文件，不进对话。

## Milestones（各自独立可交付）

- M0 zhihu 物化路由（快赢：planner spec + 测试）。
- M1 批量基座：batch job 目录/状态/worker + `resource_batch_collect` / `resource_batch_read` 两工具 + creator_full 模式 + 定向测试（fake provider 全链路）。
- M2 smartedu：tabs、目录展开、token 对齐。
- M3 douyin：图集下载、创作者资料。
- M4 批量模式扩展：time_range_search / catalog_expand 接入基座（翻页全量）。
- M5 退役：skill 从 Claude skills 目录移除（用户确认后）、文档收口。

## Acceptance criteria

- AC-01：`resource_batch_collect` 任一模式返回体 ≤ 2KB（路径/条数/样本），全量结果在文件；网关重启后任务存活（复用 0056 语义）。
- AC-02：`resource_batch_read` 可任意分页读取，单次默认 ≤ 20 条。
- AC-03：bili 时间范围全量搜索真实跑通（如某关键词一周全量），jsonl 字段覆盖标题/链接/UP/时间/播放量。
- AC-04：douyin 图集真实下载成功（视频+图片两类各验一个）。
- AC-05：smartedu 目录展开真实跑通（一个 defaultTag 目录 → 课程清单 → 详情文件）。
- AC-06：所有新入参进 typed schema；结构错误响亮报 INVALID_ARGUMENT（1ee8eda 口径）。
- AC-07：登录缺失时批量任务如实 AUTH_REQUIRED，不静默空结果。
- AC-08：全量 pytest 零新回归（当前基线 51 个既有失败）。

## Complexity exceptions

- 不为批量另起状态机：batch job 就是 0056 job 的一种 kind，同一目录布局与恢复语义。
- 平台内枚举串行；不引入每平台并发配置（参考 skill 的并发参数不移植）。

## Milestone checkpoint

```text
Original goal still unchanged?: yes（skill 仅参考，能力原生化，完成后无关联）
Non-goals still respected?: yes（无 MediaCrawler 运行时依赖；无代理池/多存储格式/Playwright 登录）
Business invariants still true?: yes（批量 O(1) 摘要 + 分页读；exact 路由/AUTH_REQUIRED 不变；复用 0056 job 语义）
New abstraction introduced?: no（batch 是 0056 job 的一种 kind，复用目录/spawner/恢复/cancel）
New source of truth introduced?: no（results.jsonl 即批量结果事实）
Fallback added?: no（失败如实 NETWORK_BLOCKED/FEATURE_NOT_SUPPORTED）
Context budget respected?: batch_collect 返回 ~100 字符；batch_read 默认 20 条；工具定义 9 个共 6.3K 字符
Actual user flow affected?: 新增批量模式 + zhihu 可物化下载；既有工具签名不变
Scope drift detected?: no（排序/时间过滤按用户决策砍除）
```

## 实施结果

### M0 zhihu 物化路由（ca1d3a5）

- `inspect_zhihu.py`：网页表示升格为 `primary/primary_resource`（对知乎，页面即资源本体）。
- `planner.py`：新增 zhihu `primary_resource`/`landing_page` webpage → `generic-web-materializer` 两条 spec（containers: article/webpage/html）。

### M1 批量基座（09b1a93）

- `batch.py`：`run_batch_collect(directory, service=None)`——creator_full 模式，全量写 `results.jsonl`，job.json 终态含文件清单与条数；DOMAIN 错误/崩溃如实落 failures，绝不停留 running。
- `job_worker.py`：按 request.json 的 `kind` 分派（`batch_collect` → batch runner；缺省 → 原下载循环）。
- `service.py`：`batch_collect`（mode 白名单/creator_id 必填/max_items 1..1000 响亮校验）+ `batch_read`（分页 ≤50、拒绝非批量任务）。
- `server.py`：`resource_batch_collect` / `resource_batch_read` 两工具（工具面 7→9），instructions 增补批量引导。
- 取消链路：douyin/bilibili `search_creator` 分页循环接入 `cancel_event`；`MultiPlatformSearchProvider.search_creator` 透传。
- 文档：README 9 工具 + 批量两节；SKILL.md §8 创作者内容增补批量口径。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| `test_zhihu_materialize_routing.py` 3 项 | 全过 | zhihu primary webpage 精确路由到 materializer；检查器追加的表示 scope/role/container 正确 | 真实知乎页面物化质量（登录墙） |
| `test_batch_base.py` 4 项 | 全过 | 全链路（collect→run→status→分页读 complete 语义）；响亮参数校验；下载任务被 batch_read 拒绝；无 creator 能力平台如实 FEATURE_NOT_SUPPORTED | 跨进程 spawn（由 0057 复用 0056 的 spawn 机制，0056 已测） |
| 全量 pytest | 51 失败 = 既有基线，零新回归 | 未破坏既有行为 | — |
| stdio 真实 MCP | 9 工具；batch_collect 空参返回 INVALID_ARGUMENT | 公共表面与 schema 校验端到端有效 | — |
| 真实平台冒烟（bilibili UP 434377496，max_items=30） | 无 Cookie：0.3s 如实 `NETWORK_BLOCKED/HTTP 412`；挂 session-manager 库：**0.8s succeeded 30 条**，标题/作者/URL 落 results.jsonl | 真实 API 链路 + 共享登录态直接复用 + 错误分类诚实 | douyin 真实枚举；数百条长跑的中断/恢复 |

## 结果

M0/M1 完成：zhihu 可物化下载、批量基座上线（9 工具）、真实 B站枚举冒烟通过且复用同一登录库。后续里程碑（M2 smartedu、M3 douyin 图集/资料、M4 time_range/catalog_expand）按计划推进；部署（gateway stop → sync → restart）待用户确认时机。

---

## M2 / M4a / M4b 实施结果（2026-08-17）

### M2 smartedu 搜索分类 tabs（8d99691）

- `SearchTask.tabs` 可选字段（typed schema），smartedu 平台生效；service 校验、MultiPlatformSearchProvider 透传、adapter `_build_payload` 用传入 tabs（不传 = 26 全分类）。参考 fork client `_build_payload` 的 tab_codes 参数。

### M4a time_range_search 批量模式（d7fbe3a）

- bilibili adapter `search` 支持 `pubtime_begin_s/pubtime_end_s`（payload 透传）。
- 批量模式：keyword + start_day/end_day（YYYY-MM-DD，≤90 天）逐日枚举、去重、落盘；响亮入口校验。

### M4b catalog_expand 批量模式（e019b71）

- **纯 CDN JSON 路线**（修正早期"需浏览器"误判；参考实现为 `C:\Users\admin\projects\mediacrawler\tools\smartedu_batch_download.py`）。
- `discover_textbook_courses(specs)`：`data_version.json` → `part_*.json` tag 匹配（zxxxk/zxxnj/zxxcc/zxxbb + 新教材）→ `resources/part_100.json` national_lesson 课程；全走 `urlopen_with_fallback`，零浏览器。
- 批量模式：specs 入参 → 课程清单（title/activity_id/textbook/classActivity URL）→ results.jsonl。
- **真实冒烟**：`语文/一年级/上册/统编版` 免登录发现 45 门课程。
- CDP 抓包探测（`%TEMP%\cdp_probe*.py`）证实：SPA 页无列表 XHR（列表数据全部来自 CDN JSON），验证了参考结论。

## 验证（M2/M4a/M4b）

| Validation | Result | What it proves |
| --- | --- | --- |
| test_smartedu_tabs 4 项 | 全过 | tabs 流转、默认/忽略/响亮校验 |
| test_batch_time_range 4 项 | 全过 | 逐日窗口、去重、校验、平台拒绝 |
| test_batch_catalog 3 项 | 全过 | catalog 流转、specs 校验、错误平台拒绝 |
| 全量 pytest | 51 = 基线 | 零回归 |
| 真实 CDN 冒烟 | 45 课程（语文/一年级/上册/统编版） | CDN JSON 免登录可直调 |

## 结果（M2/M4a/M4b）

smartedu 分类过滤、B站时间范围全量、教材目录展开（纯 API）上线。M4b 确立 CDN 路线——目录展开无需浏览器。剩余：M3（douyin 图集，已按用户决策砍除）、M5（skill 退役，待确认）。部署待执行（gateway stop → sync → restart）。
