---
name: resource-downloader
description: 成长资料下载调度器。读取用户已确认的资源，根据来源平台、资源页和已授权访问条件选择专属下载能力或通用下载方式，执行重试和 Level 0-3 降级，并输出完整下载结果。用于流水线 Stage 5，不负责搜索、筛选、评分或归档。
---

# resource-downloader

## 职责

负责：

- 读取 `stage4_selection.json` 中用户确认的资源 ID，并从 `stage3_search_results.json` 取得平台和来源信息。
- 根据 `platform` 选择专属 Platform 下载入口或通用方式。
- 控制批量下载、重试、超时、进度和降级。
- 将文件写入 `{session_dir}/downloads/`。
- 保留成功、降级和失败资源，写入 `stage5_download.json`。

不负责重新搜索、重新评分、替用户改变选择或把文件移入正式资料库。

本 Skill 拥有 `download/v1` 的输出格式。输入只引用 Stage 3 的来源信息和 Stage 4 的用户选择，不复制它们的完整资源字段。

模型负责本阶段的下载判断、工具调用、文件写入和结果组织；已有脚本是优先使用的可靠工具，不是必须经过的统一调度层。

## 输入

- 会话目录：绝对 `{session_dir}`。
- 输入文件：`{session_dir}/stage4_selection.json` 和 `stage3_search_results.json`。
- 输出文件：`{session_dir}/stage5_download.json`，Schema 为 `download/v1`。
- 下载目录：`{session_dir}/downloads/`。

只有 Stage 4 `data.status=selected` 且 `data.selected` 非空时执行。每个选择必须能按 `resource_id` 在 Stage 3 找到唯一资源。

## 执行流程

### 1. 确定下载通道

Downloader 不读取 Platform 的搜索注册表。模型根据资源页面、平台说明和当前可用访问条件判断下载路径：优先使用 `scripts/platforms/` 中已有的平台下载脚本；没有专属脚本时，根据 `references/download-methods.md` 选择合适的通用方法。来源 URL 只是候选入口，不把它当作保证可完整下载的直链。需要 Cookie、token 或浏览器会话时，只通过环境变量、配置或运行时会话传递，不写入阶段文件。

执行已有平台下载脚本前，由模型读取 Platform 共用的本地凭据约定和对应平台文档，再把当前下载需要的凭据注入环境变量。需要登录但凭据缺失或失效时，停止无意义重试并询问用户是否需要协助配置。配置完成后重新调用下载脚本；不把凭据写入下载结果或日志。

平台入口、认证和限制需要进一步确认时，按需读取 `../resource-platforms/references/platforms/{platform}.md`。

### 2. 执行与进度

- 逐条处理用户选择，必要时限制并发。
- 文件先写入临时目录，完成后再移动到 `{session_dir}/downloads/`。
- 每条资源始终产生一条结果，不因失败从数组删除。
- 进度只展示当前数量、标题和状态，不输出凭证或内部堆栈。

### 3. 重试

根据统一错误对象的 `retryable` 决定是否重试：

- 网络超时、连接失败：有限次数退避重试。
- 限流：降低频率并延迟重试。
- 登录过期：存在安全刷新路径时重试一次。
- 内容不存在、付费限制、DRM、验证码：不做无意义重试，直接进入降级或失败。

完整下载错误码与建议动作读取 `references/error-codes.md`。

### 4. Level 0-3 降级

| 等级 | 结果 |
|---|---|
| Level 0 | 完整原资源 |
| Level 1 | 官方预览、低清晰度或部分章节文件 |
| Level 2 | 可用正文、字幕、目录、音频或核心内容 |
| Level 3 | 元数据、摘要和来源链接 |

降级结果必须标记 `download_status=degraded`，说明原因，不能伪装成完整下载。具体资源类型的下载和转换方式见 `references/download-methods.md`。

### 5. 写入结果

每个选择只写一条增量结果，不复制 Stage 3 或 Stage 4 字段：

- `resource_id`
- `download_status`
- `files`
- `degraded_level`（仅降级时）
- `error`（降级或失败时）

Level 2/3 的正文、摘要或来源记录先保存成文件，再把路径写入 `files`，不要把大段内容嵌入阶段 JSON。

```json
{
  "_meta": {
    "schema_version": "download/v1",
    "session_id": "继承上游",
    "created_at": "ISO 8601"
  },
  "_summary": {
    "success_count": 1,
    "degraded_count": 0,
    "failed_count": 0
  },
  "data": {
    "results": [
      {
        "resource_id": "bilibili:BV1example",
        "download_status": "success",
        "files": ["/absolute/session/downloads/example.mp4"]
      }
    ]
  }
}
```

## 完成条件

- `data.results.length` 等于 Stage 4 的已选资源数。
- 每个已选 `resource_id` 恰好有一个结果。
- 成功或降级文件真实存在；失败结果的 `files=[]`。
- 所有失败或降级均有结构化原因。
- `_summary` 的三项计数必须能从 `data.results` 核对；只向 Flow 返回 `_summary` 和输出路径。

写入后运行：

```bash
python3 resource-downloader/scripts/validate_output.py {session_dir}
```

校验失败时修复一次；仍失败则向 Flow 返回失败，不进入归档。

## 参考资料

- `references/download-methods.md`：通用下载、转换和平台方法。
- `references/troubleshooting.md`：具体故障排查。
- `references/platform-download-contract.md`：平台下载脚本的接口约定。
- `references/error-codes.md`：下载错误码。
