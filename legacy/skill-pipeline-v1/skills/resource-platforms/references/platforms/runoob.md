# 菜鸟教程搜索

## 执行入口

- Adapter：`scripts/runoob/adapter.py`
- 搜索脚本：`scripts/runoob/runoob_search.py`
- 认证：无
- 计划参数：当前只使用关键词和 `max_results`

## 搜索路径

第一版使用菜鸟教程公开的服务端搜索页 `https://www.runoob.com/?s={query}`，解析真实教程结果，不采集页面中的 AI 回答区。结果包含标题、摘要、详情页和教程、实例、测验或文章类型。

搜索只发现公开网页，不执行代码、不登录、不下载站点内容。站内搜索通常只返回首批高相关结果，`max_results` 是上限而不是保证数量。

## 适用范围

只适合编程语言、Web 开发、数据库、数据结构、算法、开发工具和计算机基础等技术学习需求。它可以提供结构化教程、语法说明、示例和测验，不适合一般儿童成长、非技术学科或编程项目作品展示。

## 错误

- 请求超时：`NETWORK_TIMEOUT`
- HTTP 或连接失败：`NETWORK_ERROR`
- 页面结构变化：`SEARCH_EXECUTION_FAILED`
