# 央视网搜索

## 执行入口

- Adapter：`scripts/cctv/adapter.py`
- 搜索脚本：`scripts/cctv/cctv_search.py`
- 第三方依赖：无，仅使用 Python 标准库
- 认证：不需要
- 计划参数：默认只使用关键词和 `max_results`；可选 `type=video|audio`、`channel`

## 搜索路径

第一版使用央视搜索页背后的公开 JSON 接口：

`https://search.cctv.com/ifsearch.php`

固定参数：

- `sort=relevance`
- `datepid=1`
- `vtime=-1`
- `type=video`（默认）

分页参数：

- `page` 从 1 开始
- `pageSize` 按 `max_results` 截断，单页最多 20

脚本会按页请求直到达到 `max_results`、接口无更多结果或 `totalpage` 结束。接口最多按站点返回 50 页，脚本不绕过该限制。

## 输出和错误

结果以 CCTV 搜索结果 `id` 作为资源标识，返回标题、公开视频页、频道、缩略图、时长和发布时间。标题优先使用 `all_title`，并清理搜索高亮 HTML。

字段映射：

- `all_title/title` → `title`
- `urllink` → `source_url`
- `imglink` → `thumbnail_url`
- `channel` → `provider`
- `durations` → `duration`
- `uploadtime` → `publish_time`

搜索入口只发现公开音视频结果，不解析真实播放流、不下载视频，也不做最终质量评分。

HTTP 403/429 视为 `SEARCH_BLOCKED`，网络超时视为 `NETWORK_TIMEOUT`，非 JSON 或结构变化视为 `PARSE_FORMAT_NOT_SUPPORTED`。

## 当前验证状态

2026-07-08 真实请求 `数学`、`科普` 成功，`ifsearch.php` 返回标准 JSON 和公开视频页链接。CCTV 结果偏新闻和节目片段，Selector 需要按儿童成长主题继续筛选。
