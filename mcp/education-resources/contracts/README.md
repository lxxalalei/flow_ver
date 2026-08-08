# Education Resource MCP Contracts

`contracts/` 保存教育资源 MCP 的稳定领域契约。公共工具 Schema 描述 OpenClaw Skill 与
MCP 服务之间的边界；`platforms/` 另保存内部平台能力/身份 Registry 和其 Schema，供严格
loader 与冻结 descriptor 使用，不扩展 MCP 公共工具集合。这里不描述命令行参数、下载目录或
服务端运行时细节。

当前协议版本：`1.0.0`。

当前公开 catalog 位于 `contracts/tool-catalog.json`，`catalog_version` 为 `1.3.0`、
`contract_version` 为 `1.0.0`，精确暴露以下 13 个工具：

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

当前契约目录就是 `contracts/`；不存在作为当前公共接口的 `contracts/v1/` 或 `contracts/v2/`。

## 版本术语

- `1.0.0`：当前 Python stdio MCP 的公共契约版本。
- `learning-v1`：当前学习资料分类注册表版本，不是 MCP 契约版本。
- `v1`、`v2`：只在 `compatibility.md` 中表示历史教育资源迁移阶段；它们不是当前契约目录或可调用版本。

## 目录

- `domain-contract.md`：领域对象、状态机、不变量和兼容规则。
- `error-codes.json`：稳定业务错误码及其语义。
- `tool-catalog.json`：13 个 MCP 工具的机器可读目录。
- `schemas/common.schema.json`：公共 ID、资源、任务、资产和错误结构。
- `schemas/tools/*.schema.json`：每个工具的输入与输出 Schema。
- `platforms/platform-registry.json`：0018/0019 的 16 项平台能力与身份 Registry（`generic` 加 15 个内置平台）。
- `schemas/platform-registry.schema.json`：Registry 的机器可读 Schema，固定 16 项并约束 inspect 能力一致性。
- `platforms/README.md`：Registry、descriptor、身份 profile 与当前 Adapter 回退边界说明。

工具 Schema 文件通过 `#/$defs/input` 和 `#/$defs/output` 暴露独立契约。例如：

```text
schemas/tools/resource_search.schema.json#/$defs/input
schemas/tools/resource_search.schema.json#/$defs/output
```

## 版本规则

- `contract_version` 使用 SemVer，当前为 `1.0.0`。
- 允许增加非必填字段，但不得改变既有字段语义、复用错误码或放宽安全边界。
- `catalog_version` 的 minor 增长允许兼容新增工具或既有工具的可选字段；0019 的
  `resource_inspect`、0020 的 adaptive search 字段和 0022 的 AssetBundle 字段均不改变公共
  `contract_version=1.0.0`。当前 catalog 为 `1.3.0`。
- 删除字段、改变必填性、改变 ID 含义或改变状态机属于破坏性变更，必须声明新的主版本，并同步更新 Schema、
  工具目录、领域文档和兼容说明；不能仅通过把历史版本目录重新暴露来兼容。
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

## 0018 私有检索与平台 Registry

公共契约版本仍为 `1.0.0`，catalog 精确暴露 13 个工具，SQLite 仍是 Flow、ResultSet、
Presentation、Selection、Plan、Job、Asset、Archive 和 Resolution 的权威状态存储。0018 新增的 retrieval
模型位于服务内部，不改变这些公共边界：`CandidateResourceInternal`、`ResourceIdentity`、
`Representation` 和 `ResolvedResource` 只用于候选归一化、身份解析、表示合并和公共投影前的解析；
0019 的 Resolution 是独立的检查结果，不回写不可变 ResultSet。

身份优先级固定为 `native ID -> ISBN -> DOI -> platform-aware canonical URL -> weak fingerprint`。
`resource_search` 与 `resource_browse_creator` 共用 dedup，服务端在去重后才生成随机公共 `resource_id`；
Adapter 提供的 ID 不能直接作为公共 ID。canonical URL 默认只移除 fragment，平台级查询参数清理必须由
Registry identity profile 显式声明。

