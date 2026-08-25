# 0073 — Correctness hardening 与真实 OpenClaw 验收

- 状态：blocked
- 创建日期：2026-08-26
- 完成日期：未完成
- 范围：`mcp/education-resources/`、`.agent/plans/` 与真实 OpenClaw 用户链路
- 阻塞：当前执行环境只有 GitHub 仓库连接，没有仓库运行时或 OpenClaw/Gateway 执行入口，无法诚实执行聚焦 pytest、stdio probe 和真实 Agent 用户链路。

## Objective

在停止新增平台的前提下，修复当前静态审查已经确认的业务正确性问题，移除没有真实业务依据的残余限制与死代码，并把真实 OpenClaw 用户链路重新设为当前 release gate。

## Non-goals

- 不新增平台、MCP Tool、工作流状态机、Registry、持久 Resource Store 或兼容层；
- 不重写已经工作的 Adapter 协议；
- 不为了清理历史风格而进行无关大重构；
- 不用单元测试或 stdio probe 代替真实 OpenClaw / 用户链路验收。

## Business invariants

- Agent 继续负责语义判断，MCP 负责真实平台能力和 IO；
- Search / Expand 不授权下载；
- Resource 句柄仍为进程内临时句柄，只有真实长任务使用持久 Job；
- 完整业务数据不得被任意上限静默截断；上下文分页/摘要可以有界，但必须显式；
- 下载成功必须对应真实文件，多个资源不得互相覆盖或错误关联；
- 不恢复 authority/digest/binding/Flow/Selection/Plan 等旧状态链；
- 确认无运行时引用、无公共契约价值、无迁移必要的代码直接删除，不保留 inert compatibility 壳。

## Current architecture

- Active：一个 `learning-resource-flow` Skill + 一个 `education-resources` MCP；
- Search 由 `MultiPlatformSearchProvider` 路由；
- Expand / Download 使用文件型持久 Job 与 detached worker；
- Archive 依据 Job 中真实文件移动到资料库；
- URL Import 只有 `adapters.resource_urls.identify_resource_url -> expand.import_resource_url` 一条实现路径；
- 0028 的真实 OpenClaw 验收责任由本计划接替，真实用户链路仍未通过当前 release gate。

## Implemented changes

### Search correctness

- Mixed platform Search 不再引用循环外残留的 `queries/kind`；Generic 使用自己提交的 query 集合；
- future 绑定自己的 `(platform, submitted_queries)`，异常归因不再串到另一平台；
- `register_adapter` 的运行时事实只看 `platform_id + search()`；
- `AdapterDescriptor`、`descriptor_for_platform()` 以及 16 个内置 Adapter 的 `descriptor = ...` 双写已物理删除；相关测试不再伪造 `.descriptor`。

### URL Import dead-code convergence

- 删除 `ResourceService.import_url()` 与只为它服务的 `_platform_from_import_url()`、`urllib.parse` 依赖；
- 公共 MCP Import 继续只走 `adapters.resource_urls.identify_resource_url -> expand.import_resource_url`；
- 旧入口中有业务价值的 Inspector `title/resource_type` 回填迁入唯一公共 Import 路径，没有为删除死代码牺牲行为；
- `tests/test_import_url.py` 改为直接验证当前公共 Import 实现，不再由测试给旧 Service 入口续命。

### Download correctness / data bounds

- Artifact identity 改为包含 `job_id + resource_id + artifact index`，避免一个 Job 内不同 Resource 的 artifact 冲突；
- Generic Direct 同名文件使用 `name (2).ext` 等真实非覆盖路径；
- Generic Direct 不再为每个下载强制计算 sha256；DownloadResult / Artifact 的 sha256 改为可选，旧 Provider 已经计算时仍可携带；
- 删除 DownloadBatch 50 items、metadata 8KB / 64 fields / 5-depth、错误消息 512 字符等任意业务数据限制；保留凭据/URL/本地路径脱敏；
- 未删除真实 HTTP 响应、媒体分片等显式失败的 IO 上限，因为它们不是业务数据静默截断。

### SmartEdu

- 平台 title、relation、source_type、native item/group id 等事实不再经过项目自造的 64/96/120/160 字符截断和 ASCII 白名单；
- course file identity 只使用 provider 稳定 content/relation/item-or-group id，改为透明 percent-encoded composite key，不再 hash 成 opaque sha256；
- representation id 同样由当前路由事实透明组合，不作为 authority digest；
- Expand 的 course detail 网络读取移到 `smartedu_detail.py`，不再从 `smartedu_download.py` import Downloader 私有 HTTP helper；
- 保留 `_smartedu_course_detail` 作为薄测试 seam，不持有第二份状态或协议规则；
- 额外删除确认无引用的 `_stable_id()`、其唯一 `hashlib` import、未读取的 `SMARTEDU_TYPE_MAP`，并去掉 `_item_to_resource()` 未使用的 `query` 参数。

