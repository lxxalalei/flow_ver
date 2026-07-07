# 平台下载接口契约

本契约用于 Downloader 调用已有平台下载脚本时约束单资源结果。重试、降级选择和最终 Stage 5 文件由 Downloader 负责。

## 输入

```json
{
  "resource_id": "bilibili:BV1example",
  "source_url": "https://www.bilibili.com/video/BV1example",
  "output_dir": "/absolute/session/downloads",
  "params": {"quality": "auto"}
}
```

| 字段 | 必填 | 说明 |
|---|:---:|---|
| `resource_id` | 是 | Stage 3 稳定 ID |
| `source_url` | 是 | 原始来源地址 |
| `output_dir` | 是 | 绝对下载目录 |
| `params` | 否 | 只有当前平台入口明确支持时才传递 |

调用哪个 adapter 已经确定平台，因此不重复传 `platform`。超时、重试次数、认证和是否降级属于运行配置，不写入资源数据；凭证只通过安全运行环境传递。

## 输出

成功：

```json
{
  "resource_id": "bilibili:BV1example",
  "download_status": "success",
  "files": ["/absolute/session/downloads/example.mp4"]
}
```

降级：

```json
{
  "resource_id": "bilibili:BV1example",
  "download_status": "degraded",
  "degraded_level": "Level 2",
  "files": ["/absolute/session/downloads/example-summary.md"],
  "error": {
    "error_code": "CONTENT_PREMIUM_ONLY",
    "message": "原文件需要付费，已保存公开摘要",
    "retryable": false
  }
}
```

失败：

```json
{
  "resource_id": "bilibili:BV1example",
  "download_status": "failed",
  "files": [],
  "error": {
    "error_code": "CONTENT_NOT_FOUND",
    "message": "内容不存在或已删除",
    "retryable": false
  }
}
```

规则：

- `success`：至少一个真实文件，不写 `degraded_level` 或 `error`。
- `degraded`：`degraded_level` 为 Level 1—3，至少一个保存降级内容的文件，并提供 `error` 说明原因。
- `failed`：`files=[]`，必须提供 `error`。
- Level 2/3 内容必须先落盘，不把大段正文嵌入接口 JSON。
- 文件大小、格式和校验值按需从文件读取，不作为跨 Skill 必填字段。
- 平台入口不推荐替代资源、不生成最终质量等级、不决定归档位置。

错误码统一见 `error-codes.md`。
