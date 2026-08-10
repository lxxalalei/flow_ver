# Education Resources Contracts

`contracts/` 是 education-resources 公共控制面的机器契约目录。JSON/Schema 是线上的权威来源；
本目录中的 Markdown 只解释边界、版本和变更政策，不能替代或“清理”运行时实现。

## 机器权威

- [`tool-catalog.json`](tool-catalog.json)：公共工具集合、`contract_version=1.0.0`、当前
  `catalog_version=1.5.0` 及工具元数据。
- [`schemas/tools/`](schemas/tools/) 与 [`schemas/common.schema.json`](schemas/common.schema.json)：
  工具输入/输出、稳定 ID、状态和公共投影的 JSON Schema。
- [`error-codes.json`](error-codes.json)：公开业务错误码及其稳定语义；Provider、Storage 和
  validator 的内部字符串不是公共兼容面。
- [`capabilities/capability-descriptors.json`](capabilities/capability-descriptors.json)：设计时静态
  Capability Descriptor catalog；它不单独证明当前部署 readiness、候选 Representation、权利
  Eligibility 或获取成功。
- [`platforms/platform-registry.json`](platforms/platform-registry.json)：平台身份、检索和 inspect
  声明；它不替代 Capability/Readiness/Eligibility 权威链。
- [`taxonomy/learning-v1.json`](taxonomy/learning-v1.json)：资料库分类注册表；`learning-v1` 不是
  MCP 协议版本。

运行时的 Flow、ResultSet、Presentation、Selection、Resolution/Representation、Readiness、
Eligibility、Plan、Job Execution、Outcome、Asset、AssetBundle 和 Archive 权威状态在服务端
SQLite 中，不在 Markdown 或客户端输入中。

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
│   ├── capability-descriptor*.schema.json
│   ├── deployment-readiness.schema.json
│   ├── resolution.schema.json
│   ├── eligibility-decision.schema.json
│   ├── plan-item.schema.json
│   ├── actual-outcome.schema.json
│   └── platform-registry.schema.json
├── capabilities/capability-descriptors.json
├── platforms/platform-registry.json
└── taxonomy/learning-v1.json
```

平台 Registry 的说明见 [`platforms/README.md`](platforms/README.md)；服务启动、数据目录和测试命令见
[`MCP README`](../README.md)。

## 版本规则

- `contract_version` 使用 SemVer；当前公共主版本为 `1.0.0`。删除字段、改变既有字段语义、
  改变必填性或放宽安全边界，必须进入新的主版本。
- `catalog_version` 记录公共工具目录；同一契约主版本内，新增工具或既有工具的可选输出字段
  可以增加 minor，但不得悄悄改变既有 required 字段、稳定 ID、状态机或错误语义。当前为 `1.5.0`。
- Capability Descriptor、Platform Registry、taxonomy 各自拥有独立版本域，不与公共 catalog 机械同步。
- 同一 major 内错误码只允许 append-only 增加；公开错误必须先在 `error-codes.json` 登记并由
  Service 边界归一化。
- 当前运行时的旧读/新写、1.4 形状和 authority 缺失行为以
  [`compatibility.md`](compatibility.md) 为准。

## 变更与验证要求

修改公共契约时，先更新机器权威文件，再同步领域说明、兼容政策和受影响测试；不得只修改 Markdown
来宣称运行时已改变。工具、Schema、错误码、Capability 或 Registry 的变更必须保持 JSON/Schema
互相引用一致，并验证服务端仍从服务状态生成不可伪造的 ID、摘要和副作用结果。

至少运行受影响的 JSON/Schema 契约测试和 Python 检查：

```bash
cd mcp/education-resources
.venv/bin/python -m compileall -q src tests
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh all
EDUCATION_RESOURCE_MCP_PYTHON=.venv/bin/python ./scripts/run-tests.sh e2e
```

文档变更还要检查相对链接、UTF-8 编码、围栏闭合和 `git diff --check`。若无法运行完整测试，必须
记录替代验证、未覆盖的风险和继续验证所需条件。

## 相关文档

- [工作区根 README](../../../README.md)
- [当前架构事实快照](../../../docs/CURRENT_ARCHITECTURE.md)
- [开发计划](../../../docs/DEVELOPMENT_PLAN.md)
- [检索权威边界](../../../docs/RETRIEVAL_AUTHORITY.md)
- [MCP 服务 README](../README.md)
- [领域契约](domain-contract.md)
- [当前兼容与重置政策](compatibility.md)
