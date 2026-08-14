# 0028 — 用户执行的 Windows OpenClaw / 真实平台验收

- 状态：in_progress
- 创建日期：2026-08-08
- 更新日期：2026-08-14
- 完成日期：未完成
- 负责人：用户执行真实 Windows OpenClaw 与平台测试；Coding Agent 只根据用户反馈修复代码和记录结果
- 工程接入历史：[`0039 可实际测试下载平台 Active 接入`](archive/0039-download-platform-active-expansion.md) 已完成；当前真实验收由本计划直接跟踪

## Objective

记录用户在 Windows OpenClaw 中对 active 平台的实际测试结果，并把真实失败反馈到独立修复计划。

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
- 每个真实问题按需建立独立修复计划，避免让平台扩展计划永久保持 `in_progress`；
- 修复后运行与 diff 匹配的离线/子系统测试，并给出复测步骤。

## Business invariants

- 只有 active `Representation -> ProviderSpec -> exact Provider` 路线才进入 Prepare/Start。
- 所有下载继续采用 `prepare -> 用户明确确认 -> start`。
- 失败后不切 generic Provider、其他平台、scope 或 strategy。
- Tool/错误/记录不包含 Cookie、Token、动态下载 URL、Header、响应体或本地路径。
- 未产生 ready Asset 时不得记录为下载成功；fixture 或环境检查不得标记平台实际可用。

## Current test queue

建议按最能暴露当前真实链路问题的顺序执行，不要求一次性覆盖全部平台：

1. **Anna's Archive 复测**：Search 已真实返回候选；0049 已修复 Inspect 误访问合成详情页导致的 403/AUTH_REQUIRED，当前优先确认 Inspect → Prepare 是否恢复。
2. **Shuge**：Search 已能得到公开存储 `/d/` 文件候选，Inspect 与 `shuge -> generic-direct@1.0.0` 路由已接入；等待真实 Search → Inspect → Prepare → Start → Asset。
3. **Yixi / 一席**：真实样本 `speech_id=1435`《教育就是生长》已确认 `play_detail` 返回标清/高清公开 MP4；0051 已接入 Search 解析最高可用 MP4、YixiInspector 与 `yixi -> generic-direct@1.0.0` 路由。优先用该样本跑真实闭环。
4. **Bilibili**：active `bilibili-video@1.0.0`，Windows ffmpeg 合并依赖已具备；等待真实视频下载闭环。
5. **SmartEdu**：PDF、direct MP4、MP3、M4A active route 已完成工程接入；等待真实闭环。
6. **Douyin**：active `douyin-video@1.0.0`；需要可用登录态时应显式暴露认证事实。
7. **Ximalaya**：active `ximalaya-audio@1.0.0`；重点验证具体 track 绑定，不允许 album 静默变成第一首。

Generic Web materialize 可作为网页资源独立验收，但不要求与平台下载队列绑定在同一次测试中。

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
- [x] completed：2026-08-14 用户反馈 Anna's Archive Inspect 全量失败；已定位并按归档计划 [`0049`](archive/0049-annas-metadata-inspection.md) 修复。
- [x] completed：2026-08-14 用户提供一席 1435 的真实 `play_detail` 响应；0051 已按实际静态公开 MP4 数据模型接入可测试获取链。
- [ ] in_progress：用户复测 Anna's Archive，并按队列继续选择 Shuge/Yixi/Bilibili/SmartEdu 等至少一个平台完成真实闭环。
- [ ] pending：对后续真实失败建立独立修复计划并记录复测结果。
- [ ] pending：至少一个平台完成用户选择、确认、下载并产生正确 ready Asset 后记录成功证据。

## Completion criteria

- 至少一个 active 平台由用户在 Windows OpenClaw 中完成真实下载并得到正确 ready Asset；
- 所有副作用经过用户明确确认；
- 失败没有被 fallback 或伪造成功掩盖；
- 用户报告的问题已进入独立工程修复计划并完成必要复测。

## Current result

### 2026-08-14 — Anna's Archive 电子书：Inspect 全量失败（已修复，待复测）

```text
Date/time: 2026-08-14
Platform: annas-archive（Libgen-backed）
User request: 下载《毛选》类电子书
Reached stage: Search 正常返回 13 个候选；Inspect 全部失败，Prepare 被拒
Observed status or error code: 检查提示“需要授权”（AUTH_REQUIRED，检查结果未通过）
Expected behavior: 匿名 Libgen 通道应可检查并进入下载准备
Actual behavior: Inspect 对合成详情页 annas-archive.gl/md5/<md5> 发起 GET，
  该站点风控返回 403，被归类为 AUTH_REQUIRED，13 个候选全部阻塞；
  而真实下载通道（libgen.bz / libgen.gl 匿名 md5）从未被检查环节使用
Sensitive values removed: yes
```

定位：检查通道与获取通道错位。`AnnasArchiveInspector` 继承
`PlatformBoundedInspector` 的 bounded GET，检查对象是搜索适配器合成的
`annas-archive.gl/md5/<md5>` 身份页；该页既非数据源（Libgen 镜像）也非下载
通道（Libgen 镜像），其风控否决了整条链路。

修复：归档计划 [`0049`](archive/0049-annas-metadata-inspection.md)。合法 md5 资源的检查改为
纯元数据通道（`inspection.method=platform_metadata`），零网络请求；planner
命中 `annas-archive@1.0.0 / direct_file`。下载失败继续在 Job 层按项结构化
暴露。Level 2 定向验证通过；等待用户复测真实链路。

SmartEdu、Douyin、Ximalaya、Bilibili、Anna's Archive、Shuge 与 Yixi 均已有工程获取路线；是否真实 production-ready 仍以本计划中的用户 OpenClaw 结果为准。