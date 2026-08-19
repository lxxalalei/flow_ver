# 0062 — Bilibili 合集/系列展开

- 状态：in_progress
- 创建日期：2026-08-20
- 完成日期：未完成
- 范围：Bilibili 合集/系列容器枚举、现有 Batch Tool 接口、聚焦测试与 Skill 语义

## Goal

让用户给出 B 站合集/系列 URL 后，可以完整枚举其中的视频为普通 Resource 候选，并继续沿用现有“用户选择 → resource_download”链路。

## Non-goals

- 不新增 MCP Tool。
- 不引入 yt-dlp 运行时依赖。
- 不把合集混入 creator_full。
- 不自动下载合集内全部视频；Batch 只枚举候选。
- 不新增 Collection/Playlist 持久状态模型。
- 不实现收藏夹、稍后再看、番剧、课程等其他 B 站容器。
- 不改现有单视频 Inspect/Download 路径。

## Evidence

成熟实现已经存在：yt-dlp 当前包含 `BilibiliCollectionList` 与 `BilibiliSeriesList` extractor。

- 合集（season）分页接口：`/x/polymer/web-space/seasons_archives_list`
- 系列（series）分页接口：`/x/series/archives`

本实现只复用这些已验证的公开读取路径，不复制 yt-dlp 的完整 extractor 框架，也不新增 yt-dlp 运行时依赖。

## Business invariants

1. 合集/系列是 Container，不是 Creator。
2. `collection_expand` 只产生候选，不能授予下载意图。
3. 用户选择部分时通过 `resource_batch_read` 得到 resource_id 后下载；用户明确选择全部时才允许把完整 succeeded batch 交给 `resource_download(batch_job_id=...)`。
4. 完整枚举默认不传 `max_items`，直到 B 站分页真实结束。
5. B 站 API 返回真实认证/风控/网络错误时显式失败，不静默改走 creator_full 或普通搜索。

## Acceptance Criteria

- AC-01：`resource_batch_collect` 增加 `collection_expand` 模式，不新增 Tool。
- AC-02：支持新式 URL：`https://space.bilibili.com/<mid>/lists/<sid>?type=season`。
- AC-03：支持旧式合集 URL：`https://space.bilibili.com/<mid>/channel/collectiondetail?sid=<sid>`。
- AC-04：同一个入口可识别 `type=series` / `seriesdetail`，使用 series API，而不是误按合集接口处理。
- AC-05：分页直到 `archives` 结束/达到 API 报告 total，不做人为截断。
- AC-06：每个子项输出普通 Bilibili 视频 Resource（稳定 BV URL、标题、作者/发布时间等可得事实）。
- AC-07：非法或非 B 站集合 URL 明确 `INVALID_ARGUMENT` / `FEATURE_NOT_SUPPORTED`。
- AC-08：Batch 结果仍然只是候选，现有用户选择前置不变。
- AC-09：聚焦测试覆盖 season、series、分页终止、非法 URL 和 Tool schema。

## Implemented

- `BilibiliSearchAdapter.iter_collection()`：识别合集（season）和系列（series），分别调用成熟接口并分页到真实结束。
- URL 支持：新版 `/lists/<sid>?type=season|series`，以及旧版 `collectiondetail?sid=` / `seriesdetail?sid=`。
- `resource_batch_collect` 在原 Tool 内新增 `collection_expand` mode 与 `collection_url` 参数；Tool 总数保持 14。
- Batch worker 把每个子视频保存为普通 Bilibili Resource candidate，不产生下载副作用。
- Skill 明确：合集/系列/专辑/教材是内容容器，不是 Creator；完整展开后仍必须由用户选择才能下载。
- 新增离线聚焦测试，覆盖 URL 解析、season/series 接口路由、分页终止、Batch candidate-only 和 stdio schema。

## Steps

- [x] completed：核对现有仓库，确认 active Bilibili 代码只有 keyword/creator 枚举，没有合集展开
- [x] completed：核对成熟实现与 B 站现行读取接口
- [x] completed：实现 Bilibili collection/series iterator 与 Batch collection_expand
- [x] completed：补 Tool schema 与 Skill 容器语义
- [x] completed：补聚焦测试
- [ ] in_progress：在可运行仓库环境执行聚焦测试，并做至少一次真实 B站/OpenClaw 合集展开复测

## Validation

静态回读已确认：

- Bilibili Adapter 存在 `COLLECTION_URL` / `SERIES_URL` 和 `iter_collection()`；
- season 使用 `page.page_size / total`，series 使用 `page.size / total`；
- `BATCH_MODES` 包含 `collection_expand`；
- Tool schema 暴露 `collection_expand + collection_url`，Tool 名称集合不变；
- Batch worker 仍只写 `results.jsonl` 候选，不调用 Download；
- Skill 保留“用户选择后才下载”的语义边界。

待实际执行：

```text
pytest tests/test_bilibili_collection_expand.py tests/test_batch_base.py tests/test_mcp_stdio.py
```

当前执行容器仍无法直接取得该 GitHub 分支的仓库副本，因此 pytest **尚未实际执行**；不能把新增 fixture 测试写成已通过。真实 B 站/OpenClaw 合集展开也尚未执行。

## Result

代码与公共 Tool 契约已实现；计划保持 `in_progress`，直到聚焦测试和真实合集 URL 的 OpenClaw 链路有实际运行证据。