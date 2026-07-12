---
name: resource-downloader
description: 成长资料下载调度器。用于流水线 Stage 5，读取用户已确认的资源，自动选择平台单资源下载、公开文件直链或网页正文归档，校验文件真实格式和完整性，执行受控重试与 Level 0-3 降级并输出下载结果。不负责搜索、筛选、评分或正式归档。
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

模型通常只需列出待下载的 `resource_id`；`scripts/run_download_plan.py` 默认使用 `auto` 自动选择平台下载、文件直链或网页归档。只有用户明确限制结果形态时，模型才覆盖策略。执行器是唯一执行入口，负责工具调用、临时目录、超时、文件校验、降级和结果写入。模型不得直接运行平台下载命令或手工写 `stage5_download.json`。

## 输入

- 会话目录：绝对 `{session_dir}`。
- 输入文件：`{session_dir}/stage4_selection.json` 和 `stage3_search_results.json`。
- 输出文件：`{session_dir}/stage5_download.json`，Schema 为 `download/v1`。
- 执行计划：`{session_dir}/download_plan.json`，Schema 为 `download-plan/v1`。
- 下载目录：`{session_dir}/downloads/`。

只有 Stage 4 `data.status=selected` 且 `data.selected` 非空时执行。每个选择必须能按 `resource_id` 在 Stage 3 找到唯一资源。

## 执行流程

### 1. 生成下载计划

每个 Stage 4 选择恰好写一项。`strategy` 可省略，省略时默认为 `auto`：

- `auto`：优先使用适用的平台入口；无入口时根据 URL 选择文件直链或网页归档，并执行受控降级。
- `platform`：使用受支持的平台单资源下载入口。
- `direct`：仅用于确认是公开 `http/https` 文件直链的资源。
- `webpage`：保存公开来源页 HTML、可读 Markdown 和页面元数据，结果为 Level 2。
- `metadata`：明确只保存标题、简介和来源链接，结果为 Level 3 降级。

```json
{
  "_meta": {"schema_version": "download-plan/v1", "session_id": "继承 Stage 4"},
  "data": {
    "items": [
      {
        "resource_id": "bilibili:BV1example",
        "strategy": "auto",
        "allow_metadata_fallback": true
      }
    ]
  }
}
```

凭据只通过环境变量或已有安全会话提供，不写入计划。没有明确要求时使用 `auto`；只有已确认文件直链时才显式使用 `direct`。

`formats` 只传给明确支持源格式筛选的平台入口；需要约束最终文件格式时使用 `expected_formats`。两者都不是必填字段。

通用 HTTP 下载默认只访问公网地址，并检查重定向目标；本机、内网和保留地址不会自动访问。确有受信任内网资料需求时，只能由运行环境显式设置 `LRS_ALLOW_PRIVATE_NETWORK=1`。

### 2. 统一执行

```bash
python3 resource-downloader/scripts/run_download_plan.py {session_dir}
```

执行器保证文件先写入 `{session_dir}/downloads/.partial/`，完成格式、内容和符号链接检查后再原子提交到正式下载目录。任何成功或降级文件都必须位于本次会话 `downloads/`；不允许引用电脑中的既有外部文件。

### 3. 错误和降级

执行器负责将依赖、认证、超时、付费、格式损坏和下载失败转换为结构化错误。`auto` 会按“平台或文件 → 网页正文 → 元数据”降级；`allow_metadata_fallback=true` 时最终失败会保存 `source.md` 并输出 Level 3，否则输出失败。执行器不绕过登录、付费墙、DRM、验证码或其他访问控制。

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

正常流程直接运行统一执行器；需要独立复核时运行：

```bash
python3 resource-downloader/scripts/validate_output.py {session_dir}
```

校验失败时修复一次；仍失败则向 Flow 返回失败，不进入归档。

## 参考资料

- `references/download-methods.md`：通用下载、转换和平台方法。
- `references/troubleshooting.md`：具体故障排查。
- `references/platform-download-contract.md`：平台下载脚本的接口约定。
- `references/error-codes.md`：下载错误码。
- `schemas/download-plan.schema.json`：模型可写的受限下载计划。
- `scripts/run_download_plan.py`：唯一下载执行入口。
