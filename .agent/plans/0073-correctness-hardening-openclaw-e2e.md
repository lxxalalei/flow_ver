# 0073 — Correctness hardening 与真实 OpenClaw 验收

- 状态：in_progress
- 创建日期：2026-08-26
- 完成日期：未完成
- 范围：`mcp/education-resources/`、`.agent/plans/` 与真实 OpenClaw 用户链路

## Objective

在停止新增平台的前提下，修复当前静态审查已经确认的业务正确性问题，移除没有真实业务依据的残余限制/兼容壳，并把真实 OpenClaw 用户链路重新设为当前 release gate。

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
- 不恢复 authority/digest/binding/Flow/Selection/Plan 等旧状态链。

## Current architecture

- Active：一个 `learning-resource-flow` Skill + 一个 `education-resources` MCP；
- Search 由 `MultiPlatformSearchProvider` 路由；
- Expand / Download 使用文件型持久 Job 与 detached worker；
- Archive 依据 Job 中真实文件移动到资料库；
- 0028 真实 OpenClaw 验收仍未完成，但此前被错误移入 archive。

## Expected change surface

Likely to change:
- `search.py`：修复 Generic 多平台组合查询使用错误变量；
- `acquisition/router.py`、`downloader.py`：修复多资源 artifact/file 冲突；
- 下载结果/Artifact 模型：移除无业务用途的强制 sha256 与任意 metadata/batch 限制；
- Adapter 基础契约：移除无意义 `AdapterDescriptor` compatibility 壳；
- SmartEdu：移除平台事实任意截断/字符白名单，并收敛 Expand 对 Downloader 私有 helper 的依赖；
- `.agent/plans/`：恢复真实 OpenClaw 验收为 active release gate。

Should not change:
- 公共 MCP Tool 名称与输入输出语义；
- 平台真实 API、分页终止与下载策略；
- SessionStore 边界；
- Generic Web Reader/HTML Design 产品行为。

## Acceptance criteria

- AC-01：Generic + 专门平台混合搜索时 Generic 使用自己的 query，错误归因也对应正确 query；
- AC-02：同一 Download Job 多个 Resource 产生唯一 artifact identity；
- AC-03：同一 Download Job 中同名 Generic Direct 文件不互相覆盖；
- AC-04：下载模型不再强制计算/携带 sha256，且没有任意 50 items / 8KB metadata / 64 fields / 5-depth 业务限制；
- AC-05：内置 Adapter 不再依赖只有 `platform_id` 的兼容 Descriptor 双写；
- AC-06：SmartEdu 平台事实不因本项目自定义字符集/长度限制静默丢失，稳定子资源身份仍来自平台稳定字段；
- AC-07：SmartEdu Expand 不再反向依赖 Downloader 私有 HTTP helper；
- AC-08：真实 OpenClaw 验收重新成为 active 计划，未执行前不得宣称项目已完成真实用户链路验证；
- AC-09：完成后只运行与改动相称的聚焦验证；无法在当前环境实际运行的更高等级验证必须明确记录。

## Complexity exceptions

无。本轮目标是减少复杂度和修复明确错误，不新增抽象层或 source of truth。

## 步骤

- [ ] in_progress：修复已确认的三个 correctness bug（mixed search、artifact id、同名文件覆盖）。
- [ ] pending：清理强制 sha256 与任意下载数据 bounds。
- [ ] pending：移除 AdapterDescriptor compatibility 壳。
- [ ] pending：收敛 SmartEdu 平台事实与 HTTP helper 边界。
- [ ] pending：恢复并更新真实 OpenClaw E2E release gate。
- [ ] pending：执行可运行的聚焦验证，记录当前环境无法执行的真实 OpenClaw 验证。

## Milestone checkpoint

每一步完成后检查：目标是否未漂移；是否新增抽象/source of truth/fallback/截断；是否改变公共 Tool；是否存在未验证的真实用户行为。

## 验证

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted static/code inspection | pending | 接线和数据模型一致性 | 真实网络/Agent 行为 |
| focused unit/integration | pending | 受影响模块回归 | 真实 OpenClaw 用户链路 |
| MCP stdio probe | pending | Tool schema/进程可启动 | 平台可用性与 Agent 决策 |
| real OpenClaw/user flow | pending | 真实用户任务闭环 | — |

## 结果

未完成。
