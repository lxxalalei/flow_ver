# 抖音搜索

## 执行入口

- Adapter：`scripts/douyin/adapter.py`
- 搜索脚本：`scripts/douyin/douyin_search.py`
- 签名实现：`scripts/douyin/douyin_dl.py`中的`F2Engine`
- 依赖：Python包`f2`
- 认证：必须提供 `DOUYIN_COOKIE` 或 `DOUYIN_COOKIE_FILE`
- 计划参数：当前只使用关键词和 `max_results`

Cookie文件必须是浏览器请求头格式的单行纯文本：`name=value; name=value`，不能直接使用RTF表格。脚本可补充缺失的`ttwid`、`msToken`和`s_v_web_id`，但不能生成有效登录会话。

## 搜索路径

当前实现使用`f2`生成`a_bogus`签名，并调用：

`https://www.douyin.com/aweme/v1/web/search/item/`

每页最多15条，按offset继续获取，CLI默认20条并限制在1–100。结果提供视频ID、标题、作者、时长、播放和点赞信号。

## 错误和风险控制

- 无Cookie或状态码2483：`AUTH_REQUIRED`。
- 空响应、签名失效、验证码或其他风控：`SEARCH_BLOCKED`。
- Cookie、签名参数、User-Agent和网络环境不一致可能触发验证。
- 异常和日志不得输出Cookie、`msToken`、`a_bogus`或完整签名URL。

## 当前验证状态

2026-06-30真实请求能够到达接口，未登录时返回“请先登录，再继续搜索”。使用登录Cookie后HTTP 200且`status_code=0`，但响应包含`search_nil_info.search_nil_type=verify_check`并返回0条；当前搜索尚未验收为可用。

`f2`当前声明的`/aweme/v1/web/general/search/single/`端点也在同一环境触发`verify_check`。继续补少量Cookie字段不一定能解决，后续应优先验证真实浏览器会话方案。任何0条结果都必须检查`search_nil_info`，不能直接解释为没有内容。
