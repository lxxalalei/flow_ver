# 科普中国搜索

## 执行入口

- Adapter：`scripts/kepu/adapter.py`
- 搜索脚本：`scripts/kepu/kepu_search.py`
- 认证：无本地认证要求
- 计划参数：当前只使用关键词和 `max_results`

## 搜索路径

第一版使用科普中国公开搜索页：

`https://www.kepuchina.cn/search/index?search={query}&search_type=0`

脚本解析服务端返回的搜索结果卡片，输出文章/视频标题、详情页、摘要、来源、发布日期、封面和关键词。当前不聚合中国数字科技馆，因为实测公开搜索入口会循环重定向，暂不够稳定。

## 适用范围

适合科学现象、自然常识、STEM、青少年科普图文和科普视频线索。它补充公共科普来源，不替代教材、课程平台或实验视频平台。

## 错误

- 安全验证、验证码、风控页：`SEARCH_BLOCKED`
- 请求超时：`NETWORK_TIMEOUT`
- 页面结构变化导致无结果：`SEARCH_NO_RESULTS` 或 `SEARCH_EXECUTION_FAILED`
