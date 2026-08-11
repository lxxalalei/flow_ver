# Education Resources Contracts

`contracts/` 是 `education-resources` 公共控制面的机器契约目录。JSON/Schema 是公共接口的权威来源；Markdown 只解释边界、版本和迁移状态。

## 当前机器契约

- [`tool-catalog.json`](tool-catalog.json)：`contract_version=1.0.0`、`catalog_version=1.6.0`、13 个领域级 Tool。
- [`schemas/tools/`](schemas/tools/) 与 [`schemas/common.schema.json`](schemas/common.schema.json)：Tool 输入/输出、稳定业务 ID、状态与公共投影。
- [`error-codes.json`](error-codes.json)：公开业务错误码。
- [`platforms/platform-registry.json`](platforms/platform-registry.json)：平台身份、Search/Inspect 等静态声明；不证明当前 Provider 可用或一次获取成功。
- [`taxonomy/learning-v1.json`](taxonomy/learning-v1.json)：学习资料库分类注册表。

当前服务端业务状态为：

```text
Flow / ResultSet / Presentation / Selection
Resolution / Representation
Plan / Job / JobItem / Outcome
Asset / AssetBundle / Archive
```

## 0037 后的获取契约

公共获取契约不再把以下内容作为客户端或服务端持久控制面：

- Capability Descriptor binding；
- Deployment Readiness Snapshot；
- Eligibility Decision；
- `authority_digest`；
- Plan/Execution binding digest；
- `outcome_digest`。

Prepare 返回的 PlanItem 只描述：

```text
resource_id
selected_position
platform
representation_id
planned_scope
planned_strategy
planned_provider
planned_container
estimated_size_bytes
risks
```

Start 使用 Presentation / Selection / Plan 版本、确认令牌和服务端当前 Resolution 做重验证，不再接受 `authority_digest`。

JobStatus 的 Outcome 只投影：

```text
planned route
execution route + representation_id + revalidated_at
actual route
status / failure / bundle / assets / timestamps
```

Provider 能力的当前可执行性是运行时事实，不生成 readiness/eligibility ID。

## 兼容目录

0037 前的以下文件目前仍暂留仓库，供旧数据迁移、历史对照和后续 cleanup 使用：

```text
capabilities/capability-descriptors.json
schemas/capability-descriptor*.schema.json
schemas/deployment-readiness.schema.json
schemas/eligibility-decision.schema.json
```

它们不再被 `tool-catalog.json` 的下载公共契约引用，也不应被新代码当作 Active acquisition authority。兼容期结束后再通过独立 cleanup 计划物理删除，避免迁移与运行时切换混在一次改动中。

## 目录导航

```text
contracts/
├── README.md
├── tool-catalog.json
├── error-codes.json
├── domain-contract.md
├── compatibility.md
├── schemas/
│   ├── common.schema.json
│   ├── tool-catalog.schema.json
│   ├── tools/*.schema.json
│   ├── resolution.schema.json
│   ├── plan-item.schema.json
│   ├── actual-outcome.schema.json
│   └── platform-registry.schema.json
├── capabilities/              # 0037 兼容期历史输入；非 Active 获取真值
├── platforms/platform-registry.json
└── taxonomy/learning-v1.json
```

## 版本规则

- `contract_version=1.0.0`：当前公共协议主版本。
- `catalog_version=1.6.0`：记录本次下载契约简化；Tool 数量仍为 13。
- Platform Registry 与 taxonomy 有独立版本域。
- 错误码同一 major 内保持稳定语义。
- 删除旧实现字段后，不能通过所谓“兼容 fallback”在运行时重新生成一套隐藏 authority chain。

0037 删除的是内部自证状态，不删除用户确认、服务端 ID、Selection/Plan 版本、exact Provider、网络/路径安全等业务边界。

## 变更与验证要求

修改公共契约时：

1. 先改机器 Schema / catalog；
2. 同步 Runtime；
3. 运行 JSON 解析与受影响的定向行为测试；
4. 再更新说明文档；
5. 不为了让旧实现测试继续通过而恢复已经删除的业务无关字段。

推荐最小验证：

```bash
cd mcp/education-resources
.venv/bin/python -m compileall -q src
.venv/bin/python -m pytest -q tests/test_acquisition_simplification_0037.py
```

需要更大范围时再显式运行 `scripts/run-tests.sh all` / `e2e`。

0037 已用一次隔离 GitHub Actions 验证包安装、compileall、所有 JSON 契约解析和定向测试均通过。

## 相关文档

- [工作区根 README](../../../README.md)
- [当前架构事实](../../../docs/CURRENT_ARCHITECTURE.md)
- [开发路线](../../../docs/DEVELOPMENT_PLAN.md)
- [检索权威边界](../../../docs/RETRIEVAL_AUTHORITY.md)
- [MCP 服务 README](../README.md)
- [0037 获取状态链简化](../../../.agent/plans/0037-acquisition-state-simplification.md)
