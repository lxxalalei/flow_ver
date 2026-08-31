# TOOLS.md

运行时能力以 OpenClaw 实际暴露的 Tool `name / description / input schema / return` 为准；不要从历史 contracts、legacy 文件或旧计划猜测 Tool 参数和状态。

当前只有一个 active MCP：`education-resources`。

12 个 Tool 的自然语言触发、非触发、副作用、Job 和认证边界审计见
[`docs/MCP_CAPABILITY_INVENTORY.md`](docs/MCP_CAPABILITY_INVENTORY.md)。该清单是审计证据；
运行时事实仍以实际 Tool schema 和返回为准。

## 核心边界

Main Agent / Skill 负责：理解需求、设计搜索任务、判断相关性与覆盖 Gap、决定继续或停止、理解用户选择和获取意图。

MCP 负责：真实平台调用、结构展开、事实检查、下载、Job、归档和必要的 Session 状态。

> 语义判断上浮，平台机械事实下沉。

## 当前公共 Tool

资源能力：

```text
resource_search
resource_expand
resource_import_url
resource_inspect
resource_download
resource_job_status
resource_job_cancel
resource_job_read
resource_html_design
resource_archive
```

Session 辅助能力：

```text
resource_session_status
resource_session_manage
```

公共面不再暴露：

```text
resource_browse_creator
resource_batch_collect
resource_batch_read
creator_full
time_range_search
catalog_expand
collection_expand
start_day / end_day / specs / tabs
```

## Search / Expand / Inspect / Download

```text
Search   = 找到候选资源
Expand   = 向下展开容器资源的真实子资源
Inspect  = 获取会影响选择或下载的当前事实
Download = 物化用户明确选择的资源
```

它们不是固定流水线。

- 已知具体 URL 可以直接 Import，必要时 Inspect，然后 Download；
- 容器需要查看子资源时才 Expand；
- Inspect 只有未知事实会影响决策时才调用；
- Search/Expand 完成不等于用户授权下载。

`video / track / file / book` 等叶子资源不能借助 creator metadata 反向 Expand 到父对象。

## 大结果与 Job

Expand 是完整结构枚举能力。结果可以很大，因此：

```text
resource_expand(...)
  -> persistent job_id
  -> results.jsonl 保存完整结果

resource_job_read(job_id, offset, limit)
  -> 只读取当前需要进入模型上下文的一页
```

`resource_job_read` 的页大小只影响聊天上下文，不是数据总量上限。

用户只选择部分子资源时，读取足以定位这些对象的页，再：

```text
resource_download(resource_ids=[...])
```

用户明确说“全部下载”，且 Expand Job 已完整 `succeeded` 时，可以：

```text
resource_download(expand_job_id="...")
```

MCP 直接读取完整 `results.jsonl`。Expand 自身不产生下载授权。

## 当前主要平台资源视图

| 平台 | 容器 | Expand | 叶子 / 获取 |
| --- | --- | --- | --- |
| Bilibili | `creator`, `collection` | `video[]` | `video` → MP4 |
| Douyin | `creator`, `collection` | `video[]` | `video` → MP4 |
| Ximalaya | `creator`, `album` | `album[]` / `track[]` | `track` → MP3/M4A |
| SmartEdu | `textbook`, `course` | `textbook → course[]`; `course → video/document/audio[]` | course 可整体自然交付，也可下载稳定子文件 |
| Zjer | `course` | `video[]` | `video` → MP4 |
| CCTV | `column`, `series` | `video[]` | `video` → MP4（按真实流信息选择当前可确认的最高画质） |
| LibGen | 无 | — | `book` → ebook file，身份为 MD5 |
| Generic Web | 无 | — | `webpage` → offline web bundle |
| Generic File | 无 | — | `file` → 原文件 |

## Bilibili

```text
creator    -> Expand -> video[]
collection -> Expand -> video[]
video      -> Inspect(optional) -> Download
```

平台内部 season / series 区别不暴露给 Agent。当前不提供按日期完整搜索模式。

## Douyin

```text
creator    -> Expand -> video[]
collection -> Expand -> video[]
video      -> Download MP4
```

合集内部使用平台 `mix` 分页接口；`mix_id / cursor / has_more / a_bogus` 都属于 Adapter 机械事实，不进入公共 Tool schema。

## Ximalaya

```text
creator -> album[]
album   -> track[]
track   -> Download
```

主播展开使用喜马拉雅当前网页的 `/revision/user/pub` 分页接口，并以 `totalCount` 判断是否完整；分页提前结束会显式失败，不按网页 UI 的展示上限静默截断。Downloader 只接受明确 `/sound/{track_id}`。专辑不会再静默退化成“第一集”，也不会从任意 URL 猜一个数字当 track id。

## CCTV

```text
column (栏目 /lm/ 页) -> Expand -> video[]   # 公共 API getVideoListByColumn 分页
series (纪录片系列页) -> Expand -> video[]   # 页面内嵌剧集链接
video               -> Download MP4          # 自研下载链，guid 为下载键
```

