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
resource_browse_creator
resource_inspect
```

OpenClaw 中的实际工具名带服务器前缀，例如：

```text
education-resources__resource_search
```

## 当前能力边界

- 搜索：`generic` 公开网页和已接入的平台 Adapter；平台可用性与授权状态由运行结果报告。
- 当前 active 契约目录：`mcp/education-resources/contracts/`。
- 当前公共 `contract_version` 为 `1.0.0`，`catalog_version` 为 `1.3.0`，catalog 与
  运行时共 13 个工具，包含 `resource_browse_creator` 和 `resource_inspect`。
- 平台能力、身份规则和平台级 descriptor 的机器事实以
  [`mcp/education-resources/contracts/platforms/platform-registry.json`](mcp/education-resources/contracts/platforms/platform-registry.json)
  为准；当前 Registry 是 `generic` 加 15 个内置平台，共 16 个条目。
- `retrieval/` 的 resource model、identity resolver 和保守 dedup 是 MCP 内部实现；
  `resource_search` 与 `resource_browse_creator` 共用这条规范化/去重路径，内部 identity
  不等于公共 `resource_id`，后者仍由服务端随机生成。
- 获取：文件型资源走 `direct_file`；普通文章等网页默认走静态 `web_materialize` 并产生
  可归档 ZIP；`web_capture` 只有受控内部调用显式选择时可用，不是静态失败的自动 fallback。
- 状态：SQLite 持有 Flow、ResultSet、Selection、Plan、Job、Asset、AssetBundle、归档和独立的
  `resource_resolutions`；migration 4 保存检索轮次、provenance、coverage 与私有 identity，
  当前最新 migration 5 保存 Bundle、成员角色与逐项失败关系。
- 二进制和大文件不进入对话上下文。
- `resource_inspect` 只接受 `contract_version`、`flow_id`、`resource_id`、`idempotency_key`；
  服务端从 Flow 资源取得来源。它不接受 URL、路径、批量 ID、depth 或凭据，不下载、不归档，
  也不返回 locator、文件字节或本地路径。Resolution 以 `resource_id + source_fingerprint +
  inspect-v1` 做成功/partial 缓存，unresolved 允许新幂等键重试。
- 0019 当前实现启用 generic、Bilibili、NLC、Anna/Libgen、Ximalaya、Zhihu、SmartEdu
  七类 Inspector；其他平台返回 `FEATURE_NOT_SUPPORTED`。Registry 和 descriptor 仍不作为
  平台级工具暴露。

工具表、资源类型、搜索/下载 Adapter 清单和契约一致性状态见
[当前架构事实快照](docs/CURRENT_ARCHITECTURE.md)。

不要直接运行 `legacy/` 中的脚本，不要让模型拼接 Python、Node、shell 或本地下载路径。
