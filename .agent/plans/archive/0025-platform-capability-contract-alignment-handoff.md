# 0025 Platform Capability Contract Alignment - Completion Snapshot and 0028 Handoff

- 交接状态：0025 `completed`；下一阶段 0028 `pending`
- 交接日期：2026-08-10
- 已完成计划：[0025 Platform Capability Contract Alignment](0025-platform-capability-contract-alignment.md)
- 下一阶段：[0028 Real OpenClaw and Real Platform E2E](0028-real-openclaw-platform-e2e.md)
- 后续发布门禁：[0029 Retrieval Benchmark Release Gate](../0029-retrieval-benchmark-release-gate.md)
- 工作区：`/home/admin_quanxiao/projects/quanxiao/collector_flow_ver`
- 分支：`codex/growth-resource-taxonomy-rework`
- 验收 HEAD：`09d8eebbe37e76c6f298492c90214544f8a4667a`
- 用途：冻结 0025 的最终机器事实、验证证据、dirty 工作树边界和 0028 接续范围

## 结论与防重复边界

0025 的生命周期实现根审、子 Agent 验收、全量测试、E2E、静态契约门禁、OpenClaw
probe/doctor 和默认 Agent 自然语言 smoke 均已完成。本文件替代 2026-08-09 的中途阻塞交接，
其中 fingerprint mismatch、旧 Runner、Outcome/job status 未接通、调用面未迁移等描述均已过期。

恢复新会话时不得因为 Goal 后端仍保留暂停时的 `blocked` 状态，或因为文字出现“进入根审”，
就重新执行已经通过的 0025 根审和 482 项全量测试。只有后续代码、Schema、契约或运行配置发生
会使证据失效的变化，才按受影响范围重新验证。纯文档收口只运行 Markdown 和 diff 检查。

## 工作树保护

- 工作树高度 dirty，混有用户既有修改以及 0024/0025 修改；接管前必须先运行
  `git status --short`，不得 reset、checkout、clean、批量格式化或覆盖无关修改。
- `.gitignore` 当前存在、受 Git 跟踪且不在 `git status` 中。旧交接中“仍处于用户删除状态”
  的说法已失效，不得继续传播。
- 本轮没有 stage、commit 或 push；后续也不得把 dirty 工作树整体视为单一提交范围。
- 真实凭据、Cookie、Token、浏览器档案、SQLite 运行库、下载资产和平台数据不得进入仓库。

## 冻结的公共版本与能力事实

| 事实 | 0025 最终值 |
|---|---|
| MCP package/server version | `0.2.0` |
| Public `contract_version` | `1.0.0` |
| Public Tool catalog | `1.5.0` |
| Public Tools | 精确 13 个 |
| Capability catalog / registry | `1.1.0 / 1.1.0` |
| Platform Registry | `1.0.0`，16 个平台 |
| 0024 历史读兼容 | Tool catalog `1.4.0` |

精确三条 acquisition route：

1. `generic-direct@1.0.0 / direct_file / primary_resource`
2. `generic-web-materializer@1.0.0 / web_materialize / landing_page`
3. `smartedu-resource@1.0.0 / direct_file / primary_resource`

三个 Descriptor 均满足：

```text
fallback.allowed=false
fallback.allowed_scopes=[]
fallback.on_errors=[]
```

不存在专用 Provider 失败后静默切换 generic、scope 升级或 landing page 冒充 primary 的路径。

## 冻结的生命周期权威

唯一服务端权威链为：

```text
Capability Descriptor
  -> Deployment Readiness
  -> persisted Resolution / Representation
  -> Eligibility
  -> Plan capability binding + authority_digest
  -> immutable Job Execution Item
  -> exact Provider
  -> Acquisition Outcome
  -> Bundle / Asset
  -> Archive
```

关键不变量：

- `resource_download_start.authority_digest` 是 optional exact-match。省略时服务端从不可变 Plan
  读取并重新校验真实 authority；提供时必须完全一致，客户端不能生成或替换它。
- SQLite `cancelling` 是唯一持久化取消权威。Provider 返回、异常文本或 Runner event 不能把
  running Job 伪造成 cancelled。
- `finalize_job_success()` 校验完整 Execution -> Outcome -> Bundle -> Asset 闭包；失败、取消、
  quarantine 和未计划 Resource 不能留下可归档资产。
- Bundle reopen 必须匹配 exact execution item 且 Outcome 仍为 running；终态 Outcome 之后只允许
  完全一致的 Bundle/Outcome 只读 replay。
- Archive 只接受 `asset_id`，通过 reserve -> ready 状态机，并在文件副作用前重新校验 Asset 图和
  exact execution authority；生产 `Store.create_archive()` 已删除。
- Legacy Job/Outcome/Archive 可读，但缺少 `job_execution_items` 时不得产生新 Bundle、Asset 或
  Archive。Legacy Outcome 没有合法 execution digest 时，公共 `resource_job_status` 省略
  `execution`，不输出伪造摘要或字符串 `"None"`。

## 测试基础设施收口

### stdio 冷启动和 hermetic fixture

- `scripts/run-tests.sh` 在 `/tmp` 的单次运行根创建共享 bytecode cache；verifier、unittest 和
  MCP fixture 子进程复用同一隔离 cache，不扩大 5 秒 initialize timeout。
- 只有父 `PYTHONPYCACHEPREFIX` 与 runner 专用 `EDUCATION_RESOURCE_TEST_PYCACHE_DIR` 精确一致时
  才复用；任意未授权父 cache（包括仓库内路径）不会被复用。没有 runner cache 时，fixture
  使用自身临时 `data_dir/pycache`。