### Focused regressions

`tests/test_correctness_hardening.py` 覆盖：

- mixed Generic + platform query 不串线；
- Generic exception 使用自己的 query attribution；
- Adapter 无 Descriptor 仍能注册；
- multi-resource artifact identity 唯一；
- 同名文件不覆盖；
- DownloadResult 不要求 sha256；
- >50 item / >64 metadata fields / 深层 metadata / >512 message 不被任意拒绝或截断；
- SmartEdu 长文本不截断，Unicode native id 可以形成透明稳定 child key。

现有 `test_platform_adapters.py` 与 `test_import_url.py` 同步迁移到当前真实契约，不再保护已删除兼容壳。

## Acceptance criteria

- [x] AC-01：Generic + 专门平台混合搜索时 Generic 使用自己的 query，错误归因也对应正确 query；
- [x] AC-02：同一 Download Job 多个 Resource 产生唯一 artifact identity；
- [x] AC-03：同一 Download Job 中同名 Generic Direct 文件不互相覆盖；
- [x] AC-04：下载模型不再强制计算/携带 sha256，且没有任意 50 items / 8KB metadata / 64 fields / 5-depth 业务限制；
- [x] AC-05：`AdapterDescriptor` compatibility 壳及所有内置 Adapter 双写已从 active source 物理删除；
- [x] AC-06：SmartEdu 平台事实不因本项目自定义字符集/长度限制静默丢失，稳定子资源身份仍来自平台稳定字段；
- [x] AC-07：SmartEdu Expand 不再反向依赖 Downloader 私有 HTTP helper；
- [x] AC-08：真实 OpenClaw 验收重新成为 active release gate，未执行前不得宣称项目已完成真实用户链路验证；
- [x] AC-10：旧 `ResourceService.import_url()` 与重复 URL classifier 已删除，公共 Import 行为统一到一条路径；
- [ ] AC-09：聚焦 pytest / stdio / real OpenClaw 尚未实际执行；当前工具环境无可执行仓库/OpenClaw 入口。

## Complexity exceptions

无。本轮没有新增 generalized framework、持久 source of truth、fallback 状态链或 arbitrary business cap。`smartedu_detail.py` 是一个具体平台的单一 course-detail IO 模块，不是通用 Resolver/Service 层。

## 步骤

- [x] completed：修复三个 correctness bug（mixed search、artifact id、同名文件覆盖）。
- [x] completed：清理强制 sha256 与任意下载数据 bounds。
- [x] completed：物理删除 AdapterDescriptor compatibility 壳及内置 Adapter 双写。
- [x] completed：删除旧 Service URL Import 重复实现，并把必要行为迁入唯一公共 Import 路径。
- [x] completed：收敛 SmartEdu 平台事实与 Expand/Downloader 依赖边界，并删除同步确认的无引用 helper/constant/参数。
- [x] completed：恢复并更新真实 OpenClaw E2E release gate。
- [x] completed：新增/迁移与本轮 diff 直接对应的聚焦回归测试。
- [ ] blocked：实际运行聚焦 pytest / MCP stdio / 真实 OpenClaw E2E；需要有仓库运行时和 OpenClaw/Gateway 的环境继续执行。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
Business invariants still true by static inspection?: yes
New generalized abstraction introduced?: no
New persistent source of truth introduced?: no
Fallback added?: no
Arbitrary business truncation added?: no; removed existing ones
Confirmed dead compatibility code retained?: no
Actual user flow affected?: Search/Import/Download/SmartEdu correctness paths
Actual user flow validated?: no, blocked by current execution environment
Scope drift detected?: no
```

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted static/code inspection | completed | 修改接线与数据模型和审查问题一一对应；确认的 dead compatibility / duplicate Import 已从 active source 删除 | Python 实际执行、真实网络/Agent 行为 |
| focused unit/integration | tests added/migrated, not executed here | 执行后可验证本轮回归点 | 当前尚无运行结果；不能证明真实 OpenClaw |
| MCP stdio probe | not executed | — | Tool 进程实际启动/schema 回归 |
| real OpenClaw/user flow | blocked | — | 真实用户任务闭环仍未通过 release gate |
| full regression | intentionally not run | — | release 级跨切面回归 |

## 结果

本轮静态审查确认的高/中优先级代码问题与随后的死代码收口已经落到 active source：Descriptor compatibility 链和重复 Service URL Import 不再保留。公共 Tool 面没有新增，URL Import 必要的 Inspector 回填行为迁入唯一公共实现。计划保持 `blocked` 而不是虚假 `completed`，唯一剩余门槛是必须在有仓库运行时和 OpenClaw/Gateway 的环境中实际执行聚焦测试、stdio probe 和真实用户链路。完成这些验证后再决定是否归档 0073。