当前平台 Registry 共 16 项，严格 loader 校验 JSON/Schema、唯一平台 ID、平台级 identity profile
和 inspect 能力一致性；`generic`、`bilibili`、`nlc`、`annas-archive`、`ximalaya`、`zhihu`、
`smartedu` 七个平台启用 `inspect`，其余九个平台关闭。每个条目生成冻结、
递归不可变且可哈希的 `AdapterDescriptor`。详见
[平台 Registry 说明](platforms/README.md)。

## 0019 Inspection Layer

`resource_inspect` 是当前 catalog 的兼容新增工具。输入严格只有
`contract_version`、`flow_id`、`resource_id`、`idempotency_key`；服务端从 Flow 中重新取得
资源来源，不接受 URL、路径、批量 ID、检查深度或凭据。输出包含 `resolution_id`、
`resolution_status`、`resolved_resource`、`inspection` 和 `failures`，Representation 仅返回
受控元数据，不返回 locator、文件字节或本地路径。

Resolution 使用 migration 3 的 `resource_resolutions` 独立持久化，ResultSet 保持不可变。
幂等 scope 为 `resource_inspect:{flow_id}`；缓存键包含 `resource_id`、`source_fingerprint` 和
`inspect-v1`，`resolved`/`partial` 可缓存，`unresolved` 以新幂等键重试。`resource_flow_status`
通过 `current_resolutions` 提供安全恢复摘要。Generic 使用有界 GET、逐跳 SSRF、1 MiB 和
MIME/魔数校验；其余已实现的六个平台 Inspector 与 generic 总计七个平台，未启用平台返回
`FEATURE_NOT_SUPPORTED`。

## 0020 Adaptive Retrieval

`resource_search` 保持原工具名和 Provider 边界。旧请求省略 `mode` 时等价于
`replace`；`mode=extend` 必须提交当前 Flow 的 `base_result_set_id`。服务端由 base 候选与
本轮候选生成新的不可变 ResultSet，为新快照重新分配 opaque `resource_id`，并在最终事务中
复核 task version 与 current ResultSet。

SearchTask 可携带语义 `direction`，它描述本轮搜索目的，不是权威 ID。SearchRun 的
`round`、provider query runs、`provenance` 与事实 `coverage` 由服务端计算并随 ResultSet
恢复；模型不得提交或伪造这些输出。catalog 因兼容字段加法从 `1.1.0` 升至 `1.2.0`，
工具数仍为 13；0022 的 AssetBundle 可选输出字段再将 catalog 升至当前的 `1.3.0`。

## 0022 AssetBundle 兼容加法

0022 保持公共 `contract_version=1.0.0`、13 个工具和既有 Job 生命周期状态；不新增
Bundle Tool，也不增加 `partial` Job 状态。`AssetBundle` 是服务端生成的一个 Job × Resource
有序关系，不等于 ZIP 或本地目录；`bundle_id`、角色、顺序和完整度均不能由模型提交或伪造。

以下字段全部是可选输出字段，省略时旧的单 Asset 客户端仍保持原有形状：

- `asset_summary`、Library Asset 和 Archive success 可返回 `bundle_id`、`role`、`order`、
  `bundle_completion`。
- `item_failure` 可返回 `bundle_id`、`role`、`order`、`item_key`，以保留没有 Asset 的失败 BundleItem。
- `resource_job_status.success` 可返回 `completion`；它只表达 `complete|partial` 的结果完整度，
  不改变 `status` 的生命周期含义。
- `resource_flow_status.current_job` 可返回 `completion` 和服务端生成的 `bundle_ids` 摘要。

公共 `role` 固定为 `primary`、`subtitle`、`cover`、`metadata`、`attachment`、`transcript`、
`companion` 七种。一个可用 Bundle 必须有且只有一个 `primary`；部分结果仍须有可用 primary，
失败项不创建零字节假 Asset。Archive 继续只接受 `asset_id`，Library 继续按 Asset 返回；这些
新增字段只恢复 Bundle 关系，不暴露路径、字节或内部存储键。
