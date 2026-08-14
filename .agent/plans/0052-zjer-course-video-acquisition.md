# 0052 — 之江汇课程视频获取链

- 状态：in_progress
- 创建日期：2026-08-15
- 更新日期：2026-08-15
- 完成日期：未完成
- 真实样本：`courseCateId=34941`，`聂卫平围棋道场名师课堂`

## Objective

基于用户实际抓到的之江汇课程详情与媒体响应，先完成有真实证据的课程视频获取链，不猜未确认的关键词搜索 API。

## 已确认的平台事实

课程详情接口：

```text
GET https://k.zjer.cn/api/s/c/courseAfter/<courseCateId>?id=<courseCateId>&shareId=
```

样本 `34941` 返回：

- `courseInfoList[]`：每节课的 `courseInfo.id / uuid / videoId / videoSecond / courseName`；
- `m3u8List[]`：HLS 播放列表；
- `mp4List[]`：直接 MP4；
- MP4 / m3u8 URL 位于 `wkfile.zjer.cn`；
- URL 带 `Expires + OSSAccessKeyId + Signature`，属于临时签名地址；
- 同一视频存在 MP4 时，第一版无需处理 `.m3u8/.ts`。

真实第一课：

```text
courseCateId = 34941
courseInfoId = 187893
videoId = 181840
courseName = 第1课 围棋的起源、规则与气
format = mp4
resolution = 960x540
```

## Architecture decision

签名 URL 不能作为长期 Resource 身份或持久 Representation locator。

第一版链路：

```text
Zjer direct course lookup
→ courseCateId
→ course detail API
→ 每节课生成独立 Resource（稳定 course/video identity，不保存 signed URL）
→ ZjerInspector 再读 detail API，确认 video/mp4 Representation
→ Planner: zjer + video/mp4 -> zjer-video@1.0.0
→ 用户确认
→ ZjerVideoDownloader 在 Start 时重新读 detail API
→ 获取最新 signed MP4 URL
→ 复用 PublicHttpDownloader
→ Asset
```

## Scope

本轮：

1. 增加 `zjer.py`：课程详情解析、按 `courseCateId` / 详情 URL 展开课时资源；
2. 增加 `ZjerInspector`：按稳定 `courseCateId + courseInfoId + videoId` 重新确认 MP4；
3. 增加薄 `ZjerVideoDownloader`：Start 时刷新签名 URL，然后复用公共 HTTP 下载；
4. Planner 增加 exact `zjer-video@1.0.0` 路由；
5. Service 注册 Provider；
6. runtime InspectionRouter 注册 zjer；
7. 聚焦测试使用用户提供的 34941 响应结构。

## Search boundary

当前没有用户抓到、也没有公开证据证明稳定可用的之江汇“关键词课程搜索 API”。因此本轮 `ZjerSearchAdapter` 只支持：

- 直接 `courseCateId`；
- 用户提供的 `/courseAfter/<id>` 详情 URL / API URL。

普通自然语言关键词查询明确返回 `FEATURE_NOT_SUPPORTED`，不猜 `/list` 接口，不把网页搜索冒充平台原生搜索。

抓到真实课程列表/搜索请求后，再把同一 Adapter 扩到关键词搜索。

## Registry note

当前 `retrieval/registry.py` 是大型旧兼容文件，且 yixi runtime 已存在尚未回填的 Registry Inspect 差异。本轮不为了 zjer 再制造一次大文件重写。

在真实 zjer E2E 和原生搜索接口确认后，单独用最小 diff 一次性完成：

- yixi Inspect Registry 对齐；
- zjer 平台 Registry entry；
- schema 平台数；
- `EXPECTED_PLATFORM_IDS / INSPECTION_PLATFORM_IDS`；
- 平台 Registry 聚焦测试。

在此之前 zjer 属于 runtime experimental integration，不宣称完整 active platform。

## Non-goals

- 不实现 HLS / `.ts` 合并；
- 不下载整个课程的全部课时；
- 不持久化 signed MP4 URL；
- 不猜关键词搜索 API；
- 不修改 Service / Job / DB 的核心状态模型；
- 不跑无关全量测试。

## Completion criteria

- `34941` 可展开成独立课时候选；
- 候选不包含 `Signature/OSSAccessKeyId/Expires`；
- Inspector 可确认第一课 `video/mp4`；
- Planner 命中 `zjer-video@1.0.0`；
- Downloader 在执行时重新取详情并使用最新 MP4 签名地址；
- 用户可在 OpenClaw 对 34941 至少完成一次 `Search -> Inspect -> Prepare -> Confirm -> Start -> Asset`；
- 普通关键词搜索在原生接口未确认前不伪装为支持。
