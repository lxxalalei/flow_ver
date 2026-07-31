# TOOLS.md

本工作区唯一业务执行后端是 `education-resources` MCP。

## 工具

```text
resource_flow_start
resource_search
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

- 搜索平台：`generic` 公开网页。
- 搜索引擎：DuckDuckGo、Bing。
- 下载：公开网页或公开文件直链。
- 状态：SQLite 持有 Flow、Selection、Plan、Job、Asset 和归档。
- 二进制和大文件不进入对话上下文。

不要直接运行 `legacy/` 中的脚本，不要让模型拼接 Python、Node、shell 或本地下载路径。
