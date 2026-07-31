# Bilibili 搜索

## 执行入口

- Adapter：`scripts/bilibili/adapter.py`
- 搜索脚本：`scripts/bilibili/bilibili_search.py`
- 签名模块：`scripts/bilibili/wbi_sign.py`
- 第三方依赖：无，仅使用 Python 标准库
- 认证：公开搜索通常无需登录；可选 `BILIBILI_COOKIE` 或 `BILIBILI_COOKIE_FILE`
- 计划参数：当前只使用关键词和 `max_results`

Cookie 文件保存浏览器请求头中的原始 Cookie 字符串。认证信息只从运行环境读取，不进入搜索计划、Stage 3 或日志。

## 搜索路径

1. 请求 `https://api.bilibili.com/x/web-interface/nav` 获取 WBI 图像密钥。
2. 对搜索参数生成 WBI 签名。
3. 调用 `https://api.bilibili.com/x/web-interface/wbi/search/type`，固定搜索视频并按综合相关度排序。

单页最多请求50条，按页继续获取直到达到 `max_results`、接口无结果或当前页不足。CLI默认20条并限制在1–100。

## 输出和错误

结果以 BV 号作为平台资源标识，返回标题、视频链接、简介、UP主、时长、封面、发布时间，以及播放、评论和收藏等平台信号。

- HTTP/API `-412`、`-352`：`SEARCH_BLOCKED`，允许稍后重试。
- HTTP 401/403或API `-101`、`-111`：`AUTH_REQUIRED`。
- WBI密钥缺失、非JSON响应或结构变化：返回对应执行或解析错误。

搜索入口不调用历史下载脚本，也不执行字幕、排行、下载或质量评分。

## 当前验证状态

2026-06-30使用公开WBI接口真实搜索成功，并在“小学古诗”测试计划中返回有效视频结果。Cookie仍可用于提高受限网络环境下的稳定性。