- `RawMcpClient`、official stdio、contract tools/list 和 taxonomy tools/list 共用
  `build_fixture_subprocess_environment()`，不继承父进程的 session-manager、SearxNG、凭据、
  Cookie、Token、proxy、任意 `PYTHONPATH` 或用户 site 配置。
- `Popen` 显式使用 UTF-8；测试运行状态只写入隔离 data/home/tmp/library 目录。

### runner 信号清理

- verifier/unittest 通过 `setsid` 建立独立进程组，runner 记录 active child PID。
- HUP/INT/TERM 先终止整个子进程组，再分别以 129/130/143 退出，最后仅由 EXIT trap 清理测试根。
- 真实 TERM smoke：`returncode=143`、测试根退出后不存在、子测试收到 TERM、没有继续执行标记。

### Library fixture

`test_library_storage.py` 不再构造缺少 authority 的 succeeded Job/ready Asset；每个资产 fixture
都建立完整 Plan -> Readiness -> Eligibility -> Plan Item -> Job Execution Item -> running Outcome
-> Bundle/primary Asset -> terminal Outcome -> succeeded Job，没有放宽生产 Archive 校验。

## 最终验证证据

### Python / E2E

```text
cd mcp/education-resources
./scripts/run-tests.sh all
Ran 482 tests in 20.735s
OK
```

```text
cd mcp/education-resources
./scripts/run-tests.sh e2e
Ran 9 tests
OK
```

```text
compileall_status=0
compiled_pyc=183
```

183 个编译产物全部位于 `/tmp` 隔离 cache；仓库内既有 ignored `.pyc` 集合在验收前后未变化。

### 静态契约与文档

```text
json_documents=40
json_schemas=23
local_schema_refs=570

tools=13
catalog=1.5.0
contract=1.0.0

error_codes=78
metadata=78

platforms=16
platform_registry=1.0.0

capability_routes=3
capability_catalog=1.1.0
capability_registry=1.1.0
fallbacks_disabled=true

changed_markdown_files=30
local_links_at_contract_gate=73
post_handoff_local_file_links=74
git diff --check=PASS
```

### OpenClaw

验收环境：

```text
OpenClaw 2026.7.1-2
Node v24.18.1
Gateway running; connectivity probe ok
```

通过：

- `openclaw config validate`：配置有效。
- `openclaw mcp doctor education-resources --probe --json`：`ok=true`，`issues=[]`。
- `openclaw mcp probe education-resources --json`：13 Tools，`diagnostics=[]`。
- `openclaw mcp list --json` 与 `openclaw mcp show education-resources --json` 正常。

`openclaw mcp status` 的保存输出已包含：

```text
configured=true
enabled=true
ok=true
transport=stdio
```

但该 CLI 进程未在 60 秒内自行退出，外层守护返回 `124`，stderr 为空。由于 Gateway、list/show、
doctor/probe 和默认 Agent 回合均正常，此项属于 OpenClaw `2026.7.1-2` 的 status CLI 单路径退出
异常，不是 education-resources 功能阻塞；不要用扩大 timeout 或改 MCP 契约掩盖它。

### 默认 Agent 自然语言 smoke

Prompt：

```text
我是家长，想给小学三年级孩子找免费的恐龙入门图文资料。
请只创建检索流程并搜索候选，最多列出3项；
不要替我选择，不要下载，不要归档，也不要伪造任何工具结果。
```

结果：`finalStatus=success`、未超时、未中止，工具调用链为：

```text
read
resource_flow_start
resource_search
resource_presentation_save
```

没有调用 `resource_selection_save`、`resource_download_prepare`、`resource_download_start` 或
`resource_archive`，没有工具失败，也没有 fallback。

## 0028 与 0029 的接续边界

0025 完成的是能力事实、执行权威、生命周期、安全、兼容读和本地/OpenClaw 基础验收，不包括：

- 真实平台合法凭据和认证 readiness；
- 逐平台真实网络 Search -> Inspect -> Present -> Select -> Confirm -> Acquire -> Archive -> Recover；
- 真实中断、重启、恢复和资产留存矩阵；
- 120+ gold cases、benchmark baseline、critical invariant 和 release gate。

以上前三项进入 0028；benchmark 与 release gate 进入 0029。不得用 fixture、直接 Service 调用、
MCP probe 或本次无副作用 Agent smoke 代替 0028 的真实平台矩阵，也不得把 0028/0029 写成
0025 已完成内容。

## 已知非阻塞风险

1. `RawMcpClient` 仍使用 `select.select(TextIOWrapper)`：POSIX 文本预读可能使已在用户态 buffer
   的下一条消息不再触发 select，原生 Windows select 也不支持匿名 pipe。当前 WSL/Linux 标准
   runner、482 项测试和 OpenClaw 均通过；不要在 0025 收尾中仓促插入 transport 重写。
2. runner TERM 进程组 smoke 已人工验证，但尚未固化为仓库自动测试。
3. 仓库内存在历史 ignored `.pyc`；0025 没有新增或刷新它们，新 cache 均在 `/tmp`。
4. OpenClaw `mcp status` 能输出有效 JSON 但未正常退出，仍需作为 CLI 环境问题跟踪。
5. 真实平台合法会话、认证 readiness 和完整真实网络矩阵仍待 0028。

## 新会话接管指令

```text
0025 已完成，不要重复执行生命周期根审、482 项全量测试或 OpenClaw 基础验收。
先读取 AGENTS.md、0025 主计划、本完成快照、0028 和 0029，执行 git status --short 保护
shared dirty 工作树。随后只按 0028 开展真实 OpenClaw/真实平台矩阵；真实凭据只通过合法、
仓库外的 SecretRef/session-manager 使用。若后续修改使 0025 证据失效，再按受影响范围定向
回归，不采用 fallback、扩大 timeout、兼容补丁或第二套执行权威。
```
