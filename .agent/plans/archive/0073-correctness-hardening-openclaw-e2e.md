# 0073 — Correctness hardening 与真实 OpenClaw 验收

- 状态：completed
- 创建日期：2026-08-26
- 完成日期：2026-08-26
- 范围：`mcp/education-resources/`、`.agent/plans/` 与真实 OpenClaw 用户链路
- 阻塞：~~当前执行环境只有 GitHub 仓库连接~~ **2026-08-26 已解除**：本地 Windows 环境（网关 18789、包 venv、SearXNG 8888、ffmpeg/node）具备完整运行时，聚焦 pytest、stdio probe 与真实 Agent 用户链路已实际执行（见「验证」）。

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
- [x] AC-09：聚焦 pytest / stdio / real OpenClaw 已在本地 Windows 环境实际执行（见「验证」与「真实测试发现」）。

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
- [x] completed：本地 Windows 环境实际运行聚焦 pytest / MCP stdio / 真实 OpenClaw E2E（278 passed + 5 agent 任务闭环），并修复真实测试暴露的 6 个额外问题。

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

## 验证（2026-08-26 本地 Windows 实际执行）

| Validation | Result | What it proves | What it does NOT prove |
| --- | --- | --- | --- |
| targeted static/code inspection | completed | 修改接线与数据模型和审查问题一一对应 | — |
| focused unit/integration | completed: 28 passed + 4 subtests（0073 回归集 + download_resume + mcp_stdio） | 本轮回归点全部通过 | 真实网络/Agent 行为 |
| MCP stdio probe | completed: 12 tools（stdio 与 gateway probe 一致）；B站导入→下载 34.6MB MP4；CCTV 栏目展开 11 视频 + 下载 2×330MB 完整节目；CCTV 2026 短片 12.9MB（native+wasm 双路校验，ffmpeg 体检 100）；Generic zip 12.5MB 与 Content-Length 完全一致；Archive taxonomy 归档 + manifest；Job 分页/选择下载/partial 拒绝守卫 | Tool 进程启动、schema、真实平台机械链路 | 完整用户语义链路 |
| real OpenClaw/user flow | completed: 5 个 `openclaw agent` 任务（Generic Web + html_design 双主题设计；CCTV 导入→下载；LibGen 8 候选→18MB PDF 未触发登录；SmartEdu AUTH_REQUIRED→登录指引；部署后 ximalaya webtk 修复复验） | 真实用户任务闭环通过 release gate | 全平台 100% 覆盖 |
| full regression | completed: 278 passed + 1 skipped + 56 subtests | release 级跨切面回归 | — |

## 真实测试发现的额外修复（同一轮）

1. **喜马拉雅专辑展开**：`getTracksList` 平台新增 webtk 要求（ret=407"webtk缺失"）——原本报笼统「响应结构异常」且永远失败。修复：`ximalaya_expand` 解析 ret/msg 显式报 AUTH_REQUIRED（含 webtk 指引），并贯通 `session_cookie`（保存的浏览器会话 Cookie 随请求发送）。track 下载用保存会话实测成功（8.4MB M4A）。
2. **Zjer 登录墙**：课程详情 API 返回 HTTP 200 + JSON code 402「登录不存在」——原本被笼统「返回失败」掩盖且 session 注册表标记 zjer 为 not_required。修复：`fetch_course_detail` 解析 code 402→AUTH_REQUIRED；zjer 改为 cookie 平台（`cookie_domains=("zjer.cn",)`）；search/expand/inspect/download 全部贯通会话 Cookie（共享 `sessions.session_cookie`）。
3. **SmartEdu inspector landing 门**：课程详情 API（带 token）是权威事实，但 `_PlatformWebInspector` 先抓 landing page，landing 被登录墙挡住就报 AUTH_REQUIRED，detail 永不尝试。修复：`SmartEduInspector._enrich_payload` 无条件先取 detail，成功即 resolved/available 并清除 landing 失败；用户重捕获会话后课程检查实测 resolved（1 主视频 + 5 附件）。
4. **资源类型词汇表截断**：`_ALLOWED_RESOURCE_TYPES` 不含容器类型，CCTV column / B站 creator / 喜马拉雅 album / SmartEdu textbook 等导入后被静默归一化成 `other`。修复：补全 creator/collection/album/textbook/column/series/track。
5. **Import 回填覆盖容器类型**：inspect 未解析成功时（如 zjer 课程 URL 无 video 身份）会把分类器的 course 类型覆盖成 video。修复：只有 `status == "resolved"` 的检查才回填 title/resource_type。
6. **测试 harness Windows 编码**：两个 stdio 测试在中文 Windows 上按 GBK 读子进程 UTF-8 输出崩溃。修复：`encoding="utf-8", errors="replace"`。

## 剩余真实平台风险（非本轮代码缺陷）

- SmartEdu 教材 CDN 分片（`s-file-2.../national_lesson/teachingmaterials/`）匿名与带 token 均 403——疑似 CDN 主机退役或 IP/UA 风控；课程 detail 路径已可用。
- 喜马拉雅 `getTracksList` webtk 为页面 JS 挑战产物（极验类），登录会话也不含 webtk，专辑展开对所有人当前不可用；track 单集下载可用。
- B站 creator 高频分页展开约 30 条后触发 HTTP 412 风控（partial + NETWORK_BLOCKED 诚实上报）。
- zjer 需要浏览器登录捕获后课程链路才可用（本次用户跳过捕获）。
- bilibili/douyin 下载与抖音搜索需要浏览器会话捕获（本次未捕获）。

## 结果

静态审查确认的问题全部落到 active source 并已在本地 Windows 真实环境执行验证：聚焦/全量 pytest 全绿（278 passed + 1 skipped + 56 subtests），12 个 Tool 的 stdio 与 gateway probe 一致，5 个真实 Agent 用户任务闭环通过，真实平台测试又暴露并修复 6 个正确性问题（其中 3 个平台回归 + 2 个数据保真/类型问题 + 1 个测试 harness 问题）。真实 OpenClaw 用户链路 release gate 已实际通过；剩余风险为平台侧变化（CDN/反爬/登录墙），均按真实原因显式暴露。
