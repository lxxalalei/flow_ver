# 百度文库搜索

## 执行入口

- Adapter：`scripts/baiduwenku/adapter.py`
- 搜索脚本：`scripts/baiduwenku/baiduwenku_search.py`
- 认证：无本地认证要求
- 计划参数：当前只使用关键词和 `max_results`

## 搜索路径

1. 请求 `https://wenku.baidu.com/search?word={query}`。
2. 解析页面内嵌的 `window.pageData` / `PCSearch` 搜索结果数据。
3. 仅返回公开详情页候选，不下载文档，不判断免费、完整或可下载。

## 输出

每条结果输出标题、文库详情页 URL、摘要、封面图、站内排名，并在 `raw_metadata` 中保留文档 ID、文件类型、页数、付费类型、平台质量分等少量排查字段。

百度文库只作为文档、讲义、课件、补充材料的候选发现渠道。结果是否适合孩子使用、是否完整、是否免费、是否可归档，需要后续人工或归档阶段确认。

## 错误

- 百度安全验证、验证码、风控页：`SEARCH_BLOCKED`
- 请求超时：`NETWORK_TIMEOUT`
- 页面结构变化导致无结果：`SEARCH_NO_RESULTS` 或 `SEARCH_EXECUTION_FAILED`
