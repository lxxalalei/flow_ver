# Education Resource MCP Contracts

`contracts/` 保存教育资源 MCP 的稳定领域契约。它只描述 OpenClaw Skill 与
MCP 服务之间的公共边界，不描述平台 Adapter、命令行参数、下载目录或服务端
实现细节。

当前版本：`v1`（协议版本 `1.0.0`）。

## 目录

- `v1/domain-contract.md`：领域对象、状态机、不变量和兼容规则。
- `v1/error-codes.json`：稳定业务错误码及其语义。
- `v1/tool-catalog.json`：9 个 MCP 工具的机器可读目录。
- `v1/schemas/common.schema.json`：公共 ID、资源、任务、资产和错误结构。
- `v1/schemas/tools/*.schema.json`：每个工具的输入与输出 Schema。

工具 Schema 文件通过 `#/$defs/input` 和 `#/$defs/output` 暴露独立契约。例如：

```text
schemas/tools/resource_search.schema.json#/$defs/input
schemas/tools/resource_search.schema.json#/$defs/output
```

## 版本规则

- `contract_version` 使用 SemVer，并在 v1 中固定为 `1.0.0`。
- v1 内允许增加非必填字段，但不得改变既有字段语义、复用错误码或放宽安全边界。
- 删除字段、改变必填性、改变 ID 含义或改变状态机属于破坏性变更，必须创建新版本目录。
- 客户端必须拒绝不支持的主版本；服务端以
  `CONTRACT_VERSION_UNSUPPORTED` 返回可恢复业务错误。

## 安全边界

- 客户端只能传递 `flow_id`、`resource_id`、`plan_id`、`job_id`、`asset_id`
  等服务端生成的稳定 ID。
- 所有输入对象都禁止额外字段。
- 契约不接受本地路径、工作目录、解释器、可执行文件、脚本路径或 shell 命令。
- URL 只允许出现在服务端返回的资源元数据中；下载工具不接受任意 URL。
- 有副作用的调用使用幂等键；下载严格执行 `prepare -> confirm -> start`。
- 大文件和文件内容不进入 Tool JSON，工具只返回资产 ID 和受控元数据。

