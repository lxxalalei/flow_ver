# 0038 — SmartEdu Active Provider 最小恢复

- 状态：completed
- 创建日期：2026-08-12
- 完成日期：2026-08-12
- 分支：`codex/growth-resource-taxonomy-rework`
- 范围：SmartEdu Inspect → concrete Representation → ProviderSpec → exact Provider 的工程恢复
- 后续验收：由用户在 Windows OpenClaw 中自行执行真实平台测试，归入 [`0028`](0028-real-openclaw-platform-e2e.md)

## Objective

让 SmartEdu 搜索候选只有在平台 detail 返回具体且受支持的主文件后，才生成可规划的
`primary_resource` Representation，并由 `smartedu-resource@1.0.0` exact Provider 执行。

本计划完成的是 active 工程链路，不把 fixture、单元测试、Windows 安装或 MCP 可加载性解释为真实平台成功或 production-ready。

## Scope update（2026-08-12）

用户明确决定：

- 真实 Windows OpenClaw 与平台下载由用户自行验收；
- Coding Agent 不继续运行 gateway restart、MCP doctor/probe、真实 Agent 回合或真实下载；
- 平台接入优先于 Agent 代验收。

因此本计划以“工程实现 + 定向离线验证 + Windows 部署副本已同步安装”为完成边界；真实用户链证据继续由 0028 独立记录。这是用户明确修改验证职责，不是把未执行的真实验收改写为已通过。

## Delivered behavior

- 首批 concrete primary 仅支持：
  - PDF；
  - direct MP4；
  - MP3；
  - M4A。
- HLS/m3u8、WebM、EPUB 和其他格式不进入 active route。
- Inspect 必须读取本次 SmartEdu detail 事实；landing page 或搜索 metadata 不能单独升格为可下载主资源。
- direct MP4 与 m3u8 同时存在时选择 direct MP4；只有 m3u8 时不生成已确认 MP4 能力。
- Representation ID 绑定 `resource_id + source_url + provider item_key + format`；Start 重新查询 detail 并拒绝同格式但 provider item 已漂移的资源。
- Planner exact 选择 `smartedu-resource@1.0.0 / direct_file / primary_resource`，并保存实际 container。
- Provider 不存在、scope/strategy 不匹配或 Representation 漂移时显式失败；不切 generic Provider。
- SmartEdu 网络边界使用精确 HTTPS Host、公共 DNS/IP 校验、应用层逐跳重定向与敏感请求跨 Host 阻断。
- ready 文件在产生 `DownloadResult` 前检查 PDF、MP4/M4A 或 MP3 文件签名；HTML 登录页不能伪装为成功资产。
- 未恢复 Capability Descriptor、Readiness、Eligibility 或多层 digest authority；未恢复通用 size/hash 成功门禁。

## Key change surface

- Contract / models：
  - `mcp/education-resources/contracts/schemas/plan-item.schema.json`
  - `mcp/education-resources/contracts/schemas/tools/resource_download_prepare.schema.json`
  - `mcp/education-resources/src/education_resource_mcp/models.py`
  - `mcp/education-resources/src/education_resource_mcp/acquisition/models.py`
- Inspect / Provider / routing：
  - `adapters/inspect_smartedu.py`
  - `adapters/smartedu_download.py`
  - `adapters/http_client.py`
  - `inspection_registry.py`
  - `acquisition/planner.py`
  - `acquisition/simple.py`
  - `simple_service.py`
  - `simple_storage.py`
- Tests：
  - `tests/test_platform_inspectors_media.py`
  - `tests/test_smartedu_bundle.py`
  - `tests/test_acquisition_simplification_0037.py`

完整未提交文件列表以 live `git status --short` 为准，不能只依赖本计划。

## Business invariants

- Search metadata、Registry 历史 `acquire=true`、Provider 文件存在或 landing 成功都不能证明可下载。
- Prepare 只消费 fresh concrete Representation；Start 继续重验同一 provider item 与格式。
- Inspect、错误和 Tool 输出不含 detail/download URL、Token、Cookie、Header、响应体或本地路径。
- 用户确认前不 Start；本计划未执行真实下载、Archive 或真实 Agent 用户回合。

