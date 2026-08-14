# 0051 — 一席真实视频获取闭环

- 状态：in_progress
- 创建日期：2026-08-14
- 更新日期：2026-08-14
- 完成日期：未完成
- 真实样本：`speech_id=1435`，《教育就是生长》

## Objective

基于用户实际抓到的一席 `play_detail` 响应，把当前只有 Search 的一席平台补到可真实 Inspect / Prepare / Start / Asset 的视频获取链路。

## 已确认的平台事实

- 搜索已有 `YixiSearchAdapter`，可得到一席演讲 `id`。
- 真实播放详情接口：`/v3/api/h5/play_detail/?video_type=0&video_id=<id>&album_id=0`。
- 样本 1435 返回公开 MP4：标清、高清；超清 URL 为空；同时有公开 MP3。
- 当前 `InspectionResult` 公共契约禁止持久化动态 `url/source_url/download_url`，因此不能让 Inspector 把播放直链塞进 Representation。

## Implementation choice

本轮只完成视频主资源，不顺手扩音频产品语义：

1. `YixiSearchAdapter` 在构造候选时通过 `play_detail` 解析当前最高可用 MP4，并把该公开 MP4 作为资源的 `source_url`；保留 `speech_id` 作为平台身份事实。
2. 新增薄 `YixiInspector`：要求服务端 `speech_id`，并只允许一席公开域名；实际文件检查复用现有 bounded Generic inspection。
3. Planner 增加 `yixi + video/mp4 -> generic-direct@1.0.0` exact route。
4. Registry 把 yixi 加入 inspect-enabled 集合；不新增专用 Downloader。
5. 聚焦测试覆盖：搜索选择最高非空 MP4、Inspector 身份门槛、Planner exact route。

这样保持：一席特有逻辑只负责从 `speech_id` 找到实际 MP4；文件下载继续复用 `PublicHttpDownloader`。

## Non-goals

- 不新增 `YixiDownloader`。
- 不在 Representation 中泄漏媒体 URL。
- 不实现音频选择、清晰度 UI、多资源批量下载。
- 不修改其他平台行为。
- 不跑与本 diff 无关的全量测试。

## Completion criteria

- yixi Registry 正确声明 Inspect；
- `YixiInspector` 注册到默认 InspectionRouter；
- 搜索候选带稳定 `speech_id` 且 `source_url` 为最高可用公开 MP4；
- Planner 对 yixi video/mp4 选择 `generic-direct@1.0.0`；
- 真实 1435 可作为后续 OpenClaw `Search -> Inspect -> Prepare -> Confirm -> Start -> Asset` 复测样本；
- 只执行聚焦验证，无法执行时明确记录环境限制。
