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
- adapters 增强：
  - bilibili：时间范围全量搜索（逐日分页，参考 pubtime_begin/end）、UP 主资料（wbi 签名复用现有 wbi.py）、画质选择接入 `preferred_container`；
  - douyin：`publish_time` 过滤参数、图集下载（现有 DouyinDownloader 扩展 images 类型）、创作者资料并入 browse_creator 返回；
  - zhihu：搜索过滤参数（时间/类型/排序）、回答/文章详情富化（inspect_zhihu 扩展）；
  - smartedu：分类 tabs 搜索参数、同步课堂目录展开（fork smartedu client 参考移植）、token 获取与现有 sessions 对齐。
- search task schema 增加可选过滤字段（typed，进 tools/list schema——沿用 1ee8eda 的教训：结构必须可见、错误必须响亮）。
- 文档：README 工具清单、SKILL.md 增补批量模式使用边界。

## Milestones（各自独立可交付）

- M1 批量基座：batch job 目录/状态/worker + `resource_batch_collect` / `resource_batch_read` 两工具 + 定向测试（fake provider 全链路）。
- M2 bilibili：时间范围全量、UP 资料、画质选择（真实平台验收）。
- M3 douyin：publish_time、图集下载、创作者资料。
- M4 zhihu：过滤参数、详情富化。
- M5 smartedu：tabs、目录展开、token 对齐。
- M6 退役：skill 从 Claude skills 目录移除（用户确认后）、文档收口。

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

待实现后填写。

## 实施结果 / 验证 / 结果

待实现后填写。
