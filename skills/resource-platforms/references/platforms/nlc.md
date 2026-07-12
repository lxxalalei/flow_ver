# 中国国家图书馆搜索

## 执行入口

- Adapter：`scripts/nlc/adapter.py`
- 搜索脚本：`scripts/nlc/nlc_search.py`
- 认证：无
- 计划参数：`scope=catalog|site|digital|ebook`，默认 `catalog`

## 馆藏目录

`scope=catalog` 使用文津搜索公开结果页，返回中国国家图书馆馆藏中文资源（`ucs01`）和馆藏外文资源（`ucs09`）的书目候选。结果包含标题、文献类型、著者、出版年份、出版社、来源数据库、封面和稳定详情页。

文津搜索还聚合其他外部数据库。第一版只保留 `ucs01`、`ucs09`，避免把外部联合检索结果误标为国家图书馆馆藏。在线阅读和数字资源访问可能需要登录，搜索结果统一标记为低下载可行性。

## 站内搜索

`scope=site` 使用国家图书馆官网公开 JSON 搜索接口，查找展览、活动、服务、新闻和网站专题。它不搜索馆藏书目，只有需求明确指向国家图书馆网站内容时使用。

## 阅文数字电子书

`scope=digital` 或别名 `scope=ebook` 使用 `read.nlc.cn/yuewen/` 的公开列表页搜索数字电子书。结果使用 `resource_id=nlc:yuewen:{id}`，`source_url` 指向稳定详情页，并标记公开访问；是否实际提供 EPUB 由下载时的阅读页格式声明确认。

阅文 EPUB 下载不需要登录，平台入口为 `resource-downloader/scripts/platforms/nlc_download.py`。下载器只使用 Python 标准库和 `CookieJar`，按 `read -> readContent -> download` 流程取得公开 EPUB，并校验 ZIP 与 `mimetype`。不处理 `advanceSearch` 扫描 PDF，不使用 Playwright，也不绕过登录、IP、付费或其他访问控制。

## 暂不支持

- 原始 OPAC 的随机会话链和数据库切换。
- 特色资源 `advanceSearch` 的会话式高级搜索、Playwright 和扫描 PDF 下载。
- 需要登录、IP 权限、付费、验证码或其他访问控制的内容。

## 错误

- 请求超时：`NETWORK_TIMEOUT`
- HTTP 或连接失败：`NETWORK_ERROR`
- 接口或页面格式变化：`PARSE_FORMAT_NOT_SUPPORTED` 或 `SEARCH_EXECUTION_FAILED`
