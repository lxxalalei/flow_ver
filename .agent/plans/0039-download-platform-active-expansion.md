# 0039 — 可实际测试下载平台 Active 接入

- 状态：in_progress
- 创建日期：2026-08-12
- 完成日期：未完成
- 分支：`codex/growth-resource-taxonomy-rework`
- 优先级：当前唯一工程主线
- 关联验收：[`0028 Real OpenClaw and Real Platform E2E`](0028-real-openclaw-platform-e2e.md)，由用户执行真实 OpenClaw/平台测试

## Objective

在 SmartEdu 之后，把仓库中已经存在下载实现的平台接入 active 获取链，让用户能够在 Windows OpenClaw 中亲自执行真实测试：

```text
Search
  -> Inspect concrete Representation
  -> ProviderSpec
  -> exact Provider
  -> Plan
  -> 用户确认
  -> Job / Outcome / Asset
```

工程交付必须形成真实可达的 active route，不能只停留在 Downloader 文件、Registry 历史字段、fixture 或文档声明。

## Priority

当前实现顺序：

1. **Douyin**：已有 Search 与单文件 MP4 Downloader，不依赖 ffmpeg；补 active Inspector、concrete Representation、ProviderSpec 与 exact registration。
2. **Ximalaya**：已有 Search、Inspector 与单文件音频 Downloader；必须把用户选择绑定到具体 track，禁止 album 静默变成第一首。
3. **Bilibili**：已有 Search、Inspector 与 DASH Downloader；Windows 当前缺 ffmpeg，先完成链路设计与依赖显式失败，待可用合并路径后开放真实成功声明。
4. **Anna/LibGen**：不列入本阶段 active 下载接入；保持 Search/metadata Inspect，避免镜像自动切换、挑战页或书目 MD5 被误报为 concrete primary。

优先级是为了减少用户实际测试前的工程缺口，不要求下一会话重新进行全平台泛化审计。若实现证据推翻上述顺序，应在本计划 Decision log 中用具体代码/运行事实调整，而不是停留在讨论。

## Non-goals

- 不替用户执行 Windows OpenClaw 真实验收、真实下载、Archive 或凭据导入。
- 不恢复 Capability Descriptor、Readiness、Eligibility 或多层 digest authority。
- 不增加 generic/platform fallback，不按平台名隐式切换 Provider。
- 不把 Downloader 可导入、fixture 通过或下载 URL 可解析单独解释为成功能力。
- 不重构无关 Search、Archive、Library、legacy 或 session-manager 架构。
- 不新建通用 Provider framework、resolver framework 或第二套业务状态权威。

## Business invariants

- Inspector 只有在当前平台事实证明一个具体主资源可获取时，才产生：
  `primary_resource + primary + available + materializable=true`。
- Representation 必须绑定平台稳定资源事实；Start 重新获取平台事实并拒绝资源漂移。
- Plan 只执行保存的 exact Provider；失败后不切 generic、其他平台、scope 或 strategy。
- 有副作用调用继续执行 `prepare -> 用户确认 -> start`，不得自动确认。
- Tool/错误/日志不得暴露 Cookie、Token、动态下载 URL、Header、响应体或本地路径。
- ready Asset 必须非空且真实格式与声明一致；HTML/挑战页不能伪装为 MP4、MP3 或 M4A。

## Current architecture

- SmartEdu 已在 0038 完成 active exact route，作为接入模式参考，但新平台不得复用其私有 HTTP/Representation 绑定字段。
- Active Planner：`mcp/education-resources/src/education_resource_mcp/acquisition/planner.py`。
- Active Provider registry：`mcp/education-resources/src/education_resource_mcp/service.py`。
- Inspector registry：`mcp/education-resources/src/education_resource_mcp/inspection_registry.py`。
- 平台实现：
  - Douyin：`adapters/douyin.py`、`adapters/douyin_download.py`；当前无 active Inspector。
  - Ximalaya：`adapters/ximalaya.py`、`adapters/inspect_ximalaya.py`、`adapters/ximalaya_download.py`；当前 audio Representation 不可物化。
  - Bilibili：`adapters/bilibili.py`、`adapters/inspect_bilibili.py`、`adapters/bilibili_download.py`；当前 video Representation 不可物化，Downloader 依赖 ffmpeg。
