# 国家中小学智慧教育平台搜索

## 执行入口

- Adapter：`scripts/smartedu/adapter.py`
- 搜索脚本：`scripts/smartedu/smartedu_resources.py search-resources`
- 计划参数：当前只使用关键词和 `max_results`
- Adapter超时：注册表配置90秒

Adapter固定以家长身份调用跨租户资源搜索，只传递查询词和结果上限。站点扫描、栏目画像、教材索引、详情探测等其他子命令是维护工具，不属于 Stage 3 搜索入口。

## 认证

搜索使用 `SMARTEDU_ACCESS_TOKEN`。模型从本地凭据约定取得 Access Token，并在调用统一执行器时注入环境变量。传输层把它同时写入 `Authorization: Bearer ...` 和 `accessToken` 请求头。认证值不得写入计划、结果或日志。

## 搜索路径

按顺序尝试三个资源聚合接口：

1. `x-search.ykt.eduyun.cn/v1/resources/combine/search`
2. `resource-gateway.ykt.eduyun.cn/resources/combine/search`
3. `resource-gateway.ykt.eduyun.cn/resources/aggregate`

正常Adapter不启用深度搜索，只取 `--limit max_results`。SmartEdu API单页上限100、offset和limit合计不超过200；深度分页功能只供维护命令显式启用。

## 输出和错误

搜索结果归一化为标题、官方详情页、资源类型、格式、学段、年级、学科、版本、册次、来源和访问量等字段。没有从接口获得的信息不得根据查询词补造。

接口全部失败、认证失效或返回结构变化时由脚本返回失败；Adapter不得降级到下载、教材同步或浏览器抓取流程。

## 当前验证状态

2026-07-01使用公开接口真实搜索“小学古诗”成功，直接脚本与统一Adapter均返回5条并完成标准化；抽查的三个课程详情链接均能打开并显示正确的年级、册次和课时信息。未登录浏览器只能查看课程信息，微课视频、任务单和作业入口会要求登录。

Access Token 的请求头传递已经接入搜索传输层。仍需用当前有效 Token 对受限资源进行真实验收；公开搜索成功不能单独证明 Token 有效。