免登录。搜索双路：`ifsearch.php` 站内视频（叶子）+ `api.cntv.cn` 栏目目录（容器，A-Z 扫描后本地过滤）。单集/系列共用 `/YYYY/MM/DD/VID*.shtml` URL 形态，是否系列由页面真实剧集链接数（≥2）判定，不按 URL 猜测。下载前比较 clear/H5E 实际流的分辨率与码率，按真实信息选择当前可确认的最高画质；不写死 2000/720P 画质上限。搜索候选的 `VIDE...` 标识在下载时自动解析为 32 位真实 guid。

**下载链**（全部自研，无外部下载器）：普通流（HLS/直链）Python 直下；H5E 加密流分片下载后使用 Python native 解密，再由 ffmpeg 封装并做全片解码体检。当前运行时不依赖旧 JS/WASM/Node compatibility fallback 或 `vendor/cctv-h5e`；native 解密或流协议不满足当前支持边界时显式失败，不静默切换不等价路线。下载结果保留实际 route 与体检事实。
## SmartEdu

```text
textbook -> Expand -> course[]
course   -> Download -> 自然课程交付包（可能多个文件）
course   -> Expand -> video/document/audio[]
file     -> Inspect/Download -> 当前单文件
```

新旧教材、六三/五四、版本、课程类型等属于平台返回事实，不作为公共 Tool 的 `tabs/specs/mode` 参数。

教材 Expand 匿名读取平台 CDN 连续分片，直到真实 404 或空分片。同步课和精品课生成真实子 Resource；`singing`、未来未知类型和无效条目不伪造 URL，计数写入 Expand Job 的 `summary.smartedu`。

课程文件子资源使用课程原生 ID + relation + 平台 item/group ID 形成稳定文件键；不保存签名 CDN URL。Inspect/Download 都重新读取课程 Detail 定位当前表示。同一视频的 MP4/HLS/清晰度变体保持一个逻辑子资源；没有平台稳定键的条目只保留在课程整体交付包中，并计入 Expand summary 的 `unstable_files`。

## LibGen

运行时平台身份为：

```text
platform = libgen
resource = book
identity = MD5
```

Search / Inspect / Download 统一走 LibGen mirror 路径；Provider、Inspector、Session 和测试只使用 `libgen` 身份。

## URL Import

已知 URL 可以直接进入资源系统，不要求先 Search。

当前识别包括：

- Bilibili video / creator / collection；
- Douyin video / creator / collection；
- Ximalaya track / album / creator；
- SmartEdu textbook / course；
- Zjer course；
- CCTV column / video；
- LibGen book URL；
- Zhihu；
- 其他 URL → generic。

URL 是到达资源的方式，不必等同于稳定资源身份。LibGen 的稳定身份就是 MD5。

## Resource 与 File

```text
1 Resource -> 0..N real files
```

`resource_inspect` 中的 Representation 是当前可获取事实；File 是 Provider 真正产生的交付物。

`preferred_container="original"` 表示按资源自身的自然交付方式获取。不要因为 landing URL 是网页就猜 `mp4/pdf`，也不要在指定格式不存在时静默回退。

## Session

Session Tool 不是 Search/Download 的固定前置流程。只有：

- 真实能力返回 `AUTH_REQUIRED`；或
- 用户明确要求登录态管理

时才使用。

`resource_session_status` 在指定平台且需要登录时直接返回登录步骤；全量查询不重复展开步骤。`resource_session_manage(action=save|delete)` 负责保存或删除；save 接收 opaque browser-session capture，Agent 不手工挑选 Cookie/Token。

## Generic Web Resource

Generic 网页物化当前产生：

```text
source.html   # 原始 HTML（保真，抽取失败也不丢）
index.html    # 单文件可读页（用户交付物，自包含）
content.md    # 清洗 Markdown
metadata.json # 物化事实
```

正文抽取失败不能删除已经成功抓取的 `source.html`。Reader 是清洗正文的离线阅读视图，不是原网页浏览器级镜像。

用户明确要求精美或内容感知的 HTML 时，在单网页 Download Job 完成后调用 `resource_html_design`：先读取有界 `context`，由 Agent 的 HTML Design Skill 判断主题、受众、页面任务与 DesignSpec，再由 `render` 将磁盘上的完整清洗正文原样注入 `adaptive-reader-v1`。默认下载不自动设计；`source.html` / `content.md` 始终不被模型改写。

## 不再使用的架构

不要恢复：

```text
Flow
ResultSet
Presentation
Selection state
Plan state
Eligibility
Authority
canonical/projection state
confirmation token
prepare-confirm-start
各种 binding/outcome digest
```

只持久化真实需要跨进程存在的 Download / Expand Job 和 Session。

当前语义规则见 `skills/SKILL.md`；当前实现边界见 `docs/CURRENT_ARCHITECTURE.md`。
