# 平台搜索接口

## 上游任务

每个平台任务包含 `platform`、`priority` 和一个或多个 `searches`。每次调用包含 `query`、`max_results`，以及平台真实支持时才出现的 `params`。

Platform 不修改查询，不从 Intent 补充条件。

## Adapter 返回

```json
{
  "results": [
    {
      "resource_id": "bilibili:BVxxxx",
      "platform": "bilibili",
      "title": "四年级数学知识点讲解",
      "source_url": "https://...",
      "type": "视频",
      "platform_signals": {"views": 10000}
    }
  ],
  "error": null
}
```

资源必填字段只有 `resource_id`、`platform`、`title`、`source_url`。可选字段已知时才输出：`type`、`description`、`author`、`duration`、`publish_time`、`is_free`、`language`、`thumbnail_url`、`download_feasibility`、`platform_signals`、`raw_metadata`。

`raw_metadata` 只保存后续阶段确实需要且没有标准字段承载的信息，不倾倒完整平台响应。

`platform_signals` 只保留播放、点赞、评论、收藏、认证、集数等平台事实。平台脚本自行推算的质量分或等级不得进入 Stage 3，最终质量判断由 Selector 完成。

失败时 `results=[]` 并返回统一 `error`。部分结果可用时允许同时返回结果和错误。

运行依赖和认证环境变量由 `config/search-registry.json` 声明。Stage 2 只传搜索参数，不传 Cookie、Token、请求头或浏览器状态。

## Stage 3

执行器把所有 adapter 响应汇总到：

```json
{
  "_meta": {
    "schema_version": "platform-results/v1",
    "session_id": "继承 Stage 2",
    "created_at": "ISO 8601"
  },
  "_summary": {
    "resource_count": 1,
    "failed_platforms": []
  },
  "data": {
    "resources": [],
    "errors": []
  }
}
```

Platform 只能做平台内精确去重。跨平台相似判断、相关性过滤和质量评分由 Selector 完成。
