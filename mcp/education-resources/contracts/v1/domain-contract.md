# Education Resource Domain Contract v1

协议版本：`1.0.0`

## 1. 权威边界

MCP 服务端拥有 Flow、展示集合、Selection、Download Plan、Job、Asset 和归档记录
的权威状态。Skill 负责意图澄清、结果展示、用户选择、确认和解释，但不得伪造或
直接修改权威状态。

旧 Stage JSON 在迁移期只能作为导入、导出或展示格式，不能作为下载授权依据。

## 2. 稳定 ID

| 字段 | 格式 | 含义 |
|---|---|---|
| `flow_id` | `flow_<opaque>` | 一次资源收集流程 |
| `resource_id` | `res_<opaque>` | 服务端规范化后的候选资源 |
| `plan_id` | `plan_<opaque>` | 一次有期限的下载准备结果 |
| `job_id` | `job_<opaque>` | 一个异步下载任务 |
| `asset_id` | `asset_<opaque>` | 校验通过、受服务端管理的资产 |

ID 是不透明引用。客户端不得从 ID 推导路径、平台 URL、租户或数据库键，也不得
自行生成 ID。所有 ID 必须在当前可信调用上下文中重新校验归属。

## 3. Flow 阶段

v1 使用以下阶段：

```text
intent_ready -> searching -> selecting -> prepared -> downloading -> ready_to_archive -> archived
```

流程也可以进入 `failed` 或 `cancelled`。阶段名称用于展示和恢复，不替代服务端
状态校验。

## 4. 展示与选择不变量

- `resource_search` 每次成功后产生单调递增的 `presented_version`。
- `resource_selection_save` 必须携带当前 `presented_version`。
- 服务端只接受该版本展示集合内的 `resource_id`。
- 选择保存后产生单调递增的 `selection_version`。
- 空选择表示明确取消；取消后的 Selection 不得用于准备或启动下载。

## 5. 下载不变量

下载必须是两阶段操作：

1. `resource_download_prepare` 根据已保存 Selection 创建有期限的 Plan，只进行
   权限、来源、大小、格式和风险评估，不下载正式文件。
2. 用户查看准备结果并明确确认后，`resource_download_start` 携带 `plan_id`、
   `confirmation_token` 和 `idempotency_key` 启动异步 Job。

服务端必须在 `start` 时重新验证：

- Flow、Selection 和 Plan 的归属及状态；
- Plan 未过期、未使用、未取消；
- 资源仍属于已展示且明确选择的集合；
- 来源、网络、格式、大小和授权策略；
- 幂等键没有与不同请求发生冲突。

成功启动后 Plan 只能消费一次。相同幂等键和相同规范请求返回同一结果；相同键
配合不同请求返回 `IDEMPOTENCY_CONFLICT`。

## 6. Job 状态机

```text
queued -> running -> succeeded
                  -> failed
queued/running -> cancelling -> cancelled
```

- `succeeded`、`failed`、`cancelled` 是终态。
- `cancelled` 不得映射为成功，也不得留下可归档资产。
- Job 可以产生一个或多个 `asset_id`，但只有 `succeeded` Job 的已校验资产可归档。
- 重启后 Job 必须恢复执行，或明确终结为带稳定错误码的失败状态。

## 7. Asset 与归档不变量

- Asset 是服务端受控资产区内已完成格式、内容、大小和完整性校验的对象。
- `resource_archive` 只接受 `asset_id` 和其所属 `job_id`，不接受路径或 URL。
- 归档必须幂等，并保证文件提交与索引提交的一致性。
- Tool JSON 只返回资产元数据和受控访问引用，不返回大文件字节。

## 8. 错误模型

业务错误使用结构化结果返回：

```json
{
  "contract_version": "1.0.0",
  "ok": false,
  "flow_id": "flow_example000000000000",
  "error": {
    "code": "RESOURCE_NOT_SELECTED",
    "message": "The resource is not part of the saved selection.",
    "retriable": false,
    "context": []
  }
}
```

错误码在 `error-codes.json` 中登记。v1 内不得删除、复用或改变既有错误码含义。
协议损坏、JSON-RPC 错误和无法构造结构化结果的进程级故障才使用 MCP 协议错误。

## 9. 禁止的公共输入

任何 v1 工具都不得接受：

- 本地绝对或相对路径、下载目录、临时目录；
- Python、Node、浏览器、ffmpeg 或其他可执行文件路径；
- shell 命令、脚本路径、命令模板或环境变量注入；
- 任意下载 URL、任意请求头、Cookie、Token 或浏览器档案；
- 由模型声明且未经可信层注入或验证的用户、租户和权限结论。

这些内容属于部署配置、可信身份上下文或服务端 Adapter 策略，不属于模型可控的
领域工具参数。

