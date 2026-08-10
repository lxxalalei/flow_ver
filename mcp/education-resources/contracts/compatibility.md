# 当前兼容与重置政策

## 产品承诺

产品只承诺当前公共控制面：`contract_version=1.0.0`、`catalog_version=1.5.0`，机器权威以
[`tool-catalog.json`](tool-catalog.json) 和相关 Schema 为准。**产品不承诺旧数据兼容**，也不承诺
任意历史客户端、缓存的 Tool Schema 或旧确认材料可以继续执行。

文档删减不等于运行时清理。当前 runtime 仍保留有限的读取路径：

- 可读取并投影部分 `1.4` shape；
- 可读取 legacy `Plan -> Job -> Outcome -> Archive` 记录及其安全只读状态。

这些路径是恢复、审计和迁移判断用的只读兼容，不是旧数据升级承诺。服务端不会从缺失字段、旧
Plan options、平台布尔能力或 generic Provider 猜测新的执行权威，也不会把旧记录静默改写成当前
可执行状态。

## Authority 缺失时的重置边界

旧 Plan/Job/Outcome/Archive 记录缺少可验证的 Capability、Readiness、Resolution/Representation、
Eligibility 或 Job Execution authority 时，只能读取安全投影：

- 不能 `resource_download_start`；
- 不能据此执行 `resource_archive`；
- 不能重建或伪造 `authority_digest`、`plan_digest`、execution binding 或 Outcome digest；
- 不能通过省略 `authority_digest`、`allow_safe_fallback` 或换用 generic Provider 绕过校验。

恢复方式是建立新的 Flow，重新 Inspect/Resolution、选择并 `resource_download_prepare`，取得新的
用户确认后再 start；只有带有当前服务端权威链的已校验 Asset 才能归档。迁移可以保留原记录供读取，
但不应依赖手工改 SQLite、路径或摘要来“修复”旧状态。

## 客户端兼容

当前公共输出仍允许旧形状的可选字段缺省，但 Schema 使用严格对象约束时，固定缓存 `1.4` Schema
的 stale client 可能拒绝 `1.5` 新写输出。客户端应在 `initialize`/`tools/list` 后刷新当前目录；
不能刷新的客户端必须使用服务端明确提供的旧字段投影或显式停止。**这不是无感兼容**，不能把
“旧读”描述为任意 stale client 都无需升级。

`resource_download_start.input.authority_digest` 仍可省略，但省略只表示服务端从不可变 Plan 读取
真实摘要并重新校验；它不是 fallback，也不降低权限、来源、Provider、strategy、scope 或
Representation 检查强度。

## 已知契约漂移（本文件不修复）

当前 runtime 的 Acquisition Outcome 在执行中可能使用 `status="running"`，而公共
`outcome_status` Schema 当前枚举未包含 `running`。这是已知契约漂移，后续应独立修复；本轮不修改
任何 JSON/Schema，也不把文档删减当作机器契约或 runtime 已修复的证据。

相关语义见 [`domain-contract.md`](domain-contract.md)；当前架构与检索权威分别见
[`CURRENT_ARCHITECTURE.md`](../../../docs/CURRENT_ARCHITECTURE.md) 和
[`RETRIEVAL_AUTHORITY.md`](../../../docs/RETRIEVAL_AUTHORITY.md)。
