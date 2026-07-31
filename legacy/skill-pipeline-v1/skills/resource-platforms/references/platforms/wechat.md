# 微信公众号搜索

## 执行入口

- Adapter：`scripts/wechat/adapter.py`
- 搜索脚本：`scripts/wechat/search_wechat.js`
- 第三方依赖：Node.js；脚本不依赖 npm 包
- 认证：通常不需要；可选 `SOGOU_WEIXIN_COOKIE`
- 计划参数：`resolve_url` / `resolve_real_url` / `real_url`

Adapter 通过搜狗微信搜索页发现微信公众号文章，返回文章标题、搜狗中转链接或真实微信文章链接、摘要、公众号名和发布时间。默认不解析真实微信文章 URL，以降低请求量和触发反爬的概率；调用方明确传入 `resolve_url=true` 时，脚本会尝试把搜狗中转链接解析为 `mp.weixin.qq.com` 链接。

## 搜索路径

请求搜狗微信文章搜索页：

`https://weixin.sogou.com/weixin?query={keyword}&type=2&page={page}&ie=utf8`

脚本会先尝试获取搜狗会话 Cookie；如果环境变量 `SOGOU_WEIXIN_COOKIE` 已设置，则优先使用该值。单页通常返回 10 条，脚本按页请求直到达到 `max_results`，最多返回 50 条。

## 输出和错误

每条结果标准化为：

- `platform=wechat`
- `type=文章`
- `title`
- `source_url`
- `description`：搜索结果摘要
- `author`：公众号名
- `publish_time`
- `platform_signals.engine=sogou-weixin`
- `platform_signals.rank`

`raw_metadata` 只保留 `query`、`date_text`、`date_description`、`url_resolved` 等排查字段。

搜狗验证码、反爬或访问频率限制返回 `SEARCH_BLOCKED`；请求超时返回 `NETWORK_TIMEOUT`；Node.js 不存在返回系统执行错误或工具缺失。

微信公众号搜索只负责发现文章链接；正文抽取、下载和归档交给后续归档能力。
