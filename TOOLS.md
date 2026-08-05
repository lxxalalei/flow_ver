# TOOLS.md

本工作区唯一业务执行后端是 `education-resources` MCP。

## 工具

```text
resource_flow_start
resource_flow_status
resource_search
resource_presentation_save
resource_selection_save
resource_download_prepare
resource_download_start
resource_job_status
resource_job_cancel
resource_archive
resource_library_search
```

OpenClaw 中的实际工具名带服务器前缀，例如：

```text
education-resources__resource_search
```

## 当前能力边界

- 搜索：`generic` 公开网页和已接入的平台 Adapter；平台可用性与授权状态由运行结果报告。
- 当前 active 契约：`education-resources` v2.0.0，严格暴露 11 个工具。
- 下载：公开网页/文件直链，以及已接入且具备合法授权的平台下载器。
- 状态：SQLite 持有 Flow、Selection、Plan、Job、Asset 和归档。
- 二进制和大文件不进入对话上下文。

不要直接运行 `legacy/` 中的脚本，不要让模型拼接 Python、Node、shell 或本地下载路径。
