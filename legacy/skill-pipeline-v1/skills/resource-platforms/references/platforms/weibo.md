# 微博搜索

## 执行入口

- Adapter：`scripts/weibo/adapter.py`
- 搜索脚本：`scripts/weibo/weibo_search.py`
- 第三方依赖：无，仅使用Python标准库
- 认证：必须提供 `WEIBO_COOKIE` 或 `WEIBO_COOKIE_FILE`
- 计划参数：当前只使用关键词和 `max_results`

Cookie必须包含有效的`SUB`字段；如果包含`XSRF-TOKEN`，脚本同时设置`X-XSRF-TOKEN`请求头。Cookie文件保存浏览器请求头中的原始Cookie字符串。

## 搜索路径

调用`https://weibo.com/ajax/searchall`，每页请求10条并按页继续搜索，页间等待1秒，直到达到`max_results`或接口没有更多内容。CLI默认20条并限制在1–100。

结果以微博mid作为标识，优先构造用户ID和bid组成的原帖链接，否则使用详情地址；返回正文标题、摘要、作者、发布时间、图文或视频类型，以及点赞、评论和转发信号。

## 错误和限制

- 缺少`SUB`、HTTP 401/403、`ok=-100`或登录页：`AUTH_REQUIRED`。
- HTTP 418/429：`SEARCH_BLOCKED`，允许稍后重试。
- 非JSON响应或结构变化：解析或执行错误。

搜索入口不调用历史微博下载脚本，也不搜索用户主页或批量下载内容。

## 当前验证状态

独立搜索入口和结构化错误已经实现；本轮尚未使用当前有效Cookie完成真实结果验收。测试时应先确认Cookie仍有效，再判断接口或解析是否失效。
