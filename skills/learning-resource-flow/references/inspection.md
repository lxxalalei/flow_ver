# Inspection Guidance

Inspect 只用于确认会改变当前判断的事实，不是固定流程。

## 什么时候调用

调用：

```text
resource_inspect(resource_id=...)
```

适合这些情况：

- 搜索摘要不足以判断；
- 用户要求公开/无需登录/可直接访问；
- 需要确认真实文件或媒体格式；
- 需要区分正文资源和 landing page；
- 同名、版本、创作者等关键事实不清楚。

低潜候选、摘要已经够用、只是先看看时，不需要 Inspect。

## 返回事实

重点看：

- `status`
- `resource.availability`
- `resource.representations`
- 必要的 title/summary/creator/creator_id/language
- `failures`

不要寻找 fingerprint、resolution digest、inspector version、evidence snapshot 等内部证明字段。

## 与下载的关系

用户真正发起下载时，下载服务本身会 fresh Inspect。因此不要为了满足后端流程，在用户尚未需要这些事实时提前 Inspect 全部候选。

`resource_id` 是当前 MCP 进程里的资源句柄，只能来自 Search/Browse Creator。进程重启后失效就重新搜索，不做状态恢复链。
