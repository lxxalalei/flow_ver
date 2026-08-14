# 0051 — 一席真实视频获取闭环

- 状态：in_progress
- 创建日期：2026-08-14
- 更新日期：2026-08-14
- 完成日期：未完成
- 真实样本：`speech_id=1435`，《教育就是生长》
- 当前实现提交：`b62438ebb6cc4f8a60476046c7cf28b4333318b7`

## Objective

基于用户实际抓到的一席 `play_detail` 响应，把当前只有 Search 的一席平台补到可真实 Inspect / Prepare / Start / Asset 的视频获取链路。

## 已确认的平台事实

- 搜索已有 `YixiSearchAdapter`，可得到一席演讲 `id`。
- 真实播放详情接口：`/v3/api/h5/play_detail/?video_type=0&video_id=<id>&album_id=0`。
- 样本 1435 返回公开 MP4：标清、高清；超清 URL 为空；同时有公开 MP3。
- 1435 的媒体 URL 是 `alicdn.yixi.tv` 上无签名参数、无临时 token 的公开 MP4。
- 当前 `InspectionResult` 公共契约不持久化 `url/source_url/download_url`，因此媒体定位事实仍由 Resource 持有，不塞入 Representation。

## Current implementation

本轮只完成视频主资源，不顺手扩音频产品语义：

1. `YixiSearchAdapter` 在构造候选时调用 `play_detail`，过滤空 URL 和非一席公开域名，按 `type` 选择当前最高可用 MP4；1435 会选择高清 `1785913020293-3.mp4`。
2. Search 保留 `speech_id`、`video_duration`、`direct_video` 等平台事实；若某条 `play_detail` 临时失败，仍保留详情页候选，但不会冒充可下载视频。
3. 新增薄 `YixiInspector`：要求服务端 `speech_id` 和 `direct_video=true`，实际 HTTP / redirect / content 检查继续复用 `PlatformBoundedInspector`。
4. Planner 增加 `yixi + primary_resource + video/mp4 -> generic-direct@1.0.0` exact route；不新增 `YixiDownloader`。
5. 新增聚焦测试：最高非空 MP4、无视频时保留发现候选、Inspector 身份门槛、Planner exact route。

实际获取链：

```text
Yixi Search
→ speech_id
→ play_detail
→ 最高可用公开 MP4
→ YixiInspector
→ video/mp4 Representation
→ generic-direct@1.0.0
→ PublicHttpDownloader
→ Asset
```

## Registry alignment note

`retrieval/registry.py` 是约 100 KB 的旧兼容大文件。为避免为了增加一个平台 Inspect 能力而整文件重写，本提交没有把临时的大文件替换推入分支；当前 `inspection_registry.py` 明确把 `yixi` 加入 runtime inspection set，保证真实链可测试。

后续在完成 1435 实际 E2E 后，再以真正的最小行级 diff 把广义 Platform Registry 的 yixi `inspect` 声明与 runtime 对齐。这个未对齐项必须在本计划归档前清掉。

## Non-goals

- 不新增 `YixiDownloader`。
- 不在 Representation 中泄漏媒体 URL。
- 不实现音频选择、清晰度 UI、多资源批量下载。
- 不修改 Service / Job / DB 主链。
- 不跑与本 diff 无关的全量测试。

## Validation checkpoint

已完成：

- GitHub compare：实现提交只改 5 个目标文件；
- 分支读回确认 Search / Inspector / Planner 已落盘；
- commit status 当前没有可用 CI checks；
- 临时 `retrieval/registry.py` 大改候选未挂到分支。

待完成：

- OpenClaw 用 1435 跑 `Search -> Inspect -> Prepare -> Confirm -> Start -> Asset`；
- 真实 E2E 通过后对齐 Platform Registry 的 yixi inspect 声明；
- 再归档本计划。
