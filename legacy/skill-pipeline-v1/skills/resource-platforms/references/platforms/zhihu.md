# 知乎搜索

## 执行入口

- Adapter：`scripts/zhihu/adapter.py`
- 搜索脚本：`scripts/zhihu/zhihu_search.py`
- 认证：必须提供 `ZHIHU_COOKIE` 或 `ZHIHU_COOKIE_FILE`
- 计划参数：当前只使用关键词和 `max_results`

Cookie 必须同时包含有效的 `z_c0` 和 `d_c0`；文件保存浏览器请求头中的原始 Cookie 字符串。认证信息只从环境读取。

## 搜索路径

1. 使用认证调用 `https://www.zhihu.com/api/v4/search_v3`。
2. API无结果时尝试知乎搜索页HTML解析。
3. 页面无结果时通过Bing、百度的 `site:zhihu.com` 查询发现公开链接。

API单页最多20条，按offset翻页直到达到 `max_results`。直接脚本默认20条。

## 输出和错误

支持文章、回答、问题和话题等类型，输出标题、真实知乎地址、摘要、作者、发布时间，以及点赞、评论等平台信号。搜索引擎降级结果元数据较少，但必须保留真实知乎地址。

- HTTP 401/403：`AUTH_REQUIRED`。
- HTTP 429：`SEARCH_BLOCKED`，允许稍后重试。
- 页面抓取常见403；缺少认证时Platform会在联网前返回`AUTH_REQUIRED`。

## 当前验证状态

2026-06-30使用有效 Cookie 真实搜索成功。未认证 API 会返回401/400，页面路径可能403，因此认证接口是当前稳定主路径。执行前检查 `z_c0` 和 `d_c0`；Cookie 过期后重新获取，不把降级路径声明为稳定替代。
