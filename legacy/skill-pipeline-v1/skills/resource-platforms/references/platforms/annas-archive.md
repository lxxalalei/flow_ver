# Anna's Archive 搜索

## 执行入口

- Adapter：`scripts/annas-archive/adapter.py`
- 搜索脚本：`scripts/annas-archive/annas_search.py`
- 第三方依赖：无，仅使用 Python 标准库（urllib）
- 认证：搜索无需认证；下载需 `ANNAS_SECRET_KEY`（由 resource-downloader 负责）
- 可选环境变量：`ANNAS_BASE_URL`（镜像地址，默认 `annas-archive.gl`）
- 计划参数：`core`（`book` 或 `article`，默认 `book`）

## 搜索路径

图书搜索：
`https://{base_url}/search?q={query}`

文章搜索：
`https://{base_url}/search?index=articles&q={query}`

脚本通过 HTTP 请求获取搜索结果 HTML 页面，使用正则解析结果块中包含的 MD5 哈希（图书）或 DOI（文章），提取标题、作者、语言、格式和大小等元数据。

## 资源标识

- 图书：`resource_id = annas-archive:{md5}`，`source_url` 指向 `/md5/{md5}` 详情页
- 文章：`resource_id = annas-archive:{doi_hash}`，`source_url` 指向 `/articles/{doi}` 详情页

## 资源类型

根据文件扩展名映射：
- pdf → PDF文档
- epub → EPUB文档
- mobi/azw3 → 电子书
- doc/docx → Word文档
- ppt/pptx → PPT课件
- 其他 → 文档

## 输出和错误

每条结果返回标准字段：`resource_id`、`platform`、`title`、`source_url`、`type`、`author`、`description`、`language`、`is_free`（始终为 `true`）、`download_feasibility`（默认"中"）、`raw_metadata`（包含 md5/doi、格式、大小）。

搜索页面可能返回 Cloudflare 或 DDoS 保护页面。脚本检测到拦截标记时返回空结果，Adapter 将记录为执行错误。

HTML 结构变化或反爬升级时可能导致解析失败，返回空结果。此时应检查 Anna's Archive 页面结构是否变更，并更新正则解析逻辑。

## 下载说明

下载功能不属于搜索层。`ANNAS_SECRET_KEY`（Anna's Archive API Key）和 `ANNAS_DOWNLOAD_PATH` 由 resource-downloader 在 Stage 5 使用，搜索阶段不涉及。

## 镜像选择

Anna's Archive 有多个镜像，可用性可能变化。通过 `ANNAS_BASE_URL` 环境变量可指定镜像。可用镜像列表可从 [SLUM](https://open-slum.org/) 获取。

## 当前验证状态

搜索功能基于 HTML 页面解析，Anna's Archive 的页面结构可能随时间变化。连续空结果时应检查：
1. 当前镜像是否可用
2. 页面 HTML 结构是否已更新
3. 是否触发反爬或 DDoS 保护
