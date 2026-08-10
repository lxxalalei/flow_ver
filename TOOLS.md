# TOOLS.md

唯一业务执行后端是 `education-resources` MCP。OpenClaw 中工具名通常带服务器前缀，例如 `education-resources__resource_search`。

工具名称、版本、输入输出和副作用只以以下机器事实为准：

- [`mcp/education-resources/contracts/tool-catalog.json`](mcp/education-resources/contracts/tool-catalog.json)
- [`mcp/education-resources/contracts/schemas/`](mcp/education-resources/contracts/schemas/)
- [`mcp/education-resources/contracts/error-codes.json`](mcp/education-resources/contracts/error-codes.json)

服务安装、启动和验证见 [`mcp/education-resources/README.md`](mcp/education-resources/README.md)；文档导航见 [`docs/README.md`](docs/README.md)。

运行时不得让模型拼接 shell、Python、Node、脚本路径、本地下载路径、任意下载 URL 或伪造业务 ID/状态。有副作用的获取继续遵循 `prepare -> 用户明确确认 -> start`；归档只接受服务端返回并校验过的 `asset_id`。