- 服务端 Flow、Resolution、Representation、Plan、Job、Outcome、Asset 仍是业务状态权威。

## Expected change surface

Likely to change per platform slice:

- 对应 Search/Inspector/Downloader Adapter；
- `inspection_registry.py` 与 platform registry（仅新增真实 Inspector 时）；
- `acquisition/planner.py`；
- `service.py`；
- 直接相关 Schema（仅实际新增 container 时）；
- 每个平台独立的 acquisition tests；
- `contracts/platforms/README.md`、`CURRENT_ARCHITECTURE.md`。

Should not change:

- `legacy/`；
- MCP Tool 数量与两阶段确认协议；
- Archive 只接受 `asset_id` 的边界；
- SmartEdu 私有 planned Representation 注入，除非抽取确有两个已实现用例且先完成复杂度举证；
- 用户预先存在的 `.openclaw-test/pytest-tmp/`。

## Acceptance criteria

### AC-01 — Douyin

- Inspect 使用当前 detail 事实生成具体 MP4 primary，并绑定 `aweme_id` 与平台返回的稳定视频事实。
- Planner exact 选择 `douyin-video@1.0.0 / direct_file / primary_resource`。
- Active Service 精确注册 Douyin Provider；Start 重验绑定事实；无 generic fallback。
- 内容不是 MP4、详情不可用或资源漂移时结构化失败且不产生 ready Asset。

### AC-02 — Ximalaya

- 用户选择必须对应具体 `track_id`；album 候选不得在 Start 时静默改成第一首。
- Inspect 解析当前可获取音频格式后才生成 MP3/M4A concrete primary。
- Planner 与 Service exact 接入 `ximalaya-audio@1.0.0`，Start 重验 track/container。
- 不可用或内容签名不匹配时显式失败。

### AC-03 — Bilibili

- 只有能产生包含音视频的可验证最终 MP4 时才开放 materializable primary。
- Windows 缺少 ffmpeg 或等价受控合并能力时，应在 Prepare 前保持不可规划或在依赖检查中明确阻断，不能先承诺成功再在 Job 中意外失败。
- exact route 不使用 generic fallback。

### AC-04 — 用户可测试交付

- 每个平台提供最短真实测试说明：需要的会话前置、示例自然语言、预期确认点、成功/失败状态。
- Coding Agent 只运行与 diff 匹配的离线/子系统验证；真实 Windows OpenClaw 平台测试由用户执行并把结果记录到 0028。


## 用户真实测试步骤（AC-04 交付，2026-08-12）

测试入口：Windows OpenClaw 启动 education-resources MCP 后，用自然语言发起需求。
Coding Agent 不代跑真实下载；真实结果由用户记录到 0028。

### Douyin（`douyin-video@1.0.0`，direct_file / primary_resource / video / mp4）

- 会话前置：MCP 已启动；Douyin 详情核验走 a_bogus 签名 detail API，需要可用的 Douyin 登录态（与 `douyin_download` 同源）。无登录态时 Inspect 应结构化失败，不得误报可获取。
- 示例自然语言：`帮我在抖音搜索<主题/关键词>的视频，先搜索不要下载。`；候选审查后：`查看这条视频能否下载，然后生成下载计划。`
- 预期确认点：Search 返回候选 → Inspect 展示具体 MP4 可获取（materializable）→ Prepare 生成 Plan（exact `douyin-video@1.0.0`）→ 用户明确确认 → Start → Job `succeeded`。
- 成功状态：Job succeeded，产生非空 MP4 Asset（格式与声明一致），可 Archive。
- 失败状态：详情不可用、非 MP4 内容或绑定事实漂移 → 结构化失败，不产生 ready Asset；无 generic fallback。

