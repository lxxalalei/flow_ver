# TOOLS.md

运行时能力以 OpenClaw 实际暴露的 Tool `name / description / input schema / return` 为准；不要从历史 contracts、legacy 文件或旧计划猜测 Tool 参数和状态。

当前只有一个 active MCP：`education-resources`。

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
resource_archive
```

Session 辅助能力：

```text
resource_session_status
resource_session_login_guide
resource_session_save
resource_session_delete
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
| SmartEdu | `textbook`, `course` | `textbook → course[]`; `course → file[]` 尚未稳定落地 | course 可自然交付多文件 |
| Zjer | `course` | `video[]` | `video` → MP4 |
| CCTV | `column`, `series` | `video[]` | `video` → MP4（720P 上限） |
| LibGen | 无 | — | `book` → ebook file，身份为 MD5 |
| Generic Web | 无 | — | `webpage` → offline web bundle |
| Generic File | 无 | — | `file` → 原文件 |

### 当前明确 gap

- Ximalaya `creator → album[]`：尚未确认稳定、完整的主播专辑分页接口，因此当前显式不支持，不猜 API。
- SmartEdu `course → file[]`：Inspector 已能看到课程组成文件，但独立子文件还没有稳定 Resource 身份；课程本身仍可按自然交付方式下载多个真实文件。

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
creator -> album[]   # 当前实现 gap
album   -> track[]
track   -> Download
```

Downloader 只接受明确 `/sound/{track_id}`。专辑不会再静默退化成“第一集”，也不会从任意 URL 猜一个数字当 track id。

## CCTV

```text
column (栏目 /lm/ 页) -> Expand -> video[]   # 经 cctv-dl list
series (纪录片系列页) -> Expand -> video[]   # 页面内嵌剧集链接
video               -> Download MP4          # 经 cctv-dl，guid 为下载键
```

免登录。搜索双路：`ifsearch.php` 站内视频（叶子）+ `api.cntv.cn` 栏目目录（容器，A-Z 扫描后本地过滤）。单集/系列共用 `/YYYY/MM/DD/VID*.shtml` URL 形态，是否系列由页面真实剧集链接数（≥2）判定，不按 URL 猜测。画质上限 2000 档 720P。

依赖本地 `cctv-dl` 二进制（CCTVVideoDownloader）：路径用环境变量 `CCTV_DL_EXE` 覆盖，画质用 `CCTV_QUALITY`（默认 0=最高档）；缺失时显式 `PROVIDER_UNAVAILABLE`。下载产物经 ffmpeg 全片解码体检（错误行 ≤100），坏文件删除重试至多 3 次。已知边界：2021 年老视频的 h5e 确定性解密失败本 MCP 不做 WASM 备用降级，如实报错提示人工处理。

## SmartEdu

```text
textbook -> Expand -> course[]
course   -> Download -> 自然课程交付包（可能多个文件）
course   -> Expand -> file[]   # 待稳定 Resource 身份
```

新旧教材、六三/五四、版本、课程类型等属于平台返回事实，不作为公共 Tool 的 `tabs/specs/mode` 参数。

## LibGen

运行时平台身份为：

```text
platform = libgen
resource = book
identity = MD5
```

Search / Inspect / Download 走 LibGen mirror 路径，不依赖 Anna's Archive 会员页。当前下载 Provider 的少量历史内部类名仍可能保留，属于实现清理，不改变运行时平台身份。

## URL Import

已知 URL 可以直接进入资源系统，不要求先 Search。

当前识别包括：

- Bilibili video / creator / collection；
- Douyin video / creator / collection；
- Ximalaya track / album / creator；
- SmartEdu textbook / course；
- Zjer course；
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

`resource_session_save` 接收 opaque browser-session capture；Agent 不手工挑选 Cookie/Token。

## Generic Web Resource

Generic 网页物化当前产生：

```text
source.html
index.html
content.md
metadata.json
webbundle.zip
```

正文抽取失败不能删除已经成功抓取的 `source.html`。Reader 是清洗正文的离线阅读视图，不是原网页浏览器级镜像。

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
