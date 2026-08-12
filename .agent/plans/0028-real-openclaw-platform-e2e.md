# 0028 — 用户执行的 Windows OpenClaw / 真实平台验收

- 状态：in_progress
- 创建日期：2026-08-08
- 更新日期：2026-08-12
- 完成日期：未完成
- 负责人：用户执行真实 Windows OpenClaw 与平台测试；Coding Agent 只根据用户反馈修复代码和记录结果
- 工程主线：[`0039 可实际测试下载平台 Active 接入`](0039-download-platform-active-expansion.md)

## Objective

记录用户在 Windows OpenClaw 中对 active 平台的实际测试结果，并把真实失败反馈给工程主线修复。

fixture、单元测试、MCP doctor/probe、Provider 注册或 Downloader 文件存在都不能代替用户的实际平台测试。

## Scope

用户按自己选择的平台执行：

```text
自然语言需求
  -> Search
  -> Inspect
  -> Present
  -> Select
  -> Prepare
  -> 用户确认
  -> Start
  -> JobStatus
  -> Asset / Bundle
  -> 可选 Archive / Recover
```

Coding Agent：

- 不主动替用户运行 OpenClaw 验收；
- 不主动重启 Windows gateway；
- 不主动执行真实平台下载或 Archive；
- 根据用户提供的真实输出定位并修复 active 代码；
- 修复后运行与 diff 匹配的离线/子系统测试，并给出复测步骤。

## Business invariants

- 只有 active `Representation -> ProviderSpec -> exact Provider` 路线才进入 Prepare/Start。
- 所有下载继续采用 `prepare -> 用户明确确认 -> start`。
- 失败后不切 generic Provider、其他平台、scope 或 strategy。
- Tool/错误/记录不包含 Cookie、Token、动态下载 URL、Header、响应体或本地路径。
- 未产生 ready Asset 时不得记录为下载成功；fixture 或环境检查不得标记平台实际可用。

## Current test queue

1. SmartEdu：PDF、direct MP4、MP3、M4A active route 已由 0038 完成工程接入，等待用户实际测试。
2. Douyin：由 0039 实现 active route 后进入用户测试。
3. Ximalaya：由 0039 实现具体 track active route 后进入用户测试。
4. Bilibili：由 0039 解决最终 MP4 产出依赖后决定是否进入用户测试。

## Result record template

用户反馈只需保留定位问题所需的非敏感事实：

```text
Date/time:
Platform:
User request:
Reached stage: Search / Inspect / Prepare / Start / Job / Asset / Archive
Observed status or error code:
Expected behavior:
Actual behavior:
Sensitive values removed: yes/no
```

不要要求用户重复跑与问题无关的 doctor/probe 或全量环境检查。优先根据实际失败阶段定位。

## Steps

- [x] completed：历史真实 OpenClaw 调查和失败记录已保留在 Git 历史与归档计划中。
- [x] completed：2026-08-12 明确真实验收由用户执行，Coding Agent 停止代跑 OpenClaw。
- [ ] in_progress：用户测试 SmartEdu active route，并反馈第一个真实结果。
- [ ] pending：用户测试 0039 后续接入的平台。
- [ ] pending：Coding Agent 根据真实反馈修复并更新本计划结果。
- [ ] pending：至少一个平台完成用户选择、确认、下载并产生正确 ready Asset 后记录成功证据。

## Completion criteria

- 至少一个 active 平台由用户在 Windows OpenClaw 中完成真实下载并得到正确 ready Asset；
- 所有副作用经过用户明确确认；
- 失败没有被 fallback 或伪造成功掩盖；
- 用户报告的问题已进入 0039 或后续明确工程计划。

## Current result

SmartEdu、Douyin、Ximalaya、Bilibili 的 active exact route 均已完成工程接入；用户尚未执行真实平台验收。
0039 当前只根据用户真实测试反馈修复平台问题。本计划不把任何离线验证解释为真实平台通过。
