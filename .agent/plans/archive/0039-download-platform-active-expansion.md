# 0039 — 可实际测试下载平台 Active 接入

- 状态：completed
- 创建日期：2026-08-12
- 完成日期：2026-08-14
- 分支：`codex/growth-resource-taxonomy-rework`
- 优先级：已完成的工程接入切片；真实平台验收继续由 0028 跟踪
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

本计划实施顺序：

1. **Douyin**：已有 Search 与单文件 MP4 Downloader，不依赖 ffmpeg；补 active Inspector、concrete Representation、ProviderSpec 与 exact registration。
2. **Ximalaya**：已有 Search、Inspector 与单文件音频 Downloader；必须把用户选择绑定到具体 track，禁止 album 静默变成第一首。
3. **Bilibili**：已有 Search、Inspector 与 DASH Downloader；解决 Windows ffmpeg 合并依赖后开放 active route。
4. **Anna/LibGen**：不属于本计划最初接入范围；后续已由独立实现接入，并在 0028 真实测试中暴露 Inspect 问题后通过 0049 修复。

本计划只记录工程接入历史；后续真实平台问题不把 0039 永久保持为 `in_progress`，而是由 0028 记录事实并按问题建立独立修复计划。

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

## Current architecture at completion

- SmartEdu 已在 0038 完成 active exact route。
- Douyin 已形成 concrete MP4 Representation，并 exact 路由到 `douyin-video@1.0.0`。
- Ximalaya 已绑定具体 `track_id`，并 exact 路由到 `ximalaya-audio@1.0.0`。
- Bilibili 已解决 Windows ffmpeg 最终 MP4 合并依赖，并 exact 路由到 `bilibili-video@1.0.0`。
- Active Planner：`mcp/education-resources/src/education_resource_mcp/acquisition/planner.py`。
- Active Provider registry：`mcp/education-resources/src/education_resource_mcp/service.py`。
- Inspector registry：`mcp/education-resources/src/education_resource_mcp/inspection_registry.py`。
- 服务端 Flow、Resolution、Representation、Plan、Job、Outcome、Asset 仍是业务状态权威。

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
- Windows 缺少 ffmpeg 或等价受控合并能力时，应明确阻断；当前部署已具备 ffmpeg 9.0。
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

## Steps

- [x] completed：SmartEdu active 工程链路由 0038 完成并作为参考切片归档。
- [x] completed：确定下一批实现顺序和明确排除项；停止 Coding Agent 代做 OpenClaw 验收。
- [x] completed：实现 Douyin concrete Representation、exact Provider route 与定向测试。
- [x] completed：实现 Ximalaya concrete track Representation、exact Provider route 与定向测试。
- [x] completed：处理 Bilibili Windows 最终 MP4 合并依赖——本地已安装 ffmpeg 9.0（在 PATH），Bilibili DASH 合并可执行；接入 active bilibili-video provider。
- [x] completed：更新平台契约/架构说明，并交付用户真实测试步骤。
- [x] completed：工程接入范围收口；真实平台反馈继续由 0028 跟踪，并按具体问题建立独立修复计划。

## Milestone checkpoint

```text
Original goal still unchanged?: yes
Non-goals still respected?: yes
New abstraction introduced?: no
New source of truth introduced?: no
Fallback added?: no
Real OpenClaw validation owner?: user
Scope drift detected?: no
```

## Result

0039 的平台工程接入目标已经完成。后续真实可用性不由本计划声明：用户在 0028 中继续执行 OpenClaw/真实平台验收；任何失败都以真实阶段和错误事实建立独立修复计划。