### Ximalaya（`ximalaya-audio@1.0.0`，direct_file / primary_resource / audio / mp3|m4a）

- 会话前置：MCP 已启动；Inspect 解析具体 `track_id`（`/sound/{id}` 或显式元数据）后调用 signed baseInfo API 核验可播放音频流。
- 示例自然语言：`帮我在喜马拉雅搜索<主题>的音频节目。`；选到具体一集后：`下载这一集，先生成下载计划。`
- 预期确认点：候选绑定具体 `track_id` → Inspect 展示可获取的 MP3/M4A primary → Prepare 生成 Plan（exact `ximalaya-audio@1.0.0`）→ 用户确认 → Start → Job `succeeded`。
- 成功状态：Job succeeded，产生非空 MP3/M4A Asset。
- 失败状态：album 级候选不会静默变成第一首；track 不可用或内容签名不匹配 → 显式失败；无 generic fallback。

## Worker strategy

下一会话应主动并行使用子 Agent，但写入必须隔离：

- `terra_worker`：每个平台一个跨层实现任务，负责 Inspector → ProviderSpec → Provider → lifecycle 的完整 slice；使用独立 worktree。
- `luna_worker`：契约/fixture/定向测试、文档表格、Windows 依赖检测等边界清晰任务；使用独立 worktree。
- 根 Agent：冻结每个平台 Acceptance Criteria、选择合并顺序、复核 diff、解决冲突并运行最终定向验证。

不要给所有子 Agent 继承完整历史。任务描述应包含平台目标、文件所有权、禁止范围、验收标准和测试命令；使用 `fork_turns="none"`，显式选择 `terra_worker` 或 `luna_worker`。

建议首轮并行：

1. `terra_worker`：Douyin 完整 active slice；
2. `terra_worker`：Ximalaya concrete track slice；
3. `luna_worker`：为两者整理 fixture、契约与测试缺口，但不修改与前两者相同文件；
4. 主 Agent：审查 Bilibili Windows 合并依赖，只产出是否进入下一轮的明确决策，不做泛化审计。

## Validation plan

每个平台按 Level 2 验证：

- 直接相关 Inspector、Planner、Service registry 与 Provider 单元/集成测试；
- 资源漂移、no fallback、平台失败、取消、内容签名和临时文件清理；
- Python `compileall`；
- JSON Schema/contract parse（若修改契约）；
- `git diff --check`。

不默认运行全仓回归；不由 Coding Agent 执行真实 OpenClaw 下载。

## Complexity exceptions

默认：无。

如果要抽取跨平台 planned-binding 或 HTTP client，必须先证明至少两个正在实现的平台确实需要同一语义，并在本计划中填写完整复杂度举证；不得为了未来平台预先泛化。

## Steps

- [x] completed：SmartEdu active 工程链路由 0038 完成并作为参考切片归档。
- [x] completed：确定下一批实现顺序和明确排除项；停止 Coding Agent 代做 OpenClaw 验收。
- [x] completed：实现 Douyin concrete Representation、exact Provider route 与定向测试。
- [x] completed：实现 Ximalaya concrete track Representation、exact Provider route 与定向测试。
- [x] completed：处理 Bilibili Windows 最终 MP4 合并依赖——本地已安装 ffmpeg 9.0（在 PATH），Bilibili DASH 合并可执行；接入 active bilibili-video provider。
- [x] completed：更新平台契约/架构说明（`contracts/platforms/README.md` 路由表同步），并在本计划交付用户真实测试步骤。
- [ ] pending：根据用户在 0028 中的实际测试结果修复真实平台问题。

## Milestone checkpoint

```text
Original goal still unchanged?: yes — 继续接入用户可实际测试的下载平台
Non-goals still respected?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Real OpenClaw validation owner?: user
Scope drift detected?: previous Agent-side OpenClaw verification and authorization review have been stopped
```