## Complexity exception — SmartEdu 私有 HTTP Client

```text
Problem:
Windows curl fallback 会隐式跟随重定向；SmartEdu detail/asset 请求需要精确 Host 和逐跳检查。
Why current structure cannot solve it:
共享 urlopen 默认自动 redirect；BoundedWebFetcher 不支持认证流式资产。
Simplest alternative considered:
在每个 SmartEdu 请求点内联 NetworkPolicy 和 redirect loop。
Why that alternative is insufficient:
detail、relation、direct file 等路径会复制边界并产生语义漂移。
New source of truth introduced:
none；平台 detail 与现有服务端状态仍是权威。
New invariant introduced:
SmartEdu 请求只允许精确 HTTPS Host，每一跳均由应用层验证。
Failure modes introduced:
NETWORK_BLOCKED / REDIRECT_BLOCKED / PLATFORM_UNAVAILABLE / CONTENT_VALIDATION_FAILED。
```

## Validation evidence

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| Linux targeted/subsystem | 30/30 pass | SmartEdu detail → concrete primary、direct format 选择、exact route、Provider registration、内容签名与直接相关网络边界 | 真实平台、合法凭据、真实用户闭环 |
| Python compile | `compileall-ok` | 受影响 Python 源码和测试可编译 | 运行时平台成功 |
| diff hygiene | `git diff --check` pass | 当前 patch 无 whitespace error | 业务完整性 |
| Windows deployment | source synced; editable install pass; `pip check` pass; runtime verifier pass under Python 3.14.5 | Windows OpenClaw education-resources 部署副本能安装当前包及依赖 | MCP doctor/probe、网关加载、真实 Agent 或真实下载 |
| real OpenClaw/platform | not run by user decision | — | production-ready 与真实下载成功 |
| full regression | not run | — | 全仓无回归 |

Linux 定向命令：

```bash
cd mcp/education-resources
PYTHONPATH=src python -m unittest -v \
  tests.test_platform_inspectors_media \
  tests.test_smartedu_bundle \
  tests.test_acquisition_simplification_0037
python -m compileall -q src tests
git diff --check
```

Windows 实际执行到：

- 只同步 `mcp/education-resources/`；未同步 session-manager 或 Skill；
- editable install；
- `pip check`；
- `scripts/verify_runtime_environment.py`。

未执行 gateway restart、MCP doctor/probe、真实平台请求或下载。同步命令使用 `rsync --delete`，Windows source 副本中可能同时存在仓库 package 下的 `.openclaw-test/pytest-tmp/` 空测试目录；下一会话不要把它当成产品数据或测试通过证据。

## Decision log

### Decision 001 — 首批格式收紧

HLS 当前只是分段拼接，不能证明输出为 MP4；因此只开放 PDF、direct MP4、MP3、M4A。

### Decision 002 — 绑定 provider item

仅比较 container 无法发现“主文件换成另一个同格式 item”；Representation ID 因此绑定 provider item key，Start 重新计算并比较。

### Decision 003 — 用户持有真实验收

Windows OpenClaw 的实际 Agent/平台测试由用户执行。Coding Agent 交付可测试实现与说明，不再代跑 doctor/probe 或真实下载。

## Completion record

```text
[x] concrete SmartEdu primary Representation
[x] PDF/direct MP4/MP3/M4A ProviderSpec
[x] exact smartedu-resource registration
[x] Start provider-item/container revalidation
[x] directly affected contract/model updates
[x] Linux targeted/subsystem validation
[x] Windows package sync/install/runtime verification
[ ] Windows MCP doctor/probe — intentionally not run
[ ] real Agent/user flow — user-owned validation
[ ] real SmartEdu download — user-owned validation
[ ] Archive — not run
[ ] full regression — not run
```

## Result

SmartEdu active 工程链路已恢复，并已部署到 Windows education-resources 源码副本。真实平台是否接受当前会话、实际文件是否成功下载以及 OpenClaw 对话体验，仍必须由用户的 0028 验收结果决定。
