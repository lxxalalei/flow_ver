# 0052 — 之江汇课程视频获取链

- 状态：in_progress
- 创建日期：2026-08-15
- 更新日期：2026-08-15
- 完成日期：未完成
- 真实样本：`courseCateId=34941`，`聂卫平围棋道场名师课堂`
- 当前实现提交：`cf0ec153a1fd83d93f20a6fed0de26f89cc1c71b`

## Objective

基于用户实际抓到的之江汇课程详情与媒体响应，先完成有真实证据的课程视频获取链，不猜未确认的关键词搜索 API。

## 已确认的平台事实

课程详情接口：

```text
GET https://k.zjer.cn/api/s/c/courseAfter/<courseCateId>?id=<courseCateId>&shareId=
```

样本 `34941` 返回：

- `courseInfoList[]`：课时的 `courseInfo.id / uuid / videoId / videoSecond / courseName`；
- 当前带媒体详情的课时包含 `m3u8List[]` 与 `mp4List[]`；
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
size = 72781124
bitrate = 978
```

## Architecture decision

签名 URL 不能作为长期 Resource 身份或持久 Representation locator。

第一版链路：

```text
Zjer direct course lookup
→ courseCateId
→ course detail API
→ 对详情响应中已带可用 MP4 的课时生成独立 Resource
   （稳定 course/video identity，不保存 signed URL）
→ ZjerInspector 再读 detail API，确认 video/mp4 Representation
→ Planner: zjer + video/mp4 -> zjer-video@1.0.0
→ 用户确认
→ ZjerVideoDownloader 在 Start 时重新读 detail API
→ 获取最新 signed MP4 URL
→ 复用 PublicHttpDownloader
→ Asset
```

这意味着当前不会假设 `courseInfoList` 中每个只有课时元数据的条目都能由同一请求直接解析出媒体。后续若抓到“切换课时/按课时取播放信息”的真实请求，再扩到整个课程的所有课时。

## Current implementation

提交 `cf0ec153a1fd83d93f20a6fed0de26f89cc1c71b` 已完成：

1. 新增 `adapters/zjer.py`
   - 支持直接 `courseCateId` 或 `/courseAfter/<id>` URL；
   - 调真实课程详情接口；
   - 只为当前响应中已经存在有效 `mp4List` 的课时创建视频候选；
   - Resource 只保存稳定 `courseCateId / courseInfoId / videoId / UUID / 视频规格`，不保存签名媒体 URL。
2. 新增 `adapters/inspect_zjer.py`
   - 重新读取课程详情；
   - 按 `courseCateId + courseInfoId + videoId` 绑定课时；
   - 生成一个 `video/mp4` primary Representation；
   - Resolution 中不泄漏 `wkfile` signed URL。
3. 新增 `adapters/zjer_download.py`
   - Start 时再次读取课程详情；
   - 获取当时最新的签名 MP4 URL；
   - 实际字节下载复用 `PublicHttpDownloader`。
4. Planner 新增 exact route：

```text
zjer + primary_resource + video/mp4
→ zjer-video@1.0.0
```

5. Service 注册 `zjer-video@1.0.0` Provider。
6. runtime InspectionRouter 注册 `ZjerInspector`。
7. MultiPlatformSearchProvider 以 experimental direct-course 方式注册 Zjer，不把它伪装成已经完成原生关键词搜索的平台。
8. 新增聚焦测试，覆盖：
   - 34941 直接课程查询；
   - Resource/Resolution 不包含 signed URL；
   - 未确认关键词搜索时返回 `FEATURE_NOT_SUPPORTED`；
   - Inspector 生成 MP4 Representation；
   - Downloader 在 Start 时刷新签名 URL；
   - Planner exact route。

## Search boundary

当前没有用户抓到、也没有可靠证据证明稳定可用的之江汇“关键词课程搜索 API”。因此本轮 `ZjerSearchAdapter` 只支持：

- 直接 `courseCateId`；
- 用户提供的 `/courseAfter/<id>` 详情 URL / API URL。

普通自然语言关键词查询明确返回 `FEATURE_NOT_SUPPORTED`，不猜 `/list` 接口，不把网页搜索冒充平台原生搜索。

用户还抓到了：

```text
/api/s/c/courseAfter/courseWork/list?pageNum=...&courseCateId=...
```

但当前只知道请求 URL，没有足够证据证明它是课程关键词搜索或视频播放接口，因此本轮不使用。

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

## Validation checkpoint

已完成：

- GitHub detached compare 确认实现提交只涉及 8 个目标文件；
- `service.py` 最终 diff 为 `+14/-0`，没有发生大文件重写；
- `search.py` 为 `+14/-0`，Planner 为 `+11/-0`；
- 分支已推送 `cf0ec153...`；
- GitHub 当前没有返回可用 CI status。

未声称完成：

- 当前执行环境仍无法 DNS 解析 `github.com`，因此不能 clone 后运行 pytest；
- 尚未由用户在 Windows OpenClaw 跑真实 34941 下载闭环；
- 尚未确认原生关键词搜索接口；
- 尚未将 zjer 写入 broad Platform Registry。

## Non-goals

- 不实现 HLS / `.ts` 合并；
- 不下载整个课程的全部课时；
- 不持久化 signed MP4 URL；
- 不猜关键词搜索 API；
- 不修改 Service / Job / DB 的核心状态模型；
- 不跑无关全量测试。

## Completion criteria

- `34941` 可产生至少一个有真实 MP4 证据的课时候选；
- 候选不包含 `Signature/OSSAccessKeyId/Expires`；
- Inspector 可确认第一课 `video/mp4`；
- Planner 命中 `zjer-video@1.0.0`；
- Downloader 在执行时重新取详情并使用最新 MP4 签名地址；
- 用户可在 OpenClaw 对 34941 至少完成一次 `Search -> Inspect -> Prepare -> Confirm -> Start -> Asset`；
- 普通关键词搜索在原生接口未确认前不伪装为支持；
- 真实 E2E 后完成 broad Registry 最小对齐再归档本计划。
